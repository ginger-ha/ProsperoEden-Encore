#!/usr/bin/env python3
"""Small deterministic NUP v1 fixture builder for inactive native content tests.

The payload bytes are synthetic; no console keys, proprietary game data or
unlicensed titles are needed. Layout follows NUP v1's verified parser.
"""
from __future__ import annotations
from hashlib import sha256
from pathlib import Path
import struct

NO_DIRECTORY = 0xFFFFFFFF


def build(packages: list[dict]) -> bytes:
    directories: list[tuple[str, dict]] = []
    roots = []

    def add_dir(name: str, node: dict) -> int:
        index = len(directories)
        directories.append((name, node))
        for sub_name, sub_node in sorted(node["dirs"].items()):
            add_dir(sub_name, sub_node)
        return index

    def tree(files: dict[str, bytes]) -> dict:
        root = {"dirs": {}, "files": {}}
        for path, data in files.items():
            names = path.split("/")
            assert all(n and n not in (".", "..") for n in names)
            current = root
            for name in names[:-1]:
                current = current["dirs"].setdefault(name, {"dirs": {}, "files": {}})
            assert names[-1] not in current["dirs"]
            current["files"][names[-1]] = data
        return root

    for package in packages:
        node = tree(package["files"])
        roots.append(add_dir("", node))

    directory_indices = {id(node): i for i, (_, node) in enumerate(directories)}
    files: list[tuple[str, bytes]] = []
    file_indices: dict[tuple[int, str], int] = {}
    for directory_id, (_, node) in enumerate(directories):
        for name, data in sorted(node["files"].items()):
            file_indices[(directory_id, name)] = len(files)
            files.append((name, data))
    nd, nf = len(directories), len(files)
    children = []
    dir_records = []
    for directory_id, (name, node) in enumerate(directories):
        entries = [(n, directory_indices[id(sub)]) for n, sub in node["dirs"].items()]
        entries += [(n, nd + file_indices[(directory_id, n)])
                    for n in node["files"]]
        entries.sort(key=lambda e: e[0].encode("utf-8"))
        first = len(children)
        children.extend(index for _, index in entries)
        dir_records.append((name, first, len(entries)))

    strings = bytearray()

    def name_bytes(name: str) -> tuple[int, int]:
        data = name.encode("utf-8")
        offset = len(strings)
        strings.extend(data)
        return offset, len(data)

    dir_names = [name_bytes(record[0]) for record in dir_records]
    file_names = [name_bytes(name) for name, _ in files]
    count = len(packages)
    dirs_at = 0x30 + count * 0x40
    files_at = dirs_at + nd * 0x18
    children_at = files_at + nf * 0x50
    strings_at = children_at + len(children) * 4
    toc_size = (strings_at + len(strings) + 15) & ~15
    blob_at = 0x80 + toc_size

    toc = bytearray(toc_size)
    struct.pack_into("<4sIQQQQQ", toc, 0, b"TOC\x01",
                     count, nd, nf, strings_at, len(strings), 0)
    uuid_input = bytearray()
    for i, package in enumerate(packages):
        p = 0x30 + i * 0x40
        node = directories[roots[i]][1]
        exefs = node["dirs"].get("exefs")
        romfs = node["dirs"].get("romfs")
        exefs_dir = directory_indices[id(exefs)] if exefs else NO_DIRECTORY
        romfs_dir = directory_indices[id(romfs)] if romfs else NO_DIRECTORY
        title_id, version, kind = (package[k] for k in ("title_id", "version", "kind"))
        struct.pack_into("<QIIII", toc, p, title_id, roots[i],
                         exefs_dir, romfs_dir, version)
        toc[p + 0x18] = kind
        toc[p + 0x19] = 1 if (kind == 1 and not any(
            pkg["kind"] == 0 for pkg in packages)) else 0
        uuid_input += struct.pack("<QIB", title_id, version, kind)

    for i, (name, first, count_children) in enumerate(dir_records):
        off, size = dir_names[i]
        struct.pack_into("<IIIIQ", toc, dirs_at + i * 0x18,
                         off, size, first, count_children, 0)
    for i, index in enumerate(children):
        struct.pack_into("<I", toc, children_at + i * 4, index)
    toc[strings_at:strings_at + len(strings)] = strings

    blobs = bytearray()
    for i, (_, data) in enumerate(files):
        file_at = files_at + i * 0x50
        offset, n = file_names[i]
        aligned = (blob_at + len(blobs) + 15) & ~15
        blobs.extend(bytes(aligned - (blob_at + len(blobs))))
        absolute = blob_at + len(blobs)
        struct.pack_into("<IIQQQ", toc, file_at, offset, n,
                         len(data), absolute if data else 0, len(data))
        toc[file_at + 0x20:file_at + 0x40] = sha256(data).digest()
        blobs.extend(data)

    # Optional raw NUP per-package TLVs are placed after the file payloads
    # (never overlapping a member extent); every record is size-delimited.
    for i, package in enumerate(packages):
        values = package.get("metadata", {})
        if not values:
            continue
        meta = bytearray()
        for kind, payload in sorted(values.items()):
            assert isinstance(kind, int) and isinstance(payload, bytes)
            meta += struct.pack("<HHI", kind, 0, len(payload)) + payload
        aligned = (blob_at + len(blobs) + 15) & ~15
        blobs.extend(bytes(aligned - (blob_at + len(blobs))))
        struct.pack_into("<QI", toc, 0x30 + i * 0x40 + 0x20,
                         blob_at + len(blobs), len(meta))
        blobs.extend(meta)

    header = bytearray(0x80)
    header[:4] = b"NUP\x01"
    struct.pack_into("<HHQQ", header, 4, 0x80, 1, 0x80, toc_size)
    header[0x18:0x38] = sha256(toc).digest()
    struct.pack_into("<QQII", header, 0x38, blob_at,
                     blob_at + len(blobs), len(packages), 0)
    header[0x50:0x60] = sha256(uuid_input).digest()[:16]
    return bytes(header + toc + blobs)


def localized(records: list[tuple[str, bytes]]) -> bytes:
    out = bytearray()
    for language, data in records:
        encoded = language.encode("ascii")
        assert 0 < len(encoded) <= 35
        out += bytes([len(encoded)]) + encoded + struct.pack("<I", len(data)) + data
    return bytes(out)


def executable_fixture() -> bytes:
    title = 0x0100123400000000
    return build([
        {"title_id": title, "version": 1, "kind": 0,
         "metadata": {
             0x0003: b"\xff\xd8\xff" + b"synthetic-jpeg",
             0x0004: b"3.0.0",
             0x0005: b"Demo / Game",
             0x0006: b"Example Publisher",
             0x0009: localized([
                 ("en-us", b"Demo Game (US)"),
                 ("fr", "Démo / Jeu".encode("utf-8")),
             ]),
             0x000A: localized([
                 ("fr", bytes.fromhex("89504e470d0a1a0a") + b"synthetic-png"),
             ]),
             0x8000: b"unknown-type-is-ignored",
         },
         "files": {
            "exefs/main": b"base-main",
            "exefs/main.npdm": b"base-npdm",
            "romfs/state.bin": b"base-v1",
            "romfs/sub/base.dat": b"base-only",
        }},
        {"title_id": title + 0x800, "version": 3, "kind": 1,
         "metadata": {0x0005: b"Wrong update title"},
         "files": {
            "exefs/main": b"latest-main",
            "exefs/main.npdm": b"latest-npdm",
            "romfs/state.bin": b"latest-v3",
            "romfs/sub/update.dat": b"update-only",
        }},
        {"title_id": title + 0x800, "version": 2, "kind": 1, "files": {
            "exefs/main": b"older-main",
            "romfs/state.bin": b"older-v2",
        }},
        {"title_id": title + 0x1000, "version": 0, "kind": 2, "files": {
            "romfs/addon.dat": b"addon-one",
        }},
        {"title_id": title + 0x1001, "version": 0, "kind": 2, "files": {
            "romfs/addon.dat": b"addon-two",
        }},
        # Highest revision of the first DLC replaces its older package.
        {"title_id": title + 0x1000, "version": 2, "kind": 2, "files": {
            "romfs/addon.dat": b"addon-one-v2",
        }},
        # A foreign title must not appear in this base game's AoC list.
        {"title_id": title + 0x2000, "version": 0, "kind": 2, "files": {
            "romfs/addon.dat": b"foreign-dlc",
        }},
    ])


def foreign_update_fixture() -> bytes:
    """Structurally valid, but an unrelated title attempts to shadow the base."""
    title = 0x0100123400000000
    return build([
        {"title_id": title, "version": 1, "kind": 0, "files": {
            "romfs/state.bin": b"base-v1",
        }},
        {"title_id": title + 0x2000, "version": 99, "kind": 1, "files": {
            "romfs/state.bin": b"foreign-hijack",
        }},
    ])


def mismatched_npdm_fixture() -> bytes:
    """Valid NUP package record and hashes with a foreign NPDM identity."""
    title = 0x0100123400000000
    return build([
        {"title_id": title, "version": 1, "kind": 0, "files": {
            "exefs/main": b"synthetic-main",
            "exefs/main.npdm": b"foreign-npdm",
            "romfs/state.bin": b"data",
        }},
    ])


def sibling_npdm_fixture() -> bytes:
    """NPDM program index differs although the family/base ID is identical."""
    title = 0x0100123400000000
    return build([
        {"title_id": title, "version": 1, "kind": 0, "files": {
            "exefs/main": b"synthetic-main",
            "exefs/main.npdm": b"sibling-npdm",
            "romfs/state.bin": b"data",
        }},
    ])


def bad_metadata_fixture() -> bytes:
    """A well-formed TLV length carrying forbidden, overlong UTF-8."""
    title = 0x0100123400000000
    return build([
        {"title_id": title, "version": 1, "kind": 0,
         "metadata": {0x0005: b"\xC0\xAF"},
         "files": {"romfs/state.bin": b"metadata-error"}},
    ])


def duplicate_locale_fixture() -> bytes:
    """Case-insensitive duplicate BCP-47 tags must not be silently merged."""
    title = 0x0100123400000000
    return build([
        {"title_id": title, "version": 1, "kind": 0,
         "metadata": {0x0009: localized([
             ("fr", b"First"),
             ("FR", b"Duplicate"),
         ])},
         "files": {"romfs/state.bin": b"duplicate-locale"}},
    ])


def add_on_only_fixture() -> bytes:
    """Two unrelated DLC families, neither implicitly owned by a program."""
    title = 0x0100123400000000
    return build([
        {"title_id": title + 0x1000, "version": 1, "kind": 2,
         "files": {"romfs/addon.dat": b"family-one"}},
        {"title_id": title + 0x3001, "version": 2, "kind": 2,
         "files": {"romfs/addon.dat": b"family-two"}},
    ])


def oversized_npdm_fixture() -> bytes:
    """A structurally valid but oversized NPDM must never reach the vendor parser."""
    title = 0x0100123400000000
    return build([
        {"title_id": title, "version": 1, "kind": 0,
         "files": {
             "exefs/main": b"synthetic-main",
             "exefs/main.npdm": b"P" * (4 * 1024 * 1024 + 1),
         }},
    ])


def nacp_aoc_fixture(*, extracted: bool = False) -> bytes:
    """Declared AoC base in NACP TLV or the extracted ExeFS control.nacp."""
    title = 0x0100123400000000
    nacp = bytearray(0x4000)
    # ABI offset from the pinned vendor's FileSys::RawNACP.
    struct.pack_into("<Q", nacp, 0x3070, title + 0x3000)
    files = {
        "exefs/main": b"synthetic-main",
        "exefs/main.npdm": b"latest-npdm",
        "romfs/state.bin": b"base",
    }
    if extracted:
        files["exefs/control.nacp"] = bytes(nacp)
    return build([
        {"title_id": title, "version": 1, "kind": 0,
         "metadata": {0x0005: b"NACP-AoC"} if extracted else
                     {0x0002: bytes(nacp), 0x0005: b"NACP-AoC"},
         "files": files},
        {"title_id": title + 0x3001, "version": 2, "kind": 2,
         "files": {"romfs/addon.dat": b"nacp-declared"}},
        {"title_id": title + 0x1000, "version": 3, "kind": 2,
         "files": {"romfs/addon.dat": b"default-family-not-selected"}},
    ])


def corrupt_extracted_nacp_fixture() -> bytes:
    """Correct TOC/UUID, but the SHA-256 of extracted control.nacp fails."""
    blob = bytearray(nacp_aoc_fixture(extracted=True))
    signature = struct.pack("<Q", 0x0100123400003000)
    where = blob.find(signature, 0x80)
    assert where != -1
    blob[where] ^= 1
    return bytes(blob)


def short_extracted_nacp_fixture() -> bytes:
    """An advertised, hashed control.nacp must have the real NACP length."""
    title = 0x0100123400000000
    return build([
        {"title_id": title, "version": 1, "kind": 0,
         "files": {
             "exefs/main": b"synthetic-main",
             "exefs/main.npdm": b"latest-npdm",
             "exefs/control.nacp": bytes(0x3FFF),
         }},
    ])
