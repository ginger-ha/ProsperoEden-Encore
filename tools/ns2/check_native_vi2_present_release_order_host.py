#!/usr/bin/env python3
"""P2.7 real VI2 release polling creation before publication of a queued frame.

Runs real extracted owner code on Clang/GCC under OOM injection. A successful
host fixture does not prove that a PS5 driver returned any guest framebuffer.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
OWNER=ROOT/'vendor/encore-active/ns2-runtime/graphics_supervisor/core/hle/service/am/service/graphics_supervisor.cpp'
source=OWNER.read_text()
present=source.split('    void Present(HLERequestContext& ctx) {',1)[1].split(
    '    void Cancel(HLERequestContext& ctx) {',1)[0]
start='                                if(result.IsSuccess() && !m_poll){'
stop='                                if(result.IsSuccess()){\n                                    auto native='
assert present.count(start)==present.count(stop)==1
arm=present[present.index(start):present.index(stop)]
assert arm.count('Core::Timing::CreateEvent(')==1
assert arm.count('ScheduleLoopingEvent(')==1
assert 'catch (const std::bad_alloc&)' in arm
assert arm.index('ScheduleLoopingEvent(')<arm.index('m_poll=std::move(timer);')
assert present.index(start)<present.index('c->producer->QueueBuffer(')
assert present.count('c->producer->QueueBuffer(')==1
assert present.count('if(!m_poll)')==0

cpp=r'''
#include <cassert>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <new>
#include <optional>
#include <utility>
using s64=std::int64_t;
struct Result {
    int raw{};
    [[nodiscard]] bool IsSuccess() const {return raw==0;}
};
constexpr Result ResultSuccess{0};
namespace Kernel {constexpr Result ResultOutOfResource{42};}
namespace Core::Timing {
struct EventType {
    std::function<std::optional<std::chrono::nanoseconds>(s64,std::chrono::nanoseconds)> callback;
};
static bool fail_timer{};
template<class Fn>
std::shared_ptr<EventType> CreateEvent(const char*,Fn&& fn) {
    if(fail_timer)throw std::bad_alloc{};
    return std::make_shared<EventType>(EventType{std::forward<Fn>(fn)});
}
}
struct Clock {
    bool fail_schedule{};
    unsigned count{};
    std::shared_ptr<Core::Timing::EventType> scheduled;
    void ScheduleLoopingEvent(std::chrono::nanoseconds,std::chrono::nanoseconds,
                              const std::shared_ptr<Core::Timing::EventType>& poll) {
        if(fail_schedule)throw std::bad_alloc{};
        ++count;scheduled=poll;
    }
    void Tick(){assert(scheduled);(void)scheduled->callback(0,std::chrono::nanoseconds{});}
};
struct System {
    Clock clock;
    Clock& CoreTiming(){return clock;}
};
struct IVi2Session:std::enable_shared_from_this<IVi2Session> {
    System system;
    std::shared_ptr<Core::Timing::EventType> m_poll;
    std::mutex mutex;
    unsigned published{},released{};
    auto LockService() {return std::unique_lock<std::mutex>(mutex);}
    void Release() {++released;}
    Result QueueOne() {
        Result result=ResultSuccess;
__ARM__
        if (result.IsSuccess()) {
            // Actual QueueBuffer is below this point in the source owner.
            assert(m_poll && system.clock.scheduled==m_poll);
            ++published;
        }
        return result;
    }
};
int main() {
    {
        auto session=std::make_shared<IVi2Session>();
        Core::Timing::fail_timer=true;
        assert(session->QueueOne().raw==42);
        assert(session->published==0 && !session->m_poll);
        Core::Timing::fail_timer=false;
        assert(session->QueueOne().raw==0);
        assert(session->published==1 && session->system.clock.count==1);
        session->system.clock.Tick();
        assert(session->released==1);
        assert(session->QueueOne().raw==0);
        assert(session->published==2 && session->system.clock.count==1);
    }
    {
        auto session=std::make_shared<IVi2Session>();
        session->system.clock.fail_schedule=true;
        assert(session->QueueOne().raw==42);
        assert(session->published==0 && !session->m_poll &&
               session->system.clock.count==0);
        session->system.clock.fail_schedule=false;
        assert(session->QueueOne().raw==0);
        assert(session->published==1 && session->system.clock.count==1);
        session->system.clock.Tick();
        assert(session->released==1);
    }
}
'''.replace('__ARM__',arm)
env=dict(os.environ)
sdk=Path('/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk')
if sdk.exists():env['SDKROOT']=str(sdk)
compilers=list(dict.fromkeys(filter(None,(shutil.which('clang++'),shutil.which('g++')))))
assert compilers
with tempfile.TemporaryDirectory(prefix='encore-vi2-present-') as temp:
    fixture=Path(temp)/'real-present-timer.cpp';fixture.write_text(cpp)
    for compiler in compilers:
        for opt in (0,2):
            exe=Path(temp)/f'{Path(compiler).name}-{opt}'
            args=[compiler,'-std=c++20',f'-O{opt}','-Wall','-Wextra','-Werror',
                  '-pedantic','-Wno-unused-parameter','-fsanitize=undefined',
                  '-fno-sanitize-recover=all',str(fixture),'-o',str(exe)]
            built=subprocess.run(args,env=env,capture_output=True,text=True,timeout=45)
            assert built.returncode==0,(compiler,built.stderr[-3300:])
            test=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=15)
            assert test.returncode==0,(compiler,test.stderr[-2100:])
            print('P2_7_VI2_PRESENT_RELEASE_TIMER_PASS',Path(compiler).name,
                  f'O{opt}', 'publication_after_timer=proved',
                  'no_phantom_queued_frame=1',flush=True)
