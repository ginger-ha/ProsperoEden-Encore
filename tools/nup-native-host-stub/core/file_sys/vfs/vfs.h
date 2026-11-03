// SPDX-License-Identifier: GPL-3.0-or-later
// Host test substitute, kept separate from the real vendor implementation.
#pragma once
#include "core/file_sys/vfs/vfs_types.h"
#include <algorithm>
#include <cstddef>
#include <optional>
#include <string>
#include <string_view>
#include <vector>
namespace FileSys {
class VfsFile {
public:
    virtual ~VfsFile() = default;
    virtual std::string GetName() const = 0;
    virtual std::size_t GetSize() const = 0;
    virtual bool Resize(std::size_t) = 0;
    virtual VirtualDir GetContainingDirectory() const = 0;
    virtual bool IsWritable() const = 0;
    virtual bool IsReadable() const = 0;
    virtual std::size_t Read(u8*, std::size_t, std::size_t) const = 0;
    virtual std::optional<u8> ReadByte(std::size_t offset) const {
        u8 value{};
        return Read(&value, 1, offset) == 1 ?
               std::optional<u8>(value) : std::nullopt;
    }
    virtual std::vector<u8> ReadBytes(std::size_t length, std::size_t offset) const {
        std::vector<u8> result(length);
        const auto count = length ? Read(result.data(), length, offset) : 0;
        result.resize(count);
        return result;
    }
    virtual std::size_t Write(const u8*, std::size_t, std::size_t) = 0;
    virtual bool Rename(std::string_view) = 0;
};
class VfsDirectory {
public:
    virtual ~VfsDirectory() = default;
    virtual std::vector<VirtualFile> GetFiles() const = 0;
    virtual std::vector<VirtualDir> GetSubdirectories() const = 0;
    virtual bool IsWritable() const = 0;
    virtual bool IsReadable() const = 0;
    virtual std::string GetName() const = 0;
    virtual VirtualDir GetParentDirectory() const = 0;
    virtual VirtualDir CreateSubdirectory(std::string_view) = 0;
    virtual VirtualFile CreateFile(std::string_view) = 0;
    virtual bool DeleteSubdirectory(std::string_view) = 0;
    virtual bool DeleteFile(std::string_view) = 0;
    virtual bool Rename(std::string_view) = 0;
    virtual VirtualFile GetFile(std::string_view name) const {
        for (auto& f : GetFiles()) if (f->GetName() == name) return f;
        return {};
    }
    virtual VirtualDir GetSubdirectory(std::string_view name) const {
        for (auto& d : GetSubdirectories()) if (d->GetName() == name) return d;
        return {};
    }
};
class ReadOnlyVfsDirectory : public VfsDirectory {
public:
    bool IsWritable() const override { return false; }
    bool IsReadable() const override { return true; }
    VirtualDir CreateSubdirectory(std::string_view) override { return {}; }
    VirtualFile CreateFile(std::string_view) override { return {}; }
    bool DeleteSubdirectory(std::string_view) override { return false; }
    bool DeleteFile(std::string_view) override { return false; }
    bool Rename(std::string_view) override { return false; }
};
} // namespace FileSys
