// SPDX-License-Identifier: GPL-3.0-or-later
#include "nup_v1_native_content.h"

#include <utility>

#include "core/file_sys/romfs.h"
#include "core/file_sys/vfs/vfs.h"

namespace Eden::NupV1::Native {

ContentSet::ContentSet(std::shared_ptr<Mount> mount) : mount_(std::move(mount)) {
    if (!mount_) return;
    const auto& packages = mount_->Packages();
    for (std::size_t i = 0; i < packages.size(); ++i) {
        if (packages[i].kind != 2) continue;
        const auto directory = mount_->PackageView(i, ContentView::RomFS);
        if (!directory) continue;
        addons_.push_back(AddOnDirectory{
            i, packages[i].title_id, packages[i].version, std::move(directory)});
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
