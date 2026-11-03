#!/usr/bin/env python3
"""Host-only proof: NUP game discovery remains invisible unless P5 is selected."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
# P3.4: a path deleted between iterator discovery and symlink_status
# cannot be silently skipped while the caller publishes a complete DLC map.
header = (ROOT / "headless/game_files.h").read_text()
scan = header.split("FindAddOnContentDirectories(", 1)[1]
assert "if (entry_error) {" in scan
assert "incomplete = true;\\n                return;" in scan
assert "entry_error != std::errc::no_such_file_or_directory" not in scan
CODE = r"""
#include "game_files.h"
#include <cassert>
#include <filesystem>
#include <fstream>
int main(int argc, char** argv) {
    assert(argc == 2);
    namespace fs = std::filesystem;
    // Repeated library scans classify ASCII names without heap allocations.
    // Keep mixed-case addon exclusion and ordinary base-name acceptance.
    assert(Eden::IsAddOnContainerName("UpDaTeS"));
    assert(Eden::IsAddOnContainerName("ADD-ON"));
    assert(!Eden::IsAddOnContainerName("updating"));
    assert(Eden::IsReservedAddOnPackageStem("DLc_MKW"));
    assert(Eden::IsReservedAddOnPackageStem("aoc-Bananza"));
    assert(!Eden::IsReservedAddOnPackageStem("updateable"));
    assert(Eden::IsExtractedAssetFolderName("EXEFS"));
    assert(Eden::IsExtractedAssetFolderName("RomFS"));
    assert(!Eden::IsExtractedAssetFolderName("romfs-old"));
    assert(!Eden::IsNestedGameFileSelection("MKW/DlC/extra.nsp"));
    assert(!Eden::IsNestedGameFileSelection("MKW/BASE/Patch_2.nsp"));
    assert(Eden::IsGameFile("game.nsp"));
    assert(Eden::IsGameFile("game.xci"));
    assert(Eden::IsGameFile("game.nsz"));
    assert(Eden::IsGameFile("game.xcz"));
    assert(!Eden::IsGameFile("update.zst"));
#ifdef EDEN_NUP_V1_RUNTIME
    assert(Eden::IsGameFile("game.NUP"));
    assert(Eden::IsNestedGameFileSelection("MyGame/base/game.nup"));
    assert(!Eden::IsNestedGameFileSelection("MyGame/dlc/a.nup"));
#else
    assert(!Eden::IsGameFile("game.NUP"));
    assert(!Eden::IsNestedGameFileSelection("MyGame/base/game.nup"));
#endif
    assert(Eden::IsNestedGameFileSelection("MyGame/base/game.nsp"));
    assert(!Eden::IsNestedGameFileSelection("../game.nsp"));
    // One non-following status probe per entry must preserve the package
    // ranking, addon exclusion and symlink protection of both scan paths.
    const fs::path game = fs::path(argv[1]) / "Game";
    fs::create_directories(game / "base");
    fs::create_directories(game / "dlc");
    std::ofstream(game / "base" / "game.nsp").put('g');
    std::ofstream(game / "dlc" / "update.nsp").put('u');
    fs::create_directory_symlink(game / "base", game / "linked-base");
    assert(Eden::FindNestedGamePackage(game) == "base/game.nsp");
    assert(Eden::IsSafeNestedGameFilePath(game.parent_path(), "Game/base/game.nsp"));
    assert(!Eden::IsSafeNestedGameFilePath(game.parent_path(), "Game/linked-base/game.nsp"));
    bool complete = false;
    const auto addon_roots = Eden::FindAddOnContentDirectories(game, &complete);
    assert(complete && addon_roots.size() == 1 && addon_roots.front() == game / "dlc");
    // Traversing five wrapper levels is still allowed, and should discover
    // a nested DLC rather than treating it as a separate base game.
    const fs::path bounded = fs::path(argv[1]) / "Bounded";
    const auto allowed = bounded / "a" / "b" / "c" / "d" / "e" / "dlc";
    fs::create_directories(allowed);
    complete = false;
    const auto accepted = Eden::FindAddOnContentDirectories(bounded, &complete);
    assert(complete && accepted.size() == 1 && accepted.front() == allowed);
    // A deeper opaque branch cannot be treated as an empty add-on branch:
    // a partial inventory may hide updates, so fail the entire discovery.
    const fs::path deep = fs::path(argv[1]) / "Deep";
    fs::create_directories(deep / "dlc");
    std::ofstream(deep / "dlc" / "update.nsp").put('u');
    fs::create_directories(deep / "a" / "b" / "c" / "d" / "e" / "f");
    complete = true;
    assert(Eden::FindAddOnContentDirectories(deep, &complete).empty());
    assert(!complete);
    // A valid but empty title remains distinct from an unreadable title.
    const fs::path empty = fs::path(argv[1]) / "Empty";
    fs::create_directories(empty);
    complete = false;
    assert(Eden::FindAddOnContentDirectories(empty, &complete).empty());
    assert(complete);
    complete = true;
    assert(Eden::FindAddOnContentDirectories(empty / "missing", &complete).empty());
    assert(!complete);
    return 0;
}
"""

def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "nup-discovery.cpp"
        source.write_text(CODE, encoding="utf-8")
        for flag in (False, True):
            exe = root / ("nup-on" if flag else "nup-off")
            cmd = [os.environ.get("CXX", "g++"), "-std=c++20",
                   "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
                   "-I", str(ROOT / "headless")]
            if flag:
                cmd.append("-DEDEN_NUP_V1_RUNTIME=1")
            subprocess.run(cmd + [str(source), "-o", str(exe)], check=True)
            subprocess.run([str(exe), str(root / ("fixture-on" if flag else "fixture-off"))], check=True)
    print("NUP game discovery: existing formats unchanged, default OFF, P5 ON OK")

if __name__ == "__main__":
    main()
