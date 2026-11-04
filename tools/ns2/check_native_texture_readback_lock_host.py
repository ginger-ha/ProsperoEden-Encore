#!/usr/bin/env python3
"""P2.2b: compile/exercise the actual native TextureCache flush-lock branch.

No GPU or console. The fixture uses the real reviewed RAII scope and
FlushRegion texture arm, not a duplicate implementation of the decision.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

root=Path(__file__).resolve().parents[2]
source=(root/'vendor/encore-active/eden-vulkan/vulkan_rasterizer.cpp').read_text()
assert source.count('NativeTextureReadLockScope native_texture_read_scope{this};')==1
assert 'VideoCommon::ReadNs2GpuShader(' in source
scope='thread_local const RasterizerVulkan* native_texture_read_lock_owner{};'
assert source.count(scope)==1
scope+=source.split(scope,1)[1].split('\n#endif\nstruct DrawParams',1)[0]
anchor='    // No guest image ever overlapped these CPU pages: no texture readback.'
assert source.count(anchor)==1
flush=anchor+source.split(anchor,1)[1].split('    // DownloadMemory visits registered buffers only.',1)[0]
assert 'native_texture_read_lock_owner == this' in flush
assert 'texture_cache.DownloadMemory(addr, size);' in flush
cpp=r'''
#include <cassert>
#include <cstdint>
#include <mutex>
using DAddr=std::uint64_t;
using u64=std::uint64_t;
namespace VideoCommon {
enum class CacheType:std::uint32_t { TextureCache=1 };
constexpr CacheType operator&(CacheType a,CacheType b) {
    return CacheType(std::uint32_t(a)&std::uint32_t(b));
}
}
constexpr bool True(VideoCommon::CacheType kind) {return std::uint32_t(kind)!=0;}
namespace Eden::ImagePages {
constexpr bool NeverHeld(DAddr,u64) {return false;}
}
namespace Vulkan {
struct RasterizerVulkan {
    struct Cache {
        std::mutex mutex;
        unsigned downloaded{};
        void DownloadMemory(DAddr,u64) {++downloaded;}
    } texture_cache;
    void FlushTexture(DAddr addr,u64 size,VideoCommon::CacheType which);
};
namespace {
#if defined(PS5_NATIVE) && defined(EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL)
__SCOPE__
#endif
}
void RasterizerVulkan::FlushTexture(DAddr addr,u64 size,VideoCommon::CacheType which) {
    if (addr==0 || size==0) return;
__FLUSH__
}
}
int main() {
    Vulkan::RasterizerVulkan renderer, other;
    using VideoCommon::CacheType;
    renderer.FlushTexture(16,4,CacheType::TextureCache);
#if defined(PS5_NATIVE) && defined(EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL)
    {
        const std::scoped_lock lock{renderer.texture_cache.mutex};
        Vulkan::NativeTextureReadLockScope owner{&renderer};
        // With the old code, this deadlocks on the SAME non-recursive mutex
        // whenever the guest address held a registered GPU image.
        renderer.FlushTexture(16,4,CacheType::TextureCache);
        other.FlushTexture(16,4,CacheType::TextureCache);
    }
    assert(renderer.texture_cache.downloaded==2);
    assert(other.texture_cache.downloaded==1);
#else
    assert(renderer.texture_cache.downloaded==1);
#endif
}
'''.replace('__SCOPE__',scope).replace('__FLUSH__',flush)
env=dict(os.environ)
sdk=Path('/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk')
if sdk.exists():env['SDKROOT']=str(sdk)
compilers=list(dict.fromkeys(filter(None,(shutil.which('clang++'),shutil.which('g++')))))
assert compilers
with tempfile.TemporaryDirectory(prefix='encore-texture-lock-') as temp:
    path=Path(temp)/'readback.cpp';path.write_text(cpp)
    for compiler in compilers:
        for native in (False,True):
            for opt in (0,2):
                exe=Path(temp)/f'run-{Path(compiler).name}-{native}-{opt}'
                cmd=[compiler,'-std=c++20',f'-O{opt}','-Wall','-Wextra','-Werror',
                     '-Wno-unused-parameter','-fsanitize=undefined',
                     '-fno-sanitize-recover=all']
                if native:cmd+=['-DPS5_NATIVE=1','-DEDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL=1']
                built=subprocess.run(cmd+[str(path),'-o',str(exe)],env=env,
                                     capture_output=True,text=True,timeout=30)
                assert built.returncode==0,(compiler,built.stderr[-2800:])
                run=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=6)
                assert run.returncode==0,(compiler,run.stderr[-1200:])
                print('P2_2B_NATIVE_TEXTURE_REENTRANT_FLUSH_PASS',
                      Path(compiler).name,'O'+str(opt),
                      'NS2-lock' if native else 'NS1-normal',flush=True)
