// SPDX-License-Identifier: GPL-3.0-or-later
// Host-only mutable NUP read amplification and tamper tests. No PS5 build.
#include "nup_v1_vfs.h"

#include <algorithm>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <span>
#include <string>
#include <vector>

class MutableSource final : public Eden::NupV1::Source {
public:
    explicit MutableSource(std::vector<std::uint8_t> bytes) : bytes_(std::move(bytes)) {}
    std::uint64_t Size() const override { return bytes_.size(); }
    bool AllowsVerifiedMemberCache() const override { return false; }
    bool ReadAt(std::uint64_t offset, std::span<std::uint8_t> dst) const override {
        if (offset > bytes_.size() || dst.size() > bytes_.size() - offset) return false;
        std::copy_n(bytes_.data() + static_cast<std::size_t>(offset),
                    dst.size(), dst.data());
        bytes_read_ += dst.size();
        return true;
    }
    void Flip(std::size_t offset) { assert(offset < bytes_.size()); bytes_[offset] ^= 0x5a; }
    void ResetReadBytes() const { bytes_read_ = 0; }
    std::size_t ReadBytes() const { return bytes_read_; }
    std::uint64_t Le64(std::size_t offset) const {
        assert(offset + 8 <= bytes_.size());
        std::uint64_t value{};
        for (std::size_t i = 0; i < 8; ++i)
            value |= std::uint64_t(bytes_[offset + i]) << (8 * i);
        return value;
    }
private:
    std::vector<std::uint8_t> bytes_;
    mutable std::size_t bytes_read_{};
};

int main(int argc, char** argv) {
    assert(argc == 2);
    std::ifstream file(argv[1], std::ios::binary);
    assert(file);
    std::vector<std::uint8_t> bytes(std::istreambuf_iterator<char>{file}, {});
    MutableSource source(std::move(bytes));
    std::string error;
    auto archive = Eden::NupV1::Archive::Mount(source, &error);
    assert(archive && error.empty());
    const auto member = archive->FindFile(0, "proof.bin");
    assert(member && archive->MemberSize(*member) > (1U << 20));
    constexpr std::size_t Block = 1U << 18;
    std::uint8_t output = 0xa5;
    // First access validates the entire member and builds immutable block digests.
    assert(archive->ReadMember(*member, 0, std::span(&output, 1), &error));
    source.ResetReadBytes();
    assert(archive->ReadMember(*member, 1, std::span(&output, 1), &error));
    assert(source.ReadBytes() == Block);
    source.ResetReadBytes();
    const std::size_t target = Block + 17;
    assert(archive->ReadMember(*member, target, std::span(&output, 1), &error));
    assert(source.ReadBytes() == Block);
    // In-place mutation in the touched block is rejected BEFORE copying to VFS output.
    const auto blob_start = static_cast<std::size_t>(source.Le64(0x38));
    source.Flip(blob_start + target);
    output = 0xa5;
    error.clear();
    assert(!archive->ReadMember(*member, target, std::span(&output, 1), &error));
    assert(!error.empty() && output == 0xa5);
    // Other verified blocks remain usable; no stale data from corrupted block.
    error.clear();
    assert(archive->ReadMember(*member, 0, std::span(&output, 1), &error));
    assert(error.empty());
}
