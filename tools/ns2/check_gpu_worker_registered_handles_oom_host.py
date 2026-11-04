#!/usr/bin/env python3
"""P1.2 real TIPC 111 memory-handle capacity admission precedes NVMap locks."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
OWNER=ROOT/'vendor/encore-active/ns2-runtime/gpu_session/core/hle/service/am/service/gpu_worker.cpp'
method=OWNER.read_text().split('Result IGpuWorker::RegisterMemory(',1)[1].split(
    'Result IGpuWorker::ReleaseMemory(',1)[0]
start='    try {\n        m_memory.reserve(MaxOwnedGpuMemoryHandles);'
stop='    if (!m_nv_session)'
assert method.count(start)==1 and method.count(stop)==1
stage=method[method.index(start):method.index(stop)]
assert 'catch (const std::bad_alloc&)' in stage
assert method.index(start)<method.index('nvmap.CreateHandle(size, handle)')
assert method.index(start)<method.index('LockForMapDeviceAddressSpace(')
assert method.index(start)<method.index('m_memory.push_back(id);')
assert 'm_memory.push_back(id);' in method
cpp=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <new>
#include <vector>
using u32=std::uint32_t;
static int fail_new{};
void* operator new(std::size_t bytes) {
    if(fail_new && --fail_new==0)throw std::bad_alloc{};
    if(void* p=std::malloc(bytes))return p;
    throw std::bad_alloc{};
}
void operator delete(void* p) noexcept {std::free(p);}
void operator delete(void* p,std::size_t) noexcept {std::free(p);}
namespace Kernel {constexpr int ResultOutOfResource=42;}
constexpr std::size_t MaxOwnedGpuMemoryHandles=4096;
struct Worker {
    std::vector<u32> m_memory;
    unsigned created{},locked{};
    int Register() {
__STAGE__
        // Actual irreversible operations occur only after the extracted
        // reservation. Do not allocate in the simulated NVMap and lock.
        ++created;
        ++locked;
        m_memory.push_back(u32(created));
        return 0;
    }
};
int main() {
    Worker worker;
    fail_new=1;
    assert(worker.Register()==42);
    assert(worker.created==0 && worker.locked==0 && worker.m_memory.empty());
    fail_new=0;
    assert(worker.Register()==0);
    assert(worker.m_memory.size()==1 && worker.created==1);
    fail_new=1;
    for(unsigned n=0;n<128;++n)assert(worker.Register()==0);
    assert(fail_new==1 && worker.m_memory.size()==129);
    assert(worker.created==worker.locked);
    fail_new=0;
}
'''.replace('__STAGE__',stage)
env=dict(os.environ)
sdk=Path('/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk')
if sdk.exists():env['SDKROOT']=str(sdk)
compilers=list(dict.fromkeys(filter(None,(shutil.which('clang++'),shutil.which('g++')))))
assert compilers
with tempfile.TemporaryDirectory(prefix='encore-worker-handles-') as temp:
    file=Path(temp)/'owner.cpp';file.write_text(cpp)
    for compiler in compilers:
        for opt in (0,2):
            exe=Path(temp)/f'{Path(compiler).name}-{opt}'
            args=[compiler,'-std=c++20',f'-O{opt}','-Wall','-Wextra','-Werror',
                  '-pedantic','-fsanitize=undefined','-fno-sanitize-recover=all',
                  str(file),'-o',str(exe)]
            built=subprocess.run(args,env=env,capture_output=True,text=True,timeout=45)
            assert built.returncode==0,(compiler,built.stderr[-3000:])
            test=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=15)
            assert test.returncode==0,(compiler,test.stderr[-2000:])
            print('P1_2_TIPC111_REGISTERED_GPU_HANDLES_OOM_PASS',Path(compiler).name,
                  f'O{opt}', 'preallocated=4096','post_nvmap_new=0',flush=True)
