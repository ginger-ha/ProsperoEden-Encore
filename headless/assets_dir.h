// SPDX-License-Identifier: GPL-3.0-or-later
// The storage root for game/user-supplied files. Internal storage is /data/prosperoeden by
// default; an external selection changes only this root, never the required subfolder layout.
// Resolved once per process; a new root applies after Encore is reopened.
#pragma once
#include <array>
#include <filesystem>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>
#if defined(__PROSPERO__)
#include "native_directory.h"
#endif

#include "settings_store.h"
#include "storage_paths.h"

namespace Eden {
// One storage root, one schema. Internal storage defaults to /data/prosperoeden; an optional
// external root is saved as a single path and must contain the same keys/, firmware/, roms/,
// updates/, mods/, save-import/, save-export/ and ryujinx/ layout. Without filesystem access the
// app can only see its packaged/sandbox assets/ fallback.
inline std::string ResolveAssetsDir() {
    if (!FilesystemAccess()) return AppFile("assets");
    if (std::string saved = LoadSavedAssetsDir(); !saved.empty())
        return saved;
    return kDefaultAssetsDir;
}

inline const std::string& AssetsDir() {
    static const std::string directory = ResolveAssetsDir();
    return directory;
}
// Firmware and keys are independently discovered for each console family.
// All paths remain inside the selected storage root; never cross into a symlink.
enum class SwitchFamily { Switch1, Switch2 };

inline bool StorageRegular(const std::filesystem::path& path) {
    std::error_code ec;
    const auto status = std::filesystem::symlink_status(path, ec);
    return !ec && std::filesystem::is_regular_file(status) &&
           !std::filesystem::is_symlink(status);
}
inline bool StorageDirectory(const std::filesystem::path& path) {
    std::error_code ec;
    const auto status = std::filesystem::symlink_status(path, ec);
    return !ec && std::filesystem::is_directory(status) &&
           !std::filesystem::is_symlink(status);
}
// Console family and storage format are orthogonal. Never assume NS2==dump
// or NS1==NCA: either generation may use encrypted NCAs, extracted code or ZIP.
enum class FirmwareFormat { None, Nca, Extracted, Zip };
inline bool StorageTitleId(std::string_view name) {
    if (name.size() != 16) return false;
    for (char ch : name)
        if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') ||
              (ch >= 'A' && ch <= 'F'))) return false;
    return true;
}
inline FirmwareFormat DetectFirmwareFormat(const std::filesystem::path& folder) {
    namespace fs = std::filesystem;
    if (!StorageDirectory(folder)) return FirmwareFormat::None;
    if (StorageRegular(folder / "firmware-dump-named.json") &&
        StorageRegular(folder / "ncm-system-programs.bin"))
        return FirmwareFormat::Extracted;
    if (StorageRegular(folder / "main.npdm") ||
        StorageRegular(folder / "exefs/main.npdm"))
        return FirmwareFormat::Extracted;
    std::error_code ec;
#if defined(__PROSPERO__)
    const auto entries = ReadNativeDirectory(folder, ec);
#else
    std::vector<fs::directory_entry> entries;
    for (fs::directory_iterator it{folder, fs::directory_options::skip_permission_denied, ec}, end;
         !ec && it != end && entries.size() < 2048; it.increment(ec))
        entries.push_back(*it);
#endif
    if (ec) return FirmwareFormat::None;
    bool archive = false, extracted = false;
    for (const auto& entry : entries) {
        const fs::path path = entry.path();
        if (StorageRegular(path)) {
            if (path.extension() == ".nca") return FirmwareFormat::Nca;
            if (path.extension() == ".zip") archive = true;
        } else if (StorageDirectory(path) && StorageTitleId(path.filename().string())) {
            if (StorageRegular(path / "main.npdm")) extracted = true;
        }
    }
    if (extracted) return FirmwareFormat::Extracted;
    return archive ? FirmwareFormat::Zip : FirmwareFormat::None;
}
inline bool HasFirmwareNca(const std::filesystem::path& folder) {
    return DetectFirmwareFormat(folder) == FirmwareFormat::Nca;
}
inline bool HasExtractedSystemCode(const std::filesystem::path& folder) {
    return DetectFirmwareFormat(folder) == FirmwareFormat::Extracted;
}
inline bool FirmwareHasNs2Identity(const std::filesystem::path& dir) {
    if (StorageRegular(dir / ".ns2jb-firmware-dump.json")) return true;
    // A 040... system-program folder is NS2 evidence; no NCA-only guessing.
    std::error_code ec;
#if defined(__PROSPERO__)
    const auto entries = ReadNativeDirectory(dir, ec);
#else
    std::vector<std::filesystem::directory_entry> entries;
    for (std::filesystem::directory_iterator it{dir,
         std::filesystem::directory_options::skip_permission_denied, ec}, end;
         !ec && it != end && entries.size() < 512; it.increment(ec))
        entries.push_back(*it);
#endif
    if (ec) return false;
    for (const auto& entry : entries) {
        const auto p = entry.path();
        const std::string name = p.filename().string();
        if (StorageDirectory(p) && StorageTitleId(name) &&
            name.substr(0, 3) == "040" && StorageRegular(p / "main.npdm"))
            return true;
    }
    return false;
}
inline bool FirmwareHasNs1Identity(const std::filesystem::path& dir) {
    // A 010... extracted system title is NS1 evidence; .nca alone is not.
    std::error_code ec;
#if defined(__PROSPERO__)
    const auto entries = ReadNativeDirectory(dir, ec);
#else
    std::vector<std::filesystem::directory_entry> entries;
    for (std::filesystem::directory_iterator it{dir,
         std::filesystem::directory_options::skip_permission_denied, ec}, end;
         !ec && it != end && entries.size() < 512; it.increment(ec))
        entries.push_back(*it);
#endif
    if (ec) return false;
    for (const auto& entry : entries) {
        const auto p = entry.path();
        const std::string name = p.filename().string();
        if (StorageDirectory(p) && StorageTitleId(name) &&
            name.substr(0, 3) == "010" && StorageRegular(p / "main.npdm"))
            return true;
    }
    return false;
}
// Explicit family folder wins, but only when it contains a recognizable
// firmware format; a flat NCA remains assigned to NS1 for backward compatibility.
// Flat extracted data requires identifying contents, not a guessed generation.
inline std::string ResolveFirmwarePath(SwitchFamily family) {
    namespace fs = std::filesystem;
    const fs::path root{AssetsDir()};
    const auto valid = [&](const fs::path& p) {
        if (!StorageDirectory(root)) return false;
        fs::path walk = root;
        for (const auto& part : p.lexically_relative(root)) {
            walk /= part;
            if (!StorageDirectory(walk)) return false;
        }
        return DetectFirmwareFormat(p) != FirmwareFormat::None;
    };
    constexpr std::array<std::string_view, 9> ns1{
        "firmware/ns1", "firmware/switch1", "ns1/firmware",
        "switch1/firmware", "ns1", "switch1",
        "firmware/ns1-extracted", "firmware/switch1-extracted", "firmware"};
    constexpr std::array<std::string_view, 10> ns2{
        "firmware/ns2", "firmware/switch2", "firmware/ns2-extracted",
        "ns2/firmware", "switch2/firmware", "ns2", "switch2",
        "firmware/switch2-extracted", "firmware", "firmware/firmware"};
    const auto check_explicit = [&](std::string_view name) -> std::string {
        fs::path p = root / name;
        if (valid(p)) return p.string();
        if (valid(p / "firmware")) return (p / "firmware").string();
        return {};
    };
    if (family == SwitchFamily::Switch1) {
        for (auto name : ns1) {
            if (name == "firmware") continue;
            if (auto p = check_explicit(name); !p.empty()) return p;
        }
    } else {
        for (auto name : ns2) {
            if (name == "firmware" || name == "firmware/firmware") continue;
            if (auto p = check_explicit(name); !p.empty()) return p;
        }
    }
    const fs::path flat = root / "firmware";
    if (valid(flat)) {
        const auto kind = DetectFirmwareFormat(flat);
        if (family == SwitchFamily::Switch2 &&
            kind == FirmwareFormat::Extracted && FirmwareHasNs2Identity(flat))
            return flat.string();
        if (family == SwitchFamily::Switch1 &&
            (kind == FirmwareFormat::Nca ||
             (kind == FirmwareFormat::Extracted && FirmwareHasNs1Identity(flat))))
            return flat.string();
        // Do not claim an unlabelled ZIP or NCA belongs to Switch 2.
    }
    if (family == SwitchFamily::Switch2 && valid(flat / "firmware") &&
        FirmwareHasNs2Identity(flat / "firmware")) return (flat / "firmware").string();
    // Nonexistent default is intentional, and never passed off as detected.
    return (root / "firmware" /
            (family == SwitchFamily::Switch1 ? "ns1" : "ns2")).string();
}
inline std::string ResolveKeysPath(SwitchFamily family) {
    namespace fs = std::filesystem;
    const fs::path root{AssetsDir()};
    const char* explicit1[] = {"keys/ns1", "keys/switch1",
                               "ns1/keys", "switch1/keys", "keys"};
    const char* explicit2[] = {"keys/ns2", "keys/switch2",
                               "ns2/keys", "switch2/keys", "keys"};
    const char* const* locations = family == SwitchFamily::Switch1 ? explicit1 : explicit2;
    const std::size_t n = family == SwitchFamily::Switch1
        ? std::size(explicit1) : std::size(explicit2);
    for (std::size_t i = 0; i < n; ++i) {
        const fs::path candidate = root / locations[i];
        if (!StorageDirectory(root)) break;
        const fs::path relative = candidate.lexically_relative(root);
        fs::path segment = root;
        bool safe = true;
        for (const auto& part : relative) {
            segment /= part;
            if (!StorageDirectory(segment)) { safe = false; break; }
        }
        if (safe && StorageRegular(candidate / "prod.keys"))
            return candidate.string();
    }
    return (root / "keys").string();
}
// Compatibility: all existing NS1 consumers, including the native BIS
// system-NCA loader and KeyManager path, use the detected NS1 root.
// The NS2 metadata/service inventory is separate and never masquerades as
// an NS1 NCA firmware or an AES prod.keys file.
inline std::string AssetsPath(std::string_view child) {
    if (child == "firmware") return ResolveFirmwarePath(SwitchFamily::Switch1);
    if (child == "keys") return ResolveKeysPath(SwitchFamily::Switch1);
    return AssetsDir() + "/" + std::string(child);
}
inline std::string Ns2FirmwarePath() { return ResolveFirmwarePath(SwitchFamily::Switch2); }
inline std::string Ns2KeysPath() { return ResolveKeysPath(SwitchFamily::Switch2); }
} // namespace Eden
