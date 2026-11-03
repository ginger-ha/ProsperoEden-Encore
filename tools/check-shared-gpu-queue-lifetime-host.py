#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host-only P4.2: exercise the real shared GPU SPSC queue lifetime (NS1/NS2).

The active vendor header is compiled, not a mock queue implementation.
No PS5/native build, GPU calls, or guest code is executed.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "vendor/encore-active/eden-gpu/include/common/bounded_threadsafe_queue.h"
SOURCE = HEADER.read_text()
assert "std::array<Slot, Capacity> m_data;" in SOURCE
assert "std::destroy_at(std::addressof(m_data[pos].value));" in SOURCE
assert "std::construct_at(std::addressof(m_data[pos].value)" in SOURCE
assert "Capacity != 0" in SOURCE

TEST = r"""
#include <cassert>
#include <cstdint>
#include <memory>
#include <stop_token>
#include <utility>
#include "common/bounded_threadsafe_queue.h"

struct Tracked {
    static inline int alive = 0;
    static inline int destroyed = 0;
    int id;
    std::unique_ptr<int> payload;
    Tracked() = delete; // Empty slots must never manufacture a T.
    explicit Tracked(int value) : id(value), payload(std::make_unique<int>(value)) {
        ++alive;
    }
    Tracked(const Tracked&) = delete;
    Tracked& operator=(const Tracked&) = delete;
    Tracked(Tracked&& other) noexcept
        : id(other.id), payload(std::move(other.payload)) { ++alive; }
    Tracked& operator=(Tracked&& other) noexcept {
        id = other.id;
        payload = std::move(other.payload);
        return *this;
    }
    ~Tracked() { --alive; ++destroyed; }
};

int main() {
    // A default-constructed queue must have no live elements, even for
    // a non-default-constructible command/payload type.
    {
        Common::SPSCQueue<Tracked, 4> queue;
        assert(Tracked::alive == 0);
        assert(queue.TryEmplace(17));
        assert(Tracked::alive == 1);
        Tracked output(-1);
        assert(Tracked::alive == 2);
        assert(queue.TryPop(output));
        assert(output.id == 17 && output.payload && *output.payload == 17);
        // A moved-from slot must be destroyed immediately after TryPop,
        // not when a future producer eventually reuses that location.
        assert(Tracked::alive == 1);
        assert(!queue.TryPop(output));
    }
    assert(Tracked::alive == 0);
    {
        Common::SPSCQueue<Tracked, 2> queue;
        assert(queue.TryEmplace(1));
        assert(queue.TryEmplace(2));
        assert(!queue.TryEmplace(3)); // Full: no construction or destruction.
        assert(Tracked::alive == 2);
        // Destruction without popping must retire the two queued payloads.
    }
    assert(Tracked::alive == 0);
    {
        Common::SPSCQueue<Tracked, 2> queue;
        std::stop_source cancel;
        assert(queue.EmplaceWaitWithStopToken(cancel.get_token(), 4));
        assert(queue.EmplaceWaitWithStopToken(cancel.get_token(), 5));
        cancel.request_stop();
        assert(!queue.EmplaceWaitWithStopToken(cancel.get_token(), 6));
        assert(Tracked::alive == 2);
    }
    assert(Tracked::alive == 0);
    // Capacity reuse and cursor wrap retain FIFO and independent slots.
    {
        Common::SPSCQueue<int, 2> queue;
        int observed = -1;
        for (int i = 0; i < 100000; ++i) {
            assert(queue.TryEmplace(i));
            assert(queue.TryPop(observed));
            assert(observed == i);
        }
        assert(!queue.TryPop(observed));
    }
    assert(Tracked::destroyed >= 6);
}
"""

compilers = list(dict.fromkeys(
    path for name in ("clang++", "g++") if (path := shutil.which(name))))
assert compilers, "host C++20 compiler required"
with tempfile.TemporaryDirectory(prefix="encore-gpu-queue-lifetime-") as directory:
    temp = Path(directory)
    stub = temp / "common"
    stub.mkdir()
    (stub / "polyfill_thread.h").write_text("#pragma once\n")
    source = temp / "shared-gpu-queue.cpp"
    source.write_text(TEST)
    for compiler in compilers:
        for opt in ("-O0", "-O2"):
            binary = temp / (Path(compiler).name + opt)
            command = [compiler, "-std=c++20", "-pthread", opt, "-Wall",
                       "-Wextra", "-Werror", "-I", str(temp),
                       "-I", str(HEADER.parents[1]), str(source), "-o", str(binary)]
            built = subprocess.run(command, capture_output=True, text=True, timeout=60)
            assert built.returncode == 0, (compiler, opt, built.stderr[-6000:])
            ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            assert ran.returncode == 0, (compiler, opt, ran.stderr[-6000:])
            print("GPU_SHARED_SPSC_LIFETIME_PASS", Path(compiler).name, opt)
