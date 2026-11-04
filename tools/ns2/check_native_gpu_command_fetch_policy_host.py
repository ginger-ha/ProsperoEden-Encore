#!/usr/bin/env python3
"""P2.7: compile the exact G20 command-read selection under host sanitizers.

For a process-generation-authorized native NS2 channel, SafeRead must be
selected even when the guest chose unsafe DMA. The shipping NS1/host build
must retain its previous setting, without referencing the NS2 registry.
This validates policy only, NOT pending GPU job completion.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
OWNER=ROOT/'vendor/encore-active/eden-core/src/video_core'
CMAKE=(ROOT/'headless/CMakeLists.txt').read_text()
assert CMAKE.count('target_compile_definitions(video_core PRIVATE EDEN_NS2_NATIVE_GPU_DISPATCH=1)')==1
assert CMAKE.index('if(EDEN_NS2_NVDRV_EXPERIMENTAL)') < CMAKE.index('target_compile_definitions(video_core PRIVATE EDEN_NS2_NATIVE_GPU_DISPATCH=1)')
assert CMAKE.index('target_compile_definitions(video_core PRIVATE EDEN_NS2_NATIVE_GPU_DISPATCH=1)') < CMAKE.index('option(EDEN_NS2_GPU_SESSION_EXPERIMENTAL')
start='        bool use_safe = Settings::IsDMALevelDefault() ?'
end='        if (use_safe) {'
policies=[]
for filename in ('dma_pusher.cpp','dma_pusher_dev.cpp'):
    owner=(OWNER/filename).read_text()
    assert owner.count(start)==owner.count(end)==1
    policy=owner[owner.index(start):owner.index(end)]
    assert policy.count('#ifdef EDEN_NS2_NATIVE_GPU_DISPATCH')==1
    assert policy.count('NativeGpuChannelRegistry::Instance().IsNative(&channel_state)')==1
    assert 'GpuGuestMemory<Tegra::CommandHeader, Tegra::Memory::GuestMemoryFlags::SafeRead>' in owner
    assert 'GpuGuestMemory<Tegra::CommandHeader, Tegra::Memory::GuestMemoryFlags::UnsafeRead>' in owner
    policies.append(policy)
assert policies[0]==policies[1], 'DEV and normal policy diverged'
assert '#include "core/hle/service/nvdrv/devices/native_gpu_channel_registry.h"' in (OWNER/'dma_pusher.cpp').read_text()
assert '#include "core/hle/service/nvdrv/devices/native_gpu_channel_registry.h"' in (OWNER/'dma_pusher_dev.cpp').read_text()

cpp=r'''
#include <cassert>
#include <cstddef>
struct ChannelState {};
namespace Settings {
inline bool default_level{},high{},safe{};
bool IsDMALevelDefault() { return default_level; }
bool IsGPULevelHigh() { return high; }
bool IsDMALevelSafe() { return safe; }
}
namespace Service::Nvidia::Devices {
struct NativeGpuChannelRegistry {
    inline static bool authorized{};
    inline static unsigned calls{};
    static NativeGpuChannelRegistry& Instance() { static NativeGpuChannelRegistry r; return r; }
    bool IsNative(const ChannelState* channel) {
        assert(channel);
        ++calls;
        return authorized;
    }
};
}
struct Dma {
    ChannelState channel_state;
    bool SafeRead() {
__POLICY__
        return use_safe;
    }
};
int main() {
    Dma dma;
    auto& registry=Service::Nvidia::Devices::NativeGpuChannelRegistry::Instance();
    for (unsigned default_level=0;default_level<2;++default_level)
    for (unsigned high=0;high<2;++high)
    for (unsigned safe=0;safe<2;++safe)
    for (unsigned authorized=0;authorized<2;++authorized) {
        Settings::default_level=default_level;
        Settings::high=high;
        Settings::safe=safe;
        registry.authorized=authorized;
        const unsigned before=registry.calls;
        const bool historical=default_level ? bool(high) : bool(safe);
#ifdef EDEN_NS2_NATIVE_GPU_DISPATCH
        assert(dma.SafeRead()==(historical || authorized));
        assert(registry.calls==before+1);
#else
        assert(dma.SafeRead()==historical);
        assert(registry.calls==before);
#endif
    }
}
'''.replace('__POLICY__',policies[0])
compiler=shutil.which('clang++') or shutil.which('g++')
assert compiler, 'C++20 compiler required'
env=dict(os.environ)
sdk=Path('/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk')
if sdk.exists(): env['SDKROOT']=str(sdk)
with tempfile.TemporaryDirectory(prefix='encore-native-dma-fetch-') as scratch:
    src=Path(scratch)/'policy.cpp'
    src.write_text(cpp)
    for native in (False,True):
        for level in (0,2):
            exe=Path(scratch)/f'policy-{native}-{level}'
            args=[compiler,'-std=c++20',f'-O{level}','-Wall','-Wextra','-Werror',
                  '-fsanitize=undefined','-fno-sanitize-recover=all']
            if native: args+=['-DEDEN_NS2_NATIVE_GPU_DISPATCH=1']
            args += [str(src),'-o',str(exe)]
            built=subprocess.run(args,env=env,capture_output=True,text=True,timeout=45)
            assert built.returncode==0, built.stderr[-2500:]
            run=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=20)
            assert run.returncode==0,run.stderr[-1500:]
            print('P2_7_NATIVE_FETCH_POLICY_PASS',
                  'native' if native else 'shipping_NS1','O'+str(level),
                  'cases=16', 'asan=not_run', 'ubsan=pass')
