// SPDX-License-Identifier: GPL-3.0-or-later
// Host-only stand-in: the vendor VectorVfsFile owns bytes in memory.
#pragma once
#include <algorithm>
#include <string>
#include <string_view>
#include <utility>
#include <vector>
#include "core/file_sys/vfs/vfs.h"
namespace FileSys {
class VectorVfsFile final : public VfsFile {
public:
    explicit VectorVfsFile(std::vector<u8> data = {},
                           std::string name = "",
                           VirtualDir parent = nullptr)
        : bytes_(std::move(data)), name_(std::move(name)), parent_(std::move(parent)) {}
    std::string GetName() const override { return name_; }
    std::size_t GetSize() const override { return bytes_.size(); }
    bool Resize(std::size_t) override { return false; }
    VirtualDir GetContainingDirectory() const override { return parent_; }
    bool IsWritable() const override { return false; }
    bool IsReadable() const override { return true; }
    std::size_t Read(u8* target, std::size_t count, std::size_t offset) const override {
        if (offset > bytes_.size() || (!target && count)) return 0;
        const auto length = std::min(count, bytes_.size() - offset);
        if (length) std::copy_n(bytes_.begin() + offset, length, target);
        return length;
    }
    std::size_t Write(const u8*, std::size_t, std::size_t) override { return 0; }
    bool Rename(std::string_view) override { return false; }
private:
    std::vector<u8> bytes_;
    std::string name_;
    VirtualDir parent_;
};
} // namespace FileSys
