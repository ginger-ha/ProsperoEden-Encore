#!/usr/bin/env python3
"""Test the inactive FileSys VFS adapter using a minimal host VFS ABI substitute."""
from __future__ import annotations
from pathlib import Path
import importlib.util
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent

def load_fixture_module():
    path = ROOT / "tools/check-nup-v1-vfs-host.py"
    spec = importlib.util.spec_from_file_location("nup_vfs_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def main():
    fixtures = load_fixture_module()
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        binary = temp / "nup-native-host"
        subprocess.run([
            os.environ.get("CXX", "g++"), "-std=c++20", "-O1",
            "-Wall", "-Wextra", "-Werror", "-pedantic",
            "-I", str(ROOT / "tools/nup-native-host-stub"),
            "-I", str(ROOT / "headless"),
            str(ROOT / "headless/nup_v1_vfs.cpp"),
            str(ROOT / "headless/nup_v1_native_vfs.cpp"),
            str(ROOT / "tools/nup-v1-native-host.cpp"),
            "-lcrypto", "-lzstd", "-pthread", "-o", str(binary)
        ], check=True)
        addon = temp / "addon.nup"
        addon.write_bytes(fixtures.layered_fixture(addon=True))
        standalone = temp / "standalone.nup"
        standalone.write_bytes(fixtures.layered_fixture(standalone=True))
        subprocess.run([str(binary), str(addon), str(standalone)], check=True)

if __name__ == "__main__":
    main()
