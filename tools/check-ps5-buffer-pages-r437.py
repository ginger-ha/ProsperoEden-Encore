#!/usr/bin/env python3
"""R437: buffer registration must not skip HUD texture or shader invalidation."""
from pathlib import Path
import shutil, subprocess, tempfile
root=Path(__file__).resolve().parents[1]
cm=(root/'headless/CMakeLists.txt').read_text()
r=(root/'vendor/encore-active/eden-vulkan/vulkan_rasterizer.cpp').read_text()
g=(root/'tools/prepare-vulkan-port.py').read_text()
source=(root/'vendor/encore-active/eden-backports/src/video_core/buffer_cache/buffer_cache.h').read_text()
maintained=(root/'vendor/encore-active/eden-core/src/video_core/buffer_cache/buffer_cache.h').read_text()
assert 'write_derived("${PORT_BUILD_DIR}/buffer-pages/video_core/buffer_cache/buffer_cache.h"' not in cm
assert 'configure_file("${EDEN_MAINTAINED_BUFFER_PAGES}"' in cm
assert 'target_include_directories(video_core BEFORE PRIVATE "${PORT_BUILD_DIR}/buffer-pages" "${EDEN_PORT_DIR}")' in cm
old_reg = '    const auto size = buffer.SizeBytes();\n    if (insert) {\n        total_used_memory += Common::AlignUp(size, 1024);'
new_reg = '    const auto size = buffer.SizeBytes();\n    if (insert) {\n        ::Eden::BufferPages::Mark(buffer.CpuAddr(), size);\n        total_used_memory += Common::AlignUp(size, 1024);'
assert source.count(old_reg)==1
expected = '#include "buffer_pages.h"\n' + source.replace(old_reg, new_reg)
# DMA copy's byte count also reaches FindBuffer(u32); never truncate a
# >4 GiB span, and do not touch dirty-range bookkeeping on empty copies.
copy_old = "bool BufferCache<P>::DMACopy(GPUVAddr src_address, GPUVAddr dest_address, u64 amount) {\n    const std::optional<DAddr> cpu_src_address = gpu_memory->GpuToCpuAddress(src_address);"
copy_new = "bool BufferCache<P>::DMACopy(GPUVAddr src_address, GPUVAddr dest_address, u64 amount) {\n    // FindBuffer and SynchronizeBuffer accept u32 byte spans. Never truncate\n    // a wider DMA request: the caller can take its ordinary software path.\n    // Reject empty copies before dirty-range bookkeeping as well.\n    if (amount == 0 || amount > static_cast<u64>(~u32{0})) {\n        return false;\n    }\n    const std::optional<DAddr> cpu_src_address = gpu_memory->GpuToCpuAddress(src_address);"
assert expected.count(copy_old) == 1
expected = expected.replace(copy_old, copy_new)
# DMA clear's amount is a word count, unlike byte-based cache registration.
begin = expected.index('bool BufferCache<P>::DMAClear(')
end = expected.index('\ntemplate <class P>', begin)
clear = expected[begin:end]
old_clear = '    const bool dest_dirty = IsRegionRegistered(*cpu_dst_address, amount);'
assert clear.count(old_clear) == 1
clear = clear.replace('    const size_t size = amount * sizeof(u32);\n', '').replace(
    old_clear, '    // FindBuffer accepts a u32 byte span; never truncate or issue an empty fill.\n'
    '    if (amount == 0 || amount > static_cast<u64>(~u32{0}) / sizeof(u32)) {\n'
    '        return false;\n'
    '    }\n'
    '    // The DMA amount counts u32 values; registration is measured in bytes.\n'
    '    const size_t size = amount * sizeof(u32);\n'
    '    const bool dest_dirty = IsRegionRegistered(*cpu_dst_address, size);')
expected = expected[:begin] + clear + expected[end:]
# Native-only ownership scan fix. The shipping backport remains immutable,
# and its bytes are still verified against the pinned manifest.
region_before = "bool BufferCache<P>::IsRegionRegistered(DAddr addr, size_t size) {\n    const DAddr end_addr = addr + size;"
region_after = "bool BufferCache<P>::IsRegionRegistered(DAddr addr, size_t size) {\n    // An empty CPU write does not overlap any registered cache buffer.\n    if (size == 0) {\n        return false;\n    }\n    // The page_table has exactly 16 GiB of guest-physical address space.\n    // Reject unrepresentable/overflowing spans before addr + size or page_table[].\n    constexpr DAddr kTableAddressLimit = DAddr{1} << 34;\n    if (addr >= kTableAddressLimit || size > kTableAddressLimit - addr) {\n        return false;\n    }\n    const DAddr end_addr = addr + size;"
region_skip_before = "        if (buf_start_addr < end_addr && addr < buf_end_addr) {\n            return true;\n        }\n        page = Common::DivCeil(end_addr, CACHING_PAGESIZE);"
region_skip_after = "        if (buf_start_addr < end_addr && addr < buf_end_addr) {\n            return true;\n        }\n        // The first page can contain a buffer ending before addr. A later\n        // page may belong to another registered buffer intersecting the span.\n        // Do not skip all remaining pages after one non-overlapping owner.\n        ++page;"
assert expected.count(region_before) == expected.count(region_skip_before) == 1
expected = expected.replace(region_before, region_after).replace(
    region_skip_before, region_skip_after)
# Native-only zero-tick GPU fence fast path: the scheduler cannot wait
# for tick zero, and the shipping backport remains byte-for-byte pinned.
zero_tick_before = "        const u64 buffer_tick = buffer.getWriteTick();\n        if (!runtime.IsFree(buffer_tick)) {\n            runtime.Wait(buffer_tick);\n        }"
zero_tick_after = "        const u64 buffer_tick = buffer.getWriteTick();\n        // New and never-GPU-written buffers have a zero fence tick.\n        // Scheduler::Wait(0) cannot wait; skip its IsFree semaphore probe.\n        if (buffer_tick != 0 && !runtime.IsFree(buffer_tick)) {\n            runtime.Wait(buffer_tick);\n        }"
assert expected.count(zero_tick_before) == 1
expected = expected.replace(zero_tick_before, zero_tick_after)
# Native-only unmapped uniform CBUF guard. A missing GPU-to-CPU
# translation must clear the previous slot binding without optional UB.
unmapped_uniform_before = "    const std::optional<DAddr> device_addr = gpu_memory->GpuToCpuAddress(gpu_addr);\n    const Binding binding{\n        .device_addr = *device_addr,\n        .size = size,\n        .buffer_id = BufferId{},\n    };"
unmapped_uniform_after = "    const std::optional<DAddr> device_addr = gpu_memory->GpuToCpuAddress(gpu_addr);\n    if (!device_addr) {\n        // An unmapped cbuf is not a valid CPU-backed GPU buffer. Retire any\n        // previous slot binding instead of dereferencing an empty optional.\n        channel_state->uniform_buffers[stage][index] = NULL_BINDING;\n        return;\n    }\n    const Binding binding{\n        .device_addr = *device_addr,\n        .size = size,\n        .buffer_id = BufferId{},\n    };"
assert expected.count(unmapped_uniform_before) == 1
expected = expected.replace(unmapped_uniform_before, unmapped_uniform_after)
# Lichii nx2's page-table guard also needs the entire guest-physical span
# checked before CreateBuffer: only the native maintained owner is changed.
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
assert expected.count(find_page_before) == 1
expected = expected.replace(find_page_before, find_page_after)
# Native-only vertex buffer extent hardening: never truncate a 64-bit
# guest GPU range to u32 before checking the exclusive-end bounds.
vertex_extent_old = "    const u32 address_size = static_cast<u32>(gpu_addr_end - gpu_addr_begin);\n    u32 size = address_size; // TODO: Analyze stride and number of vertices"
vertex_extent_new = "    // GPU addresses are 64-bit. Truncating the range before validation\n    // could turn a valid >=4 GiB vertex span into zero or a tiny buffer.\n    const u64 address_size =\n        gpu_addr_end > gpu_addr_begin ? gpu_addr_end - gpu_addr_begin : 0;\n    u32 size = static_cast<u32>((std::min)(address_size, static_cast<u64>(~u32{0})));"
vertex_clip_old = "    if (!gpu_memory->IsWithinGPUAddressRange(gpu_addr_end) || size >= 64_MiB) {\n        size = static_cast<u32>(gpu_memory->MaxContinuousRange(gpu_addr_begin, size));\n    }\n    const BufferId buffer_id = FindBuffer(*device_addr, size, false);"
vertex_clip_new = "    if (!gpu_memory->IsWithinGPUAddressRange(gpu_addr_end) || size >= 64_MiB) {\n        size = static_cast<u32>(gpu_memory->MaxContinuousRange(gpu_addr_begin, size));\n        if (size == 0) {\n            // No mapped contiguous data: never create a zero-byte vertex\n            // buffer or retain the previous draw's vertex binding.\n            channel_state->vertex_buffers[index] = NULL_BINDING;\n            UpdateVertexBufferSlot(index, NULL_BINDING);\n            return;\n        }\n    }\n    const BufferId buffer_id = FindBuffer(*device_addr, size, false);"
assert expected.count(vertex_extent_old) == expected.count(vertex_clip_old) == 1
expected = expected.replace(vertex_extent_old, vertex_extent_new).replace(vertex_clip_old, vertex_clip_new)
# Native-only index buffer extent hardening: detect 64-bit GPU limits and
# 32-bit index arithmetic overflow before converting to FindBuffer(u32).
index_before = "    const u32 address_size = static_cast<u32>(gpu_addr_end - gpu_addr_begin);\n    const u32 draw_size = (index_buffer_ref.count + index_buffer_ref.first) * u32(index_buffer_ref.FormatSizeInBytes());\n    const u32 size = (std::min)(address_size, draw_size);"
index_after = "    // Both the GPU range and (first + count) * format size can exceed\n    // 32 bits. Compare their full widths before bounding FindBuffer(u32).\n    const u64 address_size =\n        gpu_addr_end > gpu_addr_begin ? gpu_addr_end - gpu_addr_begin : 0;\n    const u64 index_count =\n        static_cast<u64>(index_buffer_ref.count) + index_buffer_ref.first;\n    const u64 draw_size = index_count * index_buffer_ref.FormatSizeInBytes();\n    const u32 size = static_cast<u32>((std::min)(\n        (std::min)(address_size, draw_size), static_cast<u64>(~u32{0})));"
assert expected.count(index_before) == 1
expected = expected.replace(index_before, index_after)
# Native-only indirect draw extent validation; preserve source replay.
indirect_before = "    const auto update = [this](GPUVAddr gpu_addr, size_t size, Binding& binding) {\n        const std::optional<DAddr> device_addr = gpu_memory->GpuToCpuAddress(gpu_addr);"
indirect_after = "    const auto update = [this](GPUVAddr gpu_addr, size_t size, Binding& binding) {\n        // The binding and FindBuffer accept u32 bytes. An empty or wider\n        // indirect command range must not wrap into a valid-looking buffer.\n        if (size == 0 || size > static_cast<size_t>(~u32{0})) {\n            binding = NULL_BINDING;\n            return;\n        }\n        const std::optional<DAddr> device_addr = gpu_memory->GpuToCpuAddress(gpu_addr);"
assert expected.count(indirect_before) == 1
expected = expected.replace(indirect_before, indirect_after)
# Reject null guest indirect bindings end-to-end: no null-buffer touch or Vulkan submit.
indirect_null_before_0 = "    const auto bind_buffer = [this](const Binding& binding) {\n        Buffer& buffer = slot_buffers[binding.buffer_id];"
indirect_null_after_0 = "    const auto bind_buffer = [this](const Binding& binding) {\n        // An unmapped or rejected guest indirect draw has no real VkBuffer.\n        // Never touch or synchronize the null sentinel as if it were live.\n        if (binding.buffer_id == NULL_BUFFER_ID || binding.size == 0) {\n            return;\n        }\n        Buffer& buffer = slot_buffers[binding.buffer_id];"
assert expected.count(indirect_null_before_0) == 1
expected = expected.replace(indirect_null_before_0, indirect_null_after_0)
indirect_null_before_1 = "std::pair<typename BufferCache<P>::Buffer*, u32> BufferCache<P>::GetDrawIndirectCount() {\n    auto& buffer = slot_buffers[channel_state->count_buffer_binding.buffer_id];\n    return std::make_pair(&buffer, buffer.Offset(channel_state->count_buffer_binding.device_addr));\n}"
indirect_null_after_1 = "std::pair<typename BufferCache<P>::Buffer*, u32> BufferCache<P>::GetDrawIndirectCount() {\n    const Binding& binding = channel_state->count_buffer_binding;\n    if (binding.buffer_id == NULL_BUFFER_ID || binding.size == 0) {\n        return {nullptr, 0};\n    }\n    auto& buffer = slot_buffers[binding.buffer_id];\n    return std::make_pair(&buffer, buffer.Offset(binding.device_addr));\n}"
assert expected.count(indirect_null_before_1) == 1
expected = expected.replace(indirect_null_before_1, indirect_null_after_1)
indirect_null_before_2 = "std::pair<typename BufferCache<P>::Buffer*, u32> BufferCache<P>::GetDrawIndirectBuffer() {\n    auto& buffer = slot_buffers[channel_state->indirect_buffer_binding.buffer_id];\n    return std::make_pair(&buffer,\n                          buffer.Offset(channel_state->indirect_buffer_binding.device_addr));\n}"
indirect_null_after_2 = "std::pair<typename BufferCache<P>::Buffer*, u32> BufferCache<P>::GetDrawIndirectBuffer() {\n    const Binding& binding = channel_state->indirect_buffer_binding;\n    if (binding.buffer_id == NULL_BUFFER_ID || binding.size == 0) {\n        return {nullptr, 0};\n    }\n    auto& buffer = slot_buffers[binding.buffer_id];\n    return std::make_pair(&buffer, buffer.Offset(binding.device_addr));\n}"
assert expected.count(indirect_null_before_2) == 1
expected = expected.replace(indirect_null_before_2, indirect_null_after_2)
# Reject oversized native graphics SSBO/TBO slots before masks or table access.
graphics_slot_before_0 = "bool BufferCache<P>::BindGraphicsStorageBuffer(size_t stage, size_t ssbo_index, u32 cbuf_index,\n                                               u32 cbuf_offset, bool is_written) {\n    const bool already_enabled ="
graphics_slot_after_0 = "bool BufferCache<P>::BindGraphicsStorageBuffer(size_t stage, size_t ssbo_index, u32 cbuf_index,\n                                               u32 cbuf_offset, bool is_written) {\n    // Reject excess shader slots before shifting a u32 mask or indexing the\n    // per-stage storage array. Compute bindings already enforce this limit.\n    if (stage >= NUM_STAGES || ssbo_index >= NUM_STORAGE_BUFFERS) [[unlikely]] {\n        LOG_ERROR(HW_GPU, \"Graphics storage buffer stage={} index={} exceeds supported slots\",\n                  stage, ssbo_index);\n        return false;\n    }\n    const bool already_enabled ="
assert expected.count(graphics_slot_before_0) == 1
expected = expected.replace(graphics_slot_before_0, graphics_slot_after_0)
graphics_slot_before_1 = "void BufferCache<P>::BindGraphicsTextureBuffer(size_t stage, size_t tbo_index, GPUVAddr gpu_addr,\n                                               u32 size, PixelFormat format, bool is_written,\n                                               bool is_image) {\n    channel_state->enabled_texture_buffers[stage] |="
graphics_slot_after_1 = "void BufferCache<P>::BindGraphicsTextureBuffer(size_t stage, size_t tbo_index, GPUVAddr gpu_addr,\n                                               u32 size, PixelFormat format, bool is_written,\n                                               bool is_image) {\n    // A malformed descriptor array must not shift by >=32 or overwrite an\n    // adjacent stage's texture binding. Compute already guards its slots.\n    if (stage >= NUM_STAGES || tbo_index >= NUM_TEXTURE_BUFFERS) [[unlikely]] {\n        LOG_ERROR(HW_GPU, \"Graphics texture buffer stage={} index={} exceeds supported slots\",\n                  stage, tbo_index);\n        return;\n    }\n    channel_state->enabled_texture_buffers[stage] |="
assert expected.count(graphics_slot_before_1) == 1
expected = expected.replace(graphics_slot_before_1, graphics_slot_after_1)
# Maintain bounded graphics and compute SSBO CBUF indices in the selected source.
ssbo_cbuf_before_0 = "    if (stage >= NUM_STAGES || ssbo_index >= NUM_STORAGE_BUFFERS) [[unlikely]] {\n        LOG_ERROR(HW_GPU, \"Graphics storage buffer stage={} index={} exceeds supported slots\",\n                  stage, ssbo_index);"
ssbo_cbuf_after_0 = "    if (stage >= NUM_STAGES || ssbo_index >= NUM_STORAGE_BUFFERS ||\n        cbuf_index >= maxwell3d->state.shader_stages[stage].const_buffers.size()) [[unlikely]] {\n        LOG_ERROR(HW_GPU, \"Graphics SSBO stage={} slot={} cbuf={} exceeds supported slots\",\n                  stage, ssbo_index, cbuf_index);"
assert expected.count(ssbo_cbuf_before_0) == 1
expected = expected.replace(ssbo_cbuf_before_0, ssbo_cbuf_after_0)
ssbo_cbuf_before_1 = "    if (ssbo_index >= channel_state->compute_storage_buffers.size()) [[unlikely]] {\n        LOG_ERROR(HW_GPU, \"Storage buffer index {} exceeds maximum storage buffer count\",\n                  ssbo_index);"
ssbo_cbuf_after_1 = "    if (ssbo_index >= channel_state->compute_storage_buffers.size() ||\n        cbuf_index >= kepler_compute->launch_description.const_buffer_config.size()) [[unlikely]] {\n        LOG_ERROR(HW_GPU, \"Compute SSBO slot={} cbuf={} exceeds supported slots\",\n                  ssbo_index, cbuf_index);"
assert expected.count(ssbo_cbuf_before_1) == 1
expected = expected.replace(ssbo_cbuf_before_1, ssbo_cbuf_after_1)
# Clear previous-launch compute SSBO when its constant buffer is disabled.
compute_cbuf_disabled_before = "    if (((launch_desc.const_buffer_enable_mask >> cbuf_index) & 1) == 0) {\n        LOG_WARNING(HW_GPU, \"Skipped binding SSBO: cbuf index {} is not enabled\", cbuf_index);\n        return;\n    }"
compute_cbuf_disabled_after = "    if (((launch_desc.const_buffer_enable_mask >> cbuf_index) & 1) == 0) {\n        // Preserve the logical descriptor position, but never reuse a buffer\n        // left from an earlier dispatch when this launch disables its CBUF.\n        channel_state->compute_storage_buffers[ssbo_index] = NULL_BINDING;\n        channel_state->written_compute_storage_buffers &= ~(1U << ssbo_index);\n        LOG_WARNING(HW_GPU, \"Skipped binding SSBO: cbuf index {} is not enabled\", cbuf_index);\n        return;\n    }"
assert expected.count(compute_cbuf_disabled_before) == 1
expected = expected.replace(compute_cbuf_disabled_before, compute_cbuf_disabled_after)
# F01: pinned buffer-cache transform also retains mask-write elision.
mask_write_before = "    if (channel_state->enabled_uniform_buffer_masks != mask) {\n        channel_state->fast_bound_uniform_buffers.fill(0);\n        if constexpr (HAS_PERSISTENT_UNIFORM_BUFFER_BINDINGS) {\n            channel_state->dirty_uniform_buffers.fill(~u32{0});\n            channel_state->uniform_buffer_binding_sizes.fill({});\n        }\n    }\n    channel_state->enabled_uniform_buffer_masks = mask;\n    channel_state->uniform_buffer_sizes = sizes;"
mask_write_after = "    if (channel_state->enabled_uniform_buffer_masks != mask) {\n        channel_state->fast_bound_uniform_buffers.fill(0);\n        if constexpr (HAS_PERSISTENT_UNIFORM_BUFFER_BINDINGS) {\n            channel_state->dirty_uniform_buffers.fill(~u32{0});\n            channel_state->uniform_buffer_binding_sizes.fill({});\n        }\n        // A repeat pipeline already has the mask: avoid rewriting all stage\n        // entries on every draw while the buffer/texture cache locks are held.\n        channel_state->enabled_uniform_buffer_masks = mask;\n    }\n    // Equal enabled masks do not imply equal uniform sizes across pipelines.\n    channel_state->uniform_buffer_sizes = sizes;"
assert expected.count(mask_write_before) == 1
expected = expected.replace(mask_write_before, mask_write_after)
# Native buffer-cache memory budget sampling: mirror texture-cache policy
# under low pressure, but never delay an above-watermark GC probe.
budget_old = "    // If we can obtain the memory info, use it instead of the estimate.\n    if (runtime.CanReportMemoryUsage()) {\n        total_used_memory = runtime.GetDeviceMemoryUsage();\n    }\n    if (total_used_memory >= minimum_memory) {\n        RunGarbageCollector();\n    }"
budget_new = "    // If we can obtain the memory info, use it instead of the estimate.\n    if (runtime.CanReportMemoryUsage()) {\n#ifdef PS5_NATIVE\n        // Memory-budget queries use the driver while the buffer cache mutex\n        // is held. Under low pressure, probe on alternating frames; near\n        // the GC watermark, preserve every-frame sampling and prompt reclaim.\n        const bool near_gc_watermark =\n            total_used_memory >= minimum_memory - minimum_memory / 3;\n        if (near_gc_watermark || (frame_tick & 1u) == 0) {\n            total_used_memory = runtime.GetDeviceMemoryUsage();\n        }\n#else\n        total_used_memory = runtime.GetDeviceMemoryUsage();\n#endif\n    }\n    if (total_used_memory >= minimum_memory) {\n        RunGarbageCollector();\n    }"
assert expected.count(budget_old) == 1
expected = expected.replace(budget_old, budget_new)
# Preserve overlapping rolling uniform-hit windows without forward-copy UB.
history_old = "    std::copy_n(channel_state->uniform_cache_hits.begin(),\n                channel_state->uniform_cache_hits.size() - 1,\n                channel_state->uniform_cache_hits.begin() + 1);\n    std::copy_n(channel_state->uniform_cache_shots.begin(),\n                channel_state->uniform_cache_shots.size() - 1,\n                channel_state->uniform_cache_shots.begin() + 1);"
history_new = "    // History shifts overlap their source ranges. Copy from the back so\n    // each previous interval is retained exactly once, even under -O2.\n    std::copy_backward(channel_state->uniform_cache_hits.begin(),\n                       channel_state->uniform_cache_hits.end() - 1,\n                       channel_state->uniform_cache_hits.end());\n    std::copy_backward(channel_state->uniform_cache_shots.begin(),\n                       channel_state->uniform_cache_shots.end() - 1,\n                       channel_state->uniform_cache_shots.end());"
assert expected.count(history_old) == 1
expected = expected.replace(history_old, history_new)
# Do not underflow unsigned frame age during early-pressure buffer GC.
gc_age_old = "    const u64 ticks_to_destroy = aggressive_gc ? 60 : 120;\n    int num_iterations = aggressive_gc ? 64 : 32;"
gc_age_new = "    const u64 ticks_to_destroy = aggressive_gc ? 60 : 120;\n#ifdef PS5_NATIVE\n    // Before a buffer reaches the GC age, subtracting from this unsigned\n    // frame tick wraps to a huge LRU threshold. On startup/pressure bursts\n    // that wrongly evicts young buffers and can force guest downloads.\n    if (frame_tick < ticks_to_destroy) {\n        return;\n    }\n#endif\n    int num_iterations = aggressive_gc ? 64 : 32;"
assert expected.count(gc_age_old) == 1
expected = expected.replace(gc_age_old, gc_age_new)
# A fresh driver memory snapshot can be smaller than the previous buffer's
# rounded size. Unregistering it must never underflow the shared usage counter.
unregister_budget_before = "    } else {\n        total_used_memory -= Common::AlignUp(size, 1024);\n        lru_cache.Free(buffer.getLRUID());\n    }"
unregister_budget_after = "    } else {\n#ifdef PS5_NATIVE\n        // The driver budget snapshot is not an allocation ledger. A stale or\n        // smaller snapshot must not wrap unsigned usage to UINT64_MAX when\n        // removing a previously registered buffer (and trigger GC storms).\n        const u64 accounted_bytes = Common::AlignUp(size, 1024);\n        total_used_memory = total_used_memory >= accounted_bytes\n                                ? total_used_memory - accounted_bytes : 0;\n#else\n        total_used_memory -= Common::AlignUp(size, 1024);\n#endif\n        lru_cache.Free(buffer.getLRUID());\n    }"
assert expected.count(unregister_budget_before) == 1
expected = expected.replace(unregister_budget_before, unregister_budget_after)
# Channel-less homebrew/title teardown must still advance deferred GPU
# staging and destruction on PS5; desktop's original early exit is unchanged.
no_channel_old = "    // Homebrew console apps don't create or bind any channels, so this will be nullptr.\n    if (!channel_state) {\n        return;\n    }\n    runtime.TickFrame(slot_buffers);"
no_channel_new = "    // Homebrew console apps don't create or bind any channels, so this will be nullptr.\n    if (!channel_state) {\n#ifdef PS5_NATIVE\n        // The final channel can disappear while native Vulkan buffers and\n        // deferred staging remain alive. Advance the GPU lifetime scan and\n        // retirement rings even without uniform-cache statistics.\n        runtime.TickFrame(slot_buffers);\n        ++frame_tick;\n        delayed_destruction_ring.Tick();\n        for (auto& buffer : async_buffers_death_ring) {\n            runtime.FreeDeferredStagingBuffer(buffer);\n        }\n        async_buffers_death_ring.clear();\n#endif\n        return;\n    }\n    runtime.TickFrame(slot_buffers);"
assert expected.count(no_channel_old) == 1
expected = expected.replace(no_channel_old, no_channel_new)
assert maintained == expected, "R437 maintained header differs from reviewed transforms"
assert maintained.count('::Eden::BufferPages::Mark(buffer.CpuAddr(), size);') == 1
assert 'buffer-pages/video_core/buffer_cache/buffer_cache.h' in cm
assert r.count('::Eden::BufferPages::NeverRegistered(addr, size)')==8
# Five newer sites extend the original R437 witnesses: the batched path,
# two single-range invalidations, and CPU unmap. These optimizations must
# preserve shader/texture invalidation and unknown-memory fallback.
assert 'bool buffer_may_overlap = false;' in r
assert 'if (buffer_may_overlap)' in r
witness=(root/'headless/buffer_pages.h').read_text()
assert 'registered[word].load(std::memory_order_acquire) & mask' in witness
assert witness.count('if(size <= (std::uint64_t{1}<<kPageBits)-(address&page_mask)){') == 2
assert 'registered[page/64].load(std::memory_order_acquire)' in witness
assert 'return !coverage_unknown.load(std::memory_order_acquire);' in witness
assert 'registered[word].fetch_or(mask,std::memory_order_release)' in witness
assert g.count('::Eden::BufferPages::NeverRegistered(addr, size)')==8
pos=r.index('bool RasterizerVulkan::OnCPUWrite(DAddr addr, u64 size)')
body=r[pos:r.index('void RasterizerVulkan::OnCacheInvalidation',pos)]
assert body.index('::Eden::BufferPages::NeverRegistered') < body.index(
    '::Eden::Performance::GuestCacheLock(buffer_cache.mutex, false)')
assert body.index('::Eden::Performance::GuestCacheLock(buffer_cache.mutex, false)') < body.index(
    'texture_cache.WriteMemory(addr, size);') < body.index(
    'pipeline_cache.InvalidateRegion(addr, size);')
assert body.count('texture_cache.WriteMemory(addr, size);')==1
assert body.count('pipeline_cache.InvalidateRegion(addr, size);')==1
cxx=shutil.which('c++') or shutil.which('clang++') or shutil.which('g++')
assert cxx
cpp=r"""
#include "buffer_pages.h"
#include <array>
#include <cassert>
#include <thread>
#include <vector>
int main(){
 using namespace Eden::BufferPages;
 constexpr std::uint64_t p=4096;
 assert(NeverRegistered(0,1));
 assert(!NeverRegistered(0,0) && !NeverRegistered(kSpace,1));
 assert(!NeverRegistered(0,64*p+1) && !NeverRegistered(kSpace-1,2));
 Mark(0,1);
 assert(!NeverRegistered(0,1) && NeverRegistered(p,1));
 // A previously marked word stays marked on repeated registrations.
 Mark(100*p,1);
 const auto word = (100ull*p >> kPageBits) / 64;
 const auto previous = registered[word].load(std::memory_order_acquire);
 for(unsigned n=0;n<2000;++n) Mark(100*p,1);
 assert(registered[word].load(std::memory_order_acquire)==previous);
 // Concurrent overlapping and disjoint writers within one bitmap word
 // must never lose either registration on the conditional fast path.
 std::vector<std::thread> overlapping;
 for(unsigned t=0;t<8;++t)overlapping.emplace_back([t]{
   for(unsigned n=0;n<1000;++n) {
     Mark((128+t)*p, 1);
     Mark(128*p, 8*p);
   }
 });
 for(auto& task:overlapping)task.join();
 for(unsigned t=0;t<8;++t)assert(!NeverRegistered((128+t)*p,1));
 Mark(63*p+7,2*p);
 assert(!NeverRegistered(63*p,1) && !NeverRegistered(64*p,1));
 assert(!NeverRegistered(65*p,1) && NeverRegistered(66*p,p));
 std::vector<std::thread> jobs;
 for(unsigned t=0;t<8;t++)jobs.emplace_back([t]{
    const auto b=(1000000ull+t*1000ull)*4096ull;
    for(unsigned n=0;n<512;n++)Mark(b+n*4096,1);
 });
 for(auto& j:jobs)j.join();
 for(unsigned t=0;t<8;t++){
   const auto b=(1000000ull+t*1000ull)*4096ull;
   assert(!NeverRegistered(b,1));
   assert(!NeverRegistered(b+511*p,1));
   assert(NeverRegistered(b+512*p,1));
 }
 // Compare against an independent page-by-page owner oracle, including
 // registered, empty, crossing, oversized, near-end and unaligned writes.
 auto oracle=[](std::uint64_t address,std::uint64_t size){
   if(coverage_unknown.load(std::memory_order_acquire) ||
      !size || size>256*1024 || address>=kSpace || size>kSpace-address)return false;
   auto first=address>>kPageBits;
   auto last=(address+size-1)>>kPageBits;
   for(auto page=first;page<=last;++page)
     if((registered[page/64].load(std::memory_order_acquire)>>(page%64))&1u)
       return false;
   return !coverage_unknown.load(std::memory_order_acquire);
 };
 std::uint64_t rng=0xfed3c689a5b72d41ull;
 constexpr std::uint64_t lens[]{0,1,2,7,4095,4096,4097,65536,262144,262145};
 for(unsigned i=0;i<18000;++i){
   rng^=rng<<13;rng^=rng>>7;rng^=rng<<17;
   const auto address=i%3==0 ? rng%(4096ull*12000) :
                      i%3==1 ? kSpace-1-rng%10000 : rng%kSpace;
   const auto bytes=lens[i%10];
   assert(NeverRegistered(address,bytes)==oracle(address,bytes));
 }
 for(std::uint64_t addr : std::array<std::uint64_t,5>{0,4095,63*p+4095,64*p,kSpace-1})
   for(std::uint64_t bytes : lens)
     assert(NeverRegistered(addr,bytes)==oracle(addr,bytes));
 // Marking a one-page span must publish the exact same bit as the
 // previous generic word-range algorithm, including the word boundary.
 Mark(192*p+1,4094);
 assert(!NeverRegistered(192*p,1) && NeverRegistered(193*p,1));
 Mark(kSpace+1,1);
 assert(!NeverRegistered(66*p,1));
}
"""
with tempfile.TemporaryDirectory(prefix='eden-r437-') as d:
 src=Path(d)/'b.cpp';exe=Path(d)/'b'
 src.write_text(cpp)
 for opt in ('-O0','-O2'):
  exe=Path(d)/('b'+opt)
  subprocess.run([cxx,'-std=c++20',opt,'-pthread','-Wall','-Wextra','-Werror',
   '-fsanitize=undefined','-fno-sanitize-recover=all','-I'+str(root/'headless'),
   str(src),'-o',str(exe)],check=True,timeout=90)
  subprocess.run([str(exe)],check=True,timeout=90)
print('PASS R437 buffer-page witness and protected HUD invalidation')
