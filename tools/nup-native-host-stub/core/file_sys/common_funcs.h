// SPDX-License-Identifier: GPL-3.0-or-later
// Test ABI mirror of vendor/sources/eden/.../file_sys/common_funcs.h.
// The CI separately syntax-checks the actual pinned vendor header.
#pragma once
#include "core/file_sys/vfs/vfs_types.h"
namespace FileSys {
constexpr u64 AOC_TITLE_ID_MASK = 0x7FF;
constexpr u64 AOC_TITLE_ID_OFFSET = 0x1000;
constexpr u64 BASE_TITLE_ID_MASK = 0xFFFFFFFFFFFFE000;
constexpr u64 GetBaseTitleID(u64 title_id) {
    return title_id & BASE_TITLE_ID_MASK;
}
} // namespace FileSys
