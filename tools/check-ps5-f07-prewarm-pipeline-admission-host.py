#!/usr/bin/env python3
"""PS5 F07: compile selected persisted Vulkan cache insertion guards.

A completed-but-failed synchronous prewarm must not poison the runtime cache
with a permanently unusable graphics/compute pipeline object.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
active = (root/"vendor/encore-active/eden-vulkan/vk_pipeline_cache_cost.cpp").read_text()
generator = (root/"tools/prepare-vulkan-port.py").read_text()
graphics_h = (root/"vendor/encore-active/eden-vulkan/include/video_core/renderer_vulkan/vk_graphics_pipeline.h").read_text()
compute_h = (root/"vendor/encore-active/eden-vulkan/include/video_core/renderer_vulkan/vk_compute_pipeline.h").read_text()
# Keep the full selected predicate, including delayed optimized variant publication.
# The worker's *recorded* draw binding is a distinct guard tested elsewhere.
assert "if (!is_built.load(std::memory_order::acquire)) return false;" in graphics_h
assert "optimized_ready.load(std::memory_order_acquire)" in graphics_h
assert "return static_cast<bool>(pipeline) ||" in graphics_h
ready_signature = "    [[nodiscard]] bool CanExecuteDraw() const noexcept {"
assert graphics_h.count(ready_signature) == 1
ready_method = ready_signature + graphics_h.split(ready_signature, 1)[1].split("\n    }\n", 1)[0] + "\n    }"
assert "return static_cast<bool>(pipeline);" in compute_h
assert active.count("if (pipeline && pipeline->IsBound()) {") == 1
assert active.count("if (pipeline && pipeline->CanExecuteDraw()) {") == 1
assert active.count("++state.valid;") == 2
assert "EDEN_PS5_SHADER_PREWARM queued=%zu completed=%zu valid=%zu rejected=%zu prebuild_ms=%lld limit=%zu" in active
assert active.index("    workers.WaitForRequests();\n    prewarm_drain.joined = true;\n#else\n    workers.WaitForRequests(stop_loading);") < active.index("EDEN_PS5_SHADER_PREWARM queued=")
assert "f07_warm_after_4" in generator
assert "    workers.WaitForRequests();" in generator
assert "startup_prewarm_started = std::chrono::steady_clock::now();" in active
assert "f07_prewarm_metrics_old_4" in generator
for name in ("compute","graphics"):
    assert f"shader_source.count(f07_preseed_{name}_old) != 1" in generator
    assert generator.index(f"shader_source = shader_source.replace(f07_preseed_{name}_old, f07_preseed_{name}_new, 1)") < generator.index("shader_output.write_text(shader_source)")

start_compute="            if (pipeline && pipeline->IsBound()) {"
start_graphics="#ifdef PS5_NATIVE\n            if (pipeline && pipeline->CanExecuteDraw()) {"
assert active.count(start_compute)==1 and active.count(start_graphics)==1
compute=start_compute+active.split(start_compute,1)[1].split("\n            }",1)[0]+"\n            }"
graphics=start_graphics+active.split(start_graphics,1)[1].split("\n            }",1)[0]+"\n            }"
assert "compute_cache.emplace" in compute and "graphics_cache.emplace" in graphics
cpp=r"""
#include <atomic>
#include <cassert>
#include <cstddef>
#include <memory>
#include <unordered_map>
#include <utility>
struct Pipeline {
    std::atomic_bool is_built{false};
    bool pipeline{};
    std::atomic_bool optimized_ready{false};
    explicit Pipeline(bool ready, bool handle, bool optimized = false)
        : is_built(ready), pipeline(handle), optimized_ready(optimized) {}
    bool IsBound() const noexcept { return pipeline; }
""" + ready_method + r"""
};
struct Fixture {
    struct State {std::size_t valid{};} state;
    std::unordered_map<int,std::unique_ptr<Pipeline>> compute_cache,graphics_cache;
    void AdmitCompute(int key,std::unique_ptr<Pipeline> pipeline) {
""" + compute + r"""
    }
    void AdmitGraphics(int key,std::unique_ptr<Pipeline> pipeline) {
""" + graphics + r"""
    }
};
int main() {
    Fixture f;
    f.AdmitCompute(1,std::make_unique<Pipeline>(true,false));
    assert(f.compute_cache.empty() && f.state.valid==0);
    f.AdmitCompute(1,std::make_unique<Pipeline>(true,true));
    assert(f.compute_cache.size()==1 && f.compute_cache.at(1)->IsBound());
    assert(f.state.valid==1);
    f.AdmitGraphics(2,std::make_unique<Pipeline>(true,false));
#ifdef PS5_NATIVE
    assert(f.graphics_cache.empty() && f.state.valid==1);
#else
    assert(f.graphics_cache.size()==1 && f.state.valid==2);
    f.graphics_cache.clear();
#endif
    f.AdmitGraphics(2,std::make_unique<Pipeline>(true,true));
    assert(f.graphics_cache.size()==1 && f.graphics_cache.at(2)->CanExecuteDraw());
#ifdef PS5_NATIVE
    assert(f.state.valid==2);
#else
    assert(f.state.valid==3);
#endif
    // A driver build that is not yet published must NEVER enter native
    // prewarm, even if both prospective handles happen to be valid.
    f.AdmitGraphics(3,std::make_unique<Pipeline>(false,true,true));
#ifdef PS5_NATIVE
    assert(f.graphics_cache.size()==1 && f.state.valid==2);
#else
    assert(f.graphics_cache.size()==2 && f.state.valid==4);
#endif
    // An asynchronously published optimized handle is valid native prewarm
    // even when the original driver pipeline failed. Desktop still keeps its
    // original (unconditional) admission policy.
    f.AdmitGraphics(4,std::make_unique<Pipeline>(true,false,true));
    assert(f.graphics_cache.contains(4));
#ifdef PS5_NATIVE
    assert(f.graphics_cache.at(4)->CanExecuteDraw());
    assert(f.state.valid==3);
#else
    assert(!f.graphics_cache.at(4)->CanExecuteDraw());
    assert(f.state.valid==5);
#endif
}
"""
compiler=shutil.which("clang++") or shutil.which("g++")
assert compiler, "C++ compiler required"
with tempfile.TemporaryDirectory(prefix="eden-f07-preseed-") as d:
    p=Path(d)/"test.cpp"
    p.write_text(cpp)
    for variant in ([],["-DPS5_NATIVE=1"]):
        for level in ("-O0","-O2"):
            exe=Path(d)/("run"+("ps5" if variant else "desktop")+level[1:])
            subprocess.run([compiler,"-std=c++20",level,*variant,"-Wall","-Wextra","-Werror",str(p),"-o",str(exe)],check=True,capture_output=True,text=True,timeout=35)
            subprocess.run([str(exe)],check=True,timeout=15)
print("F07_PREWARM_PIPELINE_ADMISSION_HOST_PASS native_graphics_invalid=1 compute_invalid=1 optimized_recovery=1 unpublished_rejected=1 actual_header_predicate=1 desktop=1 O0=1 O2=1")
