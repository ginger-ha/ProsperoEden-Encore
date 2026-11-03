// SPDX-License-Identifier: GPL-3.0-or-later
// Host ONLY ABI stub: the real vendor RawNACP is 0x4000 bytes and its
// dlc_base_title_id field begins at 0x3070. Never installed in production.
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include "core/file_sys/vfs/vfs_types.h"
namespace FileSys {
enum class TitleDataFormat : u8 { Uncompressed = 0, Compressed = 1 };
struct LanguageEntry { std::array<u8, 0x300> contents{}; };
struct LanguageEntryData { std::array<u8, 0x3000> contents{}; };
struct RawNACP {
    std::array<u8, 0x3070> preceding{};
    std::uint64_t dlc_base_title_id{};
    // Host mock field at 0x3200. The real ABI has its own offset, derived
    // with offsetof in the production validator, never this mock literal.
    std::array<u8, 0x3200 - 0x3070 - 8> between{};
    TitleDataFormat titles_data_format{TitleDataFormat::Uncompressed};
    std::array<u8, 0x4000 - 0x3201> following{};
};
static_assert(sizeof(RawNACP) == 0x4000);
static_assert(offsetof(RawNACP, dlc_base_title_id) == 0x3070);
class NACP {
public:
    NACP() = default;
    explicit NACP(VirtualFile file) {
        if (file && file->GetSize() == sizeof(raw) &&
            file->Read(reinterpret_cast<u8*>(&raw), sizeof(raw), 0) == sizeof(raw))
            valid_ = true;
    }
    std::uint64_t GetDLCBaseTitleId() const { return raw.dlc_base_title_id; }
    bool IsValidForHostTest() const { return valid_; }
    RawNACP raw{};
private:
    bool valid_{};
};
} // namespace FileSys
