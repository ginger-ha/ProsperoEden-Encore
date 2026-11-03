// SPDX-License-Identifier: GPL-3.0-or-later
// Exercise native adapter WITHOUT linking a PS5 renderer/loader.
#include "nup_v1_native_vfs.h"
#include "nup_v1_native_content.h"
#include "nup_v1_native_aoc.h"
#include "nup_v1_native_loader.h"
#include "core/file_sys/romfs.h"
#include "core/file_sys/control_metadata.h"
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
    assert(argc == 19);
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
    assert(Read(content.CreateAddOnRomFS(2)) == "state.bin=addon-aoc\n");
    assert(!content.CreateAddOnRomFS(0));
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
    std::fill(std::begin(scratch), std::end(scratch), u8{0xA5});
    assert(newest->Read(scratch, 9, 0) == 0);
    assert(std::all_of(std::begin(scratch), std::begin(scratch) + 9,
                       [](u8 byte) { return byte == 0; }));
    assert(std::all_of(std::begin(scratch) + 9, std::end(scratch),
                       [](u8 byte) { return byte == 0xA5; }));

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
    assert(playable_mount && playable_mount->Packages().size() == 7);
    Eden::NupV1::Native::ContentSet exec_content(playable_mount);
    const auto* metadata = playable_mount->ApplicationMetadata();
    assert(metadata);
    assert(metadata->title == "Demo / Game");
    assert(metadata->publisher == "Example Publisher");
    assert(metadata->display_version == "3.0.0");
    assert(metadata->TitleFor("fr-FR") == "Démo / Jeu");
    assert(metadata->TitleFor("en-US") == "Demo Game (US)");
    assert(metadata->TitleFor("de-DE") == "Demo / Game");
    const auto* fr_icon = metadata->IconFor("fr-FR");
    assert(fr_icon && fr_icon->size() > 8);
    assert((*fr_icon)[0] == 0x89 && (*fr_icon)[1] == 0x50);
    const auto* fallback_icon = metadata->IconFor("de-DE");
    assert(fallback_icon && (*fallback_icon)[0] == 0xff);
    assert(metadata->default_icon.size() >= 3);
    assert(metadata->default_icon[0] == 0xff);
    assert(metadata->default_icon[1] == 0xd8);
    assert(metadata->default_icon[2] == 0xff);
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
    assert(exec_content.AddOns()[0].package_index == 5);
    assert(exec_content.AddOns()[1].package_index == 4);
    assert(exec_content.AddOns()[0].title_id != exec_content.AddOns()[1].title_id);
    assert(exec_content.AddOns()[0].version == 2);
    assert(exec_content.AddOns()[1].version == 0);
    assert(Read(exec_content.AddOns()[0].romfs->GetFile("addon.dat")) == "addon-one-v2");
    assert(Read(exec_content.AddOns()[1].romfs->GetFile("addon.dat")) == "addon-two");
    assert(Read(exec_content.CreateAddOnRomFS(5)) == "addon.dat=addon-one-v2\n");
    assert(Read(exec_content.CreateAddOnRomFS(4)) == "addon.dat=addon-two\n");
    assert(!exec_content.CreateAddOnRomFS(0)); // base
    assert(!exec_content.CreateAddOnRomFS(1)); // update
    assert(!exec_content.CreateAddOnRomFS(3)); // replaced older addon
    assert(!exec_content.CreateAddOnRomFS(6)); // unrelated game addon
    assert(!exec_content.CreateAddOnRomFS(500));
    assert(!effective_tree->GetFile("addon.dat"));
    // ExeFS handles remain valid after dropping the owning ContentSet/Mount.
    auto still_readable = exefs->GetFile("main");
    exefs.reset();
    playable_mount.reset();
    assert(Read(still_readable) == "latest-main");
    // Explicit-only NUP AppLoader adapter: reuse the extracted ExeFS loader
    // while overriding ReadRomFS with the NUP effective tree. No FileType,
    // catalogue or frontend registration is performed by this test.
    error.clear();
    auto app = Eden::NupV1::Native::NupAppLoader::Open(executable_input, &error);
    assert(app && error.empty());
    assert(app->GetFileType() == Loader::FileType::Unknown);
    assert(!app->IsRomFSUpdatable()); // already overlaid highest NCM version
    FileSys::NACP no_control;
    assert(app->ReadControlData(no_control) == Loader::ResultStatus::ErrorNoControl);
    FileSys::VirtualFile romfs_result;
    assert(app->ReadRomFS(romfs_result) == Loader::ResultStatus::Success);
    assert(Read(romfs_result) == "state.bin=latest-v3\n");
    FileSys::VirtualFile second_romfs;
    assert(app->ReadRomFS(second_romfs) == Loader::ResultStatus::Success);
    assert(romfs_result == second_romfs); // lazily built once per app
    std::atomic<bool> romfs_stable{true};
    std::vector<std::thread> romfs_workers;
    for (int i = 0; i < 6; ++i) {
        romfs_workers.emplace_back([&] {
            FileSys::VirtualFile concurrent_romfs;
            if (app->ReadRomFS(concurrent_romfs) != Loader::ResultStatus::Success ||
                concurrent_romfs != romfs_result) {
                romfs_stable.store(false, std::memory_order_relaxed);
            }
        });
    }
    for (auto& worker : romfs_workers) worker.join();
    assert(romfs_stable.load());
    std::uint64_t program_id{};
    std::string app_title;
    assert(app->ReadProgramId(program_id) == Loader::ResultStatus::Success);
    assert(program_id == 0x0100123400000000ULL);
    assert(app->ReadTitle(app_title) == Loader::ResultStatus::Success);
    assert(app_title == "Demo / Game");
    std::vector<u8> app_icon;
    assert(app->ReadIcon(app_icon) == Loader::ResultStatus::Success);
    assert(app_icon.size() == metadata->default_icon.size());
    assert(app_icon[0] == 0xff && app_icon[1] == 0xd8);

    Loader::AppLoader::Modules modules;
    assert(app->ReadNSOModules(modules) == Loader::ResultStatus::ErrorNotInitialized);
    Kernel::KProcess process;
    Core::System system;
    assert(app->Load(process, system).first == Loader::ResultStatus::Success);
    assert(app->ReadNSOModules(modules) == Loader::ResultStatus::Success);
    assert(modules.at(0) == "main");
    assert(app->Load(process, system).first == Loader::ResultStatus::ErrorAlreadyLoaded);
    app.reset();
    assert(Read(romfs_result) == "state.bin=latest-v3\n");

    auto missing_exefs_source = std::make_shared<MemoryFile>(Load(argv[1]));
    error.clear();
    auto missing_exefs = Eden::NupV1::Native::NupAppLoader::Open(
        missing_exefs_source, &error);
    assert(!missing_exefs && error == "NUP effective ExeFS lacks main or main.npdm");
    auto cross_title_input = std::make_shared<MemoryFile>(Load(argv[4]));
    error.clear();
    auto cross_title = Eden::NupV1::Native::Mount::Open(cross_title_input, &error);
    assert(!cross_title && error == "unrelated base/update title ID");
    // Invalid identity must fail at Open(), before constructing the real
    // extracted-loader (which eagerly parses NPDM in its constructor).
    auto forged_input = std::make_shared<MemoryFile>(Load(argv[5]));
    error.clear();
    auto forged = Eden::NupV1::Native::NupAppLoader::Open(forged_input, &error);
    assert(!forged && error == "NUP invalid NPDM program identity");
    auto sibling_input = std::make_shared<MemoryFile>(Load(argv[6]));
    error.clear();
    auto sibling = Eden::NupV1::Native::NupAppLoader::Open(sibling_input, &error);
    assert(!sibling && error == "NUP invalid NPDM program identity");

    // Source immutability is NOT promised even by a read-only VfsFile.
    // Revalidate NPDM before every post-open loader API exposure.
    auto mutable_app_input = std::make_shared<MemoryFile>(Load(argv[3]));
    error.clear();
    auto mutable_app = Eden::NupV1::Native::NupAppLoader::Open(
        mutable_app_input, &error);
    assert(mutable_app && error.empty());
    mutable_app_input->Corrupt("latest-npdm");
    u64 preserved_program_id = 0x123456ULL;
    assert(mutable_app->ReadProgramId(preserved_program_id) ==
           Loader::ResultStatus::ErrorBadNPDMHeader);
    assert(preserved_program_id == 0x123456ULL);
    FileSys::VirtualFile denied_romfs;
    assert(mutable_app->ReadRomFS(denied_romfs) ==
           Loader::ResultStatus::ErrorBadNPDMHeader);
    assert(!denied_romfs);
    std::string denied_title = "preserve";
    assert(mutable_app->ReadTitle(denied_title) ==
           Loader::ResultStatus::ErrorBadNPDMHeader);
    assert(denied_title == "preserve");
    std::vector<u8> denied_icon{1, 2, 3};
    assert(mutable_app->ReadIcon(denied_icon) ==
           Loader::ResultStatus::ErrorBadNPDMHeader);
    assert(denied_icon == std::vector<u8>({1, 2, 3}));
    Loader::AppLoader::Modules denied_modules;
    assert(mutable_app->ReadNSOModules(denied_modules) ==
           Loader::ResultStatus::ErrorBadNPDMHeader);
    assert(denied_modules.empty());
    FileSys::NACP denied_control;
    assert(mutable_app->ReadControlData(denied_control) ==
           Loader::ResultStatus::ErrorBadNPDMHeader);
    assert(!mutable_app->MakeAddOnIndex());
    Kernel::KProcess blocked_process;
    Core::System blocked_system;
    assert(mutable_app->Load(blocked_process, blocked_system).first ==
           Loader::ResultStatus::ErrorBadNPDMHeader);
    // A checksummed archive with an invalid UTF-8 metadata TLV is rejected
    // before exposing any title, icon or VFS view to an application.
    error.clear();
    auto invalid_meta = Eden::NupV1::Native::Mount::Open(
        std::make_shared<MemoryFile>(Load(argv[7])), &error);
    assert(!invalid_meta && error == "invalid NUP UTF-8 metadata");
    error.clear();
    auto duplicate_locale = Eden::NupV1::Native::Mount::Open(
        std::make_shared<MemoryFile>(Load(argv[8])), &error);
    assert(!duplicate_locale && error == "duplicate or excessive NUP localized entries");
    // A container without an executable cannot be automatically attributed
    // to a running game. Explicit caller program ID selects exactly its DLC.
    auto addons_input = std::make_shared<MemoryFile>(Load(argv[9]));
    error.clear();
    auto addon_mount = Eden::NupV1::Native::Mount::Open(addons_input, &error);
    assert(addon_mount && addon_mount->Packages().size() == 2);
    Eden::NupV1::Native::ContentSet unscoped(addon_mount);
    assert(unscoped.AddOns().empty());
    Eden::NupV1::Native::ContentSet first_scoped(
        addon_mount, 0x0100123400000000ULL);
    assert(first_scoped.AddOns().size() == 1);
    assert(first_scoped.AddOns().front().package_index == 0);
    assert(Read(first_scoped.CreateAddOnRomFS(0)) == "addon.dat=family-one\n");
    assert(!first_scoped.CreateAddOnRomFS(1));
    Eden::NupV1::Native::ContentSet second_scoped(
        addon_mount, 0x0100123400002000ULL);
    assert(second_scoped.AddOns().size() == 1);
    assert(second_scoped.AddOns().front().package_index == 1);
    assert(Read(second_scoped.CreateAddOnRomFS(1)) == "addon.dat=family-two\n");
    assert(!second_scoped.CreateAddOnRomFS(0));
    // AoC interface never mixes callers, supports stable pagination and
    // resolves an add-on index only into its own independently built RomFS.
    Eden::NupV1::Native::AddOnIndex aoc_first(
        addon_mount, 0x0100123400000000ULL);
    assert(aoc_first.Count(0x0100123400000000ULL) == 1);
    assert(aoc_first.BaseId(0x0100123400000000ULL) ==
           std::optional<u64>{0x0100123400001000ULL});
    assert(aoc_first.ListIds(0x0100123400000000ULL, 0, 2) ==
           std::vector<std::uint32_t>{0});
    assert(aoc_first.ListIds(0x0100123400000000ULL, 1, 2).empty());
    assert(aoc_first.ListIds(0x0100123400002000ULL, 0, 2).empty());
    assert(!aoc_first.OpenRomFS(0x0100123400002000ULL, 0));
    assert(!aoc_first.OpenRomFS(0x0100123400000000ULL, 1));
    assert(Read(aoc_first.OpenRomFS(0x0100123400000000ULL, 0)) ==
           "addon.dat=family-one\n");
    // A trusted NACP can specify a distinct AoC base (e.g., an upgrade
    // pack). Never guess it from the Switch-generation prefix or game ID.
    Eden::NupV1::Native::ContentSet explicit_nacp_base(
        addon_mount, 0x0100123400000000ULL, 0x0100123400003000ULL);
    assert(explicit_nacp_base.AddOns().size() == 1);
    assert(explicit_nacp_base.AddOns().front().package_index == 1);
    assert(Read(explicit_nacp_base.CreateAddOnRomFS(1)) ==
           "addon.dat=family-two\n");
    assert(!explicit_nacp_base.CreateAddOnRomFS(0));
    // Custom AoC family without a caller is never an authority to expose DLC.
    Eden::NupV1::Native::ContentSet unscoped_nacp(
        addon_mount, std::nullopt, 0x0100123400003000ULL);
    assert(unscoped_nacp.AddOns().empty());
    // Misaligned NACP AoC base (not an 0x800-title boundary) is rejected
    // rather than shifted onto adjacent add-on IDs.
    Eden::NupV1::Native::ContentSet misaligned_nacp(
        addon_mount, 0x0100123400000000ULL, 0x0100123400003001ULL);
    assert(misaligned_nacp.AddOns().empty());
    auto base_mounted_again = Eden::NupV1::Native::Mount::Open(
        executable_input, &error);
    assert(base_mounted_again);
    Eden::NupV1::Native::ContentSet wrong_program(
        base_mounted_again, 0x0100123400002000ULL);
    assert(wrong_program.AddOns().empty());
    // An oversized NPDM is rejected before any extracted-loader
    // constructor can allocate from attacker-controlled NPDM fields.
    error.clear();
    auto oversized_input = std::make_shared<MemoryFile>(Load(argv[10]));
    auto oversized = Eden::NupV1::Native::NupAppLoader::Open(
        oversized_input, &error);
    assert(!oversized && error == "NUP invalid NPDM program identity");
    // Auto-derive the real AoC base ID from the base package's 0x4000-byte
    // NACP only *after* NPDM program identity is validated. DLC at the
    // traditional +0x1000 offset must not silently join the declared family.
    error.clear();
    auto nacp_source = std::make_shared<MemoryFile>(Load(argv[11]));
    auto nacp_loader = Eden::NupV1::Native::NupAppLoader::Open(
        nacp_source, &error);
    assert(nacp_loader && error.empty());
    assert(nacp_loader->SelectedAddOns().size() == 1);
    FileSys::NACP nacp_from_tlv;
    assert(nacp_loader->ReadControlData(nacp_from_tlv) ==
           Loader::ResultStatus::Success);
    assert(nacp_from_tlv.IsValidForHostTest());
    assert(nacp_from_tlv.GetDLCBaseTitleId() == 0x0100123400003000ULL);
    assert(nacp_loader->SelectedAddOns()[0].package_index == 1);
    assert(nacp_loader->SelectedAddOns()[0].title_id ==
           0x0100123400003001ULL);
    auto aoc_from_nacp = nacp_loader->MakeAddOnIndex();
    assert(aoc_from_nacp);
    assert(aoc_from_nacp->BaseId(0x0100123400000000ULL) ==
           std::optional<u64>{0x0100123400003000ULL});
    assert(aoc_from_nacp->ListIds(0x0100123400000000ULL, 0, 8) ==
           std::vector<std::uint32_t>{1});
    assert(Read(aoc_from_nacp->OpenRomFS(0x0100123400000000ULL, 1)) ==
           "addon.dat=nacp-declared\n");
    assert(!aoc_from_nacp->OpenRomFS(0x0100123400002000ULL, 1));
    assert(Read(nacp_loader->SelectedAddOns()[0].romfs->GetFile("addon.dat")) ==
           "nacp-declared");
    // The same declared AoC family must be recovered from extracted
    // control.nacp when the NUP TLV is absent.
    error.clear();
    auto extracted_nacp_source = std::make_shared<MemoryFile>(Load(argv[12]));
    auto extracted_nacp_loader = Eden::NupV1::Native::NupAppLoader::Open(
        extracted_nacp_source, &error);
    assert(extracted_nacp_loader && error.empty());
    assert(extracted_nacp_loader->SelectedAddOns().size() == 1);
    FileSys::NACP nacp_from_exefs;
    assert(extracted_nacp_loader->ReadControlData(nacp_from_exefs) ==
           Loader::ResultStatus::Success);
    assert(nacp_from_exefs.IsValidForHostTest());
    assert(nacp_from_exefs.GetDLCBaseTitleId() ==
           nacp_from_tlv.GetDLCBaseTitleId());
    assert(extracted_nacp_loader->SelectedAddOns()[0].package_index == 1);
    assert(Read(extracted_nacp_loader->SelectedAddOns()[0].romfs->GetFile("addon.dat")) ==
           "nacp-declared");
    // The TOC can remain valid after corruption of a NACP member's data.
    // The archive may mount, but its app loader must fail closed, not
    // silently select unrelated DLC through the conventional AoC offset.
    error.clear();
    auto corrupted_nacp_source = std::make_shared<MemoryFile>(Load(argv[13]));
    auto corrupted_nacp_loader = Eden::NupV1::Native::NupAppLoader::Open(
        corrupted_nacp_source, &error);
    assert(!corrupted_nacp_loader && error == "NUP control.nacp integrity failure");
    error.clear();
    auto short_nacp_source = std::make_shared<MemoryFile>(Load(argv[14]));
    auto short_nacp_loader = Eden::NupV1::Native::NupAppLoader::Open(
        short_nacp_source, &error);
    assert(!short_nacp_loader && error == "NUP control.nacp has invalid size");
    // Compressed language tables are preflighted before the real vendor NACP
    // constructor reads them. A valid raw-deflate LanguageEntry is accepted.
    error.clear();
    auto compressed_ok = Eden::NupV1::Native::NupAppLoader::Open(
        std::make_shared<MemoryFile>(Load(argv[15])), &error);
    assert(compressed_ok && error.empty());
    FileSys::NACP compressed_control;
    assert(compressed_ok->ReadControlData(compressed_control) ==
           Loader::ResultStatus::Success);
    assert(compressed_control.IsValidForHostTest());
    // Beyond the NACP inline compressed buffer is always rejected.
    error.clear();
    auto compressed_oversize = Eden::NupV1::Native::NupAppLoader::Open(
        std::make_shared<MemoryFile>(Load(argv[16])), &error);
    assert(!compressed_oversize &&
           error == "NUP unsafe control.nacp language metadata");
    // The vendor copies decompressed content into LanguageEntry slots;
    // incomplete records are not safe to pass to that constructor.
    error.clear();
    auto compressed_partial = Eden::NupV1::Native::NupAppLoader::Open(
        std::make_shared<MemoryFile>(Load(argv[17])), &error);
    assert(!compressed_partial &&
           error == "NUP unsafe control.nacp language metadata");
    // Eager icon extraction must never allocate from an unbounded ExeFS file.
    error.clear();
    auto huge_icon = Eden::NupV1::Native::NupAppLoader::Open(
        std::make_shared<MemoryFile>(Load(argv[18])), &error);
    assert(!huge_icon && error == "NUP ExeFS icon too large");
    std::cout << "NUP native VFS adapter: lifetime, overlay, AoC isolation, mutable hash checks OK\n";
}
