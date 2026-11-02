// SPDX-License-Identifier: GPL-3.0-or-later
#include "eden_services.h"
#ifdef PS5_NATIVE
#include "ps5_profile_avatar_staging.hpp"
#endif

#include "assets_dir.h"
#include "ns2_title_catalog.h"
#include "crash_report.h"
#ifdef PS5_NATIVE
#include "boot_trace.h"
#include "log_pipe.h"
#include "performance.h"
#endif
#include "diagnostics.h"
#include "encore_overrides_runtime.h"
#include "metadata_bridge.h"
#include "title_id_fallback.h"
#include "mods.h"
#include "native_directory.h"
#include "pe/core/strings.hpp"
#include "pe/gfx/image.hpp"
#include "common/net/net.h"
#include "network_audit.h"
#include "radio_input.h"
#include "settings_store.h"
#include "version.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <ctime>
#include <dirent.h>
#include <exception>
#include <fcntl.h>
#include <filesystem>
#include <fstream>
#include <future>
#include <initializer_list>
#include <mutex>
#include <optional>
#include <nlohmann/json.hpp>
#include <stb_image.h>
#include <sys/stat.h>
#include <system_error>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <unistd.h>

#ifdef PS5_NATIVE
// Resolve the foreground console user's cached image only. This is a
// read-only platform call; no account, PSN, registry or cache modification.
extern "C" int sceUserServiceInitialize(void* params);
extern "C" int sceUserServiceGetForegroundUser(std::int32_t* user_id);
#endif

namespace {

using pe::fill;
using pe::tr;

bool IsFile(const std::string& path) {
    struct stat info {};
    if (lstat(path.c_str(), &info) == 0) return S_ISREG(info.st_mode);
    if (errno != EPERM && errno != EACCES) return false;
    return stat(path.c_str(), &info) == 0 && S_ISREG(info.st_mode);
}

#ifdef PS5_NATIVE
bool IsReadableAvatarFile(const std::string& path) {
    if (!IsFile(path)) return false;
    // stat() can succeed even when a sandboxed title cannot open the
    // privileged cache. Do not choose an unreadable PNG over a valid DDS.
    const int fd = ::open(path.c_str(), O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return false;
    struct stat info{};
    const bool readable = ::fstat(fd, &info) == 0 &&
                          S_ISREG(info.st_mode) && info.st_size >= 128 &&
                          info.st_size <= 4 * 1024 * 1024;
    (void)::close(fd);
    return readable;
}
// Check actual image decodability off the UI thread, not merely stat/open.
// A readable but corrupt PS5 PNG must not shadow the same user's valid DDS.
bool IsDecodableAvatarFile(const std::string& path) {
    if (!IsReadableAvatarFile(path)) return false;
    if (path.ends_with(".dds")) {
        pe::gfx::Image decoded;
        const bool valid = pe::gfx::load_avatar_dds(path, &decoded) && !decoded.empty();
        if (!valid) {
            static std::atomic_flag warned = ATOMIC_FLAG_INIT;
            if (!warned.test_and_set())
                std::fprintf(stderr, "EDEN_PROFILE_AVATAR status=dds_decode_failed\n");
        }
        return valid;
    }
    int width = 0, height = 0, channels = 0;
    const bool header_ok = stbi_info(path.c_str(), &width, &height, &channels) != 0 &&
                           width > 0 && height > 0 && width <= 1024 && height <= 1024;
    stbi_uc* rgba = header_ok ? stbi_load(path.c_str(), &width, &height, &channels, 4) : nullptr;
    const bool valid = rgba != nullptr;
    if (rgba) stbi_image_free(rgba);
    if (!valid) {
        static std::atomic_flag warned = ATOMIC_FLAG_INIT;
        if (!warned.test_and_set())
            std::fprintf(stderr, "EDEN_PROFILE_AVATAR status=png_decode_failed fallback=dds\n");
    }
    return valid;
}

#endif

// Only a deconstructed title's base content counts towards its Library size.
// Its executable 'main' is just one 20-40 MiB NSO; counting that alone makes
// a multi-gigabyte game appear as a 32 MB title. Do NOT add updates or DLC,
// follow symlinks, block on network media, or guess if traversal is incomplete.
// The entire walk runs on the cancellable Library background scan.
std::optional<std::uint64_t> ExtractedBaseBytes(const std::filesystem::path& title,
                                                const std::atomic<bool>* cancel) {
    namespace fs = std::filesystem;
    std::error_code error;
    if (!Eden::IsSafeExtractedDirectory(title)) return std::nullopt;
    fs::recursive_directory_iterator it(title, fs::directory_options::skip_permission_denied, error);
    if (error) return std::nullopt;
    const fs::recursive_directory_iterator end;
    std::uint64_t total = 0;
    std::size_t examined = 0;
    for (; it != end; it.increment(error)) {
        if (error || ++examined > 40000 || it.depth() > 16 ||
            (cancel && cancel->load(std::memory_order_acquire)))
            return std::nullopt;
        const auto status = it->symlink_status(error);
        if (error) return std::nullopt;
        if (fs::is_symlink(status)) {
            it.disable_recursion_pending();
            continue;
        }
        if (fs::is_directory(status)) {
            if (Eden::IsAddOnContainerName(it->path().filename().string()))
                it.disable_recursion_pending();
            continue;
        }
        if (!fs::is_regular_file(status)) continue;
        const auto size = it->file_size(error);
        if (error || size > UINT64_MAX - total) return std::nullopt;
        total += static_cast<std::uint64_t>(size);
    }
    if (error) return std::nullopt;
    return total > 0 ? std::optional<std::uint64_t>{total} : std::nullopt;
}

// Local user-supplied covers are a safe offline fallback for extracted titles
// with no packaged Control NCA or Nlib match. No game-name-specific artwork.
// Read user-supplied Control NACP without NCA keys or external title databases.
// The legacy NACP language table has up to sixteen 0x300-byte records
// (0x200-byte name + 0x100-byte developer). The compressed/extended variant
// is intentionally not guessed. This is metadata-only, never guest authority.
struct ExtractedSidecarMetadata {
    std::string name;
    std::string developer;
};

bool ValidSidecarText(std::string_view value) {
    if (value.empty()) return false;
    for (std::size_t i = 0; i < value.size();) {
        const unsigned char c = static_cast<unsigned char>(value[i]);
        if (c < 0x20 || c == 0x7f) return false;
        if (c < 0x80) { ++i; continue; }
        const std::size_t n = c >= 0xc2 && c <= 0xdf ? 2 :
                              c >= 0xe0 && c <= 0xef ? 3 :
                              c >= 0xf0 && c <= 0xf4 ? 4 : 0;
        if (!n || n > value.size() - i) return false;
        for (std::size_t j = 1; j < n; ++j)
            if ((static_cast<unsigned char>(value[i+j]) & 0xc0u) != 0x80u) return false;
        const auto second = static_cast<unsigned char>(value[i+1]);
        if ((c == 0xe0 && second < 0xa0) || (c == 0xed && second >= 0xa0) ||
            (c == 0xf0 && second < 0x90) || (c == 0xf4 && second >= 0x90)) return false;
        i += n;
    }
    return true;
}
std::string NacpString(const char* bytes, std::size_t capacity) {
    const auto* end = static_cast<const char*>(std::memchr(bytes, '\0', capacity));
    if (!end) return {};
    const std::string value(bytes, end);
    return ValidSidecarText(value) ? value : std::string{};
}
ExtractedSidecarMetadata ExtractedLocalNacp(const std::filesystem::path& title,
                                                  int language_choice) {
    namespace fs = std::filesystem;
    if (!Eden::IsSafeExtractedDirectory(title)) return {};
    // Order matches the existing extracted ExeFS/main layout. Never use
    // update/DLC control data to relabel a base game.
    for (const char* relative : {"control.nacp", "base/control.nacp",
                                 "exefs/control.nacp", "base/exefs/control.nacp"}) {
        fs::path parent = title;
        bool safe = true;
        for (const auto& part : fs::path(relative).parent_path()) {
            parent /= part;
            if (!Eden::IsSafeExtractedDirectory(parent)) { safe = false; break; }
        }
        if (!safe) continue;
        const fs::path candidate = title / relative;
        std::error_code ec;
        const auto status = fs::symlink_status(candidate, ec);
        if (ec || !fs::is_regular_file(status) || fs::is_symlink(status)) continue;
        const auto size = fs::file_size(candidate, ec);
        if (ec || size < 0x3000 || size > 0x20000) continue;
        std::ifstream input(candidate, std::ios::binary);
        if (!input) continue;
        // Map launcher language catalog indices to the 16 uncompressed
        // NACP slots; Polish/Thai use the compressed 18-language variant and
        // correctly fall back to available uncompressed entries instead.
        constexpr std::array<int, 18> to_nacp{
            0,1,3,9,4,7,6,5,10,15,8,11,-1,2,12,14,13,-1
        };
        const int preferred = language_choice >= 0 &&
            static_cast<std::size_t>(language_choice) < to_nacp.size()
            ? to_nacp[static_cast<std::size_t>(language_choice)] : -1;
        constexpr std::array<unsigned, 16> fallback{
            0,1,3,9,2,4,5,6,7,8,10,11,12,13,14,15
        };
        // Preferred language first, then English, French and other populated
        // entries. Never silently impose French on English-speaking users.
        for (std::size_t attempt = 0; attempt < fallback.size() + 1; ++attempt) {
            const unsigned language = attempt == 0 && preferred >= 0
                ? static_cast<unsigned>(preferred)
                : fallback[attempt == 0 ? 0 : attempt - 1];
            if (language >= 16 || (attempt != 0 && preferred >= 0 &&
                                   language == static_cast<unsigned>(preferred)))
                continue;
            std::array<char, 0x300> record{};
            input.clear();
            input.seekg(static_cast<std::streamoff>(language * record.size()));
            if (!input.read(record.data(), record.size())) continue;
            auto name = NacpString(record.data(), 0x200);
            if (name.empty() || name == "Application") continue;
            auto developer = NacpString(record.data() + 0x200, 0x100);
            return {std::move(name), std::move(developer)};
        }
    }
    return {};
}

std::string ExtractedLocalCover(const std::filesystem::path& title) {
    namespace fs = std::filesystem;
    if (!Eden::IsSafeExtractedDirectory(title)) return {};
    // Borrow the upstream loose-ExeFS sidecar discovery contract (Eglantine
    // 4d2cf41837): the game icon may live next to main or in base/exefs.
    // No synthetic thumbnails or fabricated rear art are needed.
    for (const char* relative : {"cover.tga", "cover.png", "cover.jpg", "cover.jpeg",
                                 "icon.tga", "icon.png", "icon.jpg",
                                 "exefs/cover.png", "exefs/cover.jpg",
                                 "exefs/icon.png", "exefs/icon.jpg",
                                 "base/cover.tga", "base/cover.png", "base/cover.jpg",
                                 "base/icon.png", "base/icon.jpg",
                                 "base/exefs/cover.png", "base/exefs/cover.jpg",
                                 "base/exefs/icon.png", "base/exefs/icon.jpg"}) {
        // symlink_status(candidate) does not detect symlinked ancestors.
        // Check each ancestor before reading a user-supplied sidecar.
        fs::path parent = title;
        bool safe = true;
        for (const auto& segment : fs::path(relative).parent_path()) {
            parent /= segment;
            if (!Eden::IsSafeExtractedDirectory(parent)) { safe = false; break; }
        }
        if (!safe) continue;
        const fs::path candidate = title / relative;
        std::error_code error;
        const auto status = fs::symlink_status(candidate, error);
        if (error || !fs::is_regular_file(status) || fs::is_symlink(status)) continue;
        const auto size = fs::file_size(candidate, error);
        if (!error && size >= 128 && size <= (16u << 20)) return candidate.string();
    }
    // Eglantine's loose ExeFS sidecars are often JPEG images named
    // icon_<language>.dat rather than *.jpg. The launcher decodes image
    // CONTENT with stb_image, independently of the extension. Scan only
    // known filenames at bounded depth; never follow symlinked parents.
    constexpr const char* languages[] = {
        "French", "CanadianFrench", "AmericanEnglish", "BritishEnglish",
        "Japanese", "German", "Spanish", "LatinAmericanSpanish", "Italian",
        "Dutch", "Portuguese", "Russian", "Korean", "SimplifiedChinese",
        "TraditionalChinese"
    };
    for (const char* base : {"exefs", "base/exefs", ".", "base"}) {
        const fs::path dir = title / base;
        // Check all ancestors, including base/; symlink_status(final) is not
        // sufficient because it follows symlinked intermediate directories.
        fs::path ancestor = title;
        bool safe = true;
        for (const auto& segment : fs::path(base)) {
            ancestor /= segment;
            if (!Eden::IsSafeExtractedDirectory(ancestor)) { safe = false; break; }
        }
        if (!safe) continue;
        for (const char* language : languages) {
            const fs::path candidate = dir / (std::string("icon_") + language + ".dat");
            std::error_code error;
            const auto status = fs::symlink_status(candidate, error);
            if (error || !fs::is_regular_file(status) || fs::is_symlink(status)) continue;
            const auto size = fs::file_size(candidate, error);
            if (error || size < 128 || size > (16u << 20)) continue;
            // Only JPEG/PNG sidecars. Other binary .dat resources must NOT be
            // handed to the cover decoder as images.
            std::ifstream input(candidate, std::ios::binary);
            char signature[8]{};
            input.read(signature, sizeof(signature));
            if (input.gcount() != static_cast<std::streamsize>(sizeof(signature))) continue;
            const bool jpeg = static_cast<unsigned char>(signature[0]) == 0xff &&
                              static_cast<unsigned char>(signature[1]) == 0xd8;
            const bool png = std::memcmp(signature, "\x89PNG\r\n\x1a\n", 8) == 0;
            if (jpeg || png) return candidate.string();
        }
    }
    return {};
}

std::uint64_t ResolveTitleId(const std::string& path, const std::string& file) {
    const std::uint64_t metadata_id = eden_game_title_id(path.c_str());
    if (metadata_id != 0) return metadata_id;
    const std::uint64_t filename_id = Eden::TitleIdFromRomFilename(file);
    if (filename_id != 0)
        std::fprintf(stderr, "EDEN_TITLE_ID_FALLBACK file=%s title_id=%016llX\n", file.c_str(),
                     static_cast<unsigned long long>(filename_id));
    return filename_id;
}

std::string NlibHeroPath(std::uint64_t title_id) {
    char id[17]{};
    std::snprintf(id, sizeof(id), "%016llX", static_cast<unsigned long long>(title_id));
    return Eden::CoversDir() + "/hero-" + id + ".tga";
}

std::string NlibIconPath(std::uint64_t title_id) {
    char id[17]{};
    std::snprintf(id, sizeof(id), "%016llX", static_cast<unsigned long long>(title_id));
    return Eden::CoversDir() + "/nlib-icon-" + id + ".tga";
}

std::string NlibScreenshotPath(std::uint64_t title_id, int index) {
    char id[17]{};
    std::snprintf(id, sizeof(id), "%016llX", static_cast<unsigned long long>(title_id));
    return Eden::CoversDir() + "/screen-" + id + "-" + std::to_string(index) + ".tga";
}


std::string NlibLanguageCode(int language) {
    language = std::clamp(language, 0, static_cast<int>(std::size(Eden::kLanguageKeys)) - 1);
    std::string key = Eden::kLanguageKeys[static_cast<std::size_t>(language)];
    const std::size_t dash = key.find('-');
    std::string base = dash == std::string::npos ? key : key.substr(0, dash);
    static constexpr const char* supported[] = {
        "en", "ja", "es", "de", "fr", "nl", "pt", "it", "zh", "ko", "ru"};
    for (const char* code : supported)
        if (base == code) return base;
    return "en";
}

std::string NlibMetadataPath(std::uint64_t title_id, const std::string& language) {
    char id[17]{};
    std::snprintf(id, sizeof(id), "%016llX", static_cast<unsigned long long>(title_id));
    return Eden::CoversDir() + "/nlib-" + id + "-" + language + ".json";
}

std::string JoinJsonStrings(const nlohmann::json& value) {
    if (!value.is_array()) return {};
    std::string result;
    for (const auto& item : value) {
        if (!item.is_string()) continue;
        if (!result.empty()) result += " · ";
        result += item.get<std::string>();
    }
    return result;
}

bool AtomicWriteText(const std::string& path, const std::string& body) {
    std::error_code directory_error;
    const std::filesystem::path parent = std::filesystem::path(path).parent_path();
    if (!parent.empty()) std::filesystem::create_directories(parent, directory_error);
    if (directory_error) return false;
    const std::string staged = path + ".new";
    std::FILE* file = std::fopen(staged.c_str(), "wb");
    if (!file) return false;
    const bool written = std::fwrite(body.data(), 1, body.size(), file) == body.size();
    const bool closed = std::fclose(file) == 0;
    if (!written || !closed || std::rename(staged.c_str(), path.c_str()) != 0) {
        (void)std::remove(staged.c_str());
        return false;
    }
    return true;
}

bool WriteJpegTga(const std::string& encoded, const std::string& output,
                  bool tall_case = false) {
    // Read JPEG dimensions BEFORE allocation. Nlib artwork is fetched in
    // parallel, so malformed/oversized JPEGs must not cause a multi-image
    // transient allocation spike on a memory-constrained console.
    if (encoded.empty() || encoded.size() > (16u << 20)) return false;
    int width = 0;
    int height = 0;
    int channels = 0;
    const bool dimensions_read = stbi_info_from_memory(
            reinterpret_cast<const unsigned char*>(encoded.data()),
            static_cast<int>(encoded.size()), &width, &height, &channels);
    const bool standard_oversized = width > 4096 || height > 2160;
    if (!dimensions_read || width <= 0 || height <= 0 ||
        (standard_oversized && !tall_case) ||
        (tall_case && (width > 4096 || height > 4096)) ||
        static_cast<std::uint64_t>(width) * static_cast<std::uint64_t>(height) > 3840u * 2160u)
        return false;

    unsigned char* rgba = stbi_load_from_memory(
        reinterpret_cast<const unsigned char*>(encoded.data()), static_cast<int>(encoded.size()),
        &width, &height, &channels, 4);
    if (!rgba || width <= 0 || height <= 0 || width > 4096 || height > 4096) {
        stbi_image_free(rgba);
        return false;
    }

    std::FILE* file = std::fopen(output.c_str(), "wb");
    if (!file) {
        stbi_image_free(rgba);
        return false;
    }

    // Case scans are unusually tall. Store only the resolution needed by
    // the launcher: uncompressed TGA stays under 13 MiB, even for a 4K source.
    // Normal Nlib images keep their previous pixel-for-pixel behaviour.
    const float scale = tall_case ?
        std::min({1.0f, 1500.0f / width, 2100.0f / height}) : 1.0f;
    const int output_width = std::max(1, static_cast<int>(width * scale));
    const int output_height = std::max(1, static_cast<int>(height * scale));
    unsigned char header[18]{};
    header[2] = 2;
    header[12] = static_cast<unsigned char>(output_width);
    header[13] = static_cast<unsigned char>(output_width >> 8);
    header[14] = static_cast<unsigned char>(output_height);
    header[15] = static_cast<unsigned char>(output_height >> 8);
    header[16] = 32;
    header[17] = 0x28; // top-left origin + 8 alpha bits
    bool ok = std::fwrite(header, 1, sizeof(header), file) == sizeof(header);
    std::vector<unsigned char> row(static_cast<std::size_t>(output_width) * 4);
    for (int y = 0; ok && y < output_height; ++y) {
        const int source_y = y * height / output_height;
        const unsigned char* source = rgba + static_cast<std::size_t>(source_y) *
                                               static_cast<std::size_t>(width) * 4;
        for (int x = 0; x < output_width; ++x) {
            const std::size_t offset = static_cast<std::size_t>(x * width / output_width) * 4;
            row[4 * x + 0] = source[offset + 2];
            row[4 * x + 1] = source[offset + 1];
            row[4 * x + 2] = source[offset + 0];
            row[4 * x + 3] = source[offset + 3];
        }
        ok = std::fwrite(row.data(), 1, row.size(), file) == row.size();
    }
    ok = std::fclose(file) == 0 && ok;
    stbi_image_free(rgba);
    return ok;
}

std::string NlibPlayersPath(std::uint64_t title_id) {
    char id[17]{};
    std::snprintf(id, sizeof(id), "%016llX", static_cast<unsigned long long>(title_id));
    return Eden::CoversDir() + "/players-" + id + ".txt";
}

// Nlib JPEGs are converted into uncompressed BGRA TGA before being cached.
// A filename alone is not sufficient: incomplete/old files previously showed
// permanently empty tiles and prevented download retries. Validate the header
// and complete payload without allocating or decoding image buffers.
bool ValidNlibTga(const std::string& path) {
    struct stat info{};
    if (stat(path.c_str(), &info) != 0 || !S_ISREG(info.st_mode) ||
        info.st_size < 18) return false;
    std::FILE* file = std::fopen(path.c_str(), "rb");
    if (!file) return false;
    unsigned char header[18]{};
    const bool readable = std::fread(header, 1, sizeof(header), file) == sizeof(header);
    std::fclose(file);
    if (!readable || header[1] != 0 || header[2] != 2 || header[16] != 32)
        return false;
    const unsigned width = static_cast<unsigned>(header[12]) |
                           (static_cast<unsigned>(header[13]) << 8);
    const unsigned height = static_cast<unsigned>(header[14]) |
                            (static_cast<unsigned>(header[15]) << 8);
    if (width == 0 || height == 0 || width > 4096 || height > 2160 ||
        static_cast<std::uint64_t>(width) * height > 3840u * 2160u)
        return false;
    const std::uint64_t bytes = 18u + header[0] +
        static_cast<std::uint64_t>(width) * height * 4u;
    return static_cast<std::uint64_t>(info.st_size) >= bytes;
}

std::string CachedNlibHero(std::uint64_t title_id) {
    if (title_id == 0) return {};
    const std::string path = NlibHeroPath(title_id);
    return ValidNlibTga(path) ? path : std::string{};
}

int CachedNlibPlayers(std::uint64_t title_id) {
    if (title_id == 0) return 0;
    std::FILE* file = std::fopen(NlibPlayersPath(title_id).c_str(), "rb");
    if (!file) return 0;
    int players = 0;
    const int read = std::fscanf(file, "%d", &players);
    (void)std::fclose(file);
    return read == 1 && players > 0 && players <= 16 ? players : 0;
}

void CacheNlibPlayers(std::uint64_t title_id, int players) {
    if (title_id == 0 || players <= 0 || players > 16) return;
    (void)mkdir(Eden::CoversDir().c_str(), 0777);
    const std::string path = NlibPlayersPath(title_id);
    const std::string staged = path + ".new";
    std::FILE* file = std::fopen(staged.c_str(), "wb");
    if (!file) return;
    const bool written = std::fprintf(file, "%d\n", players) > 0;
    const bool closed = std::fclose(file) == 0;
    if (!written || !closed || std::rename(staged.c_str(), path.c_str()) != 0)
        (void)std::remove(staged.c_str());
}

constexpr int kNlibCacheSchema = 3; // v3 persists artwork refresh epochs

struct NlibEnrichment {
    bool artwork_changed = false; // a cached image was replaced
    std::string icon;
    std::string hero;
    std::vector<std::string> screenshots;
    int max_players = 0;
    std::string name;
    std::string intro;
    std::string description;
    std::string publisher;
    std::string developer;
    std::string release_date;
    std::string categories;
};

std::string CachedNlibIcon(std::uint64_t title_id) {
    if (title_id == 0) return {};
    const std::string path = NlibIconPath(title_id);
    return ValidNlibTga(path) ? path : std::string{};
}

std::vector<std::string> CachedNlibScreens(std::uint64_t title_id) {
    std::vector<std::string> screens;
    if (title_id == 0) return screens;
    for (int index = 1; index <= 3; ++index) {
        const std::string path = NlibScreenshotPath(title_id, index);
        if (ValidNlibTga(path)) screens.push_back(path);
    }
    return screens;
}

bool LoadNlibMetadata(std::uint64_t title_id, const std::string& language, nlohmann::json* out) {
    if (out == nullptr) return false;
    std::ifstream file(NlibMetadataPath(title_id, language), std::ios::binary);
    if (!file) return false;
    try {
        file >> *out;
        return out->is_object();
    } catch (...) {
        return false;
    }
}

void ApplyNlibMetadata(const nlohmann::json& json, NlibEnrichment* result) {
    if (result == nullptr || !json.is_object()) return;
    const auto string_value = [&](const char* key) -> std::string {
        const auto it = json.find(key);
        return it != json.end() && it->is_string() ? it->get<std::string>() : std::string{};
    };
    result->name = string_value("name");
    result->intro = string_value("intro");
    result->description = string_value("description");
    result->publisher = string_value("publisher");
    result->developer = string_value("developer");
    result->release_date = string_value("releaseDate");
    result->categories = json.contains("category") ? JoinJsonStrings(json["category"]) : std::string{};
    const auto players_it = json.find("numberOfPlayers");
    const int players = players_it != json.end() && players_it->is_number_integer() ?
        players_it->get<int>() : 0;
    if (players > 0 && players <= 16) result->max_players = players;
}

bool CacheNlibJpeg(const std::string& endpoint, const std::string& path,
                   std::size_t minimum_bytes = 1024,
                   const std::atomic<bool>* cancel = nullptr) {
    // Cancellation avoids new network requests and expensive JPEG/PNG-to-TGA
    // conversion; an HTTP request already in flight must time out naturally.
    if (cancel && cancel->load(std::memory_order_acquire)) return false;
    const auto response = Common::Net::MakeRequest("https://api.nlib.cc", endpoint);
    if (!response || (cancel && cancel->load(std::memory_order_acquire)))
        return false;
    const std::string& body = *response;
    const bool jpeg = body.size() >= 2 &&
        static_cast<unsigned char>(body[0]) == 0xff &&
        static_cast<unsigned char>(body[1]) == 0xd8;
    const bool png = body.size() >= 8 &&
        std::memcmp(body.data(), "\x89PNG\r\n\x1a\n", 8) == 0;
    // stb_image decodes both; reject unexpected HTML/error responses instead
    // of persisting them as permanently broken thumbnails.
    if (body.size() < minimum_bytes || body.size() > (16u << 20) || (!jpeg && !png))
        return false;
    if (cancel && cancel->load(std::memory_order_acquire)) return false;
    (void)mkdir(Eden::CoversDir().c_str(), 0777);
    const std::string staged = path + ".new";
    if (WriteJpegTga(body, staged) && std::rename(staged.c_str(), path.c_str()) == 0)
        return true;
    (void)std::remove(staged.c_str());
    return false;
}

// Optional real retail case images from the build-time filtered public catalog.
// No full metadata archive, credentials, HTTP or XML parsing on the console.
// Matching is exact and skips colliding release editions at index-generation time.
using BoxIndex = std::unordered_map<std::string, std::array<std::vector<std::string>, 6>>;

std::string CaseKey(const std::string& title) {
    std::string key;
    key.reserve(title.size());
    bool spaced = false;
    for (unsigned char byte : title) {
        char c = static_cast<char>(byte);
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
        if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) {
            key.push_back(c);
            spaced = false;
        } else if (!key.empty() && !spaced) {
            key.push_back(' ');
            spaced = true;
        }
    }
    while (!key.empty() && key.back() == ' ') key.pop_back();
    return key;
}

bool SafeCaseFilename(const std::string& file) {
    if (file.size() < 40 || file.size() > 48) return false;
    for (unsigned char c : file)
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.'))
            return false;
    const auto dot = file.rfind('.');
    if (dot == std::string::npos) return false;
    const std::string ext = file.substr(dot);
    return ext == ".jpg" || ext == ".jpeg" || ext == ".png";
}

// The host index carries region:filename for each actual flat scan.
// Select a localized physical edition independently for front/back/spine.
// Fallbacks remain available (including North American scans for EN users).
bool SafeCaseCandidate(const std::string& token) {
    const auto colon = token.find(':');
    if (colon == std::string::npos) return SafeCaseFilename(token); // v3 fallback
    if (colon == 0 || colon > 12) return false;
    for (std::size_t i = 0; i < colon; ++i) {
        const char c = token[i];
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')))
            return false;
    }
    return SafeCaseFilename(token.substr(colon + 1));
}

std::vector<std::string> LocaleCaseCandidates(
    const std::vector<std::string>& entries, int language_choice, int face) {
    language_choice = std::clamp(language_choice, 0,
        static_cast<int>(std::size(Eden::kLanguageKeys)) - 1);
    const std::string locale = Eden::kLanguageKeys[language_choice];
    std::vector<std::string> regions;
    if (locale == "en-US" || locale == "es-419" || locale == "pt-BR")
        regions = {"us", "ca", "world", "uk", "eu", "fr"};
    else if (locale == "en-GB")
        // UK rear copy should stay English; use the US scan before an
        // unlocalized European back. PEGI European fronts remain preferred.
        regions = face == 1 ? std::vector<std::string>{"uk", "us", "ca", "world", "eu"} :
                              std::vector<std::string>{"uk", "eu", "us", "world", "ca"};
    else if (locale == "fr-CA")
        regions = {"ca", "fr", "us", "world", "eu"};
    else if (locale == "fr")
        regions = {"fr", "eu", "world", "uk", "ca", "us"};
    else if (locale == "ja")
        regions = {"jp", "asia", "world", "us", "eu"};
    else if (locale == "ko" || locale.rfind("zh", 0) == 0)
        regions = {"asia", "kr", "jp", "world", "us", "eu"};
    else {
        const auto hyphen = locale.find('-');
        const std::string lang = locale.substr(0, hyphen);
        regions = {lang, "eu", "world", "uk", "us", "ca"};
    }
    struct Candidate { int priority; std::size_t order; std::string file; };
    std::vector<Candidate> choices;
    choices.reserve(entries.size());
    for (std::size_t i = 0; i < entries.size(); ++i) {
        const std::string& token = entries[i];
        if (!SafeCaseCandidate(token)) continue;
        const auto colon = token.find(':');
        const std::string region = colon == std::string::npos ?
            "other" : token.substr(0, colon);
        const std::string file = colon == std::string::npos ?
            token : token.substr(colon + 1);
        int priority = 100;
        for (std::size_t position = 0; position < regions.size(); ++position)
            if (region == regions[position]) {
                priority = static_cast<int>(position);
                break;
            }
        choices.push_back({priority, i, file});
    }
    std::stable_sort(choices.begin(), choices.end(),
        [](const Candidate& a, const Candidate& b) {
            return a.priority < b.priority;
        });
    std::vector<std::string> sorted;
    sorted.reserve(choices.size());
    // The original linear duplicate scan was quadratic in the size of a
    // game's LaunchBox case index. Preserve the stable region-first ordering,
    // but admit each distinct filename in expected constant time.
    std::unordered_set<std::string> seen;
    seen.reserve(choices.size());
    for (const auto& candidate : choices)
        if (seen.insert(candidate.file).second)
            sorted.push_back(candidate.file);
    return sorted;
}

const BoxIndex& RetailCaseIndex() {
    static const BoxIndex index = [] {
        BoxIndex items;
        // Mounted titles can expose eboot.bin but omit auxiliary ui/ files.
        // Use the same fallback search as fonts, translations and launcher art.
        const std::string catalog_path = Eden::AppResourceFile("ui/box-art-index.tsv");
        std::ifstream input(catalog_path);
        const bool opened = static_cast<bool>(input);
        if (!opened) {
            std::fprintf(stderr, "EDEN_CASE_INDEX status=missing path=%s\n",
                         catalog_path.c_str());
        }
        std::string row;
        while (std::getline(input, row) && items.size() < 20000) {
            if (row.empty() || row[0] == '#' || row.size() > 5000) continue;
            const auto a = row.find('\t');
            if (a == std::string::npos) continue;
            const auto b = row.find('\t', a + 1);
            if (b == std::string::npos) continue;
            const auto c = row.find('\t', b + 1);
            const std::string title = row.substr(0, a);
            const std::string front = row.substr(a + 1, b - a - 1);
            const std::string back = row.substr(b + 1,
                c == std::string::npos ? c : c - b - 1);
            const auto d = c == std::string::npos ? c : row.find('\t', c + 1);
            const std::string spine = c == std::string::npos ? "-" :
                row.substr(c + 1, d == std::string::npos ? d : d - c - 1);
            std::array<std::string, 3> scene_columns{"-", "-", "-"};
            std::size_t start = d;
            for (std::string& scene : scene_columns) {
                if (start == std::string::npos) break; // v4 index remains supported
                const std::size_t end = row.find('\t', start + 1);
                scene = row.substr(start + 1,
                    end == std::string::npos ? end : end - start - 1);
                start = end;
            }
            if (title.empty() || title.size() > 170) continue;
            const auto split_candidates = [](const std::string& value) {
                std::vector<std::string> found;
                if (value == "-") return found;
                std::size_t start = 0;
                while (start < value.size() && found.size() < 12) {
                    const auto end = value.find(';', start);
                    const std::string part = value.substr(
                        start, end == std::string::npos ? end : end - start);
                    if (!SafeCaseCandidate(part)) {
                        found.clear();
                        break; // reject an invalid indexed row
                    }
                    found.push_back(part);
                    if (end == std::string::npos) break;
                    start = end + 1;
                }
                return found;
            };
            auto fronts = split_candidates(front);
            auto backs = split_candidates(back);
            auto spines = split_candidates(spine);
            if ((front != "-" && fronts.empty()) ||
                (back != "-" && backs.empty()) ||
                (spine != "-" && spines.empty())) continue;
            std::array<std::vector<std::string>, 3> scenes{};
            for (int i = 0; i < 3; ++i)
                scenes[i] = split_candidates(scene_columns[i]);
            // Invalid optional scene metadata must never invalidate valid
            // original front/back/spine entries from the same row.
            items.emplace(title, std::array<std::vector<std::string>, 6>{
                std::move(fronts), std::move(backs), std::move(spines),
                std::move(scenes[0]), std::move(scenes[1]), std::move(scenes[2])});
        }
        std::fprintf(stderr, "EDEN_CASE_INDEX status=%s entries=%zu path=%s\n",
                     opened ? "loaded" : "missing", items.size(), catalog_path.c_str());
        return items;
    }();
    return index;
}

std::string CaseFacePath(std::uint64_t title_id, const char* side) {
    char id[17]{};
    std::snprintf(id, sizeof(id), "%016llX", static_cast<unsigned long long>(title_id));
    return Eden::CoversDir() + "/box-" + side + "-" + id + ".tga";
}

// Scenic images are actual LaunchBox screenshots/fanart, cached separately
// from genuine physical box scans. Original covers never read these paths.
std::vector<std::string> CachedCaseScenes(std::uint64_t title_id) {
    std::vector<std::string> scenes;
    if (title_id == 0) return scenes;
    for (int i = 1; i <= 3; ++i) {
        const std::string side = "scene-" + std::to_string(i);
        const std::string path = CaseFacePath(title_id, side.c_str());
        if (ValidNlibTga(path)) scenes.push_back(path);
    }
    return scenes;
}

// Nlib screenshots are retained first; independent LaunchBox pictures fill
// empty slots and support the rear collage, never the actual back scan.
void AppendCaseScenes(std::vector<std::string>& screens, std::uint64_t title_id) {
    for (const auto& scene : CachedCaseScenes(title_id)) {
        if (screens.size() >= 6) break;
        if (std::find(screens.begin(), screens.end(), scene) == screens.end())
            screens.push_back(scene);
    }
}

bool FetchCaseFace(const std::vector<std::string>& candidates,
                   const std::string& destination, bool narrow_spine,
                   const std::atomic<bool>* cancel) {
    if (candidates.empty() ||
        (cancel && cancel->load(std::memory_order_acquire))) return false;
    std::string best;
    std::string best_source;
    std::size_t attempts = 0;
    std::size_t transport_failures = 0;
    std::size_t invalid_responses = 0;
    // The index is ranked by REGION, then by alternative. Take the first
    // DECODABLE face from the highest available region, not the face with the
    // most pixels across regions (which wrongly selected North America over
    // Europe). Generated older cached covers are migrated by .source markers.
    // Manual .png/.jpg/.jpeg overrides are protected in EnsureRetailCase.
    // No network activity occurs on the launch/render thread.
    for (const std::string& filename : candidates) {
        if (attempts >= 3 ||
            (cancel && cancel->load(std::memory_order_acquire))) break;
        if (!SafeCaseFilename(filename)) {
            ++invalid_responses;
            continue;
        }
        ++attempts;
        // Current LaunchBox metadata has both legacy UUID files and newer
        // r2_ files hosted on the GamesDB image CDN. Trying the legacy host
        // for an r2_ image made genuine NS2 boxes silently disappear.
        const bool r2 = filename.rfind("r2_", 0) == 0;
        const char* image_host = r2 ? "https://gamesdb-images.launchbox.gg" :
                                     "https://images.launchbox-app.com";
        const auto response = Common::Net::MakeRequest(image_host, "/" + filename);
        if (!response) {
            ++transport_failures;
            std::fprintf(stderr, "EDEN_CASE_CDN status=network-failed file=%s attempt=%zu side=%s\n",
                         filename.c_str(), attempts, narrow_spine ? "spine" : "face");
            continue;
        }
        if (cancel && cancel->load(std::memory_order_acquire)) break;
        const std::string& body = *response;
        const bool jpeg = body.size() >= 2 &&
            static_cast<unsigned char>(body[0]) == 0xff &&
            static_cast<unsigned char>(body[1]) == 0xd8;
        const bool png = body.size() >= 8 &&
            std::memcmp(body.data(), "\x89PNG\r\n\x1a\n", 8) == 0;
        if (body.size() < 1024 || body.size() > (16u << 20) || (!jpeg && !png)) {
            ++invalid_responses;
            std::fprintf(stderr, "EDEN_CASE_CDN status=invalid-body file=%s bytes=%zu jpeg=%d png=%d\n",
                         filename.c_str(), body.size(), jpeg, png);
            continue;
        }
        int w = 0, h = 0, channels = 0;
        if (!stbi_info_from_memory(
                reinterpret_cast<const unsigned char*>(body.data()),
                static_cast<int>(body.size()), &w, &h, &channels) ||
            w < (narrow_spine ? 64 : 128) ||
            h < (narrow_spine ? 600 : 200) || w > 4096 || h > 4096 ||
            static_cast<std::uint64_t>(w) * h > 3840u * 2160u) {
            ++invalid_responses;
            std::fprintf(stderr, "EDEN_CASE_CDN status=invalid-image file=%s bytes=%zu width=%d height=%d\n",
                         filename.c_str(), body.size(), w, h);
            continue;
        }
        // A larger image from a different region is NOT a better scan of
        // this edition. Once the first region-ranked usable candidate
        // decodes, do not replace it with an unrelated region.
        best = body;
        best_source = filename;
        break;
    }
    if (best.empty() || (cancel && cancel->load(std::memory_order_acquire))) {
        std::fprintf(stderr,
                     "EDEN_CASE_FETCH status=unavailable side=%s attempts=%zu network=%zu invalid=%zu\n",
                     narrow_spine ? "spine" : "face",
                     attempts, transport_failures, invalid_responses);
        return false;
    }
    (void)mkdir(Eden::CoversDir().c_str(), 0777);
    const std::string staged = destination + ".new";
    if (WriteJpegTga(best, staged, true) &&
        std::rename(staged.c_str(), destination.c_str()) == 0) {
        // Provenance for a generated TGA. A newer index can replace stale
        // US artwork even when the cached US image has higher resolution.
        // The TGA remains usable if this tiny receipt write fails.
        std::ofstream receipt(destination + ".source", std::ios::trunc);
        if (receipt) receipt << best_source << '\n';
        std::fprintf(stderr, "EDEN_CASE_FETCH status=stored side=%s source=%s attempts=%zu bytes=%zu\n",
                     narrow_spine ? "spine" : "face", best_source.c_str(), attempts, best.size());
        return true;
    }
    (void)std::remove(staged.c_str());
    std::fprintf(stderr, "EDEN_CASE_FETCH status=write-failed side=%s attempts=%zu\n",
                 narrow_spine ? "spine" : "face", attempts);
    return false;
}

// All physical box scans, NS1 and NS2, come exclusively from the verified
// region-ranked LaunchBox index. No retail-product-photo fallback is allowed.
// Missing scans use the same opaque procedural case renderer as NS1.
unsigned EnsureRetailCase(std::uint64_t title_id, const std::string& name,
                      const std::string& alternate_name, int language_choice,
                      const std::atomic<bool>* cancel) {
    if (title_id == 0 || (cancel && cancel->load(std::memory_order_acquire))) return 0;
    const auto& index = RetailCaseIndex();
    const auto selected = [&]() -> BoxIndex::const_iterator {
        auto it = index.find(CaseKey(name));
        if (it != index.end()) return it;
        return index.find(CaseKey(alternate_name));
    }();
    if (selected == index.end()) {
        std::fprintf(stderr, "EDEN_CASE_LOOKUP title=%016llX status=no-match name=%s alternate=%s index_entries=%zu\n",
                     static_cast<unsigned long long>(title_id), name.c_str(),
                     alternate_name.c_str(), index.size());
        // A retailer product photo is NOT a flat box scan: its white
        // surrounding canvas was rendered as the physical jacket front.
        // Keep the true extracted icon/hero for procedural fallback rather
        // than writing a counterfeit "box-front" from a shop photo.
        return 0u;
    }
    std::fprintf(stderr,
                 "EDEN_CASE_LOOKUP title=%016llX status=match front=%zu back=%zu spine=%zu scenes=%zu/%zu/%zu\n",
                 static_cast<unsigned long long>(title_id),
                 selected->second[0].size(), selected->second[1].size(),
                 selected->second[2].size(), selected->second[3].size(),
                 selected->second[4].size(), selected->second[5].size());
    // Both Home and Library may enrich the same title at once. Serialize
    // background fetches so the second worker reads the first worker's
    // finished cache, but never hold launcher teardown hostage to this wait.
    // No socket request or mutex sleep runs on the UI/render thread.
    static std::array<std::mutex, 64> locks;
    std::unique_lock guard(locks[title_id % locks.size()], std::defer_lock);
    while (!guard.try_lock()) {
        if (cancel && cancel->load(std::memory_order_acquire)) return 0;
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    if (cancel && cancel->load(std::memory_order_acquire)) return 0;
    static std::mutex retry_mutex;
    static std::unordered_map<std::uint64_t, std::chrono::steady_clock::time_point> retries;
    {
        std::lock_guard retry(retry_mutex);
        const auto it = retries.find(title_id);
        if (it != retries.end() && std::chrono::steady_clock::now() < it->second)
            return 0;
        // Failed image hosts, cancellation or an incomplete side must not
        // disable all retries for four hours on a newly installed game.
        retries[title_id] = std::chrono::steady_clock::now() + std::chrono::minutes(5);
    }
    bool all_ready = true;
    unsigned changed_faces = 0;
    // NS2 games may have a real front and spine but NO uploaded back.
    // Their spine must not depend on the existence of a back scan.
    for (int side = 0; side < 6; ++side) {
        if (cancel && cancel->load(std::memory_order_acquire)) {
            // Aborted title switch must not lock the next attempt out for
            // five minutes after a partial or cancelled CDN transaction.
            all_ready = false;
            break;
        }
        // Front and back always fetch first. A successful first-pass pair
        // can be followed by its spine in the SAME background enrichment;
        // otherwise the 5-minute retry could leave a complete paper wrap
        // without its printed spine until the next launcher session.
        if (side >= 3 && ValidNlibTga(CaseFacePath(title_id, "back")))
            continue; // authentic back never needs a constructed collage
        const auto candidates = LocaleCaseCandidates(selected->second[side], language_choice, side);
        if (candidates.empty()) continue;
        const char* const names[] = {
            "front", "back", "spine", "scene-1", "scene-2", "scene-3"};
        const std::string path = CaseFacePath(title_id, names[side]);
        // User-provided original scans win. Cached low-resolution CDN scans
        // may be upgraded when a better ranked alternative becomes available.
        const std::string base = path.substr(0, path.size() - 4);
        if (IsFile(base + ".png") || IsFile(base + ".jpg") ||
            IsFile(base + ".jpeg")) continue;
        // Revalidate region provenance when the package index changes.
        // Older TGA files without .source (or from another region) must be
        // re-fetched, not silently accepted solely for their pixel count.
        std::ifstream receipt(path + ".source");
        std::string cached_source;
        if (receipt) std::getline(receipt, cached_source);
        if (cached_source == candidates.front() && ValidNlibTga(path)) {
            // Generated retail scans are uncompressed BGRA TGA. stb_image's
            // stbi_info() may reject these perfectly readable files, which
            // previously triggered a fresh CDN download on every enrichment.
            // Match box_art() and the native TGA loader's header contract.
            std::FILE* input = std::fopen(path.c_str(), "rb");
            if (input) {
                unsigned char header[18]{};
                if (std::fread(header, 1, sizeof(header), input) == sizeof(header)) {
                    const int width = static_cast<int>(header[12]) |
                                      (static_cast<int>(header[13]) << 8);
                    const int height = static_cast<int>(header[14]) |
                                       (static_cast<int>(header[15]) << 8);
                    if ((side == 2 && width >= 64 && height >= 600) ||
                        (side != 2 && width >= 128 && height >= 200)) {
                        std::fclose(input);
                        continue;
                    }
                }
                std::fclose(input);
            }
        }
        // If network retrieval fails, the old cached TGA remains usable;
        // source migration is retried later without blocking rendering.
        if (!FetchCaseFace(candidates, path, side == 2, cancel)) {
            all_ready = false;
            std::fprintf(stderr, "EDEN_CASE_FACE title=%016llX side=%d status=unavailable\n",
                         static_cast<unsigned long long>(title_id), side);
        } else {
            changed_faces |= (1u << side); // Only successful atomic replacements.
            // A fallback candidate remains usable, but only retry its higher
            // priority European/locale scan on the next bounded refresh.
            std::ifstream refreshed(path + ".source");
            std::string actual;
            if (refreshed) std::getline(refreshed, actual);
            if (actual != candidates.front()) all_ready = false;
        }
    }
    if (all_ready || (cancel && cancel->load(std::memory_order_acquire))) {
        // A fully successful refresh needs no retry guard; a cancelled
        // refresh is immediately retryable on the next launcher session.
        std::lock_guard retry(retry_mutex);
        retries.erase(title_id);
    }
    return changed_faces;
}

NlibEnrichment CachedNlibEnrichment(std::uint64_t title_id, int language_choice) {
    NlibEnrichment result;
    if (title_id == 0) return result;
    result.icon = CachedNlibIcon(title_id);
    result.hero = CachedNlibHero(title_id);
    result.screenshots = CachedNlibScreens(title_id);
    result.max_players = CachedNlibPlayers(title_id);
    nlohmann::json metadata;
    if (LoadNlibMetadata(title_id, NlibLanguageCode(language_choice), &metadata))
        ApplyNlibMetadata(metadata, &result);
    if (result.hero.empty() && !result.screenshots.empty())
        result.hero = result.screenshots.front();
    return result;
}

// Nlib enriches the launcher only; no game ever depends on the network. The ROM icon stays the
// offline fallback. Cards prefer Nlib's square icon, Home prefers its 16:9 banner, and Library
// details use all available gameplay screenshots (up to the current API cap). Every
// title is queued for complete artwork at startup, not only on Library selection.
NlibEnrichment EnsureNlibEnrichment(std::uint64_t title_id, int language_choice,
                                       const std::atomic<bool>* cancel = nullptr) {
    const auto cancelled = [cancel] {
        return cancel && cancel->load(std::memory_order_acquire);
    };
    if (title_id == 0 || cancelled()) return {};

    // Home and Library can request the same title at the same time. Cache writes use
    // the same .new staging path, so serialize per hash bucket while leaving other
    // titles free to enrich in parallel.
    static std::array<std::mutex, 16> title_locks;
    std::scoped_lock title_lock{title_locks[title_id % title_locks.size()]};
    if (cancelled()) return {};

    NlibEnrichment result = CachedNlibEnrichment(title_id, language_choice);
    const std::string language = NlibLanguageCode(language_choice);
    nlohmann::json metadata;
    const bool cached_metadata = LoadNlibMetadata(title_id, language, &metadata);
    const bool current_metadata_cache = cached_metadata && metadata.is_object() &&
        metadata.value("_encore_cache_schema", 0) >= kNlibCacheSchema;
    const auto now_seconds = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    std::int64_t last_metadata_check = 0;
    std::int64_t last_artwork_check = 0;
    if (cached_metadata && metadata.is_object()) {
        const auto checked = metadata.find("_encore_checked_at");
        if (checked != metadata.end() && checked->is_number_integer())
            last_metadata_check = checked->get<std::int64_t>();
        const auto artwork = metadata.find("_encore_artwork_checked_at");
        if (artwork != metadata.end() && artwork->is_number_integer())
            last_artwork_check = artwork->get<std::int64_t>();
    }
    // Legacy schema-v2 metadata (including negative art results) must expire.
    // Use persisted timestamps rather than PS5 filesystem mtime syscalls.
    const bool metadata_expired = !current_metadata_cache ||
        last_metadata_check <= 0 || now_seconds < last_metadata_check ||
        now_seconds - last_metadata_check >= 7LL * 24 * 60 * 60;
    // Valid but outdated images are refreshed monthly, atomically.
    const bool artwork_expired = last_artwork_check <= 0 ||
        now_seconds < last_artwork_check ||
        now_seconds - last_artwork_check >= 30LL * 24 * 60 * 60;

    char id[17]{};
    std::snprintf(id, sizeof(id), "%016llX", static_cast<unsigned long long>(title_id));
    // Bounded retry map is launcher-only and independent of PS5 filesystem
    // timestamps. Old filesystem::last_write_time caused an unnecessary native
    // syscall on every selection, even for a title absent from Nlib.
    static std::mutex retry_guard;
    static std::unordered_map<std::string, std::chrono::steady_clock::time_point> next_retry;
    const std::string retry_key = std::string{id} + ":" + language;
    std::fprintf(stderr,
                 "EDEN_NLIB_BEGIN title_id=%s lang=%s cached_meta=%d cache_schema=%d cached_icon=%d cached_hero=%d cached_screens=%zu cached_players=%d\n",
                 id, language.c_str(), cached_metadata, current_metadata_cache, !result.icon.empty(), !result.hero.empty(),
                 result.screenshots.size(), result.max_players);

    try {
        bool refreshed_metadata = false;
        // One localized metadata request tells us which media exist and fills the selected game's
        // actual title/intro/publisher/etc. The response is cached separately per Nlib language.
        bool has_icon = cached_metadata && metadata.contains("icon") && metadata["icon"].is_string();
        bool has_banner = cached_metadata && metadata.contains("banner") && metadata["banner"].is_string();
        int screen_count = static_cast<int>(result.screenshots.size());
        if (cached_metadata && metadata.contains("screens") && metadata["screens"].is_object())
            screen_count = std::max(screen_count, metadata["screens"].value("count", 0));
        // A title can acquire Nlib artwork after it was first catalogued.
        // Refresh sparse metadata periodically without filesystem timestamp
        // calls, and never suppress downloads already described by cached
        // metadata just because a refresh is temporarily rate-limited.
        const bool sparse_metadata = current_metadata_cache &&
                                    (!has_icon || !has_banner || screen_count == 0);
        const bool needs_metadata = metadata_expired || sparse_metadata;
        bool may_request_metadata = needs_metadata;
        if (needs_metadata) {
            std::lock_guard lock(retry_guard);
            const auto it = next_retry.find(retry_key);
            if (it != next_retry.end() && std::chrono::steady_clock::now() < it->second)
                may_request_metadata = false;
        }
        if (needs_metadata && !may_request_metadata && !current_metadata_cache)
            return result;
        if (may_request_metadata) {
            if (cancelled()) return result;
            const std::string metadata_endpoint = std::string{"/nx/"} + id + "?lang=" + language +
                "&fields=name,intro,description,publisher,developer,releaseDate,category,languages,"
                "numberOfPlayers,icon,banner,screens";
            if (const auto response = Common::Net::MakeRequest("https://api.nlib.cc", metadata_endpoint)) {
                metadata = nlohmann::json::parse(*response);
                if (metadata.is_object()) {
                    refreshed_metadata = true;
                    metadata["_encore_cache_schema"] = kNlibCacheSchema;
                    metadata["_encore_checked_at"] = now_seconds;
                    metadata["_encore_artwork_checked_at"] = last_artwork_check;
                    (void)AtomicWriteText(NlibMetadataPath(title_id, language), metadata.dump());
                    ApplyNlibMetadata(metadata, &result);
                    has_icon = metadata.contains("icon") && metadata["icon"].is_string();
                    has_banner = metadata.contains("banner") && metadata["banner"].is_string();
                    if (metadata.contains("screens") && metadata["screens"].is_object())
                        screen_count = std::max(screen_count, metadata["screens"].value("count", 0));
                }
                std::lock_guard lock(retry_guard);
                if (!metadata.is_object() || !has_icon || !has_banner || screen_count == 0)
                    next_retry[retry_key] = std::chrono::steady_clock::now() +
                                            std::chrono::minutes(30);
                else
                    next_retry.erase(retry_key);
            } else {
                // Keep previously cached image links on a transient timeout.
                // A newly discovered title retries in five minutes.
                std::lock_guard lock(retry_guard);
                next_retry[retry_key] = std::chrono::steady_clock::now() +
                                        std::chrono::minutes(5);
                if (!current_metadata_cache) return result;
            }
        }
        if (cancelled()) return result;
        if (result.max_players > 0) CacheNlibPlayers(title_id, result.max_players);
        const bool refresh_existing_artwork = refreshed_metadata && artwork_expired;

        // Nlib banner, icon and every advertised screenshot are fetched in
        // ONE pass for every installed title. Independent HTTPS requests run
        // concurrently on this background worker, not serially at 3 seconds
        // each. No hidden "screens later in Library" scheduling.
        std::vector<std::future<bool>> downloads;
        const auto request_media = [&](std::string endpoint, std::string path,
                                       std::size_t minimum = 1024) {
            if (cancelled()) return;
            downloads.emplace_back(std::async(std::launch::async,
                [endpoint = std::move(endpoint), path = std::move(path), minimum, cancel] {
                    return CacheNlibJpeg(endpoint, path, minimum, cancel);
                }));
        };

        // A screenshot-backed hero does not prove a real banner was cached.
        if (has_banner && (CachedNlibHero(title_id).empty() || refresh_existing_artwork))
            request_media(std::string{"/nx/"} + id + "/banner/1080p",
                          NlibHeroPath(title_id), 4096);
        if (has_icon && (CachedNlibIcon(title_id).empty() || refresh_existing_artwork))
            request_media(std::string{"/nx/"} + id + "/icon/512",
                          NlibIconPath(title_id));

        const int wanted_screens = std::clamp(screen_count, 0, 3);
        for (int index = 1; index <= wanted_screens; ++index) {
            if (cancelled()) break;
            const std::string path = NlibScreenshotPath(title_id, index);
            if (!ValidNlibTga(path) || refresh_existing_artwork)
                request_media(std::string{"/nx/"} + id + "/screen/" + std::to_string(index),
                              path, 4096);
        }
        // Join only in the background enrichment task. The UI thread remains
        // free to render/input; title mutex excludes duplicate .new file writes.
        int failed_media = 0;
        for (auto& pending : downloads) {
            if (pending.get()) result.artwork_changed = true;
            else ++failed_media;
        }
        if (!cancelled() && refreshed_metadata && artwork_expired && failed_media == 0) {
            metadata["_encore_artwork_checked_at"] = now_seconds;
            (void)AtomicWriteText(NlibMetadataPath(title_id, language), metadata.dump());
        }
        if (failed_media > 0)
            std::fprintf(stderr, "EDEN_NLIB_ASSETS title_id=%s failed=%d attempted=%zu\n",
                         id, failed_media, downloads.size());

        const NlibEnrichment complete = CachedNlibEnrichment(title_id, language_choice);
        if (!complete.icon.empty()) result.icon = complete.icon;
        if (!complete.hero.empty()) result.hero = complete.hero;
        result.screenshots = complete.screenshots;
        if (result.hero.empty() && !result.screenshots.empty())
            result.hero = result.screenshots.front();
    } catch (const std::exception& error) {
        Eden::Report("artwork", (std::string{"Nlib unavailable: "} + error.what()).c_str());
    }

    std::fprintf(stderr,
                 "EDEN_NLIB_RESULT title_id=%s icon=%d hero=%d screens=%zu players=%d\n", id,
                 !result.icon.empty(), !result.hero.empty(), result.screenshots.size(),
                 result.max_players);
    return result;
}

std::uintmax_t TreeBytes(const std::filesystem::path& root,
                        const std::atomic<bool>* cancel = nullptr) {
    if (cancel && cancel->load(std::memory_order_acquire)) return 0;
    std::error_code error;
    if (!std::filesystem::exists(root, error)) return 0;
    std::uintmax_t bytes = 0;
    std::filesystem::recursive_directory_iterator it(
        root, std::filesystem::directory_options::skip_permission_denied, error), end;
    while (!error && it != end) {
        if (cancel && cancel->load(std::memory_order_acquire)) return 0;
        std::error_code entry_error;
        if (it->is_regular_file(entry_error)) {
            const auto size = it->file_size(entry_error);
            if (!entry_error) bytes += size;
        }
        it.increment(error);
        if (error) error.clear(); // Skip an unreadable entry and continue where possible.
    }
    return bytes;
}

std::string StorageSize(std::uintmax_t bytes) {
    constexpr std::uintmax_t KiB = 1024;
    constexpr std::uintmax_t MiB = KiB * 1024;
    constexpr std::uintmax_t GiB = MiB * 1024;
    char text[64];
    if (bytes >= GiB)
        std::snprintf(text, sizeof(text), "%.1f GB", static_cast<double>(bytes) / static_cast<double>(GiB));
    else if (bytes >= MiB)
        std::snprintf(text, sizeof(text), "%.1f MB", static_cast<double>(bytes) / static_cast<double>(MiB));
    else
        std::snprintf(text, sizeof(text), "%.0f KB", static_cast<double>(bytes) / static_cast<double>(KiB));
    return text;
}


// A game's update and DLC: "Update 1.2.0, 2 DLC"; brief leaves the word out ("v1.2.0, 2 DLC") for
// places with little room.
std::string AddOnSummary(uint64_t title_id, bool brief = false) {
    char update[64]{};
    unsigned dlc = 0;
    eden_game_addons(title_id, update, sizeof(update), &dlc);
    std::string text;
    if (update[0]) text = brief ? (update[0] == 'v' ? std::string{update} : "v" + std::string{update}) :
                                  fill(tr("Update {0}"), {update});
    if (dlc) text += (text.empty() ? "" : ", ") + fill(tr("{0} DLC"), {std::to_string(dlc)});
    return text;
}

// The language a game will use for the chosen one (Settings > Language), and a note when the game
// does not offer the choice and falls back to another language.
struct GameLanguage {
    std::string label;
    std::string note;
};
GameLanguage LanguageFor(const std::string& path, uint64_t title_id, int choice) {
    const int chosen = Eden::kLanguageSettings[choice];
    const int used = eden_game_language(path.c_str(), Eden::AssetsPath("keys").c_str(), title_id, chosen);
    GameLanguage result{tr(Eden::kLanguageLabels[choice]), {}};
    if (used == chosen) return result;
    result.label = tr("Another language");
    for (std::size_t i = 0; i < std::size(Eden::kLanguageSettings); ++i)
        if (Eden::kLanguageSettings[i] == used) result.label = tr(Eden::kLanguageLabels[i]);
    result.note = fill(tr("{0} not available"), {tr(Eden::kLanguageLabels[choice])});
    return result;
}

// Why a game did not start, as headless/main.cpp reports it. The reasons that are whole sentences
// are shown in the player's language; the others carry codes and file names and stay as they are.
// (tools/launcher/strings.py checks that main.cpp still says these.)
constexpr const char* kLaunchErrors[] = {
    TR("Selected ROM is no longer available"),
    TR("PS5 controller initialization failed"),
    TR("The game could not allocate PS5 memory. Close Eden Encore completely before retrying to release memory retained between games."),
    TR("Graphics backend initialization failed. Try another backend in Settings; see stderr.log and eden_log.txt for "
       "driver details."),
    TR("The game ran out of graphics memory. Lower the resolution in Settings, Video (or in the game's own settings) "
       "and start it again."),
};
std::string LaunchError(const std::string& reason) {
    std::string text = reason;
    for (const char* known : kLaunchErrors)
        if (reason == known) text = tr(known);
    // "Details:" follows it: a reason without its own full stop gets one.
    if (!text.empty() && text.back() != '.' && text.back() != '!' && text.back() != '?') text += '.';
    return text;
}

// Names of the subfolders (folders = true) or regular files in path, sorted without regard
// to case. Unlike ReadNativeDirectory, an odd entry is skipped rather than failing the
// folder: the Storage browser walks available roots/directories so an external root can be chosen.
std::vector<std::string> ListEntries(const std::string& path, bool folders, bool& ok) {
    ok = false;
    std::vector<std::string> names;
    const int fd = open(path.c_str(), O_RDONLY | O_DIRECTORY);
    if (fd < 0) return names;
    std::vector<char> buffer(65536);
    for (;;) {
        const int count = sceKernelGetdents(fd, buffer.data(), static_cast<int>(buffer.size()));
        if (count == 0) { ok = true; break; }
        if (count < 0 || count > static_cast<int>(buffer.size())) break;
        for (std::size_t offset = 0; offset + offsetof(dirent, d_name) < static_cast<std::size_t>(count);) {
            uint16_t length;
            uint8_t type;
            std::memcpy(&length, buffer.data() + offset + offsetof(dirent, d_reclen), sizeof(length));
            std::memcpy(&type, buffer.data() + offset + offsetof(dirent, d_type), sizeof(type));
            if (length <= offsetof(dirent, d_name) || offset + length > static_cast<std::size_t>(count)) break;
            const char* name = buffer.data() + offset + offsetof(dirent, d_name);
            const std::string entry(name, strnlen(name, length - offsetof(dirent, d_name)));
            offset += length;
            if (entry.empty() || entry == "." || entry == "..") continue;
            if (type == DT_LNK) continue;
            bool is_folder = type == DT_DIR, is_file = type == DT_REG;
            if (type == DT_UNKNOWN) {
                struct stat info {};
                const std::string full = path == "/" ? "/" + entry : path + "/" + entry;
                if (lstat(full.c_str(), &info) == 0) {
                    if (S_ISLNK(info.st_mode)) continue;
                } else if (errno != EPERM && errno != EACCES) {
                    continue;
                } else if (stat(full.c_str(), &info) != 0) {
                    continue;
                }
                is_folder = S_ISDIR(info.st_mode);
                is_file = S_ISREG(info.st_mode);
            }
            if (folders ? is_folder : is_file) names.push_back(entry);
        }
    }
    close(fd);
    const auto lower = [](std::string text) {
        for (char& c : text) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        return text;
    };
    std::sort(names.begin(), names.end(), [&](const std::string& a, const std::string& b) {
        return lower(a) < lower(b);
    });
    return names;
}

std::string JoinPath(const std::string& directory, const std::string& name) {
    return directory == "/" ? "/" + name : directory + "/" + name;
}

// Files in directory with one of the (lower-case) extensions; -1 when it cannot be read.
int CountFiles(const std::string& directory, std::initializer_list<const char*> extensions) {
    bool ok = false;
    int count = 0;
    for (const auto& name : ListEntries(directory, false, ok)) {
        std::string lower = name;
        for (char& c : lower) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        for (const char* extension : extensions)
            if (lower.size() > std::strlen(extension) && lower.ends_with(extension)) { ++count; break; }
    }
    return ok ? count : -1;
}

// Preserve the original count entry point while including BOTH extracted
// ExeFS and packaged base inputs inside a title folder. The Home setup
// counter must agree with the actual Library and CountInstalledGames.
int CountExeFsFolders(const std::string& directory) {
    bool ok = false;
    int count = 0;
    for (const auto& name : ListEntries(directory, true, ok)) {
        if (!Eden::FindGameFolderInput(std::filesystem::path(directory) / name).empty())
            ++count;
    }
    return ok ? count : -1;
}

unsigned int HashPath(const std::string& path) {
    unsigned int hash = 2166136261u;
    for (const unsigned char byte : path) hash = (hash ^ byte) * 16777619u;
    return hash;
}

// A title from the file's name: without its extension and the tags dumps carry
// ("Name [0100...][v0]", "Name (USA)").
std::string CleanTitle(const std::string& filename) {
    const auto selected_path = std::filesystem::path(filename);
    const std::string base = Eden::IsDeconstructedGameSelection(filename) ||
                             Eden::IsNestedGameFileSelection(filename)
                                 ? (*selected_path.begin()).string()
                                 : selected_path.stem().string();
    std::string title = base;
    if (title.rfind("[Game] ", 0) == 0) title.erase(0, 7);
    if (const auto tag = title.find_first_of("[("); tag != std::string::npos && tag > 0) title.erase(tag);
    while (!title.empty() && (title.back() == ' ' || title.back() == '_' || title.back() == '-')) title.pop_back();
    return title.empty() ? base : title;
}

// Covers are keyed by the ROM's file name, not its full path, so they survive a new game
// files folder.
std::string CoverPath(const std::string& filename) {
    char name[16]{};
    std::snprintf(name, sizeof(name), "/%08x.tga", HashPath(filename));
    return Eden::CoversDir() + name;
}

// The game's own name is kept beside its cover once the ROM has been read, so the home screen
// can name its games without opening them.
std::string NamePath(const std::string& filename) {
    char name[16]{};
    std::snprintf(name, sizeof(name), "/%08x.name", HashPath(filename));
    return Eden::CoversDir() + name;
}

std::string SavedTitle(const std::string& filename) {
    char text[513]{};
    if (std::FILE* file = std::fopen(NamePath(filename).c_str(), "rb")) {
        const std::size_t size = std::fread(text, 1, sizeof(text) - 1, file);
        std::fclose(file);
        text[size] = '\0';
    }
    return text;
}

void SaveTitle(const std::string& filename, const std::string& title) {
    if (title.empty() || SavedTitle(filename) == title) return;
    const std::string path = NamePath(filename);
    const std::string staged = path + ".new";
    std::FILE* file = std::fopen(staged.c_str(), "wb");
    if (!file) return;
    const bool written = std::fwrite(title.data(), 1, title.size(), file) == title.size();
    if (std::fclose(file) != 0 || !written || std::rename(staged.c_str(), path.c_str()) != 0)
        (void)std::remove(staged.c_str());
}

std::string GameTitle(const std::string& filename) {
    const std::string saved = SavedTitle(filename);
    return saved.empty() ? CleanTitle(filename) : saved;
}

// The cached cover of a ROM, extracted from it when missing; empty when it has none.
std::string EnsureCover(const std::string& filename, std::string* title = nullptr) {
    const std::string cover = CoverPath(filename);
    if (Eden::FileExists(cover) && !title) return cover;
    const std::string rom = Eden::AssetsPath("roms/" + filename);
    if (!Eden::FileExists(rom)) return {};
    (void)mkdir(Eden::CoversDir().c_str(), 0777);
    char extracted[513]{};
    const int metadata = eden_extract_game_metadata(rom.c_str(), Eden::AssetsPath("keys").c_str(), cover.c_str(),
                                                    extracted, sizeof(extracted));
    if (metadata & EDEN_METADATA_TITLE) {
        SaveTitle(filename, extracted);
        if (title) *title = extracted;
    }
    if (metadata & EDEN_METADATA_COVER) return cover;
    Eden::Report("cover", ("No cover extracted from " + filename).c_str());
    return Eden::FileExists(cover) ? cover : std::string{};
}

int CountInstalledGames() {
    std::error_code error;
    const auto entries = Eden::ReadNativeDirectory(Eden::AssetsPath("roms"), error);
    if (error) return 0;
    int count = 0;
    for (const auto& entry : entries) {
        const std::string filename = entry.path().filename().string();
        const auto discovered = Eden::FindGameFolderInput(entry.path());
        const std::string selection = discovered.empty() ? filename : filename + "/" + discovered;
        if (Eden::ValidRomFilename(selection) &&
            IsFile(Eden::AssetsPath("roms/" + selection))) ++count;
    }
    return count;
}

// The labels of a setting, in the player's language (tools/launcher/strings.py lists them).
template <std::size_t N>
std::vector<std::string> Labels(const char* const (&values)[N]) {
    std::vector<std::string> labels;
    for (const char* value : values) labels.emplace_back(tr(value));
    return labels;
}

// What is missing from the setup, as metadata_bridge.cpp words it, in the player's language. Each
// message is one of these texts, with a folder or a code where it says {0}.
std::string SetupMessage(const std::string& english) {
    static constexpr const char* kMessages[] = {
        TR("Missing or empty keys/prod.keys in {0}."),
        TR("prod.keys could not supply an NCA header key. Replace it with a valid key dump."),
        TR("Cannot read firmware/ in {0}. Install extracted firmware NCAs."),
        TR("A firmware NCA cannot be read. Reinstall the firmware dump."),
        TR("Firmware NCA validation failed (code {0}). Check that firmware and prod.keys are compatible."),
        TR("No firmware NCAs found in {0}."),
        TR("Firmware SystemVersion data is missing or unreadable. Install a complete firmware dump."),
        TR("Setup validation failed. Check that firmware and key files are readable and valid."),
    };
    for (const std::string_view pattern : kMessages) {
        const std::size_t hole = pattern.find("{0}");
        if (hole == std::string_view::npos) {
            if (english == pattern) return tr(english);
            continue;
        }
        const std::string_view before = pattern.substr(0, hole);
        const std::string_view after = pattern.substr(hole + 3);
        if (english.size() >= before.size() + after.size() && english.starts_with(before) &&
            english.ends_with(after))
            return fill(tr(std::string(pattern)),
                        {std::string_view{english}.substr(before.size(),
                                                           english.size() - before.size() - after.size())});
    }
    return english;
}

void RefreshEncoreOverridesManifest() {
    try {
        constexpr std::string_view kHost = "https://raw.githubusercontent.com";
        constexpr std::string_view kPath = "/niakw/encore-overrides/main/runtime-manifest.json";
        const auto response = Common::Net::MakeRequest(std::string{kHost}, std::string{kPath});
        if (!response) {
            Eden::Report("overrides", "Remote runtime manifest unavailable; using embedded snapshot");
            return;
        }
        Eden::EncoreOverridesRuntime::State checked;
        if (!Eden::EncoreOverridesRuntime::ParseManifestText(*response, &checked)) {
            Eden::Report("overrides", "Remote runtime manifest rejected; using embedded snapshot");
            return;
        }
        if (!AtomicWriteText(Eden::EncoreOverridesRuntime::ManifestPath(), *response)) {
            Eden::Report("overrides", "Could not cache remote runtime manifest");
            return;
        }
        Eden::Report("overrides",
                     ("Runtime manifest cached: revision " +
                      std::to_string(checked.database_revision) + ", " +
                      std::to_string(checked.titles.size()) + " specific title(s)").c_str());
    } catch (const std::exception& error) {
        Eden::Report("overrides", (std::string{"Remote runtime manifest failed: "} + error.what()).c_str());
    }
}

void StartEncoreOverridesRefresh() {
    static std::once_flag once;
    std::call_once(once, [] {
        // Never block launcher startup on GitHub. The validated cache becomes authoritative on the
        // next process start (or before first profile lookup if the fetch finishes early enough).
        std::thread(RefreshEncoreOverridesManifest).detach();
    });
}

} // namespace

EdenServices::EdenServices(std::string launch_error)
    : launch_error_(std::move(launch_error)),
      resolution_labels_(Labels(Eden::kResolutionLabels)),
      resolution_keys_(Labels(Eden::kResolutionKeys)),
      filter_labels_(Labels(Eden::kUpscalingFilterLabels)),
      anti_aliasing_labels_(Labels(Eden::kAntiAliasingLabels)),
      performance_profile_labels_(Labels(Eden::kPerformanceProfileLabels)),
      language_labels_(Labels(Eden::kLanguageLabels)) {
    (void)mkdir(Eden::ConfigDir().c_str(), 0777);
    // The repository currently publishes no runtime-manifest.json; a silent
    // HTTPS request on every boot can only fail and is not required when all
    // authored game profiles are compiled from our pinned vendored catalogue.
    // Keep explicit diagnostic/dev opt-in for future validated remote manifests.
    const char* remote_overrides = std::getenv("EDEN_OVERRIDES_REMOTE_REFRESH");
    if (remote_overrides != nullptr && std::strcmp(remote_overrides, "1") == 0)
        StartEncoreOverridesRefresh();
    setup_ = eden_startup_error();
    Eden::Report("setup", setup_.empty() ? "Keys and firmware startup checks passed" : setup_.c_str());
}

pe::ui::Home EdenServices::home() {
    return home(nullptr);
}

pe::ui::Home EdenServices::home(const std::atomic<bool>* cancel) {
    const auto cancelled = [cancel] {
        return cancel && cancel->load(std::memory_order_acquire);
    };
    if (cancelled()) return {};
    const std::lock_guard lock(bridge_);
    if (cancelled()) return {};
    pe::ui::Home home;
    home.setup_ready = setup_.empty();
    if (!home.setup_ready) {
        home.status = fill(tr("Setup required: {0} Open Settings, Storage to choose the root that holds the standard "
                              "keys, firmware and roms folders (or add the files to {1}), then reopen Encore."),
                           {SetupMessage(setup_), Eden::AssetsDir()});
    } else if (launch_error_.starts_with(Eden::Crash::kNotice)) {
        // The previous run ended with a crash report (headless/crash_report.h).
        home.status = fill(tr("ProsperoEden stopped because of an error. A report was saved to {0}."),
                           {launch_error_.substr(Eden::Crash::kNotice.size())});
        home.launch_failed = true;
    } else if (!launch_error_.empty()) {
        home.status = fill(tr("Game could not start: {0} Details: {1}"),
                           {LaunchError(launch_error_), Eden::LogFile("stderr.log")});
        home.launch_failed = true;
    }

    home.last_file = Eden::LoadLastGame();
    // If the last game was removed, fall back to the most recent one that still exists.
    if (!home.last_file.empty() && !IsFile(Eden::AssetsPath("roms/" + home.last_file))) {
        home.last_file.clear();
        for (const auto& name : Eden::LoadRecentGames()) {
            if (Eden::ValidRomFilename(name) && IsFile(Eden::AssetsPath("roms/" + name))) {
                home.last_file = name;
                break;
            }
        }
    }
    if (cancelled()) return {};
    const std::string last_path = Eden::AssetsPath("roms/" + home.last_file);
    home.last_exists = !home.last_file.empty() && IsFile(last_path);
    if (!home.last_file.empty()) {
        std::string title = GameTitle(home.last_file);
        std::string cover = CoverPath(home.last_file);
        bool has_cover = Eden::FileExists(cover);
        if (home.last_exists && home.setup_ready && !has_cover) {
            cover = EnsureCover(home.last_file, &title);
            has_cover = !cover.empty();
        }
        home.last_title = title;
        home.last_caption = home.last_exists ? tr("Last game opened") :
                                               tr("ROM missing from the storage root");
        home.last_caption_warning = !home.last_exists;
        if (has_cover) home.last_cover = cover;
    }
    // The last game's update and DLC and the language it will use; when it does not offer the
    // chosen one, the caption says so. The same metadata is reused by Recent cards so selecting
    // one can become the Home hero without opening the full library first.
    if (cancelled()) return {};
    const int selected_language = Eden::LoadPreferences().language;
    if (home.setup_ready)
        eden_scan_addons(Eden::AssetsPath("updates").c_str(), Eden::AssetsPath("keys").c_str(),
                         Eden::AssetsPath("roms").c_str());
    if (cancelled()) return {};
    if (home.setup_ready && home.last_exists) {
        const uint64_t title_id = ResolveTitleId(last_path, home.last_file);
        const GameLanguage language = LanguageFor(last_path, title_id, selected_language);
        home.last_title_id = title_id;
        const NlibEnrichment nlib = CachedNlibEnrichment(title_id, selected_language);
        if (!nlib.icon.empty()) home.last_cover = nlib.icon;
        home.last_hero = nlib.hero;
        home.last_screenshot = nlib.screenshots.empty() ? std::string{} : nlib.screenshots.front();
        home.last_max_players = nlib.max_players;
        home.last_intro = nlib.intro;
        home.last_description = nlib.description;
        if (!nlib.name.empty()) home.last_title = nlib.name;
        home.last_addons = AddOnSummary(title_id);
        home.last_language = language.label;
        if (!language.note.empty()) {
            home.last_caption = language.note;
            home.last_caption_warning = true;
        }
    }

    auto history = Eden::LoadRecentGames();
    if (history.empty() && home.last_exists) {
        if (!Eden::SaveRecentGame(home.last_file))
            Eden::Report("history", "Could not seed recent games from last played game");
        history.push_back(home.last_file);
    }
    for (const auto& name : history) {
        if (cancelled()) return {};
        const std::string recent_path = Eden::AssetsPath("roms/" + name);
        if (!IsFile(recent_path)) continue;
        pe::ui::Recent recent;
        recent.file = name;
        recent.title = GameTitle(name);
        recent.cover = EnsureCover(name);
        if (home.setup_ready) {
            recent.title_id = ResolveTitleId(recent_path, name);
            if (recent.title_id != 0) {
                const NlibEnrichment nlib = CachedNlibEnrichment(recent.title_id, selected_language);
                if (!nlib.icon.empty()) recent.cover = nlib.icon;
                recent.hero = nlib.hero;
                recent.screenshot = nlib.screenshots.empty() ? std::string{} : nlib.screenshots.front();
                recent.max_players = nlib.max_players;
                recent.intro = nlib.intro;
                recent.description = nlib.description;
                if (!nlib.name.empty()) recent.title = nlib.name;
                recent.addons = AddOnSummary(recent.title_id);
                recent.language = LanguageFor(recent_path, recent.title_id, selected_language).label;
            }
        }
        home.recents.push_back(std::move(recent));
        if (home.recents.size() == 7) break;
    }
    if (cancelled()) return {};
    const int installed = CountInstalledGames();
    home.system_status = fill(installed == 1 ? tr("{0} game installed") : tr("{0} games installed"),
                              {std::to_string(installed)}) +
        "  /  " + (home.setup_ready ? tr("Firmware ready") : tr("Setup required"));
    return home;
}

std::string EdenServices::clock() {
    const std::time_t now = std::time(nullptr);
    char label[32]{};
    if (const std::tm* local = std::localtime(&now))
        (void)std::strftime(label, sizeof(label), "%H:%M", local);
    return label;
}

std::string EdenServices::profile_avatar() {
#ifdef PS5_NATIVE
    // Do not scan another account's cache if the active-user lookup fails.
    // Query is deliberately issued on the launcher's background worker.
    // The controller can already have initialized UserService; calling
    // Initialize again must not cause it to be terminated underneath Pad.
    static std::once_flag user_service_once;
    std::call_once(user_service_once, [] {
        (void)sceUserServiceInitialize(nullptr);
    });
    std::int32_t user_id = -1;
    const int foreground_status = sceUserServiceGetForegroundUser(&user_id);
    // Zero is a possible foreground user ID: NiakPS5's broker accepts
    // >= 0. Rejecting zero here silently hid that user's own real avatar.
    if (foreground_status != 0 || user_id < 0) {
        static std::atomic_flag reported = ATOMIC_FLAG_INIT;
        if (!reported.test_and_set())
            std::fprintf(stderr,
                         "EDEN_PROFILE_AVATAR status=foreground_unavailable rc=%d\n",
                         foreground_status);
        return {};
    }

// Only consume NiakPS5's optional, local, explicitly owner-bound stage.
// A title is not entitled to read another account's portrait. This remains
// optional: Encore still reads its own foreground PS5 user cache directly.
    constexpr const char* staged_root="/data/NiakPS5/assets/";
    constexpr const char* staged_marker="/data/NiakPS5/assets/niak-profile-source.txt";
    if (pe::ps5::avatar_owner_marker_matches(staged_marker,
            static_cast<std::uint32_t>(user_id), "png") &&
        IsDecodableAvatarFile(std::string(staged_root)+"niak-profile.png")) {
        std::fprintf(stderr,"EDEN_PROFILE_AVATAR format=staged_png status=found\n");
        return std::string(staged_root)+"niak-profile.png";
    }
    if (pe::ps5::avatar_owner_marker_matches(staged_marker,
            static_cast<std::uint32_t>(user_id), "dds") &&
        IsDecodableAvatarFile(std::string(staged_root)+"niak-profile.dds")) {
        std::fprintf(stderr,"EDEN_PROFILE_AVATAR format=staged_dds status=found\n");
        return std::string(staged_root)+"niak-profile.dds";
    }

    // Account-scoped native cache remains the independent fallback.
    // Keep the lookup bound to the active user, never enumerate all users.
    // Some console caches contain only pre-scaled DDS avatars (no PNG).
    // Prefer the full-colour PNG, then a 128px DDS suitable for the 54px UI.
    // Directory prefixes vary between local cache revisions.
    for (const char* digits : {"%08x", "%08X"}) {
        char id[16]{};
        if (std::snprintf(id, sizeof(id), digits,
                          static_cast<unsigned>(user_id)) != 8)
            continue;
        for (const char* prefix : {"0x", "0X", ""}) {
            const std::string root =
                std::string("/system_data/priv/cache/profile/") + prefix + id + "/";
            if (IsDecodableAvatarFile(root + "avatar.png")) {
                std::fprintf(stderr, "EDEN_PROFILE_AVATAR format=png status=found\n");
                return root + "avatar.png";
            }
            for (const char* name : {"avatar128.dds", "avatar260.dds",
                                     "avatar64.dds", "avatar440.dds"}) {
                if (IsDecodableAvatarFile(root + name)) {
                    std::fprintf(stderr, "EDEN_PROFILE_AVATAR format=dds status=found\n");
                    return root + name;
                }
            }
        }
    }
    // Make the next console log actionable without exposing user identity or
    // ever searching another account's private profile cache.
    static std::atomic_flag reported_missing = ATOMIC_FLAG_INIT;
    if (!reported_missing.test_and_set()) {
        const bool marker = IsFile(staged_marker);
        const bool png = IsFile(std::string(staged_root) + "niak-profile.png");
        const bool dds = IsFile(std::string(staged_root) + "niak-profile.dds");
        std::fprintf(stderr,
                     "EDEN_PROFILE_AVATAR status=missing_for_active_user staged_marker=%d staged_png=%d staged_dds=%d\n",
                     marker, png, dds);
    }
#endif
    return {};
}

unsigned EdenServices::controllers() { return radio_input_controllers(); }

std::string EdenServices::version() {
    return Eden::kBuildVersion;
}

std::vector<pe::ui::Game> EdenServices::games() {
    return games(nullptr);
}

std::vector<pe::ui::Game> EdenServices::games(const std::atomic<bool>* cancel) {
    // The launcher reads the list beside its menu (pe/ui/library.cpp), so the metadata reader
    // is used by one thread at a time. Cancellation is sampled between titles,
    // not in the middle of metadata extraction or an in-flight file operation.
    if (cancel && cancel->load(std::memory_order_acquire)) return {};
    std::unique_lock lock(bridge_);
    std::vector<pe::ui::Game> games;
    (void)mkdir(Eden::ConfigDir().c_str(), 0777);
    (void)mkdir(Eden::CoversDir().c_str(), 0777);
    std::error_code directory_error;
    const auto entries = Eden::ReadNativeDirectory(Eden::AssetsPath("roms"), directory_error);
    if (directory_error) {
        Eden::Report("library", ("EDEN_ROM_SCAN directory_error=" +
                                 directory_error.message()).c_str());
        // Do not publish a spurious empty library on a transient PS5 mount/
        // getdents failure. Launcher::finish_scan catches the exception and
        // preserves the previous complete snapshot.
        throw std::system_error(directory_error, "ROM directory scan failed");
    }
    if (cancel && cancel->load(std::memory_order_acquire)) return games;
    eden_scan_addons(Eden::AssetsPath("updates").c_str(), Eden::AssetsPath("keys").c_str(),
                         Eden::AssetsPath("roms").c_str());
    if (cancel && cancel->load(std::memory_order_acquire)) return {};
    const int language_choice = Eden::LoadPreferences().language;
    // A failed stat or unexpected file type previously hid a title with no
    // diagnostic. Keep the UI thread free of IO: report only on this worker.
    std::size_t rom_candidates = 0;
    std::size_t stat_failures = 0;
    std::size_t non_regular = 0;
    // Enumerate local assets immediately. Enrichment is independently queued for
    // all installed titles by Launcher, so even games never selected acquire Nlib
    // banners/icons/screenshots. Disk scanning itself must stay network-free.
    for (const auto& entry : entries) {
        if (cancel && cancel->load(std::memory_order_acquire))
            return {}; // discard partial results and stop per-title disk work
        const std::string entry_name = entry.path().filename().string();
        const std::string extracted = Eden::FindDeconstructedGameMain(entry.path());
        const std::string nested_package = extracted.empty() ?
            Eden::FindNestedGamePackage(entry.path()) : std::string{};
        const bool deconstructed = !extracted.empty();
        // Persist a validated relative base input as one library entry,
        // without listing the update and DLC subtrees as independent games.
        const std::string discovered = deconstructed ? extracted : nested_package;
        const std::string file = discovered.empty() ? entry_name : entry_name + "/" + discovered;
        if (!Eden::ValidRomFilename(file)) continue;
        const std::size_t dot = file.find_last_of('.');
        std::string format = deconstructed ? "EXEFS" :
            (dot == std::string::npos ? std::string{} : file.substr(dot + 1));
        std::transform(format.begin(), format.end(), format.begin(),
                       [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
        ++rom_candidates;
        const std::string path = Eden::AssetsPath("roms/" + file);
        struct stat info {};
        if (stat(path.c_str(), &info) != 0) {
            ++stat_failures;
            if (stat_failures <= 3)
                Eden::Report("library", ("EDEN_ROM_SCAN stat_failed=" + file +
                                         " errno=" + std::to_string(errno)).c_str());
            continue;
        }
        if (!S_ISREG(info.st_mode)) {
            ++non_regular;
            continue;
        }
        char size[32]{};
        const auto complete_base_size = deconstructed ?
            ExtractedBaseBytes(entry.path(), cancel) :
            std::optional<std::uint64_t>{static_cast<std::uint64_t>(info.st_size)};
        if (cancel && cancel->load(std::memory_order_acquire)) return {};
        if (complete_base_size) {
            const double bytes = static_cast<double>(*complete_base_size);
            if (bytes >= 1073741824.0)
                std::snprintf(size, sizeof(size), "%.1f GB", bytes / 1073741824.0);
            else
                std::snprintf(size, sizeof(size), "%.1f MB", bytes / 1048576.0);
        }
        pe::ui::Game game;
        game.name = CleanTitle(entry_name);
        game.format = format;
        // Unknown size is more truthful than the 32 MB 'main' executable.
        game.size = complete_base_size ? std::string{size} : std::string{"—"};
        game.file = file;
        // A game whose data cannot be read is still listed, by its file name.
        try {
            char title[513]{};
            // The cover is replaced in one step: the menu may be loading the old one right now.
            const std::string cover = CoverPath(file);
            const std::string staged = cover + ".new";
            const int metadata = eden_extract_game_metadata(path.c_str(), Eden::AssetsPath("keys").c_str(),
                                                            staged.c_str(), title, sizeof(title));
            if (metadata & EDEN_METADATA_TITLE) {
                game.name = title;
                SaveTitle(file, game.name);
            }
            if ((metadata & EDEN_METADATA_COVER) && std::rename(staged.c_str(), cover.c_str()) == 0)
                game.cover = cover;
            else {
                (void)std::remove(staged.c_str());
                if (IsFile(cover)) game.cover = cover; // previous successful extraction
                else if (deconstructed) game.cover = ExtractedLocalCover(entry.path());
            }
            if (cancel && cancel->load(std::memory_order_acquire))
                return {}; // extraction finished; skip ID/Nlib/add-on metadata
            game.title_id = ResolveTitleId(path, file);
            const auto local_control = deconstructed ? ExtractedLocalNacp(entry.path(), language_choice)
                                                      : ExtractedSidecarMetadata{};
            if (const auto* known = Eden::Ns2Catalog::Find(game.title_id)) {
                if (local_control.name.empty()) game.name = std::string(known->name);
                SaveTitle(file, game.name);
                if (!known->publisher.empty()) game.publisher = std::string(known->publisher);
                if (!known->release_date.empty()) game.release_date = std::string(known->release_date);
                if (!known->genre.empty()) game.categories = std::string(known->genre);
                std::fprintf(stderr, "EDEN_NS2_TITLE_RESOLVED id=%016llX name=%s source=%s\n",
                             static_cast<unsigned long long>(game.title_id), game.name.c_str(),
                             local_control.name.empty() ? "offline" : "local-nacp");
            }
            if (!local_control.name.empty()) {
                game.name = local_control.name;
                if (!local_control.developer.empty()) game.developer = local_control.developer;
                SaveTitle(file, game.name);
                std::fprintf(stderr, "EDEN_EXEFS_NACP title=%016llX local_name=1 developer=%d\n",
                             static_cast<unsigned long long>(game.title_id),
                             !local_control.developer.empty());
            }
            if (game.title_id != 0) {
                const NlibEnrichment nlib = CachedNlibEnrichment(game.title_id, language_choice);
                if (!nlib.icon.empty()) game.cover = nlib.icon;
                game.hero = nlib.hero;
                game.screenshots = nlib.screenshots;
                AppendCaseScenes(game.screenshots, game.title_id);
                game.max_players = nlib.max_players;
                if (!nlib.name.empty()) game.name = nlib.name;
                game.intro = nlib.intro;
                game.description = nlib.description;
                if (!nlib.publisher.empty()) game.publisher = nlib.publisher;
                game.developer = nlib.developer;
                if (!nlib.release_date.empty()) game.release_date = nlib.release_date;
                if (!nlib.categories.empty()) game.categories = nlib.categories;
                // Render already-cached real paper scans immediately during
                // local enumeration, without waiting for network enrichment.
                const pe::ui::BoxArt cached_case = box_art(game.title_id);
                game.box_front = cached_case.front;
                game.box_back = cached_case.back;
                if (game.cover.empty() && !game.box_front.empty()) game.cover = game.box_front;
            }
            const GameLanguage language = LanguageFor(path, game.title_id, language_choice);
            game.addons = AddOnSummary(game.title_id);
            game.addons_short = AddOnSummary(game.title_id, true);
            game.language = language.label;
            game.language_note = language.note;
        } catch (const std::exception& error) {
            Eden::Report("library", (file + ": " + error.what()).c_str());
        }
        games.push_back(std::move(game));
    }

    // Metadata bridge work is finished. Home and Library start complete Nlib
    // enrichment of every installed title in background, independently of user
    // selection. A library enumeration itself must remain local/cache-only.
    lock.unlock();
    Eden::Report("library", ("EDEN_ROM_SCAN entries=" + std::to_string(entries.size()) +
                             " candidates=" + std::to_string(rom_candidates) +
                             " visible=" + std::to_string(games.size()) +
                             " stat_failures=" + std::to_string(stat_failures) +
                             " non_regular=" + std::to_string(non_regular)).c_str());

    std::sort(games.begin(), games.end(),
              [](const pe::ui::Game& a, const pe::ui::Game& b) { return a.name < b.name; });
    return games;
}

pe::ui::Game EdenServices::enrich_game_media(pe::ui::Game game) {
    return enrich_game_media(std::move(game), nullptr);
}

pe::ui::Game EdenServices::enrich_game_media(pe::ui::Game game,
                                             const std::atomic<bool>* cancel) {
    if (game.title_id == 0 ||
        (cancel && cancel->load(std::memory_order_acquire))) return game;
    const int language_choice = Eden::LoadPreferences().language;
    const std::string scanned_name = game.name;
    // Prioritize the requested ORIGINAL retail scans before any optional
    // metadata/banner/icon requests. Nlib may perform multiple slow calls;
    // previously a complete retail front could remain invisible for minutes.
    // Resolve canonical retail names locally before any Nlib request. NS2
    // extracted folders often omit spaces (e.g. DonkeyKongBananza).
    // NS1 preserves the exact previous name/filename fallback.
    if (const auto* ns2 = Eden::Ns2Catalog::Find(game.title_id)) {
        game.case_artwork_changed = EnsureRetailCase(
            game.title_id, std::string(ns2->name), scanned_name,
            language_choice, cancel);
    } else {
        game.case_artwork_changed = EnsureRetailCase(game.title_id, scanned_name, CleanTitle(game.file),
                         language_choice, cancel);
    }
    if (!(cancel && cancel->load(std::memory_order_acquire))) {
        const auto cached_case = box_art(game.title_id);
        game.box_front = cached_case.front;
        game.box_back = cached_case.back;
    }
    if (cancel && cancel->load(std::memory_order_acquire)) return game;
    NlibEnrichment enrichment = EnsureNlibEnrichment(game.title_id, language_choice, cancel);
    game.artwork_changed = enrichment.artwork_changed;
    if (!enrichment.icon.empty()) game.cover = std::move(enrichment.icon);
    else if (game.cover.empty() && !game.box_front.empty()) game.cover = game.box_front;
    if (!enrichment.hero.empty()) game.hero = std::move(enrichment.hero);
    if (!enrichment.screenshots.empty()) game.screenshots = std::move(enrichment.screenshots);
    if (enrichment.max_players > 0) game.max_players = enrichment.max_players;
    if (!enrichment.name.empty()) game.name = std::move(enrichment.name);
    else if (const auto* known = Eden::Ns2Catalog::Find(game.title_id)) game.name = std::string(known->name);
    if (!enrichment.intro.empty()) game.intro = std::move(enrichment.intro);
    if (!enrichment.description.empty()) game.description = std::move(enrichment.description);
    if (!enrichment.publisher.empty()) game.publisher = std::move(enrichment.publisher);
    if (!enrichment.developer.empty()) game.developer = std::move(enrichment.developer);
    if (!enrichment.release_date.empty()) game.release_date = std::move(enrichment.release_date);
    if (!enrichment.categories.empty()) game.categories = std::move(enrichment.categories);
    // A newly fetched localized Nlib name may match a catalog title that the
    // ROM header did not. Give it its own lookup, but never perform any HTTP
    // from the launcher draw or game-start path.
    if ((game.box_front.empty() || game.box_back.empty()) &&
        scanned_name != game.name) {
        game.case_artwork_changed |= EnsureRetailCase(game.title_id, game.name, scanned_name,
                         language_choice, cancel);
    }
    if (!(cancel && cancel->load(std::memory_order_acquire))) {
        const auto box = box_art(game.title_id);
        if (!box.front.empty()) game.box_front = box.front;
        if (!box.back.empty()) game.box_back = box.back;
        // A late local/NX2 retail-cover fetch may complete after the first
        // Nlib/cache snapshot. Always expose its real front to the game tile.
        if (game.cover.empty() && !game.box_front.empty()) game.cover = game.box_front;
        AppendCaseScenes(game.screenshots, game.title_id);
        if (game.case_artwork_changed & (8u | 16u | 32u))
            game.artwork_changed = true; // refresh GPU copies after replacement
    }
    return game;
}

pe::ui::BoxArt EdenServices::box_art(std::uint64_t title_id) {
    pe::ui::BoxArt artwork;
    if (title_id == 0) return artwork;

    // Optional local media only. Remote services need independent credentials /
    // redistribution terms; the native game-start path must never make requests.
    char id[17]{};
    std::snprintf(id, sizeof(id), "%016llX", static_cast<unsigned long long>(title_id));
    const std::string root = Eden::CoversDir() + "/box-";

    const auto find_face = [&](const char* side) -> std::string {
        for (const char* ext : {"png", "jpg", "jpeg", "tga"}) {
            const std::string path = root + side + "-" + id + "." + ext;
            struct stat info{};
            if (!IsFile(path) || stat(path.c_str(), &info) != 0 ||
                info.st_size <= 0 || info.st_size > (16LL << 20))
                continue;
            int width = 0, height = 0, channels = 0;
            bool valid = false;
            if (std::strcmp(ext, "tga") == 0) {
                // Old NS2 emergency covers were product photos, not flat
                // retail scans. Do not render their white studio canvas
                // as a genuine paper face; the worker can replace the cache
                // with region-ranked GamesDB artwork when it becomes ready.
                if (std::strcmp(side, "front") == 0) {
                    std::ifstream provenance(path + ".source");
                    std::string origin;
                    if (provenance) std::getline(provenance, origin);
                    if (origin.rfind("https://www.powerplanetonline.com", 0) == 0 ||
                        origin.rfind("https://www.euronics.ee", 0) == 0)
                        continue;
                }
                // Generated scans use uncompressed BGRA TGA. Check the whole
                // payload, then use the SAME header convention as load_tga().
                // Format sniffing through stbi_info can reject a usable TGA.
                if (ValidNlibTga(path)) {
                    std::FILE* input = std::fopen(path.c_str(), "rb");
                    if (input) {
                        unsigned char header[18]{};
                        if (std::fread(header, 1, sizeof(header), input) == sizeof(header)) {
                            width = static_cast<int>(header[12]) |
                                    (static_cast<int>(header[13]) << 8);
                            height = static_cast<int>(header[14]) |
                                     (static_cast<int>(header[15]) << 8);
                            valid = true;
                        }
                        std::fclose(input);
                    }
                }
            } else {
                valid = stbi_info(path.c_str(), &width, &height, &channels) != 0;
            }
            if (!valid ||
                width < (std::strcmp(side, "spine") == 0 ? 64 : 128) ||
                height < (std::strcmp(side, "spine") == 0 ? 600 : 128) ||
                width > 4096 || height > 4096 ||
                static_cast<std::uint64_t>(width) * height > 3840u * 2160u) {
                std::fprintf(stderr,
                    "EDEN_CASE_RESOLVE title=%016llX side=%s status=rejected ext=%s bytes=%lld dimensions=%dx%d path=%s\n",
                    static_cast<unsigned long long>(title_id), side, ext,
                    static_cast<long long>(info.st_size), width, height, path.c_str());
                continue;
            }
            std::fprintf(stderr,
                "EDEN_CASE_RESOLVE title=%016llX side=%s status=ready ext=%s bytes=%lld dimensions=%dx%d path=%s\n",
                static_cast<unsigned long long>(title_id), side, ext,
                static_cast<long long>(info.st_size), width, height, path.c_str());
            return path;
        }
        return {};
    };
    artwork.front = find_face("front");
    artwork.back = find_face("back");
    artwork.spine = find_face("spine");
    std::fprintf(stderr,
        "EDEN_CASE_RESULT title=%016llX front=%d back=%d spine=%d\n",
        static_cast<unsigned long long>(title_id),
        !artwork.front.empty(), !artwork.back.empty(), !artwork.spine.empty());
    return artwork;
}

std::string EdenServices::game_path(const std::string& file) { return Eden::AssetsPath("roms/" + file); }

bool EdenServices::game_exists(const std::string& file) {
    if (!Eden::ValidRomFilename(file)) return false;
    // A failed lstat can mean an I/O error on mounted external storage,
    // not a deleted ROM. The background presence scanner must distinguish
    // ENOENT/ENOTDIR from an indeterminate mount/EIO/permission failure,
    // otherwise two transient polls remove a valid FC27/BOTW tile.
    const std::string path = Eden::AssetsPath("roms/" + file);
    struct stat info{};
    if (lstat(path.c_str(), &info) == 0)
        return S_ISREG(info.st_mode);
    if (errno == EPERM || errno == EACCES) {
        if (stat(path.c_str(), &info) == 0)
            return S_ISREG(info.st_mode);
    }
    // Unknown != removed: keep the previous library snapshot, and let
    // subsequent polls or an explicit launch establish real file status.
    return errno != ENOENT && errno != ENOTDIR;
}

bool EdenServices::game_storage_available() {
    std::error_code error;
    return std::filesystem::is_directory(Eden::AssetsPath("roms"), error) && !error;
}

void EdenServices::arm_safe_launch() {
    // Same process: main.cpp consumes and unsets this before applying the game's settings.
    setenv("EDEN_SAFE_LAUNCH", "1", 1);
    Eden::Report("launch", "Safe launch armed for the next game only");
}

namespace {
// Share the exact override precedence between live modal reads and the
// batch catalog snapshot: only the source of the global profile changes.
bool EffectiveDockedMode(std::uint64_t title_id, const Eden::GameSettings& game,
                         int global_profile) {
    if (game.console_mode >= 0) return game.console_mode == 1;
    const int tier = game.performance_profile >= 0 &&
                             game.performance_profile < Eden::EncoreOverrides::kAuthoredProfileCount ?
                         game.performance_profile :
                     global_profile >= 0 &&
                             global_profile < Eden::EncoreOverrides::kAuthoredProfileCount ?
                         global_profile : -1;
    return tier >= 0 ? Eden::EncoreOverridesRuntime::ProfileForTitle(title_id, tier).docked : true;
}
} // namespace

bool EdenServices::docked(std::uint64_t title_id) {
    if (title_id == 0) return true;
    const Eden::GameSettings game = Eden::LoadGameSettings(title_id);
    // Keep the previous no-global-JSON fastpath for explicit per-title mode.
    if (game.console_mode >= 0) return game.console_mode == 1;
    return EffectiveDockedMode(title_id, game, Eden::LoadPreferences().performance_profile);
}

bool EdenServices::docked_for_scan(std::uint64_t title_id,
                                   const pe::ui::Preferences& snapshot) {
    if (title_id == 0) return true;
    const Eden::GameSettings game = Eden::LoadGameSettings(title_id);
    return EffectiveDockedMode(title_id, game, snapshot.performance_profile);
}

bool EdenServices::set_docked(std::uint64_t title_id, bool docked) {
    Eden::GameSettings settings = Eden::LoadGameSettings(title_id);
    settings.console_mode = docked ? 1 : 0;
    return Eden::SaveGameSettings(title_id, settings);
}

pe::ui::GameSettings EdenServices::game_settings(std::uint64_t title_id) {
    const Eden::GameSettings saved = Eden::LoadGameSettings(title_id);
    pe::ui::GameSettings result;
    result.console_mode = saved.console_mode;
    result.renderer = saved.renderer;
    result.output = saved.output;
    result.resolution = saved.resolution;
    result.filter = saved.upscaling_filter;
    result.fsr_sharpness = saved.fsr_sharpness;
    result.anti_aliasing = saved.anti_aliasing;
    result.refresh = saved.refresh;
    result.performance_profile = saved.performance_profile;
    result.controller_layout = saved.controller_layout;
    result.own_mapping = saved.own_mapping;
    result.mapping = saved.mapping;
    return result;
}

bool EdenServices::set_game_settings(std::uint64_t title_id, const pe::ui::GameSettings& settings) {
    Eden::GameSettings value;
    value.console_mode = settings.console_mode;
    value.renderer = settings.renderer;
    value.output = settings.output;
    value.resolution = settings.resolution;
    value.upscaling_filter = settings.filter;
    value.fsr_sharpness = settings.fsr_sharpness;
    value.anti_aliasing = settings.anti_aliasing;
    value.refresh = settings.refresh;
    value.performance_profile = settings.performance_profile;
    value.controller_layout = settings.controller_layout;
    value.own_mapping = settings.own_mapping;
    value.mapping = settings.mapping;
    const bool saved = Eden::SaveGameSettings(title_id, value);
    if (!saved) Eden::Report("settings", "Could not write game settings");
    return saved;
}

pe::ui::Preferences EdenServices::preferences() {
    const Eden::Preferences saved = Eden::LoadPreferences();
    pe::ui::Preferences result;
    result.hud = saved.hud;
    result.volume = saved.volume;
    result.mute = saved.mute;
    result.detailed_logging = saved.detailed_logging;
    result.renderer = saved.backend == Eden::GraphicsBackend::OpenGL ? 0 : 1;
    result.resolution = saved.resolution;
    result.filter = saved.upscaling_filter;
    result.refresh = saved.refresh;
    result.output = saved.output;
    result.performance_profile = saved.performance_profile;
    result.controller_layout = saved.controller_layout;
    result.mapping = saved.mapping;
    result.vibration = saved.vibration;
    result.vibration_strength = saved.vibration_strength;
    result.stick_deadzone = saved.stick_deadzone;
    result.language = saved.language;
    result.menu_volume = saved.menu_volume;
    result.large_text = saved.large_text;
    result.high_contrast = saved.high_contrast;
    result.reduce_motion = saved.reduce_motion;
    result.ui_theme = saved.ui_theme;
    return result;
}

bool EdenServices::set_preferences(const pe::ui::Preferences& preferences) {
    Eden::Preferences value;
    value.hud = preferences.hud;
    value.volume = preferences.volume;
    value.mute = preferences.mute;
    value.detailed_logging = preferences.detailed_logging;
    value.backend = preferences.renderer == 0 ? Eden::GraphicsBackend::OpenGL : Eden::GraphicsBackend::Vulkan;
    value.resolution = preferences.resolution;
    value.upscaling_filter = preferences.filter;
    value.fsr_sharpness = preferences.fsr_sharpness;
    value.anti_aliasing = preferences.anti_aliasing;
    value.refresh = preferences.refresh;
    value.output = preferences.output;
    value.performance_profile = preferences.performance_profile;
    value.controller_layout = preferences.controller_layout;
    value.mapping = preferences.mapping;
    value.vibration = preferences.vibration;
    value.vibration_strength = preferences.vibration_strength;
    value.stick_deadzone = preferences.stick_deadzone;
    value.language = preferences.language;
    value.menu_volume = preferences.menu_volume;
    value.large_text = preferences.large_text;
    value.high_contrast = preferences.high_contrast;
    value.reduce_motion = preferences.reduce_motion;
    value.ui_theme = preferences.ui_theme;
    const bool saved = Eden::SavePreferences(value);
    if (!saved) Eden::Report("settings", "Could not write preferences");
#ifdef PS5_NATIVE
    if (saved) {
        // Apply the toggle immediately in the launcher: no hidden running
        // stderr/stdout writers and no growing emulator log when disabled.
        Eden::NativeLogs::SetDetailed(value.detailed_logging);
        // The deep GPU/JIT hot-path counters must follow the live toggle.
        // Otherwise disabling logs leaves costly diagnostics in-game.
        Eden::Performance::detailed_gpu_profile.store(value.detailed_logging,
                                                       std::memory_order_relaxed);
        eden_network_audit_enable(value.detailed_logging ? 1 : 0);
        if (!value.detailed_logging) {
            Eden::BootTrace::Quiet(Eden::LogsDir());
            for (const char* name : {
                    "eden_log.txt", "eden_log.txt.first.txt", "eden_log.txt.old.txt"})
                (void)std::remove((Eden::UserDir() + "/log/" + name).c_str());
        }
    }
#endif
    return saved;
}

const std::vector<std::string>& EdenServices::resolution_labels() {
    return resolution_labels_;
}

const std::vector<std::string>& EdenServices::resolution_keys() {
    return resolution_keys_;
}

const std::vector<std::string>& EdenServices::filter_labels() {
    return filter_labels_;
}

const std::vector<std::string>& EdenServices::anti_aliasing_labels() {
    return anti_aliasing_labels_;
}

const std::vector<std::string>& EdenServices::performance_profile_labels() {
    return performance_profile_labels_;
}

const std::vector<std::string>& EdenServices::language_labels() {
    return language_labels_;
}

std::string EdenServices::language_region(int language) {
    static constexpr const char* kRegions[] = {TR("Japan"), TR("USA"), TR("Europe"), TR("Australia"), TR("China"),
                                               TR("Korea"), TR("Taiwan")};
    if (language < 0 || language >= int(std::size(Eden::kLanguageRegions))) return {};
    return tr(kRegions[Eden::kLanguageRegions[language]]);
}

std::string EdenServices::setup_details() {
    return setup_.empty() ?
        tr("Keys and firmware: startup checks passed. Game-specific compatibility is checked at launch.") :
        SetupMessage(setup_);
}

pe::ui::DiagnosticsInfo EdenServices::diagnostics() {
    return diagnostics(nullptr);
}

pe::ui::DiagnosticsInfo EdenServices::diagnostics(const std::atomic<bool>* cancel) {
    if (cancel && cancel->load(std::memory_order_acquire)) return {};
    pe::ui::DiagnosticsInfo result;
    result.filesystem = Eden::FilesystemAccess() ? tr("Full filesystem") : tr("Sandbox only");
    result.data_path = Eden::FilesystemAccess() ? Eden::kDataDir : Eden::UserDir();

    // RELEASE-SAFETY (FW 13.60): do not call libc statfs/statvfs, which
    // previously raised SYSTEM_ILLEGAL_FUNCTION_CALL. This directory inventory
    // now runs on a cancellable background worker; the console's filesystem
    // view also does not establish physical SSD capacity.
    result.storage_root = Eden::AssetsDir();

    const std::filesystem::path cache = std::filesystem::path{Eden::UserDir()} / "cache";
    const std::uintmax_t shader_bytes =
        TreeBytes(cache / "shader", cancel) + TreeBytes(cache / "radv", cancel) +
        TreeBytes(cache / "native-opengl", cancel) + TreeBytes(cache / "jit", cancel);
    if (cancel && cancel->load(std::memory_order_acquire)) return {};
    result.shader_cache_bytes = static_cast<std::uint64_t>(shader_bytes);
    result.shader_caches = StorageSize(shader_bytes);
    result.logs = StorageSize(TreeBytes(Eden::LogsDir(), cancel));
    if (cancel && cancel->load(std::memory_order_acquire)) return {};
    return result;
}

bool EdenServices::clear_shader_caches(std::string* message) {
    const std::filesystem::path cache = std::filesystem::path{Eden::UserDir()} / "cache";
    const std::uintmax_t before =
        TreeBytes(cache / "shader") + TreeBytes(cache / "radv") +
        TreeBytes(cache / "native-opengl") + TreeBytes(cache / "jit");
    bool ok = true;
    // Eden's per-title Vulkan/OpenGL pipeline cache lives under cache/shader. The other
    // directories are backend/JIT auxiliaries. A maintenance clear must remove all of them,
    // otherwise the launcher can report success while the active game's pipelines survive.
    for (const char* name : {"shader", "radv", "native-opengl", "jit"}) {
        std::error_code error;
        std::filesystem::remove_all(cache / name, error);
        ok = ok && !error;
    }
    if (message) {
        if (ok)
            *message = fill(tr("Cleared {0} of cache."), {StorageSize(before)});
        else
            *message = tr("Some cache files could not be removed.");
    }
    if (ok) Eden::Report("cache", "Shader/JIT caches cleared from Diagnostics");
    return ok;
}

bool EdenServices::folders(const std::string& directory, std::vector<std::string>* names) {
    bool ok = false;
    *names = ListEntries(directory, true, ok);
    return ok;
}

pe::ui::FolderInfo EdenServices::folder_info(const std::string& directory) {
    pe::ui::FolderInfo info;
    info.keys = Eden::FileExists(JoinPath(directory, "keys/prod.keys"));
    info.firmware = CountFiles(JoinPath(directory, "firmware"), {".nca"});
    const std::string roms_path = JoinPath(directory, "roms");
    const int regular = CountFiles(roms_path,
                                  {".nsp", ".xci", ".nsz", ".xcz", ".nro", ".nso",
                                   ".nca", ".nax", ".kip"});
    const int extracted = CountExeFsFolders(roms_path);
    info.games = regular < 0 || extracted < 0 ? -1 : regular + extracted;
    return info;
}

std::string EdenServices::files_folder() { return Eden::AssetsDir(); }
std::string EdenServices::saved_files_folder() { return Eden::LoadSavedAssetsDir(); }
std::string EdenServices::default_files_folder() { return Eden::kDefaultAssetsDir; }

bool EdenServices::set_files_folder(const std::string& directory) {
    if (!Eden::FilesystemAccess() || !Eden::ValidAssetsDir(directory)) return false;

    std::error_code error;
    const auto status = std::filesystem::symlink_status(directory, error);
    if (error || std::filesystem::is_symlink(status) || !std::filesystem::is_directory(status))
        return false;

    // Selecting external storage changes only the root. Every root has the exact same Encore
    // layout; individual keys/firmware/roms/etc. paths are never configurable.
    for (const char* name : {"keys", "firmware", "roms", "updates", "mods",
                             "save-import", "save-export", "ryujinx"}) {
        const std::filesystem::path child = std::filesystem::path{directory} / name;
        error.clear();
        const auto child_status = std::filesystem::symlink_status(child, error);
        if (!error && std::filesystem::exists(child_status) &&
            (std::filesystem::is_symlink(child_status) || !std::filesystem::is_directory(child_status))) {
            Eden::Report("storage", (std::string{"Unsafe storage entry: "} + child.string()).c_str());
            return false;
        }
        error.clear();
        std::filesystem::create_directories(child, error);
        if (error) {
            Eden::Report("storage", (std::string{"Could not prepare "} + name + ": " + error.message()).c_str());
            return false;
        }
    }
    const bool saved = Eden::SaveAssetsDir(directory);
    if (!saved) Eden::Report("settings", "Could not write the storage root");
    return saved;
}

int EdenServices::filesystem_access() { return Eden::FilesystemAccessStatus(); }

#ifdef EDEN_SAVE_IMPORT
// Save transfer (ryujinx_saves.h): a save comes in from save-import/<title ID>/ or a Ryujinx data
// folder in ryujinx/, and goes out to save-export/, all next to roms/.
bool EdenServices::save_transfer_available() { return true; }

pe::ui::SaveSource EdenServices::save_import_source(std::uint64_t title_id) {
    switch (eden_save_import_source(title_id)) {
    case EDEN_SAVE_FOLDER: return pe::ui::SaveSource::folder;
    case EDEN_SAVE_RYUJINX: return pe::ui::SaveSource::ryujinx;
    default: return pe::ui::SaveSource::none;
    }
}

bool EdenServices::save_import(std::uint64_t title_id, std::string* message) {
    char backup[256]{};
    switch (eden_save_import(title_id, backup, sizeof(backup))) {
    case EDEN_SAVE_DONE:
        *message = backup[0] ? tr("Imported. The save it replaced was backed up.") : tr("Imported.");
        return true;
    case EDEN_SAVE_NOTHING: {
        char title[17]{};
        std::snprintf(title, sizeof(title), "%016llX", static_cast<unsigned long long>(title_id));
        *message = fill(tr("To import, copy a Ryujinx folder to ryujinx/ or a save to save-import/{0}/, next to roms/."),
                        {title});
        return false;
    }
    case EDEN_SAVE_NO_USER:
        *message = tr("Start any game once before importing a save.");
        return false;
    default:
        *message = tr("Import failed. The current save is unchanged.");
        return false;
    }
}

bool EdenServices::save_export(std::uint64_t title_id, std::string* message) {
    char folder[256]{};
    switch (eden_save_export(title_id, folder, sizeof(folder))) {
    case EDEN_SAVE_DONE: {
        // The end of the path tells it apart: save-export/<title ID>-<date>-<time>.
        const std::string path = folder;
        const std::size_t name = path.rfind("save-export/");
        *message = fill(tr("Exported to {0}."), {name == std::string::npos ? path : path.substr(name)});
        return true;
    }
    case EDEN_SAVE_NOTHING:
        *message = tr("This game has no save to export yet.");
        return false;
    default:
        *message = tr("Export failed. Check that the storage root can be written.");
        return false;
    }
}
#else
bool EdenServices::save_transfer_available() { return false; }
pe::ui::SaveSource EdenServices::save_import_source(std::uint64_t) { return pe::ui::SaveSource::none; }
bool EdenServices::save_import(std::uint64_t, std::string*) { return false; }
bool EdenServices::save_export(std::uint64_t, std::string*) { return false; }
#endif

// Mods (headless/mods.h): what the selected storage root's mods/<title ID>/ holds for a game, and
// which of them are switched off (settings_store.h).
std::vector<pe::ui::Mod> EdenServices::mods(std::uint64_t title_id) {
    std::vector<pe::ui::Mod> result;
    const auto off = Eden::LoadDisabledMods(title_id);
    for (const Eden::Mods::Mod& mod : Eden::Mods::List(Eden::AssetsPath("mods"), title_id)) {
        std::string kind;
        const auto add = [&kind](const char* text) {
            if (!kind.empty()) kind += ", ";
            kind += tr(text);
        };
        if (mod.kinds & Eden::Mods::kCode) add(TR("Patch"));
        if (mod.kinds & Eden::Mods::kFiles) add(TR("Files"));
        if (mod.kinds & Eden::Mods::kCheats) add(TR("Cheats"));
        result.push_back({mod.name, kind, std::find(off.begin(), off.end(), mod.name) == off.end()});
    }
    return result;
}

bool EdenServices::set_mod_enabled(std::uint64_t title_id, const std::string& name, bool enabled) {
    const bool saved = Eden::SaveModEnabled(title_id, name, enabled);
    if (!saved) Eden::Report("settings", "Could not write the game's mods");
    return saved;
}

bool EdenServices::mods_enabled(std::uint64_t title_id) { return Eden::LoadModsEnabled(title_id); }

bool EdenServices::set_mods_enabled(std::uint64_t title_id, bool enabled) {
    const bool saved = Eden::SaveModsEnabled(title_id, enabled);
    if (!saved) Eden::Report("settings", "Could not write the game's mods switch");
    return saved;
}

std::string EdenServices::mods_folder(std::uint64_t title_id) {
    return "mods/" + Eden::Mods::TitleName(title_id) + "/";
}

bool EdenServices::make_mods_folder(std::uint64_t title_id) {
    const std::string root = Eden::AssetsPath("mods");
    if (!Eden::Mods::TitleFolder(root, title_id).empty()) return true;
    (void)mkdir(root.c_str(), 0777);
    return mkdir(Eden::Mods::TitleFolderToCreate(root, title_id).c_str(), 0777) == 0;
}

bool EdenServices::load_image(const std::string& path, pe::gfx::Image* image) {
    // Covers have full paths; the launcher's own art is named from its ui folder.
    const std::string resolved =
        !path.empty() && path[0] == '/' ? path : Eden::AppFile("ui/" + path);
    if (resolved.size() >= 4 && resolved.compare(resolved.size() - 4, 4, ".dds") == 0)
        return pe::gfx::load_avatar_dds(resolved, image);
    if (pe::gfx::load_tga(resolved, image))
        return true;

    // Remote enrichment (Nlib) is cached as JPEG. Decode it with the same stb_image
    // implementation already linked for game metadata/icon extraction.
    int width = 0;
    int height = 0;
    int channels = 0;
    stbi_uc* rgba = stbi_load(resolved.c_str(), &width, &height, &channels, 4);
    if (!rgba || width <= 0 || height <= 0 || width > 8192 || height > 8192) {
        if (rgba) stbi_image_free(rgba);
        return false;
    }
    image->width = width;
    image->height = height;
    image->rgba.assign(rgba, rgba + static_cast<std::size_t>(width) *
                                      static_cast<std::size_t>(height) * 4u);
    stbi_image_free(rgba);
    return true;
}
