#!/usr/bin/env python3
"""P1.2: compile the real shared native GPU scalar helper with Clang/GCC.

No PS5 SDK, console, ROMs or synthetic application build. The actual
maintained GPU MemoryManager owner must call the same tested helper.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "vendor/encore-active/eden-core/src/video_core"
OWNER = (BASE / "memory_manager.cpp").read_text()
HEADER = (BASE / "native_paged_scalar.h").read_text()
assert '#include "native_paged_scalar.h"' in OWNER
assert "Eden::GpuScalar::Read(addr, value," in OWNER
assert "Eden::GpuScalar::Write(addr, data," in OWNER
read = OWNER.split("T MemoryManager::Read(GPUVAddr addr) const {", 1)[1].split(
    "template <typename T>", 1
)[0]
write = OWNER.split("void MemoryManager::Write(GPUVAddr addr, T data) {", 1)[1].split(
    "template u8 MemoryManager::Read<u8>", 1
)[0]
assert "std::memcpy(&value, page_pointer, sizeof(T));" not in read
assert "std::memcpy(page_pointer, &data, sizeof(T));" not in write
assert HEADER.count("const auto* second = tail_bytes ?") == 1
assert HEADER.count("auto* second = tail_bytes ?") == 2
assert "if (!first || !second)" in HEADER
# One-byte accesses cannot cross a page; GCC O2 must not instantiate
# a memcpy from bytes + first_bytes on a 1-byte stack source.
assert HEADER.count("if constexpr (sizeof(T) > 1)") == 2

# Large native GPU transfers retain their efficient contiguous memcpy, but
# only when the ACTUAL device-memory continuity owner approves the full span.
# A GPU big-page hint alone is not enough after physical remapping.
block = OWNER.split("void MemoryManager::ReadBlockImpl(", 1)[1].split(
    "void MemoryManager::WriteBlock(", 1
)[0]
assert block.count("memory.GetSpan(dev_addr_base, copy_amount)") == 4
assert block.count("memory.ReadBlockUnsafe(dev_addr_base, dest_buffer, copy_amount);") == 2
assert block.count("memory.WriteBlockUnsafe(dev_addr_base, src_buffer, copy_amount);") == 2
assert "memory.GetPointer<u8>(dev_addr_base)" not in block
assert block.count("IsBigPageContinuous(page_index)") == 2
print("GPU_BLOCK_DEVICE_CONTINUITY_OWNER_PASS fast=4 fallback=4")

TEST = r"""
#include <array>
#include <cassert>
#include <cstdint>
#include <limits>
#include "native_paged_scalar.h"

using std::uint8_t;
using std::uint16_t;
using std::uint32_t;
using std::uint64_t;
using Eden::GpuScalar::Read;
using Eden::GpuScalar::Write;

int main() {
    constexpr uint64_t base = 0x300000;
    constexpr uint64_t page = 4096;
    std::array<uint8_t, page> left{}, right{};
    auto mapped = [&](uint64_t addr) -> uint8_t* {
        if (addr >= base && addr < base + page)
            return left.data() + (addr - base);
        if (addr >= base + page && addr < base + 2 * page)
            return right.data() + (addr - base - page);
        return nullptr;
    };
    for (uint64_t offset = 4089; offset < 4096; ++offset) {
        left.fill(0xa5);
        right.fill(0x5a);
        const uint64_t expected = 0x1122334455667788ULL + offset;
        assert(Write(base + offset, expected, mapped));
        uint64_t actual = 0;
        assert(Read(base + offset, actual, mapped));
        assert(actual == expected);
        assert(left[0] == 0xa5 && right.back() == 0x5a);
        const uint64_t first = page - offset;
        assert(left[offset - 1] == 0xa5);
        if (first < sizeof(expected))
            assert(right[sizeof(expected) - first] == 0x5a);
    }

    // All scalar widths, including the first byte of a new guest page.
    assert(Write(base + 1, uint8_t{0x91}, mapped));
    uint8_t c = 0;
    assert(Read(base + 1, c, mapped) && c == 0x91);
    // The very last byte of a physical page is still one scalar byte.
    // Translation must happen ONCE, never touch the next page or create
    // an impossible fortified source overread in the optimized compiler.
    unsigned u8_translations = 0;
    auto final_byte = [&](uint64_t address) -> uint8_t* {
        ++u8_translations;
        return address == base + page - 1 ? &left.back() : nullptr;
    };
    right.front() = 0x5a;
    assert(Write(base + page - 1, uint8_t{0xe3}, final_byte));
    uint8_t last_byte = 0;
    assert(Read(base + page - 1, last_byte, final_byte) && last_byte == 0xe3);
    assert(u8_translations == 2 && right.front() == 0x5a);
    assert(Write(base + page - 1, uint16_t{0xabcd}, mapped));
    uint16_t s = 0;
    assert(Read(base + page - 1, s, mapped) && s == 0xabcd);
    assert(Write(base + page - 2, uint32_t{0x12345678}, mapped));
    uint32_t n = 0;
    assert(Read(base + page - 2, n, mapped) && n == 0x12345678);

    // The second page vanishes after the first was resolved. No partial
    // writes and no guessed linear dereference into the first host array.
    auto only_first = [&](uint64_t address) -> uint8_t* {
        return address < base + page ? mapped(address) : nullptr;
    };
    left.fill(0x7d);
    uint64_t v = 0;
    assert(!Write(base + page - 3, uint64_t{0xfedcba9876543210ULL}, only_first));
    assert(left[page - 1] == 0x7d && left[page - 3] == 0x7d);
    v = 0xdeadbeef;
    assert(!Read(base + page - 3, v, only_first) && v == 0);

    // Guest address arithmetic must not wrap and translate page zero.
    int calls = 0;
    auto counted = [&](uint64_t addr) -> uint8_t* {
        ++calls;
        return mapped(addr);
    };
    const uint64_t over = (std::numeric_limits<uint64_t>::max)() - 3;
    assert(!Write(over, uint64_t{17}, counted) && calls == 0);
    v = 123;
    assert(!Read(over, v, counted) && v == 0 && calls == 0);
    // Empty mapping refuses scalar admission instead of touching a sentinel.
    assert(!Write(0, uint32_t{1}, mapped));
    return 0;
}
"""
compilers = [p for name in ("clang++", "g++") if (p := shutil.which(name))]
assert compilers, "Clang/GCC host C++20 toolchain missing"
with tempfile.TemporaryDirectory(prefix="encore-gpu-scalar-") as tmp:
    directory = Path(tmp)
    src = directory / "paged_gpu_scalar.cpp"
    src.write_text(TEST)
    for compiler in compilers:
        for level in (0, 2):
            exe = directory / f"{Path(compiler).name}-O{level}"
            command = [
                compiler, "-std=c++20", f"-O{level}", "-Wall", "-Wextra",
                "-Werror", "-fsanitize=undefined", "-fno-sanitize-recover=all",
                "-I", str(BASE), str(src), "-o", str(exe)
            ]
            built = subprocess.run(command, capture_output=True, text=True, timeout=45)
            assert built.returncode == 0, (command, built.stderr[-4000:])
            ran = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            assert ran.returncode == 0, (command, ran.stderr[-4000:])
            print("P1_2_GPU_PAGED_SCALAR_HOST_PASS", Path(compiler).name, level)
