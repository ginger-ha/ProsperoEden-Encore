#!/usr/bin/env python3
"""P1.3/P4.2: execute actual VI2 NVMap duplicate/lease/OOM hunk with mocks."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

root=Path(__file__).resolve().parents[2]
source=(root/'vendor/encore-active/ns2-runtime/graphics_supervisor/core/hle/service/am/service/graphics_supervisor.cpp').read_text()
lease_start='    std::unique_ptr<u32> lease_token;'
lease_end='    } catch (const std::bad_alloc&) {\n        // shared_ptr invoked our NVMap deleter if its allocation failed.\n        // Return an absent present image rather than unwinding through IPC.\n        return {};\n    }'
assert source.count(lease_start)==1 and source.count(lease_end)==1
start=source.index(lease_start)
end=source.index(lease_end,start)+len(lease_end)
lease_source=source[start:end]
assert lease_source.index('std::make_unique<u32>(backing)') < lease_source.index('Duplicate(true)')
assert lease_source.index('Duplicate(true)') < lease_source.index('lease_token.release()')
create_start='                            try {\n                                if (const auto created ='
create_end='                                result = Kernel::ResultOutOfResource;\n                            }'
assert source.count(create_start)==1 and source.count(create_end)==1
start=source.index(create_start)
end=source.index(create_end,start)+len(create_end)
create_source=source[start:end]
assert 'nvmap.FreeHandle(backing, true)' in create_source
assert 'catch (const std::bad_alloc&)' in create_source
cpp=r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <memory>
#include <new>
#include <optional>
#include <utility>
using u32=std::uint32_t;
static int fail_allocation{};
void* operator new(std::size_t size) {
    if (fail_allocation && --fail_allocation==0) throw std::bad_alloc{};
    if (void* ptr=std::malloc(size)) return ptr;
    throw std::bad_alloc{};
}
void operator delete(void* ptr) noexcept { std::free(ptr); }
void operator delete(void* ptr,std::size_t) noexcept { std::free(ptr); }
namespace Nvidia {enum class NvResult { Success, Fail };}
struct NvMap {
    int freed{};
    void FreeHandle(u32,bool) { ++freed; }
};
struct Container {
    NvMap nvmap;
    NvMap& GetNvMapFile() { return nvmap; }
};
struct Module {
    Container container;
    Container& GetContainer() {return container;}
};
struct Handle {
    int duplicated{}, failures{};
    u32 size{4096};
    Nvidia::NvResult Duplicate(bool internal) {
        assert(internal);
        if (failures) return Nvidia::NvResult::Fail;
        ++duplicated;
        return Nvidia::NvResult::Success;
    }
};
struct Image {std::array<u32,16> preference{};};
struct PresentImage {
    std::array<u32,16> layout{};
    u32 backing{},offset{};
    std::shared_ptr<Module> module;
    std::shared_ptr<u32> lease;
};
namespace Kernel {constexpr int ResultOutOfResource=42;}
constexpr int ResultSuccess=0;
struct Ledger {
    bool throw_on_create{},refuse{};
    std::optional<u32> Create(u32,u32,int,int,u32 id) {
        if (throw_on_create) throw std::bad_alloc{};
        if (refuse) return {};
        return id;
    }
};
struct Owner {
    std::shared_ptr<Module> m_native_module=std::make_shared<Module>();
    Ledger m_native_images;
    std::uint64_t m_next_image_id{1};
    std::optional<PresentImage> Lease(Handle* backing_handle) {
        const u32 backing{12},offset{0};
        const auto image=std::make_shared<Image>();
__LEASE__
    }
    int CreateImage(Handle* handle) {
        auto& nvmap=m_native_module->GetContainer().GetNvMapFile();
        const u32 backing{12};
        const std::optional<int> requirements{1};
        const int preferences{};
        u32 id{};
        int result=Kernel::ResultOutOfResource;
        assert(handle->Duplicate(true)==Nvidia::NvResult::Success);
__CREATE__
        assert(result==Kernel::ResultOutOfResource || id!=0);
        return result;
    }
};
int main() {
    Owner obj;
    Handle handle;
    {
        auto lease=obj.Lease(&handle);
        assert(lease && lease->backing==12 && handle.duplicated==1);
        assert(obj.m_native_module->container.nvmap.freed==0);
    }
    assert(obj.m_native_module->container.nvmap.freed==1);
    handle.failures=1;
    assert(!obj.Lease(&handle));
    assert(handle.duplicated==1 && obj.m_native_module->container.nvmap.freed==1);
    handle.failures=0;
    // Pre-duplication new fails: no NVMap duplicate acquired.
    fail_allocation=1;
    assert(!obj.Lease(&handle));
    assert(handle.duplicated==1 && obj.m_native_module->container.nvmap.freed==1);
    // Post-duplication shared_ptr control-block new fails: its custom
    // deleter must release the already duplicated NVMap handle exactly once.
    fail_allocation=2;
    assert(!obj.Lease(&handle));
    assert(handle.duplicated==2 && obj.m_native_module->container.nvmap.freed==2);
    obj.m_native_images.throw_on_create=true;
    assert(obj.CreateImage(&handle)==Kernel::ResultOutOfResource);
    assert(handle.duplicated==3 && obj.m_native_module->container.nvmap.freed==3);
    obj.m_native_images.throw_on_create=false;
    obj.m_native_images.refuse=true;
    assert(obj.CreateImage(&handle)==Kernel::ResultOutOfResource);
    assert(handle.duplicated==4 && obj.m_native_module->container.nvmap.freed==4);
    obj.m_native_images.refuse=false;
    assert(obj.CreateImage(&handle)==Kernel::ResultOutOfResource || obj.m_next_image_id==2);
    assert(handle.duplicated==5 && obj.m_native_module->container.nvmap.freed==4);
}
'''.replace('__LEASE__',lease_source).replace('__CREATE__',create_source)
# Avoid constructing the Image while the test's allocation failure is armed.
cpp=cpp.replace('const auto image=std::make_shared<Image>();','const Image value{};\n        const Image* image=&value;')
# The source uses the header's automatic std::bad_alloc branch unchanged.
env=dict(os.environ)
sdk=Path('/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk')
if sdk.exists():env['SDKROOT']=str(sdk)
compilers=list(dict.fromkeys(filter(None,(shutil.which('clang++'),shutil.which('g++')))))
assert compilers
with tempfile.TemporaryDirectory(prefix='encore-vi2-oom-') as temp:
    fixture=Path(temp)/'real-hunk.cpp';fixture.write_text(cpp)
    for compiler in compilers:
        for opt in (0,2):
            exe=Path(temp)/f'{Path(compiler).name}-{opt}'
            cmd=[compiler,'-std=c++20',f'-O{opt}','-Wall','-Wextra',
                 '-Werror','-pedantic','-Wno-unused-parameter','-fsanitize=undefined',
                 '-fno-sanitize-recover=all',str(fixture),'-o',str(exe)]
            built=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=45)
            assert built.returncode==0,(compiler,built.stderr[-3500:])
            run=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=15)
            assert run.returncode==0,(compiler,run.stderr[-3500:])
            print('P4_2_VI2_NVMap_OOM_LIFETIME_PASS',Path(compiler).name,
                  f'O{opt}', 'lease=2failures', 'ledger=rollback',flush=True)
