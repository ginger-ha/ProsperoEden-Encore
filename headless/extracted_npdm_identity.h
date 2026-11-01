// SPDX-License-Identifier: GPL-3.0-or-later
// Read-only, bounded NPDM identity fallback for extracted NS1/NS2 programs.
// This does NOT validate permissions or make a program bootable.
#pragma once
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>

namespace Eden::ExtractedNpdm {
inline std::uint32_t Read32(const unsigned char* p) noexcept {
    return std::uint32_t(p[0]) | (std::uint32_t(p[1]) << 8) |
           (std::uint32_t(p[2]) << 16) | (std::uint32_t(p[3]) << 24);
}
inline std::uint64_t Read64(const unsigned char* p) noexcept {
    return std::uint64_t(Read32(p)) | (std::uint64_t(Read32(p + 4)) << 32);
}
inline std::uint64_t TitleId(const std::filesystem::path& npdm) {
    std::error_code error;
    const auto status = std::filesystem::symlink_status(npdm, error);
    if (error || !std::filesystem::is_regular_file(status) ||
        std::filesystem::is_symlink(status)) return 0;
    const auto size = std::filesystem::file_size(npdm, error);
    if (error || size < 0x98 || size > (1u << 20)) return 0;
    std::ifstream input(npdm, std::ios::binary);
    std::array<unsigned char, 0x80> header{};
    if (!input.read(reinterpret_cast<char*>(header.data()), header.size()) ||
        std::string(reinterpret_cast<const char*>(header.data()), 4) != "META") return 0;
    const auto offset = Read32(header.data() + 0x70);
    const auto length = Read32(header.data() + 0x74);
    if (offset < 0x80 || length < 0x18 || offset > size || length > size - offset)
        return 0;
    std::array<unsigned char, 0x18> aci{};
    input.seekg(offset, std::ios::beg);
    if (!input.read(reinterpret_cast<char*>(aci.data()), aci.size()) ||
        std::string(reinterpret_cast<const char*>(aci.data()), 4) != "ACI0") return 0;
    return Read64(aci.data() + 0x10);
}
} // namespace Eden::ExtractedNpdm
