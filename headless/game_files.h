// SPDX-FileCopyrightText: Copyright 2026 Oliv3rmoon
// SPDX-License-Identifier: GPL-3.0-or-later
// File selection for the nine extensions recognized by Encore's game picker:
// NSP/XCI, their NCZ-compressed NSZ/XCZ variants, and direct NRO/NSO/NCA/NAX/KIP.
// Direct inputs can require external program contents and are not guaranteed
// to boot. Internal .ncz, NSO LZ4 and ZBIC/zstd are not standalone games.
#pragma once
#include <algorithm>
#include <cctype>
#include <charconv>
#include <cstdint>
#include <filesystem>
#include <string>
#include <string_view>
#include <system_error>
#include <vector>

namespace Eden {
inline bool EndsWithNoCase(std::string_view name, std::string_view suffix) {
    if (name.size() < suffix.size()) return false;
    name.remove_prefix(name.size() - suffix.size());
    for (std::size_t i = 0; i < suffix.size(); ++i)
        if (std::tolower(static_cast<unsigned char>(name[i])) != suffix[i]) return false;
    return true;
}
// Read as an NSP: a package of NCAs.
inline bool IsPackageFile(std::string_view name) {
    return EndsWithNoCase(name, ".nsp") || EndsWithNoCase(name, ".nsz");
}
// Read as an XCI: a game card's image.
inline bool IsCardImageFile(std::string_view name) {
    return EndsWithNoCase(name, ".xci") || EndsWithNoCase(name, ".xcz");
}
inline bool IsNupFile(std::string_view name) {
#ifdef EDEN_NUP_V1_RUNTIME
    // Only a P5-qualified runtime may offer NUP to the game picker.
    // The core's signature probe still decides whether it can be loaded.
    return EndsWithNoCase(name, ".nup");
#else
    (void)name;
    return false;
#endif
}
// Eden also has dedicated NRO, NSO, NCA, NAX and KIP loaders. These may be
// standalone homebrew, program partitions or system components, not necessarily
// complete game containers. Keep them selectable; let the native core loader
// determine whether enough content exists to boot the selection.
inline bool IsDirectLoaderFile(std::string_view name) {
    return EndsWithNoCase(name, ".nro") || EndsWithNoCase(name, ".nso") ||
           EndsWithNoCase(name, ".nca") || EndsWithNoCase(name, ".nax") ||
           EndsWithNoCase(name, ".kip");
}
inline bool IsGameFile(std::string_view name) {
    return IsPackageFile(name) || IsCardImageFile(name) ||
           IsDirectLoaderFile(name) || IsNupFile(name);
}
// Folder classification runs for every ROM scan entry. Match the fixed ASCII
// tokens directly rather than allocating and lowercasing a temporary string.
inline bool StartsWithNoCase(std::string_view name, std::string_view lowercase_prefix) {
    if (name.size() < lowercase_prefix.size()) return false;
    for (std::size_t i = 0; i < lowercase_prefix.size(); ++i)
        if (std::tolower(static_cast<unsigned char>(name[i])) != lowercase_prefix[i])
            return false;
    return true;
}
inline bool EqualsNoCase(std::string_view name, std::string_view lowercase) {
    return name.size() == lowercase.size() && StartsWithNoCase(name, lowercase);
}
inline bool IsAddOnContainerName(std::string_view name) {
    return EqualsNoCase(name, "updates") || EqualsNoCase(name, "update") ||
           EqualsNoCase(name, "patches") || EqualsNoCase(name, "patch") ||
           EqualsNoCase(name, "dlc") || EqualsNoCase(name, "aoc") ||
           EqualsNoCase(name, "addon") || EqualsNoCase(name, "addons") ||
           EqualsNoCase(name, "add-on") || EqualsNoCase(name, "add-ons") ||
           EqualsNoCase(name, "add_on");
}
// Apply the same update/DLC safeguard to newly discovered packages and
// previously saved selections. A stale persisted path is not proof of a base.
inline bool IsReservedAddOnPackageStem(std::string_view name) {
    if (IsAddOnContainerName(name)) return true;
    for (const char* prefix : {"update_", "update-", "patch_", "patch-",
                               "dlc_", "dlc-", "aoc_", "aoc-", "addon_", "addon-"}) {
        if (StartsWithNoCase(name, prefix)) return true;
    }
    return false;
}
// Extracted AOC stores can also sit beneath arbitrary wrapper names.
// Discover only canonical 16-digit hex AOC Title IDs; the vendor filesystem
// revalidates IDs and the actual read-only RomFS before mounting.
inline bool LooksLikeExtractedAocTitleId(std::string_view name) {
    if (name.size() != 16) return false;
    std::uint64_t id = 0;
    const auto [end, error] =
        std::from_chars(name.data(), name.data() + name.size(), id, 16);
    return error == std::errc{} && end == name.data() + name.size() &&
           (id & 0x1fffU) >= 0x1000U && (id & 0x1fffU) <= 0x17ffU;
}
inline bool IsExtractedAssetFolderName(std::string_view name) {
    return EqualsNoCase(name, "romfs") || EqualsNoCase(name, "exefs");
}

// A saved extracted title is either <title>/main (legacy), or
// <title>/[subdirectories]/exefs/main. The first component is always the
// title folder in roms/. Nested updates/DLC must never become base titles.
// No arbitrary file paths, parent traversal or symlinked entries are allowed.
inline bool IsDeconstructedGameSelection(std::string_view name) {
    constexpr std::string_view suffix{"/main"};
    if (!name.ends_with(suffix)) return false;
    name.remove_suffix(suffix.size());
    if (name.empty() || name.size() > 250) return false;
    std::size_t segments = 0;
    std::string_view last;
    while (!name.empty()) {
        const auto slash = name.find('/');
        const auto segment = name.substr(0, slash);
        if (segment.empty() || segment == "." || segment == ".." ||
            IsAddOnContainerName(segment) || (segment.size() == 5 && EndsWithNoCase(segment, "romfs")))
            return false;
        for (unsigned char c : segment)
            if (c < 32 || c == 127 || c == '\\') return false;
        last = segment;
        ++segments;
        if (segments > 8) return false;
        if (slash == std::string_view::npos) break;
        name.remove_prefix(slash + 1);
    }
    return segments == 1 || (segments >= 2 && last.size() == 5 && EndsWithNoCase(last, "exefs"));
}

// Symlink-free detection avoids treating arbitrary ROM directories or
// symlink targets outside the selected storage root as launchable titles.
inline bool IsDeconstructedGameDirectory(const std::filesystem::path& folder) {
    namespace fs = std::filesystem;
    std::error_code error;
    const auto directory_status = fs::symlink_status(folder, error);
    if (error || !fs::is_directory(directory_status) || fs::is_symlink(directory_status))
        return false;
    for (const char* name : {"main", "main.npdm"}) {
        error.clear();
        const auto status = fs::symlink_status(folder / name, error);
        if (error || !fs::is_regular_file(status) || fs::is_symlink(status))
            return false;
    }
    return true;
}
// Avoid following symlinks at every directory level, not just at main.npdm.
inline bool IsSafeExtractedDirectory(const std::filesystem::path& folder) {
    std::error_code error;
    const auto status = std::filesystem::symlink_status(folder, error);
    return !error && std::filesystem::is_directory(status) &&
           !std::filesystem::is_symlink(status);
}

// Returns a title-relative file path such as "main" or
// "base/exefs/main". The search is bounded, deterministic and scans only
// under the selected top-level title; it never descends into RomFS/assets,
// patches or add-on folders.
inline std::string FindDeconstructedGameMain(const std::filesystem::path& title) {
    namespace fs = std::filesystem;
    if (!IsSafeExtractedDirectory(title)) return {};
    // Root-level content stores are not games, even when an update happens
    // to carry its own valid ExeFS. Only <title>/base is a launchable title.
    const auto root_name = title.filename().string();
    if (IsAddOnContainerName(root_name) || (root_name.size() == 5 && EndsWithNoCase(root_name, "romfs")))
        return {};
    if (IsDeconstructedGameDirectory(title)) return "main";
    // Canonical dumps must remain discoverable even when this title folder
    // has hundreds of unrelated assets. Probe only validated, symlink-free
    // base/ExeFS paths before the generic bounded wrapper search.
    for (const char* base_name : {"base", "Base", "BASE"}) {
        const auto base = title / base_name;
        if (!IsSafeExtractedDirectory(base)) continue;
        for (const char* exefs_name : {"exefs", "ExeFS", "EXEFS"}) {
            const auto executable = base / exefs_name;
            if (IsSafeExtractedDirectory(executable) &&
                IsDeconstructedGameDirectory(executable))
                return std::string(base_name) + "/" + exefs_name + "/main";
        }
    }
    std::size_t visited = 0;
    const auto search = [&](const auto& self, const fs::path& dir,
                            const std::string& relative, unsigned depth) -> std::string {
        if (depth > 6 || ++visited > 128) return {};
        if (const auto leaf = dir.filename().string();
            leaf.size() == 5 && EndsWithNoCase(leaf, "exefs") && IsDeconstructedGameDirectory(dir))
            return relative + "/main";
        std::error_code error;
        std::vector<fs::path> subdirs;
        std::size_t examined = 0;
        for (fs::directory_iterator it{dir, fs::directory_options::skip_permission_denied, error},
                                    end;
             !error && it != end; it.increment(error)) {
            // Invalid/unrelated files previously escaped the directory limit:
            // a large folder could stall the library scan indefinitely.
            // Refuse partial wrapper results rather than select an accidental
            // ExeFS from an unsorted subset of an oversized directory.
            if (++examined > 512 || subdirs.size() >= 128) return {};
            const auto path = it->path();
            const auto name = path.filename().string();
            if (name.empty() || name.front() == '.' ||
                (name.size() == 5 && EndsWithNoCase(name, "romfs")) || IsAddOnContainerName(name))
                continue;
            if (IsSafeExtractedDirectory(path)) subdirs.push_back(path);
        }
        // Prefer base, then exefs, then other nested extraction folders.
        std::sort(subdirs.begin(), subdirs.end(), [](const fs::path& a, const fs::path& b) {
            const auto rank = [](const fs::path& p) {
                const auto name = p.filename().string();
                return name.size() == 4 && EndsWithNoCase(name, "base") ? 0 :
                       name.size() == 5 && EndsWithNoCase(name, "exefs") ? 1 : 2;
            };
            if (rank(a) != rank(b)) return rank(a) < rank(b);
            return a.filename().string() < b.filename().string();
        });
        for (const auto& path : subdirs) {
            const auto segment = path.filename().string();
            const auto next = relative.empty() ? segment : relative + "/" + segment;
            if (const auto found = self(self, path, next, depth + 1); !found.empty())
                return found;
        }
        return {};
    };
    return search(search, title, "", 0);
}

inline bool IsSafeDeconstructedGamePath(const std::filesystem::path& roms_root,
                                        std::string_view selection) {
    namespace fs = std::filesystem;
    if (!IsDeconstructedGameSelection(selection) || !IsSafeExtractedDirectory(roms_root))
        return false;
    fs::path path = roms_root;
    const fs::path relative{std::string(selection)};
    for (const auto& part : relative.parent_path()) {
        path /= part;
        if (!IsSafeExtractedDirectory(path)) return false;
    }
    return IsDeconstructedGameDirectory(path);
}

// Accept packaged base titles inside a title folder, while excluding extracted
// updates/DLC and unsafe path components. Content type still needs metadata.
inline bool IsNestedGameFileSelection(std::string_view selection) {
    if (selection.empty() || selection.size() > 255) return false;
    if (!IsPackageFile(selection) && !IsCardImageFile(selection) &&
        !IsNupFile(selection)) return false;
    const auto last_slash = selection.find_last_of('/');
    if (last_slash == std::string_view::npos || last_slash == 0 ||
        last_slash == selection.size() - 1) return false;
    const auto basename = selection.substr(last_slash + 1);
    const auto extension_dot = basename.find_last_of('.');
    if (basename.front() == '.' || extension_dot == std::string_view::npos ||
        IsReservedAddOnPackageStem(basename.substr(0, extension_dot)))
        return false;
    std::size_t levels = 0;
    while (!selection.empty()) {
        const auto slash = selection.find('/');
        const auto segment = selection.substr(0, slash);
        if (segment.empty() || segment == "." || segment == "..") return false;
        for (const unsigned char c : segment)
            if (c < 32 || c == 127 || c == '\\') return false;
        if (slash == std::string_view::npos) break;
        if (IsAddOnContainerName(segment) || (segment.size() == 5 && EndsWithNoCase(segment, "romfs")))
            return false;
        if (++levels > 8) return false;
        selection.remove_prefix(slash + 1);
    }
    return levels >= 1;
}

// Look for a packaged base, allowing one or more ordinary wrapper folders.
// Prefer a uniquely named "base.*" or "game.*" package. If multiple possible
// base packages exist, do not guess or accidentally launch an update/DLC.
inline std::string FindNestedGamePackage(const std::filesystem::path& title) {
    namespace fs = std::filesystem;
    if (!IsSafeExtractedDirectory(title)) return {};
    const auto root_name = title.filename().string();
    if (IsAddOnContainerName(root_name) || (root_name.size() == 5 && EndsWithNoCase(root_name, "romfs")))
        return {};
    std::vector<std::string> candidates;
    std::size_t visited = 0;
    bool incomplete = false;
    const auto scan = [&](const auto& self, const fs::path& directory,
                          const std::string& relative, unsigned depth) -> void {
        if (incomplete || depth > 6) return;
        if (++visited > 128 || candidates.size() > 64) {
            incomplete = true;
            return;
        }
        std::error_code error;
        std::vector<fs::path> subdirs;
        std::size_t examined = 0;
        for (fs::directory_iterator it{directory, fs::directory_options::skip_permission_denied, error},
                                    end;
             !error && it != end; it.increment(error)) {
            // Never select a base from a truncated, iteration-order-dependent
            // subset that may hide a competing package or an update.
            if (++examined > 512) {
                incomplete = true;
                return;
            }
            const auto path = it->path();
            const auto name = path.filename().string();
            if (name.empty() || name.front() == '.' || IsAddOnContainerName(name) ||
                (name.size() == 5 && EndsWithNoCase(name, "romfs"))) continue;
            // One non-following stat per entry. The old directory probe and
            // subsequent file probe both called symlink_status for every NSP.
            std::error_code entry_error;
            const auto status = fs::symlink_status(path, entry_error);
            if (entry_error || fs::is_symlink(status)) continue;
            if (fs::is_directory(status)) {
                subdirs.push_back(path);
                continue;
            }
            if (!fs::is_regular_file(status) ||
                (!IsPackageFile(name) && !IsCardImageFile(name) &&
                 !IsNupFile(name))) continue;
            if (IsReservedAddOnPackageStem(path.stem().string())) continue;
            const auto candidate = relative.empty() ? name : relative + "/" + name;
            // The validator consumes a ROM-root-relative persisted selection.
            // A package in the title folder itself is still nested from roms/.
            const auto selection = title.filename().string() + "/" + candidate;
            if (IsNestedGameFileSelection(selection)) candidates.push_back(candidate);
        }
        if (error) {
            incomplete = true;
            return;
        }
        std::sort(subdirs.begin(), subdirs.end(), [](const fs::path& a, const fs::path& b) {
            const auto a_name = a.filename().string();
            const auto b_name = b.filename().string();
            if (a_name == "base" && b_name != "base") return true;
            if (b_name == "base" && a_name != "base") return false;
            return a_name < b_name;
        });
        for (const auto& path : subdirs) {
            if (incomplete) return;
            if (visited >= 128 || candidates.size() > 64) {
                incomplete = true;
                return;
            }
            const auto name = path.filename().string();
            self(self, path, relative.empty() ? name : relative + "/" + name, depth + 1);
        }
    };
    scan(scan, title, "", 0);
    if (incomplete || candidates.empty() || candidates.size() > 64) return {};
    std::sort(candidates.begin(), candidates.end());
    std::vector<std::string> named_base;
    for (const auto& candidate : candidates) {
        std::string stem = fs::path(candidate).stem().string();
        std::transform(stem.begin(), stem.end(), stem.begin(),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (stem == "base" || stem == "game") named_base.push_back(candidate);
    }
    if (named_base.size() == 1) return named_base.front();
    if (named_base.size() > 1) return {};
    if (candidates.size() == 1) return candidates.front();
    // A unique game-card image is a safer base candidate than an NSP when
    // a mixed folder also contains packaged updates and DLC. Never guess
    // between two NSPs or two card images without content metadata.
    std::string unique_card;
    for (const auto& candidate : candidates) {
        if (!IsCardImageFile(candidate)) continue;
        if (!unique_card.empty()) return {};
        unique_card = candidate;
    }
    return unique_card;
}

inline std::string FindGameFolderInput(const std::filesystem::path& title) {
    if (const auto extracted = FindDeconstructedGameMain(title); !extracted.empty())
        return extracted;
    return FindNestedGamePackage(title);
}

inline bool IsSafeNestedGameFilePath(const std::filesystem::path& roms_root,
                                    std::string_view selection) {
    namespace fs = std::filesystem;
    if (!IsNestedGameFileSelection(selection) || !IsSafeExtractedDirectory(roms_root))
        return false;
    fs::path path = roms_root;
    const fs::path relative{std::string(selection)};
    for (const auto& part : relative.parent_path()) {
        path /= part;
        if (!IsSafeExtractedDirectory(path)) return false;
    }
    std::error_code error;
    const auto status = fs::symlink_status(path / relative.filename(), error);
    return !error && fs::is_regular_file(status) && !fs::is_symlink(status);
}

// Discover add-on content roots without treating each update/DLC as a game.
// These roots may contain arbitrary deeper subdirectories: the existing
// ExternalContentProvider classifies packages by Nintendo title metadata.
// Keep traversal bounded and do not inspect extracted ExeFS/RomFS payloads.
inline std::vector<std::filesystem::path> FindAddOnContentDirectories(
    const std::filesystem::path& title_root) {
    namespace fs = std::filesystem;
    std::vector<fs::path> found;
    if (!IsSafeExtractedDirectory(title_root)) return found;
    // The base may be extracted or packaged in an arbitrary wrapper. Its
    // package must never be counted as an additional content package.
    const auto base_relative = FindGameFolderInput(title_root);
    const fs::path base_package = base_relative.empty() ? fs::path{} :
                                  title_root / fs::path(base_relative);
    // A partial directory walk must not publish only whichever DLC happened
    // to be enumerated first. Preserve a bounded scan but invalidate the
    // entire discovery result if a directory exceeds that bound.
    constexpr std::size_t MaxVisited = 256;
    constexpr std::size_t MaxEntriesPerDirectory = 512;
    constexpr std::size_t MaxRoots = 128;
    std::size_t visited = 0;
    bool incomplete = false;
    const auto scan = [&](const auto& self, const fs::path& dir, unsigned depth) -> void {
        if (incomplete) return;
        // A depth cap must never silently publish only the add-ons encountered
        // in shallower siblings: discard the whole incomplete discovery.
        if (depth > 5) {
            incomplete = true;
            return;
        }
        if (++visited > MaxVisited || found.size() > MaxRoots) {
            incomplete = true;
            return;
        }
        std::error_code error;
        std::vector<fs::path> subdirs;
        bool loose_add_on = false;
        std::size_t examined = 0;
        for (fs::directory_iterator it{dir, fs::directory_options::none, error},
                                    end;
             !error && it != end; it.increment(error)) {
            if (++examined > MaxEntriesPerDirectory) {
                incomplete = true;
                return;
            }
            const auto path = it->path();
            const auto name = path.filename().string();
            if (name.empty() || name.front() == '.') continue;
            // Preserve symlink rejection without two filesystem probes
            // for each ordinary file in a wrapper or DLC directory.
            std::error_code entry_error;
            const auto status = fs::symlink_status(path, entry_error);
            if (entry_error) {
                if (entry_error != std::errc::no_such_file_or_directory &&
                    entry_error != std::errc::not_a_directory)
                    incomplete = true;
                if (incomplete) return;
                continue;
            }
            if (fs::is_symlink(status)) continue;
            if (fs::is_directory(status)) {
                // Do not descend into extracted payloads or into a detected
                // add-on container: the native package provider handles the
                // latter recursively using package CNMT/Title ID metadata.
                if (IsExtractedAssetFolderName(name)) continue;
                if (IsAddOnContainerName(name) ||
                    LooksLikeExtractedAocTitleId(name)) {
                    // A full AOC Title ID is enough to locate an extracted
                    // DLC candidate even in custom/wrapper/ directories.
                    found.push_back(path);
                } else {
                    subdirs.push_back(path);
                }
                continue;
            }
            // A package with any name in any wrapper can be an update/DLC.
            // Do not rely on a "dlc" filename prefix; the native provider
            // classifies its actual content records. Ignore symlinks.
            if (fs::is_regular_file(status) &&
                (IsPackageFile(name) || IsCardImageFile(name)) &&
                path != base_package)
                loose_add_on = true;
        }
        if (error || found.size() > MaxRoots) {
            incomplete = true;
            return;
        }
        if (loose_add_on) {
            // Provider takes directories, not individual packages. This root
            // includes all local packages and their nested add-on wrappers.
            // Avoid registering descendants twice or opening extracted RomFS.
            found.push_back(dir);
            return;
        }
        std::sort(subdirs.begin(), subdirs.end());
        for (const auto& child : subdirs) {
            if (incomplete) return;
            self(self, child, depth + 1);
        }
    };
    scan(scan, title_root, 0);
    if (incomplete || found.size() > MaxRoots) return {};
    std::sort(found.begin(), found.end());
    found.erase(std::unique(found.begin(), found.end()), found.end());
    // Keep only minimal roots; a provider scans their descendants. Build a
    // separate result to avoid mutating the same vector under std::remove_if.
    std::vector<fs::path> minimal;
    for (const auto& child : found) {
        bool covered = false;
        for (const auto& parent : found) {
            if (child == parent) continue;
            const auto relative = child.lexically_relative(parent);
            if (!relative.empty() && *relative.begin() != ".." &&
                *relative.begin() != ".") {
                covered = true;
                break;
            }
        }
        if (!covered) minimal.push_back(child);
    }
    return minimal;
}
} // namespace Eden
