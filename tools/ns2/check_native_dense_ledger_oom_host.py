#!/usr/bin/env python3
"""P1.2/P4.2 real GPU-only 214 ledger reservation and nonallocating GMMU commit."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
SRC=(ROOT/'vendor/encore-active/ns2-runtime/gpu_session/core/hle/service/am/service/gpu_worker.cpp').read_text()
method=SRC.split('Result IGpuWorker::BackGpuOnlyRegion(',1)[1].split(
    'bool IGpuWorker::RetireGpuOnlyRegion(',1)[0]
start='    decltype(m_dense_regions) pending_region;'
stop='    std::unique_ptr<Kernel::KPageGroup> pages;'
assert method.count(start)==method.count(stop)==1
reserve=method[method.index(start):method.index(stop)]
end='    m_dense_bytes += size;'
commit_start='    pending_region.begin()->second ='
assert method.count(commit_start)==method.count(end)==1
commit=method[method.index(commit_start):method.index(end)+len(end)]
assert method.index(start)<method.index('memory.AllocateAndOpen(')
assert method.index('pending_region.try_emplace(')<method.index('RemapNativeSparse(')
assert method.index('RemapNativeSparse(')<method.index('m_dense_regions.merge(pending_region);')
assert 'm_dense_regions.emplace(' not in method
assert 'catch (const std::bad_alloc&)' in reserve
assert 'pages = std::make_unique<Kernel::KPageGroup>' in method
assert 'return Kernel::ResultOutOfResource;' in method
cpp=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <map>
#include <memory>
#include <new>
#include <utility>
using u32=std::uint32_t;
using u64=std::uint64_t;
namespace Kernel {constexpr int ResultOutOfResource=42;}
constexpr int ResultSuccess=0;
static int fail_allocation{};
void* operator new(std::size_t bytes) {
    if (fail_allocation && --fail_allocation == 0) throw std::bad_alloc{};
    if (void* ptr = std::malloc(bytes)) return ptr;
    throw std::bad_alloc{};
}
void operator delete(void* pointer) noexcept { std::free(pointer); }
void operator delete(void* pointer,std::size_t) noexcept { std::free(pointer); }
u64 GetInteger(u64 value) { return value; }
struct DenseRegion {
    u64 address{}, size{}, alias{};
    u32 nvmap_handle{};
    std::unique_ptr<int> pages;
    std::weak_ptr<void> nvmap_lifetime;
    bool nvmap_released{}, gmmu_released{};
};
struct Owner {
    std::map<std::pair<u32,u64>,DenseRegion> m_dense_regions;
    u64 m_dense_bytes{};
    bool guest_remapped{};
    int Stage(u32 address_space,u64 address,u64 size,bool simulate_post_remap_oom) {
        if (m_dense_regions.contains({address_space,address}))
            return Kernel::ResultOutOfResource;
__RESERVE__
        auto pages=std::make_unique<int>(101);
        const u64 alias=0x400000;
        const u32 handle_id=88;
        auto live_handle=std::make_shared<int>(42);
        const std::weak_ptr<void> nvmap_lifetime{live_handle};
        guest_remapped=true;
        if (simulate_post_remap_oom) fail_allocation=1;
__COMMIT__
        fail_allocation=0;
        return ResultSuccess;
    }
};
int main() {
    Owner owner;
    fail_allocation=1;
    assert(owner.Stage(1,0x20000,0x1000,false)==Kernel::ResultOutOfResource);
    assert(!owner.guest_remapped && owner.m_dense_regions.empty() && !owner.m_dense_bytes);
    assert(owner.Stage(1,0x20000,0x1000,true)==ResultSuccess);
    assert(owner.guest_remapped && owner.m_dense_regions.size()==1 &&
           owner.m_dense_bytes==0x1000 && !fail_allocation);
    assert(owner.m_dense_regions.begin()->second.pages &&
           *owner.m_dense_regions.begin()->second.pages==101);
    assert(owner.Stage(1,0x20000,0x1000,false)==Kernel::ResultOutOfResource);
    assert(owner.Stage(1,0x30000,0x2000,true)==ResultSuccess);
    assert(owner.m_dense_regions.size()==2 && owner.m_dense_bytes==0x3000);
}
'''.replace('__RESERVE__',reserve).replace('__COMMIT__',commit)
env=dict(os.environ)
sdk=Path('/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk')
if sdk.exists():env['SDKROOT']=str(sdk)
compilers=list(dict.fromkeys(filter(None,(shutil.which('clang++'),shutil.which('g++')))))
assert compilers
with tempfile.TemporaryDirectory(prefix='encore-dense-ledger-') as temp:
    fixture=Path(temp)/'ledger.cpp';fixture.write_text(cpp)
    for compiler in compilers:
        for opt in (0,2):
            exe=Path(temp)/f'{Path(compiler).name}-{opt}'
            cmd=[compiler,'-std=c++20',f'-O{opt}','-Wall','-Wextra','-Werror',
                 '-pedantic','-fsanitize=undefined','-fno-sanitize-recover=all',
                 str(fixture),'-o',str(exe)]
            built=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=45)
            assert built.returncode==0,(compiler,built.stderr[-2800:])
            run=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=15)
            assert run.returncode==0,(compiler,run.stderr[-2000:])
            print('P1_2_DENSE_GPU_LEDGER_TRANSACTION_PASS',Path(compiler).name,
                  f'O{opt}', 'precommit_oom=refused', 'postcommit_new=none',flush=True)
