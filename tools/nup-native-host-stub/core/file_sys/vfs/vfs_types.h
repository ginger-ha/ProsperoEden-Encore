// SPDX-License-Identifier: GPL-3.0-or-later
// Test-only ABI subset of native VFS types; NOT shipped or installed.
#pragma once
#include <cstdint>
#include <memory>
using u8 = std::uint8_t;
using u64 = std::uint64_t;
namespace FileSys {
class VfsFile;
class VfsDirectory;
using VirtualFile = std::shared_ptr<VfsFile>;
using VirtualDir = std::shared_ptr<VfsDirectory>;
}
