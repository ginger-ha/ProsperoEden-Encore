// SPDX-License-Identifier: GPL-3.0-or-later
// Binary RomFS test using the *actual pinned vendor* RomFSBuildContext.
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <limits>
#include <map>
#include <memory>
#include <span>
#include <string>
#include <string_view>
#include <utility>
#include <vector>
#include "nup_v1_native_content.h"
#include "nup_v1_native_vfs.h"
#include "core/file_sys/fsmitm_romfsbuild.h"
#include "core/file_sys/romfs.h"
#include "core/file_sys/vfs/vfs.h"
#include "core/file_sys/vfs/vfs_concat.h"

namespace {
class MemoryFile final : public FileSys::VfsFile {
public:
    explicit MemoryFile(std::vector<u8> bytes) : bytes_(std::move(bytes)) {}
    std::string GetName() const override { return "fixture.nup"; }
    std::size_t GetSize() const override { return bytes_.size(); }
    bool Resize(std::size_t) override { return false; }
    FileSys::VirtualDir GetContainingDirectory() const override { return {}; }
    bool IsWritable() const override { return false; }
    bool IsReadable() const override { return true; }
    std::size_t Read(u8* out, std::size_t count, std::size_t offset) const override {
        if (offset > bytes_.size()) return 0;
        const auto n = std::min(count, bytes_.size() - offset);
        if (n) std::copy_n(bytes_.data() + offset, n, out);
        return n;
    }
    std::size_t Write(const u8*, std::size_t, std::size_t) override { return 0; }
    bool Rename(std::string_view) override { return false; }
    void Corrupt(std::string_view value) {
        auto it = std::search(bytes_.begin(), bytes_.end(), value.begin(), value.end());
        assert(it != bytes_.end());
        *it ^= 1;
    }
private:
    std::vector<u8> bytes_;
};

// RomFSBuildContext and ConcatenatedVfsFile are both compiled from the
// actual vendor. Their input NUP VirtualFiles use only the host VFS ABI.
std::vector<u8> ReadAt(const FileSys::VirtualFile& file, std::size_t pos,
                       std::size_t count) {
    assert(file && count <= file->GetSize() && pos <= file->GetSize() - count);
    std::vector<u8> result(count);
    if (count) assert(file->Read(result.data(), count, pos) == count);
    return result;
}

u32 Read32(std::span<const u8> bytes, std::size_t pos) {
    assert(pos <= bytes.size() && bytes.size() - pos >= 4);
    u32 result{};
    for (int i = 0; i < 4; ++i) result |= u32(bytes[pos + i]) << (i * 8);
    return result;
}

u64 Read64(std::span<const u8> bytes, std::size_t pos) {
    assert(pos <= bytes.size() && bytes.size() - pos >= 8);
    u64 result{};
    for (int i = 0; i < 8; ++i) result |= u64(bytes[pos + i]) << (i * 8);
    return result;
}

std::map<std::string, std::string> DecodeRomFS(const FileSys::VirtualFile& image) {
    constexpr u32 Empty = 0xffffffffU;
    const auto header = ReadAt(image, 0, 0x50);
    assert(Read64(header, 0) == 0x50);
    // RomFSHeader: 5 pairs of u64, with data offset as last u64.
    const auto dir_table_at = Read64(header, 0x18);
    const auto dir_table_size = Read64(header, 0x20);
    const auto file_table_at = Read64(header, 0x38);
    const auto file_table_size = Read64(header, 0x40);
    const auto data_at = Read64(header, 0x48);
    assert(dir_table_size && file_table_size);
    assert(dir_table_size < (1 << 20) && file_table_size < (1 << 20));
    const auto dirs = ReadAt(image, dir_table_at, dir_table_size);
    const auto files = ReadAt(image, file_table_at, file_table_size);

    std::map<std::string, std::string> collected;
    auto visit = [&](auto&& self, u32 entry, std::string prefix, int depth) -> void {
        assert(depth < 20);
        while (entry != Empty) {
            assert(entry <= dirs.size() && dirs.size() - entry >= 0x18);
            const u32 sibling = Read32(dirs, entry + 4);
            const u32 child_dir = Read32(dirs, entry + 8);
            const u32 first_file = Read32(dirs, entry + 0xc);
            const u32 name_size = Read32(dirs, entry + 0x14);
            assert(name_size <= dirs.size() - entry - 0x18);
            const auto name = std::string(
                reinterpret_cast<const char*>(dirs.data() + entry + 0x18), name_size);
            const auto current = prefix.empty() ? name :
                                 name.empty() ? prefix : prefix + "/" + name;
            u32 file_id = first_file;
            for (int n = 0; file_id != Empty; ++n) {
                assert(n < 1000);
                assert(file_id <= files.size() && files.size() - file_id >= 0x20);
                const u32 file_sibling = Read32(files, file_id + 4);
                const u64 file_offset = Read64(files, file_id + 8);
                const u64 file_size = Read64(files, file_id + 16);
                const u32 file_name_size = Read32(files, file_id + 0x1c);
                assert(file_name_size <= files.size() - file_id - 0x20);
                const auto file_name = std::string(
                    reinterpret_cast<const char*>(files.data() + file_id + 0x20),
                    file_name_size);
                assert(file_size < (1 << 20));
                const auto value = ReadAt(image, data_at + file_offset, file_size);
                const auto path = current.empty() ? file_name : current + "/" + file_name;
                assert(!collected.contains(path));
                collected.emplace(path, std::string(value.begin(), value.end()));
                file_id = file_sibling;
            }
            if (child_dir != Empty) self(self, child_dir, current, depth + 1);
            entry = sibling;
        }
    };
    visit(visit, 0, "", 0);
    return collected;
}

std::vector<u8> ReadFile(const char* path) {
    std::ifstream stream(path, std::ios::binary);
    assert(stream);
    return {std::istreambuf_iterator<char>(stream), std::istreambuf_iterator<char>()};
}
} // namespace

namespace FileSys {
VirtualFile PatchIPS(const VirtualFile&, const VirtualFile&); // host stub is inline
VirtualFile CreateRomFS(VirtualDir dir, VirtualDir ext) {
    if (!dir || ext) return {};
    // Keep the directory name before transferring ownership to the
    // builder; dereferencing dir after std::move is a host-test bug.
    auto name = dir->GetName();
    RomFSBuildContext builder(std::move(dir), nullptr);
    return ConcatenatedVfsFile::MakeConcatenatedFile(
        0, std::move(name), builder.Build());
}
} // namespace FileSys

int main(int argc, char** argv) {
    assert(argc == 2);
    std::string error;
    auto input = std::make_shared<MemoryFile>(ReadFile(argv[1]));
    const auto mount = Eden::NupV1::Native::Mount::Open(input, &error);
    assert(mount && error.empty());
    Eden::NupV1::Native::ContentSet content(mount);
    assert(content.HasExecutableMain());
    const auto base = content.CreateRomFS();
    const auto base_files = DecodeRomFS(base);
    assert(base_files.size() == 3);
    assert(base_files.at("state.bin") == "latest-v3");
    assert(base_files.at("sub/base.dat") == "base-only");
    assert(base_files.at("sub/update.dat") == "update-only");
    assert(!base_files.contains("addon.dat"));

    auto addon_one = content.CreateAddOnRomFS(5);
    auto addon_two = content.CreateAddOnRomFS(4);
    assert(addon_one && addon_two);
    const auto first_files = DecodeRomFS(addon_one);
    const auto second_files = DecodeRomFS(addon_two);
    assert(first_files.size() == 1 && first_files.at("addon.dat") == "addon-one-v2");
    assert(second_files.size() == 1 && second_files.at("addon.dat") == "addon-two");
    assert(!content.CreateAddOnRomFS(3)); // older DLC revision
    assert(!content.CreateAddOnRomFS(6)); // unrelated title

    // The authentic vendor builder produces a lazy table-to-file mapping.
    // Even after a successful read, the native NUP source must NOT cache
    // an integrity verdict for mutable underlying bytes.
    const auto header = ReadAt(base, 0, 0x50);
    const auto data_offset = Read64(header, 0x48);
    assert(data_offset == 0x200);
    input->Corrupt("latest-v3");
    std::array<u8, 8> rejected{};
    rejected.fill(0xa5);
    assert(base->Read(rejected.data(), rejected.size(), data_offset) == 0);
    assert(std::all_of(rejected.begin(), rejected.end(),
                       [](u8 byte) { return byte == 0; }));
    // The directory tables remain readable, while the corrupted payload is
    // never returned through the actual vendor-generated RomFS offsets.
    assert(Read64(ReadAt(base, 0, 0x50), 0) == 0x50);

    std::cout << "Real vendor RomFSBuildContext+ConcatenatedVfsFile: binary overlay and mutable SHA rejection OK\n";
}
