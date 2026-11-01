#!/usr/bin/env python3
"""Host regression for native memory GetSpan's exclusive-end page boundary.

Compile the actual two pinned GetSpan methods as the negative control and
both complete maintained native C++ sources as positive controls. No console build.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
memory = (root / "vendor/sources/eden/src/core/memory.cpp").read_text()
cmake = (root / "headless/CMakeLists.txt").read_text()
workflow = (root / ".github/workflows/encore-core-preflight.yml").read_text()

begin = "    [[nodiscard]] inline const u8* GetSpan("
end = "    bool WriteBlockImpl("
assert memory.count(begin) == 1 and memory.count(end) == 1
methods = begin + memory.split(begin, 1)[1].split(end, 1)[0]
old = (
    "        return (current_page_table->entries[addr >> YUZU_PAGEBITS].Block() "
    "== current_page_table->entries[(addr + size) >> YUZU_PAGEBITS].Block()) "
    "? GetPointerSilent(addr) : nullptr;"
)
assert methods.count(old) == 2
native_source = (root/"vendor/encore-active/eden-core/src/core/memory_native_standard.cpp").read_text()
a32_source = (root/"vendor/encore-active/eden-core/src/core/memory_native_a32.cpp").read_text()
assert 'memory_native_standard.cpp' in cmake and 'memory_native_a32.cpp' in cmake
assert 'write_derived("${eden_native_memory_tu}"' not in cmake
for unit in (native_source, a32_source):
    # The 27d087f crash hit ZeroBlock -> WalkBlock before SetCurrentPageTable.
    # Both runtime-selected implementations must fail closed, never deref null.
    assert unit.count("if (current_page_table == nullptr ||") == 1
    assert unit.count("!AddressSpaceContains(*current_page_table, addr, size)) {") == 1
assert native_source.count(begin) == a32_source.count(begin) == 1
maintained_methods = begin + native_source.split(begin,1)[1].split(end,1)[0]
a32_methods = begin + a32_source.split(begin,1)[1].split(end,1)[0]
assert maintained_methods == a32_methods, "native GetSpan must not vary by A32 profile"
assert maintained_methods.count("if (size == 0 || addr + (size - 1) < addr)") == 2
assert maintained_methods.count("start_page >= entries.size() || end_page >= entries.size()") == 2
assert old not in maintained_methods
assert "python3 -B tools/check-native-guest-span-host.py" in workflow

cpp = r"""
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
using VAddr = std::uint64_t;
using u8 = std::uint8_t;
static constexpr auto YUZU_PAGEBITS = 12;
struct Entry {
    int block{};
    int Block() const { return block; }
};
struct PageTable {
    std::array<Entry, 2> entries{};
};
struct MemoryFixture {
    PageTable* current_page_table{};
    u8 dummy{};
    u8* GetPointerSilent(VAddr) const {
        return const_cast<u8*>(&dummy);
    }
@@METHODS@@
};
int main(int argc, char**) {
    PageTable pages;
    pages.entries[0].block = 11;
    pages.entries[1].block = 22;
    MemoryFixture fixture{&pages};
    const MemoryFixture& read = fixture;
    if (argc > 2) {
        // The pinned final page probes a non-existent following entry.
        (void)fixture.GetSpan(4096, 4096);
        return 0; // Checked std::array indexing must abort.
    }
    if (argc > 1) {
        // At exact end of page 0, original code consults page 1.
        assert(fixture.GetSpan(0, 4096) == nullptr);
        assert(read.GetSpan(0, 4096) == nullptr);
        return 0;
    }
    assert(fixture.GetSpan(0, 4096) != nullptr);
    assert(read.GetSpan(0, 4096) != nullptr);
    assert(fixture.GetSpan(4096, 4096) != nullptr);
    assert(read.GetSpan(4096, 4096) != nullptr);
    assert(fixture.GetSpan(4095, 1) != nullptr);
    assert(read.GetSpan(4095, 1) != nullptr);
    assert(fixture.GetSpan(4095, 2) == nullptr);
    assert(read.GetSpan(4095, 2) == nullptr);
    assert(fixture.GetSpan(0, 0) == nullptr);
    assert(read.GetSpan(0, 0) == nullptr);
    assert(fixture.GetSpan(8192, 1) == nullptr);
    assert(read.GetSpan(8192, 1) == nullptr);
    assert(fixture.GetSpan(UINT64_MAX, 2) == nullptr);
    assert(read.GetSpan(UINT64_MAX, 2) == nullptr);
}
"""
clang = shutil.which("clang++-18") or shutil.which("clang++")
assert clang, "Clang C++20 required"
with tempfile.TemporaryDirectory(prefix="encore-guest-span-") as tmp:
    work = Path(tmp)
    for label, text, negative in (
        ("pinned", methods, True),
        ("native", maintained_methods, False),
    ):
        source = work / (label + ".cpp")
        binary = work / label
        source.write_text(cpp.replace("@@METHODS@@", text))
        subprocess.run(
            [clang, "-std=c++20", "-O1", "-g", "-Wall", "-Wextra",
             "-Werror", "-D_GLIBCXX_ASSERTIONS", "-fsanitize=address,undefined",
             "-fno-sanitize-recover=all", str(source), "-o", str(binary)],
            check=True, timeout=45
        )
        command = [str(binary)] + (["--pinned"] if negative else [])
        subprocess.run(command, check=True, timeout=45)
        if negative:
            beyond = subprocess.run(
                [str(binary), "--pinned", "--past-last"], capture_output=True,
                text=True, timeout=45
            )
            assert beyond.returncode != 0, "Pinned last-page overrun was not caught"
            assert ("Assertion" in beyond.stderr or "out of range" in beyond.stderr
                    or "runtime error" in beyond.stderr), beyond.stderr
print("NATIVE_GUEST_SPAN_HOST_PASS original_exact_boundary_false_negative=1 native_const_mutable=2 original_last_page_checked_abort=1 last_page=1 crossing=1 zero=1 overflow=1 out_of_bounds=1")
