#!/usr/bin/env python3
"""Host regression: exact extracted NS2JB input and safe NPDM identity."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    module_path = ROOT / "tools/ns2/prepare_firmware_dump.py"
    spec = importlib.util.spec_from_file_location("ns2_dump", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    compiler = shutil.which("clang++-18") or shutil.which("clang++") or shutil.which("g++")
    assert compiler
    with tempfile.TemporaryDirectory(prefix="encore-ns2-firmware-") as tmp:
        root = Path(tmp)
        payloads = {}
        def put(relative: str, data: bytes) -> dict:
            payloads["firmware/" + relative] = data
            return {"file": relative.replace("/", "\\"), "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest()}
        inventory = b"synthetic system-program inventory"
        put("ncm-system-programs.bin", inventory)
        entries = []
        for title, has_main in (("0400000000000019", True), ("0400000000000837", False)):
            npdm = bytearray(0xB0)
            npdm[:4] = b"META"
            npdm[0x70] = 0x80
            npdm[0x74] = 0x30
            npdm[0x80:0x84] = b"ACI0"
            npdm[0x90:0x98] = int(title, 16).to_bytes(8, "little")
            members = [put(title + "/main.npdm", bytes(npdm))]
            if has_main:
                members.append(put(title + "/main", b"NSO0" + b"0" * 32))
            code = put(title + "/code-info.bin", b"synthetic info")
            entries.append({"title": "0x" + title, "status": "captured", "version": 1,
                            "codeInfo": code, "files": members,
                            "absentFiles": [] if has_main else [{"name": "main", "result": 514}]})
        put(".ns2jb-firmware-dump.json", json.dumps({"kind": "ns2jb-system-code-dump"}).encode())
        put("firmware-dump-named.json",
            json.dumps({"complete": True, "counts": {"captured": len(entries)},
                        "inventory": {"rawFile": "ncm-system-programs.bin",
                                      "sha256": hashlib.sha256(inventory).hexdigest(),
                                      "total": len(entries),
                                      "keys": [{"id": e["title"], "version": e["version"],
                                                "type": 1, "installType": 1} for e in entries]},
                        "entries": entries}).encode())
        archive = root / "firmware.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name, data in payloads.items():
                z.writestr(name, data)
            z.writestr("__MACOSX/junk", b"ignored")
        module.inspect(archive)
        dest = root / "ns2-extracted"
        module.inspect(archive, dest)
        assert (dest / "0400000000000019/main").read_bytes().startswith(b"NSO0")
        assert not (dest / "0400000000000837/main").exists()
        assert not (dest / "__MACOSX").exists()
        try:
            module.inspect(archive, dest)
        except FileExistsError:
            pass
        else:
            raise AssertionError("Existing import was overwritten")
        # Exercise the exact shipping failure probe on both ACID signature
        # prefixes without supplying protected Nintendo data.
        def access_fixture(name: str, prefix: int, fac_offset: int) -> Path:
            image = bytearray(0x1000)
            image[:4] = b"META"
            image[0x78:0x7c] = (0x200).to_bytes(4, "little")
            image[0x7c:0x80] = (0x600).to_bytes(4, "little")
            base = 0x200 + prefix
            image[base:base+4] = b"ACID"
            image[base+0x20:base+0x24] = fac_offset.to_bytes(4, "little")
            image[base+0x24:base+0x28] = (0x2c).to_bytes(4, "little")
            p = root / name
            p.write_bytes(image)
            return p
        ns1 = access_fixture("valid-ns1.npdm", 0x200, 0x240)
        ns2 = access_fixture("valid-ns2.npdm", 0x300, 0x340)
        bad_fac = access_fixture("invalid-ns2-fac.npdm", 0x300, 0x5f0)
        cpp = root / "npdm.cpp"
        cpp.write_text("""#include "extracted_npdm_identity.h"
#include <cassert>
int main(int argc, char** argv) {
    assert(argc == 6);
    assert(Eden::ExtractedNpdm::TitleId(argv[1]) == 0x0400000000000019ULL);
    assert(Eden::ExtractedNpdm::TitleId(argv[2]) == 0);
    const auto one = Eden::ExtractedNpdm::ProbeAccess(argv[3]);
    const auto two = Eden::ExtractedNpdm::ProbeAccess(argv[4]);
    const auto broken = Eden::ExtractedNpdm::ProbeAccess(argv[5]);
    assert(one.header_ok && one.acid_found && !one.extended && one.fac_valid);
    assert(two.header_ok && two.acid_found && two.extended && two.fac_valid);
    assert(broken.header_ok && broken.acid_found && broken.extended &&
           !broken.fac_valid);
}""")
        binary = root / "check-npdm"
        subprocess.run([compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        "-I", str(ROOT / "headless"), str(cpp), "-o", str(binary)],
                       check=True, timeout=40)
        invalid = root / "bad.npdm"
        invalid.write_bytes(b"META" + b"0" * 36)
        subprocess.run([str(binary),
                        str(dest / "0400000000000019/main.npdm"), str(invalid),
                        str(ns1), str(ns2), str(bad_fac)],
                       check=True, timeout=10)
    print("NS2_EXTRACTED_INPUTS_HOST_PASS validated=1 partial=1 npdm_aci0=1 acid_ns1=1 acid_ns2=1 invalid_fac=1 overwrite=0")


if __name__ == "__main__":
    main()
