#!/usr/bin/env python3
"""Test the real shared Vulkan Compute descriptor walker without a PS5 build."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor/encore-active/eden-vulkan"
HEADER = VENDOR / "include/video_core/renderer_vulkan/vk_compute_storage_layout.h"
CPP = (VENDOR / "vk_compute_pipeline_cost.cpp").read_text()
GENERATOR = (ROOT / "tools/prepare-vulkan-port.py").read_text()
assert HEADER.exists(), "pinned vendor lacks shared Compute storage layout"
assert CPP.count("ComputeStorageLayout::ForEach(") == 3
assert "ASSERT(desc.count == 1)" not in CPP
assert "const u32 max_storage_slots = num_descriptor_entries > 32" in CPP
assert CPP.count("max_storage_slots,") == 2
assert "max_storage_slots" in GENERATOR
assert '#include "video_core/renderer_vulkan/vk_compute_storage_layout.h"' in CPP
assert "ComputeStorageLayout::ForEach(" in GENERATOR
assert CPP.index("const auto valid_storage_layout =") < CPP.index("guest_descriptor_queue.Acquire(")
assert "resources.storage_buffers[index].is_written == writable" in CPP
SOURCE = r"""
#include <array>
#include <cassert>
#include <cstdint>
#include <limits>
#include <vector>
#include "video_core/renderer_vulkan/vk_compute_storage_layout.h"
struct Desc {
    std::uint32_t cbuf_index;
    std::uint32_t cbuf_offset;
    std::uint32_t count;
    bool is_written;
};
struct Binding {
    std::uint32_t flat, bank, offset;
    bool written;
};
int main() {
    using Vulkan::ComputeStorageLayout::ForEach;
    const std::array<Desc, 2> descriptors{{
        {1, 0x10, 1, false},
        {5, 0x20, 3, true},
    }};
    std::vector<Binding> bindings;
    auto collect = [&](auto flat, auto bank, auto offset, auto written) {
        bindings.push_back({flat, bank, offset, written});
        return true;
    };
    assert(ForEach(descriptors, 4, collect));
    assert(bindings.size() == 4);
    assert(bindings[0].flat == 0 && bindings[0].bank == 1 &&
           bindings[0].offset == 0x10 && !bindings[0].written);
    assert(bindings[1].flat == 1 && bindings[1].bank == 5 &&
           bindings[1].offset == 0x20 && bindings[1].written);
    assert(bindings[2].flat == 2 && bindings[2].offset == 0x30);
    assert(bindings[3].flat == 3 && bindings[3].offset == 0x40);
    std::size_t visited{};
    assert(!ForEach(descriptors, 3, [&](auto,auto,auto,auto) {
        ++visited; return true;
    }));
    assert(visited == 1); // Caller preflights before mutating guest binding.
    const std::array<Desc,1> zero{{{0,0,0,false}}};
    assert(!ForEach(zero, 32, collect));
    const std::array<Desc,1> unaligned{{{0,2,1,false}}};
    assert(!ForEach(unaligned, 32, collect));
    const std::array<Desc,1> overflow{{{0,0xfffffff0u,2,false}}};
    assert(!ForEach(overflow, 32, collect));
    const std::array<Desc,1> huge{{{0,0,0xffffffffu,false}}};
    assert(!ForEach(huge, 32, collect));
    // Last complete 16-byte descriptor, without wrapping the CBUF offset.
    const std::array<Desc,1> boundary{{{7,0xfffffff0u,1,false}}};
    assert(ForEach(boundary, 1, [](auto f, auto b, auto o, bool w) {
        return f == 0 && b == 7 && o == 0xfffffff0u && !w;
    }));
    const std::array<Desc,1> off_by_one{{{7,0xfffffffcu,2,false}}};
    assert(!ForEach(off_by_one, 2, collect));
    // The first word can fit in the 32-bit CBUF index while the rest of
    // the 16-byte SSBO descriptor overflows. Both generations must reject
    // this reflection BEFORE touching BufferCache or guest CBUF state.
    const std::array<Desc,1> partial_tail{{{7,0xfffffff4u,1,false}}};
    assert(!ForEach(partial_tail, 1, collect));
    const std::array<Desc,1> last_word_only{{{7,0xfffffffcu,1,false}}};
    assert(!ForEach(last_word_only, 1, collect));
    const std::array<Desc,1> tail_count_overflow{{{7,0xfffffff0u,2,false}}};
    assert(!ForEach(tail_count_overflow, 2, collect));
    // Fail-closed callbacks (e.g. mismatched QMD3 reflection or write flag).
    assert(!ForEach(descriptors, 4, [](auto f, auto, auto, auto) {
        return f < 2;
    }));
    assert(ForEach(std::array<Desc,0>{}, 0, collect));
}
"""
for tool in ("clang++", "g++"):
    compiler = shutil.which(tool)
    if not compiler:
        continue
    for optimization in ("-O0", "-O2"):
        with tempfile.TemporaryDirectory(prefix="eden-compute-layout-") as tmp:
            source = Path(tmp) / "test.cpp"
            binary = Path(tmp) / "test"
            source.write_text(SOURCE)
            subprocess.run(
                [compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                 optimization, "-I", str(VENDOR / "include"),
                 str(source), "-o", str(binary)],
                check=True, timeout=40,
            )
            subprocess.run([str(binary)], check=True, timeout=10)
        print(f"ENCORE_SHARED_COMPUTE_STORAGE_LAYOUT_PASS {tool} {optimization}")
