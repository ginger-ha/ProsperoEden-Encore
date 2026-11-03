#!/usr/bin/env python3
"""Compile actual pinned vendor RomFSBuildContext with the native NUP VFS.

RomFSBuildContext, CreateRomFS/ExtractRomFS, concat, VectorVFS and
OffsetVFS all use real pinned vendor sources; only the base abstract VFS API
and the unused IPS extension patching use small host stubs.
Neither the PS5 core nor renderer is built.
"""
from __future__ import annotations
import importlib.util
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
SOURCES = (
    "core/file_sys/fsmitm_romfsbuild.cpp",
    "core/file_sys/fsmitm_romfsbuild.h",
    "common/alignment.h",
    "common/common_types.h",
    "core/file_sys/vfs/vfs_concat.cpp",
    "core/file_sys/vfs/vfs_concat.h",
    "core/file_sys/vfs/vfs_static.h",
    "core/file_sys/vfs/vfs_vector.h",
    "core/file_sys/vfs/vfs_vector.cpp",
    "core/file_sys/vfs/vfs_offset.h",
    "core/file_sys/vfs/vfs_offset.cpp",
    "core/file_sys/vfs/vfs_cached.h",
    "core/file_sys/romfs.cpp",
    "core/file_sys/romfs.h",
    "common/string_util.h",
    "common/swap.h",
)


def main() -> None:
    pinned = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD:vendor"], text=True
    ).strip()
    assert len(pinned) == 40
    urlbase = (
        "https://raw.githubusercontent.com/niakw/Prospero.Eden-Encore-vendor/"
        + pinned + "/sources/eden/src/"
    )
    spec = importlib.util.spec_from_file_location(
        "nup_content", ROOT / "tools/nup-v1-content-fixture.py"
    )
    assert spec is not None and spec.loader is not None
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)

    with tempfile.TemporaryDirectory() as tempdir:
        temp = Path(tempdir)
        vendor = temp / "pinned-vendor"
        for path in SOURCES:
            with urlopen(Request(urlbase + path, headers={
                "User-Agent": "EdenEncore-NUP-RomFS-Host"
            }), timeout=20) as response:
                source = response.read(128 * 1024 + 1)
            if len(source) > 128 * 1024 or not source.startswith(b"// SPDX-"):
                raise ValueError(f"invalid pinned RomFS vendor source: {path}")
            target = vendor / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source)
        # Use the actual pinned Vector/Offset VFS declarations, while
        # retaining only the small generic host VfsFile/VfsDirectory ABI.
        overrides = temp / "real-vfs-api"
        for path in (
            "core/file_sys/vfs/vfs_vector.h",
            "core/file_sys/vfs/vfs_offset.h",
        ):
            target = overrides / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(vendor / path, target)
        test_archive = temp / "nested-updates-and-addons.nup"
        test_archive.write_bytes(fixtures.executable_fixture())

        binary = temp / "nup-real-romfs"
        cmd = [
            os.environ.get("CXX", "g++"), "-std=c++20", "-O1", "-g",
            "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
            "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
            "-pedantic", "-I", str(overrides),
            "-I", str(ROOT / "tools/nup-native-host-stub"),
            "-I", str(vendor), "-I", str(ROOT / "headless"),
            str(ROOT / "headless/nup_v1_vfs.cpp"),
            str(ROOT / "headless/nup_v1_native_vfs.cpp"),
            str(ROOT / "headless/nup_v1_native_content.cpp"),
            str(vendor / "core/file_sys/fsmitm_romfsbuild.cpp"),
            str(vendor / "core/file_sys/vfs/vfs_concat.cpp"),
            str(vendor / "core/file_sys/vfs/vfs_vector.cpp"),
            str(vendor / "core/file_sys/vfs/vfs_offset.cpp"),
            str(vendor / "core/file_sys/romfs.cpp"),
            str(ROOT / "tools/nup-v1-real-romfs-host.cpp"),
            "-lcrypto", "-lzstd", "-pthread", "-o", str(binary),
        ]
        subprocess.run(cmd, check=True)
        env = dict(os.environ,
                   ASAN_OPTIONS="halt_on_error=1:detect_leaks=0",
                   UBSAN_OPTIONS="print_stacktrace=1:halt_on_error=1")
        subprocess.run([str(binary), str(test_archive)], check=True, env=env)
        print(f"Pinned vendor full RomFS round-trip {pinned[:12]}: NUP overlay/AoC binary layout OK")


if __name__ == "__main__":
    main()
