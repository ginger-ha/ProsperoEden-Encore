#!/usr/bin/env python3
"""Source-extracted F01 descriptor capacity parity and shader-reselection regression.

Compile the actual generated PreflightExactGuestDraw method together with
all six maintained Switch 1 graphics/compute reselect checks. Also guard the
separate experimental NS2 Compute preflight before its cache lock.
Compare with the old >1024-only helper on a near-full queue. No PS5 FPS claim is implied.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
generator = (root / "tools/prepare-vulkan-port.py").read_text()
native = (root / "vendor/encore-active/eden-vulkan/vulkan_rasterizer.cpp").read_text()
upstream = (root / "vendor/sources/eden/src/video_core/renderer_vulkan/vk_update_descriptor.cpp").read_text()
assert "if (used + reserve >= frame_payload_size)" in upstream
assert "required_entries > 0 ? required_entries : DEFAULT_REQUIRED_ENTRIES" in upstream

signature = ("    template <typename WaitWorker>\n"
             "    [[nodiscard]] bool PreflightExactGuestDraw(")
assert generator.count(signature) == 1
start = generator.index(signature)
end = generator.index("\n    }\n#endif", start) + len("\n    }")
helper = generator[start:end]
header = (root / "vendor/encore-active/eden-vulkan/include/video_core/renderer_vulkan/vk_update_descriptor.h").read_text()
assert helper in header, "Native maintained header has a stale exact helper"
initial_signature = ("    template <typename WaitWorker>\n"
                     "    [[nodiscard]] bool PreflightGuestDraw(")
assert generator.count(initial_signature) == 1
initial_start = generator.index(initial_signature)
initial_end = generator.index("\n    }\n    template <typename WaitWorker>", initial_start) + len("\n    }")
initial = generator[initial_start:initial_end]
assert initial in header, "Native maintained header has a stale first preflight"
assert "required_entries != 0 ? required_entries : 0x400" in initial
assert "if (used + reserve < frame_payload_size)" in initial
assert native.count("guest_descriptor_queue.PreflightGuestDraw([this] { scheduler.WaitWorker(); },") == 2
assert generator.count("guest_descriptor_queue.PreflightGuestDraw([this] { scheduler.WaitWorker(); },") == 2
assert "if (entries == 0 || entries >= frame_payload_size)" in helper
assert "if (used + entries < frame_payload_size)" in helper
assert "payload_cursor = payload_start;" in helper
prior = helper.replace("PreflightExactGuestDraw", "OldLargePreflightDraw", 1)
before = "if (entries == 0 || entries >= frame_payload_size)"
after = "if (entries <= 0x400 || entries >= frame_payload_size)"
assert prior.count(before) == 1
prior = prior.replace(before, after)

graphics_start = native.index("void RasterizerVulkan::PrepareDraw(")
compute_start = native.index("void RasterizerVulkan::DispatchCompute(")
graphics = native[graphics_start:compute_start]
compute = native[compute_start:]
loop_tag = "for (unsigned preflight = 0; preflight != 2; ++preflight) {"
check_tag = ("if (pipeline->HasDescriptorEntries() &&\n"
             "            guest_descriptor_queue.PreflightExactGuestDraw(")
# Six original graphical/Maxwell-compute reselect checks are invariant.
# The seventh checked-in call belongs ONLY to the authenticated NS2 QMD3
# dispatch and must execute before buffer_cache.mutex is acquired.
native_start = native.index("bool RasterizerVulkan::DispatchNativeCompute(")
native_end = native.index("void RasterizerVulkan::DispatchCompute(", native_start)
native_compute = native[native_start:native_end]
assert native.count("PreflightExactGuestDraw(") == 7
assert native_compute.count("PreflightExactGuestDraw(") == 1
assert native_compute.index("PreflightExactGuestDraw(") < native_compute.index(
    "std::scoped_lock lock{buffer_cache.mutex};")
assert "if (!registry.IsComputeCurrent(kepler_compute, *ticket))" in native_compute
native_preflight_start = native_compute.index("const auto preflight_guest = [&] {")
native_preflight_end = native_compute.index(
    "        if (pipeline->CanUseDescriptorBuffer()", native_preflight_start)
native_preflight_block = native_compute[native_preflight_start:native_preflight_end]
assert native_preflight_block.count("PreflightExactGuestDraw(") == 1
assert native_preflight_block.count("if (preflight_guest())") == 1
assert "gpu_memory->FlushCaching();" in native_preflight_block
assert native.count("if (!pipeline->HasDescriptorEntries() ||") == 2
assert native.count(check_tag) == 4
assert "PreflightLargeGuestDraw(" not in native
assert generator.count("PreflightExactGuestDraw(") == 8
assert "U96 native compute preflights GPU worker waits before BufferCache lock" in generator

def extract(source, start, open_brace):
    depth = 0
    for pos in range(open_brace, len(source)):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0:
                return source[start:pos + 1]
    raise AssertionError("Unbalanced source method")

def loop(source):
    assert source.count(loop_tag) == 1
    start = source.index(loop_tag)
    return extract(source, start, source.index("{", start))

def branches(source):
    assert source.count(check_tag) == 2
    out = []
    at = 0
    while (start := source.find(check_tag, at)) >= 0:
        # Skip lambda braces in the callback argument.
        marker = source.index("DescriptorEntryReservation())) {", start)
        opening = source.index("{", marker)
        out.append(extract(source, start, opening))
        at = opening + 1
    return out

gl, cl = loop(graphics), loop(compute)
gb, cb = branches(graphics), branches(compute)
for block in [gl, *gb]:
    # Graphics generation inserts multiline C++ literally.
    assert block in generator, "Graphics native source drifted from generator"
for block in [cl, *cb]:
    # Compute generator uses escaped newline strings in replace clauses.
    assert block.replace("\n", r"\n") in generator, "Compute native source drifted from generator"
for block in [gl, cl, *gb, *cb]:
    assert "HasDescriptorEntries()" in block
    assert "PreflightExactGuestDraw(" in block
    assert "gpu_memory->FlushCaching()" in block

cpp = r"""
#include <cassert>
#include <cstddef>
#include <cstdio>
#include <functional>
#include <initializer_list>
namespace Eden::Performance {
    enum class GraphicsDrawDrop { NoPipeline };
    inline void RecordGraphicsDrawDrop(GraphicsDrawDrop) {}
}
struct Pipeline {
    std::size_t descriptors{};
    bool HasDescriptorEntries() const { return descriptors != 0; }
    std::size_t DescriptorEntryReservation() const {
        return descriptors != 0 ? descriptors : 0x400;
    }
};
struct Scheduler {
    int waits{};
    std::function<void()> after_wait;
    void WaitWorker() {
        ++waits;
        if (after_wait) after_wait();
    }
};
struct Queue {
    static constexpr std::size_t frame_payload_size = 4096;
    char storage[frame_payload_size]{};
    char* payload_start{storage};
    char* payload_cursor{storage};
__INITIAL_METHOD__
HELPER
OLD_HELPER
};
struct GpuMemory {
    int flushes{};
    void FlushCaching() { ++flushes; }
};
struct Cache {
    Pipeline* selected{};
    Pipeline* CurrentGraphicsPipeline() { return selected; }
    Pipeline* CurrentComputePipeline() { return selected; }
};
struct Rig {
    Pipeline empty{0}, one{1}, many{2048};
    Pipeline* pipeline{};
    bool initial_descriptor_drain{true}; // Isolated graph-loop witness starts after a real drain.
    bool initial_compute_descriptor_drain{true}; // Isolated compute-loop witness likewise.
    Queue guest_descriptor_queue;
    Scheduler scheduler;
    GpuMemory memory;
    GpuMemory* gpu_memory{&memory};
    Cache pipeline_cache;
    explicit Rig(std::size_t descriptors, std::size_t used,
                 bool switch_to_empty = false) {
        assert(used < Queue::frame_payload_size);
        pipeline = descriptors == 0 ? &empty :
                   descriptors == 1 ? &one : &many;
        pipeline_cache.selected = pipeline;
        guest_descriptor_queue.payload_cursor += used;
        if (switch_to_empty)
            scheduler.after_wait = [this] { pipeline_cache.selected = &empty; };
    }
    void GraphLoop() { GRAPH_LOOP }
    void GraphReuse() { GRAPH_REUSE }
    void GraphCapacity() { GRAPH_CAPACITY }
    void ComputeLoop() { COMPUTE_LOOP }
    void ComputeReuse() { COMPUTE_REUSE }
    void ComputeCapacity() { COMPUTE_CAPACITY }
    void NativePreflight() { NATIVE_PREFLIGHT }
};
using Method = void (Rig::*)();
void check_native_preflight() {
    // Exercise the EXACT separate QMD3 pre-lock lambda from the maintained
    // Vulkan renderer; zero bindings must not wait or flush unnecessarily.
    Rig empty(0, 4095);
    empty.NativePreflight();
    assert(empty.scheduler.waits == 0 && empty.memory.flushes == 0);
    Rig one(1, 4095);
    one.NativePreflight();
    assert(one.scheduler.waits == 1 && one.memory.flushes == 1);
    assert(one.guest_descriptor_queue.payload_cursor ==
           one.guest_descriptor_queue.payload_start);
    Rig room(1, 4000);
    room.NativePreflight();
    assert(room.scheduler.waits == 0 && room.memory.flushes == 0);
    Rig many(2048, 3500);
    many.NativePreflight();
    assert(many.scheduler.waits == 1 && many.memory.flushes == 1);
}
void check(Method method) {
    // Even a nearly exhausted guest descriptor queue must not stall on
    // shaders that produce exactly zero descriptors.
    Rig empty(0, 4095);
    (empty.*method)();
    assert(empty.scheduler.waits == 0);
    assert(empty.guest_descriptor_queue.payload_cursor ==
           empty.guest_descriptor_queue.payload_start + 4095);

    // Exact parity with upstream Acquire: one entry at the last slot needs
    // the worker drain, including after a previous unrelated worker wait
    // has published a new small-descriptor shader.
    Rig one(1, 4095, true);
    (one.*method)();
    assert(one.scheduler.waits == 1);
    assert(one.pipeline == &one.empty);
    assert(one.guest_descriptor_queue.payload_cursor ==
           one.guest_descriptor_queue.payload_start);

    // When enough room remains, no speculative worker drain should occur.
    Rig room(1, 4000);
    (room.*method)();
    assert(room.scheduler.waits == 0);
    assert(room.guest_descriptor_queue.payload_cursor ==
           room.guest_descriptor_queue.payload_start + 4000);

    Rig many(2048, 3500, true);
    (many.*method)();
    assert(many.scheduler.waits == 1);
    assert(many.pipeline == &many.empty);
}
int main() {
    // The old helper could not pre-drain <1024 descriptors even with one
    // free entry remaining. The new helper matches Acquire's exact bound.
    Queue q;
    q.payload_cursor += 4095;
    int prior_waits = 0;
    assert(!q.OldLargePreflightDraw([&] { ++prior_waits; }, 1));
    assert(prior_waits == 0);
    int exact_waits = 0;
    assert(q.PreflightExactGuestDraw([&] { ++exact_waits; }, 1));
    assert(exact_waits == 1 && q.payload_cursor == q.payload_start);

    // The first/pre-lock preflight now uses the known exact count, not
    // the conservative 1024-entry default, avoiding a premature drain.
    Queue room;
    room.payload_cursor += 4000;
    int early_waits = 0;
    assert(!room.PreflightGuestDraw([&] { ++early_waits; }, 1));
    assert(early_waits == 0);
    assert(room.PreflightGuestDraw([&] { ++early_waits; }));
    assert(early_waits == 1);
    Queue edge;
    edge.payload_cursor += 4095;
    int edge_waits = 0;
    assert(edge.PreflightGuestDraw([&] { ++edge_waits; }, 1));
    assert(edge_waits == 1 && edge.payload_cursor == edge.payload_start);
    for (Method method : {
        &Rig::GraphLoop, &Rig::GraphReuse, &Rig::GraphCapacity,
        &Rig::ComputeLoop, &Rig::ComputeReuse, &Rig::ComputeCapacity
    }) check(method);
    check_native_preflight();
    std::puts("SEVEN_NATIVE_DESCRIPTOR_PREFLIGHT_EXACT_PARITY_PASS");
}
"""
for tag, block in [
    ("OLD_HELPER", prior), ("HELPER", helper),
    ("GRAPH_LOOP", gl), ("GRAPH_REUSE", gb[0]), ("GRAPH_CAPACITY", gb[1]),
    ("COMPUTE_LOOP", cl), ("COMPUTE_REUSE", cb[0]),
    ("COMPUTE_CAPACITY", cb[1]),
    ("NATIVE_PREFLIGHT", native_preflight_block)
]:
    # Replace the longer OLD_HELPER placeholder first; replacing HELPER
    # before it would corrupt the old-method declaration.
    assert cpp.count(tag) == 1, tag
    cpp = cpp.replace(tag, block)
assert cpp.count("__INITIAL_METHOD__") == 1
cpp = cpp.replace("__INITIAL_METHOD__", initial)
compiler = shutil.which("clang++") or shutil.which("g++") or shutil.which("c++")
assert compiler, "C++20 compiler required"
with tempfile.TemporaryDirectory(prefix="encore-exact-preflight-") as d:
    filename = Path(d) / "preflight.cpp"
    filename.write_text(cpp)
    for opt in ("-O0", "-O2"):
        exe = Path(d) / ("preflight" + opt)
        built = subprocess.run(
            [compiler, "-std=c++20", opt, "-Wall", "-Wextra", "-Werror",
             "-fsanitize=undefined", "-fno-sanitize-recover=all",
             str(filename), "-o", str(exe)],
            capture_output=True, text=True, timeout=60)
        assert built.returncode == 0, (opt, built.stderr[-5000:])
        run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
        assert run.returncode == 0, (opt, run.stdout, run.stderr[-5000:])
        assert "SEVEN_NATIVE_DESCRIPTOR_PREFLIGHT_EXACT_PARITY_PASS" in run.stdout
        print("DESCRIPTOR_PREFLIGHT_EXACT_SOURCE_PASS", opt)


# F07 V03: compile the EXACT shipping Allocate fallback body, not a
# handwritten restatement. PreflightFrameReuse may not have been called:
# a completed frame tick must not trigger scheduler.Wait under cache locks.
ring = (root / "vendor/encore-active/eden-vulkan/vk_descriptor_buffer_cost.cpp").read_text()
gen = (root / "tools/prepare-vulkan-port.py").read_text()
ring_at = ring.index("DescriptorBufferRing::Allocation DescriptorBufferRing::Allocate(")
fallback_at = ring.index("    if (frame_reused) {", ring_at)
fallback_end = ring.index("\n    if (cursor + needed > chunk_capacity)", fallback_at)
fallback = ring[fallback_at:fallback_end]
assert fallback.startswith("    if (frame_reused) {")
assert fallback.strip().endswith("}")
# Strict generator parity: the production source is the same C++ fragment
# emitted after the pinned VulkanTimer wrapper (no staging/source divergence).
gen_anchor = "        native_fallback = '''"
assert gen.count(gen_anchor) == 1
from_gen = gen.split(gen_anchor, 1)[1].split("'''", 1)[0]
assert from_gen == fallback
assert "old_tick != 0 && !scheduler.IsFree(old_tick)" in fallback
assert "scheduler.Wait(old_tick);" in fallback
assert "#else\n        { auto timer = Eden::Performance::VulkanTimer(10); scheduler.Wait(frame_ticks[frame_index]); }" in fallback
assert ring.index("PreflightFrameReuse(Scheduler& scheduler)") < ring_at
assert "old_tick == 0 || scheduler.IsFree(old_tick)" in ring[:ring_at]

fallback_cpp = r"""
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
using u64 = std::uint64_t;
namespace Eden::Performance {
struct VulkanTimer { explicit VulkanTimer(int) {} ~VulkanTimer() {} };
}
struct Scheduler {
    bool free_tick{};
    int queries{};
    int waits{};
    u64 last_wait{};
    bool IsFree(u64 tick) {
        assert(tick != 0);
        ++queries;
        return free_tick;
    }
    void Wait(u64 tick) {
        ++waits;
        last_wait = tick;
    }
};
struct Rig {
    bool frame_reused = true;
    unsigned frame_index = 0;
    std::array<u64, 1> frame_ticks{};
    void Allocate(Scheduler& scheduler) {
__ACTUAL_FALLBACK__
    }
};
int main() {
    {
        Scheduler s;
        Rig r;
        r.Allocate(s);
#ifdef PS5_NATIVE
        assert(s.waits == 0 && s.queries == 0);
#else
        assert(s.waits == 1 && s.last_wait == 0);
#endif
        assert(!r.frame_reused);
    }
    {
        Scheduler s;
        s.free_tick = true;
        Rig r;
        r.frame_ticks[0] = 17;
        r.Allocate(s);
#ifdef PS5_NATIVE
        assert(s.waits == 0 && s.queries == 1);
#else
        assert(s.waits == 1 && s.last_wait == 17);
#endif
        // Subsequent Allocate within the same frame is never waited twice.
        r.Allocate(s);
#ifdef PS5_NATIVE
        assert(s.waits == 0 && s.queries == 1);
#else
        assert(s.waits == 1);
#endif
    }
    {
        Scheduler s;
        s.free_tick = false;
        Rig r;
        r.frame_ticks[0] = 23;
        r.Allocate(s);
        assert(s.waits == 1 && s.last_wait == 23);
#ifdef PS5_NATIVE
        assert(s.queries == 1);
#else
        assert(s.queries == 0);
#endif
        assert(!r.frame_reused);
        r.Allocate(s);
        assert(s.waits == 1);
    }
    std::puts("DESCRIPTOR_RETIRED_TICK_FALLBACK_SOURCE_PASS");
}
""".replace("__ACTUAL_FALLBACK__", fallback)
with tempfile.TemporaryDirectory(prefix="encore-native-ring-fallback-") as folder:
    cpp_path = Path(folder) / "ring_fallback.cpp"
    cpp_path.write_text(fallback_cpp)
    for mode in ("native", "desktop"):
        for opt in ("-O0", "-O2"):
            exe = Path(folder) / ("ring_fallback_" + mode + "_" + opt[1:])
            cmd = [compiler, "-std=c++20", opt, "-Wall", "-Wextra",
                   "-Werror", "-fsanitize=undefined", "-fno-sanitize-recover=all"]
            if mode == "native":
                cmd += ["-DPS5_NATIVE"]
            cmd += [str(cpp_path), "-o", str(exe)]
            built = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            assert built.returncode == 0, (mode, opt, built.stderr[-5000:])
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
            assert run.returncode == 0, (mode, opt, run.stdout, run.stderr[-5000:])
            assert "DESCRIPTOR_RETIRED_TICK_FALLBACK_SOURCE_PASS" in run.stdout
            print("DESCRIPTOR_RETIRED_TICK_FALLBACK_SOURCE_PASS", mode, opt)


# F07 V03: an exhausted descriptor ring must still drain current GPU users
# before reusing memory. Compile the actual PreflightCapacity method with
# mock counters and prove a single drain, generation advance, and no drain
# for exact-fit, spare chunk, invalid or reused-frame cases.
signature_capacity = ("bool DescriptorBufferRing::PreflightCapacity(Scheduler& scheduler,\n"
                      "                                             VkDeviceSize size) {")
assert ring.count(signature_capacity) == 1
begin_capacity = ring.index(signature_capacity)
braces = 0
end_capacity = None
for index in range(ring.index("{", begin_capacity), len(ring)):
    braces += (ring[index] == "{") - (ring[index] == "}")
    if braces == 0:
        end_capacity = index + 1
        break
assert end_capacity is not None
capacity_method = ring[begin_capacity:end_capacity]
assert "scheduler.Finish();" in capacity_method
assert "++generation;" in capacity_method
assert "chunk_cursor = 0;" in capacity_method
assert "cursor = 0;" in capacity_method
assert "DescriptorRingPreflight" in capacity_method
assert "bool DescriptorBufferRing::PreflightCapacity" in gen
assert "if (chunks.empty() || frame_reused || size == 0 || !CanAllocate(size))" in gen
assert "if (needed <= chunk_capacity - cursor || chunk_cursor + 1 < chunks_per_frame)" in gen

capacity_cpp = r"""
#include <atomic>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <vector>
using u64 = std::uint64_t;
using VkDeviceSize = std::uint64_t;
namespace Common {
VkDeviceSize AlignUp(VkDeviceSize value, VkDeviceSize alignment) {
    return (value + alignment - 1) / alignment * alignment;
}
}
namespace Eden::Performance {
enum class CachePhase { DescriptorRingPreflight };
inline std::atomic<bool> detailed_gpu_profile{};
struct VulkanTimer { explicit VulkanTimer(int) {} ~VulkanTimer() {} };
struct CachePhaseTimer {
    CachePhaseTimer(CachePhase, bool) {}
    ~CachePhaseTimer() {}
};
}
struct Scheduler {
    unsigned finishes{};
    void Finish() { ++finishes; }
};
struct DescriptorBufferRing {
    std::vector<int> chunks{1};
    bool frame_reused{};
    VkDeviceSize chunk_capacity{256};
    VkDeviceSize alignment{16};
    VkDeviceSize cursor{};
    std::size_t chunk_cursor{};
    std::size_t chunks_per_frame{1};
    u64 generation{7};
    bool CanAllocate(VkDeviceSize size) const noexcept {
        return size <= chunk_capacity &&
               Common::AlignUp(size, alignment) <= chunk_capacity;
    }
    bool PreflightCapacity(Scheduler&, VkDeviceSize);
};
__CAPACITY_METHOD__
int main() {
    // The sole legal unconditional reuse happens when the last ring chunk
    // cannot hold another aligned payload. Its GPU fence must not be skipped.
    {
        Scheduler s;
        DescriptorBufferRing d;
        d.cursor = 240;
        assert(d.PreflightCapacity(s, 32));
        assert(s.finishes == 1);
        assert(d.cursor == 0 && d.chunk_cursor == 0 && d.generation == 8);
        assert(!d.PreflightCapacity(s, 32));
        assert(s.finishes == 1 && d.generation == 8);
    }
    // Exact fits, spare chunks, and wrong/zero payload requests do not drain.
    {
        Scheduler s;
        DescriptorBufferRing d;
        d.cursor = 240;
        assert(!d.PreflightCapacity(s, 16));
        assert(s.finishes == 0 && d.cursor == 240 && d.generation == 7);
        d.chunks_per_frame = 2;
        assert(!d.PreflightCapacity(s, 32));
        assert(s.finishes == 0 && d.generation == 7);
    }
    {
        Scheduler s;
        DescriptorBufferRing d;
        d.cursor = 240;
        for (const VkDeviceSize size : {VkDeviceSize{0}, VkDeviceSize{257}}) {
            assert(!d.PreflightCapacity(s, size));
        }
        assert(s.finishes == 0 && d.generation == 7);
        d.frame_reused = true;
        assert(!d.PreflightCapacity(s, 32));
        assert(s.finishes == 0 && d.generation == 7);
        d.frame_reused = false;
        d.chunks.clear();
        assert(!d.PreflightCapacity(s, 32));
        assert(s.finishes == 0 && d.generation == 7);
    }
    std::puts("DESCRIPTOR_CAPACITY_OWNER_PREFLIGHT_SOURCE_PASS");
}
""".replace("__CAPACITY_METHOD__", capacity_method)
with tempfile.TemporaryDirectory(prefix="encore-ring-capacity-") as folder:
    cpp_path = Path(folder) / "capacity.cpp"
    cpp_path.write_text(capacity_cpp)
    for opt in ("-O0", "-O2"):
        exe = Path(folder) / ("capacity_" + opt[1:])
        built = subprocess.run(
            [compiler, "-std=c++20", opt, "-Wall", "-Wextra", "-Werror",
             "-fsanitize=undefined", "-fno-sanitize-recover=all",
             str(cpp_path), "-o", str(exe)],
            capture_output=True, text=True, timeout=60)
        assert built.returncode == 0, (opt, built.stderr[-5000:])
        run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
        assert run.returncode == 0, (opt, run.stdout, run.stderr[-5000:])
        assert "DESCRIPTOR_CAPACITY_OWNER_PREFLIGHT_SOURCE_PASS" in run.stdout
        print("DESCRIPTOR_CAPACITY_OWNER_PREFLIGHT_SOURCE_PASS", opt)
