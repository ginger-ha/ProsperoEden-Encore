#!/usr/bin/env python3
"""Source-backed compute descriptor ring preflights: exact native wait and allocation logic."""
from pathlib import Path
import ast
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
active = root / "vendor/encore-active/eden-vulkan"
ring = (active / "vulkan_descriptor_buffer.cpp").read_text()
compute_pipeline = (active / "vk_compute_pipeline_cost.cpp").read_text()
compute_header = (active / "include/video_core/renderer_vulkan/vk_compute_pipeline.h").read_text()
raster = (active / "vulkan_rasterizer.cpp").read_text()
gen = (root / "tools/prepare-vulkan-port.py").read_text()
workflow = (root / ".github/workflows/encore-core-preflight.yml").read_text()
tree = ast.parse(gen)

def methods(text, needle):
    start = text.index(needle)
    opened = text.index("{", start)
    nesting = 0
    for index in range(opened, len(text)):
        if text[index] == "{": nesting += 1
        if text[index] == "}":
            nesting -= 1
            if nesting == 0:
                return text[start:index + 1]
    raise AssertionError("unterminated source method")

def adapters(path):
    result=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=="adapt":
            if len(node.args)>=3 and isinstance(node.args[0],ast.Constant) and node.args[0].value==path:
                for entry in node.args[2].elts:
                    try: result.append(ast.literal_eval(entry))
                    except (SyntaxError,ValueError,TypeError): continue
    return result

header_patches=adapters("src/video_core/renderer_vulkan/vk_compute_pipeline.h")
# The NS2 forward declaration is a separate, exact source adaptation.
# Do not mistake it for the F07 descriptor preflight replacement.
assert len(header_patches)==2 and all(len(entry)==2 for entry in header_patches)
assert header_patches[0][0] == "namespace Vulkan {"
assert "NativeQmdResourcePlan" in header_patches[0][1]
old,new=header_patches[1]
assert "bool IsBound() const noexcept" in old
assert "DescriptorRingPreflightSize() const noexcept" in new
assert "DescriptorEntryReservation() const noexcept" in new
assert "return uses_descriptor_buffer ? descriptor_buffer_layout.size : 0;" in new
assert "#ifdef PS5_NATIVE" in new
getter=methods(compute_header,"[[nodiscard]] VkDeviceSize DescriptorRingPreflightSize() const noexcept")
# The final native owner must retain the later F07 same-generation reuse
# predicate, not just the older unconditional allocation in the base adapt.
assert "last_descriptor_buffer_generation" in getter
assert "last_descriptor_payload.size() != num_descriptor_entries" in getter
reservation=methods(new,"[[nodiscard]] size_t DescriptorEntryReservation() const noexcept")
assert "descriptor_buffer_ring.Allocate(scheduler, descriptor_buffer_layout.size)" in compute_pipeline
assert "reuse_allocation" in compute_pipeline
assert "F07 compute descriptor payload fast reuse" in gen
assert "F07 compute ring reuse preflight" in gen

compute=raster.split("void RasterizerVulkan::DispatchCompute() {",1)[1].split(
    "\nvoid RasterizerVulkan::ResetCounter(",1)[0]
pair="std::scoped_lock lock{texture_cache.mutex, buffer_cache.mutex};"
assert compute.count("descriptor_buffer_ring.PreflightFrameReuse(scheduler)") == 1
assert compute.count("descriptor_buffer_ring.PreflightCapacity(") == 1
assert compute.count("guest_descriptor_queue.PreflightExactGuestDraw(") == 3
# Native compute chooses the immutable shader before a queue preflight:
# zero-entry shaders cannot reserve the fallback 1024 guest descriptors.
# A real worker drain still precedes the paired cache mutexes and reselects
# the compute shader after consuming pending guest invalidations.
select = compute.index("ComputePipeline* pipeline{pipeline_cache.CurrentComputePipeline()};")
preflight = compute.index("guest_descriptor_queue.PreflightGuestDraw(")
assert select < preflight < compute.index(pair)
assert "pipeline->HasDescriptorEntries()" in compute[select:preflight]
after_drain = compute[preflight:compute.index("#endif", preflight)]
assert "gpu_memory->FlushCaching();" in after_drain
assert "pipeline = pipeline_cache.CurrentComputePipeline();" in after_drain
assert compute.index("descriptor_buffer_ring.PreflightFrameReuse(") < compute.index(
    "descriptor_buffer_ring.PreflightCapacity(") < compute.index(pair)
assert "pipeline = pipeline_cache.CurrentComputePipeline();" in compute
between_frame_and_capacity = compute[
    compute.index("descriptor_buffer_ring.PreflightFrameReuse("):
    compute.index("descriptor_buffer_ring.PreflightCapacity(")]
assert "gpu_memory->FlushCaching();" in between_frame_and_capacity
assert "pipeline = pipeline_cache.CurrentComputePipeline();" in between_frame_and_capacity
assert "PreflightExactGuestDraw(" in between_frame_and_capacity
after_capacity=compute.split("descriptor_buffer_ring.PreflightCapacity(",1)[1].split(pair,1)[0]
assert "pipeline = pipeline_cache.CurrentComputePipeline();" in after_capacity
assert "gpu_memory->FlushCaching();" in after_capacity
assert "PreflightExactGuestDraw(" in after_capacity
assert "    if (!pipeline) return;" in after_capacity
assert compute.index("SCOPE_EXIT { SyncProbe") < compute.index(pair)
# The pinned transformation and the final native source-preserving
# rewrite both mention this guarantee. Check the compiler-selected TU
# exactly once instead of relying on a count inside the Python oracle.
assert gen.count("F07 compute preflight comment") == 1
assert compute.count("Compute reuses same-generation identical descriptor payloads.") == 1
assert "python3 -B tools/check-ps5-compute-descriptor-ring-preflight-host.py" in workflow

frame=methods(ring,"bool DescriptorBufferRing::PreflightFrameReuse(")
capacity=methods(ring,"bool DescriptorBufferRing::PreflightCapacity(")
allocation=methods(ring,"DescriptorBufferRing::Allocation DescriptorBufferRing::Allocate(")
cpp=r"""
#include <algorithm>
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <vector>
using u8 = std::uint8_t;
using u32 = std::uint32_t;
using u64 = std::uint64_t;
using VkDeviceSize = std::uint64_t;
#define ASSERT(expr) assert(expr)
#define LOG_DEBUG(...) ((void)0)
namespace Common {
template<typename T>T AlignUp(T n,T a){return (n+a-1)/a*a;}
}
static bool cache_locks_held=false;
struct Scheduler {
    u64 tick{291};
    u64 completed{};
    int waits{}, finishes{}, waits_under_lock{}, free_queries{};
    bool IsFree(u64 t) {++free_queries;return t<=completed;}
    void Wait(u64) { if (cache_locks_held) ++waits_under_lock; ++waits; }
    void Finish() { if(cache_locks_held) ++waits_under_lock; ++finishes; }
    u64 CurrentTick() const { return tick; }
};
struct DescriptorBufferRing {
    struct Allocation { u8* host{}; VkDeviceSize offset{}; u32 chunk{}; u64 generation{}; };
    bool PreflightFrameReuse(Scheduler&);
    bool PreflightCapacity(Scheduler&,VkDeviceSize);
    Allocation Allocate(Scheduler&,VkDeviceSize);
    bool CanAllocate(VkDeviceSize size) const {return Common::AlignUp(size,alignment)<=chunk_capacity;}
    u64 CurrentGeneration() const{return generation;}
    std::vector<int> chunks{1,2};
    std::array<std::array<u8,100>,2> data{};
    std::vector<u8*> chunk_hosts{data[0].data(),data[1].data()};
    std::array<u64,8> frame_ticks{};
    VkDeviceSize alignment{4},chunk_capacity{100},cursor{0};
    size_t frame_index{0},chunk_cursor{0},chunks_per_frame{2};
    u64 generation{8};
    bool frame_reused{};
};
struct Layout { VkDeviceSize size{16}; };
struct DescriptorUpdateEntry { u64 bits{}; };
struct Pipeline {
    DescriptorBufferRing& descriptor_buffer_ring;
    // Explicitly initialize the sole required dependency. Keep -Werror
    // enabled, including Clang's missing-field-initializers warning.
    explicit Pipeline(DescriptorBufferRing& ring) : descriptor_buffer_ring(ring) {}
    bool last_descriptor_buffer_valid{};
    u64 last_descriptor_buffer_generation{};
    std::vector<DescriptorUpdateEntry> last_descriptor_payload;
    bool uses_descriptor_buffer{true};
    Layout descriptor_buffer_layout{};
    size_t num_descriptor_entries{8};
__GETTER__
__RESERVATION__
};
__FRAME__
__CAPACITY__
__ALLOCATE__
int main() {
    Scheduler s;
    DescriptorBufferRing r;
    Pipeline p{r};
    assert(p.DescriptorRingPreflightSize()==16);
    p.last_descriptor_buffer_valid=true;
    p.last_descriptor_buffer_generation=r.CurrentGeneration();
    p.last_descriptor_payload.resize(p.num_descriptor_entries);
    assert(p.DescriptorRingPreflightSize()==0);
    p.last_descriptor_buffer_valid=false;
    assert(p.DescriptorEntryReservation()==8);
    // Spare capacity should not cause any early fence wait.
    assert(!r.PreflightFrameReuse(s));
    assert(!r.PreflightCapacity(s,p.DescriptorRingPreflightSize()));
    cache_locks_held=true;
    assert(r.Allocate(s,p.DescriptorRingPreflightSize()).host);
    cache_locks_held=false;
    assert(s.waits_under_lock==0&&s.waits==0&&s.finishes==0);
    // An eight-frame recycled ring waits on the previous tick, outside locks.
    r.frame_ticks[0]=128;
    r.frame_reused=true;
    assert(r.PreflightFrameReuse(s));
    assert(s.waits==1&&!r.frame_reused);
    cache_locks_held=true;
    assert(r.Allocate(s,p.DescriptorRingPreflightSize()).host);
    cache_locks_held=false;
    assert(s.waits_under_lock==0&&s.waits==1);
    // Recycled slot already completed: no wait, no forced guest shader
    // reselection. Allocations may still proceed normally.
    r.frame_reused=true;
    r.frame_ticks[0]=128;
    s.completed=128;
    assert(!r.PreflightFrameReuse(s) && s.waits==1 && !r.frame_reused);
    // No valid snapshot: full-ring allocation is guaranteed and pre-drained.
    r.chunk_cursor=1; r.cursor=96;
    assert(r.PreflightCapacity(s,p.DescriptorRingPreflightSize()));
    assert(s.finishes==1&&r.generation==9&&r.cursor==0&&r.chunk_cursor==0);
    cache_locks_held=true;
    auto allocation=r.Allocate(s,p.DescriptorRingPreflightSize());
    cache_locks_held=false;
    assert(allocation.host&&allocation.generation==9&&s.waits_under_lock==0);
    // No extension: no reservation and no early GPU fence required.
    p.uses_descriptor_buffer=false;
    assert(p.DescriptorRingPreflightSize()==0);
    assert(!r.PreflightCapacity(s,p.DescriptorRingPreflightSize()));
    // A later pipeline may use a different layout after a wait.
    p.uses_descriptor_buffer=true; p.descriptor_buffer_layout.size=40;
    assert(p.DescriptorRingPreflightSize()==40);
    assert(!r.PreflightCapacity(s,p.DescriptorRingPreflightSize()));
    // Independent pipeline capacities are tested independently.
    r.chunk_cursor=1;r.cursor=90;
    assert(r.PreflightCapacity(s,p.DescriptorRingPreflightSize()));
    cache_locks_held=true;
    assert(r.Allocate(s,p.DescriptorRingPreflightSize()).host);
    cache_locks_held=false;
    assert(s.waits_under_lock==0 && s.finishes==2);
}
""".replace("__GETTER__",getter).replace("__RESERVATION__",reservation).replace(
    "__FRAME__",frame).replace("__CAPACITY__",capacity).replace("__ALLOCATE__",allocation)
cc=shutil.which("clang++-18") or shutil.which("clang++")
assert cc, "Clang C++20 required"
with tempfile.TemporaryDirectory(prefix="encore-compute-ring-") as temp:
    src=Path(temp)/"witness.cpp";exe=Path(temp)/"witness"
    src.write_text(cpp)
    subprocess.run([cc,"-std=c++20","-O1","-Wall","-Wextra","-Werror",
                    "-fsanitize=address,undefined","-fno-sanitize-recover=all",
                    str(src),"-o",str(exe)],check=True,timeout=45)
    subprocess.run([str(exe)],check=True,timeout=30)
print("COMPUTE_DESCRIPTOR_RING_PREFLIGHT_HOST_PASS frame_fence=1 full_ring=2 no_locked_wait=1 immutable_layout=1")
