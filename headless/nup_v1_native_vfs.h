// SPDX-License-Identifier: GPL-3.0-or-later
// Native FileSys adapter for the verified NUP v1 core. Deliberately NOT registered
// as a loadable format or added to the PS5 source selectors.
#pragma once

#include <cstddef>
#include <memory>
#include <string>
#include <vector>

#include "nup_v1_vfs.h"
#include "core/file_sys/vfs/vfs_types.h"

namespace Eden::NupV1::Native {

// Cheap signature/length probe for the future loader factory. A positive
// result is NOT proof of integrity: Mount::Open still validates TOC/UUID.
bool HasNupV1Header(const FileSys::VirtualFile& source);

namespace Detail {
struct State;
}

class Mount final {
public:
    // Keeps the input VirtualFile alive for every exposed file/directory.
    // Content is reverified on every read: VfsFile does not promise immutability.
    static std::shared_ptr<Mount> Open(FileSys::VirtualFile file,
                                       std::string* error = nullptr);
    ~Mount();
    Mount(const Mount&) = delete;
    Mount& operator=(const Mount&) = delete;

    const std::vector<Eden::NupV1::Package>& Packages() const;
    const Eden::NupV1::PackageMetadata* ApplicationMetadata() const;
    // ExeFS/RomFS views. Addons are NEVER merged into Effective().
    FileSys::VirtualDir Effective(ContentView view) const;
    FileSys::VirtualDir PackageView(std::size_t package_index, ContentView view) const;

private:
    explicit Mount(std::shared_ptr<Detail::State> state);
    std::shared_ptr<Detail::State> state_;
};
} // namespace Eden::NupV1::Native
