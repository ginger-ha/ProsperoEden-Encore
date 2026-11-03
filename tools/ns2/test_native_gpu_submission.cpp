// SPDX-License-Identifier: GPL-3.0-or-later
#include <array>
#include <cstddef>
#include <cstdio>
#include <cstdlib>

#include "core/hle/service/nvdrv/devices/native_gpu_process_registry.h"
#include "core/hle/service/nvdrv/devices/native_gpu_submission.h"

namespace N = Service::Nvidia::Devices;

static void require(bool ok, const char* message) {
    if (!ok) {
        std::fprintf(stderr, "NS2 native GPFIFO: FAILED: %s\n", message);
        std::exit(1);
    }
}
int main() {
    alignas(std::max_align_t) std::array<unsigned char, 128> storage{};
    auto* p = reinterpret_cast<Kernel::KProcess*>(storage.data());
    auto* q = reinterpret_cast<Kernel::KProcess*>(storage.data() + 32);
    auto& registry = N::NativeGpuProcessRegistry::Instance();
    require(!registry.Contains(nullptr) && !registry.Contains(p) &&
            registry.Count() == 0, "default deny before GPU session bootstrap");
    require(!registry.Register(nullptr), "reject null process");
    require(registry.Register(p) && registry.Register(p) &&
            registry.Register(q) && registry.Count() == 2,
            "refcount multiple GPU sessions for one process");
    registry.Unregister(p);
    require(registry.Contains(p), "one owner keeps process native mode");
    registry.Unregister(p);
    require(!registry.Contains(p) && registry.Contains(q),
            "release only final process owner");
    registry.Unregister(p);
    registry.Unregister(q);
    require(registry.Count() == 0, "process register/unregister cleanup");

    require(!N::PlanNativeSubmission(0, 0, false),
            "native command rejected until channel GMMU initialized");
    require(!N::PlanNativeSubmission(1u | 0x100u, 2, true),
            "cannot acquire fence and issue native completion simultaneously");
    require(!N::PlanNativeSubmission(0x100u, 65, true),
            "native completion capped at 64");
    require(!N::PlanNativeSubmission(0x400u, 0, true),
            "unknown native fence flag is rejected");
    const auto native = N::PlanNativeSubmission(0x100u, 3, true);
    require(native && native->completion_count == 3 &&
            native->increment_total == 3,
            "native 3-count completion follows GPU work");
    const auto legacyStyle = N::PlanNativeSubmission(2u | 0x100u, 7, true);
    require(legacyStyle && legacyStyle->completion_count == 7 &&
            legacyStyle->increment_total == 9,
            "combined native and normal fence emits all nine promised increments");
    // Regression: native max incremented by 9, ordered queue must emit 2+7.
    for (std::uint32_t count = 0; count <= 64; ++count) {
        const auto mixed = N::PlanNativeSubmission(2u | 0x100u, count, true);
        require(mixed && mixed->completion_count == count &&
                mixed->increment_total == count + 2,
                "mixed fence count exactly matches scheduled queue increments");
    }
    const auto fence = N::PlanNativeSubmission(2u | 16u, 0, true);
    require(fence && fence->completion_count == 0 &&
            fence->increment_total == 2,
            "WFI suppression preserves two legacy fence increments");
    const auto noFence = N::PlanNativeSubmission(0, 0, true);
    require(noFence && noFence->increment_total == 0,
            "empty native submission does not fabricate a fence");
    // P2.7: this exact helper is invoked by the real native H:0x1b
    // kickoff owner before ReadBlock or any GPU queue submission.
    // Fence-only submission must never dereference a guest pointer.
    unsigned range_checks = 0;
    const auto mapped = [&](std::uint64_t address, std::size_t bytes) {
        ++range_checks;
        return address == 0x1000 && bytes == 16;
    };
    require(N::NativeGpfifoGuestHeadersReadable(0, 0, 8, mapped) &&
            range_checks == 0,
            "zero-entry fence-only submission does not access guest RAM");
    require(N::NativeGpfifoGuestHeadersReadable(0x1000, 2, 8, mapped) &&
            range_checks == 1,
            "full two-header guest span admitted in the owning process");
    require(!N::NativeGpfifoGuestHeadersReadable(0x1000, 1, 8, mapped) &&
            range_checks == 2,
            "partial mapping is not enough to acknowledge a native submit");
    require(!N::NativeGpfifoGuestHeadersReadable(0, 1, 8, mapped) &&
            range_checks == 2,
            "missing guest pointer rejected before map lookup");
    require(!N::NativeGpfifoGuestHeadersReadable(
                std::numeric_limits<std::uint64_t>::max() - 7, 2, 8, mapped) &&
            range_checks == 2,
            "guest start plus command bytes cannot overflow 64-bit VA");
    require(!N::NativeGpfifoGuestHeadersReadable(
                0x1000, 2, std::numeric_limits<std::size_t>::max(), mapped) &&
            range_checks == 2,
            "count multiplied by command width cannot overflow size_t");
    require(!N::NativeGpfifoGuestHeadersReadable(0x1000, 1, 0, mapped) &&
            range_checks == 2,
            "zero-sized command headers rejected");
    std::puts("NS2 process-scoped native GPFIFO preflight: PASS");
}
