#!/usr/bin/env python3
"""Fail closed if P5-only NUP service overlays drift from the pinned vendor.

This is source parity verification, NOT a compile/link or a console test.
Only the two intended services are changed when EDEN_NUP_V1_RUNTIME=ON.
"""
from __future__ import annotations
from pathlib import Path
import subprocess
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
VENDOR = "https://raw.githubusercontent.com/niakw/Prospero.Eden-Encore-vendor"
FILES = (
    ("encore-active/eden-core/src/core/hle/service/aoc/addon_content_manager.cpp",
     "headless/nup_v1_aoc_service.cpp"),
    ("encore-active/eden-core/src/core/file_sys/romfs_factory.cpp",
     "headless/nup_v1_romfs_factory.cpp"),
)

def vendor_source(ref: str, path: str) -> str:
    request = Request(f"{VENDOR}/{ref}/{path}", headers={
        "User-Agent": "EdenEncore-NUP-Service-Source-Preflight"
    })
    with urlopen(request, timeout=20) as response:
        raw = response.read(128 * 1024 + 1)
    assert raw.startswith(b"// SPDX-") and len(raw) <= 128 * 1024, path
    return raw.decode("utf-8")

def between(code: str, start: str, end: str) -> str:
    a = code.find(start)
    b = code.find(end, a + len(start))
    assert a >= 0 and b > a, f"missing owner region {start}"
    return code[a:b]

def main() -> None:
    pinned = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD:vendor"], text=True
    ).strip()
    assert len(pinned) == 40
    originals = {}
    patched = {}
    for vendor_path, ours in FILES:
        originals[vendor_path] = vendor_source(pinned, vendor_path)
        patched[ours] = (ROOT / ours).read_text(encoding="utf-8")

    aoc_old = originals[FILES[0][0]]
    aoc = patched[FILES[0][1]]
    # Construction, existing NCA/extracted enumeration and event services
    # are intentionally unmodified. Only Count/List/Base/Prepare are bridged.
    for first, last in (
        ("static std::vector<u64> AccumulateAOCTitleIDs(",
         "IAddOnContentManager::IAddOnContentManager("),
        ("IAddOnContentManager::IAddOnContentManager(",
         "Result IAddOnContentManager::CountAddOnContent("),
        ("Result IAddOnContentManager::GetAddOnContentListChangedEvent(",
         "void LoopProcess("),
    ):
        assert between(aoc_old, first, last) == between(aoc, first, last), (
            f"upstream aoc:u owner drift: {first}")
    for marker in (
        "VisibleAddOnTitleIds(", "SoleActiveAddOns()",
        "nup->BaseId(title_id)", "nup->OpenRomFS(program_id",
        "Settings::values.disabled_addons[current]",
    ):
        assert marker in aoc, f"missing NUP AoC gate: {marker}"

    romfs_old = originals[FILES[1][0]]
    romfs = patched[FILES[1][1]]
    for first, last in (
        ("RomFSFactory::RomFSFactory(", "VirtualFile RomFSFactory::Open("),
        ("std::shared_ptr<NCA> RomFSFactory::GetEntry(", "} // namespace FileSys"),
    ):
        assert between(romfs_old, first, last) == between(romfs, first, last), (
            f"upstream RomFS owner drift: {first}")
    for marker in (
        "SoleActiveAddOns()", "const auto try_nup",
        "ExtractedAoc::OpenRomFS(title_id)", "res->GetRomFS()",
        "Settings::values.disabled_addons[current]",
    ):
        assert marker in romfs, f"missing NUP RomFS fallback gate: {marker}"

    runtime = (ROOT / "headless/nup_v1_runtime.cmake").read_text()
    assert 'option(EDEN_NUP_V1_RUNTIME' in runtime
    assert 'nup_v1_romfs_factory.cpp' in runtime
    assert 'nup_v1_aoc_service.cpp' in runtime
    assert 'EDEN_FINAL_RELEASE_PROFILE' in runtime
    assert 'exactly one existing AoC/ROMFS source owner' in runtime
    metadata = (ROOT / "headless/metadata_bridge.cpp").read_text()
    assert '#ifdef EDEN_NUP_V1_RUNTIME' in metadata
    assert 'ReadLocalizedTitle(nup_title, PreferredNupLocale())' in metadata
    assert 'ReadLocalizedIcon(icon_bytes, PreferredNupLocale())' in metadata
    assert 'HasNupV1Header(file)' in metadata
    # Game discovery may advertise the extension only in P5.
    game_files = (ROOT / "headless/game_files.h").read_text()
    assert '#ifdef EDEN_NUP_V1_RUNTIME' in game_files
    assert 'IsNupFile(name)' in game_files
    print(f"NUP service source parity {pinned[:12]}: maintained NCA/extracted paths retained, P5-only hooks present")

if __name__ == "__main__":
    main()
