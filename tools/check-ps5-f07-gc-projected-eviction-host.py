#!/usr/bin/env python3
"""F07 P0.3: compile actual Vulkan GC projected-eviction lambdas.

Regression for the ImageBase->Image type mismatch in the GC prefetch
accounting path. Checks source/oracle parity, old-code negative compilation,
scaled/transcoded accounting and desktop/PS5 O0/O2 with UBSan. Host only.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "vendor/encore-active/eden-vulkan/vulkan-cache/video_core/texture_cache/texture_cache.h").read_text()
oracle = (root / "vendor/encore-active/eden-vulkan-oracles/vulkan_gc_downloads.inc").read_text()
generator = (root / "tools/prepare-vulkan-port.py").read_text()


def extract(text, marker, terminator):
    assert text.count(marker) == 1, f"missing/duplicate {marker}"
    start = text.index(marker)
    end = text.index(terminator, start) + len(terminator)
    return text[start:end]


reclaimed = extract(source, "    const auto ReclaimedBytes = [&](const Image& image) {", "\n    };")
projected = extract(source, "            const auto NoteProjectedEviction = [&](const Image& image) {", "\n            };")
assert projected in oracle, "GC prefetch oracle must preserve the concrete Image type"
assert "const auto ReclaimedBytes = [&](const Image& image)" in generator
assert "ReclaimedBytes(image)" in projected
assert source.count("NoteProjectedEviction(image)") == 2

cpp = r"""
#include <algorithm>
#include <cassert>
#include <cstdint>
using u64 = std::uint64_t;
enum class ImageFlagBits : unsigned { AcceleratedUpload=1, Converted=2 };
unsigned operator&(unsigned flags, ImageFlagBits bit) { return flags & static_cast<unsigned>(bit); }
bool True(unsigned flags) { return flags != 0; }
struct Info { int format=0; };
struct ImageBase { u64 guest_size_bytes=0, unswizzled_size_bytes=0; Info info{}; unsigned flags=0; };
struct Image : ImageBase { bool scaled=false; bool HasScaled() const { return scaled; } };
u64 GetScaledImageSizeBytes(const Image& image) { return image.scaled ? 2048 : 0; }
bool IsPixelFormatASTC(int format) { return format == 1; }
u64 TranscodedAstcSize(u64 size, int) { return size * 2; }
namespace Common { u64 AlignUp(u64 value, u64 alignment) {
    return (value + alignment - 1) / alignment * alignment;
} }
namespace Eden::VulkanMemory { u64 AfterProjectedEviction(u64 usage, u64 bytes) {
    return usage > bytes ? usage - bytes : 0;
} }
int main() {
    u64 usage = 10000, projected_stop = 6000;
__RECLAIMED__
__PROJECTED__
    Image image{};
    image.guest_size_bytes = 1500;
    image.unswizzled_size_bytes = 900;
    assert(ReclaimedBytes(image) == 2048);
    assert(!NoteProjectedEviction(image));
    image.scaled = true;
    assert(ReclaimedBytes(image) == 4096);
    assert(NoteProjectedEviction(image));
    usage = 10000;
    image.scaled = false;
    image.flags = 2;
    image.info.format = 1;
    assert(ReclaimedBytes(image) == 3072);
    assert(!NoteProjectedEviction(image));
}
""".replace("__RECLAIMED__", reclaimed).replace("__PROJECTED__", projected)

compiler = shutil.which("clang++-18") or shutil.which("clang++") or shutil.which("g++")
assert compiler, "C++20 compiler required"
with tempfile.TemporaryDirectory(prefix="f07-gc-reclaimed-") as folder:
    path = Path(folder) / "gc.cpp"
    path.write_text(cpp)
    for native in (False, True):
        for opt in ("-O0", "-O2"):
            exe = Path(folder) / f"{'ps5' if native else 'desktop'}{opt[1:]}"
            cmd = [compiler, "-std=c++20", opt, "-Wall", "-Wextra", "-Werror",
                   "-fsanitize=undefined", "-fno-sanitize-recover=all",
                   *(["-DPS5_NATIVE=1"] if native else []), str(path), "-o", str(exe)]
            built = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            assert built.returncode == 0, (native, opt, built.stderr[-4000:])
            ran = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
            assert ran.returncode == 0, (native, opt, ran.stderr[-4000:])
    old_projected = projected.replace("const Image& image", "const ImageBase& image")
    assert old_projected != projected
    path.write_text(cpp.replace(projected, old_projected))
    old = subprocess.run([compiler, "-std=c++20", "-O0", str(path),
                          "-o", str(Path(folder) / "old")],
                         capture_output=True, text=True, timeout=45)
    assert old.returncode != 0 and "ImageBase" in old.stderr, \
        "the previous base/derived mismatch must fail compilation"
print("F07_GC_PROJECTED_EVICTION_PASS concrete_image=1 scaled=1 transcoded=1 "
      "oracle=1 old_compile_failure=1 PS5=1 desktop=1 O0=1 O2=1 UBSan=1")
print("HOST_ONLY: no PS5 build, VRAM/FPS improvement or FC27 HUD claim")
