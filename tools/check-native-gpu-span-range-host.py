#!/usr/bin/env python3
"""Compile both real GPU GetSpan overloads with checked page-table range fixture.

The original methods access the range-walking page table before validating
GPU address-space bounds. The native derived methods must reject invalid
ranges first, without altering the normal valid-range lookup sequence.
This is host-only; no graphics driver or console environment is required.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "vendor/sources/eden/src/video_core/memory_manager.cpp").read_text()
maintained = (ROOT / "vendor/encore-active/eden-core/src/video_core/memory_manager.cpp").read_text()
cmake = (ROOT / "headless/CMakeLists.txt").read_text()
workflow = (ROOT / ".github/workflows/encore-core-preflight.yml").read_text()
start = "const u8* MemoryManager::GetSpan(const GPUVAddr src_addr, const std::size_t size) const {"
end = "} // namespace Tegra"
assert source.count(start) == 1 and source.count(end) == 1
methods = source[source.index(start):source.index(end)]
old = "    if (!IsContinuousRange(src_addr, size)) {"
assert methods.count(old) == 2
new = """    if (size == 0 || src_addr >= address_space_size ||
        size > address_space_size - src_addr ||
        !IsContinuousRange(src_addr, size)) {"""
assert maintained.count(new) == 2
assert 'set(EDEN_NATIVE_GPU_MEMORY_MANAGER' in cmake
assert cmake.count('list(REMOVE_ITEM video_sources "memory_manager.cpp")') == 1
assert cmake.count('list(APPEND video_sources "${EDEN_NATIVE_GPU_MEMORY_MANAGER}")') == 1
assert 'write_derived("${eden_gpu_span_tu}"' not in cmake
native_methods = maintained[maintained.index(start):maintained.index(end)]
assert native_methods == methods.replace(old, new), "native GetSpan guards differ from old generator"
assert "python3 -B tools/check-native-gpu-span-range-host.py" in workflow

cpp = r"""
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>
using u8 = std::uint8_t;
using GPUVAddr = std::uint64_t;
using DAddr = std::uint64_t;
struct FakeDevice {
    std::array<u8,8192> bytes{};
    u8* GetSpan(DAddr a, std::size_t n) {
        return a < bytes.size() && n <= bytes.size() - a
            ? bytes.data() + a : nullptr;
    }
    const u8* GetSpan(DAddr a, std::size_t n) const {
        return a < bytes.size() && n <= bytes.size() - a
            ? bytes.data() + a : nullptr;
    }
};
struct MemoryManager {
    static constexpr GPUVAddr address_space_size = 8192;
    FakeDevice memory;
    mutable unsigned probes{};
    std::array<int,2> page_table{1,1};
    bool IsContinuousRange(GPUVAddr addr, std::size_t) const {
        ++probes;
        // Mirrors the unguarded GetEntry indexed page-vector access.
        return page_table.at(static_cast<std::size_t>(addr >> 12)) != 0;
    }
    std::optional<DAddr> GpuToCpuAddress(GPUVAddr addr) const {
        if (addr >= address_space_size) return std::nullopt;
        return addr;
    }
    const u8* GetSpan(GPUVAddr addr,std::size_t size) const;
    u8* GetSpan(GPUVAddr addr,std::size_t size);
};
@@METHODS@@
int main() {
    MemoryManager m;
    const auto& c=static_cast<const MemoryManager&>(m);
    assert(m.GetSpan(0,4096)!=nullptr);
    assert(c.GetSpan(4096,4096)!=nullptr);
    assert(m.GetSpan(4095,2)!=nullptr);
#ifdef EXPECT_NATIVE
    auto prior=m.probes;
    assert(m.GetSpan(8192,1)==nullptr);
    assert(c.GetSpan(8192,1)==nullptr);
    assert(m.GetSpan(0,0)==nullptr);
    assert(c.GetSpan(0,0)==nullptr);
    assert(m.GetSpan(8191,2)==nullptr);
    assert(c.GetSpan(8191,2)==nullptr);
    assert(m.GetSpan(UINT64_MAX,2)==nullptr);
    assert(c.GetSpan(UINT64_MAX,2)==nullptr);
    assert(m.probes == prior); // Never walk unmapped/out-of-space vectors.
#else
    bool threw=false;
    try { (void)m.GetSpan(8192,1); }
    catch(const std::out_of_range&) { threw=true; }
    assert(threw);  // Original calls the page walk with invalid page index.
    threw=false;
    try { (void)c.GetSpan(8192,1); }
    catch(const std::out_of_range&) { threw=true; }
    assert(threw);
    assert(m.GetSpan(0,0)!=nullptr); // Original silently accepts zero span.
#endif
}
"""
clang = shutil.which("clang++-18") or shutil.which("clang++")
assert clang, "Clang C++20 is required"
with tempfile.TemporaryDirectory(prefix="encore-gpu-span-range-") as scratch:
    dest=Path(scratch)
    for name,body,enabled in (("pinned",methods,False),
                              ("native",native_methods,True)):
        unit=dest / (name + ".cpp")
        unit.write_text(cpp.replace("@@METHODS@@",body))
        exe=dest / name
        command=[clang,"-std=c++20","-O1","-g","-Wall","-Wextra","-Werror",
                 "-fsanitize=address,undefined","-fno-sanitize-recover=all"]
        if enabled: command.append("-DEXPECT_NATIVE")
        command += [str(unit),"-o",str(exe)]
        subprocess.run(command,check=True,timeout=45)
        subprocess.run([str(exe)],check=True,timeout=45)
print("NATIVE_GPU_SPAN_RANGE_HOST_PASS original_oob_pagewalk=2 original_zero_span=1 native_const_mutable=2 native_zero=1 overflow=1 past_end=1 normal_ranges=3")


# P1.2: compile the *actual guard prefixes* from the maintained shared
# GMMU owner. Out-of-VA and wrapping spans must be refused before ANY
# PTE traversal, including callers that do not go through GetSpan.
owner = maintained
contracts = (
    ("std::optional<DAddr> MemoryManager::GpuToCpuAddress(GPUVAddr addr, std::size_t size) const {",
     "    size_t page_index{addr >> page_bits};",
     "    ++page_probes;\n    return DAddr{0x1000};\n}"),
    ("bool MemoryManager::IsContinuousRange(GPUVAddr gpu_addr, std::size_t size) const {",
     "    std::optional<DAddr> old_page_addr{};",
     "    ++page_probes;\n    return true;\n}"),
    ("bool MemoryManager::IsFullyMappedRange(GPUVAddr gpu_addr, std::size_t size) const {",
     "    bool result{true};",
     "    ++page_probes;\n    return true;\n}"),
)
prefixes = []
for signature, next_statement, continuation in contracts:
    assert owner.count(signature) == 1, signature
    at = owner.index(signature)
    end_at = owner.index(next_statement, at)
    prefix = owner[at:end_at]
    assert "size == 0" in prefix, signature
    assert "address_space_size" in prefix, signature
    assert "size > address_space_size -" in prefix, signature
    prefixes.append(prefix + continuation)

unit_source = r"""
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <utility>
using GPUVAddr = std::uint64_t;
using DAddr = std::uint64_t;
struct MemoryManager {
    static constexpr GPUVAddr address_space_size = GPUVAddr{1} << 49;
    static constexpr std::size_t page_bits = 12;
    mutable unsigned page_probes{};
    std::optional<DAddr> GpuToCpuAddress(GPUVAddr, std::size_t) const;
    bool IsContinuousRange(GPUVAddr, std::size_t) const;
    bool IsFullyMappedRange(GPUVAddr, std::size_t) const;
};
""" + "\n".join(prefixes) + r"""
int main() {
    MemoryManager gpu;
    constexpr GPUVAddr limit = MemoryManager::address_space_size;
    constexpr std::size_t huge = std::numeric_limits<std::size_t>::max();
    const std::array<std::pair<GPUVAddr, std::size_t>, 8> bad{{
        {0, 0}, {limit-1, 0}, {limit, 1}, {limit+1, 1},
        {limit-1, 2}, {limit-4096, 4097},
        {std::numeric_limits<GPUVAddr>::max(), 16}, {10, huge},
    }};
    for (const auto [addr, bytes] : bad) {
        assert(!gpu.GpuToCpuAddress(addr, bytes));
        assert(!gpu.IsContinuousRange(addr, bytes));
        assert(!gpu.IsFullyMappedRange(addr, bytes));
    }
    assert(gpu.page_probes == 0); // No page-table read on any invalid span.
    const std::array<std::pair<GPUVAddr, std::size_t>, 4> valid{{
        {0, 1}, {4095, 2}, {limit - 4096, 4096}, {0, limit},
    }};
    for (const auto [addr, bytes] : valid) {
        assert(gpu.GpuToCpuAddress(addr, bytes).has_value());
        assert(gpu.IsContinuousRange(addr, bytes));
        assert(gpu.IsFullyMappedRange(addr, bytes));
    }
    assert(gpu.page_probes == valid.size() * 3);
}
"""
compilers = list(dict.fromkeys(path for name in ("clang++", "g++")
                               if (path := shutil.which(name))))
assert compilers, "At least one C++20 compiler required"
with tempfile.TemporaryDirectory(prefix="encore-gmmu-bounds-") as directory:
    cpp = Path(directory) / "gmmu_bounds.cpp"
    cpp.write_text(unit_source)
    for compiler in compilers:
        for opt in ("-O0", "-O2"):
            binary = Path(directory) / (Path(compiler).name + opt)
            subprocess.run([compiler, "-std=c++20", opt, "-Wall", "-Wextra",
                            "-Werror", "-fsanitize=undefined",
                            "-fno-sanitize-recover=all", str(cpp), "-o",
                            str(binary)], check=True, timeout=45)
            subprocess.run([str(binary)], check=True, timeout=20)
            print("P1_2_NATIVE_GMMU_BOUNDS_HOST_PASS", Path(compiler).name, opt)


# Sparse-map teardown is another direct caller of MemoryOperation. Do not
# let a malicious VA or a wrapping length reach its page-table iterator.
for signature, walk in (
    ("void MemoryManager::Unmap(GPUVAddr gpu_addr, std::size_t size) {",
     "GetSubmappedRangeImpl<false>(gpu_addr, size, page_stash);"),
    ("MemoryManager::GetSubmappedRange(GPUVAddr gpu_addr, std::size_t size) const {",
     "GetSubmappedRangeImpl<true>(gpu_addr, size, result);"),
):
    assert owner.count(signature) == owner.count(walk) == 1
    section = owner[owner.index(signature):owner.index(walk)]
    assert "size == 0 || gpu_addr >= address_space_size" in section
    assert "size > address_space_size - gpu_addr" in section
print("P1_2_NATIVE_SPARSE_RANGE_SOURCE_PASS guards_before_unmap=1 guards_before_readwalk=1")
