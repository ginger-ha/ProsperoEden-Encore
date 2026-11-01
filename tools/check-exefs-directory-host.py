#!/usr/bin/env python3
"""Host-proof the selected ExeFS game folder and saved ROM path contract.

Compile the *real* game_files.h and actual ValidRomFilename function in a
standalone host fixture, with and without optimisation and under UBSan.
This is not PS5 load/runtime qualification.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
header = (root / "headless/game_files.h").read_text()
settings = (root / "headless/settings_store.h").read_text()
library = (root / "headless/prosperoeden/eden_services.cpp").read_text()
main = (root / "headless/main.cpp").read_text()
start_key = "inline bool ValidRomFilename(std::string_view name) {"
assert settings.count(start_key) == 1
start = settings.index(start_key)
end = settings.index("\n}\n", start) + 2
actual_validator = settings[start:end]
assert "IsDeconstructedGameSelection(name)" in actual_validator
assert "c == '/' && !exefs" in actual_validator
assert 'FindDeconstructedGameMain(entry.path())' in library
assert 'FindNestedGamePackage(entry.path())' in library
assert 'FindGameFolderInput(entry.path())' in library
assert 'IsNestedGameFileSelection(name)' in settings
assert 'IsSafeNestedGameFilePath(selected_root, relative)' in main
assert 'FindAddOnContentDirectories(title_root)' in main
assert 'Eden::IsAddOnContainerName' in main
assert 'FindAddOnContentDirectories(path)' in (root / "headless/metadata_bridge.cpp").read_text()
assert 'eden_scan_addons(const char* updates_dir, const char* keys_dir, const char* roms_dir)' in (root / "headless/metadata_bridge.cpp").read_text()
assert 'FindGameFolderInput(entry.path())' in main
assert 'if (!Eden::ValidRomFilename(file)) continue;' in library
assert 'game.name = CleanTitle(entry_name);' in library
assert 'game.format = format;' in library
assert 'CountExeFsFolders(roms_path)' in library
directory_counter = library.split("int CountExeFsFolders(", 1)[1].split("unsigned int HashPath(", 1)[0]
assert "ListEntries(directory, true, ok)" in directory_counter
assert 'IsSafeDeconstructedGamePath(selected_root, selected_relative)' in main
assert 'Eden::FindGameFolderInput(entry.path())' in main
assert 'selected_path.filename() == "main"' in main
assert 'IsSafeDeconstructedGamePath(selected_root, selected_relative)' in main
assert "symlink_status(folder / name, error)" in header
# Native PS5 release compilation regression: CreateRomFS is declared only by
# core/file_sys/romfs.h, not romfs_factory.h. The real maintained loader must
# include its owning declaration, also with all NS2 flags OFF.
native_extracted = (root / "vendor/encore-active/eden-core/src/core/loader/deconstructed_rom_directory.cpp").read_text()
native_romfs = (root / "vendor/sources/eden/src/core/file_sys/romfs.h").read_text()
assert native_extracted.count('#include "core/file_sys/romfs.h"') == 1
assert 'romfs = FileSys::CreateRomFS(std::move(extracted_romfs), nullptr);' in native_extracted
assert 'VirtualFile CreateRomFS(VirtualDir dir, VirtualDir ext = nullptr);' in native_romfs
# The selected native loader must route an extracted ExeFS/main to the
# directory loader *before* generic NSO detection (rtld/sdk + NPDM identity).
loader_cpp = (root / "vendor/encore-active/eden-core/src/core/loader/loader.cpp").read_text()
identify = loader_cpp.split("FileType IdentifyFile(FileSys::VirtualFile file) {", 1)[1].split("\n}\n", 1)[0]
assert 'file->GetName() == "main"' in identify
assert identify.count("IdentifyFileLoader<AppLoader_DeconstructedRomDirectory>(file)") == 1
assert identify.index("IdentifyFileLoader<AppLoader_DeconstructedRomDirectory>(file)") < identify.index("IdentifyFileLoader<AppLoader_NSO>(file)")
assert 'return *nso_type;' in identify  # bare NSOs must still load as NSO

# The real launcher must read the owning NPDM for extracted program identity,
# rather than claiming the 20-40 MiB 'main' executable is a complete game.
bridge = (root / "headless/metadata_bridge.cpp").read_text()
assert 'ReadExtractedProgramMetadata(rom_path, vfs, &extracted)' in bridge
assert 'metadata->Load(npdm) == Loader::ResultStatus::Success' in bridge
assert 'IsSafeDeconstructedGamePath(root, relative)' in bridge
assert 'extracted.GetTitleID()' in bridge
assert 'ExtractedBaseBytes(entry.path(), cancel)' in library
assert 'ExtractedLocalCover(entry.path())' in library
assert 'std::optional<std::uint64_t>{static_cast<std::uint64_t>(info.st_size)}' in library

source = r"""
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>
#include <unistd.h>
#include "game_files.h"
namespace Eden {
VALIDATOR
}
int main() {
    namespace fs = std::filesystem;
    char format[] = "/tmp/eden-exefs-XXXXXX";
    char* tmp = ::mkdtemp(format);
    assert(tmp != nullptr);
    fs::path root{tmp};
    const fs::path rom = root / "My Game";
    fs::create_directories(rom);
    std::ofstream(rom / "main") << "code";
    std::ofstream(rom / "main.npdm") << "metadata";
    assert(Eden::IsDeconstructedGameDirectory(rom));
    assert(Eden::FindDeconstructedGameMain(rom) == "main");
    assert(Eden::IsSafeDeconstructedGamePath(root, "My Game/main"));
    assert(Eden::IsDeconstructedGameSelection("My Game/main"));
    assert(Eden::ValidRomFilename("My Game/main"));
    assert(Eden::ValidRomFilename("game.NSZ"));
    assert(Eden::ValidRomFilename("game.NAX"));
    assert(!Eden::ValidRomFilename("../main"));
    assert(!Eden::ValidRomFilename("My Game/../main"));
    assert(!Eden::ValidRomFilename("My Game/sub/main"));
    assert(Eden::ValidRomFilename("My Game/base/exefs/main"));
    assert(Eden::ValidRomFilename("My Game/base/game.XCI"));
    assert(Eden::ValidRomFilename("My Game/wrapper/second/title.nsp"));
    assert(!Eden::ValidRomFilename("My Game/updates/001/update.nsp"));
    assert(!Eden::ValidRomFilename("My Game/dlc/addon.nsp"));
    assert(!Eden::ValidRomFilename("My Game/../base/game.nsp"));
    assert(!Eden::ValidRomFilename("My Game\\game.nsp"));
    assert(Eden::ValidRomFilename("My Game/base/extra/sub/exefs/main"));
    assert(!Eden::ValidRomFilename("My Game/updates/458752/exefs/main"));
    assert(!Eden::ValidRomFilename("My Game/Updates/458752/exefs/main"));
    assert(!Eden::ValidRomFilename("My Game/DLC/bonus.nsp"));
    assert(Eden::ValidRomFilename("My Game/assets-romfs/exefs/main"));
    assert(!Eden::ValidRomFilename("updates/458752/exefs/main"));
    assert(!Eden::ValidRomFilename("dlc/exefs/main"));
    assert(!Eden::ValidRomFilename("My Game/dlc/0/exefs/main"));
    assert(!Eden::ValidRomFilename("My Game/../base/exefs/main"));
    assert(!Eden::ValidRomFilename("/main"));
    assert(!Eden::ValidRomFilename("main"));
    assert(!Eden::ValidRomFilename("My Game\\main"));
    assert(!Eden::ValidRomFilename("game.zst"));
    assert(!Eden::ValidRomFilename("folder/main/extra"));
    fs::remove(rom / "main.npdm");
    assert(!Eden::IsDeconstructedGameDirectory(rom));
    fs::create_symlink(rom / "main", rom / "main.npdm");
    assert(!Eden::IsDeconstructedGameDirectory(rom));
    fs::remove(rom / "main.npdm");
    std::ofstream(rom / "main.npdm") << "metadata";
    fs::rename(rom / "main", rom / "real_main");
    fs::create_symlink(rom / "real_main", rom / "main");
    assert(!Eden::IsDeconstructedGameDirectory(rom));
    fs::remove(rom / "main");
    fs::rename(rom / "real_main", rom / "main");
    assert(Eden::IsDeconstructedGameDirectory(rom));
    const fs::path linked = root / "symlinked-game";
    fs::create_directory_symlink(rom, linked);
    assert(!Eden::IsDeconstructedGameDirectory(linked));
    const fs::path nested = root / "Nested Game";
    fs::create_directories(nested / "base" / "exefs");
    fs::create_directories(nested / "base" / "romfs");
    fs::create_directories(nested / "updates" / "458752" / "exefs");
    fs::create_directories(nested / "dlc" / "040074a01bf13001" / "0" / "romfs");
    std::ofstream(nested / "base" / "exefs" / "main") << "code";
    std::ofstream(nested / "base" / "exefs" / "main.npdm") << "metadata";
    std::ofstream(nested / "updates" / "458752" / "exefs" / "main") << "patch";
    std::ofstream(nested / "updates" / "458752" / "exefs" / "main.npdm") << "patchmeta";
    assert(Eden::FindDeconstructedGameMain(nested) == "base/exefs/main");
    assert(Eden::IsSafeDeconstructedGamePath(root, "Nested Game/base/exefs/main"));
    // Top-level content stores cannot surface as independent library games.
    const fs::path external_updates = root / "updates" / "458752" / "exefs";
    fs::create_directories(external_updates);
    std::ofstream(external_updates / "main") << "update";
    std::ofstream(external_updates / "main.npdm") << "meta";
    assert(Eden::FindDeconstructedGameMain(root / "updates").empty());
    const fs::path external_dlc = root / "dlc" / "abc" / "exefs";
    fs::create_directories(external_dlc);
    std::ofstream(external_dlc / "main") << "addon";
    std::ofstream(external_dlc / "main.npdm") << "meta";
    assert(Eden::FindDeconstructedGameMain(root / "dlc").empty());
    const fs::path deeper = root / "Deep Game";
    fs::create_directories(deeper / "base" / "some" / "path" / "exefs");
    std::ofstream(deeper / "base" / "some" / "path" / "exefs" / "main") << "code";
    std::ofstream(deeper / "base" / "some" / "path" / "exefs" / "main.npdm") << "meta";
    assert(Eden::FindDeconstructedGameMain(deeper) == "base/some/path/exefs/main");
    const fs::path bad = root / "Unsafe Game";
    fs::create_directory(bad);
    fs::create_directory_symlink(nested / "base", bad / "base");
    assert(Eden::FindDeconstructedGameMain(bad).empty());
    assert(!Eden::IsSafeDeconstructedGamePath(root, "Unsafe Game/base/exefs/main"));
    const auto packaged = root / "Packaged Game";
    fs::create_directories(packaged / "base" / "container");
    fs::create_directories(packaged / "updates" / "458752");
    fs::create_directories(packaged / "dlc" / "addon");
    std::ofstream(packaged / "base" / "container" / "base.nsp") << "base";
    std::ofstream(packaged / "updates" / "458752" / "update.nsp") << "update";
    std::ofstream(packaged / "dlc" / "addon" / "dlc.nsp") << "addon";
    assert(Eden::FindGameFolderInput(packaged) == "base/container/base.nsp");
    assert(Eden::IsSafeNestedGameFilePath(root, "Packaged Game/base/container/base.nsp"));
    fs::create_directories(packaged / "archives" / "nested" / "Updates" / "v9");
    fs::create_directories(packaged / "base" / "romfs" / "updates");
    fs::create_directory_symlink(packaged / "updates", packaged / "symlinked-addons");
    auto addon_folders = Eden::FindAddOnContentDirectories(packaged);
    assert(addon_folders.size() == 3);
    assert(std::find(addon_folders.begin(), addon_folders.end(), packaged / "updates") != addon_folders.end());
    assert(std::find(addon_folders.begin(), addon_folders.end(), packaged / "dlc") != addon_folders.end());
    assert(std::find(addon_folders.begin(), addon_folders.end(),
                     packaged / "archives" / "nested" / "Updates") != addon_folders.end());
    assert(Eden::IsAddOnContainerName("DLC"));
    assert(Eden::IsAddOnContainerName("add-ons"));
    assert(!Eden::IsAddOnContainerName("romfs"));
    // A loose packaged DLC/update next to the base also selects the title
    // folder for the native metadata-aware content provider.
    std::ofstream(packaged / "DLC_1.nsp") << "addon";
    assert(Eden::FindGameFolderInput(packaged) == "base/container/base.nsp");
    addon_folders = Eden::FindAddOnContentDirectories(packaged);
    assert(addon_folders.size() == 1 && addon_folders.front() == packaged);
    const auto standalone = root / "Single Package";
    fs::create_directory(standalone);
    std::ofstream(standalone / "some-title.xci") << "game";
    assert(Eden::FindGameFolderInput(standalone) == "some-title.xci");
    const auto mixed_case = root / "Mixed Case";
    fs::create_directories(mixed_case / "Updates" / "v2");
    std::ofstream(mixed_case / "title.xci") << "base";
    std::ofstream(mixed_case / "Updates" / "v2" / "patch.nsp") << "patch";
    assert(Eden::FindGameFolderInput(mixed_case) == "title.xci");
    // Any wrapper name works; content metadata will establish Update/AOC.
    const auto arbitrary = root / "Arbitrary Folders";
    fs::create_directories(arbitrary / "base");
    fs::create_directories(arbitrary / "custom" / "extensions");
    std::ofstream(arbitrary / "base" / "game.xci") << "base";
    std::ofstream(arbitrary / "custom" / "extensions" / "bonus.nsp") << "addon";
    assert(Eden::FindGameFolderInput(arbitrary) == "base/game.xci");
    addon_folders = Eden::FindAddOnContentDirectories(arbitrary);
    assert(addon_folders.size() == 1);
    assert(addon_folders.front() == arbitrary / "custom" / "extensions");
    // A single base package must not be mistaken for an add-on.
    addon_folders = Eden::FindAddOnContentDirectories(standalone);
    assert(addon_folders.empty());
    // A symlink to an external add-on must not be followed by discovery.
    fs::create_symlink(arbitrary / "custom" / "extensions" / "bonus.nsp",
                       arbitrary / "base" / "bonus.nsp");
    addon_folders = Eden::FindAddOnContentDirectories(arbitrary);
    assert(addon_folders.size() == 1);
    assert(addon_folders.front() == arbitrary / "custom" / "extensions");
    // Two possible add-ons in a nested directory select that directory
    // once, rather than registering duplicate or adjacent base inputs.
    std::ofstream(arbitrary / "custom" / "extensions" / "extra.xcz") << "addon2";
    addon_folders = Eden::FindAddOnContentDirectories(arbitrary);
    assert(addon_folders.size() == 1);
    assert(addon_folders.front() == arbitrary / "custom" / "extensions");
    assert(Eden::LooksLikeExtractedAocTitleId("010074a01bf13001"));
    assert(!Eden::LooksLikeExtractedAocTitleId("010074a01bf12001"));
    const auto custom_extracted = root / "Extracted Custom DLC";
    fs::create_directories(custom_extracted / "custom" / "extra" /
                           "010074a01bf13001" / "0" / "romfs");
    addon_folders = Eden::FindAddOnContentDirectories(custom_extracted);
    assert(addon_folders.size() == 1);
    assert(addon_folders.front() ==
           custom_extracted / "custom" / "extra" / "010074a01bf13001");
    const auto mixed_images = root / "Mixed Packages";
    fs::create_directory(mixed_images);
    std::ofstream(mixed_images / "my-game.xci") << "base";
    std::ofstream(mixed_images / "bonus.nsp") << "dlc";
    std::ofstream(mixed_images / "latest-patch.nsz") << "patch";
    assert(Eden::FindGameFolderInput(mixed_images) == "my-game.xci");
    addon_folders = Eden::FindAddOnContentDirectories(mixed_images);
    assert(addon_folders.size() == 1 && addon_folders.front() == mixed_images);
    std::ofstream(mixed_images / "another-game.xcz") << "other";
    assert(Eden::FindGameFolderInput(mixed_images).empty());
    const auto ambiguous = root / "Ambiguous";
    fs::create_directory(ambiguous);
    std::ofstream(ambiguous / "one.nsp") << "base?";
    std::ofstream(ambiguous / "two.nsp") << "base?";
    assert(Eden::FindGameFolderInput(ambiguous).empty());
    const auto linked_package = root / "Linked Package";
    fs::create_directory(linked_package);
    fs::create_symlink(standalone / "some-title.xci", linked_package / "base.xci");
    assert(Eden::FindNestedGamePackage(linked_package).empty());
    assert(!Eden::IsSafeNestedGameFilePath(root, "Linked Package/base.xci"));
    assert(Eden::FindDeconstructedGameMain(root / "updates").empty());
    assert(Eden::FindNestedGamePackage(root / "dlc").empty());
    fs::remove_all(root);
    std::puts("EXEFS_DIRECTORY_AND_SELECTION_PASS");
}
""".replace("VALIDATOR", actual_validator)

compilers = [exe for exe in (shutil.which("clang++"), shutil.which("g++"))
             if exe]
assert compilers, "C++20 host compiler required"
with tempfile.TemporaryDirectory(prefix="encore-exefs-host-") as temp:
    cpp = Path(temp) / "test.cpp"
    cpp.write_text(source)
    for compiler in dict.fromkeys(compilers):
        for opt in ("-O0", "-O2"):
            exe = Path(temp) / (Path(compiler).name + opt)
            built = subprocess.run(
                [compiler, "-std=c++20", opt, "-Wall", "-Wextra", "-Werror",
                 "-fsanitize=undefined", "-fno-sanitize-recover=all",
                 "-I", str(root / "headless"), str(cpp), "-o", str(exe)],
                capture_output=True, text=True, timeout=60
            )
            assert built.returncode == 0, (compiler, opt, built.stderr[-4000:])
            check = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
            assert check.returncode == 0 and "EXEFS_DIRECTORY_AND_SELECTION_PASS" in check.stdout, (
                compiler, opt, check.stdout, check.stderr[-4000:]
            )
            print("EXEFS_REAL_SOURCE_HOST_PASS", Path(compiler).name, opt)

# Replay the exact directory-sizing and local cover fallback helpers extracted
# from the shipping launcher service, not a reimplementation of their logic.
def extract_owner(begin, end):
    assert library.count(begin) == 1, begin
    remainder = library.split(begin, 1)[1]
    assert end in remainder, end
    return begin + remainder.split(end, 1)[0]

sizing = extract_owner("std::optional<std::uint64_t> ExtractedBaseBytes(",
                       "\n// Local user-supplied covers")
covers = extract_owner("std::string ExtractedLocalCover(",
                       "\nstd::uint64_t ResolveTitleId(")
fixture = r"""
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <optional>
#include <string>
#include <unistd.h>
#include "game_files.h"

SIZING
COVERS

int main() {
    namespace fs = std::filesystem;
    char scratch[] = "/tmp/eden-base-size-XXXXXX";
    const auto* tmp = ::mkdtemp(scratch);
    assert(tmp);
    const fs::path root{tmp};
    const auto game = root / "Extracted Game";
    fs::create_directories(game / "base" / "exefs");
    fs::create_directories(game / "base" / "romfs");
    fs::create_directories(game / "updates" / "458752");
    fs::create_directories(game / "dlc" / "010074a01bf13001");
    std::ofstream(game / "base" / "exefs" / "main") << "exec";
    std::ofstream(game / "base" / "exefs" / "main.npdm") << "program!";
    std::ofstream(game / "base" / "romfs" / "data.bin") << std::string(4096, 'r');
    std::ofstream(game / "updates" / "458752" / "update.bin") << std::string(65536, 'u');
    std::ofstream(game / "dlc" / "010074a01bf13001" / "asset.bin") <<
        std::string(32768, 'd');
    assert(Eden::FindDeconstructedGameMain(game) == "base/exefs/main");
    const auto bytes = ExtractedBaseBytes(game, nullptr);
    assert(bytes && *bytes == 4 + 8 + 4096);
    assert(ExtractedLocalCover(game).empty());
    // The selected ExeFS artwork may be an image stored as a .dat sidecar,
    // e.g. icon_AmericanEnglish.dat in native Switch dumps.
    {
        std::ofstream icon(game / "base" / "exefs" / "icon_AmericanEnglish.dat",
                           std::ios::binary);
        icon.put(static_cast<char>(0xff));
        icon.put(static_cast<char>(0xd8));
        icon << std::string(160, 'J');
    }
    assert(ExtractedLocalCover(game) ==
           (game / "base" / "exefs" / "icon_AmericanEnglish.dat").string());
    fs::remove(game / "base" / "exefs" / "icon_AmericanEnglish.dat");
    // Unrelated binary data must not be accepted solely because of its name.
    std::ofstream(game / "base" / "exefs" / "icon_AmericanEnglish.dat") <<
        std::string(160, 'Q');
    assert(ExtractedLocalCover(game).empty());
    fs::remove(game / "base" / "exefs" / "icon_AmericanEnglish.dat");
    std::ofstream(game / "cover.png") << std::string(160, 'p');
    assert(ExtractedLocalCover(game) == (game / "cover.png").string());
    fs::remove(game / "cover.png");
    const auto outside = root / "outside.jpg";
    std::ofstream(outside) << std::string(4096, 'x');
    fs::create_symlink(outside, game / "cover.jpg");
    assert(ExtractedLocalCover(game).empty());
    std::atomic<bool> cancel{true};
    assert(!ExtractedBaseBytes(game, &cancel));
    fs::remove_all(root);
    std::puts("EXTRACTED_BASE_FOOTPRINT_AND_ARTWORK_PASS");
}
""".replace("SIZING", sizing).replace("COVERS", covers)
with tempfile.TemporaryDirectory(prefix="encore-extracted-library-") as temp:
    cpp = Path(temp) / "test.cpp"
    cpp.write_text(fixture)
    for compiler in dict.fromkeys(compilers):
        for opt in ("-O0", "-O2"):
            exe = Path(temp) / (Path(compiler).name + opt)
            built = subprocess.run(
                [compiler, "-std=c++20", opt, "-Wall", "-Wextra", "-Werror",
                 "-fsanitize=undefined", "-fno-sanitize-recover=all",
                 "-I", str(root / "headless"), str(cpp), "-o", str(exe)],
                capture_output=True, text=True, timeout=60)
            assert built.returncode == 0, (compiler, opt, built.stderr[-5000:])
            check = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
            assert check.returncode == 0, (compiler, opt, check.stdout, check.stderr)
            print("EXTRACTED_LIBRARY_REAL_OWNER_HOST_PASS", Path(compiler).name, opt)
