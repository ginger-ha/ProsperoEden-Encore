// SPDX-License-Identifier: GPL-3.0-or-later
// Test-only signature mirror, NOT a RomFS serializer implementation.
#pragma once
#include "core/file_sys/vfs/vfs.h"
namespace FileSys {
VirtualDir ExtractRomFS(VirtualFile file);
VirtualFile CreateRomFS(VirtualDir dir, VirtualDir ext = nullptr);
}
