#!/usr/bin/env python3
"""Compile the maintained BufferCache::FindBuffer with table/span boundary cases.

The native owner is extracted verbatim; the historical desktop backport must
remain untouched. This validates guest-buffer admission without a PS5 build.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
active = (ROOT / "vendor/encore-active/eden-core/src/video_core/buffer_cache/buffer_cache.h").read_text()
backport = (ROOT / "vendor/encore-active/eden-backports/src/video_core/buffer_cache/buffer_cache.h").read_text()
needle = "template <class P>\nBufferId BufferCache<P>::FindBuffer(DAddr device_addr, u32 size, bool sparse_compatible) {"
assert active.count(needle) == backport.count(needle) == 1
begin = active.index(needle)
method = active[begin:active.index("\ntemplate <class P>", begin + len(needle))]
assert "page >= page_table.size()" in method
assert "size > (u64{page_table.size()} << CACHING_PAGEBITS) - device_addr" in method
assert method.index("page >= page_table.size()") < method.index("page_table[page]")
legacy = backport[backport.index(needle):]
legacy = legacy[:legacy.index("\ntemplate <class P>", len(needle))]
assert "page >= page_table.size()" not in legacy  # selected native-only change
fixture = r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <vector>
using u32 = std::uint32_t;
using u64 = std::uint64_t;
using DAddr = u64;
using BufferId = unsigned;
constexpr BufferId NULL_BUFFER_ID = 0;
namespace Settings { bool IsGPUFenceBehaviorAccurate() { return false; } }
struct Buffer {
    DAddr base{};
    u32 bytes{};
    bool IsInBounds(DAddr start, u32 count) const {
        return start >= base && count <= bytes && start - base <= bytes - count;
    }
    bool IsSparseCompatible() const { return true; }
};
template<class P> class BufferCache {
public:
    static constexpr u32 CACHING_PAGEBITS = 16;
    std::vector<BufferId> page_table = std::vector<BufferId>(1 << (34 - CACHING_PAGEBITS));
    std::vector<Buffer> slot_buffers = {{}, {0x10000, 4096}};
    unsigned creations{};
    unsigned synchronizations{};
    void SynchronizeBufferWrites(Buffer&) { ++synchronizations; }
    BufferId CreateBuffer(DAddr, u32, bool) { ++creations; return 2; }
    BufferId FindBuffer(DAddr device_addr, u32 size, bool sparse_compatible);
};
''' + method + r'''
int main() {
    BufferCache<void> b;
    constexpr DAddr limit = DAddr{1} << 34;
    b.page_table[1] = 1;
    assert(b.FindBuffer(0, 16, false) == 0);
    assert(b.FindBuffer(0x10020, 32, false) == 1);
    assert(b.creations == 0 && b.synchronizations == 0);
    assert(b.FindBuffer(0x20100, 16, false) == 2);
    assert(b.creations == 1);
    assert(b.FindBuffer(limit - 64, 64, false) == 2);
    assert(b.creations == 2);
    assert(b.FindBuffer(limit - 64, 65, false) == 0);
    assert(b.FindBuffer(limit - 1, 2, false) == 0);
    assert(b.FindBuffer(limit, 1, false) == 0);
    assert(b.FindBuffer(limit + 65536, 1, false) == 0);
    assert(b.FindBuffer(~DAddr{0}, 1, false) == 0);
    assert(b.FindBuffer(limit - 1, ~u32{0}, false) == 0);
    assert(b.creations == 2 && b.synchronizations == 0);
}
'''
compiler = shutil.which("clang++") or shutil.which("c++") or shutil.which("g++")
assert compiler, "C++ compiler required"
env = dict(os.environ)
if Path("/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk").exists():
    env["SDKROOT"] = "/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk"
with tempfile.TemporaryDirectory(prefix="ns2-buffer-find-") as folder:
    source = Path(folder) / "test.cpp"
    source.write_text(fixture)
    for opt in ("-O0", "-O2"):
        exe = Path(folder) / ("test" + opt)
        subprocess.run([compiler, "-std=c++20", opt, "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=undefined", "-fno-sanitize-recover=all",
                        str(source), "-o", str(exe)], check=True, timeout=45, env=env)
        subprocess.run([str(exe)], check=True, timeout=25, env=env)
        print("NS2_NATIVE_BUFFER_FIND_BOUNDS_PASS", opt)
