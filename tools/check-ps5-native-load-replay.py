#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Replay observed native GPU command counts under 1x/4x/8x host stress.

The native SPSC stop-aware producer method is extracted from the complete
GPU queue header selected for production. The ring shim is the existing regression fixture, NOT the
PS5 GPU or the guest's HLE implementation. The 28-minute stalled scenario is
advanced in virtual counters; we do NOT claim 28 minutes of wall-clock testing
or emulate the firmware scheduler/driver.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
capture = json.loads((root / "tools/fixtures/native-load-20261013.json").read_text())
assert capture["schema"] == 1
fields = capture["window_fields"]
stfields = capture["stall_fields"]
window = [dict(zip(fields, values)) for values in capture["windows"]]
stalls = [dict(zip(stfields, values)) for values in capture["stalls"]]
assert len(window) == capture["expected_window_count"] == 68
assert len(stalls) == capture["expected_stall_count"] == 55
assert window[-1]["total"] == 9480
assert all(x["total"] == sum(y["frames"] for y in window[:i+1])+1
           for i, x in enumerate(window))
assert sum(x["frames"] for x in window) == 9479
assert abs(sum(x["seconds"] for x in window)-341.505307) < 0.001
assert max(x["worst_ms"] for x in window) >= 575
assert sum(x["late500"] for x in window) == 2
assert len([x for x in window if x["fps"] < 25]) >= 3
assert stalls[-1]["age_ms"]-stalls[0]["age_ms"] == 1_669_171
assert all(x["gpu_ticks"] == 9514 and x["frame"] == 9480 and
           x["guest_writes"] == 3123456 and x["guest_dequeues"] == 9515
           for x in stalls)
assert all(a["age_ms"] < b["age_ms"] and a["guest_ipc"] < b["guest_ipc"]
           for a, b in zip(stalls, stalls[1:]))
ipc_delta = stalls[-1]["guest_ipc"]-stalls[0]["guest_ipc"]
assert ipc_delta == 1_259_768
pad_delta = capture["pad_aggregate"]
assert pad_delta["polls_delta"] == 497_500
assert pad_delta["errors_delta"] == 0
assert pad_delta["samples_delta"] > pad_delta["polls_delta"]
ipc_per_second = ipc_delta / ((stalls[-1]["age_ms"]-stalls[0]["age_ms"])/1000)
assert 750 < ipc_per_second < 760

# Keep the existing SPSC host harness but inject the actual maintained
# queue member, not a retired CMake injection fragment. All producer tests
# share the same source of truth.
host = (root / "tools/check-ps5-gpu-producer-wake.py").read_text()
start = host.index('cpp = r"""') + len('cpp = r"""')
end = host.index('""".replace("STOP_CODE", inc)', start)
cpp = host[start:end]
assert cpp.count("int main() {") == 1
queue_header = (root / "vendor/encore-active/eden-gpu/include/common/bounded_threadsafe_queue.h").read_text()
method_start = "    template <typename... Args>\n    bool EmplaceWaitWithStopToken("
method_end = "\n\n    bool TryPop("
assert queue_header.count(method_start) == 1
begin = queue_header.index(method_start)
end_method = queue_header.index(method_end, begin)
method = queue_header[begin:end_method].strip()
assert "producer.cv.wait(lock, stop_token" in method
# The maintained queue constructs only after acquiring a free slot. Pop
# destroys the moved-from value before publishing that slot as reusable:
# destroying it again in the producer is a double-destruction bug.
assert "std::construct_at(std::addressof(m_data[pos].value)" in method
assert "std::destroy_at(" not in method
assert "union Slot {" in queue_header
assert "std::destroy_at(std::addressof(m_data[pos].value));" in queue_header
assert "std::destroy_at(std::addressof(m_data[cursor % Capacity].value));" in queue_header
assert "std::construct_at(std::addressof(m_data[write_index%Capacity].value)" in cpp
assert "std::destroy_at(std::addressof(m_data[read_index%Capacity].value));" in cpp
queue_source = cpp.split("int main() {")[0].replace("STOP_CODE", method)
assert "STOP_CODE" not in queue_source

# One queue item corresponds to one observed GPU-tick-sized source workload
# rather than a draw, CPU instruction, guest write or IPC service call.
frames = ",".join(str(x["frames"]) for x in window)
gpu_load_ms = ",".join(str(x["gpu_dispatch_ms"]) for x in window)
gpu_idle_ms = ",".join(str(x["gpu_idle_ms"]) for x in window)
baseline = stalls[0]
test = r"""
int main() {
    using namespace std::chrono_literals;
    const std::array<unsigned,68> frames{__FRAMES__};
    const std::array<double,68> dispatch_ms{__DISPATCH__};
    const std::array<double,68> idle_ms{__IDLE__};
    unsigned total{};
    const unsigned recorded_draws=__DRAWS__;
    const unsigned recorded_guest_writes=__WRITES__;
    const unsigned recorded_guest_ipc=__IPC_START__;
    double dispatch{}, idle{};
    for (size_t i=0; i<frames.size(); ++i) {
        total+=frames[i];
        dispatch+=dispatch_ms[i];
        idle+=idle_ms[i];
        assert(frames[i]>=100 && frames[i]<=151);
        assert(dispatch_ms[i]>=0 && idle_ms[i]>=0);
    }
    assert(total==9479);
    assert(idle>dispatch*2.0); // GPU owner NOT saturated before freeze.
    // Real recorded command pacing AND a 4x/8x stress envelope, with a bounded
    // 32-slot native ring and simultaneous IPC/graphics/pad-like CPU demand.
    for (int factor : {1,4,8}) {
        Queue<unsigned,32> q;
        std::stop_source source;
        const unsigned expected=total*factor;
        std::atomic<unsigned> blocked{0};
        std::atomic<unsigned> drawn{0};
        std::atomic<unsigned long long> synthetic_draws{0}, synthetic_writes{0};
        std::atomic<unsigned long long> checksum{0};
        std::atomic<unsigned> background{0};
        std::thread producer([&] {
            unsigned seq=0;
            for(auto size:frames) {
                for(unsigned i=0;i<size*static_cast<unsigned>(factor);i++) {
                    if (!q.TryEmplace(seq)) {
                        blocked.fetch_add(1,std::memory_order_relaxed);
                        assert(q.EmplaceWaitWithStopToken(source.get_token(),seq));
                    }
                    ++seq;
                }
            }
            assert(seq==expected);
        });
        std::thread renderer([&] {
            unsigned long long work=0, draw_ops=0, write_ops=0;
            std::array<unsigned,8192> fake_guest_memory{};
            const unsigned long long total_draw_ops=static_cast<unsigned long long>(recorded_draws)*factor;
            const unsigned long long total_write_ops=static_cast<unsigned long long>(recorded_guest_writes)*factor;
            for(unsigned i=0;i<expected;i++) {
                unsigned value{};
                while (!q.TryPop(value)) std::this_thread::yield();
                assert(value==i); // FIFO, no duplicate/missing GPU command.
                // Synthetic cost variation; never equate host iterations with
                // firmware driver time. Helps expose producer/consumer races.
                unsigned long long acc=value+1;
                const unsigned long long n_draws=total_draw_ops/expected+(i<total_draw_ops%expected);
                const unsigned long long n_writes=total_write_ops/expected+(i<total_write_ops%expected);
                for(unsigned long long draw=0;draw<n_draws;draw++)
                    acc=(acc*6364136223846793005ULL+1442695040888963407ULL);
                for(unsigned long long j=0;j<n_writes;j++)
                    fake_guest_memory[(acc+j)&8191u]^=static_cast<unsigned>(i+j+1);
                draw_ops+=n_draws;
                write_ops+=n_writes;
                work^=acc;
                drawn.fetch_add(1,std::memory_order_relaxed);
            }
            for (auto value:fake_guest_memory) work ^= value;
            synthetic_draws.store(draw_ops,std::memory_order_release);
            synthetic_writes.store(write_ops,std::memory_order_release);
            checksum.store(work,std::memory_order_release);
        });
        std::thread ipc([&] {
            const unsigned loops=recorded_guest_ipc*factor;
            unsigned local=0;
            for(unsigned n=0;n<loops;n++)local+=(n&1);
            background.fetch_add(loops,std::memory_order_relaxed);
            assert(local==loops/2);
        });
        producer.join();renderer.join();ipc.join();
        unsigned value{};
        assert(!q.TryPop(value));
        assert(drawn.load()==expected);
        assert(background.load()==recorded_guest_ipc*factor);
        assert(synthetic_draws.load()==static_cast<unsigned long long>(recorded_draws)*factor);
        assert(synthetic_writes.load()==static_cast<unsigned long long>(recorded_guest_writes)*factor);
        std::printf("LOAD_FACTOR %dx command_units=%u draw_like_ops=%llu "
                    "guest_write_like_ops=%llu ipc_work=%u bounded_queue=32 "
                    "producer_waits=%u checksum=%llu\n",
                    factor,expected,synthetic_draws.load(),synthetic_writes.load(),
                    recorded_guest_ipc*factor,blocked.load(),checksum.load());
    }
    // Exact observed 1,669-second interval is VIRTUAL. Exercise actual
    // producer full-queue blocking while IPC + pad pathways keep progressing.
    // This mimics the observed counter *pattern*, NOT its missing GPU cause.
    {
        Queue<unsigned,32> q;
        for(unsigned i=0;i<32;i++) assert(q.TryEmplace(i));
        std::stop_source stop;
        std::promise<bool> done;
        auto response=done.get_future();
        std::thread blocked([&] {
            done.set_value(q.EmplaceWaitWithStopToken(stop.get_token(),32));
        });
        assert(response.wait_for(15ms)==std::future_status::timeout);
        std::atomic<unsigned> ipc{0},pads{0};
        std::thread ipc_thread([&] {
            for(unsigned i=0;i<1259768;i++)ipc.fetch_add(1,std::memory_order_relaxed);
        });
        std::thread pad_thread([&] {
            for(unsigned i=0;i<497500;i++)pads.fetch_add(1,std::memory_order_relaxed);
        });
        ipc_thread.join();pad_thread.join();
        assert(response.wait_for(1ms)==std::future_status::timeout);
        assert(ipc.load()==1259768 && pads.load()==497500);
        stop.request_stop();
        assert(response.wait_for(2s)==std::future_status::ready);
        assert(!response.get());
        blocked.join();
        unsigned value=0;
        for(unsigned i=0;i<32;i++)assert(q.TryPop(value) && value==i);
        assert(!q.TryPop(value));
        std::puts("VIRTUAL_FREEZE: zero GPU progress + 1259768 IPC + 497500 pad polls "
                  "with blocked native producer, safe cancellation");
    }
    std::puts("HOST STRESS PASS: native queue stays FIFO/bounded under record-derived load");
}
""".replace("__FRAMES__",frames).replace("__DISPATCH__",gpu_load_ms).replace("__IDLE__",gpu_idle_ms)
test = (test.replace("__DRAWS__",str(baseline["draws"]))
        .replace("__WRITES__",str(baseline["guest_writes"]))
        .replace("__IPC_START__",str(baseline["guest_ipc"])))
compiler = shutil.which("clang++-18") or shutil.which("clang++") or shutil.which("g++")
assert compiler, "C++20 compiler required"
with tempfile.TemporaryDirectory(prefix="eden-native-recorded-pressure-") as tmp:
    src = Path(tmp)/"native-stress.cpp"
    exe = Path(tmp)/"native-stress"
    src.write_text(queue_source+test)
    sanitize = os.environ.get("EDEN_STRESS_SANITIZE") == "1"
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitize else []
    subprocess.run([compiler,"-std=c++20","-O2","-pthread","-Wall","-Wextra","-Werror",
                    *flags,str(src),"-o",str(exe)],check=True,timeout=60)
    subprocess.run([str(exe)],check=True,timeout=55)
print("QUALIFICATION: source-derived workload, NOT the original game, kernel, GPU or Vulkan driver")
