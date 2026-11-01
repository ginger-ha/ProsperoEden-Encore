#!/usr/bin/env python3
"""Compile/exercise the *actual* startup ZIP auto-discovery helper with mocked storage."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
CPP=(ROOT/"headless/metadata_bridge.cpp").read_text()
start=CPP.index("static void AutoImportFirmwareArchives() {")
end=CPP.index("\nconst char* eden_startup_error()",start)
function=CPP[start:end]
header=(ROOT/"headless/assets_dir.h").read_text()
header=header.replace('#include "settings_store.h"','').replace('#include "storage_paths.h"','').replace("#pragma once","")
compiler=shutil.which("clang++-18") or shutil.which("clang++") or shutil.which("g++")
assert compiler
with tempfile.TemporaryDirectory(prefix="encore-auto-fw-") as tmp:
    root=Path(tmp)
    storage=root/"storage"
    ns1=storage/"firmware/switch1/input.zip"
    ns1.parent.mkdir(parents=True)
    with zipfile.ZipFile(ns1,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("firmware/0100000000000809/main.npdm",b"META"+b"1"*2048)
    ns2=storage/"switch2/firmware/bundle.zip"
    ns2.parent.mkdir(parents=True)
    with zipfile.ZipFile(ns2,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("firmware/system.nca",b"test NCA fixture")
    native=storage/"firmware/ns2-code.zip"
    native.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(native,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("firmware/.ns2jb-firmware-dump.json",b'{"kind":"ns2jb-system-code-dump"}')
        z.writestr("firmware/firmware-dump-named.json",b'{"entries":[]}')
        z.writestr("firmware/0400000000000019/main.npdm",b"META"+b"2"*2048)
    src=r"""
#include <cctype>
#include <cstdio>
#include <fstream>
#include <filesystem>
#include <string>
#include <string_view>
#include <vector>
#include "firmware_zip_import.h"
namespace Eden {
static std::string test_root;
bool FilesystemAccess(){return true;}
std::string AppFile(std::string_view){return {};}
std::string LoadSavedAssetsDir(){return test_root;}
constexpr const char* kDefaultAssetsDir="/unused";
}
"""+header+"\n"+function+r"""
#include <cassert>
int main(int argc,char**argv) {
    assert(argc==2);
    namespace fs=std::filesystem;
    Eden::test_root=argv[1];
    AutoImportFirmwareArchives();
    const fs::path root=Eden::test_root;
    assert(fs::is_regular_file(root/"firmware/ns1/encore-imported-input/firmware/0100000000000809/main.npdm"));
    assert(fs::is_regular_file(root/"firmware/ns2/encore-imported-bundle/firmware/system.nca"));
    assert(fs::is_regular_file(root/"firmware/ns2/encore-imported-ns2-code/firmware/0400000000000019/main.npdm"));
    assert(fs::is_regular_file(root/"firmware/switch1/input.zip"));
    assert(fs::is_regular_file(root/"switch2/firmware/bundle.zip"));
    assert(Eden::ResolveFirmwarePath(Eden::SwitchFamily::Switch1).find("encore-imported-input")!=std::string::npos);
    assert(Eden::ResolveFirmwarePath(Eden::SwitchFamily::Switch2).find("encore-imported-")!=std::string::npos);
    AutoImportFirmwareArchives(); // never replaces completed outputs
}
"""
    input_file=root/"smoke.cpp"
    input_file.write_text(src)
    exe=root/"smoke"
    subprocess.run([compiler,"-std=c++20","-Wall","-Wextra","-Werror",
                    "-I",str(ROOT/"headless"),str(input_file),"-lz","-o",str(exe)],
                   check=True,timeout=45)
    subprocess.run([str(exe),str(storage)],check=True,timeout=35)
print("ENCORE_FIRMWARE_AUTO_IMPORT_HOST_PASS ns1_zip=1 ns2_nca_zip=1 ns2_dump_zip=1 idempotent=1")
