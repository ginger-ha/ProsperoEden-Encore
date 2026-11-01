#!/usr/bin/env python3
"""F07 P0.1/P0.2: foreground graphics/compute shader translation excludes optional optimization.

Extract the actual PS5 native RAII scope from the Vulkan pipeline cache and
compile it at O0/O2. Exercise cold foreground, disk-prewarm exclusion, nested
foreground, exception unwind and early return. No PS5 performance claim.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "vendor/encore-active/eden-vulkan/vk_pipeline_cache_cost.cpp").read_text()
compute = (root / "vendor/encore-active/eden-vulkan/vk_compute_pipeline_cost.cpp").read_text()
graphics = (root / "vendor/encore-active/eden-vulkan/vk_graphics_pipeline_cost.cpp").read_text()
generator = (root / "tools/prepare-vulkan-port.py").read_text()

scope_start = "struct ComputeTranslationPriorityScope {"
graphics_scope_start = "struct GraphicsTranslationPriorityScope {"
scope_end = "\n};"
assert source.count(scope_start) == source.count(graphics_scope_start) == 1
compute_start = source.index(scope_start)
graphics_start = source.index(graphics_scope_start)
scope = source[compute_start:source.index(scope_end, compute_start) + len(scope_end)]
graphics_scope = source[graphics_start:source.index(scope_end, graphics_start) + len(scope_end)]
assert compute_start < graphics_start
assert "#endif\nusing Shader::Backend::SPIRV::EmitSPIRV;" in source[graphics_start:]
assert scope.count("pending_first_use_compute_builds.fetch_add(1, std::memory_order_release)") == 1
assert scope.count("pending_first_use_compute_builds.fetch_sub(1, std::memory_order_release)") == 1
method_start = "    PipelineStatistics* statistics, bool build_in_parallel) try {"
method_end = "    auto hash = key.Hash();\n    if (device.HasBrokenCompute()) {"
assert source.count(method_start) == 1
fragment = source[source.index(method_start) + len(method_start):source.index(method_end, source.index(method_start))]
assert "ComputeTranslationPriorityScope translation_priority{build_in_parallel};" in fragment
# MKW 5fdcbff: preserve the Vulkan driver's subgroup choice unless the
# guest shader actually observes lane-level/warp semantics. The PS5-derived
# renderer must agree with the pinned generator, leaving NS1 source intact.
warp_policy = ("device.IsExtSubgroupSizeControlSupported() && uses_warp_ops "
               "? &subgroup_size_ci : nullptr")
assert compute.count(warp_policy) == 1
assert generator.count(warp_policy) == 1
for flag in ("uses_subgroup_vote", "uses_subgroup_invocation_id",
             "uses_subgroup_shuffles", "uses_subgroup_mask",
             "uses_quad_shuffles", "uses_fswzadd"):
    assert f"info.{flag}" in compute and f"info.{flag}" in generator
assert "device.IsExtSubgroupSizeControlSupported() ? &subgroup_size_ci : nullptr" not in compute
assert "pending_first_use_compute_builds{0};" in compute
assert "pending_first_use_compute_builds.load(std::memory_order_acquire)" in graphics
assert "F07 foreground compute shader translation scope" in generator
assert "F07 compute CFG IR SPIRV fairness before driver queue" in generator
assert "std::atomic<unsigned> pending_first_use_compute_builds{0};" not in source
assert "std::atomic<unsigned> pending_first_use_graphics_builds{0};" not in source
assert "std::atomic<unsigned> pending_first_use_graphics_builds{0};" in graphics
assert "extern std::atomic<unsigned> pending_first_use_graphics_builds;" in source
assert "pending_first_use_graphics_builds.load(std::memory_order_acquire)" in graphics
assert graphics_scope.count("pending_first_use_graphics_builds.fetch_add(1, std::memory_order_release)") == 1
assert graphics_scope.count("pending_first_use_graphics_builds.fetch_sub(1, std::memory_order_release)") == 1
assert "F07 graphics translation observes first-use worker counter" in generator
assert "F07 graphics shader translation priority scope" in generator
assert "F07 graphics environment first-use priority before shader translation" in generator
assert "F07 compute environment first-use priority before shader translation" in generator
# Runtime entrypoints reserve before reading the guest shader environment or
# resetting pools. Inner scopes stay active throughout CFG/IR/SPIR-V.
outer_gfx = source[source.index("std::unique_ptr<GraphicsPipeline> PipelineCache::CreateGraphicsPipeline() {"):
                   source.index("std::unique_ptr<ComputePipeline> PipelineCache::CreateComputePipeline(")]
assert outer_gfx.count("GraphicsTranslationPriorityScope first_use_preparation_priority{") == 1
assert outer_gfx.index("GraphicsTranslationPriorityScope first_use_preparation_priority{") < outer_gfx.index("GetGraphicsEnvironments(environments")
assert outer_gfx.index("GraphicsTranslationPriorityScope first_use_preparation_priority{") < outer_gfx.index("main_pools.ReleaseContents()")
assert "::Eden::DevVulkan::fast_first_pipelines" in outer_gfx
outer_cmp = source[source.index("std::unique_ptr<ComputePipeline> PipelineCache::CreateComputePipeline("):
                   source.index("std::unique_ptr<ComputePipeline> PipelineCache::CreateComputePipeline(\n    ShaderPools& pools")]
assert outer_cmp.count("ComputeTranslationPriorityScope first_use_preparation_priority{true};") == 1
assert outer_cmp.index("ComputeTranslationPriorityScope first_use_preparation_priority{true};") < outer_cmp.index("ComputeEnvironment env{")
assert outer_cmp.index("ComputeTranslationPriorityScope first_use_preparation_priority{true};") < outer_cmp.index("main_pools.ReleaseContents()")
assert "F07 reserve graphics translation before CFG IR SPIRV" in generator
graphics_method_start = "    bool build_in_parallel) try {\n#ifdef PS5_NATIVE\n    // The optional optimizer"
graphics_method_end = "    auto hash = key.Hash();\n    LOG_DEBUG(Render_Vulkan, \"{:#016x}\", hash);"
assert source.count(graphics_method_start) == source.count(graphics_method_end) == 1
graphics_fragment = source[source.index(graphics_method_start):source.index(graphics_method_end, source.index(graphics_method_start))]
assert "GraphicsTranslationPriorityScope translation_priority{" in graphics_fragment
assert "build_in_parallel && ::Eden::DevVulkan::fast_first_pipelines" in graphics_fragment
assert source.index("GraphicsTranslationPriorityScope translation_priority") < source.index(
    "Shader::Maxwell::Flow::CFG cfg(env, pools.flow_block, cfg_offset, index == 0);",
    source.index(graphics_method_start))

assert source.index("ComputeTranslationPriorityScope translation_priority") < source.index(
    "Shader::Maxwell::Flow::CFG cfg{env, pools.flow_block, env.StartAddress()};"
)

cpp = r"""
#include <atomic>
#include <cassert>
#include <stdexcept>
namespace Vulkan {
std::atomic<unsigned> pending_first_use_compute_builds{0};
std::atomic<unsigned> pending_first_use_graphics_builds{0};
namespace {
""" + scope + "\n" + graphics_scope + r"""
}
void Check(bool foreground, bool fail) {
    const unsigned before = pending_first_use_compute_builds.load(std::memory_order_acquire);
    ComputeTranslationPriorityScope translation_priority{foreground};
    assert(pending_first_use_compute_builds.load(std::memory_order_acquire) ==
           before + (foreground ? 1u : 0u));
    if (fail) throw std::runtime_error("shader translation failed");
}
void CheckGraphics(bool in_parallel, bool fast_first, bool fail) {
    const unsigned before = pending_first_use_graphics_builds.load(std::memory_order_acquire);
    GraphicsTranslationPriorityScope translation_priority{in_parallel && fast_first};
    assert(pending_first_use_graphics_builds.load(std::memory_order_acquire) ==
           before + (in_parallel && fast_first ? 1u : 0u));
    if (fail) throw std::runtime_error("graphics shader CFG/IR translation failed");
}
void CheckInterleaved() {
    ComputeTranslationPriorityScope compute_priority{true};
    assert(pending_first_use_compute_builds.load()==1);
    GraphicsTranslationPriorityScope graphics_priority{true};
    assert(pending_first_use_graphics_builds.load()==1);
    Check(true, false);
    CheckGraphics(true, true, false);
    assert(pending_first_use_graphics_builds.load()==1);
    assert(pending_first_use_compute_builds.load()==1);
}
void CheckNested() {
    ComputeTranslationPriorityScope translation_priority{true};
    assert(pending_first_use_compute_builds.load(std::memory_order_acquire) == 1);
    Check(false, false);
    assert(pending_first_use_compute_builds.load(std::memory_order_acquire) == 1);
    Check(true, false);
    assert(pending_first_use_compute_builds.load(std::memory_order_acquire) == 1);
    ComputeTranslationPriorityScope extra{true};
    assert(pending_first_use_compute_builds.load(std::memory_order_acquire) == 2);
}
}
int main() {
    using namespace Vulkan;
    for (int i = 0; i < 200; ++i) {
        Check(false, false);
        assert(pending_first_use_compute_builds.load() == 0);
        Check(true, false);
        assert(pending_first_use_compute_builds.load() == 0);
        try { Check(true, true); }
        catch (const std::runtime_error&) {}
        assert(pending_first_use_compute_builds.load() == 0);
        CheckNested();
        assert(pending_first_use_compute_builds.load() == 0);
        CheckGraphics(false, true, false);     // disk preload
        CheckGraphics(true, false, false);     // dev optimizer disabled
        CheckGraphics(true, true, false);      // foreground graphics first use
        assert(pending_first_use_graphics_builds.load() == 0);
        try { CheckGraphics(true, true, true); }
        catch (const std::runtime_error&) {}
        assert(pending_first_use_graphics_builds.load() == 0);
        CheckInterleaved();
        assert(pending_first_use_compute_builds.load() == 0);
        assert(pending_first_use_graphics_builds.load() == 0);
    }
}
"""
compiler = shutil.which("clang++-18") or shutil.which("clang++") or shutil.which("g++")
assert compiler, "C++20 compiler required"
with tempfile.TemporaryDirectory(prefix="eden-f07-compute-translation-") as d:
    source_file = Path(d) / "translation.cpp"
    source_file.write_text(cpp)
    for opt in ("-O0", "-O2"):
        exe = Path(d) / ("translation" + opt[1:])
        built = subprocess.run(
            [compiler, "-std=c++20", opt, "-Wall", "-Wextra", "-Werror",
             "-fsanitize=undefined", "-fno-sanitize-recover=all",
             str(source_file), "-o", str(exe)],
            capture_output=True, text=True, timeout=45)
        assert built.returncode == 0, (opt, built.stderr[-5000:])
        result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, (opt, result.stdout, result.stderr[-5000:])
print("F07_GRAPHICS_COMPUTE_TRANSLATION_PRIORITY_PASS runtime=1 disk_preload=0"
      " exception_unwind=1 nested=1 graphics_first_use=1 O0=1 O2=1")
