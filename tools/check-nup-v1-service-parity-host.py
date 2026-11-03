#!/usr/bin/env python3
"""Fail closed if P5-only NUP service overlays drift from the pinned vendor.

This is source parity verification, NOT a compile/link or a console test.
Only the two intended services are changed when EDEN_NUP_V1_RUNTIME=ON.
"""
from __future__ import annotations
from pathlib import Path
import shutil
import subprocess
import tempfile
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
    # Execute the production byte-bound copy expression as C++20, including
    # unaligned, zero-byte and short HIPC output spans. This is a host
    # contract test, not a PS5 service dispatch or guest IPC proof.
    begin = aoc.index("    const std::size_t capacity = out_addons.size() / sizeof(u32);")
    end = aoc.index("\n\n    R_SUCCEED();", begin)
    ipc_policy = aoc[begin:end]
    assert "std::memcpy(out_addons.data(), out.data() + offset," in ipc_policy
    assert "if (*out_count)" in ipc_policy
    test_cpp = r"""
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <span>
#include <vector>
using u32 = std::uint32_t;
u32 copy_ids(std::vector<u32> out, u32 offset, u32 count,
             std::span<std::uint8_t> out_addons) {
    u32 written = 0;
    u32* out_count = &written;
""" + ipc_policy + r"""
    return written;
}
int main() {
    for (const std::size_t capacity : {0u, 1u, 3u, 4u, 7u, 8u, 11u, 12u, 16u}) {
        std::array<std::uint8_t, 64> destination{};
        destination.fill(0xA5);
        const u32 count = copy_ids({11, 22, 33, 44}, 1, 4,
            std::span<std::uint8_t>(destination.data() + 3, capacity));
        assert(count == std::min<std::size_t>(3, capacity / sizeof(u32)));
        for (std::size_t n = 0; n < count; ++n) {
            u32 value{};
            std::memcpy(&value, destination.data() + 3 + n*sizeof(u32), sizeof(u32));
            assert(value == 22 + n * 11);
        }
        for (std::size_t n = 3 + count * sizeof(u32); n < destination.size(); ++n)
            assert(destination[n] == 0xA5);
        assert(destination[0] == 0xA5 && destination[2] == 0xA5);
    }
    assert(copy_ids({11,22,33}, 3, 9, {}) == 0);
}
"""
    compilers = list(dict.fromkeys(filter(None, (
        shutil.which("clang++"), shutil.which("g++")))))
    assert compilers, "P1.3 host C++ compiler unavailable"
    with tempfile.TemporaryDirectory(prefix="encore-aoc-ipc-") as tmp:
        source = Path(tmp) / "ipc.cpp"
        source.write_text(test_cpp)
        for compiler in compilers:
            for optimization in ("-O0", "-O2"):
                executable = Path(tmp) / (Path(compiler).name + optimization)
                subprocess.run(
                    [compiler, "-std=c++20", optimization,
                     "-Wall", "-Wextra", "-Werror",
                     str(source), "-o", str(executable)], check=True, timeout=40)
                subprocess.run([str(executable)], check=True, timeout=15)

    print(f"NUP service source parity {pinned[:12]}: maintained NCA/extracted paths retained, P5-only hooks present")

if __name__ == "__main__":
    main()
