#!/usr/bin/env python3
"""Bounded NUP v1 payload integrity verification, independent of game or emulator.

Run the existing structural checker first; then stream every raw/zstd member through
SHA-256. Requires system libzstd for codec 1 (no Python packages required).
No extraction, execution, runtime registration, or format enablement is performed.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import hashlib
import importlib.util
import json
import struct
import sys
import tempfile
from pathlib import Path

BLOCK = 1 << 20
BAD = 0xFFFFFFFF


class InvalidPayload(ValueError):
    pass


def require(ok: bool, why: str) -> None:
    if not ok:
        raise InvalidPayload(why)


def structural_checker():
    path = Path(__file__).with_name("check-nup-v1-host.py")
    spec = importlib.util.spec_from_file_location("nup_structure", path)
    require(spec is not None and spec.loader is not None, "missing structural checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Zstd:
    class Input(ctypes.Structure):
        _fields_ = [("src", ctypes.c_void_p), ("size", ctypes.c_size_t),
                    ("pos", ctypes.c_size_t)]

    class Output(ctypes.Structure):
        _fields_ = [("dst", ctypes.c_void_p), ("size", ctypes.c_size_t),
                    ("pos", ctypes.c_size_t)]

    def __init__(self):
        library = ctypes.util.find_library("zstd")
        require(library is not None, "system libzstd required for zstd payloads")
        self.lib = ctypes.CDLL(library)
        l = self.lib
        l.ZSTD_getFrameContentSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        l.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
        l.ZSTD_createDStream.restype = ctypes.c_void_p
        l.ZSTD_initDStream.argtypes = [ctypes.c_void_p]
        l.ZSTD_initDStream.restype = ctypes.c_size_t
        l.ZSTD_DCtx_setParameter.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        l.ZSTD_DCtx_setParameter.restype = ctypes.c_size_t
        l.ZSTD_freeDStream.argtypes = [ctypes.c_void_p]
        l.ZSTD_freeDStream.restype = ctypes.c_size_t
        l.ZSTD_decompressStream.argtypes = [ctypes.c_void_p, ctypes.POINTER(self.Output),
                                           ctypes.POINTER(self.Input)]
        l.ZSTD_decompressStream.restype = ctypes.c_size_t
        l.ZSTD_isError.argtypes = [ctypes.c_size_t]
        l.ZSTD_isError.restype = ctypes.c_uint
        l.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
        l.ZSTD_compressBound.restype = ctypes.c_size_t
        l.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                    ctypes.c_size_t, ctypes.c_int]
        l.ZSTD_compress.restype = ctypes.c_size_t

    def ensure(self, result: int) -> None:
        require(not self.lib.ZSTD_isError(result), "invalid zstd frame")

    def compress_fixture(self, data: bytes) -> bytes:
        source = ctypes.create_string_buffer(data)
        bound = self.lib.ZSTD_compressBound(len(data))
        target = ctypes.create_string_buffer(bound)
        count = self.lib.ZSTD_compress(target, bound, source, len(data), 1)
        self.ensure(count)
        return target.raw[:count]

    def hash_extent(self, stream, offset: int, stored: int, expected: int) -> bytes:
        stream.seek(offset)
        head = stream.read(min(18, stored))
        hdr = ctypes.create_string_buffer(head)
        frame_size = self.lib.ZSTD_getFrameContentSize(hdr, len(head))
        require(frame_size == expected, "missing/wrong zstd frame content size")
        stream.seek(offset)
        decoder = self.lib.ZSTD_createDStream()
        require(bool(decoder), "cannot allocate zstd decoder")
        digest = hashlib.sha256()
        produced = 0
        remaining = stored
        try:
            self.ensure(self.lib.ZSTD_initDStream(decoder))
            self.ensure(self.lib.ZSTD_DCtx_setParameter(decoder, 100, 26))  # 64 MiB max window
            input_bytes = None
            src = self.Input(None, 0, 0)
            while True:
                if src.pos == src.size:
                    require(remaining > 0, "truncated zstd stream")
                    data = stream.read(min(BLOCK, remaining))
                    require(bool(data), "truncated zstd extent")
                    remaining -= len(data)
                    input_bytes = ctypes.create_string_buffer(data)
                    src = self.Input(ctypes.addressof(input_bytes), len(data), 0)
                output_bytes = ctypes.create_string_buffer(BLOCK)
                dst = self.Output(ctypes.addressof(output_bytes), BLOCK, 0)
                before = src.pos
                result = self.lib.ZSTD_decompressStream(decoder, ctypes.byref(dst),
                                                        ctypes.byref(src))
                self.ensure(result)
                produced += dst.pos
                require(produced <= expected, "zstd expansion exceeds declared size")
                digest.update(output_bytes.raw[:dst.pos])
                if result == 0:
                    require(remaining == 0 and src.pos == src.size,
                            "trailing bytes / multiple zstd frames")
                    break
                require(src.pos > before or dst.pos > 0, "stalled zstd decompressor")
            require(produced == expected, "zstd decompressed size mismatch")
            return digest.digest()
        finally:
            self.lib.ZSTD_freeDStream(decoder)


def verify(path: Path) -> dict:
    info = structural_checker().check(path)
    with path.open("rb") as stream:
        header = stream.read(0x80)
        toc_off, toc_size = struct.unpack_from("<QQ", header, 8)
        blob_start = struct.unpack_from("<Q", header, 0x38)[0]
        stream.seek(toc_off)
        toc = stream.read(toc_size)
        _, dirs_count, files_count, _pool_start = struct.unpack_from("<IQQQ", toc, 4)
        files_start = 0x30 + 0x40 * len(info["packages"]) + 0x18 * dirs_count
        extents = {}
        verified_extents = {}
        ranges = []
        zstd = None
        for i in range(files_count):
            off = files_start + 0x50 * i
            size, extent, stored = struct.unpack_from("<QQQ", toc, off + 8)
            expected = toc[off + 0x20:off + 0x40]
            codec = toc[off + 0x40]
            if size == 0:
                digest = hashlib.sha256(b"").digest()
            else:
                require(extent >= blob_start, "file extent before blob region")
                identity = (size, stored, codec, expected)
                key = (extent, stored)
                require(key not in extents or extents[key] == identity,
                        "shared extent has incompatible digest/shape")
                extents[key] = identity
                if key in verified_extents:
                    digest = verified_extents[key]
                elif codec == 0:
                    stream.seek(extent)
                    digestor = hashlib.sha256()
                    remaining = stored
                    while remaining:
                        chunk = stream.read(min(remaining, BLOCK))
                        require(bool(chunk), "truncated raw extent")
                        digestor.update(chunk)
                        remaining -= len(chunk)
                    digest = digestor.digest()
                else:
                    if zstd is None:
                        zstd = Zstd()
                    digest = zstd.hash_extent(stream, extent, stored, size)
                verified_extents[key] = digest
                ranges.append((extent, extent + stored))
            require(digest == expected, f"member {i}: SHA-256 mismatch")
        unique_ranges = sorted(set(ranges))
        for (left, right), (next_left, next_right) in zip(unique_ranges, unique_ranges[1:]):
            require(right <= next_left, "overlapping non-identical extents")
        # Metadata may not alias payload extents or the TOC.
        for i in range(len(info["packages"])):
            meta_off, meta_len = struct.unpack_from("<QI", toc, 0x30 + 0x40 * i + 0x20)
            if meta_len:
                require(meta_off >= blob_start, "metadata outside blob region")
                for start, end in ranges:
                    require(meta_off + meta_len <= start or meta_off >= end,
                            "metadata overlaps payload extent")
                stream.seek(meta_off)
                meta = stream.read(meta_len)
                require(len(meta) == meta_len, "truncated metadata")
                pos = 0
                while pos < meta_len:
                    require(meta_len - pos >= 8, "truncated metadata TLV")
                    _, reserved, payload_len = struct.unpack_from("<HHI", meta, pos)
                    require(reserved == 0 and payload_len <= meta_len - pos - 8,
                            "invalid metadata TLV bounds")
                    pos += 8 + payload_len
    info["member_hashes_verified"] = True
    info["raw_zstd_integrity"] = "verified"
    return info


def fixture(codec: int, contents: bytes, *, tamper_digest=False, extra=b"") -> bytes:
    packed = contents if codec == 0 else Zstd().compress_fixture(contents)
    stored = packed + extra
    name = b"proof.bin"
    toc_size = 0xF0
    toc = bytearray(toc_size)
    struct.pack_into("<4sIQQQQQ", toc, 0, b"TOC\x01", 1, 1, 1, 0xDC, len(name), 0)
    struct.pack_into("<QIIII", toc, 0x30, 0x1234000000000000, 0, BAD, 0, 1)
    struct.pack_into("<IIIIQ", toc, 0x70, 0, 0, 0, 1, 0)
    struct.pack_into("<IIQQQ", toc, 0x88, 0, len(name), len(contents),
                     0x170 if contents else 0, len(stored))
    digest = bytearray(hashlib.sha256(contents).digest())
    if tamper_digest:
        digest[0] ^= 1
    toc[0xA8:0xC8] = digest
    toc[0xC8] = codec
    struct.pack_into("<I", toc, 0xD8, 1)
    toc[0xDC:0xDC + len(name)] = name
    header = bytearray(0x80)
    header[:4] = b"NUP\x01"
    struct.pack_into("<HHQQ", header, 4, 0x80, 1, 0x80, toc_size)
    header[0x18:0x38] = hashlib.sha256(toc).digest()
    struct.pack_into("<QQII", header, 0x38, 0x170, 0x170 + len(stored), 1, 0)
    header[0x50:0x60] = hashlib.sha256(
        struct.pack("<QIB", 0x1234000000000000, 1, 0)).digest()[:16]
    return bytes(header + toc + stored)


def dual_file_fixture(contents: bytes, *, overlap: bool = False) -> bytes:
    """Two sorted files, either sharing exactly one extent or partially overlapping."""
    require(len(contents) > 16, "fixture too small")
    toc = bytearray(0x140)
    names = b"a.binb.bin"
    struct.pack_into("<4sIQQQQQ", toc, 0, b"TOC\x01", 1, 1, 2, 0x130, len(names), 0)
    struct.pack_into("<QIIII", toc, 0x30, 0x1234000000000000, 0, BAD, 0, 1)
    struct.pack_into("<IIIIQ", toc, 0x70, 0, 0, 0, 2, 0)
    for index in (0, 1):
        sub = contents[16:] if overlap and index == 1 else contents
        off = 0x88 + 0x50 * index
        extent = 0x1C0 + (16 if overlap and index == 1 else 0)
        struct.pack_into("<IIQQQ", toc, off, index * 5, 5, len(sub), extent, len(sub))
        toc[off + 0x20:off + 0x40] = hashlib.sha256(sub).digest()
    struct.pack_into("<II", toc, 0x128, 1, 2)
    toc[0x130:0x13A] = names
    header = bytearray(0x80)
    header[:4] = b"NUP\x01"
    struct.pack_into("<HHQQ", header, 4, 0x80, 1, 0x80, len(toc))
    header[0x18:0x38] = hashlib.sha256(toc).digest()
    struct.pack_into("<QQII", header, 0x38, 0x1C0, 0x1C0 + len(contents), 1, 0)
    header[0x50:0x60] = hashlib.sha256(
        struct.pack("<QIB", 0x1234000000000000, 1, 0)).digest()[:16]
    return bytes(header + toc + contents)


def self_test() -> None:
    data = (b"NUP integrity streamed!" * 200_000) + b"end"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.nup"
        for codec in (0, 1):
            good = fixture(codec, data)
            path.write_bytes(good)
            require(verify(path)["member_hashes_verified"], "valid member not verified")
            for invalid in (fixture(codec, data, tamper_digest=True),
                            good[:-1] + bytes([good[-1] ^ 1])):
                path.write_bytes(invalid)
                try:
                    verify(path)
                except InvalidPayload:
                    pass
                else:
                    raise AssertionError(f"accepted corrupted payload (codec={codec})")
        for invalid in (fixture(1, data, extra=b"x"),
                        fixture(1, data, extra=Zstd().compress_fixture(b"second"))):
            path.write_bytes(invalid)
            try:
                verify(path)
            except InvalidPayload:
                pass
            else:
                raise AssertionError("accepted trailing zstd data/second frame")
        path.write_bytes(fixture(0, b""))
        require(verify(path)["member_hashes_verified"], "empty file rejected")
        path.write_bytes(dual_file_fixture(data))
        require(verify(path)["files"] == 2, "shared extent rejected")
        path.write_bytes(dual_file_fixture(data, overlap=True))
        try:
            verify(path)
        except InvalidPayload:
            pass
        else:
            raise AssertionError("accepted partially overlapping extents")
    print("NUP v1 payload host: raw/zstd/empty/dedup valid + 7 corruptions rejected")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        else:
            if args.path is None:
                parser.error("supply a NUP path or --self-test")
            print(json.dumps(verify(args.path), indent=2))
    except (InvalidPayload, ValueError, OSError) as exc:
        print(f"NUP payload verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
