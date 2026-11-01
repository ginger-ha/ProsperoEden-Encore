#!/usr/bin/env python3
"""Compile native ZIP firmware importer, verify deflate/CRC, safe paths and no overwrite."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
COMPILER=shutil.which("clang++-18") or shutil.which("clang++") or shutil.which("g++")
assert COMPILER
with tempfile.TemporaryDirectory(prefix="encore-firmware-auto-") as temp:
    root=Path(temp)
    fixture=root/"firmware.zip"
    with zipfile.ZipFile(fixture,"w",compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("firmware/",b"")
        z.writestr("__MACOSX/._firmware",b"mac metadata")
        z.writestr("firmware/.ns2jb-firmware-dump.json",b'{"kind":"ns2jb-system-code-dump"}')
        z.writestr("firmware/firmware-dump-named.json",b'{"entries":[]}')
        z.writestr("firmware/ncm-system-programs.bin",b"fake-index")
        z.writestr("firmware/0400000000000019/main.npdm",b"META"+b"A"*4096)
        z.writestr("firmware/0400000000000019/main",b"NSO0"+b"B"*655360)
    bad=root/"bad.zip"
    with zipfile.ZipFile(bad,"w",compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("../evil",b"should be rejected")
    cpp=root/"fixture.cpp"
    cpp.write_text(r"""
#include "firmware_zip_import.h"
#include <cassert>
#include <filesystem>
#include <fstream>
#include <string>
int main(int argc,char**argv) {
    assert(argc==4);
    namespace fs=std::filesystem;
    const fs::path archive=argv[1], unsafe=argv[2], destination=argv[3];
    std::string reason;
    assert(Eden::FirmwareZip::Import(archive,destination,&reason));
    assert(fs::is_regular_file(destination/"firmware/0400000000000019/main"));
    assert(fs::file_size(destination/"firmware/0400000000000019/main")==655364);
    assert(!fs::exists(destination/"__MACOSX"));
    assert(fs::is_regular_file(archive));
    assert(!Eden::FirmwareZip::Import(archive,destination,&reason));
    assert(!Eden::FirmwareZip::Import(unsafe,destination.parent_path()/"invalid",&reason));
    assert(!fs::exists(destination.parent_path()/"evil"));
    assert(!fs::exists(destination.parent_path()/"invalid"));
}
""")
    output=root/"test"
    subprocess.run([COMPILER,"-std=c++20","-Wall","-Wextra","-Werror",
                    "-I",str(ROOT/"headless"),str(cpp),"-lz","-o",str(output)],
                   check=True,timeout=40)
    subprocess.run([str(output),str(fixture),str(bad),
                    str(root/"store/firmware/ns2/encore-imported-firmware")],
                   check=True,timeout=20)
print("ENCORE_FIRMWARE_ZIP_NATIVE_HOST_PASS deflate=1 dir_entries=1 crc=1 symlink_guard=1 overwrite=0 traversal=0")
