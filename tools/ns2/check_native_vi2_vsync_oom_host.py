#!/usr/bin/env python3
"""P1.3/P4.2: compile actual VI2 vblank registration and exercise OOM rollback."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
OWNER=ROOT/'vendor/encore-active/ns2-runtime/graphics_supervisor/core/hle/service/am/service/graphics_supervisor.cpp'
source=OWNER.read_text()
begin='    void VsyncEvent(HLERequestContext& ctx) {'
end='    void Notifications(HLERequestContext& ctx) {'
assert source.count(begin)==source.count(end)==1
method=source[source.index(begin):source.index(end)]
assert method.index('m_vsync_events.reserve(32);') < method.index('m_context.CreateEvent("NativeVi2Vsync")')
assert method.index('m_vsync->events.reserve(32);') < method.index('m_context.CreateEvent("NativeVi2Vsync")')
assert method.index('m_vsync->events.pop_back();') < method.index('m_context.CloseEvent(event);')
assert 'm_vsync_timer = std::move(new_timer);' in method
assert 'catch (const std::bad_alloc&)' in method

cpp=r'''
#include <array>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <memory>
#include <mutex>
#include <new>
#include <optional>
#include <string>
#include <utility>
#include <vector>
using u32=std::uint32_t;
using s64=std::int64_t;
static int fail_new{};
void* operator new(std::size_t bytes) {
    if (fail_new && --fail_new==0) throw std::bad_alloc{};
    if (void* p=std::malloc(bytes)) return p;
    throw std::bad_alloc{};
}
void operator delete(void* p) noexcept {std::free(p);}
void operator delete(void* p,std::size_t) noexcept {std::free(p);}
namespace Kernel {
struct Result {u32 raw;};
constexpr Result ResultOutOfResource{0xfeed};

struct Kernel {};
struct KEvent {
    bool closed{};
    unsigned signals{};
    KEvent* GetReadableEvent() {return this;}
    void Signal(Kernel&) {assert(!closed);++signals;}
};
}
constexpr Kernel::Result ResultSuccess{0};
struct HLERequestContext {
    u32 status{0xffffffff};
    unsigned copies{};
    int GetCommand() const {return 31;}
};
namespace IPC {
struct ResponseBuilder {
    HLERequestContext& ctx;
    ResponseBuilder(HLERequestContext& request, int, int=0, int=0):ctx{request} {}
    void Push(u32 result) {ctx.status=result;}
    void PushCopyObjects(HLERequestContext&, Kernel::KEvent*) {++ctx.copies;}
};
}
namespace Core::Timing {
struct EventType {
    std::function<std::optional<std::chrono::nanoseconds>(s64,std::chrono::nanoseconds)> callback;
};
static bool fail_timer{};
template<class Callback>
std::shared_ptr<EventType> CreateEvent(const char*,Callback&& cb) {
    if (fail_timer) throw std::bad_alloc{};
    return std::make_shared<EventType>(EventType{std::forward<Callback>(cb)});
}
}
struct Timing {
    bool fail_schedule{};
    unsigned count{};
    std::shared_ptr<Core::Timing::EventType> scheduled;
    void ScheduleLoopingEvent(std::chrono::nanoseconds,std::chrono::nanoseconds,
                              const std::shared_ptr<Core::Timing::EventType>& timer) {
        if(fail_schedule) throw std::bad_alloc{};
        ++count;scheduled=timer;
    }
    void Tick() {assert(scheduled);(void)scheduled->callback(0,std::chrono::nanoseconds{0});}
};
struct System {
    Timing timing;
    Kernel::Kernel owner;
    Timing& CoreTiming(){return timing;}
    Kernel::Kernel& Kernel(){return owner;}
};
struct Context {
    std::array<Kernel::KEvent,64> pool{};
    unsigned created{},closed{};
    bool fail_create{};
    Kernel::KEvent* CreateEvent(const char*) {
        if(fail_create)return nullptr;
        assert(created<pool.size());
        return &pool[created++];
    }
    void CloseEvent(Kernel::KEvent* event) {
        assert(event && !event->closed);
        event->closed=true;
        ++closed;
    }
};
struct IVi2Session {
    struct VsyncState {
        std::mutex mutex;
        std::vector<Kernel::KEvent*> events;
    };
    System system;
    Kernel::Kernel& kernel=system.Kernel();
    Context m_context;
    std::shared_ptr<VsyncState> m_vsync=std::make_shared<VsyncState>();
    std::vector<Kernel::KEvent*> m_vsync_events;
    std::shared_ptr<Core::Timing::EventType> m_vsync_timer;
__METHOD__
};
int main() {
    {
        IVi2Session s;
        HLERequestContext request;
        fail_new=1;
        s.VsyncEvent(request);
        assert(request.status==Kernel::ResultOutOfResource.raw);
        assert(s.m_context.created==0 && s.m_vsync_events.empty());
        fail_new=0;
        request={};
        s.VsyncEvent(request);
        assert(request.status==0 && request.copies==1 && s.m_context.created==1);
    }
    {
        IVi2Session s;
        HLERequestContext request;
        fail_new=2;
        s.VsyncEvent(request);
        assert(request.status==Kernel::ResultOutOfResource.raw);
        assert(s.m_context.created==0 && s.m_vsync->events.empty());
        fail_new=0;
        request={};
        s.VsyncEvent(request);
        assert(request.status==0 && request.copies==1);
    }
    {
        IVi2Session s;
        HLERequestContext request;
        s.m_context.fail_create=true;
        s.VsyncEvent(request);
        assert(request.status==Kernel::ResultOutOfResource.raw);
        assert(s.m_vsync_events.empty() && s.m_context.created==0);
    }
    {
        IVi2Session s;
        HLERequestContext request;
        Core::Timing::fail_timer=true;
        s.VsyncEvent(request);
        assert(request.status==Kernel::ResultOutOfResource.raw);
        assert(s.m_context.created==s.m_context.closed);
        assert(s.m_vsync_events.empty() && s.m_vsync->events.empty());
        Core::Timing::fail_timer=false;
        request={};
        s.VsyncEvent(request);
        assert(request.status==0 && request.copies==1 && s.m_vsync_timer);
    }
    {
        IVi2Session s;
        HLERequestContext request;
        s.system.timing.fail_schedule=true;
        s.VsyncEvent(request);
        assert(request.status==Kernel::ResultOutOfResource.raw);
        assert(s.m_context.created==s.m_context.closed);
        assert(s.m_vsync_events.empty() && s.m_vsync->events.empty());
        s.system.timing.fail_schedule=false;
        request={};
        s.VsyncEvent(request);
        assert(request.status==0 && s.system.timing.count==1);
    }
    {
        IVi2Session s;
        for (unsigned i=0;i<32;++i) {
            HLERequestContext request;
            s.VsyncEvent(request);
            assert(request.status==0 && request.copies==1);
        }
        assert(s.m_context.created==32 && s.system.timing.count==1);
        assert(s.m_vsync_events.size()==32 && s.m_vsync->events.size()==32);
        s.system.timing.Tick();
        for(auto* event:s.m_vsync_events) assert(event->signals==1 && !event->closed);
        HLERequestContext extra;
        s.VsyncEvent(extra);
        assert(extra.status==Kernel::ResultOutOfResource.raw);
        assert(s.m_context.created==32 && s.m_vsync_events.size()==32);
    }
    std::puts("P1_3_VI2_VSYNC_OOM_PASS both_reserves timer_create schedule retry 32_events");
}
'''.replace('__METHOD__',method)
env=dict(os.environ)
sdk=Path('/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk')
if sdk.exists():env['SDKROOT']=str(sdk)
compilers=list(dict.fromkeys(filter(None,(shutil.which('clang++'),shutil.which('g++')))))
assert compilers
with tempfile.TemporaryDirectory(prefix='encore-vi2-vsync-') as temp:
    fixture=Path(temp)/'real-vsync.cpp';fixture.write_text(cpp)
    for compiler in compilers:
        for opt in (0,2):
            exe=Path(temp)/f'{Path(compiler).name}-{opt}'
            cmd=[compiler,'-std=c++20',f'-O{opt}','-Wall','-Wextra','-Werror',
                 '-Wno-unused-parameter','-pedantic','-fsanitize=undefined',
                 '-fno-sanitize-recover=all',str(fixture),'-o',str(exe)]
            built=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=45)
            assert built.returncode==0,(compiler,built.stderr[-3500:])
            result=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=15)
            assert result.returncode==0,(compiler,result.stderr[-3000:])
            print(Path(compiler).name,'O'+str(opt),result.stdout.strip(),flush=True)
