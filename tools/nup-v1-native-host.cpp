// SPDX-License-Identifier: GPL-3.0-or-later
// Exercise native adapter WITHOUT linking a PS5 renderer/loader.
#include "nup_v1_native_vfs.h"
#include "nup_v1_native_content.h"
#include "core/file_sys/romfs.h"
#include "core/file_sys/vfs/vfs.h"

#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <span>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

class MemoryFile final : public FileSys::VfsFile {
public:
    explicit MemoryFile(std::vector<u8> bytes) : bytes_(std::move(bytes)) {}
    std::string GetName() const override { return "fixture.nup"; }
    std::size_t GetSize() const override { return bytes_.size(); }
    bool Resize(std::size_t) override { return false; }
    FileSys::VirtualDir GetContainingDirectory() const override { return {}; }
    bool IsWritable() const override { return false; }
    bool IsReadable() const override { return true; }
    std::size_t Read(u8* dst, std::size_t count, std::size_t pos) const override {
        if (pos > bytes_.size()) return 0;
        const auto n = (std::min)(count, bytes_.size() - pos);
        if (n) std::copy_n(bytes_.data() + pos, n, dst);
        return n;
    }
    std::size_t Write(const u8*, std::size_t, std::size_t) override { return 0; }
    bool Rename(std::string_view) override { return false; }
    // Read-only API does not imply externally immutable backing bytes.
    void Corrupt(std::string_view old) {
        auto it = std::search(bytes_.begin(), bytes_.end(), old.begin(), old.end());
        assert(it != bytes_.end());
        *it ^= 1;
    }
private:
    std::vector<u8> bytes_;
};

// Host-only stub: checks that the bridge forwards the correct VFS tree.
// This is intentionally NOT the real RomFS serializer. Native-header syntax
// compilation checks the actual CreateRomFS API separately.
namespace FileSys {
VirtualFile CreateRomFS(VirtualDir directory, VirtualDir extension) {
    if (!directory || extension) return {};
    std::string serialized;
    for (const auto& f : directory->GetFiles()) {
        std::string data(f->GetSize(), '\0');
        if (!data.empty() &&
            f->Read(reinterpret_cast<u8*>(data.data()), data.size(), 0) != data.size())
            return {};
        serialized += f->GetName() + "=" + data + "\n";
    }
    return std::make_shared<MemoryFile>(
        std::vector<u8>(serialized.begin(), serialized.end()));
}
} // namespace FileSys

std::vector<u8> Load(const char* path) {
    std::ifstream input(path, std::ios::binary);
    assert(input);
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

std::string Read(const FileSys::VirtualFile& file) {
    assert(file && file->IsReadable() && !file->IsWritable());
    std::string bytes(file->GetSize(), '\0');
    if (!bytes.empty())
        assert(file->Read(reinterpret_cast<u8*>(bytes.data()), bytes.size(), 0) == bytes.size());
    return bytes;
}

int main(int argc, char** argv) {
    assert(argc == 4);
    auto input = std::make_shared<MemoryFile>(Load(argv[1]));
    std::string error;
    auto mount = Eden::NupV1::Native::Mount::Open(input, &error);
    assert(mount && error.empty());
    assert(mount->Packages().size() == 3);
    // ContentSet is a common NS1/NS2 handoff, not an installed loader.
    Eden::NupV1::Native::ContentSet content{mount};
    assert(!content.HasExecutableMain()); // synthetic fixture lacks ExeFS
    assert(!content.ExeFS());
    assert(content.AddOns().size() == 1);
    assert(content.AddOns().front().package_index == 2);
    assert(content.AddOns().front().romfs);
    assert(content.AddOns().front().romfs->GetFile("state.bin"));
    // Test serializer is a sentinel: verifies selected VFS contents only.
    assert(Read(content.CreateRomFS()) == "state.bin=latest-v3\n");
    using Eden::NupV1::ContentView;
    assert(!mount->Effective(ContentView::ExeFS));
    assert(!mount->PackageView(100, ContentView::RomFS));

    auto effective = mount->Effective(ContentView::RomFS);
    assert(effective && effective->IsReadable() && !effective->IsWritable());
    assert(effective->GetName() == "romfs");
    assert(effective->GetFiles().size() == 1);
    assert(effective->GetSubdirectories().empty());
    auto newest = effective->GetFile("state.bin");
    assert(newest && newest->GetContainingDirectory() == effective);
    assert(Read(newest) == "latest-v3");
    // The native FileSys API can issue concurrent reads on the same member.
    // The source adapter must serialize raw file access and preserve checksums.
    std::atomic<bool> concurrent_ok{true};
    std::vector<std::thread> workers;
    for (int worker = 0; worker < 8; ++worker) {
        workers.emplace_back([&] {
            for (int iteration = 0; iteration < 100; ++iteration) {
                u8 buffer[9]{};
                if (newest->Read(buffer, sizeof(buffer), 0) != sizeof(buffer) ||
                    std::string_view(reinterpret_cast<const char*>(buffer), sizeof(buffer))
                        != "latest-v3") {
                    concurrent_ok.store(false, std::memory_order_relaxed);
                }
            }
        });
    }
    for (auto& worker : workers) worker.join();
    assert(concurrent_ok.load());
    assert(!newest->Resize(1) && !newest->Rename("changed"));
    assert(newest->Write(reinterpret_cast<const u8*>("bad"), 3, 0) == 0);
    u8 out{};
    assert(newest->Read(&out, 1, newest->GetSize()) == 0);

    auto base = mount->PackageView(0, ContentView::RomFS);
    assert(base && Read(base->GetFile("state.bin")) == "base-v1");
    auto addon = mount->PackageView(2, ContentView::RomFS);
    assert(addon && Read(addon->GetFile("state.bin")) == "addon-aoc");
    // NativeFile pins State even if both Mount and directory handles disappear.
    mount.reset();
    effective.reset();
    base.reset();
    addon.reset();
    // AppLoader_DeconstructedRomDirectory(main) dereferences this directory.
    // The file must pin its containing directory even after Mount is gone.
    const auto held_parent = newest->GetContainingDirectory();
    assert(held_parent && held_parent->GetFile("state.bin"));
    assert(Read(newest) == "latest-v3");
    // First successful read MUST NOT memoize integrity on mutable VfsFile.
    input->Corrupt("latest-v3");
    u8 scratch[16]{};
    assert(newest->Read(scratch, 9, 0) == 0);

    auto standalone_input = std::make_shared<MemoryFile>(Load(argv[2]));
    auto standalone = Eden::NupV1::Native::Mount::Open(standalone_input, &error);
    assert(standalone);
    assert(Read(standalone->Effective(ContentView::RomFS)->GetFile("state.bin")) == "latest-v3");

    auto invalid = Load(argv[2]);
    invalid[0] ^= 1;
    auto rejected = Eden::NupV1::Native::Mount::Open(
        std::make_shared<MemoryFile>(std::move(invalid)), &error);
    assert(!rejected && !error.empty());
    // Full synthetic content: effective ExeFS, nested RomFS overlay and
    // multiple separately addressed addons (never registered in AoC).
    auto executable_input = std::make_shared<MemoryFile>(Load(argv[3]));
    auto playable_mount = Eden::NupV1::Native::Mount::Open(executable_input, &error);
    assert(playable_mount && playable_mount->Packages().size() == 5);
    Eden::NupV1::Native::ContentSet exec_content(playable_mount);
    assert(exec_content.HasExecutableMain());
    auto exefs = exec_content.ExeFS();
    assert(exefs && Read(exefs->GetFile("main")) == "latest-main");
    assert(Read(exefs->GetFile("main.npdm")) == "latest-npdm");
    assert(exefs->GetFile("main")->GetContainingDirectory() == exefs);
    assert(Read(exec_content.CreateRomFS()) == "state.bin=latest-v3\n");
    auto effective_tree = playable_mount->Effective(ContentView::RomFS);
    assert(effective_tree);
    auto sub = effective_tree->GetSubdirectory("sub");
    assert(sub);
    assert(Read(sub->GetFile("base.dat")) == "base-only");
    assert(Read(sub->GetFile("update.dat")) == "update-only");
    assert(exec_content.AddOns().size() == 2);
    assert(exec_content.AddOns()[0].package_index == 3);
    assert(exec_content.AddOns()[1].package_index == 4);
    assert(exec_content.AddOns()[0].title_id != exec_content.AddOns()[1].title_id);
    assert(Read(exec_content.AddOns()[0].romfs->GetFile("addon.dat")) == "addon-one");
    assert(Read(exec_content.AddOns()[1].romfs->GetFile("addon.dat")) == "addon-two");
    assert(!effective_tree->GetFile("addon.dat"));
    // ExeFS handles remain valid after dropping the owning ContentSet/Mount.
    auto still_readable = exefs->GetFile("main");
    exefs.reset();
    playable_mount.reset();
    assert(Read(still_readable) == "latest-main");
    std::cout << "NUP native VFS adapter: lifetime, overlay, AoC isolation, mutable hash checks OK\n";
}
