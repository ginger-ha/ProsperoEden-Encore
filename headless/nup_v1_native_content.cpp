// SPDX-License-Identifier: GPL-3.0-or-later
#include "nup_v1_native_content.h"

#include <limits>
#include <map>
#include <optional>
#include <utility>

#include "core/file_sys/common_funcs.h"
#include "core/file_sys/romfs.h"
#include "core/file_sys/vfs/vfs.h"

namespace Eden::NupV1::Native {

ContentSet::ContentSet(std::shared_ptr<Mount> mount,
                       std::optional<std::uint64_t> caller_program_id,
                       std::optional<std::uint64_t> nacp_aoc_base_id)
    : mount_(std::move(mount)) {
    if (!mount_) return;
    const auto& packages = mount_->Packages();

    // Mirror the existing aoc:u service's GetBaseTitleID contract. This
    // prevents packages belonging to unrelated games from appearing as DLC.
    std::optional<std::uint64_t> active_base;
    for (const auto& package : packages) {
        if (package.kind == 0) {
            active_base = FileSys::GetBaseTitleID(package.title_id);
            break;
        }
    }
    if (!active_base) {
        const Package* newest = nullptr;
        for (const auto& package : packages) {
            if (package.kind == 1 && (!newest || package.version > newest->version))
                newest = &package;
        }
        if (newest) active_base = FileSys::GetBaseTitleID(newest->title_id);
    }

    if (caller_program_id) {
        const auto requested = FileSys::GetBaseTitleID(*caller_program_id);
        if (active_base && *active_base != requested) return;
        active_base = requested;
    }
    // Add-on-only archives carry no owning executable title: callers must
    // supply the program identity instead of seeing cross-title content.
    if (!active_base) return;
    // A non-default NACP-declared AoC family is only meaningful when bound to
    // a known caller. Do not grant blanket visibility from an unscoped mount.
    if (nacp_aoc_base_id && !caller_program_id) return;
    if (*active_base > std::numeric_limits<std::uint64_t>::max() - FileSys::AOC_TITLE_ID_OFFSET) return;
    const auto aoc_base = nacp_aoc_base_id.value_or(
        *active_base + FileSys::AOC_TITLE_ID_OFFSET);

    // Select DLC from the declared AoC base, never by blindly treating every
    // title with a similar high prefix as belonging to the application.
    // Custom bases are inputs from trusted NACP metadata, not per-game hacks.
    // Two revisions of one DLC use the highest NCM version.
    std::map<std::uint64_t, std::size_t> selected;
    for (std::size_t i = 0; i < packages.size(); ++i) {
        const auto& package = packages[i];
        if (package.kind != 2) continue;
        if (package.title_id < aoc_base ||
            package.title_id - aoc_base > FileSys::AOC_TITLE_ID_MASK)
            continue;
        const auto it = selected.find(package.title_id);
        if (it == selected.end() ||
            package.version > packages[it->second].version) {
            selected.insert_or_assign(package.title_id, i);
        }
    }

    for (const auto& [title_id, index] : selected) {
        const auto directory = mount_->PackageView(index, ContentView::RomFS);
        if (!directory) continue;
        addons_.push_back(AddOnDirectory{
            index, title_id, packages[index].version, directory});
    }
}

FileSys::VirtualDir ContentSet::ExeFS() const {
    return mount_ ? mount_->Effective(ContentView::ExeFS) : FileSys::VirtualDir{};
}

FileSys::VirtualFile ContentSet::CreateRomFS() const {
    if (!mount_) return {};
    auto directory = mount_->Effective(ContentView::RomFS);
    return directory ? FileSys::CreateRomFS(std::move(directory), nullptr)
                     : FileSys::VirtualFile{};
}

FileSys::VirtualFile ContentSet::CreateAddOnRomFS(std::size_t package_index) const {
    for (const auto& addon : addons_) {
        if (addon.package_index == package_index && addon.romfs) {
            return FileSys::CreateRomFS(addon.romfs, nullptr);
        }
    }
    return {};
}

bool ContentSet::HasExecutableMain() const {
    const auto exefs = ExeFS();
    return exefs && exefs->GetFile("main") && exefs->GetFile("main.npdm");
}

} // namespace Eden::NupV1::Native
