#!/usr/bin/env python3
"""Compile the actual 4K GMMU partition helper and verify its source owner."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
AS = ROOT / "vendor/encore-active/ns2-runtime/nvdrv_as"
OWNER = AS / "core/hle/service/nvdrv/devices/nvhost_as_gpu.cpp"
HELPER = AS / "core/hle/service/nvdrv/devices/native_gpu_va_layout.h"
TEST = ROOT / "tools/ns2/test_native_gpu_va_layout.cpp"

def main():
    if not all(p.is_file() for p in (OWNER, HELPER, TEST)):
        print("NS2 4K GMMU source owner missing", file=sys.stderr)
        return 2
    owner = OWNER.read_text()
    markers = (
        'PlanNativeGpuVaLayout(start, split, end, big_page_size)',
        'if (!layout) return NvResult::BadValue;',
        'vm.small_page_allocator.emplace(layout->small_begin, layout->small_end);',
        'vm.big_page_allocator.emplace(layout->big_begin, layout->big_end);',
        'if (!vm.initialised || !gmmu || !m_native_process)',
        'const std::scoped_lock lock{mutex, gpu_channel_device->channel_mutex};',
        'if (!session || session->process != m_native_process)',
        'if (channel.memory_manager && channel.memory_manager != gmmu.get())',
    )
    if not all(x in owner for x in markers):
        print("NS2 real GMMU layout owner not wired to validated helper", file=sys.stderr)
        return 2
    if '(vm.va_range_end - vm.va_range_split) >> vm.big_page_size_bits' in owner:
        print("Relative GPU VA allocator bound reintroduced", file=sys.stderr)
        return 2
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        print("C++20 compiler missing", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="encore-ns2-gmmu-va-") as folder:
        for opt in ("-O0", "-O2"):
            exe = Path(folder) / ("test" + opt)
            command = [compiler, "-std=c++20", opt, "-Wall", "-Wextra", "-Werror",
                       "-pedantic", "-fsanitize=undefined", "-fno-sanitize-recover=all",
                       "-I", str(AS), str(TEST), "-o", str(exe)]
            subprocess.run(command, check=True)
            subprocess.run([str(exe)], check=True,
                           env={**os.environ, "UBSAN_OPTIONS": "halt_on_error=1"})
    print("Native GMMU bounds and absolute VA limit: PASS (O0/O2 UBSan)")
    print("No native GPU worker, Ampere shaders or PS5 first frame inferred.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
