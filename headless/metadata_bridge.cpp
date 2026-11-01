#include "metadata_bridge.h"
#include "game_files.h"
#include "extracted_npdm_identity.h"
#include "../vendor/encore-active/eden-core/src/core/file_sys/extracted_aoc_paths.h"
#include "assets_dir.h"
#include "diagnostics.h"
#include "glyph_version.h"
#include "ryujinx_saves.h"
#if defined(__PROSPERO__)
#include "native_directory.h"
#endif

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <map>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include <stb_image.h>

#include "common/fs/path_util.h"
#include "core/file_sys/card_image.h"
#include "core/file_sys/common_funcs.h"
#include "core/file_sys/content_archive.h"
#include "core/file_sys/control_metadata.h"
#include "core/file_sys/nca_metadata.h"
#include "core/file_sys/program_metadata.h"
#include "core/file_sys/registered_cache.h"
#include "core/file_sys/romfs.h"
#include "core/file_sys/submission_package.h"
#include "core/file_sys/vfs/vfs_real.h"
#include "core/hle/service/ns/language.h"
#include "core/hle/service/set/settings_types.h"
#include "core/loader/loader.h"

namespace {
constexpr std::array<const char*, 18> language_names{
    "AmericanEnglish", "BritishEnglish", "Japanese", "French", "German",
    "LatinAmericanSpanish", "Spanish", "Italian", "Dutch", "CanadianFrench",
    "Portuguese", "Russian", "Korean", "TraditionalChinese", "SimplifiedChinese",
    "BrazilianPortuguese", "Polish", "Thai",
};

FileSys::VirtualDir OpenControlRomFs(const FileSys::VirtualFile& file, bool xci) {
    std::shared_ptr<FileSys::NCA> control;
    if (xci) {
        FileSys::XCI image(file);
        if (image.GetStatus() != Loader::ResultStatus::Success) return {};
        control = image.GetNCAByType(FileSys::NCAContentType::Control);
    } else {
        FileSys::NSP package(file);
        if (package.GetStatus() != Loader::ResultStatus::Success) return {};
        control = package.GetNCA(FileSys::GetBaseTitleID(package.GetProgramTitleID()),
                                 FileSys::ContentRecordType::Control);
    }
    if (!control || control->GetStatus() != Loader::ResultStatus::Success) return {};
    const auto romfs = control->GetRomFS();
    return romfs ? FileSys::ExtractRomFS(romfs) : FileSys::VirtualDir{};
}

std::string ReadTitle(const FileSys::VirtualDir& romfs) {
    auto nacp = romfs->GetFile("control.nacp");
    if (!nacp) nacp = romfs->GetFile("Control.nacp");
    if (!nacp || nacp->GetSize() < 0x3000) return {};
    std::array<char, 0x200> name{};
    for (std::size_t language = 0; language < 16; ++language) {
        if (nacp->Read(reinterpret_cast<unsigned char*>(name.data()), name.size(),
                       language * 0x300) != name.size()) return {};
        name.back() = '\0';
        if (name.front()) return name.data();
    }
    return {};
}

// Read the source game's own NACP display version; this is game metadata,
// NOT the executable NSO Build ID used by EdiZon cheat tables. Unknown or
// unsupported encodings retain original in-game Nintendo artwork.
std::string ReadGlyphDisplayVersion(const FileSys::VirtualDir& romfs) {
    if (!romfs) return {};
    auto nacp = romfs->GetFile("control.nacp");
    if (!nacp) nacp = romfs->GetFile("Control.nacp");
    FileSys::RawNACP raw{};
    if (!nacp || nacp->ReadObject(&raw) != sizeof(raw)) return {};
    return Eden::GlyphVersion::FromNacp(raw.version_string);
}

// The supported-language flags of a control RomFS's NACP (bit n is NS ApplicationLanguage n); 0
// when they cannot be read.
uint32_t ReadLanguages(const FileSys::VirtualDir& romfs) {
    auto nacp = romfs->GetFile("control.nacp");
    if (!nacp) nacp = romfs->GetFile("Control.nacp");
    FileSys::RawNACP raw{};
    if (!nacp || nacp->ReadObject(&raw) != sizeof(raw)) return 0;
    return static_cast<uint32_t>(raw.supported_languages);
}

// Game file -> its language flags, kept from the Library's metadata pass over the same data.
std::map<std::string, uint32_t>& GameLanguages() {
    static std::map<std::string, uint32_t> languages;
    return languages;
}

FileSys::VirtualFile FindIcon(const FileSys::VirtualDir& romfs) {
    for (const char* language : language_names) {
        if (auto icon = romfs->GetFile(std::string{"icon_"} + language + ".dat")) return icon;
    }
    return {};
}

bool WriteTga(const FileSys::VirtualFile& icon, const char* output) {
    const auto encoded = icon->ReadAllBytes();
    int width = 0;
    int height = 0;
    int channels = 0;
    unsigned char* rgba = stbi_load_from_memory(encoded.data(), static_cast<int>(encoded.size()),
                                                 &width, &height, &channels, 4);
    if (!rgba || width <= 0 || height <= 0 || width > 4096 || height > 4096) {
        stbi_image_free(rgba);
        return false;
    }
    std::FILE* file = std::fopen(output, "wb");
    if (!file) {
        stbi_image_free(rgba);
        return false;
    }
    unsigned char header[18]{};
    header[2] = 2;
    header[12] = static_cast<unsigned char>(width);
    header[13] = static_cast<unsigned char>(width >> 8);
    header[14] = static_cast<unsigned char>(height);
    header[15] = static_cast<unsigned char>(height >> 8);
    header[16] = 32;
    header[17] = 0x28;
    bool ok = std::fwrite(header, 1, sizeof(header), file) == sizeof(header);
    std::vector<unsigned char> row(static_cast<std::size_t>(width) * 4);
    for (int y = 0; ok && y < height; ++y) {
        const unsigned char* source = rgba + static_cast<std::size_t>(y) * row.size();
        for (int x = 0; x < width; ++x) {
            row[4 * x + 0] = source[4 * x + 2];
            row[4 * x + 1] = source[4 * x + 1];
            row[4 * x + 2] = source[4 * x + 0];
            row[4 * x + 3] = source[4 * x + 3];
        }
        ok = std::fwrite(row.data(), 1, row.size(), file) == row.size();
    }
    ok = std::fclose(file) == 0 && ok;
    stbi_image_free(rgba);
    return ok;
}
}

// Extracted NS1/NS2 programs have no NSP/XCI Control NCA to query. The
// upstream loader already reads main.npdm as ProgramMetadata at boot;
// reuse its same validated parser, only for a symlink-free library selection.
// Never infer a title ID from a directory name or an update-version folder.
FileSys::VirtualFile ExtractedNpdm(const char* rom_path, FileSys::RealVfsFilesystem& vfs) {
    namespace fs = std::filesystem;
    const fs::path selected{rom_path};
    if (selected.filename() != "main") return {};
    const fs::path root{Eden::AssetsPath("roms")};
    const auto relative = selected.lexically_relative(root).generic_string();
    if (!Eden::IsSafeDeconstructedGamePath(root, relative)) return {};
    return vfs.OpenFile((selected.parent_path() / "main.npdm").string(),
                        FileSys::OpenMode::Read);
}

bool ReadExtractedProgramMetadata(const char* rom_path, FileSys::RealVfsFilesystem& vfs,
                                  FileSys::ProgramMetadata* metadata) {
    if (!metadata) return false;
    const auto npdm = ExtractedNpdm(rom_path, vfs);
    return npdm && metadata->Load(npdm) == Loader::ResultStatus::Success;
}

std::string ExtractedProgramName(const FileSys::ProgramMetadata& metadata) {
    const auto& bytes = metadata.GetName();
    std::string value;
    for (const auto c : bytes) {
        if (c == 0) break;
        // NPDM application_name is short ASCII, not a localized NACP title.
        // Refuse raw control characters and synthetic "Application" labels.
        if (c < 32 || c > 126) return {};
        value += static_cast<char>(c);
    }
    if (value.size() < 4 || value == "Application" || value == "application")
        return {};
    return value;
}

uint64_t eden_game_title_id(const char* rom_path) {
    if (!rom_path) return 0;
    Common::FS::SetEdenPath(Common::FS::EdenPath::KeysDir, Eden::AssetsPath("keys"));
    FileSys::RealVfsFilesystem vfs;
    FileSys::ProgramMetadata extracted;
    if (ReadExtractedProgramMetadata(rom_path, vfs, &extracted) && extracted.GetTitleID() != 0)
        return extracted.GetTitleID();
    // NS2 NPDM may contain valid ACI0 identity but extra kernel metadata
    // not yet understood by the NS1 ProgramMetadata parser. Recover ONLY
    // the title ID for library art/indexing, not kernel permissions/boot.
    const std::filesystem::path selected{rom_path};
    const auto roms_root = std::filesystem::path(Eden::AssetsPath("roms"));
    if (selected.filename() == "main" &&
        Eden::IsSafeDeconstructedGamePath(
            roms_root, selected.lexically_relative(roms_root).generic_string())) {
        const auto id = Eden::ExtractedNpdm::TitleId(selected.parent_path() / "main.npdm");
        if (id != 0) {
            std::fprintf(stderr, "EDEN_EXEFS_NPDM_ID_FALLBACK title=%016llX\\n",
                         static_cast<unsigned long long>(id));
            return id;
        }
    }
    const auto file = vfs.OpenFile(rom_path, FileSys::OpenMode::Read);
    if (!file) return 0;
    std::string path = rom_path;
    std::transform(path.begin(), path.end(), path.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (Eden::IsCardImageFile(path)) {
        FileSys::XCI image(file);
        return image.GetStatus() == Loader::ResultStatus::Success ? image.GetProgramTitleID() : 0;
    }
    if (Eden::IsPackageFile(path)) {
        FileSys::NSP package(file);
        return package.GetStatus() == Loader::ResultStatus::Success ? package.GetProgramTitleID() : 0;
    }
    return 0;
}

int eden_extract_game_metadata(const char* rom_path, const char* keys_dir,
                               const char* cover_tga_path, char* title,
                               size_t title_capacity) {
    if (!rom_path || !keys_dir || !cover_tga_path || !title || title_capacity == 0) return 0;
    title[0] = '\0';
    Common::FS::SetEdenPath(Common::FS::EdenPath::KeysDir, keys_dir);
    FileSys::RealVfsFilesystem vfs;
    FileSys::ProgramMetadata extracted;
    if (ReadExtractedProgramMetadata(rom_path, vfs, &extracted)) {
        const std::string name = ExtractedProgramName(extracted);
        if (!name.empty()) {
            std::snprintf(title, title_capacity, "%s", name.c_str());
            return EDEN_METADATA_TITLE;
        }
        return 0; // Name missing; preserve filesystem label and allow Nlib via NPDM title ID.
    }
    const auto file = vfs.OpenFile(rom_path, FileSys::OpenMode::Read);
    if (!file) return 0;
    std::string path = rom_path;
    std::transform(path.begin(), path.end(), path.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    // Direct NRO/NSO/NCA/NAX/KIP inputs have their own core loaders; they
    // are not PFS/HFS containers and have no package Control RomFS.
    if (!Eden::IsPackageFile(path) && !Eden::IsCardImageFile(path)) return 0;
    const auto romfs = OpenControlRomFs(file, Eden::IsCardImageFile(path));
    if (!romfs) return 0;
    GameLanguages()[rom_path] = ReadLanguages(romfs);

    int result = 0;
    const auto extracted_title = ReadTitle(romfs);
    if (!extracted_title.empty()) {
        std::snprintf(title, title_capacity, "%s", extracted_title.c_str());
        result |= EDEN_METADATA_TITLE;
    }
    if (const auto icon = FindIcon(romfs); icon && WriteTga(icon, cover_tga_path))
        result |= EDEN_METADATA_COVER;
    return result;
}

uint32_t eden_game_supported_languages(const char* rom_path, const char* keys_dir) {
    if (!rom_path || !keys_dir) return 0;
    if (const auto known = GameLanguages().find(rom_path); known != GameLanguages().end()) return known->second;
    try {
        Common::FS::SetEdenPath(Common::FS::EdenPath::KeysDir, keys_dir);
        FileSys::RealVfsFilesystem vfs;
        const auto file = vfs.OpenFile(rom_path, FileSys::OpenMode::Read);
        if (!file) return 0;
        std::string path = rom_path;
        std::transform(path.begin(), path.end(), path.begin(),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (!Eden::IsPackageFile(path) && !Eden::IsCardImageFile(path)) return 0;
        const auto romfs = OpenControlRomFs(file, Eden::IsCardImageFile(path));
        if (!romfs) return 0;
        return GameLanguages()[rom_path] = ReadLanguages(romfs);
    } catch (const std::exception& error) {
        std::fprintf(stderr, "[ProsperoEden] languages: %s\n", error.what());
        return 0;
    }
}

namespace {
struct AddOns {
    bool update_present = false;
    std::string update;
    unsigned dlc = 0;
    uint32_t languages = 0;  // the update's own language flags (its control data replaces the game's)
};
// Base title ID -> its update and DLC files, from the last eden_scan_addons.
std::map<uint64_t, AddOns>& ScannedAddOns() {
    static std::map<uint64_t, AddOns> scanned;
    return scanned;
}
bool& UpdatesScanCompleted() {
    static bool completed = false;
    return completed;
}
std::mutex& ScannedAddOnsMutex() {
    static std::mutex mutex;
    return mutex;
}
std::mutex& ScanAddOnsJobMutex() {
    static std::mutex mutex;
    return mutex;
}
// Both the map and completion flag are protected by ScannedAddOnsMutex.
// A scanner builds its snapshot privately, publishing only at completion.
// Never hold this mutex while reading/decrypting game files.
}

void eden_scan_addons(const char* updates_dir, const char* keys_dir, const char* roms_dir) {
    // Serialise concurrent library rescans: otherwise an older scan can
    // publish after a later refresh, replacing fresh update metadata.
    // The job lock is independent of the short reader snapshot lock.
    const std::lock_guard scan_job_guard{ScanAddOnsJobMutex()};
    // The library scan may overlap a game launch. Mutating a std::map while
    // the launcher reads metadata is undefined behavior, including crashes.
    // Build off-thread/off-lock and atomically publish a complete snapshot.
    std::map<uint64_t, AddOns> scanned;
    const auto publish = [&](bool complete) {
        std::lock_guard lock{ScannedAddOnsMutex()};
        ScannedAddOns().swap(scanned);
        UpdatesScanCompleted() = complete;
    };
    {
        std::lock_guard lock{ScannedAddOnsMutex()};
        ScannedAddOns().clear();
        UpdatesScanCompleted() = false;
    }
    if (!updates_dir || !keys_dir) return;
    try {
        Common::FS::SetEdenPath(Common::FS::EdenPath::KeysDir, keys_dir);
        FileSys::RealVfsFilesystem vfs;
        std::vector<FileSys::VirtualDir> add_on_roots;
        std::vector<std::string> scan_paths;
        // Preserve the legacy global content directory, but do not let an
        // absent directory prevent add-ons collocated with installed titles.
        const auto append_root = [&](const std::filesystem::path& path) {
            if (!Eden::IsSafeExtractedDirectory(path)) return;
            if (auto dir = vfs.OpenDirectory(path.string(), FileSys::OpenMode::Read)) {
                add_on_roots.push_back(std::move(dir));
                scan_paths.push_back(path.string());
            }
        };
        append_root(updates_dir);
        if (roms_dir && Eden::IsSafeExtractedDirectory(roms_dir)) {
            // Enumerate immediate game roots; scan each for named add-on
            // containers with a bounded traversal. Never recursively open
            // a game's extracted base RomFS just to find update packages.
            std::error_code error;
            std::size_t scanned_titles = 0;
            for (std::filesystem::directory_iterator it{
                     roms_dir, std::filesystem::directory_options::skip_permission_denied, error},
                 end;
                 !error && it != end && scanned_titles++ < 2048; it.increment(error)) {
                const auto path = it->path();
                if (!Eden::IsSafeExtractedDirectory(path)) continue;
                if (Eden::IsAddOnContainerName(path.filename().string())) {
                    append_root(path); // /roms/updates or /roms/dlc
                    continue;
                }
                for (const auto& directory : Eden::FindAddOnContentDirectories(path))
                    append_root(directory);
            }
        }
        if (add_on_roots.empty()) {
            // No add-ons is a complete scan only if the old global directory
            // is missing, not present-but-unreadable.
            std::error_code error;
            const bool global_exists = std::filesystem::exists(updates_dir, error);
            if (!error && !global_exists) publish(true);
            return;
        }
        const FileSys::ExternalContentProvider provider(std::move(add_on_roots));
        for (const auto& entry : provider.ListEntriesFilter(FileSys::TitleType::Update, std::nullopt, std::nullopt)) {
            auto& addons = scanned[FileSys::GetBaseTitleID(entry.title_id)];
            addons.update_present = true;
            if (!addons.update.empty()) continue;
            // Newest first; the display version comes from the update's own control data.
            if (const auto versions = provider.ListUpdateVersions(entry.title_id); !versions.empty()) {
                addons.update = versions.front().version_string.empty()
                    ? "v" + std::to_string(versions.front().version) : versions.front().version_string;
            } else if (const auto version = provider.GetEntryVersion(entry.title_id)) {
                addons.update = "v" + std::to_string(*version);
            }
            if (const auto control = provider.GetEntry(entry.title_id, FileSys::ContentRecordType::Control);
                control && control->GetStatus() == Loader::ResultStatus::Success)
                if (const auto romfs = control->GetRomFS())
                    if (const auto files = FileSys::ExtractRomFS(romfs)) addons.languages = ReadLanguages(files);
        }
        std::set<uint64_t> dlc;
        for (const auto& entry : provider.ListEntriesFilter(FileSys::TitleType::AOC, std::nullopt, std::nullopt))
            if (dlc.insert(entry.title_id).second)
                ++scanned[FileSys::GetBaseTitleID(entry.title_id)].dlc;
        // Match guest aoc:u: extracted, ID-addressed read-only DLC counts
        // alongside genuine packaged AOC without duplicating either ID.
        // Never infer ownership from a directory name like "bonus".
        for (const auto& entry : FileSys::ExtractedAoc::Scan(scan_paths))
            if (dlc.insert(entry.title_id).second)
                ++scanned[FileSys::GetBaseTitleID(entry.title_id)].dlc;
        publish(true);
    } catch (const std::exception& error) {
        std::fprintf(stderr, "[ProsperoEden] updates: %s\n", error.what());
        // Fail closed. The incomplete scan never becomes visible to readers.
    }
}

// Native launch-time display-art version: take the detected update when one
// exists, otherwise parse the base game's NACP. A missing/failed updates
// scan must NOT mistake an updated game for an unpatched base version.
int eden_game_glyph_display_version(const char* rom_path, const char* keys_dir,
                                    uint64_t title_id, char* output, size_t capacity) {
    if (output && capacity) output[0] = '\0';
    if (!rom_path || !keys_dir || !title_id || !output || capacity == 0) return 0;
    try {
        std::string version;
        bool scanned_update = false;
        {
            const std::lock_guard lock{ScannedAddOnsMutex()};
            if (!UpdatesScanCompleted()) return 0;
            const auto& entries = ScannedAddOns();
            const auto found = entries.find(FileSys::GetBaseTitleID(title_id));
            if (found != entries.end() && found->second.update_present) {
                // An installed update with unreadable version fails closed.
                scanned_update = true;
                version = found->second.update;
            }
        }
        if (!scanned_update) {
            Common::FS::SetEdenPath(Common::FS::EdenPath::KeysDir, keys_dir);
            FileSys::RealVfsFilesystem vfs;
            const auto file = vfs.OpenFile(rom_path, FileSys::OpenMode::Read);
            if (!file) return 0;
            std::string extension = std::filesystem::path(rom_path).extension().string();
            std::transform(extension.begin(), extension.end(), extension.begin(),
                [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
            if (!Eden::IsPackageFile(extension) && !Eden::IsCardImageFile(extension))
                return 0;
            const auto control = OpenControlRomFs(file, Eden::IsCardImageFile(extension));
            version = ReadGlyphDisplayVersion(control);
        }
        if (version.empty() || version.size() >= capacity) return 0;
        std::snprintf(output, capacity, "%s", version.c_str());
        return 1;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "[ProsperoEden] glyph source version: %s\n", error.what());
        return 0;
    }
}

int eden_game_language(const char* rom_path, const char* keys_dir, uint64_t title_id, int chosen) {
    const auto& codes = Service::Set::available_language_codes;
    if (chosen < 0 || chosen >= static_cast<int>(codes.size())) return chosen;
    uint32_t supported = 0;
    {
        const std::lock_guard lock{ScannedAddOnsMutex()};
        const auto& scanned = ScannedAddOns();
        if (const auto found = scanned.find(FileSys::GetBaseTitleID(title_id));
            title_id && found != scanned.end() && !found->second.update.empty())
            supported = found->second.languages;
    }
    if (!supported) supported = eden_game_supported_languages(rom_path, keys_dir);
    namespace NS = Service::NS;
    const auto application = NS::ConvertToApplicationLanguage(codes[static_cast<std::size_t>(chosen)]);
    const auto* priorities = application ? NS::GetApplicationLanguagePriorityList(*application) : nullptr;
    if (!supported || !priorities) return chosen;
    for (const auto language : *priorities) {
        if ((supported & NS::GetSupportedLanguageFlag(language)) == 0) continue;
        const auto match = NS::ConvertToLanguageCode(language);
        for (std::size_t i = 0; match && i < codes.size(); ++i)
            if (codes[i] == *match) return static_cast<int>(i);
    }
    return chosen;
}

int eden_game_addons(uint64_t title_id, char* update_version, size_t capacity, unsigned* dlc_count) {
    if (update_version && capacity) update_version[0] = '\0';
    if (dlc_count) *dlc_count = 0;
    AddOns snapshot;
    {
        const std::lock_guard lock{ScannedAddOnsMutex()};
        const auto& scanned = ScannedAddOns();
        const auto found = scanned.find(FileSys::GetBaseTitleID(title_id));
        if (!title_id || found == scanned.end()) return 0;
        snapshot = found->second;
    }
    if (update_version && capacity) std::snprintf(update_version, capacity, "%s", snapshot.update.c_str());
    if (dlc_count) *dlc_count = snapshot.dlc;
    return !snapshot.update.empty() || snapshot.dlc != 0;
}

namespace {
// The save folder name of the profile games use: Eden's user 0, the first valid entry of
// profiles.dat (0x10-byte header, then 0xC8-byte entries starting with the 16-byte UUID), written
// as Eden's save paths spell it (upper 64 bits, then lower). Eden creates the file on the first
// game boot; without it the one existing user save folder is used.
std::string EdenUserFolder(const std::filesystem::path& saves, std::string& error) {
    std::vector<char> data;
    const std::string profiles = Eden::UserDir() + "/nand/system/save/8000000000000010/su/avators/profiles.dat";
    if (Eden::RyujinxSaves::ReadFile(profiles, data) && data.size() >= 0x650) {
        for (std::size_t offset = 0x10; offset + 0xC8 <= 0x650; offset += 0xC8) {
            uint64_t low = 0, high = 0;
            std::memcpy(&low, data.data() + offset, sizeof(low));
            std::memcpy(&high, data.data() + offset + 8, sizeof(high));
            if (!low && !high) continue;
            char name[33];
            std::snprintf(name, sizeof(name), "%016llX%016llX", static_cast<unsigned long long>(high),
                          static_cast<unsigned long long>(low));
            return name;
        }
    }
    std::error_code list_error;
    std::vector<std::string> users;
    for (const auto& entry : Eden::RyujinxSaves::ListFolder(saves, list_error)) {
        const std::string name = entry.path().filename().string();
        if (name.size() == 32 && name != std::string(32, '0')) users.push_back(name);
    }
    if (users.size() == 1) return users.front();
    error = "start any game once first, so ProsperoEden creates its user";
    return {};
}
} // namespace

namespace {
struct SaveSource {
    int kind = EDEN_SAVE_NONE;
    std::vector<Eden::RyujinxSaves::Save> saves;
};
// A save folder copied by hand comes before a Ryujinx data folder: it names the game itself.
SaveSource FindSaveSource(uint64_t title_id) {
    std::string error;
    SaveSource source;
    source.saves = Eden::RyujinxSaves::FindFolderSaves(Eden::AssetsPath("save-import"), title_id, error);
    if (!source.saves.empty()) {
        source.kind = EDEN_SAVE_FOLDER;
        return source;
    }
    source.saves = Eden::RyujinxSaves::FindSaves(Eden::AssetsPath("ryujinx"), title_id, error);
    if (!source.saves.empty()) source.kind = EDEN_SAVE_RYUJINX;
    return source;
}
std::string TitleName(uint64_t title_id) {
    char title[17];
    std::snprintf(title, sizeof(title), "%016llX", static_cast<unsigned long long>(title_id));
    return title;
}
std::string TimeStamp() {
    char stamp[32] = "now";
    const std::time_t now = std::time(nullptr);
    if (const std::tm* local = std::localtime(&now)) std::strftime(stamp, sizeof(stamp), "%Y%m%d-%H%M%S", local);
    return stamp;
}
void PutPath(char* path, size_t capacity, const std::string& value) {
    if (path && capacity) std::snprintf(path, capacity, "%s", value.c_str());
}
} // namespace

int eden_save_import_source(uint64_t title_id) {
    return title_id ? FindSaveSource(title_id).kind : EDEN_SAVE_NONE;
}

int eden_save_import(uint64_t title_id, char* path, size_t capacity) {
    namespace fs = std::filesystem;
    PutPath(path, capacity, "");
    const SaveSource source = title_id ? FindSaveSource(title_id) : SaveSource{};
    if (source.saves.empty()) return EDEN_SAVE_NOTHING;
    std::string error;
    const fs::path root = fs::path{Eden::UserDir()} / "nand" / "user" / "save" / "0000000000000000";
    const std::string user = EdenUserFolder(root, error);
    if (user.empty()) {
        Eden::Report("save import", error.c_str());
        return EDEN_SAVE_NO_USER;
    }
    const std::string title = TitleName(title_id);
    const fs::path backups = fs::path{Eden::BackupDir()} / "save-import";
    bool replaced = false;
    if (!Eden::RyujinxSaves::Import(source.saves, root / user / title, root / std::string(32, '0') / title, backups,
                                    title + "-" + TimeStamp(), error, &replaced)) {
        Eden::Report("save import", error.c_str());
        return EDEN_SAVE_FAILED;
    }
    if (replaced) PutPath(path, capacity, backups.string());
    Eden::Report("save import", (title + (source.kind == EDEN_SAVE_FOLDER ? " from save-import" : " from ryujinx")).c_str());
    return EDEN_SAVE_DONE;
}

int eden_save_export(uint64_t title_id, char* path, size_t capacity) {
    namespace fs = std::filesystem;
    PutPath(path, capacity, "");
    if (!title_id) return EDEN_SAVE_NOTHING;
    std::string error;
    const fs::path root = fs::path{Eden::UserDir()} / "nand" / "user" / "save" / "0000000000000000";
    const std::string user = EdenUserFolder(root, error);
    if (user.empty()) return EDEN_SAVE_NOTHING;
    const std::string title = TitleName(title_id);
    const fs::path target = fs::path{Eden::AssetsPath("save-export")} / (title + "-" + TimeStamp());
    if (!Eden::RyujinxSaves::Export(root / user / title, root / std::string(32, '0') / title, target, error)) {
        Eden::Report("save export", error.c_str());
        return error == "no save yet" ? EDEN_SAVE_NOTHING : EDEN_SAVE_FAILED;
    }
    PutPath(path, capacity, target.string());
    Eden::Report("save export", target.string().c_str());
    return EDEN_SAVE_DONE;
}

const char* eden_startup_error() {
    static const std::string error = []() -> std::string {
        try {
            const std::string keys = Eden::AssetsPath("keys");
            const std::string firmware = Eden::AssetsPath("firmware");
            Common::FS::SetEdenPath(Common::FS::EdenPath::KeysDir, keys);
            FileSys::RealVfsFilesystem vfs;
            const auto prod = vfs.OpenFile(std::string{keys} + "/prod.keys", FileSys::OpenMode::Read);
            if (!prod || !prod->GetSize())
                return "Missing or empty keys/prod.keys in " + Eden::AssetsDir() + ".";
            auto& manager = Core::Crypto::KeyManager::Instance();
            if (!manager.HasKey(Core::Crypto::S256KeyType::Header))
                return "prod.keys could not supply an NCA header key. Replace it with a valid key dump.";
            std::error_code ec;
#if defined(__PROSPERO__)
            const auto entries = Eden::ReadNativeDirectory(firmware, ec);
#else
            std::vector<std::filesystem::directory_entry> entries;
            for (std::filesystem::directory_iterator it{firmware, ec}, end; !ec && it != end; it.increment(ec))
                entries.push_back(*it);
#endif
            if (ec) return "Cannot read firmware/ in " + Eden::AssetsDir() + ". Install extracted firmware NCAs.";
            unsigned count = 0;
            bool version = false;
            for (const auto& entry : entries) {
                if (entry.path().extension() != ".nca") continue;
                ++count;
                const auto file = vfs.OpenFile(entry.path().string(), FileSys::OpenMode::Read);
                if (!file) return "A firmware NCA cannot be read. Reinstall the firmware dump.";
                FileSys::NCA nca(file);
                if (nca.GetStatus() != Loader::ResultStatus::Success)
                    return "Firmware NCA validation failed (code " +
                        std::to_string(static_cast<unsigned>(nca.GetStatus())) +
                        "). Check that firmware and prod.keys are compatible.";
                if (nca.GetTitleId() == 0x0100000000000809ULL && nca.GetRomFS()) {
                    const auto romfs = FileSys::ExtractRomFS(nca.GetRomFS());
                    const auto file = romfs ? romfs->GetFile("file") : FileSys::VirtualFile{};
                    version |= file && file->GetSize() >= 0x100 && file->ReadBytes(0x100).size() == 0x100;
                }
            }
            if (!count) return "No firmware NCAs found in " + Eden::AssetsPath("firmware") + ".";
            if (!version) return "Firmware SystemVersion data is missing or unreadable. Install a complete firmware dump.";
            return {};
        } catch (...) {
            return "Setup validation failed. Check that firmware and key files are readable and valid.";
        }
    }();
    return error.c_str();
}
