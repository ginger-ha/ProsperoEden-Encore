#!/usr/bin/env python3
"""Compile PS5 persistent-worker prewarm quota and token separation scenarios.

Only the file reader may be cancelled by reaching the quota. All queued jobs
must join before the borrowed state goes out of scope; actual shader workers
remain eligible for new gameplay jobs. Prevent full-cache rebuild at boot.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
main=(root/"headless/main.cpp").read_text()
shader=(root/"vendor/encore-active/eden-vulkan/vk_pipeline_cache_cost.cpp").read_text()
gen=(root/"tools/prepare-vulkan-port.py").read_text()
worker=(root/"vendor/sources/eden/src/common/thread_worker.h").read_text()
begin="void PipelineCache::LoadDiskResources("
end="\nvoid PipelineCache::QueueVulkanPipelineCacheFlush()"
method=begin+shader.split(begin,1)[1].split(end,1)[0]
assert shader.count(begin)==1 and shader.count(end)==1
assert method.count("++state.total;")==2
# Counter writes must synchronize with progress reads in both worker callbacks.
assert method.count("std::scoped_lock count_lock{state.mutex};") == 2
assert method.count("++state.total;") == 2
assert method.count("        }\n#ifdef PS5_NATIVE\n        if (state.total == kStartupPrewarmPipelines)") == 2
assert 'shader_source.count(f07_prewarm_total_old) != 2' in gen
assert 'shader_source = shader_source.replace(f07_prewarm_total_old, f07_prewarm_total_new)' in gen

assert method.count("if (state.total == kStartupPrewarmPipelines)")==2
assert method.count("startup_reader.request_stop();")==2
assert "constexpr size_t kStartupPrewarmPipelines = 32;" in method
assert "kFc27TitleId" not in method and "kFc27PrewarmPipelines" not in method
assert "std::stop_source startup_reader;" in method
assert "const std::stop_token reader_token{startup_reader.get_token()};" in method
assert "VideoCommon::LoadPipelines(reader_token" in method
assert "#ifdef PS5_NATIVE\n    // A cancelled title-cache load" in method
assert "    workers.WaitForRequests();\n    prewarm_drain.joined = true;\n#else\n    workers.WaitForRequests(stop_loading);\n#endif" in method
assert method.count("    workers.WaitForRequests(stop_loading);") == 1
assert "StatefulThreadWorker::WaitForRequests(stop_token)" in method
assert "    workers.WaitForRequests();" in gen
assert "    workers.WaitForRequests(stop_loading);" in gen
assert "workers.WaitForRequests(reader_token)" not in method
assert 'mode=bounded-prewarm32' in main
assert 'lazy_cache.request_stop();' not in main
assert "for (auto& thread : threads) {" in worker
assert "thread.request_stop();" in worker
for i in range(5):
    assert f"shader_source.count(f07_warm_before_{i})" in gen
assert "#include <stop_token>" in shader
# The pinned generator must write the FINAL prewarm source, not a stale
# pre-transformation snapshot. The full fork reproduction also checks bytes.
assert gen.index("shader_source = shader_source.replace(f07_warm_before_4, f07_warm_after_4)") < gen.index("shader_output.write_text(shader_source)")
assert gen.count("shader_output.write_text(shader_source)") == 1

cpp=r"""
#include <cassert>
#include <cstddef>
#include <stop_token>
#include <functional>
#include <vector>
constexpr std::size_t kStartupPrewarmPipelines = 32;
struct Worker {
    bool alive=true;
    size_t done=0;
    std::vector<std::function<void()>> pending;
    void QueueWork(std::function<void()> job){ assert(alive); pending.push_back(std::move(job)); }
    void WaitForRequests(std::stop_token token={}) {
        if(token.stop_requested()) alive=false;
        for(auto& work:pending){work(); ++done;}
        pending.clear();
    }
};
std::size_t Run(std::size_t persisted, Worker& workers, bool init_only=false,
                bool cancel_title=false) {
    if(init_only) return 0;  // legacy setup-only compatibility
    std::stop_source startup_reader;
    std::size_t queued=0;
    for(std::size_t i=0;i<persisted && !startup_reader.stop_requested();++i) {
        workers.QueueWork([]{});
        ++queued;
        if(queued == kStartupPrewarmPipelines)
            startup_reader.request_stop();
    }
    // Mimic cancellation after at most 32 jobs were admitted.
    // Only the cache reader stops. The shader builder must remain alive.
    std::stop_source title;
    if(cancel_title) title.request_stop();
    workers.WaitForRequests();
    assert(!cancel_title || title.stop_requested());
    assert(workers.alive); // never forward startup_reader.get_token()
    return queued;
}
int main(){
    for(auto persisted:{0u,1u,7u,8u,9u,31u,32u,33u,128u,50000u}){
        Worker workers;
        auto count=Run(persisted,workers);
        assert(count==(persisted<kStartupPrewarmPipelines?persisted:kStartupPrewarmPipelines));
        assert(workers.done==count);
        // First-use compilation after prewarm must remain possible.
        workers.QueueWork([]{});
        workers.WaitForRequests();
        assert(workers.done==count+1);
        assert(Run(1, workers, true)==0);
        Worker canceled;
        assert(Run(persisted, canceled, false, true)==count);
        assert(canceled.alive && canceled.done==count);
        canceled.QueueWork([]{});
        canceled.WaitForRequests();
        assert(canceled.done==count+1);
    }
    Worker negative;
    std::stop_source canceled;
    canceled.request_stop();
    negative.WaitForRequests(canceled.get_token());
    assert(!negative.alive); // why reader token must NOT be sent to worker
}
"""
compiler=shutil.which("clang++") or shutil.which("g++")
assert compiler, "C++20 compiler required"
with tempfile.TemporaryDirectory(prefix="eden-f07-prewarm-") as d:
    p=Path(d)/"test.cpp";p.write_text(cpp)
    for optimization in ("-O0","-O2"):
        exe=Path(d)/("test"+optimization[1:])
        subprocess.run([compiler,"-std=c++20",optimization,"-Wall","-Wextra","-Werror",
                        str(p),"-o",str(exe)],check=True,capture_output=True,text=True,timeout=35)
        subprocess.run([str(exe)],check=True,timeout=15)
# Compile the actual selected prewarm reader, scope guard and join branch.
# Exercise normal completion, disk-reader failure and callback failure. The
# callback exception used to escape before the worker join, making borrowed
# reader state unsafe. All jobs must finish before the local state dies.
start='#ifdef PS5_NATIVE\n    // The progress callback below also runs'
finish='#ifdef PS5_NATIVE\n    // Completed attempts'
assert method.count(start)==1 and method.count(finish)==1
assert "struct PrewarmDrain" in gen and "prewarm_drain.joined = true;" in gen
prefix=method[method.index(start):method.index('    LOG_INFO(Render_Vulkan, "Total Pipeline Count:')]
suffix=method[method.index('#ifdef PS5_NATIVE\n    // A cancelled title-cache load'):method.index(finish)]
assert "PS5 shader prewarm aborted" in prefix
assert prefix.index("struct PrewarmDrain") < prefix.index("VideoCommon::LoadPipelines(")
assert "prewarm_drain.joined = true;" in suffix
assert "workers.WaitForRequests(reader_token)" not in prefix+suffix
reader_harness=r"""
#include <cassert>
#include <cstddef>
#include <functional>
#include <stdexcept>
#include <stop_token>
#include <string>
#include <utility>
#include <vector>
#define PS5_NATIVE 1
#define Render_Vulkan 0
template<class... T> void mock_log(const char*, T&&...) {}
#define LOG_WARNING(tag, fmt, ...) mock_log(fmt, ##__VA_ARGS__)
struct Worker {
    bool live=true;
    unsigned drained=0;
    unsigned joins=0;
    std::vector<std::function<void()>> pending;
    void QueueWork(std::function<void()> job) {
        assert(live);
        pending.push_back(std::move(job));
    }
    void WaitForRequests(std::stop_token token={}) {
        ++joins;
        if (token.stop_requested()) live=false;
        auto jobs=std::move(pending);
        for(auto& job:jobs) { job(); ++drained; }
        pending.clear();
    }
};
namespace Common { using ThreadWorker=::Worker; }
static bool reader_failure=false;
namespace VideoCommon {
template<class A,class B>
void LoadPipelines(std::stop_token, const std::string&, int, A&& compute, B&& graphics) {
    compute();
    if(reader_failure) throw std::runtime_error("interrupted shader cache");
    graphics();
}
}
void RunReader(bool fail, bool progress_failure) {
    reader_failure=fail;
    Worker workers;
    bool state_alive=true;
    unsigned built=0;
    std::stop_source startup_reader;
    const std::stop_token reader_token{startup_reader.get_token()};
    std::string pipeline_cache_filename{"cache.bin"};
    constexpr int CACHE_VERSION=1;
    auto load_compute=[&] { workers.QueueWork([&] {assert(state_alive); ++built;}); };
    auto load_graphics=[&] { workers.QueueWork([&] {assert(state_alive); ++built;}); };
    bool caught=false;
    try {
    {
""" + prefix + r"""
        // The actual progress callback is external to this extracted branch.
        if (progress_failure) throw std::runtime_error("progress callback");
""" + suffix + r"""
    }
    } catch(const std::runtime_error&) { caught=true; }
    assert(caught==progress_failure);
    state_alive=false;
    assert(workers.pending.empty());
    assert(workers.live);
    assert(workers.joins==1);
    assert(built==(fail ? 1u : 2u));
    workers.QueueWork([]{}); // new first-use builds remain admissible
    workers.WaitForRequests();
    assert(workers.drained==(fail ? 2u : 3u));
}
int main() {
    for (bool fail:{false,true})
        for (bool progress:{false,true})
            RunReader(fail,progress);
}
"""
with tempfile.TemporaryDirectory(prefix="eden-f07-prewarm-exception-") as d:
    p=Path(d)/"reader.cpp";p.write_text(reader_harness)
    for optimization in ("-O0","-O2"):
        exe=Path(d)/("reader"+optimization[1:])
        subprocess.run([compiler,"-std=c++20",optimization,"-Wall","-Wextra","-Werror",
                        str(p),"-o",str(exe)],check=True,capture_output=True,text=True,timeout=35)
        subprocess.run([str(exe)],check=True,timeout=15)
print("F07_PREWARM_EXCEPTION_JOIN_PASS read_error=1 callback_error=1 join_once=1 O0=1 O2=1")

print("F07_BOUND_PREWARM_HOST_PASS cap=32 reader_only_cancel=1 workers_persist=1 O0=1 O2=1")
