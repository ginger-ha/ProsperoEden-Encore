#!/usr/bin/env python3
"""Source + C++20 host witness for NS2-only GPU access SVC 0x80 admission."""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
vendor = root / "vendor/encore-active"
base = vendor / "ns2-runtime/gpu_access_svc"
src = (base / "core/hle/kernel/svc.cpp").read_text()
helper = (base / "core/hle/kernel/ns2_gpu_memory_attribute.h").read_text()
pid = (vendor / "ns2-helpers/include/core/loader/ns2_svc_trace.h").read_text()
recipe = (root / "headless/CMakeLists.txt").read_text()
assert recipe.count("set(EDEN_SHARED_NS2_GPU_ACCESS_SVC ON)") == 1
assert 'PS5_NATIVE AND EDEN_FINAL_RELEASE_PROFILE AND EDEN_REVIEWED_DUAL_NPDM' in recipe
assert 'list(REMOVE_ITEM eden_ns2_gpu_access_sources "hle/kernel/svc.cpp")' in recipe
assert 'target_include_directories(core BEFORE PUBLIC "${EDEN_NS2_GPU_ACCESS_ROOT}")' in recipe
assert 'Eden::NS2::SvcTrace::IsActive(process.GetProcessId())' in src
assert 'Settings::values.memory_layout_mode.GetValue() == Settings::MemoryLayout::Memory_12Gb' in src
assert 'process.Is64Bit()' in src
assert 'process.GetPageTable().Contains(address, size)' in src
assert 'process.GetPageTable().SetMemoryAttribute(' in src
assert 'static_cast<KMemoryAttribute>(mask)' in src
assert 'static_cast<KMemoryAttribute>(attribute)' in src
svc_enum = (base / "core/hle/kernel/svc_types.h").read_text()
block_enum = (base / "core/hle/kernel/k_memory_block.h").read_text()
assert 'GpuAccessible = (1 << 5)' in svc_enum
assert 'GpuAccessible = static_cast<u8>(Svc::MemoryAttribute::GpuAccessible)' in block_enum
assert 'SetMask = Uncached | PermissionLocked | GpuAccessible' in block_enum
assert 'target_include_directories(core BEFORE PUBLIC "${EDEN_NS2_GPU_ACCESS_ROOT}")' in recipe
assert 'target_include_directories(video_core BEFORE PRIVATE "${EDEN_NS2_GPU_ACCESS_ROOT}")' in recipe
assert 'if (imm == 0x80' in src
assert 'case Eden::NS2::GpuAccess::Status::InvalidAddress:' in src
assert 'case Eden::NS2::GpuAccess::Status::InvalidSize:' in src
assert 'case Eden::NS2::GpuAccess::Status::InvalidAttribute:' in src
assert 'result = ResultInvalidCurrentMemory;' in src
assert 'SetArg64(args, 0, result.raw);' in src
assert 'else if (process.Is64Bit())' in src and 'Call64(system, imm, args);' in src
assert 'active_pid.load(std::memory_order_acquire) == pid' in pid
assert 'GpuAccessibleMask = 0x20' in helper
compiler = shutil.which("clang++-18") or shutil.which("clang++") or shutil.which("g++")
assert compiler, "C++20 host compiler unavailable"
fixture = r"""
#include "core/hle/kernel/ns2_gpu_memory_attribute.h"
#include "core/loader/ns2_svc_trace.h"
#include <cassert>
#include <cstdint>
#include <limits>
using Eden::NS2::GpuAccess::Validate;
using Eden::NS2::GpuAccess::Status;
static_assert(Validate(0x1000, 0x1000, 0x20, 0x20) == Status::Success);
static_assert(Validate(0x1000, 0x2000, 0x20, 0) == Status::Success);
static_assert(Validate(0x1000, 0x1000, 0, 0) == Status::Success);
static_assert(Validate(0x1001, 0x1000, 0x20, 0x20) == Status::InvalidAddress);
static_assert(Validate(0x1000, 0, 0x20, 0x20) == Status::InvalidSize);
static_assert(Validate(0x1000, 0x1001, 0x20, 0x20) == Status::InvalidSize);
static_assert(Validate(std::numeric_limits<std::uint64_t>::max()-0xfff, 0x2000, 0x20, 0x20) == Status::InvalidSize);
static_assert(Validate(0x1000, 0x1000, 0x10, 0x20) == Status::InvalidAttribute);
static_assert(Validate(0x1000, 0x1000, 0x20, 0x10) == Status::InvalidAttribute);
int main() {
    using namespace Eden::NS2::SvcTrace;
    assert(!IsActive(0));
    assert(!IsActive(123));
    Register(123);
    assert(IsActive(123) && !IsActive(124));
    Unregister(124);
    assert(IsActive(123));
    Unregister(123);
    assert(!IsActive(123));
}
"""
with tempfile.TemporaryDirectory(prefix="encore-ns2-gpu-access-") as d:
    p = Path(d)
    (p / "test.cpp").write_text(fixture)
    exe = p / "test"
    subprocess.run([compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                    "-I", str(base), "-I", str(vendor / "ns2-helpers/include"),
                    str(p / "test.cpp"), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("ENCORE_NS2_GPU_ACCESS_SVC_HOST_PASS pid=exact mask=0x20 alignment=4k overflow=guarded ns1=unchanged")
