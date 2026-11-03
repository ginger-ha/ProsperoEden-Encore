#!/usr/bin/env python3
"""Host-proof actual shared extracted-AOC path parser, plus source wiring.

This cannot prove retail DLC content decrypts or a PS5 game runs.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
vendor = root / "vendor/encore-active/eden-core/src/core"
header = vendor / "file_sys/extracted_aoc_paths.h"
wrapper = vendor / "file_sys/extracted_aoc.h"
aoc = vendor / "hle/service/aoc/addon_content_manager.cpp"
romfs = vendor / "file_sys/romfs_factory.cpp"
cmake = (root / "headless/CMakeLists.txt").read_text()
assert header.is_file() and wrapper.is_file() and aoc.is_file() and romfs.is_file()
assert "ExtractedAoc::InstalledIds()" in aoc.read_text()
assert "ExtractedAoc::OpenRomFS(title_id)" in romfs.read_text()
assert "romfs_factory.cpp" in cmake and "addon_content_manager.cpp" in cmake
assert "file_sys/romfs_factory.cpp" in cmake
assert "hle/service/aoc/addon_content_manager.cpp" in cmake
assert "CreateRomFS(std::move(directory))" in wrapper.read_text()
assert 'std::find(disabled.begin(), disabled.end(), "DLC")' in wrapper.read_text()
ui = (root / "headless/metadata_bridge.cpp").read_text()
assert "FileSys::ExtractedAoc::Scan(scan_paths)" in ui
assert "dlc.insert(entry.title_id).second" in ui
assert "std::vector<std::string> scan_paths;" in ui
# P3.4: no partial update/DLC metadata may be published as complete.
# The worker scans a bounded number of title roots and every nested addon
# traversal reports whether it was complete. A missing optional global root
# is okay; an existing provider root that fails to open must refuse publish.
scan = ui.split("void eden_scan_addons(", 1)[1].split(
    "\\n// Native launch-time display-art version:", 1)[0]
assert "std::filesystem::directory_options::none" in scan
assert "if (++scanned_titles > 2048)" in scan
assert "exceeded_limit = true;" in scan
assert "if (error || exceeded_limit) return;" in scan
assert "FindAddOnContentDirectories(path, &complete)" in scan
assert "if (!complete) return;" in scan
assert "if (!append_root(updates_dir)) return;" in scan
assert "if (!append_root(directory)) return;" in scan
assert "if (status_error) return false;" in scan
assert scan.index("if (error || exceeded_limit) return;") < scan.index("publish(true);")
boot = (root / "headless/main.cpp").read_text()
assert "IsSafeExtractedDirectory(title_root)" in boot
assert "FindAddOnContentDirectories(" in boot
assert "title_root, &complete" in boot

fixture = r"""
#include <algorithm>
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include "extracted_aoc_paths.h"
namespace fs = std::filesystem;
int main(int argc, char** argv) {
    assert(argc == 2);
    const fs::path root{argv[1]};
    const fs::path game = root / "My Game";
    const fs::path dlc = game / "dlc";
    const fs::path id = dlc / "010074a01bf13001";
    fs::create_directories(id / "0" / "romfs");
    std::ofstream(id / "0" / "romfs" / "one.bin") << "test";
    fs::create_directories(game / "base" / "romfs");
    fs::create_directories(dlc / "not-an-id" / "0" / "romfs");
    fs::create_directories(dlc / "010074a01bf14001" / "romfs"); // wrong low-range
    fs::create_directories(dlc / "0100aaaa1bf13001" / "romfs");
    const auto title = FileSys::ExtractedAoc::ParseTitleId("010074a01bf13001");
    assert(title.has_value());
    assert(!FileSys::ExtractedAoc::ParseTitleId("010074a01bf12001"));
    assert(!FileSys::ExtractedAoc::ParseTitleId("bonus"));
    assert(FileSys::ExtractedAoc::BelongsToBase(*title, 0x010074a01bf12000ULL));
    assert(!FileSys::ExtractedAoc::BelongsToBase(*title, 0x0100aaaa1bf12000ULL));
    auto found = FileSys::ExtractedAoc::Scan({dlc.string()});
    assert(found.size() == 2);
    assert(std::find_if(found.begin(), found.end(), [&](const auto& e) {
        return e.title_id == *title && e.romfs_path == id / "0" / "romfs";
    }) != found.end());
    fs::create_directories(dlc / "other" / "010074a01bf13001" / "romfs");
    found = FileSys::ExtractedAoc::Scan({dlc.string()});
    // Two distinct extracted mounts for the same DLC ID: reject ambiguity.
    assert(found.size() == 1);
    assert(found.front().title_id != *title);
    fs::create_directory_symlink(id, dlc / "linked-id");
    found = FileSys::ExtractedAoc::Scan({dlc.string()});
    assert(found.size() == 1);
    std::cout << "EXTRACTED_AOC_REAL_HEADER_PASS\n";
}
"""
compilers = list(dict.fromkeys(c for c in (shutil.which("clang++"), shutil.which("g++")) if c))
assert compilers, "No C++20 host compiler"
with tempfile.TemporaryDirectory(prefix="encore-extracted-aoc-") as temporary:
    temp = Path(temporary)
    cpp = temp / "aoc_test.cpp"
    cpp.write_text(fixture)
    for compiler in compilers:
        for opt in ("-O0", "-O2"):
            exe = temp / f"{Path(compiler).name}{opt}"
            run = subprocess.run(
                [compiler, "-std=c++20", opt, "-Wall", "-Wextra", "-Werror",
                 "-fsanitize=undefined", "-fno-sanitize-recover=all",
                 "-I", str(header.parent), str(cpp), "-o", str(exe)],
                text=True, capture_output=True, timeout=60)
            assert run.returncode == 0, (compiler, run.stderr[-3000:])
            r = subprocess.run([str(exe), str(temp / f"files-{exe.name}")],
                               text=True, capture_output=True, timeout=30)
            assert r.returncode == 0 and "EXTRACTED_AOC_REAL_HEADER_PASS" in r.stdout, (
                compiler, r.stdout, r.stderr)
            print("EXTRACTED_AOC_HOST_PASS", Path(compiler).name, opt)
