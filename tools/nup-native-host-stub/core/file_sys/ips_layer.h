// SPDX-License-Identifier: GPL-3.0-or-later
// The isolated RomFS test never supplies an extension IPS tree.
#pragma once
#include "core/file_sys/vfs/vfs.h"
namespace FileSys {
inline VirtualFile PatchIPS(const VirtualFile&, const VirtualFile&) {
    return nullptr;
}
} // namespace FileSys
