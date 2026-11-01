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
// Read-only diagnostic of ACID/FS access-control layout, intended only for
// reporting failed loads. Never grants/relaxes filesystem permissions.
struct AccessProbe {
    bool header_ok = false;
    bool acid_found = false;
    bool extended = false;
    bool fac_valid = false;
    std::uint32_t acid_size = 0;
    std::uint32_t fac_offset = 0;
    std::uint32_t fac_size = 0;
};
inline AccessProbe ProbeAccess(const std::filesystem::path& npdm) {
    AccessProbe result{};
    std::error_code ec;
    const auto status = std::filesystem::symlink_status(npdm, ec);
    if (ec || !std::filesystem::is_regular_file(status) ||
        std::filesystem::is_symlink(status)) return result;
    const auto size = std::filesystem::file_size(npdm, ec);
    if (ec || size < 0x80 || size > (1u << 20)) return result;
    std::ifstream input(npdm, std::ios::binary);
    std::array<unsigned char, 0x80> header{};
    if (!input.read(reinterpret_cast<char*>(header.data()), header.size()) ||
        std::string(reinterpret_cast<const char*>(header.data()), 4) != "META")
        return result;
    result.header_ok = true;
    const auto offset = Read32(header.data() + 0x78);
    const auto length = Read32(header.data() + 0x7c);
    result.acid_size = length;
    if (offset < 0x80 || offset > size || length > size - offset) return result;
    // ACID signed-body headers start after the NS1 (0x200) or NS2
    // (0x300) signature/key prefix. Check both; do not infer from a title ID.
    for (const unsigned prefix : {0x200u, 0x300u}) {
        if (prefix > length || 0x40u > length - prefix) continue;
        std::array<unsigned char, 0x40> acid{};
        input.clear();
        input.seekg(static_cast<std::streamoff>(offset + prefix));
        if (!input.read(reinterpret_cast<char*>(acid.data()), acid.size()) ||
            std::string(reinterpret_cast<const char*>(acid.data()), 4) != "ACID")
            continue;
        result.acid_found = true;
        result.extended = (prefix == 0x300);
        result.fac_offset = Read32(acid.data() + 0x20);
        result.fac_size = Read32(acid.data() + 0x24);
        result.fac_valid = result.fac_size >= 0x2c &&
                           result.fac_offset <= length &&
                           result.fac_size <= length - result.fac_offset;
        return result;
    }
    return result;
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
