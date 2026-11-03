// SPDX-License-Identifier: GPL-3.0-or-later
// Host ONLY ABI stub: the real vendor RawNACP is 0x4000 bytes and its
// dlc_base_title_id field begins at 0x3070. Never installed in production.
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include "core/file_sys/vfs/vfs_types.h"
namespace FileSys {
struct RawNACP {
    std::array<u8, 0x3070> preceding{};
    std::uint64_t dlc_base_title_id{};
    std::array<u8, 0x4000 - 0x3070 - 8> following{};
};
static_assert(sizeof(RawNACP) == 0x4000);
static_assert(offsetof(RawNACP, dlc_base_title_id) == 0x3070);
} // namespace FileSys
