#!/usr/bin/env python3
"""Host-only proof: NUP game discovery remains invisible unless P5 is selected."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
CODE = r"""
#include "game_files.h"
#include <cassert>
int main() {
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
            subprocess.run([str(exe)], check=True)
    print("NUP game discovery: existing formats unchanged, default OFF, P5 ON OK")

if __name__ == "__main__":
    main()
