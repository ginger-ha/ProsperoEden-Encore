#!/usr/bin/env python3
"""Do not confuse offline source closure with elimination of source rewrites.

This is a fail-on-regression, NOT a claim that every native source already
builds without a CMake-generated derived unit.
"""
from pathlib import Path
import json

root = Path(__file__).resolve().parents[1]
vendor = root / "vendor"
sources = vendor / "sources"
active = vendor / "encore-active"
c = (root / "headless/CMakeLists.txt").read_text()
vulkan = (root / "headless/vulkan.cmake").read_text()
deps = json.loads((root / "tools/deps.json").read_text())["items"]
root_names = {entry.name for entry in sources.iterdir() if entry.is_dir()}
for dep in deps:
    name = dep["name"]
    if name == "pacbrew":
        assert (vendor / "objects/pacbrew").is_dir(), "pacbrew binary archive not vendored"
    else:
        assert name in root_names, f"missing pinned dependency source: {name}"
for extra in ("eden-cpm", "boilerplate-setup-0"):
    assert extra in root_names, extra
fork_names = {entry.name for entry in active.iterdir() if entry.is_dir()}
for name in ("eden-backports", "eden-build", "eden-core", "eden-gpu",
             "eden-surface-lifecycle", "eden-vulkan", "ps5-mesa"):
    assert name in fork_names, f"missing active patched tree: {name}"
assert 'file(COPY "${EDEN_ACTIVE_VULKAN}/" DESTINATION "${PORT_BUILD_DIR}")' in vulkan
assert (active/"eden-build/src/CMakeLists.txt").is_file(), "missing maintained native CMake"
assert 'execute_process(COMMAND python3 "${PORT_ROOT}/tools/prepare-vulkan-port.py"' not in vulkan
# Migration budget: historical ceilings (77/87/225) no longer protect a
# consolidated source tree. Match the remaining reviewed CMake generation
# sites and leave room only for removing them, never for adding new ones.
# For READ/REPLACE the approved pinned exceptions below are subtracted first.
baseline = {"write_derived(": 1, "file(READ": 4, "string(REPLACE": 2}
# Count actual top-level CMake commands, not tokens in comments or quoted text.
# A documentary reference to a retired rewrite must not look like live debt.
import re
counts = {
    name: len(re.findall(rf"^\s*{re.escape(name)}", c, re.M))
    for name in baseline
}
# All generation targets still permitted in the main CMake recipe.
# These are a shrinking allowlist: a migrated target needs no new exemption.
# G23 produces a GLSL resource and is deliberately not treated as C++ debt.
import re
allowed_generated_targets = {
    "${PORT_BUILD_DIR}/include/loading_scene_glsl.h",  # G23: GLSL resource
}
generated_targets = re.findall(r'^\s*write_derived\(\s*"([^"]+)"', c, re.M)
assert len(generated_targets) == counts["write_derived("], (
    "Unrecognized CMake write_derived site", generated_targets)
assert len(generated_targets) == len(set(generated_targets)), (
    "Duplicated CMake generation target", generated_targets)
assert set(generated_targets) <= allowed_generated_targets, (
    "Unreviewed generated CMake source: migrate to vendor/encore-active",
    sorted(set(generated_targets) - allowed_generated_targets))

assert 'function(eden_patch source old new)' not in c
# G11/X06: the last generated C++ has one complete Encore owner per profile.
assert 'write_derived("${derived}"' not in c
assert 'include("${EDEN_PORT_DIR}/native_jit_memory_read_guard.cmake")' not in c
assert 'list(APPEND core_sources "${EDEN_G11_SOURCE}")' in c
assert 'set_source_files_properties("${EDEN_G11_SOURCE}" TARGET_DIRECTORY core PROPERTIES' in c
for bits in (32,64):
    for platform in ("host","native"):
        for profile in ("normal","dev"):
            name = f"arm_dynarmic_{bits}_{platform}_{profile}.cpp"
            assert (active/"eden-core/src/core/arm/dynarmic/g11"/name).is_file(), name
assert 'write_derived("${derived}"' in (
    root/"tools/fixtures/legacy-g11-jit.cmake").read_text()
# G19: direct ownership from a single full Encore kernel translation unit.
assert 'write_derived("${PORT_BUILD_DIR}/kernel.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/core/hle/kernel/kernel.cpp" kernel_source)' not in c
assert 'list(APPEND core_sources "${EDEN_MAINTAINED_KERNEL_SOURCE}")' in c
assert 'list(FIND core_sources hle/kernel/kernel.cpp eden_g19_pinned_owner)' in c
for name in ("kernel_standard.cpp", "kernel_dev.cpp"):
    assert (active/"eden-core/src/core/hle/kernel"/name).is_file(), name
assert 'write_derived("${PORT_BUILD_DIR}/kernel.cpp"' in (
    root/"tools/fixtures/legacy-g19-kernel.cmake").read_text()
# G21 no longer injects source-level GPU sync code from CMake.
# All five host/native/DEV variants are maintained as complete C++ sources.
approved_sync = {"file(READ": (), "string(REPLACE": ()}
assert 'gpu_sync_wait_original' not in c
assert 'gpu_tick_lock_original' not in c
assert 'gpu_read_capture_original' not in c
assert 'write_derived("${PORT_BUILD_DIR}/gpu.cpp"' not in c
assert 'list(APPEND video_sources "${EDEN_MAINTAINED_G21_GPU}")' in c
for name in ("gpu_gl_host.cpp", "gpu_gl_host_dev.cpp", "gpu_gl_native.cpp",
             "gpu_gl_native_dev.cpp", "gpu_vulkan.cpp"):
    assert (active/"eden-core/src/video_core"/name).is_file(), name

# G13/X05 native guard ownership is now in the two complete maintained
# sources. Keep each contract in both, not in CMake string-rewrite fragments.
native_units = [
    (active/"eden-core/src/core"/name).read_text()
    for name in ("memory_native_standard.cpp", "memory_native_a32.cpp")
]
for unit in native_units:
    assert unit.count("gpu_dirty_managers[core].Collect(subaddress, span);") == 1
    assert unit.count("::Eden::GpuDirty::ForEachRegion(address, size,") == 1
    assert unit.count("ShouldLogUnmappedAccess()") == 11
    assert "std::numeric_limits<u64>::max() - GetInteger(base)" in unit
assert 'write_derived("${eden_gpu_span_tu}"' not in c
assert 'native_gpu_granular_bounds.cmake' not in c
assert not (root / "headless/native_gpu_granular_bounds.cmake").exists()
assert "Pinned GPU read callback lifetime changed" not in c
for name in ("gpu_gl_host.cpp", "gpu_gl_host_dev.cpp",
             "gpu_gl_native.cpp", "gpu_gl_native_dev.cpp"):
    unit = (active/"eden-core/src/video_core"/name).read_text()
    assert unit.count('RequestSyncOperation([this, raster_area]() {') == 1
assert 'RequestSyncOperation([this, &raster_area]() {' in (
    active/"eden-core/src/video_core/gpu_vulkan.cpp").read_text()
assert (root / "tools/check-native-gpu-read-capture-host.py").is_file()
assert "python3 -B tools/check-native-gpu-read-capture-host.py" in (
    root / ".github/workflows/encore-core-preflight.yml").read_text()
assert c.count('list(REMOVE_ITEM video_sources "memory_manager.cpp")') == 1
assert c.count('list(APPEND video_sources "${EDEN_NATIVE_GPU_MEMORY_MANAGER}")') == 1
assert (root / "tools/check-native-gpu-span-range-host.py").is_file()
assert "python3 -B tools/check-native-gpu-span-range-host.py" in (
    root / ".github/workflows/encore-core-preflight.yml").read_text()
assert all(u.count("const auto end_page = (addr + size - 1) >> YUZU_PAGEBITS;") == 2 for u in native_units)
assert (root / "tools/check-native-guest-span-host.py").is_file()
assert "python3 -B tools/check-native-guest-span-host.py" in (
    root / ".github/workflows/encore-core-preflight.yml").read_text()
assert all(u.count("thread_local Common::ScratchBuffer<u32> read_scratch;") == 1 for u in native_units)
assert all(u.count("VideoCore::RasterizerDownloadArea auxiliary_read_area{};") == 1 for u in native_units)
assert (root / "tools/check-native-gpu-read-core-host.py").is_file()
assert "python3 -B tools/check-native-gpu-read-core-host.py" in (
    root / ".github/workflows/encore-core-preflight.yml").read_text()
assert (root / "tools/check-native-gpu-dirty-subregion-host.py").is_file()
assert "python3 -B tools/check-native-gpu-dirty-subregion-host.py" in (
    root / ".github/workflows/encore-core-preflight.yml").read_text()
approved_counts = {}
for name, fragments in approved_sync.items():
    for fragment in fragments:
        assert c.count(fragment) == 1, f"missing pinned GPU sync generation: {fragment}"
    approved_counts[name] = len(fragments)
for name, limit in baseline.items():
    effective_count = counts[name] - approved_counts.get(name, 0)
    assert effective_count <= limit, (
        f"new CMake source override added: {name}: "
        f"baseline={effective_count} > {limit}, total={counts[name]}; "
        "integrate sources under vendor/encore-active instead"
    )

# Regression oracle: the maintained diagnostic IFile TU must be exactly the
# old pinned file + its former CMake replacement (apart from the normalized
# include path); prevent silent semantic drift while removing string rewrites.
fs_rel = "core/hle/service/filesystem/fsp/fs_i_file.cpp"
fs_pinned = (sources / "eden/src" / fs_rel).read_text()
fs_maintained = (active / "eden-core/src" / fs_rel).read_text()
fs_old = """    R_RETURN(
        backend->Read(reinterpret_cast<size_t*>(out_size.Get()), offset, out_buffer.data(), size));"""
fs_new = """    const auto fs_start = ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed) ? ::Eden::Performance::NowNs() : 0;
    const Result fs_result =
        backend->Read(reinterpret_cast<size_t*>(out_size.Get()), offset, out_buffer.data(), size);
    if (fs_start) {
        ::Eden::Performance::AddSince(::Eden::Performance::guest_fs_file, fs_start);
        ::Eden::Performance::guest_fs_file_bytes.fetch_add(static_cast<unsigned long long>(*out_size.Get()), std::memory_order_relaxed);
    // Diagnostic only: avoid formatting every file read while quiet.
        LOG_WARNING(Service_FS, "EDEN_FS_FILE_READ offset={:#x} size={} read={} result={:#x} ns={}", offset, size, *out_size.Get(), fs_result.raw, ::Eden::Performance::NowNs() - fs_start);
    }
    R_RETURN(fs_result);"""
assert fs_pinned.count(fs_old) == 1
assert fs_maintained == '#include "performance.h"\n' + fs_pinned.replace(fs_old, fs_new), (
    "Maintained IFile profile TU diverges from the already-audited generated source")
assert c.count('list(APPEND core_sources "${EDEN_MAINTAINED_PROFILE_FS_FILE}")') == 1
assert 'list(REMOVE_ITEM core_sources "hle/service/filesystem/fsp/fs_i_file.cpp")' in c
assert 'target_include_directories(core PRIVATE "${EDEN_PORT_DIR}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/gpu_thread.cpp"' not in c
assert 'write_derived("${PORT_BUILD_DIR}/include/common/bounded_threadsafe_queue.h"' not in c
# The stop-aware producer's single implementation is the selected GPU source,
# not a fresh CMake string rewrite or a historical injection fragment.
producer_header = (active / "eden-gpu/include/common/bounded_threadsafe_queue.h").read_text()
assert producer_header.count("bool EmplaceWaitWithStopToken(") == 1
assert "producer.cv.wait(lock, stop_token" in producer_header
for variant in ("gpu_thread_dev.cpp", "gpu_thread_quiet.cpp"):
    gpu_worker = (active / "eden-gpu" / variant).read_text()
    assert "state.queue.EmplaceWaitWithStopToken(stop_source.get_token()," in gpu_worker
assert 'configure_file("${EDEN_ACTIVE_GPU}/include/common/bounded_threadsafe_queue.h"' in c
assert 'string(REPLACE "${gpu_block_wait_original}" "${gpu_block_wait_checked}"' not in c
assert 'configure_file("${EDEN_ACTIVE_GPU}/include/common/bounded_threadsafe_queue.h"' in c
assert 'configure_file("${EDEN_ACTIVE_GPU}/${EDEN_GPU_WORKER_VARIANT}"' in c
assert 'write_derived("${PORT_BUILD_DIR}/fs_i_file.cpp"' not in c
assert "fs_file_source" not in c

storage_rel = "core/hle/service/filesystem/fsp/fs_i_storage.cpp"
storage_pinned = (sources / "eden/src" / storage_rel).read_text()
storage_maintained = (active / "eden-core/src" / storage_rel).read_text()
storage_old = "    backend->Read(out_bytes.data(), length, offset);"
storage_new = """    const auto fs_start = ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed) ? ::Eden::Performance::NowNs() : 0;
    const auto fs_read = backend->Read(out_bytes.data(), length, offset);
    if (fs_read != static_cast<std::size_t>(length))
        LOG_ERROR(Service_FS, "EDEN_FS_SHORT_STORAGE offset={:#x} length={} read={} size={}", offset, length, fs_read, backend->GetSize());
    if (fs_start) {
        ::Eden::Performance::AddSince(::Eden::Performance::guest_fs_storage, fs_start);
        ::Eden::Performance::guest_fs_storage_bytes.fetch_add(static_cast<unsigned long long>(length), std::memory_order_relaxed);
    }"""
assert storage_pinned.count(storage_old) == 1
assert storage_maintained == '#include "performance.h"\n' + storage_pinned.replace(storage_old, storage_new), (
    "Maintained IStorage profile TU diverges from the earlier CMake-generated source")
assert c.count('list(APPEND core_sources "${EDEN_MAINTAINED_PROFILE_FS_STORAGE}")') == 1
assert 'write_derived("${PORT_BUILD_DIR}/fs_i_storage.cpp"' not in c
assert "fs_storage_source" not in c
assert counts["write_derived("] <= 63, counts
print("VENDOR_MAINTAINED_FS_ISTORAGE_PARITY_PASS: read, short read, quiet policy")


# FS open diagnostics used to be a CMake loop patching three calls.
# Compare maintained C++ with that exact previous generated content.
fs_system_rel = "core/hle/service/filesystem/fsp/fs_i_filesystem.cpp"
fs_system_pinned = (sources / "eden/src" / fs_system_rel).read_text()
fs_system_maintained = (active / "eden-core/src" / fs_system_rel).read_text()
fs_system_expected = '#include "performance.h"\n' + fs_system_pinned
fs_system_calls = (
    ("file", """backend->OpenFile(&vfs_file, FileSys::Path(path->str),
                            static_cast<FileSys::OpenMode>(mode))"""),
    ("directory", """backend->OpenDirectory(&vfs_dir, FileSys::Path(path->str),
                                 static_cast<FileSys::OpenDirectoryMode>(mode))"""),
    ("entry", "backend->GetEntryType(&vfs_entry_type, FileSys::Path(path->str))"),
)
for kind, expression in fs_system_calls:
    before = f"    R_TRY({expression});"
    after = (f"    const Result fs_open_result = {expression};\n"
             "    if (::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed))\n"
             f'        LOG_WARNING(Service_FS, "EDEN_FS_OPEN kind={kind} path={{}} result={{:#x}}", path->str, fs_open_result.raw);\n'
             "    R_TRY(fs_open_result);")
    assert fs_system_expected.count(before) == 1, ("unpinned FS-open call", kind)
    fs_system_expected = fs_system_expected.replace(before, after)
assert fs_system_maintained == fs_system_expected, (
    "Maintained IFileSystem diagnostic diverges from former CMake-generated TU")
assert c.count('list(APPEND core_sources "${EDEN_MAINTAINED_PROFILE_FS_SYSTEM}")') == 1
assert c.count('list(REMOVE_ITEM core_sources "hle/service/filesystem/fsp/fs_i_filesystem.cpp")') == 1
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_PROFILE_FS_SYSTEM}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/fs_i_filesystem.cpp"' not in c
assert "fs_system_source" not in c
print("VENDOR_MAINTAINED_FS_IFILESYSTEM_PARITY_PASS: three opens, quiet guard, DEV selection")


# Native host-syncpoint callback diagnostic: exact old-generated TU parity.
nvctrl_rel = "core/hle/service/nvdrv/devices/nvhost_ctrl.cpp"
nvctrl_pinned = (sources / "eden/src" / nvctrl_rel).read_text()
nvctrl_maintained = (active / "eden-core/src" / nvctrl_rel).read_text()
nvctrl_old = """    event.wait_handle =
        host1x_syncpoint_manager.RegisterHostAction(fence_id, target_value, [this, slot]() {
            auto& event_ = events[slot];"""
nvctrl_new = """    const auto wait_start = ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed) ? ::Eden::Performance::NowNs() : 0;
    event.wait_handle =
        host1x_syncpoint_manager.RegisterHostAction(fence_id, target_value, [this, slot, wait_start]() {
            if (wait_start) ::Eden::Performance::AddSince(::Eden::Performance::guest_sync_wait, wait_start);
            auto& event_ = events[slot];"""
assert nvctrl_pinned.count(nvctrl_old) == 1
assert nvctrl_maintained == '#include "performance.h"\n' + nvctrl_pinned.replace(nvctrl_old, nvctrl_new), (
    "Maintained nvhost_ctrl source diverges from original event-wait instrumentation")
assert c.count('list(APPEND core_sources "${EDEN_MAINTAINED_PROFILE_NVCTRL}")') == 1
assert c.count('list(REMOVE_ITEM core_sources "hle/service/nvdrv/devices/nvhost_ctrl.cpp")') == 1
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_PROFILE_NVCTRL}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/nvhost_ctrl.cpp"' not in c
assert "ctrl_source" not in c and "ctrl_old" not in c

# The previous one-line CMake wrapper of DequeueBuffer's blocking wait is
# now a real maintained source, identical apart from the necessary include.
dequeue_rel = "core/hle/service/nvnflinger/buffer_queue_producer.cpp"
dequeue_pinned = (sources / "eden/src" / dequeue_rel).read_text()
dequeue_maintained = (active / "eden-core/src" / dequeue_rel).read_text()
dequeue_old = "        Status status = WaitForFreeSlotThenRelock(async, &found, &return_flags, lock);"
dequeue_new = """#ifdef EDEN_NVNF_DEQUEUE_PROFILE
        const auto dequeue_start = ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed) ? ::Eden::Performance::NowNs() : 0;
#endif
        Status status = WaitForFreeSlotThenRelock(async, &found, &return_flags, lock);
#ifdef EDEN_NVNF_DEQUEUE_PROFILE
        if (dequeue_start) ::Eden::Performance::AddSince(::Eden::Performance::guest_dequeue_wait, dequeue_start);
#endif"""
assert dequeue_pinned.count(dequeue_old) == 1
detach_before = "    *out_buffer = slots[found].graphic_buffer;\n    *out_fence = slots[found].fence;\n\n    core->FreeBufferLocked(found);\n\n    return Status::NoError;\n}"
detach_after = "    *out_buffer = slots[found].graphic_buffer;\n    *out_fence = slots[found].fence;\n\n    core->FreeBufferLocked(found);\n    // DetachBuffer and CancelBuffer wake waiting producers. The oldest-free\n    // detach path must publish the same state transition to all dequeuers.\n    // Notify under core->mutex so waiters cannot miss the transition.\n    core->SignalDequeueCondition();\n\n    return Status::NoError;\n}"
assert dequeue_pinned.count(detach_before) == 1
dequeue_expected = '#ifdef EDEN_NVNF_DEQUEUE_PROFILE\n#include "performance.h"\n#endif\n' + dequeue_pinned.replace(dequeue_old, dequeue_new)
assert dequeue_expected.count(detach_before) == 1
dequeue_expected = dequeue_expected.replace(detach_before, detach_after)
queue_before = "    item.graphic_buffer.reset();\n    item.slot = BufferItem::INVALID_BUFFER_SLOT;\n\n    if (listener_available) {"
queue_after = "    // Notify consumers with the actual queued item: keep its buffer and slot\n    // alive until the callback completes, outside the BufferQueue mutex.\n    if (listener_available) {"
assert dequeue_expected.count(queue_before) == 1
dequeue_expected = dequeue_expected.replace(queue_before, queue_after)
# Buffer history is opt-in: no per-frame clock on its default-disabled path.
history_before_1 = "        ++core->frame_counter;\n"
history_after_1 = "        // History is normally disabled: avoid unconditional wall-clock work.\n        const bool record_buffer_history = Settings::values.enable_buffer_history.GetValue();\n        ++core->frame_counter;\n"
assert dequeue_expected.count(history_before_1) == 1
dequeue_expected = dequeue_expected.replace(history_before_1, history_after_1)
history_before_2 = "        slots[slot].presentation_time = Common::g_wall_clock.GetTimeNS().count();"
history_after_2 = "        slots[slot].presentation_time = record_buffer_history\n                                            ? Common::g_wall_clock.GetTimeNS().count() : 0;"
assert dequeue_expected.count(history_before_2) == 1
dequeue_expected = dequeue_expected.replace(history_before_2, history_after_2)
history_before_3 = "if (Settings::values.enable_buffer_history.GetValue()) {"
history_after_3 = "if (record_buffer_history) {"
assert dequeue_expected.count(history_before_3) == 2
dequeue_expected = dequeue_expected.replace(history_before_3, history_after_3)
backpressure_before = "        if (too_many_buffers) {\n            LOG_ERROR(Service_Nvnflinger, \"queue size is {}, waiting\", core->queue.size());\n        }"
backpressure_after = "        if (too_many_buffers) {\n            // Backpressure is an expected queue state, not a service failure.\n            // Avoid per-wakeup ERROR formatting/output on the producer hot path.\n            LOG_DEBUG(Service_Nvnflinger, \"queue size is {}, waiting\", core->queue.size());\n        }"
assert dequeue_expected.count(backpressure_before) == 1
dequeue_expected = dequeue_expected.replace(backpressure_before, backpressure_after)

# Dequeue diagnostics must snapshot frame metadata while the core mutex is
# owned; logging a live slot outside the lock races with producer/consumer.
dequeue_frame_before_0 = "    Status return_flags = Status::NoError;\n    bool attached_by_consumer = false;\n"
dequeue_frame_after_0 = "    Status return_flags = Status::NoError;\n    bool attached_by_consumer = false;\n    u64 returned_frame_number{};\n"
assert dequeue_expected.count(dequeue_frame_before_0) == 1
dequeue_expected = dequeue_expected.replace(dequeue_frame_before_0, dequeue_frame_after_0)
dequeue_frame_before_1 = "        *out_fence = slots[found].fence;\n        slots[found].fence = Fence::NoFence();\n"
dequeue_frame_after_1 = "        *out_fence = slots[found].fence;\n        slots[found].fence = Fence::NoFence();\n        // Snapshot the slot metadata while the queue mutex is still owned.\n        returned_frame_number = slots[found].frame_number;\n"
assert dequeue_expected.count(dequeue_frame_before_1) == 1
dequeue_expected = dequeue_expected.replace(dequeue_frame_before_1, dequeue_frame_after_1)
dequeue_frame_before_2 = "            slots[*out_slot].frame_number = UINT32_MAX;\n            slots[*out_slot].graphic_buffer = graphic_buffer;\n"
dequeue_frame_after_2 = "            slots[*out_slot].frame_number = UINT32_MAX;\n            returned_frame_number = UINT32_MAX;\n            slots[*out_slot].graphic_buffer = graphic_buffer;\n"
assert dequeue_expected.count(dequeue_frame_before_2) == 1
dequeue_expected = dequeue_expected.replace(dequeue_frame_before_2, dequeue_frame_after_2)
dequeue_frame_before_3 = "    LOG_DEBUG(Service_Nvnflinger, \"returning slot={} frame={}, flags={}\", *out_slot,\n              slots[*out_slot].frame_number, return_flags);"
dequeue_frame_after_3 = "    LOG_DEBUG(Service_Nvnflinger, \"returning slot={} frame={}, flags={}\", *out_slot,\n              returned_frame_number, return_flags);"
assert dequeue_expected.count(dequeue_frame_before_3) == 1
dequeue_expected = dequeue_expected.replace(dequeue_frame_before_3, dequeue_frame_after_3)
# R435/F05: the prior producer-dequeue oracle is still useful for proving
# byte-for-byte provenance of all old maintained changes, but F05 now adds a
# producer release->guest-event listener. Project ONLY that separately tested
# change away before comparing against the historical expected TU. Fingerprint
# the complete new listener/registry block, so new unchecked code cannot be
# silently absorbed into an arbitrary skipped region.
wake_begin = "// A guest waiting on BufferQueueProducer::GetNativeHandle"
wake_end = "BufferQueueProducer::BufferQueueProducer("
assert dequeue_maintained.count(wake_begin) == 1
assert dequeue_maintained.count(wake_end) == 1
wake_block = dequeue_maintained[
    dequeue_maintained.index(wake_begin):dequeue_maintained.index(wake_end)
]
wake_fingerprint = 14695981039346656037
for wake_byte in wake_block.encode("utf-8"):
    wake_fingerprint = ((wake_fingerprint ^ wake_byte) * 1099511628211) & ((1 << 64) - 1)
assert wake_fingerprint == 0x83686626E6E9D1A7, "F05 producer release wake block changed"
dequeue_legacy_projection = dequeue_maintained.replace(wake_block, "", 1)

# Revert the F05 queue-mutex/kernel-scheduler lock-order repair *before*
# projecting older maintained producer patches onto the pinned Eden source.
# Changes must be present exactly once in their own method; unreviewed
# source drift fails the audit rather than being silently normalized.
def strip_producer_unlocked_signal(method_begin: str, method_end: str,
                                   before: str, after: str) -> None:
    global dequeue_legacy_projection
    start = dequeue_legacy_projection.index(method_begin)
    end = dequeue_legacy_projection.index(method_end, start + len(method_begin))
    part = dequeue_legacy_projection[start:end]
    assert part.count(after) == 1, ("F05 producer lock-order delta drift", method_begin, after[:100])
    part = part.replace(after, before, 1)
    dequeue_legacy_projection = (
        dequeue_legacy_projection[:start] + part + dequeue_legacy_projection[end:]
    )

strip_producer_unlocked_signal("Status BufferQueueProducer::SetBufferCount(", "Status BufferQueueProducer::WaitForFreeSlotThenRelock(",
    "    std::shared_ptr<IConsumerListener> listener;\n    {\n        std::scoped_lock lock{core->mutex};",
    "    std::shared_ptr<IConsumerListener> listener;\n    {\n        std::unique_lock lock{core->mutex};")
strip_producer_unlocked_signal("Status BufferQueueProducer::SetBufferCount(", "Status BufferQueueProducer::WaitForFreeSlotThenRelock(",
    "            // The guest may be sleeping on the Binder native wait handle.\n            buffer_wait_event->Signal(service_context.kernel);",
    "            // Publish only after releasing the queue mutex: kernel event\n            // signaling acquires the scheduler lock.\n            lock.unlock();\n            buffer_wait_event->Signal(service_context.kernel);")
strip_producer_unlocked_signal("Status BufferQueueProducer::SetBufferCount(", "Status BufferQueueProducer::WaitForFreeSlotThenRelock(",
    "        core->override_max_buffer_count = buffer_count;\n        core->SignalDequeueCondition();\n        buffer_wait_event->Signal(service_context.kernel);\n        listener = core->consumer_listener;\n    }\n\n    // Call back without lock held",
    "        core->override_max_buffer_count = buffer_count;\n        core->SignalDequeueCondition();\n        listener = core->consumer_listener;\n    }\n    buffer_wait_event->Signal(service_context.kernel);\n\n    // Call back without lock held")
strip_producer_unlocked_signal("Status BufferQueueProducer::DetachBuffer(", "Status BufferQueueProducer::AttachBuffer(",
    "Status BufferQueueProducer::DetachBuffer(s32 slot) {\n    LOG_DEBUG(Service_Nvnflinger, \"slot {}\", slot);\n\n    std::scoped_lock lock{core->mutex};",
    "Status BufferQueueProducer::DetachBuffer(s32 slot) {\n    LOG_DEBUG(Service_Nvnflinger, \"slot {}\", slot);\n\n    std::unique_lock lock{core->mutex};")
strip_producer_unlocked_signal("Status BufferQueueProducer::DetachBuffer(", "Status BufferQueueProducer::AttachBuffer(",
    "    // Match CancelBuffer: expose this freed slot to guest waiters, too.\n    buffer_wait_event->Signal(service_context.kernel);",
    "    // Host waiter publication stays under the queue lock; guest event\n    // publication must be outside it to avoid scheduler lock inversion.\n    lock.unlock();\n    buffer_wait_event->Signal(service_context.kernel);")
strip_producer_unlocked_signal("Status BufferQueueProducer::DetachBuffer(", "Status BufferQueueProducer::AttachBuffer(",
    "    std::scoped_lock lock{core->mutex};\n    core->WaitWhileAllocatingLocked();",
    "    std::unique_lock lock{core->mutex};\n    core->WaitWhileAllocatingLocked();")
strip_producer_unlocked_signal("Status BufferQueueProducer::DetachBuffer(", "Status BufferQueueProducer::AttachBuffer(",
    "    // DetachBuffer and CancelBuffer wake waiting producers. The oldest-free\n    // detach path must publish the same state transition to all dequeuers.\n    // Notify under core->mutex so waiters cannot miss the transition.\n    core->SignalDequeueCondition();\n    buffer_wait_event->Signal(service_context.kernel);",
    "    // Publish host dequeue-generation transition under the queue lock,\n    // then signal the Binder guest event only after dropping that lock.\n    core->SignalDequeueCondition();\n    lock.unlock();\n    buffer_wait_event->Signal(service_context.kernel);")
strip_producer_unlocked_signal("void BufferQueueProducer::CancelBuffer(", "Status BufferQueueProducer::Query(",
    "    std::scoped_lock lock{core->mutex};",
    "    std::unique_lock lock{core->mutex};")
strip_producer_unlocked_signal("void BufferQueueProducer::CancelBuffer(", "Status BufferQueueProducer::Query(",
    "    core->SignalDequeueCondition();\n    buffer_wait_event->Signal(service_context.kernel);",
    "    core->SignalDequeueCondition();\n    lock.unlock();\n    buffer_wait_event->Signal(service_context.kernel);")
strip_producer_unlocked_signal("Status BufferQueueProducer::Disconnect(", "Status BufferQueueProducer::SetPreallocatedBuffer(",
    "    std::shared_ptr<IConsumerListener> listener;\n    Status status = Status::NoError;",
    "    std::shared_ptr<IConsumerListener> listener;\n    Status status = Status::NoError;\n    bool released_queue = false;")
strip_producer_unlocked_signal("Status BufferQueueProducer::Disconnect(", "Status BufferQueueProducer::SetPreallocatedBuffer(",
    "                core->SignalDequeueCondition();\n                buffer_wait_event->Signal(service_context.kernel);\n                listener = core->consumer_listener;",
    "                core->SignalDequeueCondition();\n                released_queue = true;\n                listener = core->consumer_listener;")
strip_producer_unlocked_signal("Status BufferQueueProducer::Disconnect(", "Status BufferQueueProducer::SetPreallocatedBuffer(",
    "    if (listener) {\n        listener->OnBuffersReleased();",
    "    if (released_queue) {\n        buffer_wait_event->Signal(service_context.kernel);\n    }\n    if (listener) {\n        listener->OnBuffersReleased();")
strip_producer_unlocked_signal("Status BufferQueueProducer::SetPreallocatedBuffer(", "Kernel::KReadableEvent* BufferQueueProducer::GetNativeHandle(",
    "    std::scoped_lock lock{core->mutex};",
    "    std::unique_lock lock{core->mutex};")
strip_producer_unlocked_signal("Status BufferQueueProducer::SetPreallocatedBuffer(", "Kernel::KReadableEvent* BufferQueueProducer::GetNativeHandle(",
    "    core->SignalDequeueCondition();\n    buffer_wait_event->Signal(service_context.kernel);",
    "    core->SignalDequeueCondition();\n    lock.unlock();\n    buffer_wait_event->Signal(service_context.kernel);")


def strip_f05_once(before: str, after: str) -> None:
    global dequeue_legacy_projection
    assert dequeue_legacy_projection.count(after) == 1, ("F05 delta drift", after[:90])
    dequeue_legacy_projection = dequeue_legacy_projection.replace(after, before, 1)

# Opt-in F05 live-wait attribution: this is a native-only diagnostic
# insertion, not part of the upstream BufferQueue producer semantics.
strip_f05_once(
    "            if (!core->WaitForDequeueCondition(lk)) {\n"
    "                // We are no longer running\n"
    "                return Status::NoError;\n"
    "            }",
    "#ifdef EDEN_NVNF_DEQUEUE_PROFILE\n"
    "            // F05: a producer stuck inside this wait never contributes to\n"
    "            // completed DequeueBuffer timings. Publish in-flight waiters only\n"
    "            // in the opt-in profile, without changing the blocking predicate.\n"
    "            ::Eden::Performance::GuestDequeueBlockedScope blocking_scope;\n"
    "#endif\n"
    "            if (!core->WaitForDequeueCondition(lk)) {\n"
    "                // We are no longer running\n"
    "                return Status::NoError;\n"
    "            }",
)

strip_f05_once("", '#include "core/hle/service/nvnflinger/producer_listener.h"\n#include <unordered_map>\n')
strip_f05_once(
    '    buffer_wait_event = service_context.CreateEvent("BufferQueue:WaitEvent");',
    '    buffer_wait_event = service_context.CreateEvent("BufferQueue:WaitEvent");\n'
    '    auto wake = std::make_shared<ProducerReleaseWake>(buffer_wait_event, service_context.kernel);\n'
    '    std::scoped_lock lock{release_wakes_mutex};\n'
    '    release_wakes.emplace(this, std::move(wake));',
)
strip_f05_once(
    "BufferQueueProducer::~BufferQueueProducer() {\n"
    "    service_context.CloseEvent(buffer_wait_event);\n}",
    "BufferQueueProducer::~BufferQueueProducer() {\n"
    "    std::shared_ptr<ProducerReleaseWake> wake;\n"
    "    {\n"
    "        std::scoped_lock lock{release_wakes_mutex};\n"
    "        const auto it = release_wakes.find(this);\n"
    "        if (it != release_wakes.end()) {\n"
    "            wake = std::move(it->second);\n"
    "            release_wakes.erase(it);\n"
    "        }\n"
    "    }\n"
    "    if (wake) wake->Stop();\n"
    "    service_context.CloseEvent(buffer_wait_event);\n}",
)
strip_f05_once(
    '        core->connected_producer_listener = listener;',
    '        // HOS IPC connects with no guest listener. Always keep a local wake\n'
    '        // callback so the kernel wait handle is signalled on consumer release.\n'
    '        // Preserve an explicit listener by forwarding its notification.\n'
    '        if (const auto wake = GetReleaseWake(this)) {\n'
    '            wake->SetDelegate(listener);\n'
    '            core->connected_producer_listener = wake;\n'
    '        } else {\n'
    '            core->connected_producer_listener = listener;\n'
    '        }',
)
# Three pre-existing producer-side free/reset paths also wake the guest
# Binder event when their host dequeue condition changes (F05).
strip_f05_once(
    "            core->override_max_buffer_count = 0;\n"
    "            core->SignalDequeueCondition();\n"
    "            return Status::NoError;",
    "            core->override_max_buffer_count = 0;\n"
    "            core->SignalDequeueCondition();\n"
    "            // The guest may be sleeping on the Binder native wait handle.\n"
    "            buffer_wait_event->Signal(service_context.kernel);\n"
    "            return Status::NoError;",
)
strip_f05_once(
    "    core->FreeBufferLocked(slot);\n"
    "    core->SignalDequeueCondition();\n\n"
    "    return Status::NoError;",
    "    core->FreeBufferLocked(slot);\n"
    "    core->SignalDequeueCondition();\n"
    "    // Match CancelBuffer: expose this freed slot to guest waiters, too.\n"
    "    buffer_wait_event->Signal(service_context.kernel);\n\n"
    "    return Status::NoError;",
)
strip_f05_once(
    "    // Notify under core->mutex so waiters cannot miss the transition.\n"
    "    core->SignalDequeueCondition();\n\n"
    "    return Status::NoError;",
    "    // Notify under core->mutex so waiters cannot miss the transition.\n"
    "    core->SignalDequeueCondition();\n"
    "    buffer_wait_event->Signal(service_context.kernel);\n\n"
    "    return Status::NoError;",
)

# QueueBuffer replacement also frees an old tracked slot; publish a guest
# Binder wake just as CancelBuffer, Detach and consumer ReleaseBuffer do.
strip_f05_once(
    "    BufferItem item;\n"
    "    std::shared_ptr<IConsumerListener> listener_available;\n"
    "    std::shared_ptr<IConsumerListener> listener_replaced;",
    "    BufferItem item;\n"
    "    std::shared_ptr<IConsumerListener> listener_available;\n"
    "    std::shared_ptr<IConsumerListener> listener_replaced;\n"
    "    bool recycled_queued_slot = false;",
)
strip_f05_once(
    "            if (front->is_droppable && core->StillTracking(*front)) {\n"
    "                slots[front->slot].buffer_state = BufferState::Free;\n"
    "                if (record_buffer_history) {",
    "            if (front->is_droppable && core->StillTracking(*front)) {\n"
    "                slots[front->slot].buffer_state = BufferState::Free;\n"
    "                recycled_queued_slot = true;\n"
    "                if (record_buffer_history) {",
)
strip_f05_once(
    "",
    "    if (recycled_queued_slot) {\n"
    "        // KEvent::Signal takes the guest scheduler lock. Never acquire it\n"
    "        // while holding the BufferQueue mutex: an unblocked guest may\n"
    "        // reenter Binder/BufferQueue and reverse that lock order.\n"
    "        buffer_wait_event->Signal(service_context.kernel);\n"
    "    }\n\n",
)
assert dequeue_legacy_projection == dequeue_expected, (
    "Maintained queue-dequeue provenance or the F05 release wake delta diverged"
)
assert 'check-fc27-f05-producer-release-wake-host.py' in (
    root / ".github/workflows/encore-core-fast-gate.yml").read_text()

# Compile one maintained source; CMake owns DEV's compile-time profiler switch.
assert c.count('buffer_queue_producer_standard.cpp') == 0
assert c.count('target_compile_definitions(core PRIVATE EDEN_NVNF_DEQUEUE_PROFILE=1)') == 1
assert c.count('list(APPEND core_sources "${EDEN_MAINTAINED_PROFILE_DEQUEUE}")') == 1
assert c.count('list(REMOVE_ITEM core_sources "hle/service/nvnflinger/buffer_queue_producer.cpp")') == 1
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_PROFILE_DEQUEUE}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/buffer_queue_producer.cpp"' not in c
assert "producer_source" not in c and "producer_old" not in c
# F05: pinned-to-maintained consumer delta for abandonment wake.
consumer_rel = "core/hle/service/nvnflinger/buffer_queue_consumer.cpp"
consumer_pinned = (sources / "eden/src" / consumer_rel).read_text()
consumer_active = (active / "eden-core/src" / consumer_rel).read_text()
consumer_start = "Status BufferQueueConsumer::Disconnect() {"
consumer_end = "\nStatus BufferQueueConsumer::GetReleasedBuffers("
assert consumer_pinned.count(consumer_start) == 1 and consumer_pinned.count(consumer_end) == 1
consumer_old = consumer_pinned[consumer_pinned.index(consumer_start):
                               consumer_pinned.index(consumer_end)]
consumer_new = """Status BufferQueueConsumer::Disconnect() {
    LOG_DEBUG(Service_Nvnflinger, "called");

    std::shared_ptr<IProducerListener> producer_listener;
    {
        std::scoped_lock lock{core->mutex};
        if (core->consumer_listener == nullptr) {
            LOG_ERROR(Service_Nvnflinger, "no consumer is connected");
            return Status::BadValue;
        }

        core->is_abandoned = true;
        core->consumer_listener = nullptr;
        core->queue.clear();
        core->FreeAllBuffersLocked();
        core->SignalDequeueCondition();
        // A guest blocked on the producer's Binder native handle cannot
        // observe the host condition variable. Publish the terminal wake
        // through the same release listener used for ordinary buffer frees.
        producer_listener = std::move(core->connected_producer_listener);
    }

    // Release callbacks must never execute under core->mutex: a guest or
    // external listener can reenter the queue and otherwise deadlock.
    if (producer_listener) {
        producer_listener->OnBufferReleased();
    }
    return Status::NoError;
}
"""
# Revert only reviewed F05 additions to the pinned source, not arbitrary
# consumer text. Every replacement is unique and changes fail this audit.
assert consumer_active.count(consumer_new) == 1
consumer_legacy_projection = consumer_active.replace(consumer_new, consumer_old, 1)

def strip_consumer_f05_once(before: str, after: str) -> None:
    global consumer_legacy_projection
    assert consumer_legacy_projection.count(after) == 1, (
        "F05 consumer acquisition delta drift", after[:120])
    consumer_legacy_projection = consumer_legacy_projection.replace(after, before, 1)

# F05: discard of an untracked/stale buffer is NOT a release of an
# available producer slot. Keep the new notification predicate independent
# of the host dequeuer's more general queue-size broadcast.
strip_consumer_f05_once(
    "    bool dropped_queued_frames = false;",
    "    bool dropped_queued_frames = false;\n"
    "    bool freed_tracked_slot = false;",
)
strip_consumer_f05_once(
    "                slots[front->slot].buffer_state = BufferState::Free;\n"
    "            }\n\n"
    "            core->queue.erase(front);",
    "                slots[front->slot].buffer_state = BufferState::Free;\n"
    "                freed_tracked_slot = true;\n"
    "            }\n\n"
    "            core->queue.erase(front);",
)
strip_consumer_f05_once(
    "                const auto listener = core->connected_producer_listener;\n"
    "                lock.unlock();\n"
    "                if (listener) listener->OnBufferReleased();",
    "                if (freed_tracked_slot) {\n"
    "                    const auto listener = core->connected_producer_listener;\n"
    "                    lock.unlock();\n"
    "                    if (listener) listener->OnBufferReleased();\n"
    "                }",
)
strip_consumer_f05_once(
    "    if (dropped_queued_frames) {\n"
    "        // A dropped queued buffer is another producer-availability transition.",
    "    if (freed_tracked_slot) {\n"
    "        // Only a freed tracked slot creates a guest producer-availability transition.",
)

strip_consumer_f05_once(
    "    std::scoped_lock lock{core->mutex};",
    "    std::unique_lock lock{core->mutex};\n"
    "    bool dropped_queued_frames = false;",
)
strip_consumer_f05_once(
    "            core->queue.erase(front);\n"
    "            front = core->queue.begin();",
    "            core->queue.erase(front);\n"
    "            dropped_queued_frames = true;\n"
    "            front = core->queue.begin();",
)
strip_consumer_f05_once(
    '            LOG_DEBUG(Service_Nvnflinger, "defer desire={} expect={}", desired_present,\n'
    '                      expected_present.count());\n'
    '            return Status::PresentLater;',
    '            LOG_DEBUG(Service_Nvnflinger, "defer desire={} expect={}", desired_present,\n'
    '                      expected_present.count());\n'
    '            if (dropped_queued_frames) {\n'
    '                // Even without an acquired frame, discarded entries can make\n'
    '                // producer progress. Wake both host dequeuers and guest Binder\n'
    '                // waiters. Never invoke a callback while core->mutex is held.\n'
    '                core->SignalDequeueCondition();\n'
    '                const auto listener = core->connected_producer_listener;\n'
    '                lock.unlock();\n'
    '                if (listener) listener->OnBufferReleased();\n'
    '            }\n'
    '            return Status::PresentLater;',
)
strip_consumer_f05_once(
    "    core->queue.erase(front);\n\n"
    "    // We might have freed a slot while dropping old buffers, or the producer  may be blocked\n"
    "    // waiting for the number of buffers in the queue to decrease.\n"
    "    core->SignalDequeueCondition();\n\n"
    "    return Status::NoError;",
    "    core->queue.erase(front);\n\n"
    "    // We might have freed a slot while dropping old buffers, or the producer\n"
    "    // may be blocked waiting for the number of queued buffers to decrease.\n"
    "    core->SignalDequeueCondition();\n"
    "    if (dropped_queued_frames) {\n"
    "        // A dropped queued buffer is another producer-availability transition.\n"
    "        // The host condition is insufficient for the guest's Binder wait handle.\n"
    "        const auto listener = core->connected_producer_listener;\n"
    "        lock.unlock();\n"
    "        if (listener) listener->OnBufferReleased();\n"
    "    }\n\n"
    "    return Status::NoError;",
)
assert consumer_legacy_projection == consumer_pinned, (
    "Maintained consumer acquire/disconnect diverged from pinned reviewed F05 deltas"
)
assert c.count('list(REMOVE_ITEM core_sources "hle/service/nvnflinger/buffer_queue_consumer.cpp")') == 1
assert c.count('list(APPEND core_sources "\x24{EDEN_MAINTAINED_NVNF_CONSUMER}")') == 1
print("VENDOR_MAINTAINED_NVNF_CONSUMER_PARITY_PASS: teardown Binder wake")

print("VENDOR_MAINTAINED_DEQUEUE_PARITY_PASS: wait timing, detach wake, DEV selection")

print("VENDOR_MAINTAINED_NVCTRL_PARITY_PASS: async callback capture, quiet clock, DEV selection")

print("VENDOR_MAINTAINED_FS_IFILE_PARITY_PASS: pinned native DEV source, no CMake rewrite")



# HLE request dispatch: reproduce both historical CMake substitutions against
# the pinned file. The filesystem caller probe is applied to BOTH dispatch
# wrappers, even though we intentionally make no new runtime behavior changes.
hle_rel = "core/hle/service/service.cpp"
hle_pinned = (sources / "eden/src" / hle_rel).read_text()
hle_maintained = (active / "eden-core/src" / hle_rel).read_text()
hle_expected = '#include "performance.h"\n#include "core/arm/debug.h"\n' + hle_pinned
hle_calls = ("        InvokeRequest(ctx);", "            InvokeRequestTipc(ctx);")
hle_metric = """            if (profile_hle)
                ::Eden::Performance::RecordHle(service_name, ctx.GetCommand(), ::Eden::Performance::NowNs() - hle_start);
"""
for call in hle_calls:
    assert hle_expected.count(call) == 1, ("missing pinned HLE request dispatch", call)
    wrapper = ("""        {
            const bool profile_hle = ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed);
            const auto hle_start = profile_hle ? ::Eden::Performance::NowNs() : 0;
""" + call + "\n" + hle_metric + "        }")
    hle_expected = hle_expected.replace(call, wrapper)
assert hle_expected.count(hle_metric) == 2
hle_trace = """            if (::Eden::Performance::trace_fs_callers.load(std::memory_order_relaxed) && std::string_view{service_name} == "IFileSystem") {
                std::string frames;
                for (const auto& entry : Core::GetBacktrace(&ctx.GetThread()))
                    frames += fmt::format(" {}+{:X}", entry.module, entry.offset);
                LOG_WARNING(Service_FS, "EDEN_FS_CALLER command={} thread={} name={} frames={}", ctx.GetCommand(),
                            ctx.GetThread().GetThreadId(), Core::GetThreadName(&ctx.GetThread()).value_or("-"), frames);
            }
"""
hle_expected = hle_expected.replace(hle_metric, hle_metric + hle_trace)
assert hle_maintained == hle_expected, "Maintained service dispatch diverges from former CMake-generated HLE source"
# Synchronous IPC: request ID and timing are captured BEFORE the potentially
# blocking call; the exact historical body is maintained, not regenerated.
ipc_rel = "core/hle/kernel/svc/svc_ipc.cpp"
ipc_pinned = (sources / "eden/src" / ipc_rel).read_text()
ipc_maintained = (active / "eden-core/src" / ipc_rel).read_text()
ipc_old = "    R_RETURN(session->SendSyncRequest(kernel, message, buffer_size));"
ipc_new = """    const bool ipc_profile = ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed);
    const auto ipc_start = ipc_profile ? ::Eden::Performance::NowNs() : 0;
    const auto ipc_tid = ipc_profile ? GetCurrentThread(kernel).GetThreadId() : 0;
    auto* const ipc_slot = ipc_profile ? ::Eden::Performance::BeginGuestIpc(ipc_tid, ipc_start) : nullptr;
    const Result ipc_result = session->SendSyncRequest(kernel, message, buffer_size);
    if (ipc_profile) ::Eden::Performance::FinishGuestIpc(ipc_slot, ipc_tid, ipc_start, ::Eden::Performance::NowNs() - ipc_start);
    R_RETURN(ipc_result);"""
assert ipc_pinned.count(ipc_old) == 1
ipc_timeout_old = """                timeout = kernel.HardwareTimer().GetTick() + offset_tick + 2;
                if (timeout <= 0) {
                    timeout = (std::numeric_limits<s64>::max)();
                }"""
ipc_timeout_fixed = """                s64 absolute{};
                if (__builtin_add_overflow(kernel.HardwareTimer().GetTick(), offset_tick,
                                           &absolute) ||
                    __builtin_add_overflow(absolute, s64{2}, &absolute) ||
                    absolute <= 0) {
                    timeout = (std::numeric_limits<s64>::max)();
                } else {
                    timeout = absolute;
                }"""
assert ipc_pinned.count(ipc_timeout_old) == 1
ipc_index_old = """            s32 index;
            Result result = KSynchronizationObject::Wait(kernel, std::addressof(index), objs, num_objects, timeout);"""
ipc_index_fixed = """            // Wait may return cancellation/termination before setting the index.
            // Never propagate an indeterminate slot on non-timeout failures.
            s32 index{-1};
            Result result = KSynchronizationObject::Wait(kernel, std::addressof(index), objs, num_objects, timeout);"""
assert ipc_pinned.count(ipc_index_old) == 1
ipc_expected = ('#include "performance.h"\n' +
                ipc_pinned.replace(ipc_old, ipc_new).replace(ipc_timeout_old, ipc_timeout_fixed).replace(ipc_index_old, ipc_index_fixed))
assert ipc_maintained == ipc_expected, (
    "Maintained DEV IPC source diverges from pinned + profiler + deadline and slot guards")
ipc_standard = (active / "eden-core/src/core/hle/kernel/svc/svc_ipc_standard.cpp").read_text()
# Final IPC source adds one fail-closed check *only* for impossible success
# indices; DEV remains the pinned profile with its instrumented timestamps.
ipc_success_old = """            if (R_SUCCEEDED(result)) {
                KServerSession* session = objs[index]->DynamicCast<KServerSession*>();"""
ipc_success_safe = """            if (R_SUCCEEDED(result)) {
                // Even a successful wake must identify an actual queued object.
                // Fail closed rather than indexing before/after the wait buffer
                // if an unexpected native wakeup publishes an invalid slot.
                if (index < 0 || index >= num_objects || objs[index] == nullptr) {
                    *out_index = -1;
                    R_THROW(ResultOutOfRange);
                }
                KServerSession* session = objs[index]->DynamicCast<KServerSession*>();"""
assert ipc_pinned.count(ipc_success_old) == 1
ipc_standard_expected = (ipc_pinned.replace(ipc_timeout_old, ipc_timeout_fixed)
                         .replace(ipc_index_old, ipc_index_fixed)
                         .replace(ipc_success_old, ipc_success_safe))
assert ipc_standard == ipc_standard_expected, (
    "Maintained normal IPC source diverges from pinned + deadline, initialized index, guarded successful slot")
assert 'list(APPEND core_sources "${EDEN_MAINTAINED_SVC_IPC_STANDARD}")' in c
assert 'list(APPEND core_sources "${EDEN_MAINTAINED_PROFILE_HLE_SERVICE}"' in c
for name, pinned_path in (
        ("HLE_SERVICE", "hle/service/service.cpp"),
        ("SVC_IPC", "hle/kernel/svc/svc_ipc.cpp")):
    assert f'set(EDEN_MAINTAINED_PROFILE_{name}' in c
    assert ('"${EDEN_MAINTAINED_PROFILE_' + name + '}"') in c
    assert f'"{pinned_path}"' in c
    assert ('write_derived("${PORT_BUILD_DIR}' + "/" + ("hle_service" if name == "HLE_SERVICE" else "svc_ipc") + '.cpp"') not in c
assert c.count('list(REMOVE_ITEM core_sources "hle/service/service.cpp" "hle/kernel/svc/svc_ipc.cpp")') == 1
for name in ("hle_source", "ipc_source", "hle_call", "ipc_old"):
    assert name not in c, ("legacy configure-time HLE rewrite still referenced", name)
print("VENDOR_MAINTAINED_HLE_IPC_PARITY_PASS: both dispatches, caller traces, guest IPC attribution, DEV selection")

# Native common/runtime unit selection must be real maintained C++, not
# transient CMake string-rewritten source. Exact source parity is checked,
# with the former absolute include replaced by the tracked include directory.
thread_rel = "common/thread.cpp"
thread_original = (sources / "eden/src" / thread_rel).read_text()
thread_maintained = (active / "eden-core/src" / thread_rel).read_text()
thread_old = "void SetCurrentThreadName(const char* name) {"
thread_new = thread_old + "\n    ::Eden::Performance::RegisterWorker(name);"
assert thread_original.count(thread_old) == 1
assert thread_maintained == '#include "performance.h"\n' + thread_original.replace(thread_old, thread_new)
assert c.count('list(APPEND common_sources "${EDEN_MAINTAINED_NATIVE_THREAD}")') == 1
assert 'list(REMOVE_ITEM common_sources thread.cpp)' in c
assert 'write_derived("${PORT_BUILD_DIR}/thread.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/common/thread.cpp" thread_source)' not in c
fs_native_rel = "common/fs/fs.cpp"
fs_native_original = (sources / "eden/src" / fs_native_rel).read_text()
fs_native_maintained = (active / "eden-core/src" / fs_native_rel).read_text()
fs_native_old = "fs::directory_iterator(path, ec)"
assert fs_native_original.count(fs_native_old) == 2
fs_native_expected = '#include "native_directory.h"\n' + fs_native_original.replace(
    fs_native_old, "Eden::ReadNativeDirectory(path, ec)")
assert fs_native_maintained == fs_native_expected
assert c.count('list(APPEND common_sources "${EDEN_MAINTAINED_NATIVE_FS}")') == 1
assert 'list(REMOVE_ITEM common_sources fs/fs.cpp)' in c
assert 'write_derived("${PORT_BUILD_DIR}/fs.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/common/fs/fs.cpp" fs_source)' not in c
assert 'target_include_directories(common PRIVATE "${EDEN_PORT_DIR}")' in c
# Verify native common sources are selected exactly once and originals removed.
native_common_block = c.split("    get_target_property(common_sources common SOURCES)", 1)[1].split(
    '    set_property(TARGET common PROPERTY SOURCES "${common_sources}")', 1)[0]
assert native_common_block.count("list(REMOVE_ITEM common_sources thread.cpp)") == 1
assert native_common_block.count("list(REMOVE_ITEM common_sources fs/fs.cpp)") == 1
assert native_common_block.count("list(APPEND common_sources") == 4
for former_read in ("thread_source", "fs_source"):
    assert former_read not in native_common_block
for name in ("EDEN_MAINTAINED_NATIVE_THREAD", "EDEN_MAINTAINED_NATIVE_FS"):
    assert ('if(NOT EXISTS "${' + name + '}")') in native_common_block

print("VENDOR_MAINTAINED_COMMON_RUNTIME_PARITY_PASS: thread name, two iterators, native-only selection")

# Native CPU feature detection: move the CPUID 0x15 fallback out of its
# leaf-specific block without changing the existing host frequency heuristic.
cpu_rel = "common/cpu_features.cpp"
cpu_pinned = (sources / "eden/src" / cpu_rel).read_text()
cpu_active = (active / "eden-core/src" / cpu_rel).read_text()
cpu_fallback = """        } else {
            caps.tsc_frequency = X64::EstimateRDTSCFrequency();
        }"""
cpu_leaf16 = "    if (max_std_fn >= 0x16) {"
cpu_leaf16_new = """    if (caps.invariant_tsc && caps.tsc_frequency < 1'000'000'000ULL) {
        caps.tsc_frequency = X64::EstimateRDTSCFrequency();
    }

    if (max_std_fn >= 0x16) {"""
assert cpu_pinned.count(cpu_fallback) == cpu_pinned.count(cpu_leaf16) == 1
cpu_expected = cpu_pinned.replace(cpu_fallback, "        }").replace(cpu_leaf16, cpu_leaf16_new)
# N76/N77 adds only the audited, opt-in guest-rate block to the shared owner.
# Reverse its exact bytes for the original TSC parity check; reject drift.
ns2_cpu_header = "#ifdef EDEN_NS2_GUEST_COUNTER\n#include \"encore/guest_counter_policy.h\"\n#endif\n"
ns2_cpu_block = "#ifdef EDEN_NS2_GUEST_COUNTER\n    // Shared guest-clock policy: Nintendo's second-generation SDK converts\n    // CNT ticks using 31.25 MHz. Keep the original fast path for Switch 1.\n    if (Eden::GuestCounter::Rate() != Eden::GuestCounter::Switch1Hz) {\n        if (!invariant)\n            return static_cast<s64>(Eden::GuestCounter::NanosecondsToGuest(\n                static_cast<u64>(GetUptime())));\n        const u64 factor = Eden::GuestCounter::NativeFactor();\n        if (factor != 0)\n            return MultiplyHigh(GetUptime(), factor);\n        // A missing host clock calibration must not divide by zero or\n        // silently keep the wrong 19.2 MHz guest rate.\n        if (rdtsc_frequency == 0)\n            return 0;\n        return MultiplyHigh(GetUptime(),\n                            GetFixedPoint64Factor(Eden::GuestCounter::Rate(),\n                                                  rdtsc_frequency));\n    }\n#endif\n"
if "#ifdef EDEN_NS2_GUEST_COUNTER" in cpu_active:
    assert cpu_active.count(ns2_cpu_header) == 1, "N76 header modified or duplicated"
    assert cpu_active.count(ns2_cpu_block) == 1, "N76 timing block modified or duplicated"
    cpu_active = cpu_active.replace(ns2_cpu_header, "").replace(ns2_cpu_block, "")
assert cpu_active == cpu_expected, "TSC source differs from previous configure-time transformation"
assert c.count('list(APPEND common_sources "${EDEN_MAINTAINED_NATIVE_CPU_FEATURES}")') == 1
assert 'list(REMOVE_ITEM common_sources cpu_features.cpp)' in c
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_NATIVE_CPU_FEATURES}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/cpu_features.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/common/cpu_features.cpp" features_source)' not in c

# Native writable/cache/config roots and the legacy-compatibility folder.
# Header normalization is safe because the common target carries the same
# EDEN_PORT_DIR private include root used by the previous generated file.
paths_rel = "common/fs/path_util.cpp"
paths_pinned = (sources / "eden/src" / paths_rel).read_text()
paths_active = (active / "eden-core/src" / paths_rel).read_text()
paths_old = "#else\n        eden_path = GetCurrentDir() / PORTABLE_DIR;"
paths_new = """#elif defined(PS5_NATIVE)
        eden_path = Eden::UserDir();
        eden_path_cache = eden_path / CACHE_DIR;
        eden_path_config = eden_path / CONFIG_DIR;
#else
        eden_path = GetCurrentDir() / PORTABLE_DIR;"""
legacy_old = "#else\n        // In Ryujinx's infinite wisdom"
legacy_new = """#elif defined(PS5_NATIVE)
        GenerateLegacyPath(EmuPath::RyujinxDir, eden_path / RYUJINX_DIR);
#else
        // In Ryujinx's infinite wisdom"""
assert paths_pinned.count(paths_old) == paths_pinned.count(legacy_old) == 1
paths_expected = '#include "storage_paths.h"\n' + paths_pinned.replace(
    paths_old, paths_new).replace(legacy_old, legacy_new)
assert paths_active == paths_expected, "Native user/config path source differs from prior generator"
assert c.count('list(APPEND common_sources "${EDEN_MAINTAINED_NATIVE_PATHS}")') == 1
assert 'list(REMOVE_ITEM common_sources fs/path_util.cpp)' in c
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_NATIVE_PATHS}")' in c
assert 'target_include_directories(common PRIVATE "${EDEN_PORT_DIR}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/path_util.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/common/fs/path_util.cpp" paths_source)' not in c
print("VENDOR_MAINTAINED_NATIVE_TSC_PATH_PARITY_PASS: CPUID fallback, native roots, DEV build selection")

# Native getifaddrs interface provider: exactly three platform-branch
# substitutions used to be emitted as a generated CMake translation unit.
interfaces_rel = "core/internal_network/network_interface.cpp"
interfaces_pinned = (sources / "eden/src" / interfaces_rel).read_text()
interfaces_active = (active / "eden-core/src" / interfaces_rel).read_text()
interface_replacements = (
    ("defined(__linux__) || defined(__ANDROID__)",
     "defined(__linux__) || defined(__ANDROID__) || defined(__FreeBSD__)"),
    ("defined(__ANDROID__) || defined(__linux__)",
     "defined(__ANDROID__) || defined(__linux__) || defined(__FreeBSD__)"),
    ("#ifdef __ANDROID__", "#if defined(__ANDROID__) || defined(__FreeBSD__)"),
)
interface_expected = interfaces_pinned
for old_branch, native_branch in interface_replacements:
    assert interface_expected.count(old_branch) == 1, ("native interface branch changed", old_branch)
    interface_expected = interface_expected.replace(old_branch, native_branch)
assert interfaces_active == interface_expected, "Native network interfaces diverge from previous CMake source"
assert c.count('list(APPEND core_sources "${EDEN_MAINTAINED_NATIVE_NET_INTERFACES}")') == 1
assert 'list(REMOVE_ITEM core_sources internal_network/network_interface.cpp)' in c
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_NATIVE_NET_INTERFACES}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/network_interface.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/core/internal_network/network_interface.cpp" interfaces_source)' not in c
print("VENDOR_MAINTAINED_NATIVE_NET_INTERFACES_PARITY_PASS: getifaddrs branch, native-only selection")





# Firmware system root: preserved transformation and selected native C++.
native_fs_rel = "core/hle/service/filesystem/filesystem.cpp"
native_fs_pinned = (sources / "eden/src" / native_fs_rel).read_text()
native_fs_active = (active / "eden-core/src" / native_fs_rel).read_text()
native_fs_old = "nand_directory, std::move(load_directory), std::move(dump_directory));"
native_fs_new = ('nand_directory, std::move(load_directory), std::move(dump_directory), '
                 'vfs.OpenDirectory(Eden::AssetsPath("firmware"), FileSys::OpenMode::Read));')
assert native_fs_pinned.count(native_fs_old) == 1
assert native_fs_active == ('#include "assets_dir.h"\n'
                           + native_fs_pinned.replace(native_fs_old, native_fs_new))
assert c.count('list(REMOVE_ITEM core_sources hle/service/filesystem/filesystem.cpp)') == 1
assert c.count('list(APPEND core_sources "${EDEN_MAINTAINED_NATIVE_FILESYSTEM}")') == 1
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_NATIVE_FILESYSTEM}")' in c
assert 'target_include_directories(core PRIVATE "${EDEN_PORT_DIR}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/filesystem.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/core/hle/service/filesystem/filesystem.cpp" fs_service)' not in c
print("VENDOR_MAINTAINED_NATIVE_FILESYSTEM_PARITY_PASS: firmware and selection")

# Source parity for non-owning RomFS builder parents: the old CMake
# substitutions targeted TWO directory/file contexts and TWO assignments.
romfs_rel = "core/file_sys/fsmitm_romfsbuild.cpp"
romfs_pinned = (sources / "eden/src" / romfs_rel).read_text()
romfs_active = (active / "eden-core/src" / romfs_rel).read_text()
romfs_rewrites = (
    ("    std::shared_ptr<RomFSBuildDirectoryContext> parent;",
     "    RomFSBuildDirectoryContext* parent = nullptr;"),
    ("parent = std::move(parent_dir_ctx);", "parent = parent_dir_ctx.get();"),
)
for old,new in romfs_rewrites:
    assert romfs_pinned.count(old) == 2, ("pinned RomFS parent drift", old)
    romfs_pinned = romfs_pinned.replace(old,new)
assert romfs_active == romfs_pinned, "maintained RomFS builder differs from former CMake unit"
assert c.count('list(REMOVE_ITEM core_sources file_sys/fsmitm_romfsbuild.cpp)') == 1
assert c.count('list(APPEND core_sources "${EDEN_MAINTAINED_ROMFS_BUILDER}")') == 1
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_ROMFS_BUILDER}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/fsmitm_romfsbuild.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/core/file_sys/fsmitm_romfsbuild.cpp"' not in c
print("VENDOR_MAINTAINED_ROMFS_BUILDER_PARITY_PASS: two non-owning links, two assignments")

# Native BISFactory is a coordinated header/source pair: constructors and
# firmware root, plus the lookup-only mod directory behavior, match the
# former configure-time substitutions byte-for-byte.
bis_header_pinned = (sources / "eden/src/core/file_sys/bis_factory.h").read_text()
bis_header_maintained = (active / "eden-core/include/core/file_sys/bis_factory.h").read_text()
bis_header_old = "VirtualDir dump_root);"
bis_header_new = "VirtualDir dump_root, VirtualDir firmware_root = {});"
assert bis_header_pinned.count(bis_header_old) == 1
assert bis_header_maintained == bis_header_pinned.replace(bis_header_old,bis_header_new)
bis_cpp_pinned = (sources / "eden/src/core/file_sys/bis_factory.cpp").read_text()
bis_cpp_maintained = (active / "eden-core/src/core/file_sys/bis_factory.cpp").read_text()
bis_rewrites = (
    ("VirtualDir dump_root_)", "VirtualDir dump_root_, VirtualDir firmware_root)"),
    ('GetOrCreateDirectoryRelative(nand_root, "/system/Contents/registered")',
     'firmware_root ? std::move(firmware_root) : GetOrCreateDirectoryRelative(nand_root, "/system/Contents/registered")'),
    ('    return GetOrCreateDirectoryRelative(load_root, fmt::format("/{:016X}", title_id));\n'
     '}\n\nVirtualDir BISFactory::GetModificationDumpRoot',
     '    const auto wanted = fmt::format("{:016X}", title_id);\n'
     '    if (load_root != nullptr)\n'
     '        for (const auto& folder : load_root->GetSubdirectories())\n'
     '            if (Common::ToUpper(folder->GetName()) == wanted) return folder;\n'
     '    return nullptr;\n'
     '}\n\nVirtualDir BISFactory::GetModificationDumpRoot'),
)
for old,new in bis_rewrites:
    assert bis_cpp_pinned.count(old) == 1, ("pinned BISFactory contract drift",old)
    bis_cpp_pinned = bis_cpp_pinned.replace(old,new)
assert bis_cpp_maintained == '#include "common/string_util.h"\n' + bis_cpp_pinned
assert c.count('list(REMOVE_ITEM core_sources file_sys/bis_factory.cpp)') == 1
assert c.count('list(APPEND core_sources "${EDEN_MAINTAINED_BIS_SOURCE}")') == 1
assert 'target_include_directories(core BEFORE PUBLIC "${EDEN_MAINTAINED_BIS_INCLUDE_ROOT}")' in c
assert 'file(REMOVE "${PORT_BUILD_DIR}/include/core/file_sys/bis_factory.h")' in c
assert 'write_derived("${PORT_BUILD_DIR}/bis_factory.cpp"' not in c
assert 'write_derived("${PORT_BUILD_DIR}/include/core/file_sys/bis_factory.h"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/core/file_sys/bis_factory.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/core/file_sys/bis_factory.h"' not in c
print("VENDOR_MAINTAINED_BIS_PAIR_PARITY_PASS: API, firmware root, mods and native selection")

# Renderer factory parity: Vulkan keeps the untouched source while the
# OpenGL-only native profile selects the tracked two-removal variant.
pinned_factory = (sources / "eden/src/video_core/video_core.cpp").read_text()
maintained_gl_factory = (active / "eden-core/src/video_core/video_core_opengl.cpp").read_text()
gl_removals = (
    '#include "video_core/renderer_vulkan/renderer_vulkan.h"',
    '    case Settings::RendererBackend::Vulkan:\n'
    '        return std::make_unique<Vulkan::RendererVulkan>(emu_window, device_memory, gpu, std::move(context));\n',
)
for removed in gl_removals:
    assert pinned_factory.count(removed) == 1, ("pinned factory drift",removed)
    pinned_factory = pinned_factory.replace(removed, "")
assert maintained_gl_factory == pinned_factory
factory_select = ('list(REMOVE_ITEM video_sources video_core.cpp gpu.cpp)\n'
                  'if(EDEN_PS5_VULKAN)\n'
                  '    list(APPEND video_sources video_core.cpp)\n'
                  'else()\n'
                  '    list(APPEND video_sources "${EDEN_MAINTAINED_GL_VIDEO_FACTORY}")\n'
                  'endif()')
assert factory_select in c
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_GL_VIDEO_FACTORY}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/video_core.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/video_core/video_core.cpp" video_factory)' not in c
print("VENDOR_VIDEO_FACTORY_SELECTION_PASS: pinned Vulkan and maintained OpenGL")

# RendererOpenGL previously passed through an identity CMake file copy.
# The pinned source already belongs to video_core; do not duplicate objects.
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/video_core/renderer_opengl/renderer_opengl.cpp" renderer_source)' not in c
assert 'write_derived("${PORT_BUILD_DIR}/renderer_opengl.cpp"' not in c
assert 'list(REMOVE_ITEM video_sources renderer_opengl/renderer_opengl.cpp)' not in c
assert 'list(APPEND video_sources "${PORT_BUILD_DIR}/renderer_opengl.cpp")' not in c
assert 'renderer_opengl/renderer_opengl.cpp' in (sources / "eden/src/video_core/CMakeLists.txt").read_text()
# Stale generated renderer must not remain an explicit Vulkan rebuild dependency.
assert '${PORT_BUILD_DIR}/renderer_opengl.cpp' not in vulkan
assert '${PROJECT_SOURCE_DIR}/src/video_core/renderer_opengl/renderer_opengl.cpp' in vulkan
print("VENDOR_OPENGL_RENDERER_IDENTITY_COPY_REMOVED: pinned source selected")

# GL source parity and conditional selection: exact old CMake substitutions.
native_gl_buffer = "video_core/renderer_opengl/gl_buffer_cache.cpp"
native_gl_query = "video_core/renderer_opengl/gl_query_cache.cpp"
pinned_gl_buffer = (sources/"eden/src"/native_gl_buffer).read_text()
pinned_gl_query = (sources/"eden/src"/native_gl_query).read_text()
old_buf = "static_cast<GLsizeiptr>(size), GL_RED, GL_UNSIGNED_INT, &value);"
new_buf = "static_cast<GLsizeiptr>(size), GL_RED_INTEGER, GL_UNSIGNED_INT, &value);"
old_qry = "const bool slice_counter = WaitPending() && stream.IsEnabled();"
new_qry = "const bool slice_counter = false; // PS5: do not split cached query reads."
assert pinned_gl_buffer.count(old_buf) == 1
assert pinned_gl_query.count(old_qry) == 1
assert (active/"eden-core/src"/native_gl_buffer).read_text() == pinned_gl_buffer.replace(old_buf,new_buf)
assert (active/"eden-core/src"/native_gl_query).read_text() == pinned_gl_query.replace(old_qry,new_qry)
assert c.count('list(APPEND video_sources "${EDEN_MAINTAINED_GL_BUFFER_CACHE}")') == 1
assert c.count('list(APPEND video_sources "${EDEN_MAINTAINED_GL_QUERY_CACHE}")') == 1
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_GL_BUFFER_CACHE}")' in c
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_GL_QUERY_CACHE}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/gl_buffer_cache.cpp"' not in c
assert 'write_derived("${PORT_BUILD_DIR}/gl_query_cache.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/video_core/renderer_opengl/gl_buffer_cache.cpp" buffer_source)' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/video_core/renderer_opengl/gl_query_cache.cpp" query_source)' not in c
print("VENDOR_MAINTAINED_GL_CACHE_PARITY_PASS buffer=1 native_query=1")

# The native compiler-rt TLS unit is maintained, not rewritten by CMake.
emutls_upstream = (sources/"compiler-rt/emutls.c").read_text()
emutls_original = "#define EMUTLS_SKIP_DESTRUCTOR_ROUNDS 0"
emutls_updated = "#define EMUTLS_SKIP_DESTRUCTOR_ROUNDS 1"
assert emutls_upstream.count(emutls_original) == 1
assert (active/"compiler-rt/emutls.c").read_text() == emutls_upstream.replace(emutls_original,emutls_updated)
assert c.count('target_sources(common PRIVATE "${EDEN_MAINTAINED_EMUTLS}" "${COMPILER_RT}/cpu_model_x86.c")') == 1
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_EMUTLS}")' in c
assert 'target_include_directories(common PRIVATE "${COMPILER_RT}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/emutls.c"' not in c
assert 'file(READ "${COMPILER_RT}/emutls.c" emutls)' not in c
print("VENDOR_COMPILER_RT_EMUTLS_PARITY_PASS native_rounds=1")

# Native development GL texture diagnostics: preserve old CMake output.
gl_src = (sources / "eden/src/video_core/renderer_opengl/gl_texture_cache.cpp").read_text()
gl_anchor = "dst_origin.y, dst_origin.z, region.width, region.height, region.depth);"
gl_trace = "        static unsigned copy_errors = 0;\n        const GLenum copy_error = copy_errors < 8 ? glGetError() : GL_NO_ERROR;\n        if (copy_error && copy_errors++ < 8) {\n            GLint sw = 0, dw = 0;\n            glGetTextureLevelParameteriv(src_name, src_origin.level, GL_TEXTURE_WIDTH, &sw);\n            glGetTextureLevelParameteriv(dst_name, dst_origin.level, GL_TEXTURE_WIDTH, &dw);\n            std::printf(\"EDEN_DEV_COPY error=%x src=%u target=%x level=%d x=%d width=%d dst=%u target=%x level=%d x=%d width=%d extent=%dx%dx%d\\n\", copy_error, src_name, src_target, src_origin.level, src_origin.x, sw, dst_name, dst_target, dst_origin.level, dst_origin.x, dw, region.width, region.height, region.depth);\n        }"
assert gl_src.count(gl_anchor) == 1, "Pinned development GL copy site drift"
gl_old_generated = "#include <cstdio>\n" + gl_src.replace(gl_anchor, gl_anchor + "\n" + gl_trace)
assert (active / "eden-core/src/video_core/renderer_opengl/gl_texture_cache.cpp").read_text() == gl_old_generated
assert c.count('list(APPEND video_sources "${EDEN_MAINTAINED_DEV_GL_TEXTURE}")') == 1
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_DEV_GL_TEXTURE}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/gl_texture_cache.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/video_core/renderer_opengl/gl_texture_cache.cpp" texture_source)' not in c
assert 'renderer_opengl/gl_texture_cache.cpp' in (sources / "eden/src/video_core/CMakeLists.txt").read_text()
print("MAINTAINED_GL_TEXTURE_DEV_PARITY_PASS: bounded copy instrumentation")

# A32 fastmem must derive from the *installed shipping backport*, not from
# the original pinned Eden file that is overwritten before CMake configure.
shipping_memory = (active / "eden-backports/src/core/memory.cpp").read_text()
a32_memory = (active / "eden-core/src/core/memory.cpp").read_text()
old_fastmem_guard = "        if (process.IsApplication() && Settings::IsFastmemEnabled()) {"
new_fastmem_guard = "        if (process.IsApplication() && !process.Is64Bit() && Settings::IsFastmemEnabled()) {"
assert shipping_memory.count(old_fastmem_guard) == 1, "shipping memory ABI/input changed"
assert a32_memory == shipping_memory.replace(old_fastmem_guard, new_fastmem_guard)
assert c.count('list(APPEND core_sources "${EDEN_MAINTAINED_A32_MEMORY}")') == 1
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_A32_MEMORY}")' in c
assert 'if(EDEN_A32_FASTMEM)' in c
# G13/X05 no longer derives source in CMake: one selected full native TU.
for label in ("a32","standard"):
    chosen = 'memory_native_'+label+'.cpp'
    assert 'set(EDEN_NATIVE_GUEST_SOURCE "${EDEN_NATIVE_MEMORY_ROOT}/'+chosen+'")' in c
    unit = (active/"eden-core/src/core"/chosen).read_text()
    assert unit.count("ShouldLogUnmappedAccess()") == 11
    assert "std::numeric_limits<u64>::max() - GetInteger(base)" in unit
assert 'file(READ "${eden_cpu_memory_tu}" eden_cpu_memory)' not in c
assert 'include("${EDEN_PORT_DIR}/native_guest_range_overflow.cmake")' not in c
assert 'set_property(SOURCE "${EDEN_NATIVE_GUEST_SOURCE}" TARGET_DIRECTORY core' in c
assert not (root/"headless/native_guest_range_overflow.cmake").exists()
print("MAINTAINED_NATIVE_MEMORY_SOURCE_OWNER_PASS profiles=2")

# Maintained nvdrv session ownership must match the exact pinned generator.
nvdrv_rel = "core/hle/service/nvdrv/core/container.cpp"
nvdrv_pinned = (sources / "eden/src" / nvdrv_rel).read_text()
nvdrv_expected = "#include \"core/core.h\"\n#include <utility>\n" + nvdrv_pinned
for before, after in (
    ("    session.is_active = true;",
     "    process->Open(impl->host1x.System().Kernel()); // Paired with the final CloseSession after SMMU unregistration.\n    session.is_active = true;"),
    ("void Container::CloseSession(SessionId session_id) {\n    std::scoped_lock lk(impl->session_guard);",
     "void Container::CloseSession(SessionId session_id) {\n    std::unique_lock lk(impl->session_guard);"),
    ("    impl->id_pool.emplace_front(session_id.id);",
     "    impl->id_pool.emplace_front(session_id.id);\n    auto* process = std::exchange(session.process, nullptr);\n    lk.unlock(); // Process finalization may close other services.\n    process->Close(impl->host1x.System().Kernel());"),
):
    assert nvdrv_expected.count(before) == 1, ("nvdrv source anchor drift", before)
    nvdrv_expected = nvdrv_expected.replace(before, after)
assert (active / "eden-core/src" / nvdrv_rel).read_text() == nvdrv_expected
assert c.count('list(APPEND core_sources "${EDEN_MAINTAINED_NVDRV_CONTAINER}")') == 1
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_NVDRV_CONTAINER}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/nvdrv_container.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/core/hle/service/nvdrv/core/container.cpp" nvcontainer)' not in c
print("VENDOR_MAINTAINED_NVDRV_SESSION_PARITY_PASS source=1 selections=1")

# The direct controller TU must reproduce the previous CMake-generated TU.
rumble_original = (sources / "eden/src/hid_core/frontend/emulated_controller.cpp").read_text()
rumble_site = "    output_params[LeftIndex] = left_joycon;\n    output_params[RightIndex] = right_joycon;\n"
rumble_insert = "    if (output_params[LeftIndex].Get(\"engine\", \"\").empty()) {\n        const auto rumble_port = std::to_string(Service::HID::NpadIdTypeToIndex(npad_id_type));\n        output_params[LeftIndex] = Common::ParamPackage{\"engine:virtual_gamepad,port:\" + rumble_port + \",pad:1\"};\n        output_params[RightIndex] = Common::ParamPackage{\"engine:virtual_gamepad,port:\" + rumble_port + \",pad:2\"};\n    }\n"
assert rumble_original.count(rumble_site) == 1, "pinned rumble source site changed"
rumble_generated = "#include <string>\n" + rumble_original.replace(rumble_site, rumble_site + rumble_insert)
assert (active / "eden-core/src/hid_core/frontend/emulated_controller.cpp").read_text() == rumble_generated
assert 'list(APPEND controller_sources "${EDEN_MAINTAINED_RUMBLE_CONTROLLER}")' in c
assert 'if(NOT EXISTS "${EDEN_MAINTAINED_RUMBLE_CONTROLLER}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/emulated_controller.cpp"' not in c
print("MAINTAINED_RUMBLE_UNIT_PARITY_PASS selection=hid_core")


# Exact old-source parity for NPad: this must reproduce the former build
# generator applied to the immutable shipping-backport snapshot, not an
# independently rewritten input implementation.
npad_shipping = (active / "eden-backports/src/hid_core/resources/npad/npad.cpp").read_text()
npad_old_pair = "        auto& controller = controller_data[aruid_index][controller_idx];\n        const auto is_connected = controller.device->IsConnected();"
npad_new_pair = "        auto& controller = controller_data[aruid_index][controller_idx];\n        if (controller.device == nullptr) {\n            continue;  // ProsperoEden: this applet resource is not activated yet\n        }\n        const auto is_connected = controller.device->IsConnected();"
npad_old_entry = "void NPad::ControllerUpdate(Kernel::KernelCore& kernel, Core::HID::ControllerTriggerType type, std::size_t controller_idx) {\n"
npad_new_entry = "void NPad::ControllerUpdate(Kernel::KernelCore& kernel, Core::HID::ControllerTriggerType type, std::size_t controller_idx) {\n    if (applet_resource_holder.applet_resource == nullptr) {\n        return;\n    }\n"
assert npad_shipping.count(npad_old_pair) == npad_shipping.count(npad_old_entry) == 1
npad_expected = npad_shipping.replace(npad_old_pair, npad_new_pair).replace(
    npad_old_entry, npad_new_entry)
assert (active / "eden-core/src/hid_core/resources/npad/npad.cpp").read_text() == npad_expected, (
    "Maintained NPad differs from previous CMake source generator")
assert c.count('list(APPEND npad_sources "${EDEN_NPAD_SELECTED}")') == 1
assert c.count('list(FILTER npad_sources EXCLUDE REGEX "(^|/)npad\\\\.cpp$")') == 1
assert 'write_derived("${PORT_BUILD_DIR}/npad.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/hid_core/resources/npad/npad.cpp" npad_source)' not in c
print("MAINTAINED_NPAD_SOURCE_PARITY_PASS guards=2 selection=hid_core")

# Dev NPad is not another instrumented CMake-generated translation unit.
# It is the guarded normal source with one scoped Fullkey event witness.
npad_dev = (active / "eden-core/src/hid_core/resources/npad/npad_pause_diag.cpp").read_text()
npad_prefix = "#include <atomic>\\n#include <cstdio>\\n".replace("\\n", "\n")
assert npad_dev.startswith(npad_prefix)
npad_dev_body = npad_dev[len(npad_prefix):]
fullkey_start = "                npad->fullkey_lifo.WriteNextEntry(pad_state);\n"
fullkey_end = "                break;\n            case Core::HID::NpadStyleIndex::Handheld:"
assert npad_expected.count(fullkey_start + fullkey_end) == 1
assert npad_dev_body.count(fullkey_end) == 1
loc = npad_dev_body.index(fullkey_start + "                {")
tail = npad_dev_body.index(fullkey_end, loc)
instrumentation = npad_dev_body[loc+len(fullkey_start):tail]
for essential in (
    "eden_fullkey_writes.fetch_add(", "eden_fullkey_plus_edges.fetch_add(",
    "eden_fullkey_last_plus.exchange(", "EDEN_NPAD_PLUS_LIFO edges=%llu",
    "EDEN_NPAD_PROGRESS fullkey_writes=%llu", "std::memory_order_relaxed",
):
    assert essential in instrumentation, ("diagnostic NPad witness missing", essential)
assert instrumentation.startswith("                {\n") and instrumentation.endswith("                }\n")
assert npad_dev_body[:loc+len(fullkey_start)] + npad_dev_body[tail:] == npad_expected, (
    "DEV NPad diverges outside the Fullkey diagnostic witness")
assert npad_dev_body.count(npad_new_pair) == 1 and npad_dev_body.count(npad_new_entry) == 1
assert 'set(EDEN_NPAD_SELECTED "${EDEN_MAINTAINED_NPAD_DEV}")' in c
assert 'set(EDEN_NPAD_SELECTED "${EDEN_MAINTAINED_NPAD}")' in c
assert c.count('list(APPEND npad_sources "${EDEN_NPAD_SELECTED}")') == 1
assert 'write_derived("${PORT_BUILD_DIR}/npad_pause_diag.cpp"' not in c
assert 'list(APPEND eden_npad_sources "${PORT_BUILD_DIR}/npad_pause_diag.cpp")' not in c
print("MAINTAINED_NPAD_DEV_PARITY_PASS guards=2 scoped_fullkey_witness=1 selection=exclusive")




# Exact parity with the four former pinned CMake patch-manager replacements.
pm_base = (root / "vendor/sources/eden/src/core/file_sys/patch_manager.cpp").read_text()
pm_pairs = [["std::vector<VirtualDir> patch_dirs = {sdmc_load_dir};","std::vector<VirtualDir> patch_dirs;\n    if (sdmc_load_dir) patch_dirs.push_back(sdmc_load_dir);"],["    std::vector<VirtualDir> patch_dirs = load_dir->GetSubdirectories();\n    if (std::find(disabled.cbegin(), disabled.cend(), \"SDMC\") == disabled.cend()) {","    std::vector<VirtualDir> patch_dirs;\n    if (load_dir != nullptr) patch_dirs = load_dir->GetSubdirectories();\n    if (sdmc_load_dir != nullptr && std::find(disabled.cbegin(), disabled.cend(), \"SDMC\") == disabled.cend()) {"],["const auto this_build_id = fmt::format(\"{:0<64}\", name.substr(0, name.find('.')));","const auto this_build_id = fmt::format(\"{:0<64}\", Common::ToUpper(name.substr(0, name.find('.'))));"],["        LOG_ERROR(Loader, \"Cannot load mods for invalid title_id={:016X}\", title_id);\n",""]]
pm_expected = pm_base
for pos, (old, new) in enumerate(pm_pairs):
    assert pm_expected.count(old) == (1, 1, 1, 3)[pos], ("pinned patch manager drift", pos)
    pm_expected = pm_expected.replace(old, new)
assert (active / "eden-core/src/core/file_sys/patch_manager.cpp").read_text() == pm_expected
assert 'list(APPEND core_sources "${EDEN_MAINTAINED_IPS_LAYER}" "${EDEN_MAINTAINED_PATCH_MANAGER}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/patch_manager.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/core/file_sys/patch_manager.cpp" patch_source)' not in c
print("MAINTAINED_PATCH_MANAGER_PARITY_PASS four substitutions three logs")


# Former X02 slot-vector source generation: exact pinned input replacement.
slot_base = (root / "vendor/sources/eden/src/common/slot_vector.h").read_text()
slot_old = "[[nodiscard]] SlotId insert(Args&&... args) noexcept {\n        const u32 index = FreeValueIndex();\n        new (&values[index].object) T(std::forward<Args>(args)...);"
slot_new = "[[nodiscard]] SlotId insert(Args&&... args) {\n        const u32 index = FreeValueIndex();\n        try {\n            new (&values[index].object) T(std::forward<Args>(args)...);\n        } catch (...) {\n            free_list.push_back(index); // Restores the popped slot without allocating.\n            throw;\n        }"
assert slot_base.count(slot_old) == 1, "Pinned SlotVector constructor changed"
slot_expected = slot_base.replace(slot_old, slot_new)
slot_maintained = active / "eden-core/overrides/slot-vector/common/slot_vector.h"
assert slot_maintained.read_text() == slot_expected, "Maintained SlotVector does not match former CMake"
assert 'target_include_directories(common BEFORE PUBLIC "${EDEN_MAINTAINED_SLOT_VECTOR_ROOT}")' in c
assert 'target_include_directories(video_core BEFORE PRIVATE "${EDEN_MAINTAINED_SLOT_VECTOR_ROOT}")' in c
assert "slot_vector_recovery.cmake" not in c
print("MAINTAINED_SLOT_VECTOR_PARITY_PASS header=common/slot_vector.h")


# X01 historical MacroJIT recovery -- complete source equals old generator.
macro_original = (root / "vendor/sources/eden/src/video_core/macro.cpp").read_text()
macro_replacements = [["        u32 carry_flag{};","        u32 carry_flag{};\n        std::exception_ptr failure;\n        bool failed{};"],["    program(&state, parameters.data(), parameters.data() + parameters.size());","    program(&state, parameters.data(), parameters.data() + parameters.size());\n    if (state.failure) std::rethrow_exception(state.failure);"],["static void MacroJIT_SendThunk(Core::System* system, Engines::Maxwell3D* maxwell3d, Macro::MethodAddress method_address, u32 value) {\n    maxwell3d->CallMethod(*system, method_address.address, value, true);\n}","static void MacroJIT_SendThunk(MacroJITx64Impl::JITState* state, Macro::MethodAddress method_address, u32 value) noexcept {\n    try {\n        state->maxwell3d->CallMethod(*state->system, method_address.address, value, true);\n    } catch (...) {\n        state->failure = std::current_exception();\n        state->failed = true;\n    }\n}"],["    mov(Common::X64::ABI_PARAM1, qword[STATE + offsetof(JITState, system)]);\n    mov(Common::X64::ABI_PARAM2, qword[STATE + offsetof(JITState, maxwell3d)]);\n    mov(Common::X64::ABI_PARAM3.cvt32(), METHOD_ADDRESS);\n    mov(Common::X64::ABI_PARAM4.cvt32(), value);","    mov(Common::X64::ABI_PARAM3.cvt32(), value);\n    mov(Common::X64::ABI_PARAM2.cvt32(), METHOD_ADDRESS);\n    mov(Common::X64::ABI_PARAM1, STATE);"],["    Common::X64::ABI_PopRegistersAndAdjustStack(*this, PersistentCallerSavedRegs(), 0);\n\n    Xbyak::Label dont_process{};","    Common::X64::ABI_PopRegistersAndAdjustStack(*this, PersistentCallerSavedRegs(), 0);\n    cmp(byte[STATE + offsetof(JITState, failed)], 0);\n    jne(end_of_code, T_NEAR);\n\n    Xbyak::Label dont_process{};"]]
macro_derived = "#include <exception>\n" + macro_original
for idx, (before, after) in enumerate(macro_replacements):
    assert macro_derived.count(before) == 1, ("MacroJIT pinned hunk drift", idx)
    macro_derived = macro_derived.replace(before, after)
assert (active / "eden-core/src/video_core/macro.cpp").read_text() == macro_derived
assert 'list(APPEND video_sources "${EDEN_MAINTAINED_MACRO}")' in c
assert 'macro_recovery.cmake' not in c
print("MAINTAINED_MACRO_RECOVERY_PARITY_PASS anchors=5")


# A single canonical override root does not mean every native frontend .inc
# is an upstream patch. Make ALL headless CMake modules and fragments visible,
# so no additional source mutation can appear without review.
single_source_doc = (root / "docs/EDEN_OVERRIDE_SOURCE_OF_TRUTH.md").read_text()
def single_source_table(begin_tag, end_tag):
    assert single_source_doc.count(begin_tag) == single_source_doc.count(end_tag) == 1
    return [
        line.split("`", 2)[1]
        for line in single_source_doc.split(begin_tag)[1].split(end_tag)[0].splitlines()
        if line.startswith("| `headless/")
    ]
candidates_modules = sorted(p.relative_to(root).as_posix() for p in (root/"headless").rglob("*.cmake"))
candidates_fragments = sorted(p.relative_to(root).as_posix() for p in (root/"headless").rglob("*.inc"))
assert single_source_table("<!-- SINGLE_SOURCE_CMAKE_START -->", "<!-- SINGLE_SOURCE_CMAKE_END -->") == candidates_modules, (
    "undocumented headless CMake code/override module", candidates_modules)
assert single_source_table("<!-- SINGLE_SOURCE_FRAGMENTS_START -->", "<!-- SINGLE_SOURCE_FRAGMENTS_END -->") == candidates_fragments, (
    "undocumented headless injected fragment", candidates_fragments)
# Both module and fragment inventories are checked by exact path equality above;
# a second migration-stage numeric assertion would become stale after deletions.
# Derive the expected scope counters from the actual tracked inputs, then
# compare their rendered values with the architecture document. Do not freeze
# migration-stage totals into a separate test (which goes stale every move).
import re
main_generators = len(re.findall(r'write_derived\(\s*"([^"]+)"', c))
# Count exact targets, not just the number of writes: a new generator in
# a previously reviewed module must never hide behind an unchanged total.
module_sites = [
    (name, target)
    for name in candidates_modules
    for target in re.findall(
        r'^\s*write_derived\(\s*"([^"]+)"',
        (root / name).read_text(), re.M
    )
]
module_generators = len(module_sites)
migration_doc = (root / "docs/EDEN_OVERRIDE_MIGRATION_INVENTORY.md").read_text()
module_begin = "<!-- MODULE_GENERATORS_START -->"
module_end = "<!-- MODULE_GENERATORS_END -->"
assert migration_doc.count(module_begin) == migration_doc.count(module_end) == 1
documented_module_sites = re.findall(
    r'^\|\s*M\d+\s*\|\s*\x60([^\x60]+)\x60\s*\|\s*\x60([^\x60]+)\x60\s*\|',
    migration_doc.split(module_begin)[1].split(module_end)[0], re.M
)
assert module_sites == documented_module_sites, (
    "Undocumented CMake module-generated source: migrate to Encore or "
    "review and document its exact owner/target",
    module_sites, documented_module_sites
)
print("ENCORE_MODULE_GENERATOR_OWNER_PASS", f"sites={module_generators}")
source_catalog = (root / "docs/EDEN_ACTIVE_SOURCE_CATALOG.md").read_text()
catalog_start = "<!-- ACTIVE_SOURCE_CATALOG_START -->"
catalog_end = "<!-- ACTIVE_SOURCE_CATALOG_END -->"
assert source_catalog.count(catalog_start) == source_catalog.count(catalog_end) == 1
catalog_rows = re.findall(
    r"^\| \x60[^\x60]+\x60 \|", source_catalog.split(catalog_start)[1].split(catalog_end)[0], re.M
)
main_noun = "générateur" if main_generators == 1 else "générateurs"
assert f"**{main_generators} {main_noun}**" in single_source_doc
module_noun = "générateur" if module_generators == 1 else "générateurs"
assert f"**{module_generators} {module_noun}**" in single_source_doc
total_sites = main_generators + module_generators
site_noun = "site" if total_sites == 1 else "sites"
assert f"**{total_sites} {site_noun}**" in single_source_doc
assert f"**{len(catalog_rows)} sources et en-têtes suivis**" in single_source_doc
for deleted_module in ("headless/macro_recovery.cmake", "headless/slot_vector_recovery.cmake"):
    assert not (root/deleted_module).exists(), ("legacy source generator reintroduced", deleted_module)
print("ENCORE_SINGLE_SOURCE_SCOPE_PASS", f"modules={len(candidates_modules)}", f"fragments={len(candidates_fragments)}")


# Byte-exact relocation of six shared-JIT inputs. Do not permit another
# physical owner under headless after moving the authoritative source.
import subprocess


def check_canonical_git_object(source, expected, label):
    """Prove stored Git object identity and working-tree consistency."""
    relative = source.relative_to(root).as_posix()
    # Git stores vendor sources under the submodule's own HEAD once the
    # parent tracks vendor as a 160000 gitlink. Keep the same canonical
    # blob assertion in both layouts rather than weakening the proof.
    vendor_entry = subprocess.run(
        ["git", "ls-tree", "HEAD", "--", "vendor"], cwd=root,
        check=True, capture_output=True, text=True).stdout.strip()
    is_gitlink = vendor_entry.startswith("160000 commit ") and vendor_entry.endswith("\tvendor")
    repository = root / "vendor" if is_gitlink and relative.startswith("vendor/") else root
    git_path = relative.removeprefix("vendor/") if repository != root else relative
    actual = subprocess.run(
        ["git", "rev-parse", f"HEAD:{git_path}"], cwd=repository,
        check=True, capture_output=True, text=True).stdout.strip()
    assert actual == expected, (label, "Git source blob drift", relative, actual)
    # git diff uses tracked text filters, so this does not mistake a
    # checkout EOL conversion for an intentional source modification.
    result = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", git_path], cwd=repository)
    assert result.returncode == 0, (label, "dirty canonical source", relative)


shared_jit_blobs = {
    "jit_group.h": "50e7f0993ea3db6902bd11bfac496659dce54fb3",
    "jit_group_support.inc": "22cf4c406003cbe2fe1295503dc879086f2ee65e",
    "jit_impl.inc": "953bb5e8455848e143c523b86f1128c4192bc84b",
    "jit_links.inc": "7dfe9cf7eabaabe90c61e74e1242c7712cec3503",
    "jit_push_rsb.inc": "08d4ab5765ef788748ba1c7b283a9cbcfad0d047",
    "jit_state_args.inc": "bee5fe16657a46647690f69c73596b8ee1d03ea4",
}
assert all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in shared_jit_blobs.values()), "Malformed canonical JIT Git object ID"
for filename, original_blob in shared_jit_blobs.items():
    source = active / "eden-core/dynarmic/shared-jit" / filename
    assert source.is_file() and not (root / "headless/dynarmic" / filename).exists(), (
        "duplicate shared JIT fragment or missing canonical owner", filename)
    check_canonical_git_object(source, original_blob, "JIT")
shared_jit_selector = (root / "headless/dynarmic/shared-jit.cmake").read_text()
assert 'set(EDEN_SHARED_JIT_DIR "${PORT_ROOT}/vendor/encore-active/eden-core/dynarmic/shared-jit")' in shared_jit_selector
assert ('configure_file("${EDEN_SHARED_JIT_DIR}/jit_group.h"\n'
        '        "${PORT_BUILD_DIR}/include/dynarmic/backend/x64/jit_group.h" COPYONLY)') in shared_jit_selector
assert 'file(READ "${EDEN_SHARED_JIT_DIR}/jit_group.h" eden_group_header)' not in shared_jit_selector
assert 'write_derived("${PORT_BUILD_DIR}/include/dynarmic/backend/x64/jit_group.h"' not in shared_jit_selector
# Exact M01 parity: an A64JitState header, not a build-time string rewrite.
jit_state_pinned = (sources / "eden/src/dynarmic/src/dynarmic/backend/x64/a64_jitstate.h").read_text()
jit_state_anchor = "    std::array<u64, RSB_SIZE> rsb_codeptrs;\n"
jit_state_added = "\n    // ProsperoEden: what generated code reads instead of embedding it, so that any core can run\n    // code another core compiled (jit_group.h): this core's callbacks and JIT object, TPIDR\n    // registers, exclusive monitor slots, configuration and fast dispatch table.\n    void* eden_callbacks = nullptr;\n    void* eden_jit = nullptr;\n    u64* eden_tpidr_el0 = nullptr;\n    const u64* eden_tpidrro_el0 = nullptr;\n    void* eden_exclusive_address = nullptr;\n    void* eden_exclusive_value = nullptr;\n    const void* eden_conf = nullptr;\n    void* eden_fast_dispatch = nullptr;\n"
assert jit_state_pinned.count(jit_state_anchor) == 1, "Pinned A64JitState layout drift"
jit_state_expected = jit_state_pinned.replace(jit_state_anchor, jit_state_anchor + jit_state_added)
assert (active / "eden-core/dynarmic/shared-jit/a64_jitstate.h").read_text() == jit_state_expected, (
    "Maintained A64JitState differs from historical M01 generation")
assert ('configure_file("${EDEN_SHARED_JIT_DIR}/a64_jitstate.h"\n'
        '        "${PORT_BUILD_DIR}/include/${eden_jitstate_relative}" COPYONLY)') in shared_jit_selector
assert 'write_derived("${PORT_BUILD_DIR}/include/${eden_jitstate_relative}"' not in shared_jit_selector
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/dynarmic/src/${eden_jitstate_relative}"' not in shared_jit_selector
print("ENCORE_SHARED_JIT_STATE_PARITY_PASS M01 exact historical layout, direct maintained copy")
# M03 exact parity: the canonical callback translation unit reproduces
# the previous generated includes, args registry and two call substitutions.
callback_original = (sources / "eden/src/dynarmic/src/dynarmic/backend/x64/callback.cpp").read_text()
callback_args = (active / "eden-core/dynarmic/shared-jit/jit_state_args.inc").read_text()
callback_changes = (
    ("namespace Dynarmic::Backend::X64 {\n",
     "namespace Dynarmic::Backend::X64 {\n" + callback_args),
    ("    code.mov(code.ABI_PARAM1, arg);\n    code.CallFunction(fn);\n}",
     "    EdenLoadArg(code, code.ABI_PARAM1, arg);\n    code.CallFunction(fn);\n}"),
    ("    code.mov(code.ABI_PARAM2, arg);\n#endif",
     "    EdenLoadArg(code, code.ABI_PARAM2, arg);\n#endif"),
)
callback_expected = callback_original
for before, after in callback_changes:
    assert callback_expected.count(before) == 1, ("Pinned shared-JIT callback anchor drift", before)
    callback_expected = callback_expected.replace(before, after)
callback_expected = "#include <array>\n#include <atomic>\n#include <cstdlib>\n#include <optional>\n" + callback_expected
assert (active / "eden-core/dynarmic/shared-jit/callback.cpp").read_text() == callback_expected, (
    "Maintained shared-JIT callback differs from M03 output")
assert ('configure_file("${EDEN_SHARED_JIT_DIR}/callback.cpp"\n'
        '        "${PORT_BUILD_DIR}/callback.cpp" COPYONLY)') in shared_jit_selector
assert 'write_derived("${PORT_BUILD_DIR}/callback.cpp"' not in shared_jit_selector
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/dynarmic/src/dynarmic/backend/x64/callback.cpp"' not in shared_jit_selector
print("ENCORE_SHARED_JIT_CALLBACK_PARITY_PASS M03 full tracked C++")
print("ENCORE_SHARED_JIT_SOURCE_OWNERS_PASS", len(shared_jit_blobs))


# Scalar Dynarmic fragments have one physical authority in encore-active.
# These are original Git blobs, not regenerated C++ from CMake strings.
scalar_canonical_blobs = {
    "scalar-fold.inc": "00dcb6ae900c314c396b61013e2adf9ec42a0fa8",
    "scalar-memory-read.inc": "4c3c1ad419af0fbd01bb64b2aac9be65b7b31fc0",
    "scalar-memory-write.inc": "3d86e3e8ca2294a4dfe244063950db583dc22af9",
}
for filename, expected in scalar_canonical_blobs.items():
    source = active / "eden-core/dynarmic/scalar" / filename
    assert source.is_file() and not (root / "headless" / filename).exists(), (
        "scalar injection has duplicate or missing authority", filename)
    check_canonical_git_object(source, expected, "scalar")
scalar_module = (root / "headless/scalar-memory.cmake").read_text()
assert 'file(READ "${EDEN_SCALAR_INPUT_DIR}/scalar-memory-${lower}.inc" scalar_access)' not in scalar_module
assert "set(memory_source" not in scalar_module
for variant in ("standard", "checked"):
    compiled = (active / f"eden-core/src/dynarmic/backend/x64/emit_x64_memory_{variant}.cpp.inc").read_text()
    for direction in ("read", "write"):
        oracle = (active / f"eden-core/dynarmic/scalar/scalar-memory-{direction}.inc").read_text()
        assert oracle in compiled, ("lost scalar fallback", variant, direction)
assert not (root / "headless/checked-fastmem.cmake").exists()
assert 'write_derived("' not in scalar_module
assert 'list(APPEND jit_sources "${EDEN_MAINTAINED_SCALAR_BACKEND}/emit_x64_${unit}.cpp")' in scalar_module
for unit in ("vector", "data_processing"):
    assert (active / f"eden-core/src/dynarmic/backend/x64/emit_x64_{unit}.cpp").is_file()
assert (root / "tools/check-maintained-scalar-emitters.py").is_file()
# Both Fermi2D variants are full tracked sources; native CMake selects,
# and the ordinary mode remains OFF for unqualified layered copies.
for fermi_variant in ("fermi_2d_observed.cpp", "fermi_2d_experimental.cpp"):
    assert (active / "eden-core/src/video_core/engines" / fermi_variant).is_file()
fermi_selector = (root / "headless/gpu_native_observability.cmake").read_text()
assert 'option(EDEN_UNQUALIFIED_FERMI2D_COPY "3D software blit experiments" OFF)' in fermi_selector
assert 'write_derived(' not in fermi_selector
assert (root / "tools/check-maintained-fermi2d-variants.py").is_file()
print("VENDOR_MAINTAINED_FERMI2D_VARIANTS_OWNER_PASS")

# Maxwell PRMT translations now live in the complete tracked shader unit.
assert (active / "eden-core/src/shader_recompiler/frontend/maxwell/translate/impl/not_implemented.cpp").is_file()
assert 'target_sources(shader_recompiler PRIVATE "${EDEN_MAINTAINED_NATIVE_PRMT}")' in (root / "headless/gpu_native_observability.cmake").read_text()
assert (root / "tools/check-maintained-maxwell-prmt.py").is_file()
print("VENDOR_MAINTAINED_PRMT_OWNER_PASS")

# OpenGL rasterizer diagnostics now compile from one selected full source.
gl_rasterizer_dir = active / "eden-core/src/video_core/renderer_opengl"
assert (gl_rasterizer_dir / "gl_rasterizer.cpp").is_file()
assert (gl_rasterizer_dir / "gl_rasterizer_dev.cpp").is_file()
assert 'list(APPEND video_sources "${EDEN_MAINTAINED_GL_RASTERIZER}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/gl_rasterizer.cpp"' not in c
assert (root / "tools/check-maintained-opengl-rasterizer.py").is_file()
print("VENDOR_MAINTAINED_GL_RASTERIZER_OWNER_PASS")

# Native GPU software blitter has a tracked complete source based on the
# shipping backport; the former three edits are tested outside CMake.
assert (active / "eden-core/src/video_core/engines/sw_blitter/blitter.cpp").is_file()
assert 'target_sources(video_core PRIVATE "${EDEN_MAINTAINED_NATIVE_BLITTER}")' in (root / "headless/gpu_native_observability.cmake").read_text()
assert (root / "tools/check-maintained-sw-blitter.py").is_file()
print("VENDOR_MAINTAINED_SW_BLITTER_OWNER_PASS")

# KProcess finalization timing is selected from a complete DEV-only TU.
assert (active / "eden-core/src/core/hle/kernel/k_process.cpp").is_file()
assert 'list(APPEND process_core_sources "${EDEN_MAINTAINED_DEV_PROCESS}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/k_process.cpp"' not in c
assert (root / "tools/check-maintained-kprocess-dev.py").is_file()
print("VENDOR_MAINTAINED_KPROCESS_DEV_OWNER_PASS")

# Xbyak writable alias uses a complete tagged header. Only the separate
# code_source transformation remains indirect, explicitly inventoried.
assert (active / "eden-build/third_party/xbyak/xbyak.h").is_file()
assert 'configure_file("${EDEN_MAINTAINED_XBYAK_HEADER}"' in (root / "headless/jit-alias.cmake").read_text()
assert (root / "tools/check-maintained-xbyak-alias.py").is_file()
print("VENDOR_MAINTAINED_XBYAK_OWNER_PASS")

# Dynarmic block-range pair is maintained and the old headless source pair
# is retired. The build selects the complete units directly.
assert (active / "eden-core/src/dynarmic/backend/block_range_information.cpp").is_file()
assert (active / "eden-core/src/dynarmic/backend/block_range_information.h").is_file()
assert 'target_sources(dynarmic PRIVATE\n    "${EDEN_MAINTAINED_BLOCK_RANGE_DIR}/block_range_information.cpp")' in c
assert (root / "tools/check-maintained-block-range.py").is_file()
print("VENDOR_MAINTAINED_BLOCK_RANGE_OWNER_PASS")

# Native JIT constant pool has a complete tracked source and explicit selector.
assert (active / "eden-core/src/dynarmic/backend/x64/constant_pool.cpp").is_file()
assert 'target_sources(dynarmic PRIVATE "${EDEN_MAINTAINED_CONSTANT_POOL}")' in (root / "headless/jit-alias.cmake").read_text()
assert (root / "tools/check-maintained-constant-pool.py").is_file()
print("VENDOR_MAINTAINED_CONSTANT_POOL_OWNER_PASS")

# RegAlloc now has complete tracked sources and one explicit selector.
regalloc_dir = active / "eden-core/src/dynarmic/backend/x64"
assert (regalloc_dir / "reg_alloc.h").is_file() and (regalloc_dir / "reg_alloc.cpp").is_file()
assert "write_derived(" not in (root / "headless/dynarmic/reg_alloc.cmake").read_text()
assert (root / "tools/check-maintained-reg-alloc.py").is_file()
print("VENDOR_MAINTAINED_REGALLOC_OWNER_PASS")

# Sparse memory table is maintained as a full header; replay lives in a standalone host oracle.
assert (active / "eden-core/src/common/sparse_large_vector.h").is_file()
assert 'configure_file("${EDEN_MAINTAINED_SPARSE_VECTOR}"' in c
assert 'write_derived("${PORT_BUILD_DIR}/sparse/common/sparse_large_vector.h"' not in c
assert (root / "tools/check-maintained-sparse-vector.py").is_file()
print("VENDOR_MAINTAINED_SPARSE_OWNER_PASS")

# Dynarmic scalar source-only equivalence, no generator in CMake.
scalar_root = sources / "eden/src/dynarmic/src/dynarmic"
base_impl = (scalar_root / "frontend/A64/translate/impl/impl.cpp").read_text()
old_r = "    return ir.VectorGetElement(bitsize, ir.GetQ(vec), 0);"
new_r = "    return ir.VectorGetElement(bitsize, bitsize == 32 || bitsize == 64 ? V(bitsize, vec) : ir.GetQ(vec), 0);"
old_w = "    ir.SetQ(vec, ir.ZeroExtendToQuad(value));"
new_w = ("    if (bitsize == 32 || bitsize == 64) {\n"
         "        V(bitsize, vec, ir.ZeroExtendToQuad(value));\n"
         "    } else {\n"
         "        ir.SetQ(vec, ir.ZeroExtendToQuad(value));\n"
         "    }")
assert base_impl.count(old_r) == base_impl.count(old_w) == 1
assert (active / "eden-core/src/dynarmic/frontend/A64/translate/impl/impl.cpp").read_text() == base_impl.replace(old_r, new_r).replace(old_w, new_w)
base_trans = (scalar_root / "frontend/A64/translate/a64_translate.cpp").read_text()
old_inc = '"dynarmic/frontend/A64/translate/impl/impl.cpp"'
assert base_trans.count(old_inc) == 1
assert (active / "eden-core/src/dynarmic/frontend/A64/translate/a64_translate.cpp").read_text() == base_trans.replace(old_inc, '"impl/impl.cpp"')
base_opt = (scalar_root / "ir/opt_passes.cpp").read_text()
opt_anchor = "        case Op::LeastSignificantWord:\n            FoldLeastSignificantWord(inst);\n            break;"
assert base_opt.count(opt_anchor) == 1
fold_oracle = (active / "eden-core/dynarmic/scalar/scalar-fold.inc").read_text()
assert (active / "eden-core/src/dynarmic/ir/opt_passes.cpp").read_text() == base_opt.replace(opt_anchor, opt_anchor + "\n" + fold_oracle)
assert 'target_sources(dynarmic PRIVATE\n    "${EDEN_MAINTAINED_SCALAR_TRANSLATOR}"\n    "${EDEN_MAINTAINED_SCALAR_OPT}")' in c
for retired in ("scalar_impl.cpp", "a64_translate.cpp", "opt_passes.cpp"):
    assert 'write_derived("${PORT_BUILD_DIR}/' + retired + '"' not in c
assert 'file(READ "${EDEN_SCALAR_INPUT_DIR}/scalar-fold.inc" scalar_fold)' not in c
print("VENDOR_MAINTAINED_SCALAR_TUS_PARITY_PASS: scalar lanes, local impl include, IR folding")
assert 'set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${EDEN_SCALAR_INPUTS})' in c
assert 'set(EDEN_SCALAR_INPUT_DIR' in c
print("ENCORE_SCALAR_CANONICAL_INPUTS_PASS", len(scalar_canonical_blobs))


# The five previous Vulkan injection fragments are retained solely as
# historical comparison fixtures, never inputs to the shipping renderer.
vulkan_oracle_sources = {
    "vulkan_loading.inc": "2dbae2a22ac0a7ce17e9b39c9b08ba35d896fc01",
    "vulkan_hud_prepare.inc": "36c585ed6726206722450450be7f0c5bb3cafb2d",
    "vulkan_hud_draw.inc": "794563c243b53ecccc4191f2a7de1b7dad0d2b2a",
    "vulkan_gc_downloads.inc": "f59f02df433d65a89467aab8c4845f3c9e0b03ae",
    "vulkan_download_batch.inc": "f3e36e0432f7026a65620329f79cbbe20e1c898a",
}
for filename, expected_git_blob in vulkan_oracle_sources.items():
    oracle = active / "eden-vulkan-oracles" / filename
    assert oracle.is_file() and not (root / "headless" / filename).exists()
    check_canonical_git_object(oracle, expected_git_blob, "Vulkan oracle")
    assert filename not in vulkan, ("test fixture is still a native CMake input", filename)
assert (active / "eden-vulkan/vulkan_renderer.cpp").is_file()
print("ENCORE_VULKAN_ORACLE_SCOPE_PASS", len(vulkan_oracle_sources))


# GPU memory manager: exact reconstruction of the retired native CMake source.
# This is an offline witness, never an alternate generated production file.
gpu_expected = (root / "vendor/sources/eden/src/video_core/memory_manager.cpp").read_text()
gpu_hunks = [
    ('#include "memory_manager.h"\n', "", 1),
    ("    if (!IsContinuousRange(src_addr, size)) {", "    if (size == 0 || src_addr >= address_space_size ||\n        size > address_space_size - src_addr ||\n        !IsContinuousRange(src_addr, size)) {", 2),
    ("bool MemoryManager::IsGranularRange(GPUVAddr gpu_addr, std::size_t size) const {\n", "bool MemoryManager::IsGranularRange(GPUVAddr gpu_addr, std::size_t size) const {\n    if (gpu_addr >= address_space_size || size == 0 || size > address_space_size - gpu_addr) {\n        return false;\n    }\n", 1),
    ("            const std::size_t page{(page_index & big_page_mask) + size};\n            return page <= big_page_size;", "            return size <= big_page_size - (gpu_addr & big_page_mask);", 1),
    ("const std::size_t page{(gpu_addr & Core::DEVICE_PAGEMASK) + size};\n", "", 2),
    ("return page <= Core::DEVICE_PAGESIZE;", "return size <= Core::DEVICE_PAGESIZE - (gpu_addr & Core::DEVICE_PAGEMASK);", 2),
]
for index, (before, after, expected_count) in enumerate(gpu_hunks):
    assert gpu_expected.count(before) == expected_count, ("GPU pinned anchor drift", index)
    gpu_expected = gpu_expected.replace(before, after)
gpu_maintained = active / "eden-core/src/video_core/memory_manager.cpp"
assert gpu_maintained.is_file()
gpu_actual = gpu_maintained.read_text()
if gpu_actual != gpu_expected:
    # N51 optional changed-PTE batching is in the same production source owner.
    # Both *complete* source identities must remain exact; no regex deletion
    # or blind acceptance of other video_core/memory_manager.cpp changes.
    import hashlib
    def git_blob_id(text):
        raw = text.encode()
        return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert git_blob_id(gpu_expected) == "f30099dfb5df01d9cd787d199e3e61f28205669a", (
        "pre-NS2 GPU source baseline drift")
    # The N51 GPU batching owner has one later, independently reviewed P1.2
    # revision. P1.2 adds checked cross-page scalars and a physical-backing
    # fallback. Match the *entire* canonical blob; do not accept a general
    # source variant or declare the historical five-hunk oracle identical.
    owner_sha = git_blob_id(gpu_actual)
    n51_sha = "c7923dbbef27a9088dbfcb33c162e3c7069679c1"
    p12_sha = "7dba34b3e300515cd5b0a8579fe893072cb70b24"
    # Complete P1.2 successor reviewed against the historical generated TU:
    # bounds checks on unmap, sparse walks and GMMU address ranges; physical
    # device-backed block fallbacks and scalar paging are preserved. This is
    # an exact blob admission, never a general substring-based exception.
    p12_bounded_sha = "b5caf9fa5b0477b005249d4b87bac89934bf4c50"
    p12_walk_guarded_sha = "836c0653652957a996db89ba7a7d5c48db1350a8"
    assert owner_sha in (n51_sha, p12_sha, p12_bounded_sha, p12_walk_guarded_sha), (
        "unreviewed changed-PTE/P1.2 GPU source drift", owner_sha)
    assert "#ifdef EDEN_NS2_GPU_RANGE_BATCH" in gpu_actual
    if owner_sha in (p12_sha, p12_bounded_sha, p12_walk_guarded_sha):
        assert '#include "native_paged_scalar.h"' in gpu_actual
        assert "Eden::GpuScalar::Read(addr, value" in gpu_actual
        assert "Eden::GpuScalar::Write(addr, data" in gpu_actual
        assert gpu_actual.count("memory.GetSpan(dev_addr_base, copy_amount)") == 4
        assert "memory.ReadBlockUnsafe(dev_addr_base, dest_buffer, copy_amount)" in gpu_actual
        assert "memory.WriteBlockUnsafe(dev_addr_base, src_buffer, copy_amount)" in gpu_actual
        if owner_sha in (p12_bounded_sha, p12_walk_guarded_sha):
            assert gpu_actual.count("size > address_space_size -") >= 7
            assert "const size_t page_last{((addr + size - 1) >> page_bits) + 1};" in gpu_actual
            assert "GetSubmappedRangeImpl<true>(gpu_addr, size, result);" in gpu_actual
    if owner_sha == p12_walk_guarded_sha:
        # Not just a new allowlist entry: remove precisely the three audited
        # range guards and prove the complete previous owner blob reappears.
        # Any other code mutation would break this replay even if someone
        # inadvertently updated an opaque hash in the inventory.
        exact_guards = (
            """    // Every mapped/unmapped guest region traverses this common PTE walker.
    // Neither a wrapped 64-bit range nor a span past the configured 40/49-bit
    // guest VA limit may probe the backing page table, even via SafeRead.
    if (size == 0 || gpu_src_addr >= address_space_size ||
        size > address_space_size - gpu_src_addr) return;
""",
            """    // Invalid GPU command spans follow the existing unmapped-read contract:
    // return zero bytes without visiting an out-of-range PTE or stale page.
    if (size == 0) return;
    if (gpu_src_addr >= address_space_size ||
        size > address_space_size - gpu_src_addr) {
        std::memset(dest_buffer, 0, size);
        return;
    }
""",
            """    // A refused write must not queue a dirty interval with a wrapping address.
    if (size == 0 || gpu_dest_addr >= address_space_size ||
        size > address_space_size - gpu_dest_addr) return;
""",
        )
        previous_owner = gpu_actual
        for guard in exact_guards:
            assert previous_owner.count(guard) == 1, "missing P1.2 walker guard"
            previous_owner = previous_owner.replace(guard, "")
        assert git_blob_id(previous_owner) == p12_bounded_sha, (
            "P1.2 GPU PTE walker mutation exceeds exactly reviewed guards")
        walker_test = root / "tools/ns2/check_native_gpu_memory_walker_bounds_host.py"
        assert walker_test.is_file() and "MemoryOperation" in walker_test.read_text()
    # N51's independent source-normalisation witness must also pin both
    # complete blobs and recheck all batching operands after removing N51.
    n51_guard = (root / "tools/ns2/check_egl_gpu_range_batch.py").read_text()
    assert f'n51_original = "{n51_sha}"' in n51_guard
    assert f'p12_protected = "{p12_sha}"' in n51_guard
    assert f'p12_bounded = "{p12_bounded_sha}"' in n51_guard
    assert f'p12_walk_guarded = "{p12_walk_guarded_sha}"' in n51_guard
    assert 't.count("memory.GetSpan(dev_addr_base, copy_amount)") == 4' in n51_guard

assert 'list(APPEND video_sources "${EDEN_NATIVE_GPU_MEMORY_MANAGER}")' in c
assert c.count('list(REMOVE_ITEM video_sources "memory_manager.cpp")') == 1
assert 'write_derived("${eden_gpu_span_tu}"' not in c
print("MAINTAINED_GPU_MEMORY_MANAGER_PARITY_PASS patches=5 sites=8 selection=video_core")

# Exact historical CMake generation witness; never produces production code.
network_original = (root / "vendor/sources/eden/src/core/internal_network/network.cpp").read_text()
network_old_start = "void Initialize() {\n    if (pipe("
network_old_end = "void Finalize() {\n    if (interrupt_pipe_fd"
network_init = "void Initialize() {\n    if (socketpair(AF_UNIX, SOCK_STREAM, 0, interrupt_pipe_fd) != 0)\n        throw std::runtime_error(\"Native wakeup socketpair failed\");\n    try {\n        unsigned char value = 0x5a, received = 0;\n        errno = 0;\n        const auto written = send(interrupt_pipe_fd[1], &value, 1, MSG_DONTWAIT);\n        const int write_error = errno;\n        errno = 0;\n        const auto count = recv(interrupt_pipe_fd[0], &received, 1, MSG_DONTWAIT);\n        const int read_error = errno;\n        std::printf(\"EDEN_SOCKET_PRIME write=%lld write_errno=%d read=%lld read_errno=%d value=%u\\n\",\n            static_cast<long long>(written), write_error, static_cast<long long>(count), read_error, received);\n        if (written != 1 || count != 1 || received != value)\n            throw std::runtime_error(\"Native wakeup socketpair initialization failed\");\n    } catch (...) {\n        for (int& fd : interrupt_pipe_fd) { close(fd); fd = -1; }\n        throw;\n    }\n}\n\n"
network_interrupt = "    errno = 0;\n    const auto written = send(interrupt_pipe_fd[1], &value, sizeof(value), MSG_DONTWAIT);\n    const int write_error = errno;\n    // A full nonblocking stream already has a pending wakeup for poll().\n    if (written == -1 && (write_error == EAGAIN || write_error == EWOULDBLOCK)) return;\n    if (written != 1) std::fprintf(stderr, \"EDEN_SOCKET_INTERRUPT result=%lld errno=%d\\n\",\n        static_cast<long long>(written), write_error);\n    ASSERT(written == 1);\n"
assert network_original.count("namespace Network {") == 1
assert network_original.count(network_old_start) == 1
assert network_original.count(network_old_end) >= 1
network_expected = network_original.replace("namespace Network {",
    "namespace Network {\\n#ifndef IPPROTO_DCCP\\nconstexpr int IPPROTO_DCCP = 33;\\n#endif".replace("\\n", "\n"))
begin = network_expected.index(network_old_start)
ending = network_expected.index(network_old_end, begin)
network_expected = network_expected[:begin] + network_init + network_expected[ending:]
old_write = "    ASSERT(write(interrupt_pipe_fd[1], &value, sizeof(value)) == 1);"
old_read = "ssize_t ret = read(interrupt_pipe_fd[0], &value, sizeof(value));"
assert network_expected.count(old_write) == 1 and network_expected.count(old_read) == 1
network_expected = network_expected.replace(old_write, network_interrupt)
network_expected = network_expected.replace(old_read,
    "ssize_t ret = recv(interrupt_pipe_fd[0], &value, sizeof(value), MSG_DONTWAIT);")
network_expected = "#include <cstdio>\\n#include <stdexcept>\\n".replace("\\n", "\n") + network_expected
assert (active / "eden-core/src/core/internal_network/network.cpp").read_text() == network_expected
assert 'list(APPEND core_sources "${EDEN_NATIVE_NETWORK_SOURCE}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/network.cpp"' not in c
print("MAINTAINED_NETWORK_SOURCE_PARITY_PASS transformations=5")


gpu_injection_blobs = {
    "gpu_sync_failure_wait.inc": "8840ab6d3e440321191765a823496e7f68d7feb3",
}
for filename, expected_blob in gpu_injection_blobs.items():
    input_source = active / "eden-core/gpu-injections" / filename
    assert input_source.is_file() and not (root / "headless" / filename).exists()
    check_canonical_git_object(input_source, expected_blob, "GPU injection")
    # G21 no longer injects this historic method from active CMake.
    # Preserve its canonical blob only as a parity oracle while proving the
    # full native GPU owners contain the same failure-aware wait.
    legacy_g21 = (root / "tools/fixtures/legacy-g21-gpu.cmake").read_text()
    assert f'/eden-core/gpu-injections/{filename}"' in legacy_g21
    assert f'/eden-core/gpu-injections/{filename}"' not in c
    historic_wait = input_source.read_text().strip()
    for gpu_name in ("gpu_gl_host.cpp", "gpu_gl_host_dev.cpp",
                     "gpu_gl_native.cpp", "gpu_gl_native_dev.cpp"):
        unit = (active/"eden-core/src/video_core"/gpu_name).read_text()
        assert historic_wait in unit, ("G21 wait drift", gpu_name)
# The old queue injection was redundant and has been removed outright:
# the same stop-aware method has a single shipping owner in eden-gpu.
assert not (active / "eden-core/gpu-injections/gpu_queue_stop_wait.inc").exists()
assert 'gpu_queue_stop_wait.inc' not in c
queue_header = (active / "eden-gpu/include/common/bounded_threadsafe_queue.h").read_text()
assert queue_header.count("bool EmplaceWaitWithStopToken(") == 1
for variant in ("gpu_thread_dev.cpp", "gpu_thread_quiet.cpp"):
    worker = (active / "eden-gpu" / variant).read_text()
    assert "state.queue.EmplaceWaitWithStopToken(stop_source.get_token()," in worker
assert 'configure_file("${EDEN_ACTIVE_GPU}/include/common/bounded_threadsafe_queue.h"' in c
print("ENCORE_GPU_INJECTIONS_CANONICAL_PASS", len(gpu_injection_blobs))


# Historical CMake transformations are an exact oracle only, never compiled.
vi_pinned = (root/"vendor/sources/eden/src/core/hle/service/vi/conductor.cpp").read_text()
vi_pairs = [["    for (auto& [display_id, manager] : m_vsync_managers) {\n        m_container.ComposeOnDisplay(&m_swap_interval, &m_compose_speed_scale, display_id);\n        manager.SignalVsync(m_system.Kernel());\n    }","    if (const int compose_delay = ::Eden::Performance::compose_delay_us.load(std::memory_order_relaxed);\n        compose_delay > 0 && m_system.IsMulticore()) {\n        for (auto& [display_id, manager] : m_vsync_managers) {\n            manager.SignalVsync(m_system.Kernel());\n        }\n        std::this_thread::sleep_for(std::chrono::microseconds(compose_delay));\n        for (auto& [display_id, manager] : m_vsync_managers) {\n            m_container.ComposeOnDisplay(&m_swap_interval, &m_compose_speed_scale, display_id);\n        }\n        return;\n    }\n    for (auto& [display_id, manager] : m_vsync_managers) {\n        m_container.ComposeOnDisplay(&m_swap_interval, &m_compose_speed_scale, display_id);\n        manager.SignalVsync(m_system.Kernel());\n    }"],["    const f32 effective_fps = 60.f / static_cast<f32>(m_swap_interval);\n    return static_cast<s64>(speed_scale * (1000000000.f / effective_fps));","    const f32 effective_fps = 60.f / static_cast<f32>(m_swap_interval);\n    ::Eden::Display::game_millihertz.store(static_cast<int>(effective_fps * 1000.f / speed_scale),\n                                           std::memory_order_relaxed);\n    return static_cast<s64>(speed_scale * (1000000000.f / effective_fps));"]]
for old, new in vi_pairs:
    assert vi_pinned.count(old)==1, ("pinned VI source drift", old[:65])
    vi_pinned=vi_pinned.replace(old,new)
vi_expected="#include \"display_refresh.h\"\n#include \"performance.h\"\n#include <thread>\n"+vi_pinned
assert (active/"eden-core/src/core/hle/service/vi/conductor.cpp").read_text()==vi_expected, "VI source parity mismatch"
assert 'list(APPEND core_sources "${EDEN_MAINTAINED_VI_CONDUCTOR}")' in c
assert 'target_include_directories(core PRIVATE "${EDEN_PORT_DIR}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/vi_conductor.cpp"' not in c
print("ENCORE_VI_CONDUCTOR_PARITY_PASS",len(vi_pairs))


# Earlier pinned spin-lock generator is retired. The owned translation unit
# is a byte-exact copy of its old emitted C++ at migration; this Git blob
# locks the accepted source, while the prefix remains from pinned Dynarmic.
spin_source = active / "eden-core/src/dynarmic/common/spin_lock_x64.cpp"
check_canonical_git_object(spin_source, "a64e6302d78be07870038ba990c3487c4ce6bd75", "native spin lock")
spin_pinned = (root/"vendor/sources/eden/src/dynarmic/src/dynarmic/common/spin_lock_x64.cpp").read_text()
spin_marker = "namespace {\\nstruct SpinLockImpl".replace("\\n","\n")
assert spin_pinned.count(spin_marker)==1
assert spin_source.read_text().startswith(spin_pinned.split(spin_marker,1)[0])
assert spin_source.read_text().count("void SpinLock::Lock() noexcept") == 1
assert spin_source.read_text().count("void SpinLock::Unlock() noexcept") == 1
assert "__atomic_exchange_n(&storage, 1, __ATOMIC_SEQ_CST)" in spin_source.read_text()
assert 'target_sources(dynarmic PRIVATE "${EDEN_MAINTAINED_SPIN_LOCK}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/spin_lock_x64.cpp"' not in c
assert not (root/"headless/spin-lock.inc").exists()
print("ENCORE_NATIVE_SPIN_LOCK_SOURCE_PASS")

# Historical CMake IPS/patch-text fixes (eight eden_patch substitutions plus
# the function-body splice) now have one canonical C++ owner. This SHA is
# the exact Git blob calculated from the old generator on the pinned source.
ips_layer = active / "eden-core/src/core/file_sys/ips_layer.cpp"
check_canonical_git_object(ips_layer, "f6687abf25ef2874c06c2523c530b5ba197e6d45", "IPS")
assert 'set(EDEN_MAINTAINED_IPS_LAYER' in c
assert 'list(APPEND core_sources "${EDEN_MAINTAINED_IPS_LAYER}" "${EDEN_MAINTAINED_PATCH_MANAGER}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/ips_layer.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/core/file_sys/ips_layer.cpp" ips_source)' not in c
assert "set(ips_escape [=[" not in c
print("MAINTAINED_IPS_LAYER_SOURCE_PASS pinned_generator_blob=f6687abf")


# R428 per-layer ASTC scratch is now a canonical, selected C++ source. Its
# Git blob was derived by applying the single historical CMake raw-string
# replacement against the pinned Eden texture utility.
astc_maintained = active / "eden-core/src/video_core/texture_cache/util.cpp"
# Preserve the complete R428 source except named 3D-layout/policy changes.
import hashlib
astc_previous = astc_maintained.read_text()
# This selected translation unit now includes the native-only R312 texture
# descriptor guard. Verify its complete semantics, then reverse *only* this
# reviewed delta before comparing against the pinned R428 ASTC git blob.
# Any other change to the texture owner continues to fail closed.
tic_begin = astc_previous.index("bool IsValidEntry(")
tic_end = astc_previous.index("\nboost::container::small_vector<BufferImageCopy", tic_begin)
tic_active = astc_previous[tic_begin:tic_end]
tic_baseline = (root / "vendor/sources/eden/src/video_core/texture_cache/util.cpp").read_text()
tic_base_start = tic_baseline.index("bool IsValidEntry(")
tic_base_end = tic_baseline.index("\nboost::container::small_vector<BufferImageCopy", tic_base_start)
tic_baseline = tic_baseline[tic_base_start:tic_base_end]
expected_tic_native = '''bool IsValidEntry(const Tegra::MemoryManager& gpu_memory, const TICEntry& config) {
#ifdef PS5_NATIVE
    // The zero TIC format is invalid. Reject it before constructing a
    // fallback RGBA image view (which can sample unrelated guest backing).
    if (config.format == static_cast<Tegra::Texture::TextureFormat>(0)) {
        return false;
    }
#endif
    const GPUVAddr address = config.Address();
    if (address == 0) {
        return false;
    }
    if (address >= (1ULL << 40)) {
        return false;
    }
    if (gpu_memory.GpuToCpuAddress(address).has_value()) {
        return true;
    }
#ifdef PS5_NATIVE
    // The range overload can succeed when only a *later* page is mapped.
    // That is not proof the first page of a non-sparse texture exists.
    if (config.is_sparse == 0) {
        return false;
    }
#endif
    const ImageInfo info{config};
    const size_t guest_size_bytes = CalculateGuestSizeInBytes(info);
    return gpu_memory.GpuToCpuAddress(address, guest_size_bytes).has_value();
}'''
assert tic_active == expected_tic_native + '\n', 'native TIC guard unreviewed drift'
assert astc_previous.count(tic_active) == 1
astc_previous = astc_previous.replace(tic_active, tic_baseline)
astc_layout_edits = [
    ('    u32 output_offset = 0;\n    Common::ScratchBuffer<u8> decode_scratch;\n\n    const Extent2D tile_size = DefaultBlockSize(info.format);', '    if (copies.empty()) {\n        return;\n    }\n    u32 output_offset = 0;\n    Common::ScratchBuffer<u8> decode_scratch;\n\n    // One conversion must use one format policy for all its mip levels.\n    const auto recompression_setting = Settings::values.astc_recompression.GetValue();\n    const bool astc = IsPixelFormatASTC(info.format);\n    const Extent2D tile_size = DefaultBlockSize(info.format);'),
    ('        const auto recompression_setting = Settings::values.astc_recompression.GetValue();\n        const bool astc = IsPixelFormatASTC(info.format);\n\n        if (astc && recompression_setting == Settings::AstcRecompression::Uncompressed) {', '        if (astc && recompression_setting == Settings::AstcRecompression::Uncompressed) {'),
    ('                             copy.image_subresource.num_layers *\n                             BytesPerBlock(PixelFormat::A8B8G8R8_UNORM);', '                             copy.image_extent.depth * copy.image_subresource.num_layers *\n                             BytesPerBlock(PixelFormat::A8B8G8R8_UNORM);'),
    ('                             copy.image_subresource.num_layers *\n                             ConvertedBytesPerBlock(info.format);', '                             copy.image_extent.depth * copy.image_subresource.num_layers *\n                             ConvertedBytesPerBlock(info.format);'),
]
for before, after in reversed(astc_layout_edits):
    assert astc_previous.count(after) == 1, 'texture layout delta drift'
    astc_previous = astc_previous.replace(after, before)
astc_blob = astc_previous.encode()
assert hashlib.sha1(b'blob ' + str(len(astc_blob)).encode() + b'\0' + astc_blob).hexdigest() == '8f393887e88d7e38681fea109074338bba5b26fc', 'unreviewed texture utility drift'
assert 'list(APPEND video_sources "${EDEN_MAINTAINED_TEXTURE_UTIL}")' in c
assert 'set(EDEN_MAINTAINED_TEXTURE_UTIL' in c
assert 'write_derived("${PORT_BUILD_DIR}/texture_cache_util.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/video_core/texture_cache/util.cpp" eden_texture_util)' not in c
assert 'set(eden_astc_decode_old [=[' not in c
print("MAINTAINED_ASTC_TEXTURE_PARITY_PASS R428")


# The host-only GPU header is tracked in Encore too: byte-for-byte
# equivalence to the old CMake fallback (8 queue slots plus stop/join).
host_original = (root / "vendor/sources/eden/src/video_core/gpu_thread.h").read_text()
host_queue_old = "using CommandQueue = Common::SPSCQueue<CommandDataContainer>;"
host_queue_new = "using CommandQueue = Common::SPSCQueue<CommandDataContainer, 8>;"
host_stop_old = "    ~ThreadManager();"
host_stop_new = "    ~ThreadManager();\\n    void Stop() { thread.request_stop(); if (thread.joinable()) thread.join(); }".replace("\\n", "\n")
assert host_original.count(host_queue_old) == host_original.count(host_stop_old) == 1
host_expected = host_original.replace(host_queue_old, host_queue_new).replace(host_stop_old, host_stop_new)
host_canonical = active / "eden-core/host-gpu/include/video_core/gpu_thread.h"
assert host_canonical.read_text() == host_expected, "Host GPU header parity drift"
assert 'configure_file("${EDEN_MAINTAINED_HOST_GPU_HEADER}"' in c
assert 'write_derived("${PORT_BUILD_DIR}/include/video_core/gpu_thread.h"' not in c
print("MAINTAINED_HOST_GPU_HEADER_PARITY_PASS slots=8 stop_join=1")


# The previous CMake shader cache generator used a pinned source prefix,
# one recovery include and the original namespace tail. Compare the
# directly selected complete source to that exact old textual contract.
shader_pinned = (root / "vendor/sources/eden/src/video_core/shader_environment.cpp").read_text()
shader_begin = shader_pinned.find("void LoadPipelines(")
shader_end = shader_pinned.rfind("} // namespace VideoCommon")
assert shader_begin > 0 and shader_end > shader_begin
shader_prefix = "#include <cstdio>\n#include <new>\n#include <stdexcept>\n#include <system_error>\n"
shader_expected = (shader_prefix + shader_pinned[:shader_begin] +
                   '#include "shader_cache_reader.inc"\n\n' +
                   shader_pinned[shader_end:])
shader_maintained = active / "eden-core/src/video_core/shader_environment.cpp"
reader_maintained = active / "eden-core/src/video_core/shader_cache_reader.inc"
assert shader_maintained.read_text() == shader_expected, "Shader cache source not equivalent to old CMake"
assert reader_maintained.is_file() and not (root / "headless/shader_cache_reader.inc").exists()
check_canonical_git_object(reader_maintained, "5d652ca5cd6d8ec919c04902a18d87247673e523", "shader cache reader")
assert 'list(APPEND video_sources "${EDEN_MAINTAINED_SHADER_ENVIRONMENT}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/shader_environment.cpp"' not in c
print("ENCORE_SHADER_CACHE_SOURCE_PARITY_PASS", "source and reader canonical")


# The selected BSD source equals all five previous CMake instrumentation
# replacements on top of the immutable shipping backport, modulo the
# equivalent quoted header resolved through core's headless include path.
bsd_shipping = (active / "eden-backports/src/core/hle/service/sockets/bsd.cpp").read_text()
bsd_expected = '#include "network_audit.h"\n' + bsd_shipping
bsd_replacements = [["    const Errno result = Translate(file_descriptors[fd]->socket->Connect(Translate(addr_in)));","    const Errno result = Translate(file_descriptors[fd]->socket->Connect(Translate(addr_in)));\n    if ((result == Errno::SUCCESS || result == Errno::ISCONN) && eden_network_audit_active()) {\n        const auto peer = Translate(addr_in);\n        const std::string host = Network::IPv4AddressToString(peer.ip) + \":\" + std::to_string(peer.portno);\n        eden_network_audit_event(\"guest\", \"connect\", host.c_str(), 0, 0);\n    }"],["    return Translate(file_descriptors[fd]->socket->Send(message, flags));","    const auto send_result = Translate(file_descriptors[fd]->socket->Send(message, flags));\n    if (send_result.first > 0 && eden_network_audit_active()) {\n        const std::string descriptor = \"fd:\" + std::to_string(fd);\n        eden_network_audit_event(\"guest\", \"tx\", descriptor.c_str(), send_result.first, 0);\n    }\n    return send_result;"],["    return Translate(file_descriptors[fd]->socket->SendTo(flags, message, p_addr_in));","    const auto sent = Translate(file_descriptors[fd]->socket->SendTo(flags, message, p_addr_in));\n    if (sent.first > 0 && eden_network_audit_active()) {\n        const std::string target = p_addr_in ? Network::IPv4AddressToString(p_addr_in->ip) + \":\" + std::to_string(p_addr_in->portno) : \"fd:\" + std::to_string(fd);\n        eden_network_audit_event(\"guest\", \"tx\", target.c_str(), sent.first, 0);\n    }\n    return sent;"],["    const auto [ret, bsd_errno] = Translate(descriptor.socket->Recv(flags, message));","    const auto [ret, bsd_errno] = Translate(descriptor.socket->Recv(flags, message));\n    if (ret > 0 && eden_network_audit_active()) {\n        const std::string descriptor = \"fd:\" + std::to_string(fd);\n        eden_network_audit_event(\"guest\", \"rx\", descriptor.c_str(), ret, 0);\n    }"],["    const auto [ret, bsd_errno] = Translate(descriptor.socket->RecvFrom(flags, message, p_addr_in));","    const auto [ret, bsd_errno] = Translate(descriptor.socket->RecvFrom(flags, message, p_addr_in));\n    if (ret > 0 && eden_network_audit_active()) {\n        const std::string target = p_addr_in ? Network::IPv4AddressToString(p_addr_in->ip) + \":\" + std::to_string(p_addr_in->portno) : \"fd:\" + std::to_string(fd);\n        eden_network_audit_event(\"guest\", \"rx\", target.c_str(), ret, 0);\n    }"]]
for i, (needle, replacement) in enumerate(bsd_replacements):
    assert bsd_expected.count(needle) == 1, ("shipping guest BSD anchor changed", i)
    bsd_expected = bsd_expected.replace(needle, replacement)
assert (active / "eden-core/src/core/hle/service/sockets/bsd.cpp").read_text() == bsd_expected, (
    "audited guest BSD no longer matches the old CMake transformation")
assert 'list(APPEND core_sources "${EDEN_MAINTAINED_GUEST_BSD}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/audited_guest_bsd.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/core/hle/service/sockets/bsd.cpp" audited_bsd)' not in c
assert 'target_include_directories(core PRIVATE "${EDEN_PORT_DIR}")' in c
print("MAINTAINED_GUEST_BSD_PARITY_PASS rewrites=5 shipping_backport=preserved")


# Former CMake guest DNS substitutions are now a host-only equality oracle.
dns_base = (active / "eden-backports/src/core/hle/service/sockets/sfdnsres.cpp").read_text()
dns_first = dns_base.find("static const constexpr std::array blockedDomains = {")
dns_last = dns_base.find("static NetDbError GetAddrInfoErrorToNetDbError")
assert dns_first >= 0 and dns_last > dns_first
dns_expected = dns_base[:dns_first] + dns_base[dns_last:]
dns_pairs = [["    // Prevent resolution of Nintendo servers\n    if (IsBlockedHost(host)) {\n        LOG_WARNING(Network, \"Resolution of hostname {} requested, returning EAI_AGAIN\", host);\n        return {0, GetAddrInfoError::AGAIN};\n    }\n\n","",2],["    if (eden_network_host_blocked(host.c_str())) return {0, GetAddrInfoError::NODATA};","    const bool encore_denied = eden_network_host_blocked(host.c_str()) != 0;\n    eden_network_audit_event(\"guest\", encore_denied ? \"dns-denied\" : \"dns-allowed\", host.c_str(), 0, encore_denied ? 1 : 0);\n    if (encore_denied) return {0, GetAddrInfoError::NODATA};",2],["    auto res_v = Network::GetAddressInfo(host, /*service*/ std::nullopt);","    auto res_v = Network::GetAddressInfo(host, /*service*/ std::nullopt);\n    if (eden_network_audit_active()) {\n        const bool found = std::get_if<std::vector<Network::AddrInfo>>(&res_v) != nullptr;\n        eden_network_audit_event(\"guest\", found ? \"dns-resolved\" : \"dns-error\", host.c_str(), 0, found ? 0 : 1);\n    }",1],["    auto res_v = Network::GetAddressInfo(host, service);","    auto res_v = Network::GetAddressInfo(host, service);\n    if (eden_network_audit_active()) {\n        const bool found = std::get_if<std::vector<Network::AddrInfo>>(&res_v) != nullptr;\n        eden_network_audit_event(\"guest\", found ? \"dns-resolved\" : \"dns-error\", host.c_str(), 0, found ? 0 : 1);\n    }",1]]
for i, (old, new, occurrences) in enumerate(dns_pairs):
    assert dns_expected.count(old) == occurrences, ("shipping guest DNS drift", i)
    dns_expected = dns_expected.replace(old, new)
assert "IsBlockedHost" not in dns_expected
dns_expected = '#include "network_audit.h"\n' + dns_expected
assert (active / "eden-core/src/core/hle/service/sockets/sfdnsres.cpp").read_text() == dns_expected
assert 'list(APPEND core_sources "${EDEN_MAINTAINED_GUEST_DNS}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/audited_guest_dns.cpp"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/core/hle/service/sockets/sfdnsres.cpp" audited_dns)' not in c
assert 'target_include_directories(core PRIVATE "${EDEN_PORT_DIR}")' in c
print("MAINTAINED_GUEST_DNS_SOURCE_PARITY_PASS old_rewrites=5 denied_policy=retained")


# Exact parity of the four former CMake C++ span-constructor fixes.
# Production only copies the complete versioned nvdrv header.
ioctl_pinned = (root / "vendor/sources/eden/src/core/hle/service/nvdrv/devices/ioctl_serialization.h").read_text()
ioctl_pairs = [["(fixed, inl_out,","(fixed, std::span<InlOutVarArg>{inl_out.data(), inl_out.size()},"],["(var, std::forward","(std::span<VarArg>{var.data(), var.size()}, std::forward"],["(fixed, var,","(fixed, std::span<VarArg>{var.data(), var.size()},"],["(fixed, inl_in,","(fixed, std::span<InlInVarArg>{inl_in.data(), inl_in.size()},"]]
ioctl_expected = ioctl_pinned
for before, after in ioctl_pairs:
    assert ioctl_expected.count(before) == 1, ("ioctl header baseline drift", before)
    ioctl_expected = ioctl_expected.replace(before, after)
ioctl_active = active / "eden-core/src/core/hle/service/nvdrv/devices/ioctl_serialization.h"
assert ioctl_active.read_text() == ioctl_expected, "ioctl maintained header differs from former generated source"
assert 'configure_file("${EDEN_MAINTAINED_IOCTL}"' in c
assert 'target_include_directories(core BEFORE PRIVATE "${PORT_BUILD_DIR}/include")' in c
assert 'write_derived("${PORT_BUILD_DIR}/include/${ioctl_header}"' not in c
assert 'file(READ "${PROJECT_SOURCE_DIR}/src/${ioctl_header}" ioctl_source)' not in c
print("ENCORE_MAINTAINED_NVDRV_IOCTL_PARITY_PASS replacements=4")

# Keep the generator inventory synchronized with every future source migration.
# It catalogs CMake invocations, not physical output files from variable loops.
import re
inventory = (root / "docs/EDEN_OVERRIDE_MIGRATION_INVENTORY.md").read_text()
# Do not hide active non-CMake source transforms behind the CMake-only
# generator counter. The matching inventory names real build entrypoints,
# historical replayers and independent source-equivalence oracles.
assert "## Overrides et générateurs hors CMake principal" in inventory
for relative in (
    "tools/prepare-build.sh", "tools/install-vendored-eden-backports.py",
    "tools/install-vendored-eden-build-flags.py",
    "tools/install-vendored-surface-lifecycle.py",
    "tools/install-vendored-radv.py", "tools/install-active-core-backports.py",
    "tools/apply-eden-backports.sh", "tools/prepare-vulkan-port.py",
    "tools/patch-radv-wsi.py", "tools/sync-encore-overrides.py",
    "tools/sync-glyph-overrides.py", "tools/launcher/strings.py",
    "tools/build-headless-host.sh", "tools/build-opengl-sdk.sh",
    "tools/build-headless-native.sh", "tools/materialize-openssl-cert.py",
    "tools/build-radv-dependencies.sh", "tools/radv-active-inputs.py",
):
    assert (root / relative).is_file(), ("untracked script entrypoint", relative)
    assert "`" + relative + "`" in inventory, ("script override not catalogued", relative)
staging = (root / "tools/prepare-build.sh").read_text()
assert 'python3 -B tools/install-active-core-backports.py "$eden"' in staging
active_core_installer = (root / "tools/install-active-core-backports.py").read_text()
assert 'ACTIVE = ROOT / "vendor/encore-active/eden-core"' in active_core_installer
assert "shutil.copyfile(maintained, tmp)" in active_core_installer
assert "maintained_bytes != new:" in active_core_installer
assert "maintained_bytes.replace(header, b\"\").replace(" in active_core_installer
assert "guest_counter, original_counter) != new" in active_core_installer
assert "N76 modified unrelated native A64 source" in active_core_installer
assert 'python3 -B tools/install-vendored-eden-backports.py --repair-owned-cache "$eden"' in staging
cache_installer = (root / "tools/install-vendored-eden-backports.py").read_text()
assert 'def is_owned_cached_source(destination:Path)->bool:' in cache_installer
assert 'if current!=contract[\'upstream\'] and (' in cache_installer
assert 'saved_stale.get(rel)!=current' in cache_installer
assert 'EDEN_STALE_SOURCE_PRESERVED' in cache_installer
assert 'python3 -B tools/check-vendored-eden-cache-rebase-host.py' in (
    root / ".github/workflows/encore-core-preflight.yml").read_text()
assert 'python3 -B tools/install-vendored-eden-build-flags.py "$eden"' in staging
assert 'python3 -B tools/install-vendored-surface-lifecycle.py "$eden"' in staging
assert 'tools/prepare-vulkan-port.py' not in vulkan
radv_legacy = (root / "tools/patch-radv-wsi.py").read_text()
assert "if not oracle:" in radv_legacy and "Legacy RADV source rewrite disabled" in radv_legacy
assert 'patch-radv-wsi.py --check' in staging
native_builder = (root / "tools/build-headless-native.sh").read_text()
assert 'tools/materialize-openssl-cert.py' in native_builder
radv_builder = (root / "tools/build-radv-dependencies.sh").read_text()
assert "current.write_text(derived)" in radv_builder
assert "trap restore_cross_ini EXIT" in radv_builder
assert 'tools/install-vendored-radv.py' in radv_builder

# Maxwell conditional-render diagnostic: exact former generated DEV code.
maxwell_pinned = (sources / "eden/src/video_core/engines/maxwell_3d.cpp").read_text()
maxwell_old_accel = "    if (rasterizer->AccelerateConditionalRendering()) {\n        execute_on = true;\n        return;\n    }"
maxwell_new_accel = "    if (rasterizer->AccelerateConditionalRendering()) {\n        execute_on = true;\n        ::Eden::Performance::CountCondition(0);\n        return;\n    }"
maxwell_old_end = "    }\n    }\n}\n\nvoid Maxwell3D::ProcessCounterReset() {"
maxwell_new_end = "    }\n    }\n    ::Eden::Performance::CountCondition(\n        regs.render_enable_override == Regs::RenderEnable::Override::AlwaysRender ? 1u :\n        regs.render_enable_override == Regs::RenderEnable::Override::NeverRender ? 2u :\n        3u + static_cast<unsigned>(regs.render_enable.mode) * 2u + (execute_on ? 1u : 0u));\n}\n\nvoid Maxwell3D::ProcessCounterReset() {"
assert maxwell_pinned.count(maxwell_old_accel) == maxwell_pinned.count(maxwell_old_end) == 1
maxwell_expected = '#include "performance.h"\n' + maxwell_pinned.replace(maxwell_old_accel, maxwell_new_accel).replace(maxwell_old_end, maxwell_new_end)
assert (active / "eden-core/src/video_core/engines/maxwell_3d.cpp").read_text() == maxwell_expected
assert 'list(APPEND video_sources "${EDEN_MAINTAINED_DEV_MAXWELL}")' in c
assert 'write_derived("${PORT_BUILD_DIR}/maxwell_3d.cpp"' not in c
print("VENDOR_MAINTAINED_MAXWELL_DEV_PARITY_PASS: two render-condition instruments")
# Native RADV startup: previously generated from the pinned boilerplate,
# with one ps5_fp_ieee call before C++ static initializers.
radv_crt_original = (sources / "boilerplate/tooling/native/app_crt.cpp").read_text()
radv_old = 'extern "C" void _init()\n{'
radv_new = 'extern "C" void ps5_fp_ieee();\nextern "C" void _init()\n{\n    ps5_fp_ieee();'
assert radv_crt_original.count(radv_old) == 1
assert (active / "eden-build/tooling/native/app_crt_radv.cpp").read_text() == radv_crt_original.replace(radv_old, radv_new)
assert 'set(eden_app_crt "${EDEN_MAINTAINED_RADV_CRT}")' in c
assert 'write_derived("${eden_app_crt}"' not in c
print("VENDOR_MAINTAINED_RADV_CRT_PARITY_PASS: pinned startup and native-only variant")

# R437: the native BufferCache is a tracked header, never reassembled by CMake.
r437_rel = "eden-core/src/video_core/buffer_cache/buffer_cache.h"
r437_back = (active / "eden-backports/src/video_core/buffer_cache/buffer_cache.h").read_text()
r437_before = ("    const auto size = buffer.SizeBytes();\n    if (insert) {\n"
                "        total_used_memory += Common::AlignUp(size, 1024);")
r437_after = ("    const auto size = buffer.SizeBytes();\n    if (insert) {\n"
               "        ::Eden::BufferPages::Mark(buffer.CpuAddr(), size);\n"
               "        total_used_memory += Common::AlignUp(size, 1024);")
assert r437_back.count(r437_before) == 1
r437_expected = '#include "buffer_pages.h"\n' + r437_back.replace(r437_before, r437_after)
# Preserve the native DMA copy span guard when reconstructing the maintained
# BufferCache header. FindBuffer/SynchronizeBuffer narrow their spans to u32.
copy_before = ("bool BufferCache<P>::DMACopy(GPUVAddr src_address, GPUVAddr dest_address, u64 amount) {\n"
               "    const std::optional<DAddr> cpu_src_address = gpu_memory->GpuToCpuAddress(src_address);")
copy_after = ("bool BufferCache<P>::DMACopy(GPUVAddr src_address, GPUVAddr dest_address, u64 amount) {\n"
              "    // FindBuffer and SynchronizeBuffer accept u32 byte spans. Never truncate\n"
              "    // a wider DMA request: the caller can take its ordinary software path.\n"
              "    // Reject empty copies before dirty-range bookkeeping as well.\n"
              "    if (amount == 0 || amount > static_cast<u64>(~u32{0})) {\n"
              "        return false;\n"
              "    }\n"
              "    const std::optional<DAddr> cpu_src_address = gpu_memory->GpuToCpuAddress(src_address);")
assert r437_expected.count(copy_before) == 1
r437_expected = r437_expected.replace(copy_before, copy_after)
clear_start = r437_expected.index('bool BufferCache<P>::DMAClear(')
clear_end = r437_expected.index('\ntemplate <class P>', clear_start)
clear_body = r437_expected[clear_start:clear_end]
clear_old = '    const bool dest_dirty = IsRegionRegistered(*cpu_dst_address, amount);'
assert clear_body.count(clear_old) == 1
clear_body = clear_body.replace('    const size_t size = amount * sizeof(u32);\n', '').replace(
    clear_old, '    // FindBuffer accepts a u32 byte span; never truncate or issue an empty fill.\n'
    '    if (amount == 0 || amount > static_cast<u64>(~u32{0}) / sizeof(u32)) {\n'
    '        return false;\n'
    '    }\n'
    '    // The DMA amount counts u32 values; registration is measured in bytes.\n'
    '    const size_t size = amount * sizeof(u32);\n'
    '    const bool dest_dirty = IsRegionRegistered(*cpu_dst_address, size);')
r437_expected = r437_expected[:clear_start] + clear_body + r437_expected[clear_end:]
# Native-only buffer registration fix: a non-overlapping owner in the
# first partial page must not hide another owner on a subsequent page.
region_before = "bool BufferCache<P>::IsRegionRegistered(DAddr addr, size_t size) {\n    const DAddr end_addr = addr + size;"
region_after = "bool BufferCache<P>::IsRegionRegistered(DAddr addr, size_t size) {\n    // An empty CPU write does not overlap any registered cache buffer.\n    if (size == 0) {\n        return false;\n    }\n    // The page_table has exactly 16 GiB of guest-physical address space.\n    // Reject unrepresentable/overflowing spans before addr + size or page_table[].\n    constexpr DAddr kTableAddressLimit = DAddr{1} << 34;\n    if (addr >= kTableAddressLimit || size > kTableAddressLimit - addr) {\n        return false;\n    }\n    const DAddr end_addr = addr + size;"
region_skip_before = "        if (buf_start_addr < end_addr && addr < buf_end_addr) {\n            return true;\n        }\n        page = Common::DivCeil(end_addr, CACHING_PAGESIZE);"
region_skip_after = "        if (buf_start_addr < end_addr && addr < buf_end_addr) {\n            return true;\n        }\n        // The first page can contain a buffer ending before addr. A later\n        // page may belong to another registered buffer intersecting the span.\n        // Do not skip all remaining pages after one non-overlapping owner.\n        ++page;"
assert r437_expected.count(region_before) == r437_expected.count(region_skip_before) == 1
r437_expected = r437_expected.replace(region_before, region_after).replace(
    region_skip_before, region_skip_after)
# Native-only zero-tick GPU fence fast path: the scheduler cannot wait
# for tick zero, and the shipping backport remains byte-for-byte pinned.
zero_tick_before = "        const u64 buffer_tick = buffer.getWriteTick();\n        if (!runtime.IsFree(buffer_tick)) {\n            runtime.Wait(buffer_tick);\n        }"
zero_tick_after = "        const u64 buffer_tick = buffer.getWriteTick();\n        // New and never-GPU-written buffers have a zero fence tick.\n        // Scheduler::Wait(0) cannot wait; skip its IsFree semaphore probe.\n        if (buffer_tick != 0 && !runtime.IsFree(buffer_tick)) {\n            runtime.Wait(buffer_tick);\n        }"
assert r437_expected.count(zero_tick_before) == 1
r437_expected = r437_expected.replace(zero_tick_before, zero_tick_after)
# Native-only unmapped uniform CBUF guard. A missing GPU-to-CPU
# translation must clear the previous slot binding without optional UB.
unmapped_uniform_before = "    const std::optional<DAddr> device_addr = gpu_memory->GpuToCpuAddress(gpu_addr);\n    const Binding binding{\n        .device_addr = *device_addr,\n        .size = size,\n        .buffer_id = BufferId{},\n    };"
unmapped_uniform_after = "    const std::optional<DAddr> device_addr = gpu_memory->GpuToCpuAddress(gpu_addr);\n    if (!device_addr) {\n        // An unmapped cbuf is not a valid CPU-backed GPU buffer. Retire any\n        // previous slot binding instead of dereferencing an empty optional.\n        channel_state->uniform_buffers[stage][index] = NULL_BINDING;\n        return;\n    }\n    const Binding binding{\n        .device_addr = *device_addr,\n        .size = size,\n        .buffer_id = BufferId{},\n    };"
assert r437_expected.count(unmapped_uniform_before) == 1
r437_expected = r437_expected.replace(unmapped_uniform_before, unmapped_uniform_after)
# Native-only table-capacity guard ported from Lichii nx2. The span must
# remain in-range as well as its first page; keep pinned backports immutable.
find_page_before = ("BufferId BufferCache<P>::FindBuffer(DAddr device_addr, u32 size, bool sparse_compatible) {\n"
                    "    if (device_addr == 0) {\n        return NULL_BUFFER_ID;\n    }\n"
                    "    const u64 page = device_addr >> CACHING_PAGEBITS;\n")
find_page_after = ("BufferId BufferCache<P>::FindBuffer(DAddr device_addr, u32 size, bool sparse_compatible) {\n"
                   "    // An unmapped/invalid guest-physical address must never index outside\n"
                   "    // the fixed 16 GiB page table. Keep this guard before any buffer lookup.\n"
                   "    const u64 page = device_addr >> CACHING_PAGEBITS;\n"
                   "    if (device_addr == 0 || page >= page_table.size() ||\n"
                   "        size > (u64{page_table.size()} << CACHING_PAGEBITS) - device_addr) {\n"
                   "        return NULL_BUFFER_ID;\n    }\n")
assert r437_expected.count(find_page_before) == 1
r437_expected = r437_expected.replace(find_page_before, find_page_after)
# Native-only vertex buffer extent hardening: never truncate a 64-bit
# guest GPU range to u32 before checking the exclusive-end bounds.
vertex_extent_old = "    const u32 address_size = static_cast<u32>(gpu_addr_end - gpu_addr_begin);\n    u32 size = address_size; // TODO: Analyze stride and number of vertices"
vertex_extent_new = "    // GPU addresses are 64-bit. Truncating the range before validation\n    // could turn a valid >=4 GiB vertex span into zero or a tiny buffer.\n    const u64 address_size =\n        gpu_addr_end > gpu_addr_begin ? gpu_addr_end - gpu_addr_begin : 0;\n    u32 size = static_cast<u32>((std::min)(address_size, static_cast<u64>(~u32{0})));"
vertex_clip_old = "    if (!gpu_memory->IsWithinGPUAddressRange(gpu_addr_end) || size >= 64_MiB) {\n        size = static_cast<u32>(gpu_memory->MaxContinuousRange(gpu_addr_begin, size));\n    }\n    const BufferId buffer_id = FindBuffer(*device_addr, size, false);"
vertex_clip_new = "    if (!gpu_memory->IsWithinGPUAddressRange(gpu_addr_end) || size >= 64_MiB) {\n        size = static_cast<u32>(gpu_memory->MaxContinuousRange(gpu_addr_begin, size));\n        if (size == 0) {\n            // No mapped contiguous data: never create a zero-byte vertex\n            // buffer or retain the previous draw's vertex binding.\n            channel_state->vertex_buffers[index] = NULL_BINDING;\n            UpdateVertexBufferSlot(index, NULL_BINDING);\n            return;\n        }\n    }\n    const BufferId buffer_id = FindBuffer(*device_addr, size, false);"
assert r437_expected.count(vertex_extent_old) == r437_expected.count(vertex_clip_old) == 1
r437_expected = r437_expected.replace(vertex_extent_old, vertex_extent_new).replace(vertex_clip_old, vertex_clip_new)
# Native-only index buffer extent hardening: detect 64-bit GPU limits and
# 32-bit index arithmetic overflow before converting to FindBuffer(u32).
index_before = "    const u32 address_size = static_cast<u32>(gpu_addr_end - gpu_addr_begin);\n    const u32 draw_size = (index_buffer_ref.count + index_buffer_ref.first) * u32(index_buffer_ref.FormatSizeInBytes());\n    const u32 size = (std::min)(address_size, draw_size);"
index_after = "    // Both the GPU range and (first + count) * format size can exceed\n    // 32 bits. Compare their full widths before bounding FindBuffer(u32).\n    const u64 address_size =\n        gpu_addr_end > gpu_addr_begin ? gpu_addr_end - gpu_addr_begin : 0;\n    const u64 index_count =\n        static_cast<u64>(index_buffer_ref.count) + index_buffer_ref.first;\n    const u64 draw_size = index_count * index_buffer_ref.FormatSizeInBytes();\n    const u32 size = static_cast<u32>((std::min)(\n        (std::min)(address_size, draw_size), static_cast<u64>(~u32{0})));"
assert r437_expected.count(index_before) == 1
r437_expected = r437_expected.replace(index_before, index_after)
# Native-only indirect draw extent validation; preserve source replay.
indirect_before = "    const auto update = [this](GPUVAddr gpu_addr, size_t size, Binding& binding) {\n        const std::optional<DAddr> device_addr = gpu_memory->GpuToCpuAddress(gpu_addr);"
indirect_after = "    const auto update = [this](GPUVAddr gpu_addr, size_t size, Binding& binding) {\n        // The binding and FindBuffer accept u32 bytes. An empty or wider\n        // indirect command range must not wrap into a valid-looking buffer.\n        if (size == 0 || size > static_cast<size_t>(~u32{0})) {\n            binding = NULL_BINDING;\n            return;\n        }\n        const std::optional<DAddr> device_addr = gpu_memory->GpuToCpuAddress(gpu_addr);"
assert r437_expected.count(indirect_before) == 1
r437_expected = r437_expected.replace(indirect_before, indirect_after)
# Reject null guest indirect bindings end-to-end: no null-buffer touch or Vulkan submit.
indirect_null_before_0 = "    const auto bind_buffer = [this](const Binding& binding) {\n        Buffer& buffer = slot_buffers[binding.buffer_id];"
indirect_null_after_0 = "    const auto bind_buffer = [this](const Binding& binding) {\n        // An unmapped or rejected guest indirect draw has no real VkBuffer.\n        // Never touch or synchronize the null sentinel as if it were live.\n        if (binding.buffer_id == NULL_BUFFER_ID || binding.size == 0) {\n            return;\n        }\n        Buffer& buffer = slot_buffers[binding.buffer_id];"
assert r437_expected.count(indirect_null_before_0) == 1
r437_expected = r437_expected.replace(indirect_null_before_0, indirect_null_after_0)
indirect_null_before_1 = "std::pair<typename BufferCache<P>::Buffer*, u32> BufferCache<P>::GetDrawIndirectCount() {\n    auto& buffer = slot_buffers[channel_state->count_buffer_binding.buffer_id];\n    return std::make_pair(&buffer, buffer.Offset(channel_state->count_buffer_binding.device_addr));\n}"
indirect_null_after_1 = "std::pair<typename BufferCache<P>::Buffer*, u32> BufferCache<P>::GetDrawIndirectCount() {\n    const Binding& binding = channel_state->count_buffer_binding;\n    if (binding.buffer_id == NULL_BUFFER_ID || binding.size == 0) {\n        return {nullptr, 0};\n    }\n    auto& buffer = slot_buffers[binding.buffer_id];\n    return std::make_pair(&buffer, buffer.Offset(binding.device_addr));\n}"
assert r437_expected.count(indirect_null_before_1) == 1
r437_expected = r437_expected.replace(indirect_null_before_1, indirect_null_after_1)
indirect_null_before_2 = "std::pair<typename BufferCache<P>::Buffer*, u32> BufferCache<P>::GetDrawIndirectBuffer() {\n    auto& buffer = slot_buffers[channel_state->indirect_buffer_binding.buffer_id];\n    return std::make_pair(&buffer,\n                          buffer.Offset(channel_state->indirect_buffer_binding.device_addr));\n}"
indirect_null_after_2 = "std::pair<typename BufferCache<P>::Buffer*, u32> BufferCache<P>::GetDrawIndirectBuffer() {\n    const Binding& binding = channel_state->indirect_buffer_binding;\n    if (binding.buffer_id == NULL_BUFFER_ID || binding.size == 0) {\n        return {nullptr, 0};\n    }\n    auto& buffer = slot_buffers[binding.buffer_id];\n    return std::make_pair(&buffer, buffer.Offset(binding.device_addr));\n}"
assert r437_expected.count(indirect_null_before_2) == 1
r437_expected = r437_expected.replace(indirect_null_before_2, indirect_null_after_2)
# Reject oversized native graphics SSBO/TBO slots before masks or table access.
graphics_slot_before_0 = "bool BufferCache<P>::BindGraphicsStorageBuffer(size_t stage, size_t ssbo_index, u32 cbuf_index,\n                                               u32 cbuf_offset, bool is_written) {\n    const bool already_enabled ="
graphics_slot_after_0 = "bool BufferCache<P>::BindGraphicsStorageBuffer(size_t stage, size_t ssbo_index, u32 cbuf_index,\n                                               u32 cbuf_offset, bool is_written) {\n    // Reject excess shader slots before shifting a u32 mask or indexing the\n    // per-stage storage array. Compute bindings already enforce this limit.\n    if (stage >= NUM_STAGES || ssbo_index >= NUM_STORAGE_BUFFERS) [[unlikely]] {\n        LOG_ERROR(HW_GPU, \"Graphics storage buffer stage={} index={} exceeds supported slots\",\n                  stage, ssbo_index);\n        return false;\n    }\n    const bool already_enabled ="
assert r437_expected.count(graphics_slot_before_0) == 1
r437_expected = r437_expected.replace(graphics_slot_before_0, graphics_slot_after_0)
graphics_slot_before_1 = "void BufferCache<P>::BindGraphicsTextureBuffer(size_t stage, size_t tbo_index, GPUVAddr gpu_addr,\n                                               u32 size, PixelFormat format, bool is_written,\n                                               bool is_image) {\n    channel_state->enabled_texture_buffers[stage] |="
graphics_slot_after_1 = "void BufferCache<P>::BindGraphicsTextureBuffer(size_t stage, size_t tbo_index, GPUVAddr gpu_addr,\n                                               u32 size, PixelFormat format, bool is_written,\n                                               bool is_image) {\n    // A malformed descriptor array must not shift by >=32 or overwrite an\n    // adjacent stage's texture binding. Compute already guards its slots.\n    if (stage >= NUM_STAGES || tbo_index >= NUM_TEXTURE_BUFFERS) [[unlikely]] {\n        LOG_ERROR(HW_GPU, \"Graphics texture buffer stage={} index={} exceeds supported slots\",\n                  stage, tbo_index);\n        return;\n    }\n    channel_state->enabled_texture_buffers[stage] |="
assert r437_expected.count(graphics_slot_before_1) == 1
r437_expected = r437_expected.replace(graphics_slot_before_1, graphics_slot_after_1)
# Maintain bounded graphics and compute SSBO CBUF indices in the selected source.
ssbo_cbuf_before_0 = "    if (stage >= NUM_STAGES || ssbo_index >= NUM_STORAGE_BUFFERS) [[unlikely]] {\n        LOG_ERROR(HW_GPU, \"Graphics storage buffer stage={} index={} exceeds supported slots\",\n                  stage, ssbo_index);"
ssbo_cbuf_after_0 = "    if (stage >= NUM_STAGES || ssbo_index >= NUM_STORAGE_BUFFERS ||\n        cbuf_index >= maxwell3d->state.shader_stages[stage].const_buffers.size()) [[unlikely]] {\n        LOG_ERROR(HW_GPU, \"Graphics SSBO stage={} slot={} cbuf={} exceeds supported slots\",\n                  stage, ssbo_index, cbuf_index);"
assert r437_expected.count(ssbo_cbuf_before_0) == 1
r437_expected = r437_expected.replace(ssbo_cbuf_before_0, ssbo_cbuf_after_0)
ssbo_cbuf_before_1 = "    if (ssbo_index >= channel_state->compute_storage_buffers.size()) [[unlikely]] {\n        LOG_ERROR(HW_GPU, \"Storage buffer index {} exceeds maximum storage buffer count\",\n                  ssbo_index);"
ssbo_cbuf_after_1 = "    if (ssbo_index >= channel_state->compute_storage_buffers.size() ||\n        cbuf_index >= kepler_compute->launch_description.const_buffer_config.size()) [[unlikely]] {\n        LOG_ERROR(HW_GPU, \"Compute SSBO slot={} cbuf={} exceeds supported slots\",\n                  ssbo_index, cbuf_index);"
assert r437_expected.count(ssbo_cbuf_before_1) == 1
r437_expected = r437_expected.replace(ssbo_cbuf_before_1, ssbo_cbuf_after_1)
# Clear previous-launch compute SSBO when its constant buffer is disabled.
compute_cbuf_disabled_before = "    if (((launch_desc.const_buffer_enable_mask >> cbuf_index) & 1) == 0) {\n        LOG_WARNING(HW_GPU, \"Skipped binding SSBO: cbuf index {} is not enabled\", cbuf_index);\n        return;\n    }"
compute_cbuf_disabled_after = "    if (((launch_desc.const_buffer_enable_mask >> cbuf_index) & 1) == 0) {\n        // Preserve the logical descriptor position, but never reuse a buffer\n        // left from an earlier dispatch when this launch disables its CBUF.\n        channel_state->compute_storage_buffers[ssbo_index] = NULL_BINDING;\n        channel_state->written_compute_storage_buffers &= ~(1U << ssbo_index);\n        LOG_WARNING(HW_GPU, \"Skipped binding SSBO: cbuf index {} is not enabled\", cbuf_index);\n        return;\n    }"
assert r437_expected.count(compute_cbuf_disabled_before) == 1
r437_expected = r437_expected.replace(compute_cbuf_disabled_before, compute_cbuf_disabled_after)
# F01: pinned buffer-cache transform also retains mask-write elision.
mask_write_before = "    if (channel_state->enabled_uniform_buffer_masks != mask) {\n        channel_state->fast_bound_uniform_buffers.fill(0);\n        if constexpr (HAS_PERSISTENT_UNIFORM_BUFFER_BINDINGS) {\n            channel_state->dirty_uniform_buffers.fill(~u32{0});\n            channel_state->uniform_buffer_binding_sizes.fill({});\n        }\n    }\n    channel_state->enabled_uniform_buffer_masks = mask;\n    channel_state->uniform_buffer_sizes = sizes;"
mask_write_after = "    if (channel_state->enabled_uniform_buffer_masks != mask) {\n        channel_state->fast_bound_uniform_buffers.fill(0);\n        if constexpr (HAS_PERSISTENT_UNIFORM_BUFFER_BINDINGS) {\n            channel_state->dirty_uniform_buffers.fill(~u32{0});\n            channel_state->uniform_buffer_binding_sizes.fill({});\n        }\n        // A repeat pipeline already has the mask: avoid rewriting all stage\n        // entries on every draw while the buffer/texture cache locks are held.\n        channel_state->enabled_uniform_buffer_masks = mask;\n    }\n    // Equal enabled masks do not imply equal uniform sizes across pipelines.\n    channel_state->uniform_buffer_sizes = sizes;"
assert r437_expected.count(mask_write_before) == 1
r437_expected = r437_expected.replace(mask_write_before, mask_write_after)
# Reproduce the five later F07 native-only buffer-cache deltas independently
# from the pinned backport. Keep these strict anchors in sync with the R437
# source-extracted witness; the complete maintained header is compared below.
# Native buffer-cache memory budget sampling: mirror texture-cache policy
# under low pressure, but never delay an above-watermark GC probe.
budget_old = "    // If we can obtain the memory info, use it instead of the estimate.\n    if (runtime.CanReportMemoryUsage()) {\n        total_used_memory = runtime.GetDeviceMemoryUsage();\n    }\n    if (total_used_memory >= minimum_memory) {\n        RunGarbageCollector();\n    }"
budget_new = "    // If we can obtain the memory info, use it instead of the estimate.\n    if (runtime.CanReportMemoryUsage()) {\n#ifdef PS5_NATIVE\n        // Memory-budget queries use the driver while the buffer cache mutex\n        // is held. Under low pressure, probe on alternating frames; near\n        // the GC watermark, preserve every-frame sampling and prompt reclaim.\n        const bool near_gc_watermark =\n            total_used_memory >= minimum_memory - minimum_memory / 3;\n        if (near_gc_watermark || (frame_tick & 1u) == 0) {\n            total_used_memory = runtime.GetDeviceMemoryUsage();\n        }\n#else\n        total_used_memory = runtime.GetDeviceMemoryUsage();\n#endif\n    }\n    if (total_used_memory >= minimum_memory) {\n        RunGarbageCollector();\n    }"
assert r437_expected.count(budget_old) == 1
r437_expected = r437_expected.replace(budget_old, budget_new)
# Preserve overlapping rolling uniform-hit windows without forward-copy UB.
history_old = "    std::copy_n(channel_state->uniform_cache_hits.begin(),\n                channel_state->uniform_cache_hits.size() - 1,\n                channel_state->uniform_cache_hits.begin() + 1);\n    std::copy_n(channel_state->uniform_cache_shots.begin(),\n                channel_state->uniform_cache_shots.size() - 1,\n                channel_state->uniform_cache_shots.begin() + 1);"
history_new = "    // History shifts overlap their source ranges. Copy from the back so\n    // each previous interval is retained exactly once, even under -O2.\n    std::copy_backward(channel_state->uniform_cache_hits.begin(),\n                       channel_state->uniform_cache_hits.end() - 1,\n                       channel_state->uniform_cache_hits.end());\n    std::copy_backward(channel_state->uniform_cache_shots.begin(),\n                       channel_state->uniform_cache_shots.end() - 1,\n                       channel_state->uniform_cache_shots.end());"
assert r437_expected.count(history_old) == 1
r437_expected = r437_expected.replace(history_old, history_new)
# Do not underflow unsigned frame age during early-pressure buffer GC.
gc_age_old = "    const u64 ticks_to_destroy = aggressive_gc ? 60 : 120;\n    int num_iterations = aggressive_gc ? 64 : 32;"
gc_age_new = "    const u64 ticks_to_destroy = aggressive_gc ? 60 : 120;\n#ifdef PS5_NATIVE\n    // Before a buffer reaches the GC age, subtracting from this unsigned\n    // frame tick wraps to a huge LRU threshold. On startup/pressure bursts\n    // that wrongly evicts young buffers and can force guest downloads.\n    if (frame_tick < ticks_to_destroy) {\n        return;\n    }\n#endif\n    int num_iterations = aggressive_gc ? 64 : 32;"
assert r437_expected.count(gc_age_old) == 1
r437_expected = r437_expected.replace(gc_age_old, gc_age_new)
# A fresh driver memory snapshot can be smaller than the previous buffer's
# rounded size. Unregistering it must never underflow the shared usage counter.
unregister_budget_before = "    } else {\n        total_used_memory -= Common::AlignUp(size, 1024);\n        lru_cache.Free(buffer.getLRUID());\n    }"
unregister_budget_after = "    } else {\n#ifdef PS5_NATIVE\n        // The driver budget snapshot is not an allocation ledger. A stale or\n        // smaller snapshot must not wrap unsigned usage to UINT64_MAX when\n        // removing a previously registered buffer (and trigger GC storms).\n        const u64 accounted_bytes = Common::AlignUp(size, 1024);\n        total_used_memory = total_used_memory >= accounted_bytes\n                                ? total_used_memory - accounted_bytes : 0;\n#else\n        total_used_memory -= Common::AlignUp(size, 1024);\n#endif\n        lru_cache.Free(buffer.getLRUID());\n    }"
assert r437_expected.count(unregister_budget_before) == 1
r437_expected = r437_expected.replace(unregister_budget_before, unregister_budget_after)
# Channel-less homebrew/title teardown must still advance deferred GPU
# staging and destruction on PS5; desktop's original early exit is unchanged.
no_channel_old = "    // Homebrew console apps don't create or bind any channels, so this will be nullptr.\n    if (!channel_state) {\n        return;\n    }\n    runtime.TickFrame(slot_buffers);"
no_channel_new = "    // Homebrew console apps don't create or bind any channels, so this will be nullptr.\n    if (!channel_state) {\n#ifdef PS5_NATIVE\n        // The final channel can disappear while native Vulkan buffers and\n        // deferred staging remain alive. Advance the GPU lifetime scan and\n        // retirement rings even without uniform-cache statistics.\n        runtime.TickFrame(slot_buffers);\n        ++frame_tick;\n        delayed_destruction_ring.Tick();\n        for (auto& buffer : async_buffers_death_ring) {\n            runtime.FreeDeferredStagingBuffer(buffer);\n        }\n        async_buffers_death_ring.clear();\n#endif\n        return;\n    }\n    runtime.TickFrame(slot_buffers);"
assert r437_expected.count(no_channel_old) == 1
r437_expected = r437_expected.replace(no_channel_old, no_channel_new)

assert (active / r437_rel).read_text() == r437_expected, (
    "R437 maintained buffer cache differs from source reconstruction; "
    "check BufferPages registration, DMA copy bounds and DMA clear bounds"
)
assert 'configure_file("${EDEN_MAINTAINED_BUFFER_PAGES}"' in c
assert 'write_derived("${PORT_BUILD_DIR}/buffer-pages/video_core/buffer_cache/buffer_cache.h"' not in c
print("VENDOR_MAINTAINED_BUFFER_PAGES_PARITY_PASS: shipping backport and native-only selection")
print("VENDOR_SCRIPTED_TRANSFORM_ENTRYPOINTS_PASS staged=5 oracles=2 profile_generators=2")

begin = "<!-- OVERRIDE_GENERATORS_START -->"
end = "<!-- OVERRIDE_GENERATORS_END -->"
assert inventory.count(begin) == inventory.count(end) == 1
recorded = re.findall(r"^\| G\d\d \| \x60([^\x60]+)\x60 \|",
                      inventory.split(begin)[1].split(end)[0], re.M)
current = re.findall(r'write_derived\(\s*"([^"]+)"', c)
assert recorded == current, "CMake-generated override inventory changed: re-inventory targets"
assert len(current) == counts["write_derived("], "dynamic or unquoted generator not cataloged"
print(f"VENDOR_GENERATOR_INVENTORY_PASS entries={len(recorded)}")

# Indirect CMake includes can generate more source units than the primary
# CMake file. Keep the second table exhaustive and order-stable as well.
module_begin = "<!-- MODULE_GENERATORS_START -->"
module_end = "<!-- MODULE_GENERATORS_END -->"
assert inventory.count(module_begin) == inventory.count(module_end) == 1
module_recorded = re.findall(
    r"^\| M\d\d \| \x60([^\x60]+)\x60 \| \x60([^\x60]+)\x60 \|",
    inventory.split(module_begin)[1].split(module_end)[0], re.M)
module_files = (
    "headless/dynarmic/reg_alloc.cmake",
    "headless/dynarmic/shared-jit.cmake",
    "headless/gpu_native_observability.cmake",
    "headless/guest_write_deferred_bridge.cmake",
    "headless/jit-alias.cmake",
    "headless/scalar-memory.cmake",
)
module_current = []
for module in module_files:
    content = (root / module).read_text()
    module_current.extend((module, target) for target in
                          re.findall(r'write_derived\(\s*"([^"]+)"', content))
assert module_recorded == module_current, "Module CMake source generator inventory is stale"
assert len(module_current) == module_generators, (len(module_current), module_generators)
# Indirect X01/X02 are no longer CMake generators: full source units
# live under encore-active, and the parity witnesses above verify them.
for old_module in ("headless/macro_recovery.cmake", "headless/slot_vector_recovery.cmake"):
    assert not (root / old_module).exists(), ("removed CMake mutator returned", old_module)
# Verify the two independently extracted inventories against the generated
# scope counters, rather than pinning a migration-stage total.
assert len(recorded) == main_generators, (len(recorded), main_generators)
assert len(module_recorded) == module_generators, (len(module_recorded), module_generators)
print(f"VENDOR_MODULE_GENERATOR_INVENTORY_PASS entries={len(module_recorded)}")

# Separate ledger: these modules modify source without calling write_derived
# locally. Two materialize an output directly; two mutate source variables
# that a root CMake generator subsequently writes. Never count them as extra
# write_derived call sites, but never silently drop them from the inventory.
indirect_begin, indirect_end = "<!-- INDIRECT_OVERRIDES_START -->", "<!-- INDIRECT_OVERRIDES_END -->"
assert inventory.count(indirect_begin) == inventory.count(indirect_end) == 1
indirect_recorded = re.findall(
    r"^\| X\d\d \| \x60([^\x60]+)\x60 \|",
    inventory.split(indirect_begin)[1].split(indirect_end)[0], re.M)
indirect_expected = ()
assert not (root/"headless/native_jit_memory_read_guard.cmake").exists()
x06_oracle = (root/"tools/fixtures/legacy-x06-native-jit-memory-read-guard.cmake").read_text()
assert "string(REPLACE" in x06_oracle and "wrapper" in x06_oracle
assert indirect_recorded == [entry[0] for entry in indirect_expected], (
    "Unlisted or reordered indirect CMake override; recheck files and symbols")
for module, required in indirect_expected:
    content = (root / module).read_text()
    assert all(token in content for token in required), ("indirect override changed", module)
assert len(indirect_recorded) == len(indirect_expected), (len(indirect_recorded), len(indirect_expected))
print(f"VENDOR_INDIRECT_OVERRIDE_INVENTORY_PASS modules={len(indirect_recorded)} (not generator sites)")

# Third independent source-change mechanism: pinned backport patch replays.
# Count checked calls, not the number of files they touch or optional runs.
replay_begin = "<!-- SOURCE_PATCH_REPLAYS_START -->"
replay_end = "<!-- SOURCE_PATCH_REPLAYS_END -->"
assert inventory.count(replay_begin) == inventory.count(replay_end) == 1
registered_patches = re.findall(
    r"^\| P\d\d \| \x60([^\x60]+\.patch)\x60 \|",
    inventory.split(replay_begin)[1].split(replay_end)[0], re.M)
legacy_replay_source = (root / "tools/apply-eden-backports.sh").read_text()
legacy_calls = re.findall(
    r'^[ \t]*apply_one "\$root/headless/backports/([^"]+\.patch)"',
    legacy_replay_source, re.M)
active_core_installer = (root / "tools/install-active-core-backports.py").read_text()
patch_names = {p.name for p in (root / "headless/backports").glob("*.patch")}
assert len(legacy_calls) == len(set(legacy_calls)) == 51
active_core_patches = sorted(patch_names.difference(legacy_calls))
assert active_core_patches == [
    "eden-dynarmic-icache-coherence.patch",
    "eden-sm-host-wait.patch",
]
assert all(f'headless/backports/{name}' in active_core_installer
           for name in active_core_patches)
assert "if len(names) != 5:" in active_core_installer
assert "git apply --check" not in legacy_replay_source or "git apply" in legacy_replay_source
assert 'git apply "$patch"' in legacy_replay_source
assert "EDEN_EXPERIMENTAL_DUMMY_THREAD_WAITS:-OFF" in legacy_replay_source
assert len(patch_names) == len(registered_patches) == 53
assert registered_patches == legacy_calls + active_core_patches
assert set(registered_patches) == patch_names
print("VENDOR_SOURCE_PATCH_REPLAY_INVENTORY_PASS: 51 replay calls, 2 active-core patches, 53 files")

# Independent source-target audit: 53 registered patches may touch more
# physical translation units than the high-priority function graph names.
# This reports EXACT path gaps; it does not assert all unlisted functions
# have never been checked, nor that the pinned file is selected at runtime.
audit_register = (root / "docs/EDEN_CORE_AUDIT_DEPENDENCIES.md").read_text()
audit_paths = set()
for audit_line in audit_register.splitlines():
    if audit_line.startswith("| ") and len(audit_line.split("|")) > 4 and re.fullmatch(r"[A-Z][0-9]{2,3}", audit_line.split("|")[1].strip()):
        fields = audit_line.split("|")
        if len(fields) >= 5:
            audit_paths.add(fields[4].strip())
patch_target_map = {}
for patch_name in sorted(patch_names):
    patch_body = (root / "headless/backports" / patch_name).read_text()
    target_paths = {line[6:] for line in patch_body.splitlines() if line.startswith("+++ b/")}
    assert target_paths, ("patch has no target paths", patch_name)
    patch_target_map[patch_name] = target_paths
all_patch_targets = set().union(*patch_target_map.values())
def has_exact_audit_path(relative):
    return any(prefix + relative in audit_paths for prefix in (
        "vendor/sources/eden/", "vendor/encore-active/eden-core/",
        "vendor/encore-active/eden-backports/",
        "vendor/encore-active/eden-vulkan/", "vendor/encore-active/eden-gpu/",
        "vendor/encore-active/eden-threading/",
        "vendor/encore-active/eden-sync/",
        "vendor/encore-active/eden-shader/",
    ))
shipping_manifest = json.loads((active / "eden-backports/manifest.json").read_text())
shipping_build_recipes = {"src/common/CMakeLists.txt", "src/core/CMakeLists.txt"}
assert shipping_build_recipes <= set(shipping_manifest["entries"])
unmatched_patch_targets = sorted(path for path in all_patch_targets
                                 if path not in shipping_build_recipes
                                 and not has_exact_audit_path(path))
assert not unmatched_patch_targets, ("unowned source patch targets", unmatched_patch_targets)
assert len(patch_target_map) == 53
print("VENDOR_PATCH_TARGET_FOOTPRINT_PASS "
      f"patches={len(patch_target_map)} "
      f"touched_paths={len(all_patch_targets)} "
      f"unmatched_exact_graph={len(unmatched_patch_targets)}")
for missing_path in unmatched_patch_targets:
    print("VENDOR_PATCH_TARGET_NEEDS_OWNER", missing_path)









print(f"VENDOR_SOURCE_PINNED roots={len(root_names)} manifest_items={len(deps)} "
      f"active_forks={len(fork_names)}")
print("VENDOR_REWRITE_DEBT_PARTIAL " +
      " ".join(f"{name}={value}" for name, value in counts.items()) +
      " (ceilings, not a declaration of completion)")
print("VENDOR_NATIVE_VULKAN_SOURCE tracked active copy; generator only comparison oracle")
