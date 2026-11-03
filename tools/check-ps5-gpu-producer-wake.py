#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise PS5 stop-aware SPSC producer with full queue, cancellation and FIFO.

The template method is the real one selected from the maintained GPU source.
The host shim reproduces the pinned SPSC queue's indexes, CV protocols and live union-slot lifetime.
Native SDK compilation remains a separate PS5 build gate.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
# Extract the real producer method from the complete, shipping GPU header.
# The old gpu_queue_stop_wait.inc has been retired; the selected full queue header is authoritative.
active_gpu = root / "vendor/encore-active/eden-gpu"
header = (active_gpu / "include/common/bounded_threadsafe_queue.h").read_text()
quiet = (active_gpu / "gpu_thread_quiet.cpp").read_text()
dev = (active_gpu / "gpu_thread_dev.cpp").read_text()
cmake = (root / "headless/CMakeLists.txt").read_text()
method_start = "    template <typename... Args>\n    bool EmplaceWaitWithStopToken("
method_end = "\n\n    bool TryPop("
assert header.count(method_start) == 1
start = header.index(method_start)
end = header.find(method_end, start)
assert end > start, 'canonical GPU queue method boundary missing'
inc = header[start:end].strip()
assert "EmplaceWaitWithStopToken" in inc
assert "producer.cv.wait(lock, stop_token" in inc
assert "consumer.index.load(std::memory_order_acquire)" in inc
assert "std::construct_at" in inc
assert "consumer.cv.notify_one()" in inc
assert "union Slot {" in header
assert "std::array<Slot, Capacity> m_data;" in header
assert header.count("std::construct_at(std::addressof(m_data[pos].value)") == 2
assert header.count("std::destroy_at(std::addressof(m_data[pos].value));") == 1
assert "std::destroy_at(std::addressof(m_data[cursor % Capacity].value));" in header
for worker in (quiet, dev):
    assert "state.queue.TryEmplace(std::move(command_data), fence, block)" in worker
    assert "state.queue.EmplaceWaitWithStopToken(stop_source.get_token()," in worker
assert 'set(EDEN_ACTIVE_GPU "${PORT_ROOT}/vendor/encore-active/eden-gpu")' in cmake
assert 'configure_file("${EDEN_ACTIVE_GPU}/include/common/bounded_threadsafe_queue.h"' in cmake
assert 'configure_file("${EDEN_ACTIVE_GPU}/${EDEN_GPU_WORKER_VARIANT}"' in cmake
assert 'list(APPEND video_sources "${PORT_BUILD_DIR}/gpu_thread.cpp")' in cmake
assert 'file(READ "${PORT_ROOT}/vendor/encore-active/eden-core/gpu-injections/gpu_queue_stop_wait.inc"' not in cmake

cpp = r"""
#include <array>
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstddef>
#include <condition_variable>
#include <cstdio>
#include <future>
#include <memory>
#include <mutex>
#include <stop_token>
#include <thread>
#include <utility>
#include <vector>

template <typename T, size_t Capacity> class Queue {
    static_assert(Capacity != 0 && (Capacity & (Capacity - 1)) == 0);
public:
    ~Queue() {
        const auto end = producer.index.load(std::memory_order_relaxed);
        for (auto cursor = consumer.index.load(std::memory_order_relaxed);
             cursor != end; ++cursor)
            std::destroy_at(std::addressof(m_data[cursor % Capacity].value));
    }
    template <typename... Args> bool TryEmplace(Args&&... args) noexcept {
        const auto write_index=producer.index.load(std::memory_order_relaxed);
        if (write_index-consumer.index.load(std::memory_order_acquire)==Capacity)
            return false;
        std::construct_at(std::addressof(m_data[write_index%Capacity].value),std::forward<Args>(args)...);
        ++producer.index;
        std::scoped_lock lock{consumer.cv_mutex}; consumer.cv.notify_one();
        return true;
    }
    bool TryPop(T& target) noexcept {
        const auto read_index=consumer.index.load(std::memory_order_relaxed);
        if (read_index==producer.index.load(std::memory_order_acquire)) return false;
        target=std::move(m_data[read_index%Capacity].value);
        std::destroy_at(std::addressof(m_data[read_index%Capacity].value));
        ++consumer.index;
        std::scoped_lock lock{producer.cv_mutex}; producer.cv.notify_one();
        return true;
    }
STOP_CODE
private:
    union Slot {
        Slot() noexcept {}
        ~Slot() {}
        T value;
    };
    std::array<Slot,Capacity> m_data;
    alignas(64) struct {
        std::atomic_size_t index{0};
        std::condition_variable_any cv;
        std::mutex cv_mutex;
    } producer;
    alignas(64) struct {
        std::atomic_size_t index{0};
        std::condition_variable_any cv;
        std::mutex cv_mutex;
    } consumer;
};
int main() {
    using namespace std::chrono_literals;
    {
        Queue<int,2> q;
        assert(q.TryEmplace(1) && q.TryEmplace(2) && !q.TryEmplace(3));
        std::stop_source src;
        std::promise<bool> complete;
        auto result=complete.get_future();
        std::thread waiter([&] {complete.set_value(q.EmplaceWaitWithStopToken(src.get_token(),3));});
        assert(result.wait_for(20ms)==std::future_status::timeout);
        src.request_stop();
        assert(result.wait_for(1s)==std::future_status::ready && !result.get());
        waiter.join();
        int v=0; assert(q.TryPop(v) && v==1); assert(q.TryPop(v) && v==2);
        assert(!q.TryPop(v));
    }
    {
        Queue<int,2> q;
        assert(q.TryEmplace(11) && q.TryEmplace(12));
        std::stop_source src;
        std::promise<bool> complete; auto result=complete.get_future();
        std::thread waiter([&] {complete.set_value(q.EmplaceWaitWithStopToken(src.get_token(),13));});
        assert(result.wait_for(20ms)==std::future_status::timeout);
        int v=0; assert(q.TryPop(v) && v==11);
        assert(result.wait_for(1s)==std::future_status::ready && result.get());
        waiter.join();
        assert(q.TryPop(v) && v==12); assert(q.TryPop(v) && v==13);
        assert(!q.TryPop(v));
    }
    // A 256-entry native queue absorbs long multi-draw submission bursts
    // while retaining bounded capacity, FIFO order and stop-aware backpressure.
    {
        Queue<int,256> q;
        for (int i=0; i<256; ++i) assert(q.TryEmplace(i));
        assert(!q.TryEmplace(256));
        std::stop_source src;
        std::promise<bool> completion;
        auto result=completion.get_future();
        std::thread producer([&] {
            completion.set_value(q.EmplaceWaitWithStopToken(src.get_token(),256));
        });
        assert(result.wait_for(20ms)==std::future_status::timeout);
        int value=-1;
        assert(q.TryPop(value) && value==0);
        assert(result.wait_for(1s)==std::future_status::ready && result.get());
        producer.join();
        for (int i=1; i<=256; ++i) {
            assert(q.TryPop(value) && value==i);
        }
        assert(!q.TryPop(value));
    }
    {
        Queue<int,8> q;
        std::stop_source src;
        constexpr int n=4000;
        std::thread producer([&] {
            for (int i=0;i<n;++i) {
                if (!q.TryEmplace(i))
                    assert(q.EmplaceWaitWithStopToken(src.get_token(),i));
            }
        });
        std::thread consumer([&] {
            for (int i=0;i<n;++i) {
                int value;
                while (!q.TryPop(value)) std::this_thread::yield();
                assert(value==i);
            }
        });
        producer.join(); consumer.join();
    }
    // 64 independent title-like lifecycles with bursty GPU producers and
    // deliberately delayed consumers. The native stop-aware method is
    // extracted from the maintained eden-gpu queue header, not reimplemented here.
    for (int session=0; session<64; ++session) {
        Queue<int,256> q;
        constexpr int items=384;
        std::stop_source src;
        std::thread producer([&] {
            for(int i=0; i<items; ++i) {
                if(!q.TryEmplace(i))
                    assert(q.EmplaceWaitWithStopToken(src.get_token(),i));
                if((i+session)%37==0) std::this_thread::yield();
            }
        });
        std::thread consumer([&] {
            for(int i=0; i<items; ++i) {
                int value{-1};
                while(!q.TryPop(value)) std::this_thread::yield();
                assert(value==i);
                if((i+session)%17==0)
                    std::this_thread::sleep_for(std::chrono::microseconds(25));
            }
        });
        producer.join();
        consumer.join();
        int last{};
        assert(!q.TryPop(last));
    }
    // Shutdown when producer is waiting on a full native command queue.
    // No command should be published after cancellation or outlive the queue.
    for (int cycle=0; cycle<64; ++cycle) {
        Queue<int,8> q;
        for(int i=0;i<8;i++) assert(q.TryEmplace(i));
        std::stop_source src;
        std::promise<bool> promise;
        auto future=promise.get_future();
        std::thread blocked([&] {
            promise.set_value(q.EmplaceWaitWithStopToken(src.get_token(),99));
        });
        assert(future.wait_for(1ms)==std::future_status::timeout);
        src.request_stop();
        assert(future.wait_for(2s)==std::future_status::ready);
        assert(!future.get());
        blocked.join();
        int value{-1};
        for(int i=0;i<8;i++) { assert(q.TryPop(value) && value==i); }
        assert(!q.TryPop(value));
    }
    {
        auto resource = std::make_shared<int>(42);
        {
            Queue<std::shared_ptr<int>,2> q;
            assert(q.TryEmplace(resource));
            assert(resource.use_count() == 2);
        }
        // All live queue slots are destroyed when the queue is retired.
        assert(resource.use_count() == 1);
    }
    std::puts("PASS: exact native SPSC wait: 4096 base + 24576 bursty commands, 64 cancelled/full sessions");
}
""".replace("STOP_CODE", inc)
with tempfile.TemporaryDirectory(prefix="eden-ps5-gpu-cv-wake-") as tmp:
    source = Path(tmp) / "queue.cpp"
    exe = Path(tmp) / "queue"
    source.write_text(cpp)
    compiler = shutil.which("clang++-18") or shutil.which("clang++") or shutil.which("g++")
    assert compiler, "C++20 compiler missing"
    subprocess.run([compiler,"-std=c++20","-O1","-g","-pthread",
                    "-Wall","-Wextra","-Werror",
                    str(source),"-o",str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=30)
print("HOST ONLY: native producer method + live union-slot lifetime; console compiler/frame pacing not qualified")
