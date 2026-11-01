#!/usr/bin/env python3
"""C04: compile the real PS5/desktop layer-count resize decision.

No GPU hardware, PS5 FPS, or on-screen pixel freshness is asserted here.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
blit = (ROOT / "vendor/encore-active/eden-vulkan/vulkan_blit_screen.cpp").read_text()
header = (ROOT / "vendor/encore-active/eden-vulkan/include/video_core/renderer_vulkan/vk_blit_screen.h").read_text()
generator = (ROOT / "tools/prepare-vulkan-port.py").read_text()
adapt = (ROOT / "vendor/encore-active/eden-vulkan/vulkan_window_adapt_pass.cpp").read_text()
fast = (ROOT / ".github/workflows/encore-core-fast-gate.yml").read_text()
full = (ROOT / ".github/workflows/encore-core-preflight.yml").read_text()
command = "python3 -B tools/check-ps5-f07-present-layer-growth-host.py"
assert command in fast and command in full
assert "std::list<Layer> layers{};" in header
# Retaining inactive owners is safe because only the first active configs
# are dereferenced and recorded by the composition pass.
assert "const size_t layer_count = configs.size();" in adapt
assert "auto layer_it = layers.begin();" in adapt
assert "for (size_t i = 0; i < layer_count; i++) {" in adapt
assert "layer_it->ConfigureDraw(" in adapt
assert "VkExtent2D layer_window_size{};" in header
assert "F07 C04 append-only presentation layers without device idle" in generator
assert blit.count("    if (!rebuild_layers && !retire_excess_layers &&") == 1
assert blit.index("    if (resource_update_required) {\n        WaitIdle(device);") < blit.index(
    "    if (!rebuild_layers && !retire_excess_layers &&"
)
start = blit.index("    // Presentation layers live in std::list:")
start = blit.rfind("#ifdef PS5_NATIVE", 0, start)
end = blit.index("\n    window_adapt->Draw(", start)
block = blit[start:end]
assert block.count("layers.emplace_back(device, memory_allocator, scheduler, device_memory, image_count,") == 3
assert "if (!rebuild_layers && !retire_excess_layers &&" in block
assert "constexpr size_t kMaxRetainedLayers = 8;" in block
assert "layers.size() > kMaxRetainedLayers && layers.size() > framebuffers.size()" in block
assert "else if (rebuild_layers || retire_excess_layers)" in block
assert "output_sensitive && output_size_changed" in block
assert "layer_window_size = window_size;" in block
assert "if (!layers.empty())" not in block
assert "if (!resource_update_required && !layers.empty())" in block
assert block.count("WaitIdle(device);") == 1
assert "#else\n    if (layers.size() != framebuffers.size()) {" in block
assert block.rstrip().endswith("#endif")

code = r"""
#include <cassert>
#include <cstddef>
#include <cstdio>
#include <list>
#include <vector>
struct Device {};
struct Allocator {};
struct Scheduler {};
struct Memory {};
struct WindowSize { unsigned width{}, height{}; };
using VkExtent2D = WindowSize;
namespace Settings { enum class ScalingFilter { Bilinear, Fsr, Sgsr, SgsrEdge }; }
struct Filters {};
struct Adapt { int GetDescriptorSetLayout() const {return 7;} };
struct Layer {
    static inline unsigned made=0;
    static inline unsigned destroyed=0;
    unsigned generation{};
    WindowSize output{};
    Layer(const Device&,Allocator&,Scheduler&,Memory&,std::size_t,
          WindowSize size,int,Filters&) : generation(++made), output(size) {}
    Layer(const Layer&)=delete;
    Layer& operator=(const Layer&)=delete;
    ~Layer() {++destroyed;}
};
struct Screen {
    Device device{};
    Allocator memory_allocator{};
    Scheduler scheduler{};
    Memory device_memory{};
    std::size_t image_count{3};
    Filters filters{};
    Adapt adapt{};
    Adapt* window_adapt{&adapt};
    Settings::ScalingFilter scaling_filter{Settings::ScalingFilter::Bilinear};
    std::list<Layer> layers{};
    VkExtent2D layer_window_size{};
    unsigned idle_calls{};
    void WaitIdle(const Device&) {++idle_calls;}
    void Apply(std::size_t n, [[maybe_unused]] bool resource_update_required,
               unsigned width=1280, unsigned height=720) {
        std::vector<int> framebuffers(n);
        const WindowSize window_size{width,height};
__ACTUAL_DECISION__
    }
};
int main() {
    Screen b;
    b.Apply(1,false);
    assert(b.layers.size()==1 && b.idle_calls==0 && Layer::made==1);
    [[maybe_unused]] const Layer* const first=&b.layers.front();
    [[maybe_unused]] const unsigned generation=first->generation;
    b.Apply(3,false);
    assert(b.layers.size()==3);
#ifdef PS5_NATIVE
    assert(b.idle_calls==0 && Layer::made==3 && Layer::destroyed==0);
    assert(&b.layers.front()==first && b.layers.front().generation==generation);
#else
    assert(b.idle_calls==0 && Layer::made==4 && Layer::destroyed==1);
#endif
    b.Apply(3,false);
#ifdef PS5_NATIVE
    assert(b.idle_calls==0 && Layer::made==3 && Layer::destroyed==0);
#else
    assert(b.idle_calls==0 && Layer::made==4 && Layer::destroyed==1);
#endif
    b.Apply(1,false);
#ifdef PS5_NATIVE
    // Shrinking the active draw count must not destroy cached layer owners.
    assert(b.layers.size()==3 && b.idle_calls==0);
    assert(Layer::made==3 && Layer::destroyed==0);
    b.Apply(3,false);
    assert(b.layers.size()==3 && b.idle_calls==0);
    assert(Layer::made==3 && Layer::destroyed==0);
    assert(&b.layers.front()==first);
    b.Apply(1,false);
    assert(b.layers.size()==3 && b.idle_calls==0);
#else
    assert(b.layers.size()==1);
    assert(b.idle_calls==0 && Layer::made==5 && Layer::destroyed==4);
#endif
    b.Apply(1,true);
#ifdef PS5_NATIVE
    // Caller already waited before a settings/descriptor-layout change.
    // Rebuild exactly once even with unchanged frame count, not twice-idle.
    assert(b.idle_calls==0 && b.layers.size()==1 && Layer::made==4 && Layer::destroyed==3);
#else
    assert(b.idle_calls==0 && Layer::made==5 && Layer::destroyed==4);
#endif
#ifdef PS5_NATIVE
    // FSR and both SGSR modes own output-sized images created by Layer.
    // Same-size growth keeps identities; a changed screen rectangle must
    // drain and rebuild even if the swapchain extent and layer count match.
    for (const auto filter : {Settings::ScalingFilter::Fsr,
                              Settings::ScalingFilter::Sgsr,
                              Settings::ScalingFilter::SgsrEdge}) {
        Screen f;
        f.scaling_filter=filter;
        f.Apply(1,false,1280,720);
        const Layer* const first=&f.layers.front();
        f.Apply(3,false,1280,720);
        assert(f.idle_calls==0 && &f.layers.front()==first);
        f.Apply(3,false,1920,1080);
        assert(f.idle_calls==1 && f.layers.size()==3);
        for (const Layer& layer : f.layers)
            assert(layer.output.width==1920 && layer.output.height==1080);
        const Layer* const refreshed=&f.layers.front();
        f.Apply(4,false,1920,1080);
        assert(f.idle_calls==1 && &f.layers.front()==refreshed);
    }
    // A bilinear layer has no output-sized constructor resources.
    Screen plain;
    plain.Apply(1,false,1280,720);
    const Layer* const plain_first=&plain.layers.front();
    plain.Apply(3,false,1920,1080);
    assert(plain.idle_calls==0 && &plain.layers.front()==plain_first);
    // Keep at most eight *spare* layer owners. Over-budget shrink must
    // block until queued readers are complete, then rebuild exact actives.
    Screen budget;
    budget.Apply(9,false);
    assert(budget.layers.size()==9 && budget.idle_calls==0);
    budget.Apply(8,false);
    assert(budget.layers.size()==8 && budget.idle_calls==1);
    budget.Apply(2,false);
    assert(budget.layers.size()==8 && budget.idle_calls==1);
    budget.Apply(8,false);
    assert(budget.layers.size()==8 && budget.idle_calls==1);
#endif
    std::puts("F07_C04_LAYER_GROWTH_PASS");
}
""".replace("__ACTUAL_DECISION__",block)
compiler=shutil.which("clang++") or shutil.which("g++")
assert compiler, "C++20 compiler required"
with tempfile.TemporaryDirectory(prefix="f07-c04-layer-growth-") as d:
    source=Path(d)/"growth.cpp"
    source.write_text(code)
    for native in (False,True):
        for opt in ("-O0","-O2"):
            executable=Path(d)/("growth-"+str(int(native))+opt)
            cmd=[compiler,"-std=c++20",opt,"-Wall","-Wextra","-Werror",
                 "-fsanitize=undefined","-fno-sanitize-recover=all",
                 *(["-DPS5_NATIVE=1"] if native else []),
                 str(source),"-o",str(executable)]
            built=subprocess.run(cmd,capture_output=True,text=True,timeout=60)
            assert built.returncode==0,(native,opt,built.stderr[-6000:])
            result=subprocess.run([str(executable)],capture_output=True,text=True,timeout=20)
            assert result.returncode==0,(native,opt,result.stderr[-4000:])
            assert "F07_C04_LAYER_GROWTH_PASS" in result.stdout
            print("F07_C04_LAYER_GROWTH_PASS native="+str(int(native)),opt)
print("F07_C04_NO_GPU_OR_CONSOLE_FRAME_PROOF")
