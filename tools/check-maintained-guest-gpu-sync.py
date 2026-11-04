#!/usr/bin/env python3
"""G20 pinned-source parity, normal/DEV; not evidence of hardware correctness."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / "vendor/encore-active/eden-core/src/video_core"
DMA = (ROOT / "vendor/encore-active/eden-backports/src/video_core/dma_pusher.cpp").read_text()
PULLER = (ROOT / "vendor/sources/eden/src/video_core/engines/puller.cpp").read_text()
CMAKE = (ROOT / "headless/CMakeLists.txt").read_text()

def once(source, old, new):
    assert source.count(old) == 1, (old, source.count(old))
    return source.replace(old, new)

OLD_WAIT = "        sync_cv.wait(lk, [this]() { return synced; });"
WAIT = ("        while (!synced && !system.IsShuttingDown())\n"
        "            sync_cv.wait_for(lk, std::chrono::milliseconds(10));")
DMA_FAULT_INC = '#ifdef PS5_NATIVE\n#include "gpu_failure.h"\n#endif\n#include "common/settings.h"'
DMA_FAULT_WAIT = "        while (!synced && !system.IsShuttingDown()) {\n#ifdef PS5_NATIVE\n            // A failed GPU worker cannot deliver this pending fence.\n            if (auto failure = ::Eden::PeekGpuFailure())\n                std::rethrow_exception(failure);\n#endif\n            sync_cv.wait_for(lk, std::chrono::milliseconds(10));\n        }\n#ifdef PS5_NATIVE\n        // A failure published together with the final notification must not\n        // be mistaken for a successful DMA fence acknowledgement.\n        if (auto failure = ::Eden::PeekGpuFailure())\n            std::rethrow_exception(failure);\n#endif"
OLD_SEM = "    while (word != value) {"
SEM = "    while (word != value && !dma_pusher.system.IsShuttingDown()) {"
GPU_FAULT_INC = '#ifdef PS5_NATIVE\n#include "gpu_failure.h"\n#endif\n#include "common/assert.h"'
GPU_FAULT_INIT = """    const auto value = regs.semaphore_acquire;
#ifdef PS5_NATIVE
    // On a failed graphics worker, a stale GPU semaphore can never progress.
    // Sample failure once per 64 unsuccessful polls, starting with the first.
    unsigned acquire_polls = 0;
#endif
"""
GPU_FAULT_LOOP = """    while (word != value && !dma_pusher.system.IsShuttingDown()) {
#ifdef PS5_NATIVE
        if ((acquire_polls++ & 63u) == 0u) {
            if (auto failure = ::Eden::PeekGpuFailure())
                std::rethrow_exception(failure);
        }
#endif
"""

def expected(kind, dev):
    if kind == "dma":
        source = once(DMA, OLD_WAIT, WAIT + "\n        if (system.IsShuttingDown()) return false;")
        source = once(source, '#include "common/settings.h"', DMA_FAULT_INC)
        if dev:
            timer = ("        { ::Eden::Performance::DiagnosticActiveTimer dma_fence_timer(\n"
                     "            ::Eden::Performance::gpu_dma_sync_wait, ::Eden::Performance::gpu_dma_sync_active_since_ns,\n"
                     "            !synced && !system.IsShuttingDown());\n" + WAIT + "\n        }")
            source = once(source, WAIT, timer)
        source = once(source, WAIT, DMA_FAULT_WAIT)
    else:
        source = once(PULLER, OLD_SEM, SEM)
        source = once(source, '#include "common/assert.h"', GPU_FAULT_INC)
        source = once(source, '    const auto value = regs.semaphore_acquire;\n', GPU_FAULT_INIT)
        source = once(source, SEM + '\n', GPU_FAULT_LOOP)
        if dev:
            timer = ("    ::Eden::Performance::DiagnosticActiveTimer semaphore_timer(\n"
                     "        ::Eden::Performance::gpu_puller_semaphore_wait,\n"
                     "        ::Eden::Performance::gpu_puller_semaphore_active_since_ns,\n"
                     "        word != value && !dma_pusher.system.IsShuttingDown());\n" + SEM)
            source = once(source, SEM, timer)
    if kind == "dma":
        inc = '#include "video_core/guest_memory.h"\n'
        source = once(source, inc, inc +
            '#ifdef EDEN_NS2_NATIVE_GPU_DISPATCH\n'
            '#include "core/hle/service/nvdrv/devices/native_gpu_channel_registry.h"\n'
            '#endif\n')
        policy = ('        const bool use_safe = Settings::IsDMALevelDefault() ? '
                  'Settings::IsGPULevelHigh() : Settings::IsDMALevelSafe();')
        native = '''        bool use_safe = Settings::IsDMALevelDefault() ? Settings::IsGPULevelHigh() : Settings::IsDMALevelSafe();
#ifdef EDEN_NS2_NATIVE_GPU_DISPATCH
        // P2.7: C7x0 native GPFIFO command words can have been produced by
        // an earlier GPU dispatch. A guest setting for UNSAFE DMA must never
        // bypass GPU cache coherency for an authenticated NS2 channel.
        // SafeRead flushes the actual guest GPU region before consuming the
        // live words, including the non-contiguous backing fallback.
        use_safe |= Service::Nvidia::Devices::NativeGpuChannelRegistry::Instance().IsNative(&channel_state);
#endif'''
        source = once(source, policy, native)
    if dev:
        source = '#include "performance.h"\n' + source
    return "#include <chrono>\n" + source

for kind, name in (("dma", "dma_pusher"), ("puller", "engines/puller")):
    for dev in (False, True):
        path = name + ("_dev" if dev else "") + ".cpp"
        assert (ACTIVE / path).read_text() == expected(kind, dev), path
assert "foreach(unit dma_pusher engines/puller)" not in CMAKE
assert 'write_derived("${PORT_BUILD_DIR}/${unit_name}.cpp" "${command_source}")' not in CMAKE
for marker in ('list(REMOVE_ITEM video_sources dma_pusher.cpp engines/puller.cpp)',
               'list(APPEND video_sources "${EDEN_MAINTAINED_GPU_DMA}" "${EDEN_MAINTAINED_GPU_PULLER}")',
               'target_include_directories(video_core PRIVATE "${EDEN_PORT_DIR}")',
               'dma_pusher_dev.cpp', 'engines/puller_dev.cpp'):
    assert marker in CMAKE, marker
print("ENCORE_G20_GUEST_GPU_PARITY_PASS normal=2 dev=2")
