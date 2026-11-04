#!/usr/bin/env python3
"""Compile inactive NUP adapter against exact pinned vendor VFS headers (host only).

Only the native file, RomFS and loader API headers are fetched at the gitlink SHA.
This is a C++ ABI/source-signature preflight, NOT a full vendor/core/PS5 build.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
from urllib.request import Request, urlopen
import sys

ROOT = Path(__file__).resolve().parent.parent
FILES = (
    "common/common_funcs.h",
    "common/common_types.h",
    "core/file_sys/fs_filesystem.h",
    "core/file_sys/common_funcs.h",
    "core/file_sys/romfs.h",
    "core/file_sys/vfs/vfs.h",
    "core/file_sys/vfs/vfs_types.h",
    "core/file_sys/vfs/vfs_vector.h",
    "common/bit_field.h",
    "common/swap.h",
    "core/file_sys/control_metadata.h",
    "core/file_sys/program_metadata.h",
    "core/loader/loader.h",
    "core/loader/deconstructed_rom_directory.h",
)

def main() -> None:
    pinned = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD:vendor"], text=True
    ).strip()
    assert len(pinned) == 40 and all(c in "0123456789abcdef" for c in pinned), pinned
    urlbase = ("https://raw.githubusercontent.com/niakw/"
               "Prospero.Eden-Encore-vendor/" + pinned + "/sources/eden/src/")
    # A locally mounted vendor submodule at the exact gitlink SHA is a
    # stronger and much faster source of truth than repeated HTTP downloads.
    # If absent in a CI sandbox, retain the original pinned-URL fallback.
    local_vendor = ROOT / "vendor/sources/eden/src"
    local_sha = subprocess.run(
        ["git", "-C", str(ROOT / "vendor"), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False)
    local_verified = (
        local_sha.returncode == 0 and local_sha.stdout.strip() == pinned)

    with tempfile.TemporaryDirectory() as folder:
        includes = Path(folder)
        for path in FILES:
            request = Request(urlbase + path, headers={"User-Agent": "EdenEncore-NUP-ABI-CI"})
            local_path = local_vendor / path
            if local_verified and local_path.is_file():
                data = local_path.read_bytes()
            else:
                with urlopen(request, timeout=20) as response:
                    data = response.read(128 * 1024 + 1)
            if len(data) > 128 * 1024 or not data.startswith(b"// SPDX-"):
                raise ValueError(f"Invalid pinned vendor header: {path}")
            target = includes / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        # Apple Clang diagnoses anonymous vendor ABI structs differently
        # from GCC. Suppress only this known extension diagnostic on macOS.
        vendor_abi_flags = ["-Wno-nested-anon-types"] if sys.platform == "darwin" else []
        subprocess.run([
            os.environ.get("CXX", "g++"), "-std=c++20", "-fsyntax-only",
            *vendor_abi_flags,
            # The actual vendor AppLoader header intentionally names unused
            # virtual-function parameters. Keep all other warnings fatal.
            "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-pedantic",
            "-I", str(includes),
            "-I", str(ROOT / "headless"),
            str(ROOT / "headless/nup_v1_native_vfs.cpp"),
            str(ROOT / "headless/nup_v1_native_content.cpp"),
            str(ROOT / "headless/nup_v1_native_aoc.cpp"),
            str(ROOT / "headless/nup_v1_native_loader.cpp"),
            str(ROOT / "headless/nup_v1_loader_route.cpp"),
        ], check=True)
    print(f"NUP native adapter compiles against pinned vendor VFS headers {pinned[:12]}")

if __name__ == "__main__":
    main()
