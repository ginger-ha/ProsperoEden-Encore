#!/usr/bin/env python3
"""Compile and exercise the real NS1/NS2 firmware and keys resolver."""
from pathlib import Path
import subprocess
import tempfile
import shutil

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "headless/assets_dir.h").read_text()
source = source.replace('#include "settings_store.h"', '')
source = source.replace('#include "storage_paths.h"', '')
source = source.replace('#pragma once', '')
compiler = shutil.which("clang++-18") or shutil.which("clang++") or shutil.which("g++")
assert compiler, "No C++20 compiler found"
cpp = r"""
#include <cassert>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>
namespace Eden {
static std::string test_root;
bool FilesystemAccess() { return true; }
std::string AppFile(std::string_view) { return {}; }
std::string LoadSavedAssetsDir() { return test_root; }
constexpr const char* kDefaultAssetsDir = "/unused";
}
""" + source + r"""
namespace fs=std::filesystem;
static void put(const fs::path& p, const std::string& data="test") {
  fs::create_directories(p.parent_path());
  std::ofstream(p, std::ios::binary) << data;
}
int main(int argc, char** argv) {
  assert(argc==2);
  using Eden::SwitchFamily;
  const fs::path r{argv[1]};
  Eden::test_root=r.string();
  fs::create_directories(r / "firmware");
  put(r / "firmware/firmware1.nca");
  // Legacy flat NCAs resolve only as NS1; never auto-claim NS2.
  assert(Eden::ResolveFirmwarePath(SwitchFamily::Switch1)==(r/"firmware").string());
  assert(Eden::ResolveFirmwarePath(SwitchFamily::Switch2)!=(r/"firmware").string());
  fs::remove(r / "firmware/firmware1.nca");
  put(r / "firmware/ns1/0100000000000809/main.npdm", "META");
  put(r / "firmware/ns2/0400000000000019/main.npdm", "META");
  assert(Eden::ResolveFirmwarePath(SwitchFamily::Switch1)==(r/"firmware/ns1").string());
  assert(Eden::ResolveFirmwarePath(SwitchFamily::Switch2)==(r/"firmware/ns2").string());
  fs::remove_all(r / "firmware/ns1");
  fs::remove_all(r / "firmware/ns2");
  put(r / "firmware/switch1/fw.zip");
  put(r / "switch2/firmware/fw.nca");
  assert(Eden::ResolveFirmwarePath(SwitchFamily::Switch1)==(r/"firmware/switch1").string());
  assert(Eden::ResolveFirmwarePath(SwitchFamily::Switch2)==(r/"switch2/firmware").string());
  put(r / "keys/ns1/prod.keys");
  put(r / "keys/switch2/prod.keys");
  assert(Eden::ResolveKeysPath(SwitchFamily::Switch1)==(r/"keys/ns1").string());
  assert(Eden::ResolveKeysPath(SwitchFamily::Switch2)==(r/"keys/switch2").string());
  fs::remove_all(r / "keys/ns1");
  fs::remove_all(r / "keys/switch2");
  put(r / "keys/prod.keys");
  assert(Eden::ResolveKeysPath(SwitchFamily::Switch1)==(r/"keys").string());
  assert(Eden::ResolveKeysPath(SwitchFamily::Switch2)==(r/"keys").string());
  // Untrusted symlink roots cannot cross outside the chosen storage root.
  fs::remove_all(r/"switch2");
  std::error_code ec;
  fs::create_directory_symlink(r / "firmware/switch1",r/"switch2",ec);
  assert(Eden::ResolveFirmwarePath(SwitchFamily::Switch2)!=(r/"switch2").string());
  assert(Eden::DetectFirmwareFormat(r/"firmware/switch1")==Eden::FirmwareFormat::Zip);
  assert(Eden::AssetsPath("firmware")==Eden::ResolveFirmwarePath(SwitchFamily::Switch1));
  assert(Eden::AssetsPath("keys")==Eden::ResolveKeysPath(SwitchFamily::Switch1));
}
"""
with tempfile.TemporaryDirectory(prefix="encore-firmware-matrix-") as d:
    root = Path(d)
    (root/"fixture.cpp").write_text(cpp)
    subprocess.run([compiler,"-std=c++20","-Wall","-Wextra","-Werror",
                    str(root/"fixture.cpp"),"-o",str(root/"check")],
                   check=True,timeout=45)
    subprocess.run([str(root/"check"),str(root/"storage")],check=True,timeout=20)
print("ENCORE_FIRMWARE_MATRIX_HOST_PASS ns1=nca,extracted,zip ns2=nca,extracted keys=isolated,flat safe_symlinks=1")
