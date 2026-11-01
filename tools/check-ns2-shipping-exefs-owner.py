#!/usr/bin/env python3
"""Validate one shipping PS5 ExeFS owner for NS1 and NS2."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
cmake = (ROOT / "headless/CMakeLists.txt").read_text()
release = cmake.split("# Experimental ExeFS bridge", 1)[1].split(
    "# N52: process-run admission", 1
)[0]
assert 'option(EDEN_NS2_EXEFS_EXPERIMENTAL' in release
assert 'set(EDEN_SHARED_NS2_EXEFS OFF)' in release
assert 'if(PS5_NATIVE AND EDEN_FINAL_RELEASE_PROFILE AND EDEN_REVIEWED_DUAL_NPDM)' in release
assert 'set(EDEN_SHARED_NS2_EXEFS ON)' in release
assert 'if(EDEN_NS2_EXEFS_EXPERIMENTAL OR EDEN_SHARED_NS2_EXEFS)' in release
assert 'if(NOT EDEN_REVIEWED_DUAL_NPDM)' in release
assert 'set_property(TARGET core PROPERTY SOURCES' in release
for name in ("loader.cpp", "deconstructed_rom_directory.cpp"):
    assert (ROOT / "vendor/encore-active/ns2-experimental/src/core/loader" / name).is_file()
positions = [i for i in range(len(release))
             if release.startswith('if(PS5_NATIVE AND EDEN_NS2_EXEFS_EXPERIMENTAL)', i)]
assert len(positions) == 2
assert 'eden_ns2_native_nso_idx' in release[positions[0]:positions[1]]
assert 'EDEN_NS2_NATIVE_SVC_SOURCE' in release[positions[1]:]
assert 'EDEN_SHARED_NS2_EXEFS' in release
rom = (ROOT / "vendor/encore-active/ns2-experimental/src/core/loader/deconstructed_rom_directory.cpp").read_text()
loader = (ROOT / "vendor/encore-active/ns2-experimental/src/core/loader/loader.cpp").read_text()
for required in (
    "metadata.IsSwitch2()", "metadata.UsesExtendedAcid()",
    "Eden::NS2::ExeFS::PreflightNso",
    "Eden::NS2::ExeFS::AdmitKProcessCode",
    "Eden::NS2::ExeFS::MainThreadPermitted",
    "Eden::NS2::ExeFS::VerifyUncompressedTextHandoff",
):
    assert required in rom, required
assert "Eden::NS2::SvcTrace::Register" in rom
assert 'IdentifyFileLoader<AppLoader_DeconstructedRomDirectory>(file)' in loader
assert "Eden::NS2::Content::IdentifyName" in loader
assert "AppLoader_NSP" in loader and "AppLoader_XCI" in loader
assert 'Settings::SetNceEnabled(is_39bit && !metadata.UsesExtendedAcid())' in rom
print("ENCORE_NS2_SHARED_EXEFS_SHIPPING_OWNER_PASS release=one ns1_nso_preserved=1")
