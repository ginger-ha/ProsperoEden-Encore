#!/usr/bin/env python3
"""Execute pinned GPU queue slot lifetime; reject a skipped moved-from destructor.

The original queue overwrites still-live preconstructed elements and leaks
resource owners. The maintained common GPU queue now has explicit Slot storage:
a successful push constructs its element, Pop destroys it *before* publishing
the free slot, and destruction of a nonempty queue visits only live entries.
The native-source fixture checks a valid move whose source retains ownership.
No console run or graphics timing claim.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
original = (root / "vendor/sources/eden/src/common/bounded_threadsafe_queue.h").read_text()
cmake = (root / "headless/CMakeLists.txt").read_text()
workflow = (root / ".github/workflows/encore-core-preflight.yml").read_text()
canonical_path = root / "vendor/encore-active/eden-gpu/include/common/bounded_threadsafe_queue.h"
canonical = canonical_path.read_text()
construct = "std::construct_at(std::addressof(m_data[pos]), std::forward<Args>(args)...);"
live_construct = "std::construct_at(std::addressof(m_data[pos].value), std::forward<Args>(args)...);"
live_destroy = "std::destroy_at(std::addressof(m_data[pos].value));"

# Keep the broken pinned source only as a negative regression witness. The
# corrected compiled queue must be the same full header selected in CMake.
assert original.count(construct) == 1
assert original.count("std::destroy_at(std::addressof(m_data[pos]));") == 0
assert canonical.count(construct) == 0
assert canonical.count(live_construct) == 2
assert canonical.count(live_destroy) == 2
assert "union Slot {" in canonical
assert "std::array<Slot, Capacity> m_data;" in canonical
assert "t = std::move(m_data[pos].value);\n        // Destroy moved-from commands before the producer can reuse the slot.\n        " + live_destroy in canonical
assert "for (auto cursor = consumer.index.load(std::memory_order_relaxed);" in canonical
assert "std::destroy_at(std::addressof(m_data[cursor % Capacity].value));" in canonical
assert canonical.count("bool EmplaceWaitWithStopToken(") == 1
assert "producer.cv.wait(lock, stop_token" in canonical
assert "python3 -B tools/check-native-gpu-queue-slot-lifetime-host.py" in workflow
assert 'configure_file("${EDEN_ACTIVE_GPU}/include/common/bounded_threadsafe_queue.h"' in cmake
assert 'write_derived("${PORT_BUILD_DIR}/include/common/bounded_threadsafe_queue.h"' not in cmake
assert not (root / "vendor/encore-active/eden-core/gpu-injections/gpu_queue_stop_wait.inc").exists()

program = r"""
#include <array>
#include <atomic>
#include <cassert>
#include <cstdio>
#include <memory>
#include <stop_token>
#include <thread>
#include <utility>
#include "common/bounded_threadsafe_queue.h"

struct Resource {
    static inline int living{};
    Resource() { ++living; }
    ~Resource() { --living; }
};
struct RetainedAfterMove {
    std::shared_ptr<Resource> payload;
    RetainedAfterMove() = default;
    explicit RetainedAfterMove(const std::shared_ptr<Resource>& resource)
        : payload(resource) {}
    // Valid move operations: the source deliberately keeps an owner.
    RetainedAfterMove(RetainedAfterMove&& other) noexcept
        : payload(other.payload) {}
    RetainedAfterMove& operator=(RetainedAfterMove&& other) noexcept {
        payload = other.payload;
        return *this;
    }
    RetainedAfterMove(const RetainedAfterMove&) = delete;
    RetainedAfterMove& operator=(const RetainedAfterMove&) = delete;
};

int main() {
    {
        Common::SPSCQueue<RetainedAfterMove, 2> q;
        RetainedAfterMove received;
        for (unsigned i = 0; i < 12; ++i) {
            auto resource = std::make_shared<Resource>();
            assert(q.TryEmplace(resource));
            assert(q.TryPop(received));
            assert(received.payload == resource);
            received.payload.reset();
            resource.reset();
        }
#if EXPECT_REPAIRED
        // Pop eagerly destroys each moved-from slot; no abandoned owner remains.
        assert(Resource::living == 0);
#else
        // Baseline has overwritten ten live moved-from owners, leaking each.
        assert(Resource::living == 12);
#endif
    }
#if EXPECT_REPAIRED
    assert(Resource::living == 0);
    std::puts("PINNED_GPU_QUEUE_SLOT_DESTRUCTOR_REUSE_PASS");
#else
    assert(Resource::living == 10);
    std::puts("PINNED_GPU_QUEUE_ORIGINAL_MOVED_FROM_OWNER_LEAK_WITNESS_PASS");
#endif
}
"""
compiler = shutil.which("g++") or shutil.which("clang++")
assert compiler, "C++20 compiler required"
with tempfile.TemporaryDirectory(prefix="encore-native-queue-lifetime-") as folder:
    temp = Path(folder)
    inc = temp / "common"
    inc.mkdir()
    # The upstream polyfill is not involved in the queue slot's semantics.
    (inc / "polyfill_thread.h").write_text("#pragma once\n#include <stop_token>\n")
    code = temp / "queue_lifetime.cpp"
    code.write_text(program)
    for name, source, repaired in (
        ("original", original, False),
        ("maintained", canonical, True),
    ):
        (inc / "bounded_threadsafe_queue.h").write_text(
            "#include <memory>\n#include <stop_token>\n" + source
        )
        binary = temp / name
        subprocess.run(
            [compiler, "-std=c++20", "-O2", "-Wall", "-Wextra", "-Werror",
             "-pthread", "-I", str(temp), "-DEXPECT_REPAIRED=" + str(int(repaired)),
             str(code), "-o", str(binary)], check=True, timeout=30)
        result = subprocess.run([str(binary)], check=True, text=True,
                                capture_output=True, timeout=10)
        print(result.stdout, end="")

print("PINNED_GPU_QUEUE_NATIVE_SLOT_DESTRUCTION_SCOPE_ONLY")
