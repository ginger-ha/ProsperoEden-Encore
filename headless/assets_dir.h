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
inline bool HasFirmwareNca(const std::filesystem::path& folder) {
    if (!StorageDirectory(folder)) return false;
    std::error_code ec;
#if defined(__PROSPERO__)
    const auto entries = ReadNativeDirectory(folder, ec);
    if (ec) return false;
    for (const auto& entry : entries) {
        const auto path = entry.path();
        if (path.extension() == ".nca" && StorageRegular(path)) return true;
    }
#else
    std::size_t visited = 0;
    for (std::filesystem::directory_iterator it{folder,
             std::filesystem::directory_options::skip_permission_denied, ec}, end;
         !ec && it != end && visited++ < 2048; it.increment(ec)) {
        if (it->path().extension() == ".nca" && StorageRegular(it->path())) return true;
    }
#endif
    return false;
}
inline bool HasExtractedSystemCode(const std::filesystem::path& folder) {
    return StorageDirectory(folder) &&
           StorageRegular(folder / ".ns2jb-firmware-dump.json") &&
           StorageRegular(folder / "firmware-dump-named.json") &&
           StorageRegular(folder / "ncm-system-programs.bin");
}
// Explicit family folders take priority over the legacy flat storage path.
// The flat layout is still preferred over any guessed/unmarked location.
// Nested wrappers from dumps are accepted only at known, bounded levels.
inline std::string ResolveFirmwarePath(SwitchFamily family) {
    namespace fs = std::filesystem;
    const fs::path root{AssetsDir()};
    const auto try_candidate = [&](const fs::path& candidate) {
        // Every candidate below has a statically known ancestry under root.
        const fs::path relative = candidate.lexically_relative(root);
        fs::path segment = root;
        if (!StorageDirectory(root)) return false;
        for (const auto& part : relative) {
            segment /= part;
            if (!StorageDirectory(segment)) return false;
        }
        return family == SwitchFamily::Switch1 ? HasFirmwareNca(candidate)
                                                : HasExtractedSystemCode(candidate);
    };
    const char* explicit1[] = {"firmware/ns1", "firmware/switch1",
                               "ns1/firmware", "switch1/firmware",
                               "ns1", "switch1", "firmware"};
    const char* explicit2[] = {"firmware/ns2", "firmware/switch2",
                               "firmware/ns2-extracted", "ns2/firmware",
                               "switch2/firmware", "ns2", "switch2",
                               "firmware", "firmware/firmware"};
    const char* const* locations = family == SwitchFamily::Switch1 ? explicit1 : explicit2;
    const std::size_t n = family == SwitchFamily::Switch1
        ? std::size(explicit1) : std::size(explicit2);
    for (std::size_t i = 0; i < n; ++i) {
        const fs::path candidate = root / locations[i];
        if (try_candidate(candidate)) return candidate.string();
        // Some dumps have an extra `firmware/` wrapper.
        if (family == SwitchFamily::Switch2 && locations[i] != std::string_view{"firmware"}) {
            if (try_candidate(candidate / "firmware")) return (candidate / "firmware").string();
        }
    }
    return (root / "firmware").string();
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
