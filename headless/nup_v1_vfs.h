// SPDX-License-Identifier: GPL-3.0-or-later
// Read-only NUP v1 VFS core. Not wired into the PS5 loader or game catalogue.
// No game IDs, keys, title-dependent hacks, GPU or host filesystem assumptions.
#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace Eden::NupV1 {

// Source lifetime must exceed Archive lifetime. ReadAt must return exactly the
// requested bytes or false. Immutable sources may cache successful SHA-256 checks;
// mutable sources MUST opt out, so each read is fully reverified.
class Source {
public:
    virtual ~Source() = default;
    virtual std::uint64_t Size() const = 0;
    virtual bool ReadAt(std::uint64_t offset, std::span<std::uint8_t> dst) const = 0;
    // Set false for externally mutable VFS files; invalidates cached integrity.
    virtual bool AllowsVerifiedMemberCache() const { return true; }
};

enum class ContentView : std::uint8_t { ExeFS, RomFS };

struct DirEntry {
    std::string name;
    bool directory{};
    std::optional<std::size_t> file_index; // set only for files
};

struct Package {
    std::uint64_t title_id{};
    std::uint32_t version{};
    std::uint8_t kind{}; // base 0, update 1, addon 2
    bool standalone_update{};
    std::uint32_t root_dir{};
    std::uint32_t exefs_dir{};
    std::uint32_t romfs_dir{};
};

// Optional NUP metadata. Never trusted as the program identity; NPDM is
// authoritative and is parsed separately by FileSys::ProgramMetadata.
struct PackageMetadata {
    std::string title;
    std::string publisher;
    std::string display_version;
    std::vector<std::uint8_t> default_icon;
    // Opaque, size-checked vendor NACP blob. Never executed or used as
    // program identity; the native bridge may consult its AoC base ID.
    std::vector<std::uint8_t> control_nacp;
    std::map<std::string, std::string> localized_titles;
    std::map<std::string, std::vector<std::uint8_t>> localized_icons;

    // No dependency on frontend settings. Exact BCP-47 tag, primary-language
    // fallback, default language; no guesswork about the user's locale.
    std::string_view TitleFor(std::string_view language) const;
    const std::vector<std::uint8_t>* IconFor(std::string_view language) const;
};

class Archive final {
public:
    // Mount checks all structure, TOC SHA-256, UUID, paths, DAG/cycles and
    // extents. Payload verification is performed on every ReadMember.
    static std::unique_ptr<Archive> Mount(const Source& source, std::string* error = nullptr);
    ~Archive();
    Archive(const Archive&) = delete;
    Archive& operator=(const Archive&) = delete;

    const std::vector<Package>& Packages() const { return packages_; }
    const PackageMetadata* MetadataOf(std::size_t index) const;
    // Prefer application base metadata, otherwise first standalone update.
    const PackageMetadata* ApplicationMetadata() const;
    std::size_t FileCount() const { return files_.size(); }

    // Paths are package-root-relative, with '/' separators. No traversal.
    std::optional<std::size_t> FindFile(std::size_t package_index,
                                        std::string_view relative_path) const;
    // Look beneath the explicit ExeFS/RomFS node in the selected package.
    std::optional<std::size_t> FindPackageMember(std::size_t package_index,
                                                 ContentView view,
                                                 std::string_view relative_path) const;
    // Pick the highest NCM update version in this archive and shadow the base
    // on matching paths. For base-less archives, only standalone updates apply.
    // Add-ons remain separate and are addressed by FindPackageMember.
    std::optional<std::size_t> FindEffectiveMember(ContentView view,
                                                   std::string_view relative_path) const;
    // Enumerate immediate children; nullopt means the directory is absent.
    // Enables a later FileSys::VirtualDir adapter without unpacking the NUP.
    std::optional<std::vector<DirEntry>> ListPackageDirectory(
        std::size_t package_index, ContentView view,
        std::string_view relative_path = {}) const;
    std::optional<std::vector<DirEntry>> ListEffectiveDirectory(
        ContentView view, std::string_view relative_path = {}) const;
    // Reads exactly dst.size() bytes, never past member bounds. First access
    // verifies the ENTIRE member SHA-256 with bounded memory; subsequent
    // accesses reuse this verification only because Source is immutable.
    // Zstd ranges still decompress from the beginning; no unbounded cache.
    // Callers MUST discard dst if false is returned.
    bool ReadMember(std::size_t file_index, std::uint64_t offset,
                    std::span<std::uint8_t> dst, std::string* error = nullptr) const;
    std::uint64_t MemberSize(std::size_t file_index) const;

private:
    explicit Archive(const Source& source) : source_(source) {}
    void Parse();
    std::optional<std::size_t> FindFromDir(std::uint32_t dir,
                                           std::string_view relative_path) const;
    std::optional<std::uint32_t> WalkDirectory(std::uint32_t root,
                                               std::string_view relative_path) const;
    bool ShadowsPath(std::uint32_t root, std::string_view relative_path) const;
    std::optional<std::vector<DirEntry>> ListFromDir(std::uint32_t root,
                                                     std::string_view relative_path) const;

    struct Directory {
        std::string name;
        std::uint32_t first{};
        std::uint32_t count{};
    };
    struct File {
        std::string name;
        std::uint64_t size{};
        std::uint64_t offset{};
        std::uint64_t stored{};
        std::uint8_t codec{};
        std::uint8_t digest[32]{};
    };

    const Source& source_;
    mutable std::mutex verified_mutex_;
    mutable std::vector<std::uint8_t> member_verified_; // valid only for immutable Sources
    std::vector<Package> packages_;
    std::vector<PackageMetadata> package_metadata_;
    std::vector<Directory> dirs_;
    std::vector<File> files_;
    std::vector<std::uint32_t> children_;
};

} // namespace Eden::NupV1
