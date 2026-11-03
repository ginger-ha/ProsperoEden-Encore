#!/usr/bin/env python3
"""NUP v1 *structural* preflight for unencrypted NS1/NS2 dump containers.

No game-specific exceptions, no extraction, no guest execution, no PS5 runtime hook.
Specification: https://github.com/a55uka/nup/blob/meow/SPEC.md
A successful check is NOT a substitute for full raw/zstd member SHA-256 verification.
"""
from __future__ import annotations

from collections import deque

import argparse
import hashlib
import os
import struct
import tempfile
from pathlib import Path

MAX_TOC = 64 * 1024 * 1024
MAX_NODES = 2_000_000
BAD = 0xFFFFFFFF


class InvalidNup(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidNup(message)


def record(data: bytes, offset: int, fmt: str) -> tuple:
    size = struct.calcsize(fmt)
    require(0 <= offset <= len(data) - size, "truncated TOC record")
    return struct.unpack_from(fmt, data, offset)


def check(path: Path) -> dict:
    total = path.stat().st_size
    require(total >= 0x80, "short superblock")
    with path.open("rb") as stream:
        header = stream.read(0x80)
        require(header[:4] == b"NUP\x01", "not NUP v1")
        header_size, version = struct.unpack_from("<HH", header, 4)
        toc_offset, toc_size = struct.unpack_from("<QQ", header, 8)
        blob_offset, announced_size = struct.unpack_from("<QQ", header, 0x38)
        package_count, flags = struct.unpack_from("<II", header, 0x48)
        require(header_size == 0x80 and version == 1, "unsupported header revision")
        require(toc_offset == header_size, "wrong TOC offset")
        require(0 < toc_size <= MAX_TOC and toc_size % 16 == 0, "invalid TOC size")
        require(blob_offset % 16 == 0 and blob_offset >= toc_offset + toc_size,
                "invalid blob offset")
        require(announced_size == total and blob_offset <= total, "invalid file size")
        require(0 < package_count <= 65536 and flags == 0, "invalid package count/flags")
        require(header[0x60:0x80] == bytes(0x20), "nonzero reserved superblock")
        stream.seek(toc_offset)
        toc = stream.read(toc_size)
    require(len(toc) == toc_size, "truncated TOC")
    require(hashlib.sha256(toc).digest() == header[0x18:0x38], "TOC SHA-256 mismatch")
    require(toc[:4] == b"TOC\x01", "invalid TOC magic")

    count, dirs_count, files_count, pool_offset, pool_size, reserved = record(
        toc, 4, "<IQQQQQ"
    )
    require(count == package_count and reserved == 0, "TOC header inconsistency")
    require(dirs_count <= MAX_NODES and files_count <= MAX_NODES, "excessive node count")
    packages_end = 0x30 + 0x40 * count
    dirs_start = packages_end
    files_start = dirs_start + 0x18 * dirs_count
    slots_start = files_start + 0x50 * files_count
    require(slots_start <= pool_offset <= len(toc), "overlapping TOC tables")
    require(pool_size <= len(toc) - pool_offset, "invalid string pool")
    pool = memoryview(toc)[pool_offset:pool_offset + pool_size]

    def name(off: int, size: int, *, root: bool = False) -> str:
        require(off <= len(pool) and size <= len(pool) - off, "bad name bounds")
        raw = bytes(pool[off:off + size])
        require(not (b"/" in raw or b"\\" in raw or b"\0" in raw), "unsafe path component")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise InvalidNup("invalid UTF-8 in file tree") from exc
        require(text not in (".", "..") and (bool(text) or root), "empty/unsafe name")
        return text

    dirs = []
    slot_count = 0
    for i in range(dirs_count):
        off, size, first, count_children, zero = record(toc, dirs_start + i * 0x18, "<IIIIQ")
        require(zero == 0, "nonzero directory reserved bytes")
        dirs.append((name(off, size, root=True), first, count_children))
        slot_count += count_children
    require(slot_count <= MAX_NODES * 2, "excessive child references")
    require(slots_start + 4 * slot_count <= pool_offset, "children overlap string pool")
    slots = record(toc, slots_start, f"<{slot_count}I") if slot_count else ()
    slot_owners = [0] * slot_count
    for directory_name, first, number in dirs:
        require(first <= slot_count and number <= slot_count - first, "bad child span")
        child_names = []
        for slot in range(first, first + number):
            require(slot_owners[slot] == 0, "child slot has multiple owners")
            slot_owners[slot] = 1
            node = slots[slot]
            require(node < dirs_count + files_count, "child node out of bounds")
            if node < dirs_count:
                child_names.append(dirs[node][0])
            else:
                index = node - dirs_count
                x, y = record(toc, files_start + index * 0x50, "<II")
                child_names.append(name(x, y))
        require(child_names == sorted(set(child_names), key=lambda s: s.encode("utf-8")),
                "unsorted or duplicate child names")

    require(all(owner == 1 for owner in slot_owners), "unowned directory child slot")
    # A cyclic directory graph would recurse forever in a mounted VFS.
    # Topological traversal handles very deep trees without Python recursion.
    incoming = [0] * dirs_count
    for _, first, number in dirs:
        for node in slots[first:first + number]:
            if node < dirs_count:
                incoming[node] += 1
    for i, count in enumerate(incoming):
        require(count <= 1, "directory has multiple parents")
        if count:
            require(bool(dirs[i][0]), "empty nested directory name")
    pending = deque(i for i, count in enumerate(incoming) if count == 0)
    visited = 0
    while pending:
        index = pending.popleft()
        visited += 1
        _, first, number = dirs[index]
        for node in slots[first:first + number]:
            if node < dirs_count:
                incoming[node] -= 1
                if incoming[node] == 0:
                    pending.append(node)
    require(visited == dirs_count, "cyclic directory tree")

    for i in range(files_count):
        off = files_start + i * 0x50
        name_off, name_size, size, extent, stored = record(toc, off, "<IIQQQ")
        name(name_off, name_size)
        codec, codec_flags, res = record(toc, off + 0x40, "<BBH")
        require(codec in (0, 1) and codec_flags == 0 and res == 0, "unsupported codec")
        require(toc[off + 0x44:off + 0x50] == bytes(12), "nonzero file reserved bytes")
        if size == 0:
            require(extent == 0 and stored == 0 and codec == 0, "bad empty extent")
        else:
            require(stored > 0 and extent >= blob_offset and extent % 16 == 0,
                    "misaligned/empty extent")
            require(extent <= total and stored <= total - extent, "extent outside file")
            require(codec != 0 or stored == size, "raw extent size mismatch")

    packages = []
    signature = bytearray()
    base_packages = 0
    for i in range(package_count):
        off = 0x30 + i * 0x40
        title_id, root_dir, exefs, romfs, version_num = record(toc, off, "<QIIII")
        kind, pkg_flags, zero, zero2 = record(toc, off + 0x18, "<BBHI")
        meta_offset, meta_size = record(toc, off + 0x20, "<QI")
        require(kind <= 2 and (pkg_flags & ~1) == 0 and zero == zero2 == 0,
                "invalid package kind/flags/reserved")
        require(toc[off + 0x2C:off + 0x40] == bytes(20),
                "nonzero package reserved bytes")
        require(root_dir < dirs_count, "missing package root")
        require(all(x == BAD or x < dirs_count for x in (exefs, romfs)), "bad content root")
        require(kind == 1 or pkg_flags == 0, "standalone flag on non-update")
        if kind == 0:
            base_packages += 1
        if meta_size:
            require(meta_offset >= blob_offset and meta_offset <= total and
                    meta_size <= total - meta_offset, "metadata outside container")
        else:
            require(meta_offset == 0, "empty metadata with nonzero offset")
        signature.extend(struct.pack("<QIB", title_id, version_num, kind))
        packages.append({"title_id": f"{title_id:016X}", "version": version_num,
                         "kind": ("base", "update", "addon")[kind],
                         "standalone_update": bool(pkg_flags)})
    require(base_packages <= 1, "multiple base packages")
    # Base-less update-only packages require explicit standalone markers;
    # a normal base+update must not incorrectly claim to be standalone.
    for package in packages:
        if package["kind"] == "update":
            require(package["standalone_update"] == (base_packages == 0),
                    "inconsistent standalone-update flag")
    require(hashlib.sha256(signature).digest()[:16] == header[0x50:0x60],
            "content UUID mismatch")
    return {"packages": packages, "directories": dirs_count, "files": files_count,
            "toc_sha256_verified": True, "member_hashes_verified": False}


def self_test() -> None:
    package = bytearray(0x40)
    struct.pack_into("<QIIII", package, 0, 0x1000000000000000, 0, BAD, BAD, 1)
    directory = bytes(0x18)
    toc = bytearray(0x90)
    struct.pack_into("<4sIQQQQQ", toc, 0, b"TOC\x01", 1, 1, 0, 0x88, 0, 0)
    toc[0x30:0x70] = package
    toc[0x70:0x88] = directory
    head = bytearray(0x80)
    head[:4] = b"NUP\x01"
    struct.pack_into("<HHQQ", head, 4, 0x80, 1, 0x80, len(toc))
    head[0x18:0x38] = hashlib.sha256(toc).digest()
    struct.pack_into("<QQII", head, 0x38, 0x110, 0x110, 1, 0)
    head[0x50:0x60] = hashlib.sha256(struct.pack("<QIB", 0x1000000000000000, 1, 0)).digest()[:16]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixture.nup"
        valid = bytes(head + toc)
        path.write_bytes(valid)
        assert check(path)["toc_sha256_verified"]
        for offset in (0, 0x80, 0x18, 0x48, 0x50):
            damaged = bytearray(valid)
            damaged[offset] ^= 0x01
            path.write_bytes(damaged)
            try:
                check(path)
            except InvalidNup:
                pass
            else:
                raise AssertionError(f"damaged fixture accepted at {offset}")
        # Self-referencing root with a consistent TOC hash: only graph validation
        # should reject it (rather than magic, offsets or header validation).
        cyclic_toc = bytearray(valid[0x80:])
        struct.pack_into("<Q", cyclic_toc, 0x18, 0x8C)  # string pool starts after 1 slot
        struct.pack_into("<I", cyclic_toc, 0x7C, 1)  # root child_count
        struct.pack_into("<I", cyclic_toc, 0x88, 0)  # root -> root
        cyclic_header = bytearray(valid[:0x80])
        cyclic_header[0x18:0x38] = hashlib.sha256(cyclic_toc).digest()
        path.write_bytes(cyclic_header + cyclic_toc)
        try:
            check(path)
        except InvalidNup:
            pass
        else:
            raise AssertionError("cyclic directory tree accepted")
        update_toc = bytearray(valid[0x80:])
        update_toc[0x48] = 1  # package kind: update
        update_toc[0x49] = 1  # standalone update, no base
        update_header = bytearray(valid[:0x80])
        update_header[0x18:0x38] = hashlib.sha256(update_toc).digest()
        update_header[0x50:0x60] = hashlib.sha256(
            struct.pack("<QIB", 0x1000000000000000, 1, 1)).digest()[:16]
        path.write_bytes(update_header + update_toc)
        assert check(path)["packages"][0]["standalone_update"]
        update_toc[0x49] = 0  # same valid TOC, but forbidden base-less marker
        update_header[0x18:0x38] = hashlib.sha256(update_toc).digest()
        path.write_bytes(update_header + update_toc)
        try:
            check(path)
        except InvalidNup:
            pass
        else:
            raise AssertionError("base-less update without standalone marker accepted")
    print("NUP v1 host preflight: valid base/update fixtures + 7 corruption/cycle cases passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.path is None:
        parser.error("supply a NUP filename or --self-test")
    try:
        import json
        print(json.dumps(check(args.path), indent=2))
        return 0
    except (OSError, InvalidNup) as exc:
        print(f"NUP validation failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
