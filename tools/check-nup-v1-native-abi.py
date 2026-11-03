#!/usr/bin/env python3
"""Compile inactive NUP adapter against exact pinned vendor VFS headers (host only).

Only five textual headers are fetched at the repository's recorded gitlink SHA.
This is a C++ ABI/source-signature preflight, NOT a full vendor/core/PS5 build.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
FILES = (
    "common/common_funcs.h",
    "common/common_types.h",
    "core/file_sys/fs_filesystem.h",
    "core/file_sys/common_funcs.h",
    "core/file_sys/romfs.h",
    "core/file_sys/vfs/vfs.h",
    "core/file_sys/vfs/vfs_types.h",
)

def main() -> None:
    pinned = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD:vendor"], text=True
    ).strip()
    assert len(pinned) == 40 and all(c in "0123456789abcdef" for c in pinned), pinned
    urlbase = ("https://raw.githubusercontent.com/niakw/"
               "Prospero.Eden-Encore-vendor/" + pinned + "/sources/eden/src/")
    with tempfile.TemporaryDirectory() as folder:
        includes = Path(folder)
        for path in FILES:
            request = Request(urlbase + path, headers={"User-Agent": "EdenEncore-NUP-ABI-CI"})
            with urlopen(request, timeout=20) as response:
                data = response.read(128 * 1024 + 1)
            if len(data) > 128 * 1024 or not data.startswith(b"// SPDX-"):
                raise ValueError(f"Invalid pinned vendor header: {path}")
            target = includes / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        subprocess.run([
            os.environ.get("CXX", "g++"), "-std=c++20", "-fsyntax-only",
            "-Wall", "-Wextra", "-Werror", "-pedantic",
            "-I", str(includes),
            "-I", str(ROOT / "headless"),
            str(ROOT / "headless/nup_v1_native_vfs.cpp"),
            str(ROOT / "headless/nup_v1_native_content.cpp"),
        ], check=True)
    print(f"NUP native adapter compiles against pinned vendor VFS headers {pinned[:12]}")

if __name__ == "__main__":
    main()
