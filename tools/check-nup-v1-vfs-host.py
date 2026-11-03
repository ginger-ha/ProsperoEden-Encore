#!/usr/bin/env python3
"""Compile and exercise isolated C++ NUP VFS (never builds or registers PS5)."""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
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
        print(f"NUP C++ read-only VFS: {valid} valid / {rejected} malformed cases passed")


if __name__ == "__main__":
    main()
