// SPDX-License-Identifier: GPL-3.0-or-later
#include "nup_v1_vfs.h"

#include <algorithm>
#include <array>
#include <cstring>
#include <deque>
#include <functional>
#include <limits>
#include <map>
#include <memory>
#include <stdexcept>
#include <set>
#include <tuple>
#include <type_traits>
#include <utility>

#include <openssl/evp.h>
#include <openssl/sha.h>
#include <zstd.h>

namespace Eden::NupV1 {
namespace {
constexpr std::uint32_t NoDirectory = 0xFFFFFFFFU;
constexpr std::uint64_t MaxToc = 64ULL * 1024 * 1024;
constexpr std::uint64_t MaxMeta = 32ULL * 1024 * 1024;
constexpr std::uint64_t MaxNodes = 2000000;
constexpr std::size_t BlockSize = 1 << 20;
constexpr std::size_t MaxMutableRawDigestCacheBytes = 16 << 20;

void Check(bool condition, const char* reason) {
    if (!condition) throw std::runtime_error(reason);
}

template <typename T> T ReadLe(std::span<const std::uint8_t> bytes, std::size_t pos) {
    static_assert(std::is_unsigned_v<T>);
    Check(pos <= bytes.size() && sizeof(T) <= bytes.size() - pos, "truncated NUP record");
    T value{};
    for (std::size_t i = 0; i < sizeof(T); ++i)
        value |= static_cast<T>(bytes[pos + i]) << (i * 8);
    return value;
}

bool AllZero(std::span<const std::uint8_t> data) {
    return std::all_of(data.begin(), data.end(), [](std::uint8_t b) { return b == 0; });
}

bool Utf8Name(std::string_view value, bool root) {
    if (value.empty()) return root;
    if (value == "." || value == "..") return false;
    for (std::size_t i = 0; i < value.size();) {
        const auto c = static_cast<std::uint8_t>(value[i]);
        if (c == '/' || c == '\\' || c < 0x20 || c == 0x7F) return false;
        if (c < 0x80) { ++i; continue; }
        std::size_t following = 0;
        if (c >= 0xC2 && c <= 0xDF) following = 1;
        else if (c >= 0xE0 && c <= 0xEF) following = 2;
        else if (c >= 0xF0 && c <= 0xF4) following = 3;
        else return false;
        if (following >= value.size() - i) return false;
        const auto second = static_cast<std::uint8_t>(value[i + 1]);
        if (second < 0x80 || second > 0xBF) return false;
        if ((c == 0xE0 && second < 0xA0) || (c == 0xED && second > 0x9F) ||
            (c == 0xF0 && second < 0x90) || (c == 0xF4 && second > 0x8F))
            return false;
        for (std::size_t j = 2; j <= following; ++j) {
            const auto t = static_cast<std::uint8_t>(value[i + j]);
            if (t < 0x80 || t > 0xBF) return false;
        }
        i += following + 1;
    }
    return true;
}

// Metadata strings may contain slashes (unlike path components) but must
// remain valid, printable UTF-8. These limits prevent unbounded UI strings.
bool Utf8Metadata(std::string_view value, std::size_t limit) {
    if (value.empty() || value.size() > limit) return false;
    for (std::size_t i = 0; i < value.size();) {
        const auto first = static_cast<std::uint8_t>(value[i]);
        if (first < 0x20 || first == 0x7f) return false;
        if (first < 0x80) { ++i; continue; }
        std::size_t following = 0;
        if (first >= 0xC2 && first <= 0xDF) following = 1;
        else if (first >= 0xE0 && first <= 0xEF) following = 2;
        else if (first >= 0xF0 && first <= 0xF4) following = 3;
        else return false;
        if (following >= value.size() - i) return false;
        const auto second = static_cast<std::uint8_t>(value[i + 1]);
        if (second < 0x80 || second > 0xBF) return false;
        if ((first == 0xE0 && second < 0xA0) ||
            (first == 0xED && second > 0x9F) ||
            (first == 0xF0 && second < 0x90) ||
            (first == 0xF4 && second > 0x8F)) return false;
        for (std::size_t j = 2; j <= following; ++j) {
            const auto following_byte = static_cast<std::uint8_t>(value[i + j]);
            if (following_byte < 0x80 || following_byte > 0xBF) return false;
        }
        i += following + 1;
    }
    return true;
}

// Normalize BCP-47 ASCII tags without consulting UI or system locale.
// The parser rejects empty segments and control characters.
std::optional<std::string> NormalizeLanguage(std::string_view value) {
    if (value.empty() || value.size() > 35 ||
        value.front() == '-' || value.back() == '-') return std::nullopt;
    std::string result;
    result.reserve(value.size());
    char prev = '\0';
    for (const char chr : value) {
        if (chr == '-' && prev == '-') return std::nullopt;
        if ((chr < 'A' || chr > 'Z') &&
            (chr < 'a' || chr > 'z') &&
            (chr < '0' || chr > '9') && chr != '-')
            return std::nullopt;
        const char normalized = chr >= 'A' && chr <= 'Z'
                                    ? static_cast<char>(chr - 'A' + 'a') : chr;
        result.push_back(normalized);
        prev = chr;
    }
    return result;
}

bool ImageSignature(std::span<const std::uint8_t> bytes) {
    const bool jpeg = bytes.size() >= 3 &&
        bytes[0] == 0xff && bytes[1] == 0xd8 && bytes[2] == 0xff;
    const bool png = bytes.size() >= 8 &&
        bytes[0] == 0x89 && bytes[1] == 0x50 &&
        bytes[2] == 0x4e && bytes[3] == 0x47 &&
        bytes[4] == 0x0d && bytes[5] == 0x0a &&
        bytes[6] == 0x1a && bytes[7] == 0x0a;
    return jpeg || png;
}

bool NameLess(const std::string& a, const std::string& b) {
    return std::lexicographical_compare(a.begin(), a.end(), b.begin(), b.end(),
        [](unsigned char x, unsigned char y) { return x < y; });
}

std::array<std::uint8_t, 32> Hash(std::span<const std::uint8_t> bytes) {
    std::array<std::uint8_t, 32> result{};
    Check(SHA256(bytes.data(), bytes.size(), result.data()) != nullptr, "SHA-256 error");
    return result;
}

struct Digest {
    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> ctx{EVP_MD_CTX_new(), &EVP_MD_CTX_free};
    Digest() {
        Check(ctx != nullptr && EVP_DigestInit_ex(ctx.get(), EVP_sha256(), nullptr) == 1,
              "SHA-256 context failed");
    }
    void Add(std::span<const std::uint8_t> bytes) {
        Check(EVP_DigestUpdate(ctx.get(), bytes.data(), bytes.size()) == 1, "SHA-256 update failed");
    }
    std::array<std::uint8_t, 32> End() {
        std::array<std::uint8_t, 32> out{};
        unsigned int size = 0;
        Check(EVP_DigestFinal_ex(ctx.get(), out.data(), &size) == 1 && size == out.size(),
              "SHA-256 final failed");
        return out;
    }
};

std::vector<std::uint8_t> ReadChunk(const Source& source, std::uint64_t off, std::size_t size) {
    std::vector<std::uint8_t> result(size);
    Check(source.ReadAt(off, result), "short NUP source read");
    return result;
}
} // namespace

Archive::~Archive() = default;

std::unique_ptr<Archive> Archive::Mount(const Source& source, std::string* error) {
    try {
        auto archive = std::unique_ptr<Archive>(new Archive(source));
        archive->Parse();
        return archive;
    } catch (const std::exception& ex) {
        if (error) *error = ex.what();
        return nullptr;
    }
}

void Archive::Parse() {
    Check(source_.Size() >= 0x80, "short superblock");
    const auto head = ReadChunk(source_, 0, 0x80);
    Check(head[0] == 'N' && head[1] == 'U' && head[2] == 'P' && head[3] == 1,
          "wrong NUP magic/version");
    Check(ReadLe<std::uint16_t>(head, 4) == 0x80 &&
          ReadLe<std::uint16_t>(head, 6) == 1, "unsupported NUP header");
    const auto toc_at = ReadLe<std::uint64_t>(head, 8);
    const auto toc_size = ReadLe<std::uint64_t>(head, 0x10);
    const auto blob_at = ReadLe<std::uint64_t>(head, 0x38);
    const auto file_size = ReadLe<std::uint64_t>(head, 0x40);
    const auto count = ReadLe<std::uint32_t>(head, 0x48);
    Check(toc_at == 0x80 && toc_size > 0 && toc_size <= MaxToc && toc_size % 16 == 0,
          "invalid TOC dimensions");
    Check(file_size == source_.Size() && toc_at + toc_size <= file_size &&
          blob_at >= toc_at + toc_size && blob_at <= file_size && blob_at % 16 == 0,
          "invalid NUP blob bounds");
    Check(count > 0 && count <= 65536 && ReadLe<std::uint32_t>(head, 0x4C) == 0 &&
          AllZero(std::span<const std::uint8_t>(head).subspan(0x60, 0x20)),
          "unsupported superblock fields");
    const auto toc = ReadChunk(source_, toc_at, static_cast<std::size_t>(toc_size));
    const auto toc_hash = Hash(toc);
    Check(std::equal(toc_hash.begin(), toc_hash.end(), head.begin() + 0x18),
          "TOC SHA-256 mismatch");
    Check(toc[0] == 'T' && toc[1] == 'O' && toc[2] == 'C' && toc[3] == 1,
          "wrong TOC magic");
    Check(ReadLe<std::uint32_t>(toc, 4) == count &&
          ReadLe<std::uint64_t>(toc, 0x28) == 0, "inconsistent TOC header");

    const auto nd = ReadLe<std::uint64_t>(toc, 8);
    const auto nf = ReadLe<std::uint64_t>(toc, 0x10);
    const auto strings_at = ReadLe<std::uint64_t>(toc, 0x18);
    const auto strings_size = ReadLe<std::uint64_t>(toc, 0x20);
    Check(nd > 0 && nd <= MaxNodes && nf <= MaxNodes &&
          nd + nf <= MaxNodes && strings_at <= toc.size() &&
          strings_size <= toc.size() - strings_at, "oversized NUP tables");
    const std::uint64_t dirs_at = 0x30 + static_cast<std::uint64_t>(count) * 0x40;
    const std::uint64_t files_at = dirs_at + nd * 0x18;
    const std::uint64_t slots_at = files_at + nf * 0x50;
    Check(slots_at <= strings_at, "overlapping TOC tables");

    const auto name_at = [&](std::uint32_t off, std::uint32_t len, bool root) {
        Check(off <= strings_size && len <= strings_size - off, "name beyond string pool");
        const std::string value(reinterpret_cast<const char*>(toc.data() + strings_at + off), len);
        Check(Utf8Name(value, root), "invalid NUP path component");
        return value;
    };

    dirs_.reserve(static_cast<std::size_t>(nd));
    std::uint64_t total_slots = 0;
    for (std::uint64_t i = 0; i < nd; ++i) {
        const std::size_t at = static_cast<std::size_t>(dirs_at + i * 0x18);
        const auto off = ReadLe<std::uint32_t>(toc, at);
        const auto len = ReadLe<std::uint32_t>(toc, at + 4);
        const auto first = ReadLe<std::uint32_t>(toc, at + 8);
        const auto nchildren = ReadLe<std::uint32_t>(toc, at + 12);
        Check(ReadLe<std::uint64_t>(toc, at + 16) == 0, "nonzero directory reserved");
        total_slots += nchildren;
        Check(total_slots <= MaxNodes * 2, "too many children");
        dirs_.push_back({name_at(off, len, true), first, nchildren});
    }
    Check(total_slots <= (strings_at - slots_at) / 4, "child array overruns TOC");
    children_.reserve(static_cast<std::size_t>(total_slots));
    for (std::uint64_t i = 0; i < total_slots; ++i) {
        const auto id = ReadLe<std::uint32_t>(toc, static_cast<std::size_t>(slots_at + i * 4));
        Check(id < nd + nf, "child index beyond table");
        children_.push_back(id);
    }

    files_.reserve(static_cast<std::size_t>(nf));
    std::vector<std::pair<std::uint64_t, std::uint64_t>> regions;
    std::map<std::pair<std::uint64_t, std::uint64_t>,
             std::tuple<std::uint64_t, std::uint8_t, std::array<std::uint8_t, 32>>> extents;
    for (std::uint64_t i = 0; i < nf; ++i) {
        const std::size_t at = static_cast<std::size_t>(files_at + i * 0x50);
        File f{};
        f.name = name_at(ReadLe<std::uint32_t>(toc, at),
                         ReadLe<std::uint32_t>(toc, at + 4), false);
        f.size = ReadLe<std::uint64_t>(toc, at + 8);
        f.offset = ReadLe<std::uint64_t>(toc, at + 0x10);
        f.stored = ReadLe<std::uint64_t>(toc, at + 0x18);
        std::memcpy(f.digest, toc.data() + at + 0x20, 32);
        f.codec = toc[at + 0x40];
        Check(f.codec <= 1 && toc[at + 0x41] == 0 &&
              ReadLe<std::uint16_t>(toc, at + 0x42) == 0 &&
              AllZero(std::span<const std::uint8_t>(toc).subspan(at + 0x44, 12)),
              "unsupported file fields");
        if (f.size == 0) {
            Check(f.offset == 0 && f.stored == 0 && f.codec == 0, "bad empty extent");
        } else {
            Check(f.stored > 0 && f.offset >= blob_at && f.offset % 16 == 0 &&
                  f.offset <= file_size && f.stored <= file_size - f.offset &&
                  (f.codec != 0 || f.size == f.stored), "invalid extent");
            std::array<std::uint8_t, 32> digest{};
            std::memcpy(digest.data(), f.digest, 32);
            const auto [it, added] = extents.emplace(
                std::make_pair(f.offset, f.stored), std::make_tuple(f.size, f.codec, digest));
            Check(added || it->second == std::make_tuple(f.size, f.codec, digest),
                  "deduplicated extent disagrees");
            regions.emplace_back(f.offset, f.offset + f.stored);
        }
        files_.push_back(std::move(f));
    }

    member_verified_.assign(files_.size(), 0);
    std::vector<unsigned> incoming(nd);
    std::vector<std::uint8_t> slot_owners(children_.size());
    for (const auto& dir : dirs_) {
        Check(dir.first <= children_.size() &&
              dir.count <= children_.size() - dir.first, "bad directory child span");
        std::optional<std::string> previous;
        for (std::uint32_t k = 0; k < dir.count; ++k) {
            Check(slot_owners[dir.first + k]++ == 0, "child slot has multiple owners");
            const auto id = children_[dir.first + k];
            const auto& name = id < nd ? dirs_[id].name : files_[id - nd].name;
            Check(!previous || NameLess(*previous, name), "unsorted/duplicate child");
            previous = name;
            if (id < nd) {
                ++incoming[id];
                Check(incoming[id] <= 1, "directory has multiple parents");
            }
        }
    }
    Check(std::all_of(slot_owners.begin(), slot_owners.end(),
                      [](std::uint8_t uses) { return uses == 1; }),
          "unowned directory child slot");
    for (std::size_t i = 0; i < dirs_.size(); ++i)
        if (incoming[i]) Check(!dirs_[i].name.empty(), "empty nested directory name");
    auto deps = incoming;
    std::deque<std::size_t> queue;
    for (std::size_t i = 0; i < deps.size(); ++i)
        if (deps[i] == 0) queue.push_back(i);
    std::size_t visited = 0;
    while (!queue.empty()) {
        const auto d = queue.front();
        queue.pop_front();
        ++visited;
        const auto& dir = dirs_[d];
        for (std::uint32_t k = 0; k < dir.count; ++k) {
            const auto node = children_[dir.first + k];
            if (node < nd && --deps[node] == 0) queue.push_back(node);
        }
    }
    Check(visited == nd, "cyclic NUP directory references");

    Digest uuid_hash;
    unsigned base_count = 0;
    // Retain metadata only up to a fixed total budget. Large numbers of
    // package icons must not multiply guest-controlled memory consumption.
    constexpr std::size_t MaxCachedIcons = 16U * 1024 * 1024;
    std::size_t cached_icon_bytes = 0;
    std::vector<std::pair<std::uint64_t, std::uint64_t>> metadata_regions;
    for (std::uint32_t i = 0; i < count; ++i) {
        const auto at = static_cast<std::size_t>(0x30 + i * 0x40);
        Package p{};
        p.title_id = ReadLe<std::uint64_t>(toc, at);
        p.root_dir = ReadLe<std::uint32_t>(toc, at + 8);
        p.exefs_dir = ReadLe<std::uint32_t>(toc, at + 0xC);
        p.romfs_dir = ReadLe<std::uint32_t>(toc, at + 0x10);
        p.version = ReadLe<std::uint32_t>(toc, at + 0x14);
        p.kind = toc[at + 0x18];
        const auto flags = toc[at + 0x19];
        p.standalone_update = (flags & 1) != 0;
        Check(p.kind <= 2 && (flags & ~1U) == 0 &&
              ReadLe<std::uint16_t>(toc, at + 0x1A) == 0 &&
              ReadLe<std::uint32_t>(toc, at + 0x1C) == 0 &&
              AllZero(std::span<const std::uint8_t>(toc).subspan(at + 0x2C, 20)),
              "invalid package kind/flags");
        Check(p.root_dir < nd &&
              (p.exefs_dir == NoDirectory || p.exefs_dir < nd) &&
              (p.romfs_dir == NoDirectory || p.romfs_dir < nd),
              "missing package directory");
        if (p.kind == 0) ++base_count;
        if (p.kind != 1) Check(flags == 0, "standalone flag on non-update");
        const auto meta_at = ReadLe<std::uint64_t>(toc, at + 0x20);
        const auto meta_size = ReadLe<std::uint32_t>(toc, at + 0x28);
        PackageMetadata package_meta;
        std::set<std::string> localized_title_tags;
        std::set<std::string> localized_icon_tags;
        if (!meta_size) Check(meta_at == 0, "zero metadata with nonzero address");
        else {
            Check(meta_size <= MaxMeta && meta_at >= blob_at &&
                  meta_at <= file_size && meta_size <= file_size - meta_at,
                  "metadata exceeds file");
            metadata_regions.emplace_back(meta_at, meta_at + meta_size);
            const auto meta = ReadChunk(source_, meta_at, meta_size);
            std::size_t pos = 0;
            while (pos < meta.size()) {
                Check(meta.size() - pos >= 8, "truncated metadata TLV");
                const auto length = ReadLe<std::uint32_t>(meta, pos + 4);
                Check(ReadLe<std::uint16_t>(meta, pos + 2) == 0 &&
                      length <= meta.size() - pos - 8, "invalid metadata TLV");
                const auto kind = ReadLe<std::uint16_t>(meta, pos);
                const auto payload = std::span<const std::uint8_t>(
                    meta.data() + pos + 8, length);
                if (kind == 0x0002 && package_meta.control_nacp.empty()) {
                    // NACP is opaque to the platform-independent core.
                    // The pinned native vendor defines RawNACP as 0x4000;
                    // reject oversized control metadata, skip unknown sizes.
                    Check(length <= 64U * 1024U, "NUP NACP metadata too large");
                    if (length == 0x4000)
                        package_meta.control_nacp.assign(payload.begin(), payload.end());
                } else if (kind == 0x0003 && package_meta.default_icon.empty()) {
                    // Icons can be large but the UI never needs an unbounded
                    // blob. Ignore unknown encodings instead of mislabeling.
                    Check(length <= 4 * 1024 * 1024, "NUP icon metadata too large");
                    if (ImageSignature(payload) &&
                        length <= MaxCachedIcons - cached_icon_bytes) {
                        package_meta.default_icon.assign(payload.begin(), payload.end());
                        cached_icon_bytes += length;
                    }
                } else if (kind == 0x0004 || kind == 0x0005 || kind == 0x0006) {
                    const auto text = std::string_view(
                        reinterpret_cast<const char*>(payload.data()), payload.size());
                    const auto max_length = kind == 0x0004 ? 128U : 4096U;
                    Check(Utf8Metadata(text, max_length), "invalid NUP UTF-8 metadata");
                    auto& target = kind == 0x0004 ? package_meta.display_version :
                                   kind == 0x0005 ? package_meta.title :
                                                    package_meta.publisher;
                    if (target.empty()) target.assign(text);
                } else if (kind == 0x0009 || kind == 0x000A) {
                    // Repeated LocalizedRecord: u8 lang_len, language bytes,
                    // u32 data_len, data bytes. Never trust nested lengths.
                    std::size_t cursor = 0;
                    auto& seen = kind == 0x0009 ?
                                     localized_title_tags : localized_icon_tags;
                    while (cursor < payload.size()) {
                        const auto lang_len = payload[cursor++];
                        Check(lang_len > 0 && lang_len <= payload.size() - cursor,
                              "invalid NUP localized language length");
                        const auto raw_tag = std::string_view(
                            reinterpret_cast<const char*>(payload.data() + cursor), lang_len);
                        const auto tag = NormalizeLanguage(raw_tag);
                        Check(tag.has_value(), "invalid NUP localized language tag");
                        cursor += lang_len;
                        Check(payload.size() - cursor >= 4,
                              "truncated NUP localized record");
                        const auto data_len = ReadLe<std::uint32_t>(payload, cursor);
                        cursor += 4;
                        Check(data_len <= payload.size() - cursor,
                              "invalid NUP localized payload length");
                        Check(seen.insert(*tag).second && seen.size() <= 64,
                              "duplicate or excessive NUP localized entries");
                        const auto data = payload.subspan(cursor, data_len);
                        if (kind == 0x0009) {
                            const auto title = std::string_view(
                                reinterpret_cast<const char*>(data.data()), data.size());
                            Check(Utf8Metadata(title, 4096),
                                  "invalid NUP localized title UTF-8");
                            package_meta.localized_titles.emplace(*tag, title);
                        } else {
                            Check(data_len <= 4 * 1024 * 1024,
                                  "NUP localized icon too large");
                            if (ImageSignature(data) &&
                                data_len <= MaxCachedIcons - cached_icon_bytes) {
                                package_meta.localized_icons.emplace(
                                    *tag, std::vector<std::uint8_t>(data.begin(), data.end()));
                                cached_icon_bytes += data_len;
                            }
                        }
                        cursor += data_len;
                    }
                }
                pos += 8 + length;
            }
        }
        package_metadata_.push_back(std::move(package_meta));

        // ExeFS/RomFS directory references must be reachable beneath the
        // advertised package root; never trust arbitrary cross-package trees.
        const auto reachable = [&](std::uint32_t target) {
            if (target == NoDirectory) return true;
            std::vector<std::uint32_t> stack{p.root_dir};
            while (!stack.empty()) {
                const auto cur = stack.back();
                stack.pop_back();
                if (cur == target) return true;
                const auto& dir = dirs_[cur];
                for (std::uint32_t j = 0; j < dir.count; ++j) {
                    const auto node = children_[dir.first + j];
                    if (node < nd) stack.push_back(node);
                }
            }
            return false;
        };
        Check(reachable(p.exefs_dir) && reachable(p.romfs_dir),
              "package content directory outside root");
        std::array<std::uint8_t, 13> sig{};
        for (unsigned b = 0; b < 8; ++b)
            sig[b] = static_cast<std::uint8_t>(p.title_id >> (8 * b));
        for (unsigned b = 0; b < 4; ++b)
            sig[b + 8] = static_cast<std::uint8_t>(p.version >> (8 * b));
        sig[12] = p.kind;
        uuid_hash.Add(sig);
        packages_.push_back(p);
    }
    Check(base_count <= 1, "multiple base packages");
    std::set<std::uint32_t> update_versions;
    for (const auto& p : packages_) {
        if (p.kind != 1) continue;
        Check(p.standalone_update == (base_count == 0),
              "inconsistent standalone-update flag");
        Check(update_versions.insert(p.version).second,
              "duplicate update version");
    }
    // NUP is a single application's base/update bundle. A malicious update
    // claiming an unrelated base title must never shadow that game's ExeFS
    // or RomFS simply because its NCM version is larger. This is the same
    // title-base mask used by the common FileSys::GetBaseTitleID API.
    constexpr std::uint64_t BaseTitleMask = 0xFFFFFFFFFFFFE000ULL;
    std::optional<std::uint64_t> application_base;
    for (const auto& p : packages_) {
        if (p.kind == 2) continue; // Addons are isolated by the native AoC view.
        const auto base = p.title_id & BaseTitleMask;
        if (!application_base) application_base = base;
        Check(*application_base == base, "unrelated base/update title ID");
    }

    const auto uuid = uuid_hash.End();
    Check(std::equal(uuid.begin(), uuid.begin() + 16, head.begin() + 0x50),
          "NUP content UUID mismatch");
    // Identical extent reuse is permitted; partial overlap is forbidden.
    std::sort(regions.begin(), regions.end());
    regions.erase(std::unique(regions.begin(), regions.end()), regions.end());
    for (std::size_t i = 1; i < regions.size(); ++i)
        Check(regions[i - 1].second <= regions[i].first, "overlapping file extents");
    std::sort(metadata_regions.begin(), metadata_regions.end());
    for (std::size_t i = 1; i < metadata_regions.size(); ++i)
        Check(metadata_regions[i - 1].second <= metadata_regions[i].first,
              "overlapping metadata");
    for (const auto& meta : metadata_regions) {
        auto it = std::lower_bound(regions.begin(), regions.end(), meta,
            [](const auto& extent, const auto& needle) {
                return extent.second <= needle.first;
            });
        Check(it == regions.end() || it->first >= meta.second,
              "metadata overlaps file payload");
    }
}

std::string_view PackageMetadata::TitleFor(std::string_view language) const {
    if (const auto tag = NormalizeLanguage(language)) {
        auto exact = localized_titles.find(*tag);
        if (exact != localized_titles.end()) return exact->second;
        const auto cut = tag->find('-');
        if (cut != std::string::npos) {
            exact = localized_titles.find(tag->substr(0, cut));
            if (exact != localized_titles.end()) return exact->second;
        }
    }
    if (!title.empty()) return title;
    const auto english = localized_titles.find("en-us");
    if (english != localized_titles.end()) return english->second;
    return localized_titles.empty() ? std::string_view{} :
                                     std::string_view{localized_titles.begin()->second};
}

const std::vector<std::uint8_t>* PackageMetadata::IconFor(
    std::string_view language) const {
    if (const auto tag = NormalizeLanguage(language)) {
        auto exact = localized_icons.find(*tag);
        if (exact != localized_icons.end()) return &exact->second;
        const auto cut = tag->find('-');
        if (cut != std::string::npos) {
            exact = localized_icons.find(tag->substr(0, cut));
            if (exact != localized_icons.end()) return &exact->second;
        }
    }
    if (!default_icon.empty()) return &default_icon;
    const auto english = localized_icons.find("en-us");
    if (english != localized_icons.end()) return &english->second;
    return localized_icons.empty() ? nullptr : &localized_icons.begin()->second;
}

const PackageMetadata* Archive::MetadataOf(std::size_t index) const {
    return index < package_metadata_.size() ? &package_metadata_[index] : nullptr;
}

const PackageMetadata* Archive::ApplicationMetadata() const {
    for (std::size_t i = 0; i < packages_.size(); ++i)
        if (packages_[i].kind == 0) return MetadataOf(i);
    for (std::size_t i = 0; i < packages_.size(); ++i)
        if (packages_[i].kind == 1) return MetadataOf(i);
    return nullptr; // add-on-only archives do not represent an application.
}

std::optional<std::size_t> Archive::FindFile(std::size_t pkg, std::string_view path) const {
    if (pkg >= packages_.size()) return std::nullopt;
    return FindFromDir(packages_[pkg].root_dir, path);
}

std::optional<std::size_t> Archive::FindFromDir(std::uint32_t dir,
                                               std::string_view path) const {
    if (dir == NoDirectory || dir >= dirs_.size() || path.empty()) return std::nullopt;
    while (true) {
        const auto end = path.find('/');
        const auto part = path.substr(0, end);
        if (!Utf8Name(part, false)) return std::nullopt;
        const auto& parent = dirs_[dir];
        bool matched = false;
        for (std::uint32_t k = 0; k < parent.count; ++k) {
            const auto node = children_[parent.first + k];
            const auto& name = node < dirs_.size() ? dirs_[node].name
                                                   : files_[node - dirs_.size()].name;
            if (name != part) continue;
            matched = true;
            if (end == std::string_view::npos) {
                if (node >= dirs_.size()) return node - dirs_.size();
                return std::nullopt;
            }
            if (node >= dirs_.size()) return std::nullopt;
            dir = node;
            break;
        }
        if (!matched || end == std::string_view::npos) return std::nullopt;
        path.remove_prefix(end + 1);
    }
}

std::optional<std::size_t> Archive::FindPackageMember(
    std::size_t pkg, ContentView view, std::string_view path) const {
    if (pkg >= packages_.size()) return std::nullopt;
    const auto& package = packages_[pkg];
    const auto dir = view == ContentView::ExeFS ? package.exefs_dir : package.romfs_dir;
    return FindFromDir(dir, path);
}

std::optional<std::size_t> Archive::FindEffectiveMember(
    ContentView view, std::string_view path) const {
    std::optional<std::size_t> base;
    std::optional<std::size_t> newest_update;
    for (std::size_t i = 0; i < packages_.size(); ++i) {
        const auto& package = packages_[i];
        if (package.kind == 0) base = i;
        if (package.kind == 1 &&
            (!newest_update || package.version > packages_[*newest_update].version))
            newest_update = i;
    }
    if (newest_update) {
        if (const auto member = FindPackageMember(*newest_update, view, path))
            return member;
        const auto& package = packages_[*newest_update];
        const auto dir = view == ContentView::ExeFS ? package.exefs_dir : package.romfs_dir;
        if (ShadowsPath(dir, path)) return std::nullopt;
    }
    if (base) return FindPackageMember(*base, view, path);
    return std::nullopt;
}

std::optional<std::uint32_t> Archive::WalkDirectory(
    std::uint32_t dir, std::string_view path) const {
    if (dir == NoDirectory || dir >= dirs_.size()) return std::nullopt;
    if (path.empty()) return dir;
    while (true) {
        const auto end = path.find('/');
        const auto part = path.substr(0, end);
        if (!Utf8Name(part, false)) return std::nullopt;
        const auto& parent = dirs_[dir];
        std::optional<std::uint32_t> found;
        for (std::uint32_t j = 0; j < parent.count; ++j) {
            const auto node = children_[parent.first + j];
            if (node < dirs_.size() && dirs_[node].name == part) {
                found = node;
                break;
            }
        }
        if (!found) return std::nullopt;
        dir = *found;
        if (end == std::string_view::npos) return dir;
        path.remove_prefix(end + 1);
    }
}

bool Archive::ShadowsPath(std::uint32_t dir, std::string_view path) const {
    if (dir == NoDirectory || dir >= dirs_.size() || path.empty()) return false;
    while (true) {
        const auto end = path.find('/');
        const auto part = path.substr(0, end);
        if (!Utf8Name(part, false)) return false;
        const auto& parent = dirs_[dir];
        std::optional<std::uint32_t> found;
        for (std::uint32_t j = 0; j < parent.count; ++j) {
            const auto node = children_[parent.first + j];
            const auto& name = node < dirs_.size() ? dirs_[node].name
                                                    : files_[node - dirs_.size()].name;
            if (name == part) {
                found = node;
                break;
            }
        }
        if (!found) return false;
        // A file or directory with the exact path shadows the base. A file
        // encountered midway blocks all descendant lookups, not just itself.
        if (end == std::string_view::npos || *found >= dirs_.size()) return true;
        dir = *found;
        path.remove_prefix(end + 1);
    }
}

std::optional<std::vector<DirEntry>> Archive::ListFromDir(
    std::uint32_t root, std::string_view path) const {
    const auto dir = WalkDirectory(root, path);
    if (!dir) return std::nullopt;
    const auto& parent = dirs_[*dir];
    std::vector<DirEntry> entries;
    entries.reserve(parent.count);
    for (std::uint32_t j = 0; j < parent.count; ++j) {
        const auto node = children_[parent.first + j];
        if (node < dirs_.size()) {
            entries.push_back({dirs_[node].name, true, std::nullopt});
        } else {
            const auto file = static_cast<std::size_t>(node - dirs_.size());
            entries.push_back({files_[file].name, false, file});
        }
    }
    return entries;
}

std::optional<std::vector<DirEntry>> Archive::ListPackageDirectory(
    std::size_t pkg, ContentView view, std::string_view path) const {
    if (pkg >= packages_.size()) return std::nullopt;
    const auto& package = packages_[pkg];
    const auto dir = view == ContentView::ExeFS ? package.exefs_dir : package.romfs_dir;
    return ListFromDir(dir, path);
}

std::optional<std::vector<DirEntry>> Archive::ListEffectiveDirectory(
    ContentView view, std::string_view path) const {
    std::optional<std::size_t> base;
    std::optional<std::size_t> newest_update;
    for (std::size_t i = 0; i < packages_.size(); ++i) {
        const auto& p = packages_[i];
        if (p.kind == 0) base = i;
        if (p.kind == 1 &&
            (!newest_update || p.version > packages_[*newest_update].version))
            newest_update = i;
    }
    const auto base_entries = base ? ListPackageDirectory(*base, view, path)
                                   : std::optional<std::vector<DirEntry>>{};
    const auto update_entries = newest_update ?
        ListPackageDirectory(*newest_update, view, path)
        : std::optional<std::vector<DirEntry>>{};
    if (!base_entries && !update_entries) return std::nullopt;
    if (!update_entries && newest_update) {
        const auto& package = packages_[*newest_update];
        const auto dir = view == ContentView::ExeFS ? package.exefs_dir : package.romfs_dir;
        if (ShadowsPath(dir, path)) return std::nullopt;
    }
    struct ByteLess {
        bool operator()(const std::string& a, const std::string& b) const {
            return NameLess(a, b);
        }
    };
    std::map<std::string, DirEntry, ByteLess> merged;
    if (base_entries)
        for (const auto& entry : *base_entries) merged.insert_or_assign(entry.name, entry);
    if (update_entries)
        for (const auto& entry : *update_entries) merged.insert_or_assign(entry.name, entry);
    std::vector<DirEntry> result;
    result.reserve(merged.size());
    for (const auto& entry : merged) result.push_back(entry.second);
    return result;
}

std::uint64_t Archive::MemberSize(std::size_t index) const {
    return index < files_.size() ? files_[index].size : 0;
}

bool Archive::ReadMember(std::size_t index, std::uint64_t offset,
                         std::span<std::uint8_t> dst, std::string* error) const {
    try {
        Check(index < files_.size(), "unknown member");
        const auto& f = files_[index];
        Check(offset <= f.size && dst.size() <= f.size - offset, "member read outside bounds");
        const bool allow_cache = source_.AllowsVerifiedMemberCache();
        bool already_verified = false;
        if (allow_cache) {
            std::lock_guard guard(verified_mutex_);
            already_verified = member_verified_[index] != 0;
        }
        if (already_verified && f.codec == 0) {
            Check(dst.empty() || source_.ReadAt(f.offset + offset, dst),
                  "verified raw extent short read");
            return true;
        }
        std::shared_ptr<const std::vector<std::array<std::uint8_t, 32>>> raw_blocks;
        if (!allow_cache && f.codec == 0) {
            std::lock_guard guard(verified_mutex_);
            const auto found = raw_block_digests_.find(index);
            if (found != raw_block_digests_.end()) raw_blocks = found->second;
        }
        if (raw_blocks) {
            // The member's full SHA was already checked when these digests
            // were recorded. Rehash each touched raw block against that
            // immutable verified reference, even if VfsFile is mutable.
            if (dst.empty()) return true;
            const auto start_block = offset / BlockSize;
            const auto last_block = (offset + dst.size() - 1) / BlockSize;
            for (auto block = start_block; block <= last_block; ++block) {
                Check(block < raw_blocks->size(), "verified raw block outside index");
                const auto block_offset = block * BlockSize;
                const auto bytes = static_cast<std::size_t>(
                    std::min<std::uint64_t>(BlockSize, f.size - block_offset));
                const auto chunk = ReadChunk(source_, f.offset + block_offset, bytes);
                Check(Hash(chunk) == (*raw_blocks)[static_cast<std::size_t>(block)],
                      "raw member block SHA-256 mismatch");
                const auto first = std::max<std::uint64_t>(offset, block_offset);
                const auto last = std::min<std::uint64_t>(
                    offset + dst.size(), block_offset + bytes);
                if (first < last)
                    std::memcpy(dst.data() + (first - offset),
                                chunk.data() + (first - block_offset), last - first);
            }
            return true;
        }
        // A member too large for the bounded digest cache keeps the original
        // full SHA validation on every read instead of trusting old content.
        std::vector<std::array<std::uint8_t, 32>> pending_raw_blocks;
        if (!allow_cache && f.codec == 0 && f.size > 0) {
            const auto blocks = 1 + (f.size - 1) / BlockSize;
            if (blocks <= MaxMutableRawDigestCacheBytes / 32) {
                pending_raw_blocks.reserve(static_cast<std::size_t>(blocks));
            }
        }
        Digest digest;
        std::uint64_t produced = 0;
        const auto record = [&](std::span<const std::uint8_t> chunk) {
            Check(chunk.size() <= f.size - produced, "member expansion beyond declared size");
            if (!already_verified) digest.Add(chunk);
            const auto start = std::max(produced, offset);
            const auto finish = std::min(produced + chunk.size(), offset + dst.size());
            if (start < finish)
                std::memcpy(dst.data() + (start - offset),
                            chunk.data() + (start - produced), finish - start);
            produced += chunk.size();
        };
        if (f.size > 0 && f.codec == 0) {
            std::uint64_t cursor = 0;
            while (cursor < f.stored) {
                const auto count = static_cast<std::size_t>(
                    std::min<std::uint64_t>(BlockSize, f.stored - cursor));
                const auto chunk = ReadChunk(source_, f.offset + cursor, count);
                if (pending_raw_blocks.capacity() != 0)
                    pending_raw_blocks.push_back(Hash(chunk));
                record(chunk);
                cursor += count;
            }
        } else if (f.size > 0) {
            const auto head = ReadChunk(source_, f.offset,
                static_cast<std::size_t>(std::min<std::uint64_t>(f.stored, 18)));
            const auto frame_size = ZSTD_getFrameContentSize(head.data(), head.size());
            Check(frame_size == f.size, "unknown/wrong zstd frame content size");
            using StreamPtr = std::unique_ptr<ZSTD_DStream, decltype(&ZSTD_freeDStream)>;
            StreamPtr stream(ZSTD_createDStream(), &ZSTD_freeDStream);
            Check(stream != nullptr, "cannot create zstd decoder");
            Check(!ZSTD_isError(ZSTD_initDStream(stream.get())) &&
                  !ZSTD_isError(ZSTD_DCtx_setParameter(stream.get(), ZSTD_d_windowLogMax, 26)),
                  "cannot bound zstd window");
            std::vector<std::uint8_t> input;
            std::vector<std::uint8_t> output(BlockSize);
            ZSTD_inBuffer in{nullptr, 0, 0};
            std::uint64_t consumed = 0;
            while (true) {
                if (in.pos == in.size) {
                    Check(consumed < f.stored, "truncated zstd frame");
                    const auto n = static_cast<std::size_t>(
                        std::min<std::uint64_t>(BlockSize, f.stored - consumed));
                    input = ReadChunk(source_, f.offset + consumed, n);
                    consumed += n;
                    in = ZSTD_inBuffer{input.data(), input.size(), 0};
                }
                ZSTD_outBuffer out{output.data(), output.size(), 0};
                const auto before = in.pos;
                const auto status = ZSTD_decompressStream(stream.get(), &out, &in);
                Check(!ZSTD_isError(status), "invalid zstd payload");
                record(std::span<const std::uint8_t>(output.data(), out.pos));
                // Once integrity is memoized, only decode as far as this
                // range needs; the immutable source was checked in full.
                if (already_verified && produced >= offset + dst.size()) break;
                if (status == 0) {
                    Check(consumed == f.stored && in.pos == in.size,
                          "trailing zstd bytes/concatenated frames");
                    break;
                }
                Check(in.pos > before || out.pos > 0, "stalled zstd decoder");
            }
        }
        if (!already_verified) {
            Check(produced == f.size, "member decoded size mismatch");
            const auto actual = digest.End();
            Check(std::equal(actual.begin(), actual.end(), f.digest), "member SHA-256 mismatch");
            if (allow_cache) {
                std::lock_guard guard(verified_mutex_);
                member_verified_[index] = 1;
            } else if (!pending_raw_blocks.empty()) {
                const auto bytes = pending_raw_blocks.size() *
                                   sizeof(pending_raw_blocks.front());
                std::lock_guard guard(verified_mutex_);
                if (!raw_block_digests_.contains(index) &&
                    bytes <= MaxMutableRawDigestCacheBytes - raw_digest_cache_bytes_) {
                    raw_block_digests_.emplace(index,
                        std::make_shared<const std::vector<std::array<std::uint8_t, 32>>>(
                            std::move(pending_raw_blocks)));
                    raw_digest_cache_bytes_ += bytes;
                }
            }
        } else {
            Check(produced >= offset + dst.size(), "short decoded member range");
        }
        return true;
    } catch (const std::exception& ex) {
        if (error) *error = ex.what();
        return false;
    }
}
} // namespace Eden::NupV1
