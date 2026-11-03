// SPDX-License-Identifier: GPL-3.0-or-later
// Minimal host adapter; no PS5 loader registration or ROM discovery.
#include "nup_v1_vfs.h"

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <span>
#include <string_view>
#include <string>
#include <vector>

class HostSource final : public Eden::NupV1::Source {
public:
    explicit HostSource(const std::filesystem::path& path)
        : input_(path, std::ios::binary), size_(std::filesystem::file_size(path)) {}
    std::uint64_t Size() const override { return size_; }
    bool ReadAt(std::uint64_t offset, std::span<std::uint8_t> dst) const override {
        if (offset > size_ || dst.size() > size_ - offset) return false;
        if (dst.empty()) return true;
        input_.clear();
        input_.seekg(static_cast<std::streamoff>(offset));
        if (!input_) return false;
        input_.read(reinterpret_cast<char*>(dst.data()),
                    static_cast<std::streamsize>(dst.size()));
        return input_.gcount() == static_cast<std::streamsize>(dst.size());
    }
private:
    mutable std::ifstream input_;
    std::uint64_t size_{};
};

void PrintHex(std::span<const std::uint8_t> bytes) {
    for (const auto c : bytes)
        std::cout << std::hex << std::setfill('0') << std::setw(2)
                  << static_cast<unsigned>(c);
    std::cout << std::dec;
}

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "Usage: nup-v1-vfs-host archive.nup package-relative/path\n";
        return 2;
    }
    try {
        HostSource source(argv[1]);
        std::string error;
        auto archive = Eden::NupV1::Archive::Mount(source, &error);
        if (!archive) {
            std::cerr << "NUP mount rejected: " << error << '\n';
            return 1;
        }
        const std::string_view name(argv[2]);
        std::optional<std::size_t> file;
        constexpr std::string_view effective = "@effective/romfs/";
        constexpr std::string_view base = "@base/romfs/";
        constexpr std::string_view first_update = "@update1/romfs/";
        constexpr std::string_view second_update = "@update2/romfs/";
        if (name.starts_with(effective))
            file = archive->FindEffectiveMember(Eden::NupV1::ContentView::RomFS,
                                                name.substr(effective.size()));
        else if (name.starts_with(base))
            file = archive->FindPackageMember(0, Eden::NupV1::ContentView::RomFS,
                                              name.substr(base.size()));
        else if (name.starts_with(first_update))
            file = archive->FindPackageMember(1, Eden::NupV1::ContentView::RomFS,
                                              name.substr(first_update.size()));
        else if (name.starts_with(second_update))
            file = archive->FindPackageMember(2, Eden::NupV1::ContentView::RomFS,
                                              name.substr(second_update.size()));
        else
            file = archive->FindFile(0, name);
        if (!file) {
            std::cerr << "Member not found in package 0\n";
            return 1;
        }
        const auto member_size = archive->MemberSize(*file);
        const auto chunk_size = static_cast<std::size_t>(
            std::min<std::uint64_t>(member_size, 64));
        std::vector<std::uint8_t> first(chunk_size), last(chunk_size);
        if (!archive->ReadMember(*file, 0, first, &error) ||
            !archive->ReadMember(*file, member_size - chunk_size, last, &error)) {
            std::cerr << "NUP member rejected: " << error << '\n';
            return 1;
        }
        std::cout << "size=" << member_size << " first=";
        PrintHex(first);
        std::cout << " last=";
        PrintHex(last);
        std::cout << "\n";
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "Host error: " << ex.what() << '\n';
        return 1;
    }
}
