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
    # A valid central directory must not authorize an inconsistent LOCAL
    # entry or a payload that runs into the ZIP's own index.
    first_member="firmware/0400000000000019/main.npdm"
    with zipfile.ZipFile(fixture) as z:
        info=z.getinfo(first_member)
    original=fixture.read_bytes()
    # A legitimate ZIP comment may contain the four-byte EOCD marker.
    # The importer must continue to the real end record, not stop at the
    # decoy signature and reject the user's firmware archive.
    commented=root/"comment-with-eocd-marker.zip"
    commented.write_bytes(original)
    with zipfile.ZipFile(commented,"a") as z:
        z.comment=b"Firmware notes PK\\x05\\x06" + b"padding-"*8
    with zipfile.ZipFile(commented) as z:
        assert z.testzip() is None
    local=info.header_offset
    assert original[local:local+4] == b"PK\x03\x04"
    name_offset=local+30
    wrong_name=bytearray(original)
    wrong_name[name_offset]=ord("x")
    local_name=root/"bad-local-name.zip"
    local_name.write_bytes(wrong_name)
    wrong_crc=bytearray(original)
    crc_offset=local+14
    wrong_crc[crc_offset] ^= 0x01
    local_crc=root/"bad-local-crc.zip"
    local_crc.write_bytes(wrong_crc)
    directory=original.find(b"PK\x01\x02")
    assert directory>local
    central_entry=original.find(first_member.encode(),directory)
    assert central_entry>=directory+46
    central_header=central_entry-46
    assert original[central_header:central_header+4] == b"PK\x01\x02"
    wrong_extent=bytearray(original)
    # ZIP32 central compressed-length field, little endian.
    wrong_extent[central_header+20:central_header+24]=(directory).to_bytes(4,"little")
    oversized=root/"bad-central-extent.zip"
    oversized.write_bytes(wrong_extent)
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
    assert(argc==7);
    namespace fs=std::filesystem;
    const fs::path archive=argv[1], unsafe=argv[2], destination=argv[6];
    std::string reason;
    if (!Eden::FirmwareZip::Import(archive,destination,&reason)) {
        std::fprintf(stderr, "ZIP_IMPORT_FAIL: %s\\n", reason.c_str());
        return 2;
    }
    assert(fs::is_regular_file(destination/"firmware/0400000000000019/main"));
    assert(fs::file_size(destination/"firmware/0400000000000019/main")==655364);
    assert(!fs::exists(destination/"__MACOSX"));
    assert(fs::is_regular_file(archive));
    assert(!Eden::FirmwareZip::Import(archive,destination,&reason));
    assert(!Eden::FirmwareZip::Import(unsafe,destination.parent_path()/"invalid",&reason));
    assert(!fs::exists(destination.parent_path()/"evil"));
    assert(!fs::exists(destination.parent_path()/"invalid"));
    for (int i=3;i<6;++i) {
        const fs::path rejected=destination.parent_path()/
            ("rejected-"+std::to_string(i));
        assert(!Eden::FirmwareZip::Import(argv[i],rejected,&reason));
        assert(!fs::exists(rejected));
        assert(!fs::exists(rejected.string()+".incomplete"));
    }
}
""")
    output=root/"test"
    subprocess.run([COMPILER,"-std=c++20","-Wall","-Wextra","-Werror",
                    "-I",str(ROOT/"headless"),str(cpp),"-lz","-o",str(output)],
                   check=True,timeout=40)
    subprocess.run([str(output),str(fixture),str(bad),
                    str(local_name),str(local_crc),str(oversized),
                    str(root/"store/firmware/ns2/encore-imported-firmware")],
                   check=True,timeout=20)
    subprocess.run([str(output),str(commented),str(bad),
                    str(local_name),str(local_crc),str(oversized),
                    str(root/"store-commented/firmware/ns2/encore-imported-firmware")],
                   check=True,timeout=20)
print("ENCORE_FIRMWARE_ZIP_NATIVE_HOST_PASS deflate=1 dir_entries=1 crc=1 symlink_guard=1 overwrite=0 traversal=0")
