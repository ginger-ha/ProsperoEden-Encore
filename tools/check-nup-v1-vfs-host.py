#!/usr/bin/env python3
"""Compile and exercise isolated C++ NUP VFS (never builds or registers PS5)."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import struct
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def payload_tools():
    module_path = ROOT / "tools/check-nup-v1-payload-host.py"
    spec = importlib.util.spec_from_file_location("nup_payload", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expected(data: bytes) -> str:
    width = min(len(data), 64)
    return f"size={len(data)} first={data[:width].hex()} last={data[-width:].hex()}"


def layered_fixture(*, duplicate_version: bool = False, addon: bool = False,
                    standalone: bool = False,
                    broken_standalone: bool = False) -> bytes:
    """Base/multi-update, standalone updates, and separate AoC package views."""
    bad = 0xFFFFFFFF
    title = 0x0100123400000000
    packages = (
        (title, 1, 1 if standalone else 0, b"base-v1"),
        (title + 0x800, 3, 1, b"latest-v3"),
        (title + (0x1000 if addon else 0x800),
         0 if addon else (3 if duplicate_version else 2),
         2 if addon else 1, b"addon-aoc" if addon else b"older-v2"),
    )
    toc = bytearray(0x2A0)
    names = b"romfsstate.bin"
    struct.pack_into("<4sIQQQQQ", toc, 0, b"TOC\x01",
                     len(packages), 6, 3, 0x288, len(names), 0)
    blob = bytearray()
    absolute = 0x320
    signature = bytearray()
    for i, (title_id, version, kind, data) in enumerate(packages):
        p = 0x30 + 0x40 * i
        struct.pack_into("<QIIII", toc, p, title_id, 2 * i, bad, 2 * i + 1, version)
        toc[p + 0x18] = kind
        if standalone and kind == 1 and not (broken_standalone and i == 1):
            toc[p + 0x19] = 1
        signature.extend(struct.pack("<QIB", title_id, version, kind))
        d = 0xF0 + i * 2 * 0x18
        struct.pack_into("<IIIIQ", toc, d, 0, 0, 2 * i, 1, 0)
        struct.pack_into("<IIIIQ", toc, d + 0x18, 0, 5, 2 * i + 1, 1, 0)
        struct.pack_into("<II", toc, 0x270 + i * 8, 2 * i + 1, 6 + i)
        aligned = (absolute + 15) & ~15
        blob.extend(bytes(aligned - absolute))
        absolute = aligned
        f = 0x180 + i * 0x50
        struct.pack_into("<IIQQQ", toc, f, 5, 9, len(data), absolute, len(data))
        toc[f + 0x20:f + 0x40] = hashlib.sha256(data).digest()
        blob.extend(data)
        absolute += len(data)
    toc[0x288:0x288 + len(names)] = names
    header = bytearray(0x80)
    header[:4] = b"NUP\x01"
    struct.pack_into("<HHQQ", header, 4, 0x80, 1, 0x80, len(toc))
    header[0x18:0x38] = hashlib.sha256(toc).digest()
    struct.pack_into("<QQII", header, 0x38, 0x320, absolute, len(packages), 0)
    header[0x50:0x60] = hashlib.sha256(signature).digest()[:16]
    return bytes(header + toc + blob)


def main() -> None:
    fixtures = payload_tools()
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        binary = base / "nup-vfs-host"
        command = [
            os.environ.get("CXX", "g++"), "-std=c++20", "-O1",
            "-Wall", "-Wextra", "-Werror", "-pedantic",
            "-I", str(ROOT / "headless"),
            str(ROOT / "headless/nup_v1_vfs.cpp"),
            str(ROOT / "tools/nup-v1-vfs-host.cpp"),
            "-lcrypto", "-lzstd", "-o", str(binary),
        ]
        subprocess.run(command, check=True)
        archive = base / "test.nup"
        valid = 0
        rejected = 0

        def execute(blob: bytes, member: str, data: bytes | None) -> None:
            nonlocal valid, rejected
            archive.write_bytes(blob)
            run = subprocess.run([str(binary), str(archive), member],
                                 capture_output=True, text=True, check=False)
            if data is None:
                assert run.returncode != 0, (
                    f"Invalid NUP accepted: stdout={run.stdout}, stderr={run.stderr}"
                )
                rejected += 1
            else:
                assert run.returncode == 0, run.stderr
                assert run.stdout.strip() == expected(data), run.stdout
                valid += 1

        raw = b"NUP-C++-reader-test-" * 100_000 + b"EOF"
        compressed = b"compressible-content-" * 210_000 + b"END"
        for codec, data in ((0, raw), (1, compressed)):
            good = fixtures.fixture(codec, data)
            execute(good, "proof.bin", data)
            execute(fixtures.fixture(codec, data, tamper_digest=True), "proof.bin", None)
            execute(good[:-1] + bytes([good[-1] ^ 0x10]), "proof.bin", None)
            execute(good, "../proof.bin", None)
        execute(fixtures.fixture(0, b""), "proof.bin", b"")
        execute(fixtures.dual_file_fixture(raw), "a.bin", raw)
        execute(fixtures.dual_file_fixture(raw), "b.bin", raw)
        execute(fixtures.dual_file_fixture(raw, overlap=True), "a.bin", None)
        execute(fixtures.fixture(1, compressed, extra=b"trailing"), "proof.bin", None)
        execute(fixtures.fixture(1, compressed,
                                 extra=fixtures.Zstd().compress_fixture(b"second")),
                "proof.bin", None)
        # Dedicated mutable source: random 1-byte reads must rehash only the
        # touched 256-KiB block, and an in-place mutation must be rejected.
        mutable_binary = base / "nup-mutable-block-host"
        mutable_command = [
            os.environ.get("CXX", "g++"), "-std=c++20", "-O2",
            "-Wall", "-Wextra", "-Werror", "-pedantic",
            "-I", str(ROOT / "headless"),
            str(ROOT / "headless/nup_v1_vfs.cpp"),
            str(ROOT / "tools/nup-v1-mutable-block-host.cpp"),
            "-lcrypto", "-lzstd", "-o", str(mutable_binary),
        ]
        subprocess.run(mutable_command, check=True)
        archive.write_bytes(fixtures.fixture(0, raw))
        subprocess.run([str(mutable_binary), str(archive)], check=True)
        layered = layered_fixture()
        execute(layered, "@base/romfs/state.bin", b"base-v1")
        execute(layered, "@update1/romfs/state.bin", b"latest-v3")
        execute(layered, "@update2/romfs/state.bin", b"older-v2")
        execute(layered, "@effective/romfs/state.bin", b"latest-v3")
        archive.write_bytes(layered)
        listed = subprocess.run([str(binary), str(archive), "@list-effective/romfs/"],
                                capture_output=True, text=True, check=True)
        assert listed.stdout == "state.bin:F:1\n", listed.stdout
        listed_absent = subprocess.run(
            [str(binary), str(archive), "@list-effective/romfs/not-present"],
            capture_output=True, text=True, check=False)
        assert listed_absent.returncode != 0
        execute(layered_fixture(duplicate_version=True),
                "@effective/romfs/state.bin", None)
        execute(layered_fixture(addon=True),
                "@addon/romfs/state.bin", b"addon-aoc")
        execute(layered_fixture(addon=True),
                "@effective/romfs/state.bin", b"latest-v3")
        execute(layered_fixture(standalone=True),
                "@effective/romfs/state.bin", b"latest-v3")
        execute(layered_fixture(standalone=True, broken_standalone=True),
                "@effective/romfs/state.bin", None)

        # Reject an empty nested name even though empty package roots are valid.
        malformed = bytearray(layered)
        struct.pack_into("<I", malformed, 0x80 + 0xF0 + 0x18 + 4, 0)
        malformed[0x18:0x38] = hashlib.sha256(malformed[0x80:0x320]).digest()
        execute(bytes(malformed), "@effective/romfs/state.bin", None)

        # Two directory records may not claim the same child-array slot.
        malformed = bytearray(layered)
        struct.pack_into("<I", malformed, 0x80 + 0xF0 + 2 * 0x18 + 8, 0)
        malformed[0x18:0x38] = hashlib.sha256(malformed[0x80:0x320]).digest()
        execute(bytes(malformed), "@effective/romfs/state.bin", None)
        print(f"NUP C++ read-only VFS: {valid} valid / {rejected} malformed cases passed")


if __name__ == "__main__":
    main()
