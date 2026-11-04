#!/usr/bin/env python3
"""P2.7: execute real DMA command-list fence policy for both maintained paths.

A native authenticated guest GPU barrier must never depend on a host NS1
performance toggle. Does not claim hardware completion or real guest output.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
OWNER=ROOT/'vendor/encore-active/eden-core/src/video_core'
start='        const bool explicit_sync = command_list.command_lists[dma_pushbuffer_subindex].sync;'
stop='\n#endif'
policies=[]
for name in ('dma_pusher.cpp','dma_pusher_dev.cpp'):
    source=(OWNER/name).read_text()
    assert source.count(start)==1
    code=source[source.index(start):]
    assert stop in code
    policy=code[:code.index(stop)+len(stop)]
    assert '#ifdef EDEN_NS2_NATIVE_GPU_DISPATCH' in policy
    assert 'NativeGpuChannelRegistry::' in policy
    assert 'signal_sync = explicit_sync && user_sync;' in policy
    policies.append(policy)
assert policies[0]==policies[1],'maintained DMA paths must have identical fences'
cpp=r'''
#include <array>
#include <cassert>
#include <cstdint>
struct ChannelState {};
namespace Settings {
struct Setting {bool value{};bool GetValue() const {return value;}};
struct Values {Setting sync_memory_operations;};
inline Values values;
}
namespace Service::Nvidia::Devices {
struct NativeGpuChannelRegistry {
    inline static bool authorized{};
    inline static unsigned probes{};
    static NativeGpuChannelRegistry& Instance() {
        static NativeGpuChannelRegistry registry;
        return registry;
    }
    bool IsNative(const ChannelState* state) {
        assert(state);
        ++probes;
        return authorized;
    }
};
}
struct DmaPusher {
    struct Header {bool sync;};
    struct Commands {std::array<Header,2> command_lists;};
    Commands command_list{};
    ChannelState channel_state;
    std::size_t dma_pushbuffer_subindex{1};
    bool signal_sync{};
    void NextListFence() {
__POLICY__
    }
};
int main() {
    using Service::Nvidia::Devices::NativeGpuChannelRegistry;
    auto& registry=NativeGpuChannelRegistry::Instance();
    for(int explicit_sync=0;explicit_sync<2;++explicit_sync)
    for(int user_sync=0;user_sync<2;++user_sync)
    for(int native=0;native<2;++native) {
        DmaPusher dma;
        dma.command_list.command_lists[1].sync=explicit_sync!=0;
        Settings::values.sync_memory_operations.value=user_sync!=0;
        registry.authorized=native!=0;
        const unsigned before=registry.probes;
        dma.signal_sync=true; // stale state must never bypass a false barrier
        dma.NextListFence();
#ifdef EDEN_NS2_NATIVE_GPU_DISPATCH
        const bool expected=explicit_sync && (user_sync || native);
        // Deferred native authorization is not needed unless an explicit
        // GPU barrier is present and the host setting did not already wait.
        assert(registry.probes-before==(explicit_sync && !user_sync));
#else
        const bool expected=explicit_sync && user_sync;
        assert(registry.probes==before);
#endif
        assert(dma.signal_sync==expected);
    }
}
'''.replace('__POLICY__',policies[0])
env=dict(os.environ)
sdk=Path('/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk')
if sdk.exists():env['SDKROOT']=str(sdk)
compilers=list(dict.fromkeys(filter(None,(shutil.which('clang++'),shutil.which('g++')))))
assert compilers
with tempfile.TemporaryDirectory(prefix='encore-gpfifo-fence-') as temp:
    src=Path(temp)/'policy.cpp';src.write_text(cpp)
    for compiler in compilers:
        for native in (False,True):
            for opt in (0,2):
                exe=Path(temp)/f'{Path(compiler).name}-{native}-{opt}'
                cmd=[compiler,'-std=c++20',f'-O{opt}','-Wall','-Wextra',
                     '-Werror','-pedantic','-fsanitize=undefined',
                     '-fno-sanitize-recover=all',str(src),'-o',str(exe)]
                if native:cmd.insert(1,'-DEDEN_NS2_NATIVE_GPU_DISPATCH=1')
                built=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=45)
                assert built.returncode==0,(compiler,built.stderr[-3300:])
                run=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=15)
                assert run.returncode==0,(compiler,run.stderr[-2500:])
                print('P2_7_GPU_FIFO_FENCE_POLICY_PASS',Path(compiler).name,
                      f'O{opt}','NS2-native' if native else 'NS1-legacy',
                      'cases=8',flush=True)
