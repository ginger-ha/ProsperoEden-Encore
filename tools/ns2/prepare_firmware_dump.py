#!/usr/bin/env python3
"""Validate/optionally unpack a user's own NS2JB system-code dump.

This is NOT an NCA firmware installer and does not enable NS2 system services.
It never alters the working NS1 firmware, keys, ROMs or original input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import zipfile

TITLE_ID = re.compile(r"040[0-9a-fA-F]{13}\Z")
MAX_BYTES = 1024 * 1024 * 1024


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def inspect(archive: Path, output: Path | None = None) -> None:
    with zipfile.ZipFile(archive) as z:
        files: dict[str, zipfile.ZipInfo] = {}
        size = 0
        for member in z.infolist():
            name = member.filename
            if member.is_dir() or name.startswith("__MACOSX/") or name.endswith("/.DS_Store"):
                continue
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or not name.startswith("firmware/") or name in files:
                raise ValueError("Unsafe or duplicate archive member: " + name)
            if ((member.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("Symlinked archive member: " + name)
            if member.file_size > MAX_BYTES or size + member.file_size > MAX_BYTES:
                raise ValueError("Archive exceeds bounded decompression budget")
            size += member.file_size
            files[name] = member

        def read(name: str) -> bytes:
            if name not in files:
                raise ValueError("Missing archive member: " + name)
            return z.read(files[name])

        header = json.loads(read("firmware/.ns2jb-firmware-dump.json"))
        if header.get("kind") != "ns2jb-system-code-dump":
            raise ValueError("Not an NS2JB system-code dump")
        manifest = json.loads(read("firmware/firmware-dump-named.json"))
        entries = manifest.get("entries", [])
        if not isinstance(entries, list) or not 1 <= len(entries) <= 256:
            raise ValueError("Invalid system-program inventory length")
        if manifest.get("complete") is not True or manifest.get("counts", {}).get("captured") != len(entries):
            raise ValueError("Manifest capture is incomplete")
        inventory = manifest.get("inventory", {})
        if inventory.get("rawFile") != "ncm-system-programs.bin":
            raise ValueError("Unknown system-program inventory file")
        if digest(read("firmware/ncm-system-programs.bin")) != inventory.get("sha256"):
            raise ValueError("System-program inventory checksum mismatch")
        # NCM's `keys` are composite content-index records (ID/version/type/
        # installType), NOT AES, NCA, title decryption or prod.keys material.
        # Verify these records against the system-program list, do not export
        # or pass them to the emulator's cryptographic KeyManager.
        ncm_records = inventory.get("keys")
        if not isinstance(ncm_records, list) or len(ncm_records) != len(entries) or \
                inventory.get("total") != len(entries):
            raise ValueError("NCM inventory count/keys disagree with program entries")
        expected_index = set()
        for entry in entries:
            title = entry.get("title")
            version = entry.get("version")
            if not isinstance(title, str) or not TITLE_ID.fullmatch(title.removeprefix("0x")) or \
                    not isinstance(version, int) or isinstance(version, bool):
                raise ValueError("Invalid title/version in system-program records")
            if (title.lower(), version) in expected_index:
                raise ValueError("Duplicate title/version in system-program records")
            expected_index.add((title.lower(), version))
        actual_index = set()
        for record in ncm_records:
            if not isinstance(record, dict) or set(record) != {"id", "version", "type", "installType"}:
                raise ValueError("Expected NCM index record, not cryptographic key material")
            if not isinstance(record["id"], str) or not TITLE_ID.fullmatch(
                    record["id"].removeprefix("0x")):
                raise ValueError("Invalid NCM content identifier")
            if any(not isinstance(record[field], int) or isinstance(record[field], bool)
                   for field in ("version", "type", "installType")):
                raise ValueError("Invalid NCM content record attributes")
            key = (record["id"].lower(), record["version"])
            if key in actual_index:
                raise ValueError("Duplicate NCM content-index key")
            actual_index.add(key)
        if expected_index != actual_index:
            raise ValueError("NCM inventory keys do not match system-program title/version records")
        verified = {
            name: read(name) for name in (
                "firmware/.ns2jb-firmware-dump.json",
                "firmware/firmware-dump-named.json",
                "firmware/ncm-system-programs.bin",
            )
        }
        seen: set[str] = set()
        missing_main: list[str] = []
        for entry in entries:
            title = entry.get("title")
            if not isinstance(title, str) or not title.startswith("0x") or not TITLE_ID.fullmatch(title[2:]):
                raise ValueError("Unrecognized system-program title ID")
            folder = title[2:].lower()
            if folder in seen or entry.get("status") != "captured":
                raise ValueError("Duplicate or incomplete system-program record")
            seen.add(folder)
            for part in entry.get("files", []):
                relative = part.get("file", "").replace("\\", "/")
                if relative not in (folder + "/main", folder + "/main.npdm"):
                    raise ValueError("Unexpected program path: " + relative)
                name = "firmware/" + relative
                data = read(name)
                if len(data) != part.get("size") or digest(data) != part.get("sha256"):
                    raise ValueError("System-program checksum mismatch: " + folder)
                magic = b"NSO0" if relative.endswith("/main") else b"META"
                if not data.startswith(magic):
                    raise ValueError("Bad system-program signature: " + folder)
                verified[name] = data
            if "firmware/" + folder + "/main.npdm" not in verified:
                raise ValueError("Missing NPDM in dump: " + folder)
            if "firmware/" + folder + "/main" not in verified:
                if not any(x.get("name") == "main" for x in entry.get("absentFiles", [])):
                    raise ValueError("Unreported missing executable: " + folder)
                missing_main.append(folder)
            code = entry.get("codeInfo", {})
            path = code.get("file", "").replace("\\", "/")
            if path != folder + "/code-info.bin":
                raise ValueError("Unexpected code-info path")
            data = read("firmware/" + path)
            if digest(data) != code.get("sha256"):
                raise ValueError("Code-info checksum mismatch: " + folder)
            verified["firmware/" + path] = data

        if set(files) != set(verified):
            raise ValueError("Unknown member(s) in system-code archive")
        print(f"NS2_SYSTEM_CODE_DUMP_PASS captured={len(seen)} "
              f"complete_pairs={len(seen)-len(missing_main)} missing_main={len(missing_main)} "
              f"verified_files={len(verified)} ncm_index_keys={len(ncm_records)} "
              f"crypto_keys=0 firmware_nca=0 runtime_ready=NO")
        if missing_main:
            print("MISSING_MAIN_TITLE_IDS " + ", ".join(missing_main))
        if output is None:
            return
        if output.exists():
            raise FileExistsError("Refusing to replace existing output: " + str(output))
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output.parent, prefix=".encore-ns2-dump-") as temp:
            stage = Path(temp) / "ns2-extracted"
            for name, data in verified.items():
                target = stage.joinpath(*PurePosixPath(name).parts[1:])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            os.replace(stage, output)
        print(f"NS2_SYSTEM_CODE_DUMP_STAGED path={output} runtime_ready=NO")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Your own firmware.zip system-code dump")
    parser.add_argument("--output", type=Path, help="Create this new output directory, never overwrite")
    options = parser.parse_args()
    inspect(options.archive, options.output)
