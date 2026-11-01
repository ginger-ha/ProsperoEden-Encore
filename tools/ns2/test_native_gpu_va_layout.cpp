// SPDX-License-Identifier: GPL-3.0-or-later
// Host-only native GMMU VA fixture; does not submit GPU commands.
#include <cassert>
#include <cstdint>
#include <cstdio>
#include "core/hle/service/nvdrv/devices/native_gpu_va_layout.h"

using Service::Nvidia::Devices::PlanNativeGpuVaLayout;
int main() {
    const auto defaults = PlanNativeGpuVaLayout(0x8000000, 1ULL << 34, 1ULL << 37, 0x20000);
    assert(defaults && defaults->small_begin == 32768 &&
           defaults->small_end == 4194304 && defaults->big_begin == 131072 &&
           defaults->big_end == 1048576);
    // Both FlatAllocator limits are absolute; a relative (end-split)
    // calculation would incorrectly return half this custom large-page end.
    const auto custom = PlanNativeGpuVaLayout(0x1000000, 1ULL << 30, 1ULL << 31, 0x10000);
    assert(custom && custom->big_begin == 16384 && custom->big_end == 32768);
    assert(!PlanNativeGpuVaLayout(0x8000000, 1ULL << 37, 1ULL << 34, 0x20000));
    assert(!PlanNativeGpuVaLayout(0x8000000, 1ULL << 34, 1ULL << 34, 0x20000));
    assert(!PlanNativeGpuVaLayout(0, 1ULL << 34, 1ULL << 37, 0x20000));
    assert(!PlanNativeGpuVaLayout(0x8000001, 1ULL << 34, 1ULL << 37, 0x20000));
    assert(!PlanNativeGpuVaLayout(0x8000000, (1ULL << 34) + 0x1000, 1ULL << 37, 0x20000));
    assert(!PlanNativeGpuVaLayout(0x8000000, 1ULL << 34, (1ULL << 37) + 0x1000, 0x20000));
    assert(!PlanNativeGpuVaLayout(0x8000000, 1ULL << 45, 1ULL << 46, 0x20000));
    assert(!PlanNativeGpuVaLayout(0x8000000, 1ULL << 34, 1ULL << 37, 0x40000));
    std::puts("NS2 real 4K GMMU page partitions: PASS");
}
