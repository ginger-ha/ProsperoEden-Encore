"""Adapt the pinned Eden Vulkan platform boundary and required renderer fixes."""
from pathlib import Path
import struct
import re
import os
import subprocess
import sys
source, output = map(Path, sys.argv[1:])
port = Path(__file__).resolve().parents[1] / 'headless'
vulkan_oracle = Path(__file__).resolve().parents[1] / 'vendor/encore-active/eden-vulkan-oracles'
def adapt(relative, destination, replacements):
    text = (source / relative).read_text()
    for old, new in replacements:
        if text.count(old) != 1:
            raise RuntimeError(f"Pinned Vulkan anchor changed: {relative}: {old[:60]}")
        text = text.replace(old, new)
    path = output / destination
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)

adapt('src/core/frontend/emu_window.h', 'include/core/frontend/emu_window.h',
      [('    Xcb,', '    Xcb,\n    PS5,')])
adapt('src/video_core/renderer_vulkan/vk_rasterizer.cpp', 'vulkan_rasterizer.cpp', [
    # DMA extent width contract: avoid u32 wrap before buffer-cache lookup.
    ("    const u32 buffer_size = static_cast<u32>(buffer_operand.pitch * buffer_operand.height);", "    // Widen before multiplying, then respect the u32 buffer-cache span.\n    const u64 buffer_size_wide = static_cast<u64>(buffer_operand.pitch) * buffer_operand.height;\n    if (buffer_size_wide > static_cast<u64>(~u32{0})) {\n        return false;\n    }\n    const u32 buffer_size = static_cast<u32>(buffer_size_wide);"),
    # CPU page registration proof for buffer-only guest readbacks.
    ("    if ((True(which & VideoCommon::CacheType::BufferCache))) {\n        std::scoped_lock lock{buffer_cache.mutex};\n        buffer_cache.DownloadMemory(addr, size);\n    }", "    // DownloadMemory visits registered buffers only. Pages with no\n    // registration history cannot require a buffer readback or mutex.\n    // Unknown/large spans conservatively execute the original path.\n    if (True(which & VideoCommon::CacheType::BufferCache) &&\n        !::Eden::BufferPages::NeverRegistered(addr, size)) {\n        std::scoped_lock lock{buffer_cache.mutex};\n        buffer_cache.DownloadMemory(addr, size);\n    }"),
    ("    if ((True(which & VideoCommon::CacheType::BufferCache))) {\n        std::scoped_lock lock{buffer_cache.mutex};\n        if (buffer_cache.IsRegionGpuModified(addr, size)) {\n            return true;\n        }\n    }", "    // A buffer GPU-dirty range requires a registered buffer. Never skip\n    // the test for an unknown or formerly registered CPU page.\n    if (True(which & VideoCommon::CacheType::BufferCache) &&\n        !::Eden::BufferPages::NeverRegistered(addr, size)) {\n        std::scoped_lock lock{buffer_cache.mutex};\n        if (buffer_cache.IsRegionGpuModified(addr, size)) {\n            return true;\n        }\n    }"),
    # Skip impossible texture readback mutex acquisitions, CPU addresses only.
    ("    if (True(which & VideoCommon::CacheType::TextureCache)) {\n        std::scoped_lock lock{texture_cache.mutex};\n        texture_cache.DownloadMemory(addr, size);\n    }", "    // No guest image ever overlapped these CPU pages: no texture readback.\n    // Unknown, large or previously registered pages keep the original lock.\n    if (True(which & VideoCommon::CacheType::TextureCache) &&\n        !::Eden::ImagePages::NeverHeld(addr, size)) {\n        std::scoped_lock lock{texture_cache.mutex};\n        texture_cache.DownloadMemory(addr, size);\n    }"),
    ("    if (True(which & VideoCommon::CacheType::TextureCache)) {\n        std::scoped_lock lock{texture_cache.mutex};\n        return texture_cache.IsRegionGpuModified(addr, size);\n    }", "    // Zero-size queries preserve old behavior; known-empty valid pages\n    // cannot contain any GPU-modified texture requiring a guest readback.\n    if (True(which & VideoCommon::CacheType::TextureCache) &&\n        (size == 0 || !::Eden::ImagePages::NeverHeld(addr, size))) {\n        std::scoped_lock lock{texture_cache.mutex};\n        return texture_cache.IsRegionGpuModified(addr, size);\n    }"),
    # CPU-addressed unmapping: do not lock an image cache for never-held pages.
    ("void RasterizerVulkan::UnmapMemory(DAddr addr, u64 size) {\n    {\n        std::scoped_lock lock{texture_cache.mutex};\n        texture_cache.UnmapMemory(addr, size);\n    }", "void RasterizerVulkan::UnmapMemory(DAddr addr, u64 size) {\n    // ImagePages tracks CPU-addressed registered images monotonically.\n    // Do not contend on the texture mutex if this unmapped CPU range\n    // could never own an image; unknown/large ranges retain full work.\n    if (!::Eden::ImagePages::NeverHeld(addr, size)) {\n        std::scoped_lock lock{texture_cache.mutex};\n        texture_cache.UnmapMemory(addr, size);\n    }"),
    # The CPU Unmap path may skip ONLY buffer invalidation if no CPU page
    # in this span has ever belonged to a guest GPU buffer. Leave texture
    # eviction and shader invalidation in the original order.
    ("    {\n        std::scoped_lock lock{buffer_cache.mutex};\n        buffer_cache.WriteMemory(addr, size);\n    }\n    pipeline_cache.OnCacheInvalidation(addr, size);", "    // A never-registered CPU page cannot reference a cached GPU buffer.\n    // The monotonic owner witness fails closed on unknown or large ranges;\n    // a buffer registered later begins CPU-dirty and uploads normally.\n    if (!::Eden::BufferPages::NeverRegistered(addr, size)) {\n        std::scoped_lock lock{buffer_cache.mutex};\n        buffer_cache.WriteMemory(addr, size);\n    }\n    pipeline_cache.OnCacheInvalidation(addr, size);"),
    # Conservative native inline-upload texture lock elision (CPU occupancy only).
    ("    {\n        std::scoped_lock lock_texture{texture_cache.mutex};\n        texture_cache.WriteMemory(*cpu_addr, copy_size);\n    }", "    // DMA inline writes do not need the texture mutex when these CPU pages\n    // have never belonged to an image. Unknown and large ranges fail closed.\n    if (!::Eden::ImagePages::NeverHeld(*cpu_addr, copy_size)) {\n        std::scoped_lock lock_texture{texture_cache.mutex};\n        texture_cache.WriteMemory(*cpu_addr, copy_size);\n    }"),
    # R: skip provably unnecessary Vulkan texture-cache invalidation locks.
    ("void RasterizerVulkan::InvalidateRegion(DAddr addr, u64 size, VideoCommon::CacheType which) {\n    if (addr == 0 || size == 0) {\n        return;\n    }\n    if (True(which & VideoCommon::CacheType::TextureCache)) {", "void RasterizerVulkan::InvalidateRegion(DAddr addr, u64 size, VideoCommon::CacheType which) {\n    if (addr == 0 || size == 0) {\n        return;\n    }\n    // The monotonic image page map is published before registration.\n    // Only bypass the texture mutex when the range never held an image.\n    if (True(which & VideoCommon::CacheType::TextureCache) &&\n        !::Eden::ImagePages::NeverHeld(addr, size)) {"),
    ("void RasterizerVulkan::InnerInvalidation(std::span<const std::pair<DAddr, std::size_t>> sequences) {\n    {\n        std::scoped_lock lock{texture_cache.mutex};\n        for (const auto& [addr, size] : sequences) {\n            texture_cache.WriteMemory(addr, size);\n        }\n    }", "void RasterizerVulkan::InnerInvalidation(std::span<const std::pair<DAddr, std::size_t>> sequences) {\n    // One owner-witness traversal for the whole batch. Texture and buffer\n    // page occupancy are monotonic, independently published before cache\n    // registration. Preserve the original texture -> buffer -> shader order.\n    // Stop probing a domain once an overlapping range is known.\n    bool texture_may_overlap = false;\n    bool buffer_may_overlap = false;\n    for (const auto& [addr, size] : sequences) {\n        if (!texture_may_overlap && !::Eden::ImagePages::NeverHeld(addr, size))\n            texture_may_overlap = true;\n        if (!buffer_may_overlap && !::Eden::BufferPages::NeverRegistered(addr, size))\n            buffer_may_overlap = true;\n        if (texture_may_overlap && buffer_may_overlap) break;\n    }\n    if (texture_may_overlap) {\n        std::scoped_lock lock{texture_cache.mutex};\n        for (const auto& [addr, size] : sequences) {\n            // Recheck under the texture mutex, so a concurrent registration\n            // cannot be mistaken for an image-free page in a mixed batch.\n            if (!::Eden::ImagePages::NeverHeld(addr, size)) {\n                texture_cache.WriteMemory(addr, size);\n            }\n        }\n    }"),
    ("void RasterizerVulkan::OnCacheInvalidation(DAddr addr, u64 size) {\n    if (addr == 0 || size == 0) {\n        return;\n    }\n\n    {\n        std::scoped_lock lock{texture_cache.mutex};\n        texture_cache.WriteMemory(addr, size);\n    }", "void RasterizerVulkan::OnCacheInvalidation(DAddr addr, u64 size) {\n    if (addr == 0 || size == 0) {\n        return;\n    }\n\n    // A never-owned image page cannot have texture descriptors to evict.\n    // Unknown, large and previously mapped spans still acquire the mutex.\n    if (!::Eden::ImagePages::NeverHeld(addr, size)) {\n        std::scoped_lock lock{texture_cache.mutex};\n        texture_cache.WriteMemory(addr, size);\n    }"),
    # Preserve buffer first-registration CPU-dirty semantics while eliding
    # proven-empty batched buffer invalidations on the native GPU hot path.
    ("    {\n        std::scoped_lock lock{buffer_cache.mutex};\n        for (const auto& [addr, size] : sequences) {\n            buffer_cache.WriteMemory(addr, size);\n        }\n    }", "    // BufferPages::Mark publishes before insertion; a future registration\n    // begins CPU-dirty. The shared preflight above still fails closed for\n    // unknown/large ranges. Keep rechecks under the original cache mutex.\n    if (buffer_may_overlap) {\n        std::scoped_lock lock{buffer_cache.mutex};\n        for (const auto& [addr, size] : sequences) {\n            if (!::Eden::BufferPages::NeverRegistered(addr, size)) {\n                buffer_cache.WriteMemory(addr, size);\n            }\n        }\n    }"),
    # FC27 reviewed P0: avoid buffer mutex on never-owned guest pages for
    # the two *single-range* invalidation paths. Leave independent texture,
    # shader and query paths in original source order.
    ("    if ((True(which & VideoCommon::CacheType::BufferCache))) {\n        std::scoped_lock lock{buffer_cache.mutex};\n        buffer_cache.WriteMemory(addr, size);\n    }\n    if ((True(which & VideoCommon::CacheType::QueryCache))) {", "    // A buffer cannot have GPU-owned content before its first registration.\n    // NeverRegistered fails closed for unknown or large ranges; future buffer\n    // registrations start CPU-dirty, so their first upload is unaffected.\n    if (True(which & VideoCommon::CacheType::BufferCache) &&\n        !::Eden::BufferPages::NeverRegistered(addr, size)) {\n        std::scoped_lock lock{buffer_cache.mutex};\n        buffer_cache.WriteMemory(addr, size);\n    }\n    if ((True(which & VideoCommon::CacheType::QueryCache))) {"),
    ("    {\n        std::scoped_lock lock{buffer_cache.mutex};\n        buffer_cache.WriteMemory(addr, size);\n    }\n    pipeline_cache.InvalidateRegion(addr, size);\n}", "    // Unowned pages cannot contain stale buffer data. Preserve the\n    // shader invalidation regardless of buffer ownership.\n    if (!::Eden::BufferPages::NeverRegistered(addr, size)) {\n        std::scoped_lock lock{buffer_cache.mutex};\n        buffer_cache.WriteMemory(addr, size);\n    }\n    pipeline_cache.InvalidateRegion(addr, size);\n}"),
    # DMA buffer-copy spans are narrowed to u32 by FindBuffer. Reject any
    # empty/oversized copy before the guest buffer-cache mutex is acquired.
    ("bool AccelerateDMA::BufferCopy(GPUVAddr src_address, GPUVAddr dest_address, u64 amount) {\n    std::scoped_lock lock{buffer_cache.mutex};\n    return buffer_cache.DMACopy(src_address, dest_address, amount);\n}", "bool AccelerateDMA::BufferCopy(GPUVAddr src_address, GPUVAddr dest_address, u64 amount) {\n    // Invalid DMA byte counts have no GPU buffer range; return to the\n    // software path without contending on the guest buffer cache mutex.\n    if (amount == 0 || amount > static_cast<u64>(~u32{0})) {\n        return false;\n    }\n    std::scoped_lock lock{buffer_cache.mutex};\n    return buffer_cache.DMACopy(src_address, dest_address, amount);\n}"),
    # Signed INT_MIN scissor offsets must be widened before negation.
    ("const u32 shrink = (std::min)(extent, static_cast<u32>(-offset));", "const u32 shrink = (std::min)(extent, static_cast<u32>(-static_cast<s64>(offset)));"),
    # R: DrawTexture needs the same pending guest memory invalidation drain
    # as ordinary draw/clear, before its texture-cache mutex acquisition.
    ("    FlushWork();\n\n    std::scoped_lock l{texture_cache.mutex};\n    texture_cache.SynchronizeDescriptors(false);", "    FlushWork();\n    // Apply queued guest page remaps before reading cache-owned texture views.\n    // InnerInvalidation itself locks texture_cache.mutex.\n    gpu_memory->FlushCaching();\n\n    std::scoped_lock l{texture_cache.mutex};\n    texture_cache.SynchronizeDescriptors(false);"),
    # The raw-image Vulkan blit in DrawTexture binds a graphics pipeline
    # without invalidating the tracked guest pipeline state. Restore the
    # scheduler's graphics/descriptor state after the blit is queued.
    ("    blit_image.BlitColor(framebuffer, texture.RenderTarget(), texture.ImageHandle(),\n"
     "                         sampler->Handle(), dst_region, src_region, src_size);\n"
     "}",
     "    blit_image.BlitColor(framebuffer, texture.RenderTarget(), texture.ImageHandle(),\n"
     "                         sampler->Handle(), dst_region, src_region, src_size);\n"
     "#ifdef PS5_NATIVE\n"
     "    // Raw-image blit directly binds its own Vulkan graphics pipeline.\n"
     "    // It does not invalidate Scheduler's cached guest graphics state.\n"
     "    // Ensure the following guest draw rebinds pipeline and descriptors.\n"
     "    scheduler.InvalidateState();\n"
     "#endif\n"
     "}"),
    # Guard short unsigned quad strips before subtracting the two lead vertices.
    ("params.num_vertices = (params.num_vertices - 2) / 2 * 6;", "params.num_vertices = params.num_vertices >= 2 ? (params.num_vertices - 2) / 2 * 6 : 0;"),
    # Compute synchronization (dev_vulkan.h compute_barriers): indirect
    # dispatches returned before the pre-dispatch barrier, and no barrier made a dispatch's
    # writes visible to later indirect arguments, vertex/index fetch, shaders or copies.
    ('void RasterizerVulkan::DispatchCompute() {',
     """namespace {
constexpr VkMemoryBarrier COMPUTE_WRITE_BARRIER{
    .sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
    .pNext = nullptr,
    .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT,
    .dstAccessMask = VK_ACCESS_INDIRECT_COMMAND_READ_BIT | VK_ACCESS_INDEX_READ_BIT |
                     VK_ACCESS_VERTEX_ATTRIBUTE_READ_BIT | VK_ACCESS_UNIFORM_READ_BIT |
                     VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT |
                     VK_ACCESS_TRANSFER_READ_BIT | VK_ACCESS_TRANSFER_WRITE_BIT,
};
constexpr VkMemoryBarrier COMPUTE_INPUT_BARRIER{
    .sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER,
    .pNext = nullptr,
    .srcAccessMask = VK_ACCESS_MEMORY_WRITE_BIT,
    .dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_INDIRECT_COMMAND_READ_BIT,
};
constexpr VkPipelineStageFlags COMPUTE_CONSUMER_STAGES =
    VK_PIPELINE_STAGE_DRAW_INDIRECT_BIT | VK_PIPELINE_STAGE_VERTEX_INPUT_BIT |
    VK_PIPELINE_STAGE_ALL_GRAPHICS_BIT | VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT |
    VK_PIPELINE_STAGE_TRANSFER_BIT;
} // namespace

void RasterizerVulkan::DispatchCompute() {"""),
    ('        scheduler.RequestOutsideRenderPassOperationContext();\n        scheduler.Record([pipeline, indirect_buffer = buffer->Handle(),',
     """        scheduler.RequestOutsideRenderPassOperationContext();
        if (::Eden::DevVulkan::compute_barriers) {
            scheduler.Record([](vk::CommandBuffer cmdbuf) {
                cmdbuf.PipelineBarrier(vk::PIPELINE_STAGE_GRAPHICS_COMPUTE_TRANSFER,
                                       VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT | VK_PIPELINE_STAGE_DRAW_INDIRECT_BIT,
                                       0, COMPUTE_INPUT_BARRIER);
            });
        }
        scheduler.Record([pipeline, indirect_buffer = buffer->Handle(),"""),
    ('            cmdbuf.DispatchIndirect(indirect_buffer, indirect_offset);\n',
     """            cmdbuf.DispatchIndirect(indirect_buffer, indirect_offset);
            if (::Eden::DevVulkan::compute_barriers)
                cmdbuf.PipelineBarrier(VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, COMPUTE_CONSUMER_STAGES, 0,
                                       COMPUTE_WRITE_BARRIER);
"""),
    ('        cmdbuf.Dispatch(dim[0], dim[1], dim[2]);\n',
     """        cmdbuf.Dispatch(dim[0], dim[1], dim[2]);
        if (::Eden::DevVulkan::compute_barriers)
            cmdbuf.PipelineBarrier(VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, COMPUTE_CONSUMER_STAGES, 0,
                                   COMPUTE_WRITE_BARRIER);
"""),
    # CounterEnable below starts a query immediately. A deferred clear has no
    # active pass yet, so later realization would end that query in a different
    # render-pass scope (VUID-vkCmdEndQuery-None-07007). Keep the immediate path
    # when the guest enables occlusion counting.
    ('const bool can_defer_clear = ENABLE_DEFERRED_CLEAR &&',
     'const bool can_defer_clear = ENABLE_DEFERRED_CLEAR && !regs.zpass_pixel_count_enable &&'),
    ('#include <algorithm>', '#include <algorithm>\n#include "performance.h"\n#include "buffer_write_ahead.h"'),
    # Guest threads take the cache locks here (tracked-page writes, flush-area reads).
    ('bool RasterizerVulkan::OnCPUWrite(DAddr addr, u64 size) {',
     'bool RasterizerVulkan::OnCPUWrite(DAddr addr, u64 size) {\n    ::Eden::Performance::BatchedGuestWriteTimer guest_write_timer;\n    const bool sample_guest_write = ::Eden::Performance::ShouldSampleGuestWrite();'),
    ('VideoCore::RasterizerDownloadArea RasterizerVulkan::GetFlushArea(DAddr addr, u64 size) {',
     "VideoCore::RasterizerDownloadArea RasterizerVulkan::GetFlushArea(DAddr addr, u64 size) {\n    ::Eden::Performance::DiagnosticTimer guest_read_timer(::Eden::Performance::guest_cpu_read);\n    // A guest read cannot overlap a registered image when no page in this\n    // range has ever appeared in the image slot map. Skip the GPU-held mutex.\n    // Unknown/out-of-range/large ranges retain the original blocking path.\n    if (::Eden::ImagePages::NeverHeld(addr, size)) {\n        return VideoCore::RasterizerDownloadArea{\n            .start_address = Common::AlignDown(addr, Core::DEVICE_PAGESIZE),\n            .end_address = Common::AlignUp(addr + size, Core::DEVICE_PAGESIZE),\n            .preemtive = true,\n        };\n    }"),
    # ... and wait for those locks spinning briefly before sleeping (performance.h GuestCacheLock).
    ('        std::scoped_lock lock{texture_cache.mutex};\n        auto area = texture_cache.GetFlushArea(addr, size);',
     '        ::Eden::Performance::GuestCacheLock(texture_cache.mutex, true);\n'
     '        std::lock_guard lock{texture_cache.mutex, std::adopt_lock};\n        auto area = texture_cache.GetFlushArea(addr, size);'),
    ('        std::scoped_lock lock{buffer_cache.mutex};\n        if (buffer_cache.OnCPUWrite(addr, size)) {',
     '        ::Eden::Performance::CachePhaseTimer buffer_wait{\n'
     '            ::Eden::Performance::CachePhase::GuestWriteBufferWait, sample_guest_write};\n'
     '        ::Eden::Performance::GuestCacheLock(buffer_cache.mutex, false);\n'
     '        buffer_wait.Stop();\n'
     '        std::lock_guard lock{buffer_cache.mutex, std::adopt_lock};\n'
     '        ::Eden::Performance::CachePhaseTimer buffer_work{\n'
     '            ::Eden::Performance::CachePhase::GuestWriteBufferWork, sample_guest_write};\n'
     '        if (buffer_cache.OnCPUWrite(addr, size)) {'),
    ('    {\n        std::scoped_lock lock{texture_cache.mutex};\n        texture_cache.WriteMemory(addr, size);\n    }\n    pipeline_cache.InvalidateRegion(addr, size);',
     '    // ImagePages is monotonically published before texture slot insertion.\n'
     '    // Only never-held small ranges may skip the texture-cache mutex; unknown\n'
     '    // and previously registered pages retain the full invalidation path.\n'
     '    if (!::Eden::ImagePages::NeverHeld(addr, size)) {\n'
     '        ::Eden::Performance::CachePhaseTimer texture_wait{\n'
     '            ::Eden::Performance::CachePhase::GuestWriteTextureWait, sample_guest_write};\n'
     '        ::Eden::Performance::GuestCacheLock(texture_cache.mutex, true);\n'
     '        texture_wait.Stop();\n'
     '        std::lock_guard lock{texture_cache.mutex, std::adopt_lock};\n'
     '        ::Eden::Performance::CachePhaseTimer texture_work{\n'
     '            ::Eden::Performance::CachePhase::GuestWriteTextureWork, sample_guest_write};\n'
     '        texture_cache.WriteMemory(addr, size);\n    }\n'
     '    ::Eden::Performance::CachePhaseTimer shader_invalidate{\n'
     '        ::Eden::Performance::CachePhase::GuestWriteShaderInvalidate, sample_guest_write};\n'
     '    pipeline_cache.InvalidateRegion(addr, size);'),
    # Upstream #187 subset: under the ALREADY-HELD buffer lock, optionally
    # mark contiguous registered pages CPU-dirty ahead of a guest write.
    # No guest texture/shader tracking shortcut, no speculative deferred replay;
    # the unqualified path stays disabled by default (cpu_write_ahead=0).
    ('        if (buffer_cache.OnCPUWrite(addr, size)) {\n            return true;\n        }\n    }\n',
     '        if (buffer_cache.OnCPUWrite(addr, size)) {\n            return true;\n        }\n'
     '        (void)::Eden::BufferWriteAhead::MarkFollowingPages(\n'
     '            static_cast<std::uint64_t>(addr), static_cast<std::uint64_t>(size),\n'
     '            ::Eden::Performance::cpu_write_ahead.load(std::memory_order_relaxed),\n'
     '            [&](std::uint64_t page, std::uint64_t span) {\n'
     '                return buffer_cache.IsRegionRegistered(static_cast<DAddr>(page), span);\n'
     '            },\n'
     '            [&](std::uint64_t page, std::uint64_t span) {\n'
     '                return buffer_cache.OnCPUWrite(static_cast<DAddr>(page), span);\n'
     '            });\n    }\n'),
    # From upstream ProsperoEden 0dd9dd0 (#102): submitting after 4096 draws
    # can exceed the PS5 GPU watchdog (VK_ERROR_DEVICE_LOST). Cap command
    # buffers at 512 draws, keeping Encore's current worker handoff cadence
    # and runtime diagnostics unchanged. Replace the FULL platform ifdef.
    ('#ifdef __ANDROID__\n    static constexpr u32 DRAWS_TO_DISPATCH = 512;\n    static constexpr u32 CHECK_MASK = 3;\n#else\n    static constexpr u32 DRAWS_TO_DISPATCH = 4096;\n    static constexpr u32 CHECK_MASK = 7;\n#endif // __ANDROID__\n\n    static_assert(DRAWS_TO_DISPATCH % (CHECK_MASK + 1) == 0);\n',
     '    static constexpr u32 DRAWS_TO_DISPATCH = 512;\n'
     '    const u32 CHECK_MASK = ::Eden::Performance::dispatch_mask.load(std::memory_order_relaxed);\n\n'),
    # R437: buffer-cache OnCPUWrite is allowed to avoid only the buffer
    # mutex when no page in the small write was EVER registered. The image
    # and shader invalidations remain unconditional on this code path.
    ('DEBUG_ASSERT(addr != 0 || size != 0);\n    {\n        ::Eden::Performance::CachePhaseTimer buffer_wait',
     'DEBUG_ASSERT(addr != 0 || size != 0);\n    // Buffer and texture page evidence independently guards their mutexes.\n    // Shader invalidation always runs, even if neither cache ever owned a page.\n    if (!::Eden::BufferPages::NeverRegistered(addr, size)) {\n        ::Eden::Performance::CachePhaseTimer buffer_wait'),
    # R309 PS5 watchdog: upstream checked the dispatch cadence BEFORE the 512-draw
    # ceiling. At mask 7 it therefore flushed on draw 519, not 512; at mask 63
    # on draw 575. Enforce the hard ceiling independently of dispatch cadence.
    # Preserve the original pre-flush dispatch calls and all cache/fence locks.
    ('    if ((++draw_counter & CHECK_MASK) != CHECK_MASK) {\n'
     '        return;\n'
     '    }\n'
     '    if (draw_counter < DRAWS_TO_DISPATCH) {\n'
     '        scheduler.DispatchWork();\n'
     '        return;\n'
     '    }\n'
     '    scheduler.Flush();\n'
     '    draw_counter = 0;',
     '''    ++draw_counter;
    if (draw_counter >= DRAWS_TO_DISPATCH) {
        scheduler.Flush();
        draw_counter = 0;
        return;
    }
    if ((draw_counter & CHECK_MASK) == CHECK_MASK) {
        scheduler.DispatchWork();
    }'''),
    # Per-draw count for the GPU-thread report (dispatch time per draw).
    ('    FlushWork();\n    gpu_memory->FlushCaching();\n\n    GraphicsPipeline* const pipeline{pipeline_cache.CurrentGraphicsPipeline()};',
     '    if (::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed))\n'
     '        ::Eden::Performance::rasterizer_draw.calls.fetch_add(1, std::memory_order_relaxed);\n    FlushWork();\n    gpu_memory->FlushCaching();\n\n    GraphicsPipeline* const pipeline{pipeline_cache.CurrentGraphicsPipeline()};'),

    # R319: the guest descriptor queue can call scheduler.WaitWorker() on
    # capacity overflow while BOTH GPU caches are locked in ConfigureImpl.
    # Pre-drain the ordinary 0x400-entry reserve on the GPU thread BEFORE
    # the rasterizer takes those mutexes, using the same worker fence as
    # Acquire. Keep Acquire's original larger-descriptor fallback intact.
    ('    gpu_memory->FlushCaching();\n\n    GraphicsPipeline* const pipeline{pipeline_cache.CurrentGraphicsPipeline()};',
     '''    gpu_memory->FlushCaching();
#ifdef PS5_NATIVE
    if (guest_descriptor_queue.PreflightGuestDraw([this] { scheduler.WaitWorker(); })) {
        // CPU guests can have invalidated texture pages during the drain.
        // Consume those guest remaps before choosing a pipeline/cache views.
        gpu_memory->FlushCaching();
    }
#endif

    GraphicsPipeline* const pipeline{pipeline_cache.CurrentGraphicsPipeline()};'''),
    # R325: uncommon >0x400-entry pipeline descriptor reservations can still
    # block in Acquire() under both guest cache mutexes. Check their exact
    # immutable reservation and reselect after any actual worker drain.
    ('    GraphicsPipeline* const pipeline{pipeline_cache.CurrentGraphicsPipeline()};\n'
     '    if (!pipeline) {\n        return;\n    }',
     '''    GraphicsPipeline* pipeline{pipeline_cache.CurrentGraphicsPipeline()};
    if (!pipeline) {
        ::Eden::Performance::RecordGraphicsDrawDrop(
            ::Eden::Performance::GraphicsDrawDrop::NoPipeline);
        return;
    }
#ifdef PS5_NATIVE
    for (unsigned preflight = 0; preflight != 2; ++preflight) {
        // The initial exact-capacity check already passed without a drain.
        // Without a worker wait there was no shader reselection, so a second
        // identical capacity probe cannot change its answer on this draw.
        if (preflight == 0 && !initial_descriptor_drain) break;
        if (!pipeline->HasDescriptorEntries() ||
            !guest_descriptor_queue.PreflightExactGuestDraw(
                [this] { scheduler.WaitWorker(); }, pipeline->DescriptorEntryReservation()))
            break;
        gpu_memory->FlushCaching();
        pipeline = pipeline_cache.CurrentGraphicsPipeline();
        if (!pipeline) {
            ::Eden::Performance::RecordGraphicsDrawDrop(
                ::Eden::Performance::GraphicsDrawDrop::NoPipeline);
            return;
        }
    }
#endif'''),
    # A forced release blocks the GPU thread until the fence thread has retired
    # every older fence. Time only that producer-side drain.
    ('    fence_manager.WaitPendingFences(force);',
     '''    if (force) {
        ::Eden::Performance::DiagnosticTimer drain_timer(::Eden::Performance::gpu_fence_drain);
        fence_manager.WaitPendingFences(force);
    } else {
        fence_manager.WaitPendingFences(force);
    }'''),
    # UpdateDynamicStates asked the cache for the current pipeline a second time
    # per draw, recomputing the same fixed-state key. Reuse PrepareDraw's result;
    # other callers keep the original lookup.
    ('template <typename Func>\nvoid RasterizerVulkan::PrepareDraw(bool is_indexed, Func&& draw_func) {',
     '''namespace {
// GPU thread only: the pipeline PrepareDraw refreshed for the draw in progress.
GraphicsPipeline* prepared_pipeline = nullptr;
} // namespace

template <typename Func>
void RasterizerVulkan::PrepareDraw(bool is_indexed, Func&& draw_func) {'''),
    ('    std::scoped_lock lock{buffer_cache.mutex, texture_cache.mutex};\n    // update engine as channel may be different.',
     '''#ifdef PS5_NATIVE
    // Waiting on an eight-frame-old descriptor buffer GPU fence here keeps
    // guest texture writes unblocked while the Vulkan GPU owner waits.
    if (pipeline->CanUseDescriptorBuffer() &&
        descriptor_buffer_ring.PreflightFrameReuse(scheduler)) {
        // The frame fence can expose pending guest invalidations. Recheck
        // shader identity before using the pipeline under both cache locks.
        gpu_memory->FlushCaching();
        pipeline = pipeline_cache.CurrentGraphicsPipeline();
        if (!pipeline) {
            ::Eden::Performance::RecordGraphicsDrawDrop(
                ::Eden::Performance::GraphicsDrawDrop::NoPipeline);
            return;
        }
        // A newly selected pipeline may reserve more guest descriptors.
        // Keep any worker wait ahead of the paired cache mutexes.
        if (pipeline->HasDescriptorEntries() &&
            guest_descriptor_queue.PreflightExactGuestDraw(
                [this] { scheduler.WaitWorker(); }, pipeline->DescriptorEntryReservation())) {
            gpu_memory->FlushCaching();
            pipeline = pipeline_cache.CurrentGraphicsPipeline();
            if (!pipeline) {
                ::Eden::Performance::RecordGraphicsDrawDrop(
                    ::Eden::Performance::GraphicsDrawDrop::NoPipeline);
                return;
            }
        }
    }
#endif
#ifdef PS5_NATIVE
    // Pre-drain only when a new payload is GUARANTEED and the last ring
    // chunk is full. Reusable/uncertain payloads keep the original fallback.
    if (descriptor_buffer_ring.PreflightCapacity(
            scheduler, pipeline->DescriptorRingPreflightSize())) {
        gpu_memory->FlushCaching();
        pipeline = pipeline_cache.CurrentGraphicsPipeline();
        if (!pipeline) {
            ::Eden::Performance::RecordGraphicsDrawDrop(
                ::Eden::Performance::GraphicsDrawDrop::NoPipeline);
            return;
        }
        // This GPU drain can change the selected pipeline after the earlier
        // descriptor preflight. Check its NEW reservation before taking the
        // buffer/texture mutex pair, so Acquire cannot wait under both locks.
        if (pipeline->HasDescriptorEntries() &&
            guest_descriptor_queue.PreflightExactGuestDraw(
                [this] { scheduler.WaitWorker(); }, pipeline->DescriptorEntryReservation())) {
            gpu_memory->FlushCaching();
            pipeline = pipeline_cache.CurrentGraphicsPipeline();
            if (!pipeline) {
                ::Eden::Performance::RecordGraphicsDrawDrop(
                    ::Eden::Performance::GraphicsDrawDrop::NoPipeline);
                return;
            }
        }
    }
#endif
#ifdef PS5_NATIVE
    // Only reserve thread-local storage here. Cache descriptors and shader
    // bindings are still read and validated under the paired cache locks.
    pipeline->PreflightDescriptorScratch();
#endif
    const bool cache_sample = ::Eden::Performance::ShouldSampleCacheDraw();
    const bool previous_sample = ::Eden::Performance::cache_draw_sample_active;
    ::Eden::Performance::cache_draw_sample_active = cache_sample;
    SCOPE_EXIT { ::Eden::Performance::cache_draw_sample_active = previous_sample; };
    ::Eden::Performance::CachePhaseTimer pair_wait{
        ::Eden::Performance::CachePhase::PairWait, cache_sample};
    std::scoped_lock lock{buffer_cache.mutex, texture_cache.mutex};
    pair_wait.Stop();
    ::Eden::Performance::CachePhaseTimer pair_held{
        ::Eden::Performance::CachePhase::PairHeld, cache_sample};
    prepared_pipeline = pipeline;
    SCOPE_EXIT {
        prepared_pipeline = nullptr;
    };
    // update engine as channel may be different.'''),
    # R310: keep all GPU cache locks unchanged. Only clock 1/16 diagnostic
    # draws to resolve whether actual waits are in Configure or drawing.
    ('    pipeline->SetEngine(maxwell3d, gpu_memory);\n    if (!pipeline->Configure(is_indexed))\n        return;\n\n    UpdateDynamicStates();\n',
     '''    ::Eden::Performance::CachePhaseTimer configure_phase{
        ::Eden::Performance::CachePhase::PipelineConfigure, cache_sample};
    pipeline->SetEngine(maxwell3d, gpu_memory);
    const bool pipeline_ok = pipeline->Configure(is_indexed);
    configure_phase.Stop();
    if (!pipeline_ok) {
        ::Eden::Performance::RecordGraphicsDrawDrop(
            ::Eden::Performance::GraphicsDrawDrop::ConfigureRejected);
        return;
    }

    ::Eden::Performance::CachePhaseTimer dynamic_phase{
        ::Eden::Performance::CachePhase::DynamicStates, cache_sample};
    UpdateDynamicStates();
    dynamic_phase.Stop();
'''),
    ('    query_cache.NotifySegment(true);\n    HandleTransformFeedback();\n    query_cache.CounterEnable(VideoCommon::QueryType::ZPassPixelCount64, maxwell3d->regs.zpass_pixel_count_enable);\n    draw_func();',
     '''    ::Eden::Performance::CachePhaseTimer draw_phase{
        ::Eden::Performance::CachePhase::QueryAndDraw, cache_sample};
    query_cache.NotifySegment(true);
    HandleTransformFeedback();
    query_cache.CounterEnable(VideoCommon::QueryType::ZPassPixelCount64, maxwell3d->regs.zpass_pixel_count_enable);
    draw_func();
    draw_phase.Stop();'''),
    ('        if (auto* gp = pipeline_cache.CurrentGraphicsPipeline(); gp && gp->HasDynamicVertexInput()) {',
     '        if (auto* gp = prepared_pipeline ? prepared_pipeline : pipeline_cache.CurrentGraphicsPipeline();\n            gp && gp->HasDynamicVertexInput()) {'),
    # Development GPU fault probe (dev_vulkan.h, pipeline_trace=on): once the runner
    # creates /app0/sync-draws.txt, report every draw/dispatch to klog and wait for the
    # GPU, so the last report before a fatal GPU fault names the operation.
    ('#include "performance.h"', '#include "performance.h"\n#include "image_pages.h"\n#include "buffer_pages.h"\n#include "dev_vulkan.h"\n#include "diagnostics.h"\n#include <filesystem>'),
    ('scheduler.Record([draw_params](vk::CommandBuffer cmdbuf) {\n            ',
     'scheduler.Record([draw_params, pipeline = prepared_pipeline](vk::CommandBuffer cmdbuf) {\n            if (!pipeline || !pipeline->CanExecuteRecordedDraw()) {\n                ::Eden::Performance::RecordGraphicsDrawDrop(\n                    ::Eden::Performance::GraphicsDrawDrop::WorkerPipelineFailed);\n                return;\n            }\n            '),
    ('scheduler.Record([buffer_obj = buffer->Handle(), offset,\n                              stride = params.stride](vk::CommandBuffer cmdbuf) {\n                ',
     'scheduler.Record([buffer_obj = buffer->Handle(), offset,\n                              stride = params.stride,\n                              pipeline = prepared_pipeline](vk::CommandBuffer cmdbuf) {\n                if (!pipeline || !pipeline->CanExecuteRecordedDraw()) {\n                    ::Eden::Performance::RecordGraphicsDrawDrop(\n                        ::Eden::Performance::GraphicsDrawDrop::WorkerPipelineFailed);\n                    return;\n                }\n                '),
    ('scheduler.Record([draw_buffer_obj = draw_buffer->Handle(),\n                              buffer_obj = buffer->Handle(), offset_base, offset,\n                              params](vk::CommandBuffer cmdbuf) {\n                ',
     'scheduler.Record([draw_buffer_obj = draw_buffer->Handle(),\n                              buffer_obj = buffer->Handle(), offset_base, offset,\n                              params, pipeline = prepared_pipeline](vk::CommandBuffer cmdbuf) {\n                if (!pipeline || !pipeline->CanExecuteRecordedDraw()) {\n                    ::Eden::Performance::RecordGraphicsDrawDrop(\n                        ::Eden::Performance::GraphicsDrawDrop::WorkerPipelineFailed);\n                    return;\n                }\n                '),
    ('scheduler.Record([buffer_obj = buffer->Handle(), offset, params](vk::CommandBuffer cmdbuf) {\n            ',
     'scheduler.Record([buffer_obj = buffer->Handle(), offset, params,\n                          pipeline = prepared_pipeline](vk::CommandBuffer cmdbuf) {\n            if (!pipeline || !pipeline->CanExecuteRecordedDraw()) {\n                ::Eden::Performance::RecordGraphicsDrawDrop(\n                    ::Eden::Performance::GraphicsDrawDrop::WorkerPipelineFailed);\n                return;\n            }\n            '),
    ('''    FlushWork();
    gpu_memory->FlushCaching();
#ifdef PS5_NATIVE
    if (guest_descriptor_queue.PreflightGuestDraw''',
     '''    FlushWork();
#ifdef PS5_NATIVE
    // Pre-dispatch a nearly full command chunk before cache acquisition.
    // This is an ordinary FIFO dispatch, NOT a fence wait.
    if (scheduler.PreflightDrawCommands() &&
        ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)) {
        ::Eden::Performance::scheduler_preflight_dispatches.fetch_add(
            1, std::memory_order_relaxed);
    }
#endif
    gpu_memory->FlushCaching();
#ifdef PS5_NATIVE
    if (guest_descriptor_queue.PreflightGuestDraw'''),
    # Source-selected graphics preflight: zero-descriptor draws must not
    # drain 1024 payload entries before consulting their immutable pipeline.
    # Revalidate after a real drain because guest remaps can change shader IDs.
    ("#ifdef PS5_NATIVE\n    if (guest_descriptor_queue.PreflightGuestDraw([this] { scheduler.WaitWorker(); })) {\n        // CPU guests can have invalidated texture pages during the drain.\n        // Consume those guest remaps before choosing a pipeline/cache views.\n        gpu_memory->FlushCaching();\n    }\n#endif\n\n    GraphicsPipeline* pipeline{pipeline_cache.CurrentGraphicsPipeline()};\n    if (!pipeline) {\n        ::Eden::Performance::RecordGraphicsDrawDrop(\n            ::Eden::Performance::GraphicsDrawDrop::NoPipeline);\n        return;\n    }\n", "    GraphicsPipeline* pipeline{pipeline_cache.CurrentGraphicsPipeline()};\n    if (!pipeline) {\n        ::Eden::Performance::RecordGraphicsDrawDrop(\n            ::Eden::Performance::GraphicsDrawDrop::NoPipeline);\n        return;\n    }\n#ifdef PS5_NATIVE\n    // Select the actual shader first: the old 1024-entry preflight could\n    // wait for the GPU worker even when this pipeline writes zero descriptors.\n    // Never hold guest cache locks while waiting. The worker may publish guest\n    // remaps and change the selected pipeline, so reselect after a real drain.\n    bool initial_descriptor_drain = false;\n    if (pipeline->HasDescriptorEntries() &&\n        guest_descriptor_queue.PreflightGuestDraw([this] { scheduler.WaitWorker(); },\n                                                pipeline->DescriptorEntryReservation())) {\n        initial_descriptor_drain = true;\n        gpu_memory->FlushCaching();\n        pipeline = pipeline_cache.CurrentGraphicsPipeline();\n        if (!pipeline) {\n            ::Eden::Performance::RecordGraphicsDrawDrop(\n                ::Eden::Performance::GraphicsDrawDrop::NoPipeline);\n            return;\n        }\n    }\n#endif\n"),
    ('''void RasterizerVulkan::DispatchCompute() {
    FlushWork();
    gpu_memory->FlushCaching();''',
     '''void RasterizerVulkan::DispatchCompute() {
    FlushWork();
#ifdef PS5_NATIVE
    if (scheduler.PreflightDrawCommands() &&
        ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)) {
        ::Eden::Performance::scheduler_preflight_dispatches.fetch_add(
            1, std::memory_order_relaxed);
    }
#endif
    gpu_memory->FlushCaching();'''),
    ('GraphicsPipeline* prepared_pipeline = nullptr;',
     'GraphicsPipeline* prepared_pipeline = nullptr;\n'
     '// The pipeline of the last prepared draw, for the development fault probe.\n'
     'GraphicsPipeline* probe_pipeline = nullptr;\n'
     'bool SyncProbeActive() {\n'
     '    static unsigned poll = 0;\n'
     '    static bool active = false;\n'
     '    if (!active && ::Eden::DevVulkan::trace_pipelines && (++poll & 255) == 0)\n'
     '        active = std::filesystem::exists("/app0/sync-draws.txt");\n'
     '    return active;\n'
     '}\n'
     'void SyncProbe(Scheduler& scheduler, const char* kind, const void* pipeline) {\n'
     '    if (!SyncProbeActive()) return;\n'
     '    static unsigned long long sequence = 0;\n'
     '    char text[96];\n'
     '    std::snprintf(text, sizeof(text), "%s #%llu p=%p", kind, ++sequence, pipeline);\n'
     '    ::Eden::Report("sync", text);\n'
     '    scheduler.Finish();\n'
     '}'),
    ('    prepared_pipeline = pipeline;\n', '    prepared_pipeline = pipeline;\n    probe_pipeline = pipeline;\n'),
    ('        }\n    });\n}\n\nvoid RasterizerVulkan::DrawIndirect() {',
     '        }\n    });\n    SyncProbe(scheduler, "draw", probe_pipeline);\n}\n\nvoid RasterizerVulkan::DrawIndirect() {'),
    ('void RasterizerVulkan::DrawTexture() {', 'void RasterizerVulkan::DrawTexture() {\n    SCOPE_EXIT { SyncProbe(scheduler, "draw_texture", nullptr); };'),
    ('void RasterizerVulkan::Clear(u32 layer_count) {', 'void RasterizerVulkan::Clear(u32 layer_count) {\n    SCOPE_EXIT { SyncProbe(scheduler, "clear", nullptr); };'),
    ('    ComputePipeline* const pipeline{pipeline_cache.CurrentComputePipeline()};\n    if (!pipeline) {\n        return;\n    }',
     '    ComputePipeline* const pipeline{pipeline_cache.CurrentComputePipeline()};\n    if (!pipeline) {\n        return;\n    }\n'
     '    SCOPE_EXIT { SyncProbe(scheduler, "dispatch", pipeline); };'),
    # Dynamic vertex input: a stream with instancing on and frequency 0 advances per vertex, as the
    # pipeline's static vertex input (binding_divisors) and OpenGL's divisor 0 take it. Here it was
    # an instance-rate binding with divisor 0, every vertex reading element 0: geometry collapsed
    # (objects vanishing for a frame, a whole scene drawn as one flat colour).
    ('        const bool is_instanced{regs.vertex_stream_instances.IsInstancingEnabled(binding)};\n',
     '        const bool is_instanced{regs.vertex_stream_instances.IsInstancingEnabled(binding) &&\n'
     '                                input_binding.frequency != 0};\n'),
    ("    gpu_memory->FlushCaching();\n\n    ComputePipeline* const pipeline{pipeline_cache.CurrentComputePipeline()};",
     "    gpu_memory->FlushCaching();\n#ifdef PS5_NATIVE\n    // Compute Configure runs under both guest cache locks. Drain the common\n    // descriptor queue overflow BEFORE taking those locks, exactly as Draw.\n    // The GPU worker may publish guest invalidations while it drains.\n    if (guest_descriptor_queue.PreflightGuestDraw([this] { scheduler.WaitWorker(); })) {\n        gpu_memory->FlushCaching();\n    }\n#endif\n\n    ComputePipeline* const pipeline{pipeline_cache.CurrentComputePipeline()};"),

    ("    ComputePipeline* const pipeline{pipeline_cache.CurrentComputePipeline()};\n    if (!pipeline) {\n        return;\n    }\n    SCOPE_EXIT { SyncProbe(scheduler, \"dispatch\", pipeline); };\n    std::scoped_lock lock{texture_cache.mutex, buffer_cache.mutex};",
     "    ComputePipeline* pipeline{pipeline_cache.CurrentComputePipeline()};\n    if (!pipeline) {\n        return;\n    }\n#ifdef PS5_NATIVE\n    // Compute always allocates new descriptor-buffer space for a dispatch.\n    // Drain only necessary GPU fences while neither guest cache is locked.\n    // Worker drains can publish guest shader/descriptor invalidations.\n    for (unsigned preflight = 0; preflight != 2; ++preflight) {\n        // No preceding worker drain means neither the descriptor cursor nor\n        // the selected shader changed since the first exact-capacity probe.\n        if (preflight == 0 && !initial_compute_descriptor_drain) break;\n        if (!pipeline->HasDescriptorEntries() ||\n            !guest_descriptor_queue.PreflightExactGuestDraw(\n                [this] { scheduler.WaitWorker(); }, pipeline->DescriptorEntryReservation()))\n            break;\n        gpu_memory->FlushCaching();\n        pipeline = pipeline_cache.CurrentComputePipeline();\n        if (!pipeline) return;\n    }\n    if (pipeline->CanUseDescriptorBuffer() &&\n        descriptor_buffer_ring.PreflightFrameReuse(scheduler)) {\n        gpu_memory->FlushCaching();\n        pipeline = pipeline_cache.CurrentComputePipeline();\n        if (!pipeline) return;\n        if (pipeline->HasDescriptorEntries() &&\n            guest_descriptor_queue.PreflightExactGuestDraw(\n                [this] { scheduler.WaitWorker(); }, pipeline->DescriptorEntryReservation())) {\n            gpu_memory->FlushCaching();\n            pipeline = pipeline_cache.CurrentComputePipeline();\n            if (!pipeline) return;\n        }\n    }\n    if (descriptor_buffer_ring.PreflightCapacity(\n            scheduler, pipeline->DescriptorRingPreflightSize())) {\n        gpu_memory->FlushCaching();\n        pipeline = pipeline_cache.CurrentComputePipeline();\n        if (!pipeline) return;\n        if (pipeline->HasDescriptorEntries() &&\n            guest_descriptor_queue.PreflightExactGuestDraw(\n                [this] { scheduler.WaitWorker(); }, pipeline->DescriptorEntryReservation())) {\n            gpu_memory->FlushCaching();\n            pipeline = pipeline_cache.CurrentComputePipeline();\n            if (!pipeline) return;\n        }\n    }\n#endif\n    SCOPE_EXIT { SyncProbe(scheduler, \"dispatch\", pipeline); };\n    std::scoped_lock lock{texture_cache.mutex, buffer_cache.mutex};"),
])
# Host conditional rendering (VK_EXT_conditional_rendering, dev_vulkan.h hcr_mode): count each
# decision (EDEN_DEV_GUEST cond= slots 13-19); hcr=exact sends the conditions Eden would draw
# unconditionally, or predicate from a pending host query, to the exact CPU evaluation;
# hcr=cpu evaluates every condition on the CPU and predicates from constant 0/1 buffers.
# Reuse the insertion result instead of hashing the TFB bank twice per query.
tfb_sync_edits = [('            sync_values_stash.try_emplace(query->start_bank_id);\n            sync_values_stash[query->start_bank_id].emplace_back(HostSyncValues{', '            auto& bank_values = sync_values_stash.try_emplace(query->start_bank_id).first->second;\n            bank_values.emplace_back(HostSyncValues{')]
# Preserve the two samples result-vector allocations across completed batches.
samples_recycle_edits = [('        sync_values_stash.clear();\n    }\n\n    void PresyncWrites() override {', '        RecycleSyncValues();\n    }\n\n    void PresyncWrites() override {'), ('            pending_sync.clear();\n            sync_values_stash.clear();\n            return;', '            pending_sync.clear();\n            RecycleSyncValues();\n            return;'), ('        sync_values_stash.clear();\n        sync_values_stash.emplace_back();', '        RecycleSyncValues();\n        sync_values_stash.emplace_back();'), ('        sync_values_stash.emplace_back();\n        std::vector<HostSyncValues>* sync_values', '        sync_values_stash.emplace_back().swap(sync_values_cache[0]);\n        std::vector<HostSyncValues>* sync_values'), ('                    sync_values_stash.emplace_back();', '                    sync_values_stash.emplace_back().swap(sync_values_cache[1]);'), ('private:\n    template <typename Func>', 'private:\n    // SyncValues copies result metadata into its own deferred command before\n    // returning. Keep the two producer vectors for the next batch instead of\n    // repeatedly freeing their backing allocations.\n    void RecycleSyncValues() {\n        ASSERT(sync_values_stash.size() <= sync_values_cache.size());\n        for (size_t i = 0; i < sync_values_stash.size(); ++i) {\n            sync_values_stash[i].swap(sync_values_cache[i]);\n            sync_values_cache[i].clear();\n        }\n        sync_values_stash.clear();\n    }\n\n    template <typename Func>'), ('    std::deque<std::vector<HostSyncValues>> sync_values_stash;', '    std::deque<std::vector<HostSyncValues>> sync_values_stash;\n    std::array<std::vector<HostSyncValues>, 2> sync_values_cache;')]
adapt('src/video_core/renderer_vulkan/vk_query_cache.cpp', 'vulkan_query_cache.cpp', [
    ('        sync_values->reserve(num_slots_used);',
     '        // A pending query contributes at most one result. Cap the slot-based\n'
     '        // estimate without enlarging it when many queries share a few slots.\n'
     '        sync_values->reserve((std::min)(num_slots_used, pending_sync.size()));'),
    # Page-spanning query results require a complete and overflow-checked destination span.
    ("#include <cstddef>\n#include <limits>", "#include <algorithm>\n#include <cstddef>\n#include <limits>"),
    ("#include <span>\n#include <type_traits>", "#include <span>\n#include <stdexcept>\n#include <type_traits>"),
    ("        total_size += sync_val.size;\n        bool found = false;\n        DAddr base = Common::AlignDown(sync_val.address, Core::DEVICE_PAGESIZE);\n        DAddr base_end = base + Core::DEVICE_PAGESIZE;", "        if (sync_val.size == 0 ||\n            sync_val.size > std::numeric_limits<DAddr>::max() - sync_val.address ||\n            sync_val.size > std::numeric_limits<size_t>::max() - total_size) {\n            throw std::overflow_error(\"Query sync value range overflow\");\n        }\n        total_size += sync_val.size;\n        bool found = false;\n        const DAddr base = Common::AlignDown(sync_val.address, Core::DEVICE_PAGESIZE);\n        // A query result may straddle a device-memory page. ObtainCPUBuffer\n        // must cover the complete value, not only the page containing its start.\n        const DAddr last_page = Common::AlignDown(\n            sync_val.address + sync_val.size - 1, Core::DEVICE_PAGESIZE);\n        if (last_page > std::numeric_limits<DAddr>::max() - Core::DEVICE_PAGESIZE) {\n            throw std::overflow_error(\"Query sync page end overflow\");\n        }\n        const DAddr base_end = last_page + Core::DEVICE_PAGESIZE;"),
    ("            if (base < loc.second && loc.first < base_end) {\n                set_found();", "            if (base < loc.second && loc.first < base_end) {\n                loc.first = (std::min)(loc.first, base);\n                loc.second = (std::max)(loc.second, base_end);\n                set_found();"),
    ("        if (!found) {\n            impl->redirect_cache.push_back(impl->little_cache.size());\n            impl->little_cache.emplace_back(base, base_end);\n        }\n    }\n\n    // Vulkan part.", "        if (!found) {\n            impl->redirect_cache.push_back(impl->little_cache.size());\n            impl->little_cache.emplace_back(base, base_end);\n        }\n    }\n    // ObtainCPUBuffer takes a u32 length. Never truncate a combined page\n    // span to a shorter buffer and then record copies beyond its end.\n    for (const auto& range : impl->little_cache) {\n        if (range.second - range.first > std::numeric_limits<u32>::max()) {\n            throw std::overflow_error(\"Query sync buffer span exceeds u32\");\n        }\n    }\n\n    // Vulkan part."),
    # Sort query indices and merge spans while preserving original copy order.
    ('    impl->redirect_cache.clear();\n    impl->little_cache.clear();\n    size_t total_size = 0;\n    for (auto& sync_val : values) {\n        if (sync_val.size == 0 ||\n            sync_val.size > std::numeric_limits<DAddr>::max() - sync_val.address ||\n            sync_val.size > std::numeric_limits<size_t>::max() - total_size) {\n            throw std::overflow_error("Query sync value range overflow");\n        }\n        total_size += sync_val.size;\n        bool found = false;\n        const DAddr base = Common::AlignDown(sync_val.address, Core::DEVICE_PAGESIZE);\n        // A query result may straddle a device-memory page. ObtainCPUBuffer\n        // must cover the complete value, not only the page containing its start.\n        const DAddr last_page = Common::AlignDown(\n            sync_val.address + sync_val.size - 1, Core::DEVICE_PAGESIZE);\n        if (last_page > std::numeric_limits<DAddr>::max() - Core::DEVICE_PAGESIZE) {\n            throw std::overflow_error("Query sync page end overflow");\n        }\n        const DAddr base_end = last_page + Core::DEVICE_PAGESIZE;\n        for (size_t i = 0; i < impl->little_cache.size(); i++) {\n            const auto set_found = [&] {\n                impl->redirect_cache.push_back(i);\n                found = true;\n            };\n            auto& loc = impl->little_cache[i];\n            if (base < loc.second && loc.first < base_end) {\n                loc.first = (std::min)(loc.first, base);\n                loc.second = (std::max)(loc.second, base_end);\n                set_found();\n                break;\n            }\n            if (loc.first == base_end) {\n                loc.first = base;\n                set_found();\n                break;\n            }\n            if (loc.second == base) {\n                loc.second = base_end;\n                set_found();\n                break;\n            }\n        }\n        if (!found) {\n            impl->redirect_cache.push_back(impl->little_cache.size());\n            impl->little_cache.emplace_back(base, base_end);\n        }\n    }\n', '    impl->redirect_cache.clear();\n    impl->redirect_cache.resize(values.size());\n    impl->little_cache.clear();\n    impl->sync_order.resize(values.size());\n    size_t total_size = 0;\n    for (size_t i = 0; i < values.size(); ++i) {\n        const auto& sync_val = values[i];\n        if (sync_val.size == 0 ||\n            sync_val.size > std::numeric_limits<DAddr>::max() - sync_val.address ||\n            sync_val.size > std::numeric_limits<size_t>::max() - total_size) {\n            throw std::overflow_error("Query sync value range overflow");\n        }\n        total_size += sync_val.size;\n        impl->sync_order[i] = i;\n    }\n    // Sort indices, not values: copies retain the original query order.\n    // Separated pages otherwise require a quadratic scan of earlier groups.\n    const auto by_page = [&](size_t a, size_t b) {\n        return Common::AlignDown(values[a].address, Core::DEVICE_PAGESIZE) <\n               Common::AlignDown(values[b].address, Core::DEVICE_PAGESIZE);\n    };\n    // Monotonic pages, including arbitrary addresses within one page, need\n    // only a linear scan. Sort only batches whose page order differs.\n    if (!std::is_sorted(impl->sync_order.begin(), impl->sync_order.end(), by_page)) {\n        std::sort(impl->sync_order.begin(), impl->sync_order.end(), by_page);\n    }\n    for (const size_t i : impl->sync_order) {\n        const auto& sync_val = values[i];\n        const DAddr base = Common::AlignDown(sync_val.address, Core::DEVICE_PAGESIZE);\n        const DAddr last_page = Common::AlignDown(\n            sync_val.address + sync_val.size - 1, Core::DEVICE_PAGESIZE);\n        if (last_page > std::numeric_limits<DAddr>::max() - Core::DEVICE_PAGESIZE) {\n            throw std::overflow_error("Query sync page end overflow");\n        }\n        const DAddr base_end = last_page + Core::DEVICE_PAGESIZE;\n        if (impl->little_cache.empty() || impl->little_cache.back().second < base) {\n            impl->little_cache.emplace_back(base, base_end);\n        } else {\n            // Sorted starts make the last group the only possible match,\n            // including a result connecting two formerly separate groups.\n            auto& loc = impl->little_cache.back();\n            loc.second = (std::max)(loc.second, base_end);\n        }\n        impl->redirect_cache[i] = impl->little_cache.size() - 1;\n    }\n'),
    ('    std::vector<size_t> redirect_cache;\n', '    std::vector<size_t> redirect_cache;\n    std::vector<size_t> sync_order;\n'),
    # Allocate query destination metadata before the contended cache mutex.
    ('    // Vulkan part.\n    std::scoped_lock lk(impl->buffer_cache.mutex);\n    impl->buffer_cache.BufferOperations([&] {\n        impl->buffers_to_upload_to.clear();', '    // Vulkan part.\n    // The recorded command takes this vector each call. Reserve the known\n    // range count before locking, avoiding geometric growth under the mutex.\n    impl->buffers_to_upload_to.clear();\n    impl->buffers_to_upload_to.reserve(impl->little_cache.size());\n    std::scoped_lock lk(impl->buffer_cache.mutex);\n    impl->buffer_cache.BufferOperations([&] {'),
    # Predicate inversion is part of the cached conditional-render state.
    ("    if (impl->hcr_is_set) {\n        if (impl->hcr_setup.buffer == impl->hcr_buffer &&\n            impl->hcr_setup.offset == impl->hcr_offset) {\n            return;\n        }\n    }", "    // The same predicate buffer can be reused with inverted comparison.\n    // A changed comparison must re-record the conditional rendering state.\n    const VkConditionalRenderingFlagsEXT flags =\n        is_equal ? VK_CONDITIONAL_RENDERING_INVERTED_BIT_EXT : 0;\n    if (impl->hcr_is_set) {\n        if (impl->hcr_setup.buffer == impl->hcr_buffer &&\n            impl->hcr_setup.offset == impl->hcr_offset &&\n            impl->hcr_setup.flags == flags) {\n            return;\n        }\n    }"),
    ("    impl->hcr_setup.flags = is_equal ? VK_CONDITIONAL_RENDERING_INVERTED_BIT_EXT : 0;", "    impl->hcr_setup.flags = flags;"),
    # Upstream Eden #4499: UpdateBuffers here can change the TFB counter
    # buffer count after BeginTransformFeedbackEXT has already recorded it.
    # Keep the existing refresh in FlushBeginTFB only.
    ('        // Refresh buffer state before ending transform feedback to ensure counters_count is up-to-date.\n'
     '        UpdateBuffers();\n', ''),
    ('#include "video_core/vulkan_common/vulkan_wrapper.h"\n',
     '#include "video_core/vulkan_common/vulkan_wrapper.h"\n#include "dev_vulkan.h"\n#include "performance.h"\n'),
    ('    vk::Buffer hcr_resolve_buffer;\n',
     '    vk::Buffer hcr_resolve_buffer;\n    vk::Buffer hcr_constant_buffer; // hcr=cpu: predicates 0 and 1\n'),
    ('        hcr_resolve_buffer = memory_allocator.CreateBuffer(buffer_ci, MemoryUsage::DeviceLocal);\n    }\n',
     '''        hcr_resolve_buffer = memory_allocator.CreateBuffer(buffer_ci, MemoryUsage::DeviceLocal);
        if (device.IsExtConditionalRendering() && ::Eden::DevVulkan::hcr_mode == 2) {
            VkBufferCreateInfo constant_ci = buffer_ci;
            constant_ci.size = 2 * sizeof(u32);
            constant_ci.usage = VK_BUFFER_USAGE_CONDITIONAL_RENDERING_BIT_EXT;
            hcr_constant_buffer = memory_allocator.CreateBuffer(constant_ci, MemoryUsage::Upload);
            const u32 predicates[2]{0, 1};
            std::memcpy(hcr_constant_buffer.Mapped().data(), predicates, sizeof(predicates));
            hcr_constant_buffer.Flush();
        }
    }
'''),
    ('''bool QueryCacheRuntime::HostConditionalRenderingCompareValue(VideoCommon::LookupData object_1,
                                                             [[maybe_unused]] bool qc_dirty) {
    if (!impl->device.IsExtConditionalRendering()) {
        return false;
    }
    HostConditionalRenderingCompareBCImpl(object_1.address, true, true);
    return true;
}''',
     '''namespace {
// hcr=cpu: Maxwell3D::ProcessQueryCondition's exact evaluation (the read flushes pending GPU
// results), then the driver predicates the draws from a constant buffer. kind: 0 Conditional,
// 1 IfEqual, 2 IfNotEqual.
bool HostConditionalRenderingOnCpu(QueryCacheRuntime& runtime, QueryCacheRuntimeImpl& impl, DAddr address,
                                   unsigned kind) {
    if (address == 0 || !impl.hcr_constant_buffer) {
        ::Eden::Performance::CountCondition(13);
        runtime.EndHostConditionalRendering();
        return false;
    }
    u32 compare[6]{};
    impl.device_memory.ReadBlock(address, compare, sizeof(compare));
    const bool equal = compare[0] == compare[4] && compare[1] == compare[5];
    const bool execute = kind == 0 ? compare[0] != 0 && compare[1] != 0 : (kind == 1 ? equal : !equal);
    ::Eden::Performance::CountCondition(execute ? 17 : 18);
    const bool was_running = impl.is_hcr_running;
    if (was_running) {
        runtime.PauseHostConditionalRendering();
    }
    impl.hcr_setup.buffer = *impl.hcr_constant_buffer;
    impl.hcr_setup.offset = execute ? sizeof(u32) : 0;
    impl.hcr_setup.flags = 0;
    impl.hcr_is_set = true;
    impl.is_hcr_running = false;
    if (was_running) {
        runtime.ResumeHostConditionalRendering();
    }
    return true;
}
} // namespace

bool QueryCacheRuntime::HostConditionalRenderingCompareValue(VideoCommon::LookupData object_1,
                                                             [[maybe_unused]] bool qc_dirty) {
    if (!impl->device.IsExtConditionalRendering()) {
        return false;
    }
    if (::Eden::DevVulkan::hcr_mode == 2) {
        return HostConditionalRenderingOnCpu(*this, *impl, object_1.address, 0);
    }
    if (::Eden::DevVulkan::hcr_mode == 1 && qc_dirty) {
        ::Eden::Performance::CountCondition(19);
        EndHostConditionalRendering();
        return false;
    }
    ::Eden::Performance::CountCondition(16);
    HostConditionalRenderingCompareBCImpl(object_1.address, true, true);
    return true;
}'''),
    ('''    if (!impl->device.IsExtConditionalRendering()) {
        return false;
    }

    const auto check_in_bc = [&](DAddr address) {''',
     '''    if (!impl->device.IsExtConditionalRendering()) {
        return false;
    }
    if (::Eden::DevVulkan::hcr_mode == 2) {
        return HostConditionalRenderingOnCpu(*this, *impl, object_1.address, equal_check ? 1 : 2);
    }

    const auto check_in_bc = [&](DAddr address) {'''),
    ('''    if (!is_in_ac[0] && !is_in_ac[1]) {
        EndHostConditionalRendering();
        return false;
    }

    if (!qc_dirty && !is_in_bc[0] && !is_in_bc[1]) {
        EndHostConditionalRendering();
        return false;
    }
''',
     '''    if (!is_in_ac[0] && !is_in_ac[1]) {
        ::Eden::Performance::CountCondition(13);
        EndHostConditionalRendering();
        return false;
    }

    if (!qc_dirty && !is_in_bc[0] && !is_in_bc[1]) {
        ::Eden::Performance::CountCondition(13);
        EndHostConditionalRendering();
        return false;
    }
    // hcr=exact: a pending host query is not in any buffer yet; the CPU evaluation waits for it.
    if (::Eden::DevVulkan::hcr_mode == 1 && qc_dirty) {
        ::Eden::Performance::CountCondition(19);
        EndHostConditionalRendering();
        return false;
    }
'''),
    ('''            HostConditionalRenderingCompareValueImpl(*objects[j], equal_check);
            return true;''',
     '''            ::Eden::Performance::CountCondition(15);
            HostConditionalRenderingCompareValueImpl(*objects[j], equal_check);
            return true;'''),
    ('''    if (!is_gpu_high) {
        EndHostConditionalRendering();
        return true;
    }

    if (!is_in_bc[0] && !is_in_bc[1]) {
        EndHostConditionalRendering();
        return true;
    }
    HostConditionalRenderingCompareBCImpl(object_1.address, equal_check);''',
     '''    // Eden draws these unconditionally; hcr=exact evaluates them on the CPU instead.
    if (!is_gpu_high || (!is_in_bc[0] && !is_in_bc[1])) {
        ::Eden::Performance::CountCondition(14);
        EndHostConditionalRendering();
        return ::Eden::DevVulkan::hcr_mode != 1;
    }
    ::Eden::Performance::CountCondition(16);
    HostConditionalRenderingCompareBCImpl(object_1.address, equal_check);'''),
    # Flat query-copy storage and outside-lock upload preparation.
    ('    std::vector<std::vector<VkBufferCopy>> copies_setup;', '    std::vector<VkBufferCopy> copies_setup;\n    std::vector<size_t> copy_offsets;\n    std::vector<size_t> copy_cursors;'),
    ('    // Vulkan part.\n    // The recorded command takes this vector each call. Reserve the known\n    // range count before locking, avoiding geometric growth under the mutex.\n    impl->buffers_to_upload_to.clear();\n    impl->buffers_to_upload_to.reserve(impl->little_cache.size());\n    std::scoped_lock lk(impl->buffer_cache.mutex);\n    impl->buffer_cache.BufferOperations([&] {\n        for (auto& pair : impl->little_cache) {\n            static constexpr auto sync_info = VideoCommon::ObtainBufferSynchronize::FullSynchronize;\n            const auto post_op = VideoCommon::ObtainBufferOperation::DoNothing;\n            const auto [buffer, offset] = impl->buffer_cache.ObtainCPUBuffer(\n                pair.first, static_cast<u32>(pair.second - pair.first), sync_info, post_op);\n            impl->buffers_to_upload_to.emplace_back(buffer->Handle(), offset);\n        }\n    });\n\n    VkBuffer src_buffer;\n    [[maybe_unused]] StagingBufferRef ref;\n    impl->copies_setup.clear();\n    impl->copies_setup.resize(impl->little_cache.size());\n    if constexpr (SyncValuesType::GeneratesBaseBuffer) {\n        ref = impl->staging_pool.Request(total_size, MemoryUsage::Upload);\n        size_t current_offset = ref.offset;\n        size_t accumulated_size = 0;\n        for (size_t i = 0; i < values.size(); i++) {\n            size_t which_copy = impl->redirect_cache[i];\n            impl->copies_setup[which_copy].emplace_back(VkBufferCopy{\n                .srcOffset = current_offset + accumulated_size,\n                .dstOffset = impl->buffers_to_upload_to[which_copy].second + values[i].address -\n                             impl->little_cache[which_copy].first,\n                .size = values[i].size,\n            });\n            std::memcpy(ref.mapped_span.data() + accumulated_size, &values[i].value,\n                        values[i].size);\n            accumulated_size += values[i].size;\n        }\n        src_buffer = ref.buffer;\n    } else {\n        for (size_t i = 0; i < values.size(); i++) {\n            size_t which_copy = impl->redirect_cache[i];\n            impl->copies_setup[which_copy].emplace_back(VkBufferCopy{\n                .srcOffset = values[i].offset,\n                .dstOffset = impl->buffers_to_upload_to[which_copy].second + values[i].address -\n                             impl->little_cache[which_copy].first,\n                .size = values[i].size,\n            });\n        }\n        src_buffer = base_src_buffer;\n    }\n\n    impl->scheduler.RequestOutsideRenderPassOperationContext();\n    impl->scheduler.Record([src_buffer, dst_buffers = std::move(impl->buffers_to_upload_to), vk_copies = std::move(impl->copies_setup)](vk::CommandBuffer cmdbuf) {\n        size_t size = dst_buffers.size();\n        for (size_t i = 0; i < size; i++) {\n            cmdbuf.CopyBuffer(src_buffer, dst_buffers[i].first, vk_copies[i]);\n        }\n    });', '    // Prepare all query metadata before taking the buffer cache mutex.\n    // One flat copy array replaces one allocation per destination group.\n    const size_t groups = impl->little_cache.size();\n    impl->copy_cursors.assign(groups, 0);\n    for (const size_t group : impl->redirect_cache) {\n        ++impl->copy_cursors[group];\n    }\n    impl->copy_offsets.resize(groups + 1);\n    size_t next_copy = 0;\n    for (size_t group = 0; group < groups; ++group) {\n        impl->copy_offsets[group] = next_copy;\n        const size_t count = impl->copy_cursors[group];\n        impl->copy_cursors[group] = next_copy;\n        next_copy += count;\n    }\n    impl->copy_offsets[groups] = next_copy;\n    impl->copies_setup.resize(values.size());\n\n    // Vulkan part.\n    // Keep buffers protected through recording. Metadata storage grows above;\n    // staging retains its original tick ownership AFTER buffer consolidation.\n    impl->buffers_to_upload_to.clear();\n    impl->buffers_to_upload_to.reserve(groups);\n    std::scoped_lock lk(impl->buffer_cache.mutex);\n    impl->buffer_cache.BufferOperations([&] {\n        // BufferOperations retries when a merge invalidates earlier handles.\n        impl->buffers_to_upload_to.clear();\n        for (auto& pair : impl->little_cache) {\n            static constexpr auto sync_info = VideoCommon::ObtainBufferSynchronize::FullSynchronize;\n            const auto post_op = VideoCommon::ObtainBufferOperation::DoNothing;\n            const auto [buffer, offset] = impl->buffer_cache.ObtainCPUBuffer(\n                pair.first, static_cast<u32>(pair.second - pair.first), sync_info, post_op);\n            impl->buffers_to_upload_to.emplace_back(buffer->Handle(), offset);\n        }\n    });\n\n    VkBuffer src_buffer = base_src_buffer;\n    [[maybe_unused]] StagingBufferRef ref;\n    if constexpr (SyncValuesType::GeneratesBaseBuffer) {\n        ref = impl->staging_pool.Request(total_size, MemoryUsage::Upload);\n        src_buffer = ref.buffer;\n    }\n    [[maybe_unused]] size_t accumulated_size = 0;\n    for (size_t i = 0; i < values.size(); ++i) {\n        const size_t group = impl->redirect_cache[i];\n        VkDeviceSize source_offset;\n        if constexpr (SyncValuesType::GeneratesBaseBuffer) {\n            source_offset = ref.offset + accumulated_size;\n            if (values[i].size == sizeof(values[i].value)) {\n                std::memcpy(ref.mapped_span.data() + accumulated_size, &values[i].value,\n                            sizeof(values[i].value));\n            } else {\n                std::memcpy(ref.mapped_span.data() + accumulated_size, &values[i].value,\n                            values[i].size);\n            }\n            accumulated_size += values[i].size;\n        } else {\n            source_offset = values[i].offset;\n        }\n        impl->copies_setup[impl->copy_cursors[group]++] = VkBufferCopy{\n            .srcOffset = source_offset,\n            .dstOffset = impl->buffers_to_upload_to[group].second + values[i].address -\n                         impl->little_cache[group].first,\n            .size = values[i].size,\n        };\n    }\n\n    impl->scheduler.RequestOutsideRenderPassOperationContext();\n    impl->scheduler.Record([src_buffer, dst_buffers = std::move(impl->buffers_to_upload_to),\n                            vk_copies = std::move(impl->copies_setup),\n                            copy_offsets = std::move(impl->copy_offsets)](vk::CommandBuffer cmdbuf) {\n        const std::span<const VkBufferCopy> copies{vk_copies};\n        for (size_t i = 0; i < dst_buffers.size(); ++i) {\n            cmdbuf.CopyBuffer(src_buffer, dst_buffers[i].first,\n                             copies.subspan(copy_offsets[i], copy_offsets[i + 1] - copy_offsets[i]));\n        }\n    });'),
    *tfb_sync_edits,
    *samples_recycle_edits,
])

# R319: avoid descriptor-ring overflow waits while holding the paired guest
# buffer/texture cache mutexes. Only the graphics queue invokes this method.
# Normal draws add one cheap space check; overflow still waits using exactly
# scheduler.WaitWorker(), which was the original UpdateDescriptorQueue gate.
adapt('src/video_core/renderer_vulkan/vk_update_descriptor.h',
      'include/video_core/renderer_vulkan/vk_update_descriptor.h', [
    ('    void Acquire(Scheduler& scheduler, size_t required_entries = 0,\n'
     '                 bool use_descriptor_buffer_ = false);',
     '''    void Acquire(Scheduler& scheduler, size_t required_entries = 0,
                 bool use_descriptor_buffer_ = false);
#ifdef PS5_NATIVE
    // Exact zero-descriptor graphics pipeline: publish an empty payload
    // without the ordinary 1024-entry fallback reservation or GPU wait.
    // Acquire(0) keeps its legacy semantics for other callers.
    void AcquireKnownEmpty(bool use_descriptor_buffer_) noexcept {
        use_descriptor_buffer = supports_descriptor_buffer && use_descriptor_buffer_;
        upload_start = payload_cursor;
    }
    template <typename WaitWorker>
    [[nodiscard]] bool PreflightGuestDraw(WaitWorker&& wait_worker,
                                          size_t required_entries = 0x400) {
        // Preserve the old default for any other caller. Native draw/compute
        // supply the exact positive descriptor count passed to Acquire().
        const size_t reserve = required_entries != 0 ? required_entries : 0x400;
        if (reserve >= frame_payload_size)
            return false;
        const size_t used = static_cast<size_t>(payload_cursor - payload_start);
        if (used + reserve < frame_payload_size)
            return false;
        wait_worker();
        payload_cursor = payload_start;
        return true;
    }
    template <typename WaitWorker>
    [[nodiscard]] bool PreflightExactGuestDraw(WaitWorker&& wait_worker, size_t entries) {
        // Match Acquire(required_entries) for every nonempty pipeline,
        // including fewer than 1024 descriptors after a worker-triggered
        // shader reselect. Zero-descriptor pipelines must skip this helper.
        if (entries == 0 || entries >= frame_payload_size)
            return false;
        const size_t used = static_cast<size_t>(payload_cursor - payload_start);
        if (used + entries < frame_payload_size)
            return false;
        wait_worker();
        payload_cursor = payload_start;
        return true;
    }
#endif'''),
    ("#include <variant>",
     "#ifdef PS5_NATIVE\n#include <cstring>\n#endif\n#include <variant>"),
    ("    void AddSampledImage(VkImageView image_view, VkSampler sampler) {\n        *(payload_cursor++) = VkDescriptorImageInfo{\n            .sampler = sampler,\n            .imageView = image_view,\n            .imageLayout = VK_IMAGE_LAYOUT_GENERAL,\n        };\n    }\n\n",
     "    void AddSampledImage(VkImageView image_view, VkSampler sampler) {\n#ifdef PS5_NATIVE\n        if (use_descriptor_buffer) {\n            // Descriptor-buffer reuse compares raw entries. Fully initialize\n            // inactive union bytes and struct padding, not only Vulkan fields.\n            auto* const entry = payload_cursor++;\n            std::memset(entry, 0, sizeof(*entry));\n            entry->image.sampler = sampler;\n            entry->image.imageView = image_view;\n            entry->image.imageLayout = VK_IMAGE_LAYOUT_GENERAL;\n            return;\n        }\n#endif\n        *(payload_cursor++) = VkDescriptorImageInfo{\n            .sampler = sampler,\n            .imageView = image_view,\n            .imageLayout = VK_IMAGE_LAYOUT_GENERAL,\n        };\n    }\n\n"),
    ("    void AddImage(VkImageView image_view) {\n        *(payload_cursor++) = VkDescriptorImageInfo{\n            .sampler = VK_NULL_HANDLE,\n            .imageView = image_view,\n            .imageLayout = VK_IMAGE_LAYOUT_GENERAL,\n        };\n    }\n\n",
     "    void AddImage(VkImageView image_view) {\n#ifdef PS5_NATIVE\n        if (use_descriptor_buffer) {\n            auto* const entry = payload_cursor++;\n            std::memset(entry, 0, sizeof(*entry));\n            entry->image.sampler = VK_NULL_HANDLE;\n            entry->image.imageView = image_view;\n            entry->image.imageLayout = VK_IMAGE_LAYOUT_GENERAL;\n            return;\n        }\n#endif\n        *(payload_cursor++) = VkDescriptorImageInfo{\n            .sampler = VK_NULL_HANDLE,\n            .imageView = image_view,\n            .imageLayout = VK_IMAGE_LAYOUT_GENERAL,\n        };\n    }\n\n"),
    ("    void AddBuffer(VkBuffer buffer, VkDeviceAddress base_address, VkDeviceSize offset,\n                   VkDeviceSize size) {\n        if (!use_descriptor_buffer) {\n            AddBuffer(buffer, offset, size);\n            return;\n        }\n        *(payload_cursor++) = DescriptorAddress{\n            .address = base_address == 0 ? 0 : base_address + offset,\n            .range = base_address == 0 ? VK_WHOLE_SIZE : size,\n            .format = VK_FORMAT_UNDEFINED,\n        };\n    }\n\n",
     "    void AddBuffer(VkBuffer buffer, VkDeviceAddress base_address, VkDeviceSize offset,\n                   VkDeviceSize size) {\n        if (!use_descriptor_buffer) {\n            AddBuffer(buffer, offset, size);\n            return;\n        }\n#ifdef PS5_NATIVE\n        auto* const entry = payload_cursor++;\n        std::memset(entry, 0, sizeof(*entry));\n        entry->address.address = base_address == 0 ? 0 : base_address + offset;\n        entry->address.range = base_address == 0 ? VK_WHOLE_SIZE : size;\n        entry->address.format = VK_FORMAT_UNDEFINED;\n#else\n        *(payload_cursor++) = DescriptorAddress{\n            .address = base_address == 0 ? 0 : base_address + offset,\n            .range = base_address == 0 ? VK_WHOLE_SIZE : size,\n            .format = VK_FORMAT_UNDEFINED,\n        };\n#endif\n    }\n\n"),
    ("    void AddTexelBuffer(VkBufferView texel_buffer, VkDeviceAddress base_address,\n                        VkDeviceSize offset, VkDeviceSize size, VkFormat format) {\n        if (!use_descriptor_buffer) {\n            AddTexelBuffer(texel_buffer);\n            return;\n        }\n        *(payload_cursor++) = DescriptorAddress{\n            .address = base_address == 0 ? 0 : base_address + offset,\n            .range = base_address == 0 ? VK_WHOLE_SIZE : size,\n            .format = format,\n        };\n    }\n",
     "    void AddTexelBuffer(VkBufferView texel_buffer, VkDeviceAddress base_address,\n                        VkDeviceSize offset, VkDeviceSize size, VkFormat format) {\n        if (!use_descriptor_buffer) {\n            AddTexelBuffer(texel_buffer);\n            return;\n        }\n#ifdef PS5_NATIVE\n        auto* const entry = payload_cursor++;\n        std::memset(entry, 0, sizeof(*entry));\n        entry->address.address = base_address == 0 ? 0 : base_address + offset;\n        entry->address.range = base_address == 0 ? VK_WHOLE_SIZE : size;\n        entry->address.format = format;\n#else\n        *(payload_cursor++) = DescriptorAddress{\n            .address = base_address == 0 ? 0 : base_address + offset,\n            .range = base_address == 0 ? VK_WHOLE_SIZE : size,\n            .format = format,\n        };\n#endif\n    }\n"),
])

adapt('src/video_core/renderer_vulkan/vk_swapchain.cpp', 'vulkan_swapchain.cpp', [
    # A single VkQueue requires host external synchronization; two distinct
    # queue *families* do not. Avoid holding the graphics submit lock over a
    # potentially blocking WSI call only when the handles are provably distinct.
    ('    std::scoped_lock lock{scheduler.submit_mutex};\n'
     '    switch (const VkResult result = present_queue.Present(present_info)) {',
     '    // Host queue external synchronization is per VkQueue, not per VkDevice.\n'
     '    // Different queue families use distinct handles: do not delay GPU\n'
     '    // submissions behind a blocked WSI present on an independent queue.\n'
     '    // When the families match, both handles refer to queue index zero and\n'
     '    // MUST still share the same mutex for Vulkan correctness.\n'
     '    std::unique_lock<std::mutex> lock{scheduler.submit_mutex, std::defer_lock};\n'
     '    if (device.GetGraphicsFamily() == device.GetPresentFamily()) lock.lock();\n'
     '    switch (const VkResult result = present_queue.Present(present_info)) {'),
    # PS5 native: a swapchain without a free image previously hung here
    # forever (UINT64_MAX). Timeouts are recoverable without touching the
    # image index or the signalled image-available semaphore.
    # 40 * 250ms is an upper bound, not a per-frame polling/logging loop.
    ('    const VkResult result = device.GetLogical().AcquireNextImageKHR(\n'
     '        *swapchain, (std::numeric_limits<u64>::max)(), *present_semaphores[frame_index],\n'
     '        VK_NULL_HANDLE, &image_index);',
     '''#ifdef PS5_NATIVE
    constexpr u64 kAcquireSliceNs = 250'000'000ULL;
    constexpr u32 kMaxAcquireTimeouts = 40;
    VkResult result = VK_TIMEOUT;
    for (u32 i = 0; i < kMaxAcquireTimeouts; ++i) {
        result = device.GetLogical().AcquireNextImageKHR(
            *swapchain, kAcquireSliceNs, *present_semaphores[frame_index],
            VK_NULL_HANDLE, &image_index);
        if (result != VK_TIMEOUT && result != VK_NOT_READY) {
            break;
        }
    }
    if (result == VK_TIMEOUT || result == VK_NOT_READY) {
        // Failed acquisition has no valid image and must not reach scheduler.Wait.
        // Propagate to the existing present_failure + launcher recovery path.
        throw vk::Exception(VK_TIMEOUT);
    }
#else
    const VkResult result = device.GetLogical().AcquireNextImageKHR(
        *swapchain, (std::numeric_limits<u64>::max)(), *present_semaphores[frame_index],
        VK_NULL_HANDLE, &image_index);
#endif'''),
    # VK_ERROR_OUT_OF_DATE_KHR does not acquire an image or signal the
    # semaphore. Never index resource_ticks[image_index] on this path.
    ('    case VK_SUBOPTIMAL_KHR:\n        is_suboptimal = true;\n        break;\n'
     '    case VK_ERROR_OUT_OF_DATE_KHR:\n        is_outdated = true;\n        break;',
     '    case VK_SUBOPTIMAL_KHR:\n        is_suboptimal = true;\n        break;\n'
     '    case VK_ERROR_OUT_OF_DATE_KHR:\n        is_outdated = true;\n        return true;'),
    # VK_SUBOPTIMAL_KHR DOES acquire an image and signals image_available.
    # Recreate on the following frame (NeedsRecreation), only AFTER submitting
    # the current image and consuming that signal. Do not rebuild a swapchain
    # while holding an acquired image or a still-signalled semaphore.
    ('    return is_suboptimal || is_outdated;\n}\n\nvoid Swapchain::Present(',
     '    return is_outdated;\n}\n\nvoid Swapchain::Present('),
    # An acquisition error has no usable image index. Forward it to the existing
    # renderer recovery path instead of indexing or presenting an invalid image.
    ('LOG_ERROR(Render_Vulkan, "vkAcquireNextImageKHR returned {}", string_VkResult(result));',
     'LOG_ERROR(Render_Vulkan, "vkAcquireNextImageKHR returned {}", string_VkResult(result));\n        vk::Check(result);'),
    ('LOG_CRITICAL(Render_Vulkan, "Failed to present with error {}", string_VkResult(result));',
     'LOG_CRITICAL(Render_Vulkan, "Failed to present with error {}", string_VkResult(result));\n        vk::Check(result);'),
])
# Keep the overlay in the existing display composition pass (also used for
# frontend screenshots), excluding guest applet captures. Cache its pipeline.
# Preserve upstream ABI, including consumers whose quoted includes resolve to
# the original header. Display/capture purpose belongs to the draw call.
adapt('src/video_core/present.h', 'include/video_core/present.h', [])
adapt('src/video_core/renderer_vulkan/vk_present_manager.h',
      'include/video_core/renderer_vulkan/vk_present_manager.h', [
    ('#include <mutex>', '#include <mutex>\n#include <exception>'),
    # R336: present worker can recreate swapchain while GPU renderer reads its metadata.
    ('#include <condition_variable>', '#include <atomic>\n#include <condition_variable>'),
    ('    [[nodiscard]] size_t MaxExtraFrames() const;',
     '    [[nodiscard]] size_t MaxExtraFrames() const;\n'
     '    [[nodiscard]] std::size_t SwapchainImageCount() const { return swapchain_image_count.load(); }\n'
     '    [[nodiscard]] VkFormat SwapchainImageFormat() const { return swapchain_image_format.load(); }\n'
     '    [[nodiscard]] VkFormat SwapchainImageViewFormat() const { return swapchain_image_view_format.load(); }'),
    ('    std::size_t image_count{};',
     '    std::atomic<std::size_t> image_count{};\n'
     '    std::atomic<std::size_t> swapchain_image_count{};\n'
     '    std::atomic<VkFormat> swapchain_image_format{};\n'
     '    std::atomic<VkFormat> swapchain_image_view_format{};'),
    ('    std::condition_variable_any frame_cv;',
     '    std::condition_variable_any frame_cv;\n'
     '    std::condition_variable_any present_ready_cv;'),
    ('    std::jthread present_thread;',
     '    bool present_in_flight{}; // guarded by queue_mutex\n'
     '    std::size_t present_waiters{}; // drain waiters, guarded by queue_mutex\n'
     '    std::exception_ptr present_failure;\n    std::jthread present_thread;'),
    # R335: declare frame abandonment on repeated surface loss.
    ('    void SetImageCount();',
     '    void DiscardFrame(Frame* frame);\n\n    void SetImageCount();'),
    ("    std::mutex free_mutex;",
     "    std::mutex free_mutex;\n    std::size_t free_waiters{}; // guarded by free_mutex"),
])
adapt('src/video_core/renderer_vulkan/vk_present_manager.cpp', 'vulkan_present_manager.cpp', [
    # R335: bounded recovery from VK_ERROR_SURFACE_LOST_KHR. Upstream #4509
    # October 8 2026 avoids a permanent while(true) Vulkan present loop.
    ('constexpr size_t MAX_FRAMES_IN_FLIGHT = 7;',
     'constexpr size_t MAX_FRAMES_IN_FLIGHT = 7;\nconstexpr u32 MAX_PRESENT_ATTEMPTS = 3;'),
    # Capture presenter-owned swapchain metadata without data races.
    ('    image_count = std::min<size_t>(swapchain.GetImageCount(), MAX_FRAMES_IN_FLIGHT);\n#endif',
     '    image_count = std::min<size_t>(swapchain.GetImageCount(), MAX_FRAMES_IN_FLIGHT);\n#endif\n'
     '    swapchain_image_count.store(swapchain.GetImageCount());\n'
     '    swapchain_image_format.store(swapchain.GetImageFormat());\n'
     '    swapchain_image_view_format.store(swapchain.GetImageViewFormat());'),
    ('void PresentManager::CopyToSwapchain(Frame* frame) {',
     '''void PresentManager::DiscardFrame(Frame* frame) {
    static constexpr VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT;
    const VkSemaphore render_ready = *frame->render_ready;
    const VkSubmitInfo submit_info{
        .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
        .pNext = nullptr,
        .waitSemaphoreCount = 1U,
        .pWaitSemaphores = &render_ready,
        .pWaitDstStageMask = &wait_stage,
        .commandBufferCount = 0U,
        .pCommandBuffers = nullptr,
        .signalSemaphoreCount = 0U,
        .pSignalSemaphores = nullptr,
    };
    std::scoped_lock submit_lock{scheduler.submit_mutex};
    void(device.GetGraphicsQueue().Submit(submit_info, *frame->present_done));
}

void PresentManager::CopyToSwapchain(Frame* frame) {'''),
    # R337: a *second* unbounded loop lives inside CopyToSwapchainImpl.
    # Repeated VK_SUBOPTIMAL_KHR / VK_ERROR_OUT_OF_DATE_KHR can cause endless
    # swapchain recreation even after R335 bounds outer surface-loss recovery.
    # Propagate through the existing outer retry/discard fence path instead.
    ('    while (swapchain.AcquireNextImage()) {\n        RecreateSwapchain(frame);\n    }',
     '    for (u32 acquire_attempt = 0; swapchain.AcquireNextImage(); ++acquire_attempt) {\n'
     '        if (acquire_attempt >= MAX_PRESENT_ATTEMPTS - 1) {\n'
     '            throw vk::Exception(VK_ERROR_SURFACE_LOST_KHR);\n'
     '        }\n'
     '        RecreateSwapchain(frame);\n'
     '    }'),
    ('    while (true) {\n        try {\n            // Recreate surface and swapchain if needed.',
     '    for (u32 attempt = 0; attempt < MAX_PRESENT_ATTEMPTS; ++attempt) {\n'
     '        try {\n            // Recreate surface and swapchain if needed.'),
    ('    }\n}\n\nvoid PresentManager::CopyToSwapchainImpl(Frame* frame) {',
     '    }\n    DiscardFrame(frame);\n}\n\nvoid PresentManager::CopyToSwapchainImpl(Frame* frame) {'),
    # R334: the existing RecreateFrame unconditionally assigns a new VkImage
    # while its previous VkFramebuffer and VkImageViews are still live.
    # Release dependents in Vulkan parent-child order before image replacement.
    ('    frame->image = memory_allocator.CreateImage({',
     '    frame->framebuffer = vk::Framebuffer{};\n'
     '    frame->storage_view = vk::ImageView{};\n'
     '    frame->image_view = vk::ImageView{};\n'
     '    frame->image = memory_allocator.CreateImage({'),
    # The upstream reset of storage_view after the new image_view is built
    # is now redundant: it is already released before the old VkImage.
    ('    frame->storage_view = vk::ImageView{};\n    if (storage_supported) {',
     '    if (storage_supported) {'),
    ('#include "video_core/renderer_vulkan/vk_present_manager.h"',
     '#include "video_core/renderer_vulkan/vk_present_manager.h"\n#include "gpu_failure.h"\n#include "performance.h"'),
    # GetRenderFrame runs on the GPU thread: time its free-frame and
    # present-completion waits (FIFO back-pressure on the producer).
    ('    // Wait for free presentation frames\n    std::unique_lock lock{free_mutex};',
     '    // Wait for free presentation frames\n    ::Eden::Performance::DiagnosticTimer present_wait_timer(::Eden::Performance::gpu_present_wait);\n    std::unique_lock lock{free_mutex};'),
    ('PresentThread(token);', '''try {
            PresentThread(token);
        } catch (...) {
            const auto error = std::current_exception();
            {
                std::scoped_lock lock{queue_mutex, free_mutex};
                present_failure = error;
                present_queue.clear();
                present_in_flight = false;
            }
            free_cv.notify_all();
            frame_cv.notify_all();
            Eden::RecordGpuFailure(error);
        }'''),
    ('free_cv.wait(lock, [this] { return !free_queue.empty(); });',
     '''free_cv.wait(lock, [this] { return present_failure || !free_queue.empty(); });
    if (present_failure) std::rethrow_exception(present_failure);'''),
    # Once dequeued, only GetRenderFrame owns this Frame until it returns.
    # Do not block PresentThread's free-queue handoff on a GPU fence wait.
    ('    free_queue.pop_front();',
     '    free_queue.pop_front();\n'
     '    // Exclusive ownership transferred to this caller. Let the present\n'
     '    // thread recycle OTHER frames during our Vulkan GPU fence wait.\n'
     '    lock.unlock();'),
    ('            present_queue.push_back(frame);',
     '            if (present_failure) return;\n            present_queue.push_back(frame);'),
    # The drain waiter and present worker have different predicates.
    # A dedicated CV avoids waking the drain on every frame enqueue.
    ('            present_queue.push_back(frame);\n            frame_cv.notify_one();',
     '            // The worker can sleep only with an empty queue. After the\n'
     '            // first frame wakes it, queued followers need no second wake.\n'
     '            // A worker copying a frame is not asleep, even with an empty queue.\n'
     '            // Test under queue_mutex to avoid losing an empty->nonempty edge.\n'
     '            const bool wake_presenter = present_queue.empty() && !present_in_flight;\n'
     '            present_queue.push_back(frame);\n'
     '            // Only the presentation worker waits on present_ready_cv.\n'
     '            // Avoid waking WaitPresent on every enqueue; it needs completion.\n'
     '            lock.unlock();\n'
     '            if (wake_presenter) present_ready_cv.notify_one();'),
    ('frame_cv.wait(lock, token, [this] { return !present_queue.empty(); });',
     'present_ready_cv.wait(lock, token, [this] { return !present_queue.empty(); });'),
    ('            // Take the frame and notify anyone waiting',
     '            // Take the frame; completion is signaled after the swapchain copy.'),
    ('            present_queue.pop_front();',
     '            present_queue.pop_front();\n            present_in_flight = true;'),
    # WaitPresent's predicate remains false after dequeue while the frame
    # is in flight; the early notify_one would only cause a spurious wake.
    ('            present_in_flight = true;\n            frame_cv.notify_one();',
     '            present_in_flight = true;'),
    ('            std::scoped_lock fl{free_mutex};\n'
     '            free_queue.push_back(frame);\n'
     '            free_cv.notify_one();',
     '            {\n'
     '                std::scoped_lock fl{free_mutex};\n'
     '                free_queue.push_back(frame);\n'
     '                free_cv.notify_one();\n'
     '            }\n'
     '            // Publish completion only AFTER presentation and frame handoff.\n'
     '            // Release swapchain mutex before reacquiring queue_mutex.\n'
     '            lock.unlock();\n'
     '            bool notify_drainers{};\n'
     '            {\n'
     '                std::lock_guard queue_lock{queue_mutex};\n'
     '                present_in_flight = false;\n'
     '                // A future WaitPresent sees an already idle queue under\n'
     '                // this same mutex; only the final queued completion can\n'
     '                // satisfy a drain waiter. Backlog wakes are wasted.\n'
     '                notify_drainers = present_waiters != 0 && present_queue.empty();\n'
     '            }\n'
     '            if (notify_drainers) frame_cv.notify_all();'),
    # Release free_mutex before waking the producer of the next frame.
    ('                free_queue.push_back(frame);\n'
     '                free_cv.notify_one();\n'
     '            }\n'
     '            // Publish completion',
     '                free_queue.push_back(frame);\n'
     '            }\n'
     '            // Notify only after releasing free_mutex to avoid waking into\n'
     '            // an immediately contended queue lock.\n'
     '            free_cv.notify_one();\n'
     '            // Publish completion'),
    ('frame_cv.wait(queue_lock, [this] { return present_queue.empty(); });',
     '// No drain waiter is needed when the queue is already idle.\n'
     '        // Register real waiters under queue_mutex before sleeping so the\n'
     '        // present worker can skip useless per-frame CV notifications.\n'
     '        if (!present_failure && (!present_queue.empty() || present_in_flight)) {\n'
     '            ++present_waiters;\n'
     '            frame_cv.wait(queue_lock, [this] {\n'
     '                return present_failure || (present_queue.empty() && !present_in_flight);\n'
     '            });\n'
     '            --present_waiters;\n'
     '        }\n'
     '        if (present_failure) std::rethrow_exception(present_failure);'),
    # Synchronous presentation must publish its recycled frame under the
    # same mutex as GetRenderFrame and wake blocked frame consumers.
    # Do not hold the mutex across CopyToSwapchain or GPU fences.
    ('        scheduler.WaitWorker();\n'
     '        CopyToSwapchain(frame);\n'
     '        free_queue.push_back(frame);',
     '        scheduler.WaitWorker();\n'
     '        CopyToSwapchain(frame);\n'
     '        // The synchronous presenter must obey GetRenderFrame\'s free_mutex\n'
     '        // and wake a concurrent frame waiter just like PresentThread does.\n'
     '        {\n'
     '            std::scoped_lock lock{free_mutex};\n'
     '            free_queue.push_back(frame);\n'
     '        }\n'
     '        free_cv.notify_one();'),
    # R316 PS5: swapchain and present frame use the SAME VkFormat.
    # When extents already match, vkCmdCopyImage is exact and avoids a
    # redundant filtered blit. Keep the linear blit for actual scaling,
    # and keep non-PS5/upstream behavior unchanged.
    ('    if (blit_supported) {\n        cmdbuf.BlitImage(',
     '    if (blit_supported\n'
     '#ifdef PS5_NATIVE\n'
     '        && (frame->width != extent.width || frame->height != extent.height)\n'
     '#endif\n'
     '    ) {\n        cmdbuf.BlitImage('),

    # R424: preserve the pre-existing generated presenter body as a precise
    # equivalence anchor, then replace only the FIFO/fence timing phases.
    ("Frame* PresentManager::GetRenderFrame() {\n\n    // Wait for free presentation frames\n    ::Eden::Performance::DiagnosticTimer present_wait_timer(::Eden::Performance::gpu_present_wait);\n    std::unique_lock lock{free_mutex};\n    free_cv.wait(lock, [this] { return present_failure || !free_queue.empty(); });\n    if (present_failure) std::rethrow_exception(present_failure);\n\n    // Take the frame from the queue\n    Frame* frame = free_queue.front();\n    free_queue.pop_front();\n    // Exclusive ownership transferred to this caller. Let the present\n    // thread recycle OTHER frames during our Vulkan GPU fence wait.\n    lock.unlock();\n\n    // Wait for the presentation to be finished so all frame resources are free\n    frame->present_done.Wait();\n    frame->present_done.Reset();\n\n    return frame;\n}\n", "Frame* PresentManager::GetRenderFrame() {\n\n    // Keep the original aggregate for existing FPS/parsing tools.\n    ::Eden::Performance::DiagnosticTimer present_wait_timer(::Eden::Performance::gpu_present_wait);\n    Frame* frame{};\n    {\n        // Wait for a free presentation frame without holding free_mutex\n        // during the later GPU completion fence.\n        ::Eden::Performance::DiagnosticTimer free_wait(\n            ::Eden::Performance::gpu_present_free_wait);\n        std::unique_lock lock{free_mutex};\n        free_cv.wait(lock, [this] { return present_failure || !free_queue.empty(); });\n        if (present_failure) std::rethrow_exception(present_failure);\n        frame = free_queue.front();\n        free_queue.pop_front();\n    }\n\n    // The fence wait is distinct from FIFO backpressure. Both phases are\n    // measured ONLY in detailed logging; quiet path semantics are unchanged.\n    {\n        ::Eden::Performance::DiagnosticTimer fence_wait(\n            ::Eden::Performance::gpu_present_fence_wait);\n        frame->present_done.Wait();\n    }\n    frame->present_done.Reset();\n\n    return frame;\n}\n"),
    # C04: free-frame CV is signaled only if a consumer registered under free_mutex.
    ("        free_cv.wait(lock, [this] { return present_failure || !free_queue.empty(); });\n        if (present_failure) std::rethrow_exception(present_failure);",
     "        // Only sleepers need a free-frame wake. Register before releasing\n        // free_mutex in condition_variable::wait to avoid a lost notify.\n        if (free_queue.empty() && !present_failure) {\n            ++free_waiters;\n            free_cv.wait(lock, [this] { return present_failure || !free_queue.empty(); });\n            --free_waiters;\n        }\n        if (present_failure) std::rethrow_exception(present_failure);"),
    ("        {\n            std::scoped_lock lock{free_mutex};\n            free_queue.push_back(frame);\n        }\n        free_cv.notify_one();",
     "        bool wake_free_waiter{};\n        {\n            std::scoped_lock lock{free_mutex};\n            free_queue.push_back(frame);\n            wake_free_waiter = free_waiters != 0;\n        }\n        if (wake_free_waiter) free_cv.notify_one();"),
    ("            {\n                std::scoped_lock fl{free_mutex};\n                free_queue.push_back(frame);\n            }\n            // Notify only after releasing free_mutex to avoid waking into\n            // an immediately contended queue lock.\n            free_cv.notify_one();",
     "            bool wake_free_waiter{};\n            {\n                std::scoped_lock fl{free_mutex};\n                free_queue.push_back(frame);\n                wake_free_waiter = free_waiters != 0;\n            }\n            // Notify after releasing free_mutex, and only for an actual\n            // sleeping frame consumer. Never skip the error broadcast.\n            if (wake_free_waiter) free_cv.notify_one();"),
])
# Descriptor buffers: Eden's null buffer (nullDescriptor devices) has device address 0,
# but WriteDescriptorBuffer passed it with the binding's range. RADV then builds a real
# descriptor at GPU address 0; desktop kernels only log the resulting page fault, the PS5
# kills the title (TCP read at VA 0).
# The spec requires a null pAddressInfo (or VK_WHOLE_SIZE) for a null descriptor.
# Development A/B switches for device features (headless/dev_vulkan.h, dev-settings).
adapt('src/video_core/vulkan_common/vulkan_device.cpp', 'vulkan_device.cpp', [
    ('#include <algorithm>', '#include <algorithm>\n#include <cstdio>\n#include "dev_vulkan.h"\n#include "performance.h"\n#include "vulkan_pool_capacity.h"'),
    # "Memory in use" for the texture and buffer caches: on the console, the budget less what is
    # left of the pool the CPU shares with the GPU (performance.h, graphics_memory_free).
    ('u64 Device::GetDeviceMemoryUsage() const {\n',
     'namespace {\n'
     '// The largest block of the shared pool that was free when the device was made: about the most\n'
     '// graphics can be given in this session.\n'
     '::Eden::VulkanMemory::PoolCapacityLatch graphics_capacity;\n'
     '}\n\n'
     'u64 Device::GetDeviceMemoryUsage() const {\n'
     '    if (const auto free_memory = ::Eden::Performance::graphics_memory_free.load(std::memory_order_relaxed);\n'
     '        free_memory && ::Eden::Performance::graphics_usage_from_pool.load(std::memory_order_relaxed)) {\n'
     '        // The caches evict what is unused 1.6 GiB under the budget and evict hard 0.8 GiB under\n'
     '        // it. Where the pool could never give graphics 6.4 GiB, those marks become a quarter\n'
     '        // and an eighth of what it could give.\n'
     '        // One existing throttled kernel callback; never probe a second time here.\n'
     '        const u64 observed_free = free_memory();\n'
     '        // A failed initial probe is not permanent zero capacity: accept\n'
     '        // the first later nonzero sample for THIS device lifetime.\n'
     '        const u64 session_capacity = graphics_capacity.Observe(observed_free);\n'
     '        const double scale = session_capacity != 0 && session_capacity < 6400_MiB\n'
     '                                 ? static_cast<double>(6400_MiB) / static_cast<double>(session_capacity)\n'
     '                                 : 1.0;\n'
     '        const u64 free_bytes = static_cast<u64>(static_cast<double>(observed_free) * scale);\n'
     '        return device_access_memory > free_bytes ? device_access_memory - free_bytes : 0;\n'
     '    }\n'),
    ('    extensions.descriptor_buffer = features.descriptor_buffer.descriptorBuffer;',
     '    extensions.descriptor_buffer = features.descriptor_buffer.descriptorBuffer &&\n'
     '        !::Eden::DevVulkan::disable_descriptor_buffer;'),
    ('    features.robustness2.robustBufferAccess2 = VK_FALSE;\n'
     '    features.robustness2.robustImageAccess2 = VK_FALSE;\n'
     '    extensions.robustness_2 = features.robustness2.nullDescriptor;',
     '    if (!::Eden::DevVulkan::robustness2) {\n'
     '        features.robustness2.robustBufferAccess2 = VK_FALSE;\n'
     '        features.robustness2.robustImageAccess2 = VK_FALSE;\n'
     '    }\n'
     '    if (::Eden::DevVulkan::disable_null_descriptor) {\n'
     '        features.robustness2.nullDescriptor = VK_FALSE;\n'
     '    }\n'
     '    extensions.robustness_2 = features.robustness2.nullDescriptor;'),
    ('            (queue_family_properties[*graphics].queueFlags & VK_QUEUE_SPARSE_BINDING_BIT) != 0;',
     '            (queue_family_properties[*graphics].queueFlags & VK_QUEUE_SPARSE_BINDING_BIT) != 0 &&\n'
     '            !::Eden::DevVulkan::disable_sparse;'),
    ('            features.custom_border_color.customBorderColorWithoutFormat;\n    }\n'
     '    RemoveExtensionFeatureIfUnsuitable(extensions.custom_border_color',
     '            features.custom_border_color.customBorderColorWithoutFormat &&\n'
     '            !::Eden::DevVulkan::disable_custom_border;\n    }\n'
     '    RemoveExtensionFeatureIfUnsuitable(extensions.custom_border_color'),
    # dev-settings conditional_rendering=off: guest render-enable conditions are resolved
    # without VK_EXT_conditional_rendering (the path Eden takes on drivers without it).
    ('    // VK_EXT_border_color_swizzle\n',
     '    if (::Eden::DevVulkan::disable_conditional_rendering) {\n'
     '        extensions.conditional_rendering = false;\n    }\n'
     '    // VK_EXT_border_color_swizzle\n'),
    # The heaps and the budget the texture/buffer caches size themselves from.
    ('            device_access_memory = std::min<u64>(device_access_memory, normal_memory + scaler_memory);\n'
     '        }\n    }\n}\n',
     '            device_access_memory = std::min<u64>(device_access_memory, normal_memory + scaler_memory);\n'
     '        }\n    }\n'
     '    const auto free_memory = ::Eden::Performance::graphics_memory_free.load(std::memory_order_relaxed);\n'
     '    // Reset on each new VkDevice, even when a first kernel probe fails.\n'
     '    graphics_capacity.Reset(free_memory ? free_memory() : 0);\n'
     '    std::printf("EDEN_VULKAN_MEMORY integrated=%d heaps=%zu local=%llu initial_usage=%llu device_access=%llu "\n'
     '                "capacity=%llu\\n",\n'
     '                int(is_integrated), valid_heap_memory.size(), static_cast<unsigned long long>(local_memory),\n'
     '                static_cast<unsigned long long>(device_initial_usage),\n'
     '                static_cast<unsigned long long>(device_access_memory),\n'
     '                static_cast<unsigned long long>(graphics_capacity.Value()));\n}\n'),
])
# Development GPU fault probe (dev_vulkan.h, submit_sync=on): wait for every
# submission, so the CPU never records against work the GPU has not finished.
GPU_TIME_HELPERS = r'''
namespace {
// Development GPU execution time (dev_vulkan.h gpu_time): timestamps at the start and end
// of every scheduler command buffer, summed once the GPU has run them and printed every
// 5 s as EDEN_GPU_TIME. Worker thread only.
struct GpuTimeProbe {
    static constexpr u32 SLOTS = 512;
    vk::QueryPool pool;
    PFN_vkCmdWriteTimestamp write{};
    double period_ns{};
    u64 next{}, first_pending{};
    u64 session{};  // reset before first command of a new VkDevice/title
    u32 current{};
    u64 busy_ns{}, max_ns{}, submissions{};
    std::chrono::steady_clock::time_point report{};
    bool failed{};
} gpu_time;

void GpuTimeBegin(const Device& device, vk::CommandBuffer cmdbuf) {
    if (!::Eden::DevVulkan::gpu_time) return;
    const u64 session = ::Eden::DevVulkan::gpu_time_session.load(std::memory_order_acquire);
    if (gpu_time.session != session) {
        // Previous VkDevice teardown implicitly destroyed its query pool.
        // The process-global probe must discard that device's handle, counters
        // and failures before any query on the next title can be recorded.
        gpu_time = GpuTimeProbe{};
        gpu_time.session = session;
    }
    if (gpu_time.failed) return;
    if (!gpu_time.write) {
        const auto& dld = device.GetDispatchLoader();
        gpu_time.write = reinterpret_cast<PFN_vkCmdWriteTimestamp>(
            dld.vkGetDeviceProcAddr(*device.GetLogical(), "vkCmdWriteTimestamp"));
        gpu_time.period_ns = device.GetPhysical().GetProperties().limits.timestampPeriod;
        if (!gpu_time.write || gpu_time.period_ns <= 0) { gpu_time.failed = true; return; }
        gpu_time.pool = device.GetLogical().CreateQueryPool({
            .sType = VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO,
            .pNext = nullptr,
            .flags = 0,
            .queryType = VK_QUERY_TYPE_TIMESTAMP,
            .queryCount = GpuTimeProbe::SLOTS * 2,
            .pipelineStatistics = 0,
        });
        gpu_time.report = std::chrono::steady_clock::now();
    }
    if (gpu_time.next - gpu_time.first_pending >= GpuTimeProbe::SLOTS) {
        gpu_time.failed = true; // results stopped arriving; never overwrite a pending slot
        std::printf("EDEN_GPU_TIME failed=ring\n");
        return;
    }
    gpu_time.current = static_cast<u32>(gpu_time.next++ % GpuTimeProbe::SLOTS);
    cmdbuf.ResetQueryPool(*gpu_time.pool, gpu_time.current * 2, 2);
    gpu_time.write(*cmdbuf, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, *gpu_time.pool, gpu_time.current * 2);
}

void GpuTimeEnd(vk::CommandBuffer cmdbuf) {
    if (!::Eden::DevVulkan::gpu_time || gpu_time.failed || !gpu_time.write) return;
    gpu_time.write(*cmdbuf, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, *gpu_time.pool, gpu_time.current * 2 + 1);
}

void GpuTimeCollect(const Device& device) {
    if (!::Eden::DevVulkan::gpu_time || gpu_time.failed || !gpu_time.write) return;
    while (gpu_time.first_pending + 1 < gpu_time.next) {
        const u32 slot = static_cast<u32>(gpu_time.first_pending % GpuTimeProbe::SLOTS);
        std::array<u64, 2> stamps{};
        if (device.GetLogical().GetQueryResults(*gpu_time.pool, slot * 2, 2, sizeof(stamps), stamps.data(),
                                               sizeof(u64), VK_QUERY_RESULT_64_BIT) != VK_SUCCESS) break;
        const u64 ns = stamps[1] > stamps[0]
                           ? static_cast<u64>(double(stamps[1] - stamps[0]) * gpu_time.period_ns) : 0;
        gpu_time.busy_ns += ns;
        gpu_time.max_ns = (std::max)(gpu_time.max_ns, ns);
        ++gpu_time.submissions;
        ++gpu_time.first_pending;
    }
    const auto now = std::chrono::steady_clock::now();
    const auto wall = std::chrono::duration_cast<std::chrono::nanoseconds>(now - gpu_time.report).count();
    if (wall >= 5'000'000'000) {
        std::printf("EDEN_GPU_TIME wall_ms=%.1f busy_ms=%.1f submissions=%llu max_ms=%.2f\n", wall / 1e6,
                    gpu_time.busy_ns / 1e6, static_cast<unsigned long long>(gpu_time.submissions),
                    gpu_time.max_ns / 1e6);
        gpu_time.busy_ns = gpu_time.max_ns = gpu_time.submissions = 0;
        gpu_time.report = now;
    }
}

// VkQueryPool is a device child. It must be destroyed explicitly while the
// owner VkDevice remains live (not forgotten when the next title begins).
void GpuTimeDestroy(const Device& device) {
    if (!gpu_time.pool) return;
    const auto& dld = device.GetDispatchLoader();
    const VkDevice handle = *device.GetLogical();
    (void)dld.vkDeviceWaitIdle(handle);
    dld.vkDestroyQueryPool(handle, *gpu_time.pool, nullptr);
    gpu_time = GpuTimeProbe{};
}
} // namespace
'''
# R357: a Vulkan worker wake-on-pop is only needed for active WaitWorker
# drain callers, not for every consumed draw batch. Preserve native queue
# ownership, execution_mutex synchronization, and destructor stop-wakeup.
adapt('src/video_core/renderer_vulkan/vk_scheduler.h',
      'include/video_core/renderer_vulkan/vk_scheduler.h', [

    ('''    /// Send work to a separate thread.
    template <typename T>''', '''#ifdef PS5_NATIVE
    // A command chunk can fill while Configure() holds both guest GPU-cache
    // locks. Send the previous command batch BEFORE those locks are acquired,
    // without waiting for GPU completion or modifying resource/fence state.
    // The normal Record fallback stays authoritative if a draw is unusually
    // command-heavy (>4 KiB of queued callbacks).
    bool PreflightDrawCommands() {
        constexpr size_t kDrawCommandReserve = 4096;
        if (!chunk || chunk->Empty() || chunk->HasReserve(kDrawCommandReserve))
            return false;
        DispatchWork();
        return true;
    }
#endif

    /// Send work to a separate thread.
    template <typename T>'''),
    ('''        bool Empty() const {
            return command_offset == 0;
        }
''', '''        bool Empty() const {
            return command_offset == 0;
        }

#ifdef PS5_NATIVE
        bool HasReserve(size_t bytes) const noexcept {
            // Allow for maximum command alignment after the current offset.
            const size_t needed = bytes + alignof(std::max_align_t);
            return needed <= data.size() && command_offset <= data.size() - needed;
        }
#endif
'''),
    ("    std::condition_variable_any event_cv;\n    std::jthread worker_thread;", "    std::condition_variable_any event_cv;\n    // Protected by queue_mutex. Only a draining WaitWorker needs a wakeup\n    // when the Vulkan worker consumes a queued command chunk.\n    unsigned queue_drain_waiters{};\n    // Protected by queue_mutex. The worker is executing a chunk (and thus\n    // cannot be sleeping on event_cv) until its next queue acquisition.\n    bool worker_in_flight{};\n    std::jthread worker_thread;"),
])
adapt('src/video_core/renderer_vulkan/vk_scheduler.cpp', 'vulkan_scheduler.cpp', [
    ("void Scheduler::AcquireNewChunk() {\n    std::scoped_lock rl{reserve_mutex};\n\n    if (chunk_reserve.empty()) {\n        // If we don't have anything reserved, we need to make a new chunk.\n        chunk = std::make_unique<CommandChunk>();\n    } else {\n        // Otherwise, we can just take from the reserve.\n        chunk = std::move(chunk_reserve.back());\n        chunk_reserve.pop_back();\n    }\n}", "void Scheduler::AcquireNewChunk() {\n    {\n        std::scoped_lock rl{reserve_mutex};\n        if (!chunk_reserve.empty()) {\n            // The producer can reuse a completed command chunk immediately.\n            chunk = std::move(chunk_reserve.back());\n            chunk_reserve.pop_back();\n            return;\n        }\n    }\n    // Allocation can page fault or invoke allocator locks. Never hold the\n    // recycling mutex across it: the GPU worker must remain free to return\n    // finished chunks while the producer creates another command batch.\n    chunk = std::make_unique<CommandChunk>();\n}"),
    ("void Scheduler::DispatchWork() {\n    if (chunk && !chunk->Empty()) {\n        {\n            std::scoped_lock ql{queue_mutex};\n            work_queue.push(std::move(chunk));\n        }\n        event_cv.notify_all();\n        AcquireNewChunk();\n    }\n}", "void Scheduler::DispatchWork() {\n    if (chunk && !chunk->Empty()) {\n        bool wake_worker{};\n        {\n            std::scoped_lock ql{queue_mutex};\n            // If the worker is executing a chunk, it will consume queued\n            // successors on its next loop without sleeping. Only the idle\n            // transition requires a broadcast (drain waiters share this CV).\n            wake_worker = work_queue.empty() && !worker_in_flight;\n            work_queue.push(std::move(chunk));\n        }\n        if (wake_worker) event_cv.notify_all();\n        AcquireNewChunk();\n    }\n}"),
    ("            std::unique_lock lk{queue_mutex};\n\n            // Wait for work.\n            event_cv.wait(lk, stop_token, [&] { return TryPopQueue(work); });\n\n            // If we've been asked to stop, we're done.\n            if (stop_token.stop_requested()) {\n                return;\n            }\n\n            // Exchange lock ownership", "            std::unique_lock lk{queue_mutex};\n            // This lock also guards DispatchWork's idle-to-active wake test.\n            // A producer cannot miss the wake when the queue is empty.\n            worker_in_flight = false;\n\n            // Wait for work.\n            event_cv.wait(lk, stop_token, [&] { return TryPopQueue(work); });\n\n            // If we've been asked to stop, we're done.\n            if (stop_token.stop_requested()) {\n                return;\n            }\n            worker_in_flight = true;\n\n            // Exchange lock ownership"),
    ("        std::unique_lock ql{queue_mutex};\n        event_cv.wait(ql, [this] { return work_queue.empty(); });", "        std::unique_lock ql{queue_mutex};\n        ++queue_drain_waiters;\n        event_cv.wait(ql, [this] { return work_queue.empty(); });\n        --queue_drain_waiters;"),
    ("        ++queue_drain_waiters;\n        event_cv.wait(ql, [this] { return work_queue.empty(); });\n        --queue_drain_waiters;\n    }\n\n    // Now wait for execution to finish.\n    std::scoped_lock el{execution_mutex};\n}", "        ++queue_drain_waiters;\n        event_cv.wait(ql, [this] {\n#ifdef PS5_NATIVE\n            return work_queue.empty() || static_cast<bool>(::Eden::PeekGpuFailure());\n#else\n            return work_queue.empty();\n#endif\n        });\n        --queue_drain_waiters;\n#ifdef PS5_NATIVE\n        if (auto failure = ::Eden::PeekGpuFailure())\n            std::rethrow_exception(failure);\n#endif\n    }\n\n    // Now wait for execution to finish.\n    std::scoped_lock el{execution_mutex};\n#ifdef PS5_NATIVE\n    // In-flight work publishes errors before releasing execution_mutex.\n    if (auto failure = ::Eden::PeekGpuFailure())\n        std::rethrow_exception(failure);\n#endif\n}"),

    ("        work = std::move(work_queue.front());\n        work_queue.pop();\n        event_cv.notify_all();\n        return true;", "        work = std::move(work_queue.front());\n        work_queue.pop();\n        // The consumer normally has no producer waiting for an empty queue.\n        // Avoid broadcasting on every chunk when it cannot wake anyone.\n        // queue_mutex synchronizes this check with WaitWorker's registration.\n        if (work_queue.empty() && queue_drain_waiters != 0)\n            event_cv.notify_all();\n        return true;"),
    ('#include <memory>', '#include <algorithm>\n#include <memory>\n#include <array>\n#include <chrono>\n#include <cstdio>\n#include "dev_vulkan.h"'),
    ('#include "common/thread.h"', '#include "common/thread.h"\n#include "performance.h"'),
    ("#include \"performance.h\"", "#include \"performance.h\"\n#ifdef PS5_NATIVE\n#include \"gpu_failure.h\"\n#endif"),
    ("    worker_thread = std::jthread([this](std::stop_token token) { WorkerThread(token); });", "    worker_thread = std::jthread([this](std::stop_token token) {\n#ifdef PS5_NATIVE\n        try {\n            WorkerThread(token);\n        } catch (...) {\n            // Background setup failures must also reach native GPU observers.\n            ::Eden::RecordGpuFailure(std::current_exception());\n            event_cv.notify_all();\n        }\n#else\n        WorkerThread(token);\n#endif\n    });"),
    ("            const bool has_submit = work->HasSubmit();\n            work->ExecuteAll(current_cmdbuf, current_upload_cmdbuf);\n\n            // If the chunk was a submission, reallocate the command buffer.\n            if (has_submit) {\n                AllocateWorkerCommandBuffer();\n            }", "#ifdef PS5_NATIVE\n            try {\n#endif\n                const bool has_submit = work->HasSubmit();\n                work->ExecuteAll(current_cmdbuf, current_upload_cmdbuf);\n\n                // If the chunk was a submission, reallocate the command buffer.\n                if (has_submit) {\n                    AllocateWorkerCommandBuffer();\n                }\n#ifdef PS5_NATIVE\n            } catch (...) {\n                // Publish failure before releasing execution_mutex. A\n                // WaitWorker drain can never mistake this chunk for success.\n                ::Eden::RecordGpuFailure(std::current_exception());\n                event_cv.notify_all();\n                return;\n            }\n#endif"),
    ('    Common::SetCurrentThreadToPerformanceCores();',
     '    Common::SetCurrentThreadToPerformanceCores();\n#ifdef PS5_NATIVE\n'
     '    ::Eden::Performance::ProbeSchedulerOnce("VulkanWorker");\n#endif'),
    ('namespace Vulkan {\n', 'namespace Vulkan {\n' + GPU_TIME_HELPERS),
    # The default destructor joins worker_thread only AFTER its body. If a
    # dev timestamp probe created a query pool, join before destroying it.
    ('Scheduler::~Scheduler() = default;',
     '''Scheduler::~Scheduler() {
    // The worker writes gpu_time.pool. Do not test that field until the
    // worker has stopped: the old conditional check raced with its first
    // CreateQueryPool on a quick title exit, risking use-after-free.
    worker_thread.request_stop();
    event_cv.notify_all();
    if (worker_thread.joinable()) worker_thread.join();
    if (gpu_time.pool) GpuTimeDestroy(device);
}'''),
    ('        .pInheritanceInfo = nullptr,\n    });\n    current_upload_cmdbuf = vk::CommandBuffer(command_pool->Commit(), device.GetDispatchLoader());',
     '        .pInheritanceInfo = nullptr,\n    });\n    GpuTimeBegin(device, current_cmdbuf);\n'
     '    current_upload_cmdbuf = vk::CommandBuffer(command_pool->Commit(), device.GetDispatchLoader());'),
    ('        upload_cmdbuf.End();\n        cmdbuf.End();\n',
     '        upload_cmdbuf.End();\n        GpuTimeEnd(cmdbuf);\n        cmdbuf.End();\n'),
    ('            vk::Check(result);\n            break;\n        }\n    });\n    chunk->MarkSubmit();',
     '            vk::Check(result);\n            break;\n        }\n        GpuTimeCollect(device);\n    });\n    chunk->MarkSubmit();'),
    ('    const u64 signal_value = SubmitExecution(signal_semaphore, wait_semaphore);\n'
     '    AllocateNewContext();\n    return signal_value;',
     '    const u64 signal_value = SubmitExecution(signal_semaphore, wait_semaphore);\n'
     '    if (::Eden::DevVulkan::sync_submissions) {\n        Wait(signal_value);\n    }\n'
     '    AllocateNewContext();\n    return signal_value;'),
    ("    std::array<VkClearValue, 9> values{};\n    for (u32 i = 0; i < clear_value_count && i < values.size(); ++i) {\n        values[i] = clear_values[i];\n    }\n    Record([renderpass, framebuffer_handle, render_area, values, clear_value_count](", "    std::array<VkClearValue, 9> values{};\n    // The Vulkan pointer below owns exactly these nine entries. Never publish\n    // the caller's unchecked clearValueCount after clipping the copy.\n    const u32 bounded_clear_value_count =\n        clear_values ? (std::min)(clear_value_count, static_cast<u32>(values.size())) : 0;\n    for (u32 i = 0; i < bounded_clear_value_count; ++i) {\n        values[i] = clear_values[i];\n    }\n    Record([renderpass, framebuffer_handle, render_area, values, bounded_clear_value_count]("),
    ("            .clearValueCount = clear_value_count,\n            .pClearValues = clear_value_count != 0 ? values.data() : nullptr,", "            .clearValueCount = bounded_clear_value_count,\n            .pClearValues = bounded_clear_value_count != 0 ? values.data() : nullptr,"),
])
adapt('src/video_core/renderer_vulkan/pipeline_helper.h',
      'include/video_core/renderer_vulkan/pipeline_helper.h', [
    ('            VkDescriptorGetInfoEXT get_info{',
     '            const VkDescriptorAddressInfoEXT* const buffer_info{\n'
     '                entry.address.address != 0 ? &address_info : nullptr};\n'
     '            VkDescriptorGetInfoEXT get_info{'),
    ('get_info.data.pUniformBuffer = &address_info;', 'get_info.data.pUniformBuffer = buffer_info;'),
    ('get_info.data.pStorageBuffer = &address_info;', 'get_info.data.pStorageBuffer = buffer_info;'),
    ('get_info.data.pUniformTexelBuffer = &address_info;', 'get_info.data.pUniformTexelBuffer = buffer_info;'),
    ('get_info.data.pStorageTexelBuffer = &address_info;', 'get_info.data.pStorageTexelBuffer = buffer_info;'),
])
# F07: the buffer usage interval is already cleared after its GPU tick.
# Keep the normal desktop history unchanged; native idle buffers retire once,
# avoiding a repeated per-page tracker reset under buffer_cache.mutex.
adapt('src/video_core/renderer_vulkan/vk_buffer_cache.h',
      'include/video_core/renderer_vulkan/vk_buffer_cache.h', [
    ("    void ResetUsageTracking() noexcept {\n        tracker.Reset();\n    }", "    void ResetUsageTracking() noexcept {\n        tracker.Reset();\n#ifdef PS5_NATIVE\n        // Sentinel 0 means no outstanding GPU usage after the completed\n        // interval has been cleared. MarkUsage publishes the next real tick.\n        last_usage_tick = 0;\n#endif\n    }"),
])

adapt('src/video_core/renderer_vulkan/vk_blit_screen.h',
      'include/video_core/renderer_vulkan/vk_blit_screen.h', [
    ('VkFormat current_swapchain_view_format);',
     'VkFormat current_swapchain_view_format, bool draw_hud = false);'),
    ('    std::list<Layer> layers{};',
     '    std::list<Layer> layers{};\n#ifdef PS5_NATIVE\n'
     '    // Constructor size for FSR/SGSR layer resources, not swapchain extent.\n'
     '    VkExtent2D layer_window_size{};\n#endif'),
])
adapt('src/video_core/renderer_vulkan/renderer_vulkan.h',
      'include/video_core/renderer_vulkan/renderer_vulkan.h', [
    ('    void Composite(', '    void PresentLoading();\n    void Composite('),
])
adapt('src/video_core/renderer_vulkan/renderer_vulkan.cpp', 'vulkan_renderer.cpp', [
    ('#include "video_core/renderer_vulkan/renderer_vulkan.h"',
     '#include "video_core/renderer_vulkan/renderer_vulkan.h"\n#include "display_refresh.h"'),
    # A frame the display has no refresh for is not presented: a game patched for more frames
    # than the output shows keeps its pace instead of waiting for a refresh per frame
    # (headless/display_refresh.h). The frame still ends as any other.
    ('    RenderScreenshot(framebuffers);\n    Frame* frame = present_manager.GetRenderFrame();',
     '    RenderScreenshot(framebuffers);\n'
     '    if (::Eden::Display::SkipFrame()) {\n'
     '        gpu.RendererFrameEndNotify();\n'
     '        rasterizer.TickFrame();\n'
     '        return;\n'
     '    }\n'
     '    Frame* frame = present_manager.GetRenderFrame();'),
    ('    Report();', '    PresentLoading();\n    Report();'),
    # The graphics worker must not read mutable swapchain dimensions/format
    # directly while the background present worker can call RecreateSwapchain.
    ('render_window.GetFramebufferLayout(), swapchain.GetImageCount(),',
     'render_window.GetFramebufferLayout(), present_manager.SwapchainImageCount(),'),
    ('frame_gen.Process(device, frame, swapchain.GetImageFormat(), GuestExtent(framebuffers));',
     'frame_gen.Process(device, frame, present_manager.SwapchainImageFormat(), GuestExtent(framebuffers));'),
    ('swapchain.GetImageViewFormat());', 'present_manager.SwapchainImageViewFormat(), true);'),
    ('layout, 1, format);', 'layout, 1, format, true);'),
    ('void RendererVulkan::Report() const {',
     (vulkan_oracle / 'vulkan_loading.inc').read_text() + '\nvoid RendererVulkan::Report() const {'),
    # Present() only records the hand-off into a fresh chunk. Dispatch it now so
    # the present thread gets this frame immediately instead of after the
    # producer's next 8-draw dispatch (upstream does this only with LSFG).
    ('    present_manager.Present(frame);\n#ifdef HAS_LSFG\n    scheduler.DispatchWork();\n#endif',
     '    present_manager.Present(frame);\n    scheduler.DispatchWork();'),
    ('} // namespace Vulkan', '''} // namespace Vulkan
namespace Eden {
void PresentVulkanLoading(VideoCore::RendererBase& renderer) {
    static_cast<Vulkan::RendererVulkan&>(renderer).PresentLoading();
}
}'''),
])
adapt('src/video_core/renderer_vulkan/present/window_adapt_pass.h',
      'include/video_core/renderer_vulkan/present/window_adapt_pass.h', [
    ('const Layout::FramebufferLayout& layout, Frame* dst);',
     'const Layout::FramebufferLayout& layout, Frame* dst, bool draw_hud = false);'),
    ('    vk::Pipeline coverage_pipeline;',
     '    vk::Pipeline coverage_pipeline;\n    vk::PipelineLayout hud_layout;\n    vk::Pipeline hud_pipeline;'),
])
# Deferred presentation metadata: one owning small vector, inline single layer.
present_draw_edits = [('#include "core/frontend/framebuffer_layout.h"', '#include <boost/container/small_vector.hpp>\n\n#include "core/frontend/framebuffer_layout.h"'), ('    std::vector<PresentPushConstants> push_constants(layer_count);\n    std::vector<VkDescriptorSet> descriptor_sets(layer_count);\n    std::vector<VkPipeline> graphics_pipelines(layer_count);', '    struct LayerDraw {\n        PresentPushConstants push_constants;\n        VkDescriptorSet descriptor_set;\n        VkPipeline graphics_pipeline;\n    };\n    // The usual single-layer frame needs no heap storage. Larger frames\n    // share one allocation, transferred to the deferred draw command.\n    boost::container::small_vector<LayerDraw, 1> draws(layer_count);'), ('        switch (configs[i].blending) {', '        auto& draw = draws[i];\n        switch (configs[i].blending) {'), ('            graphics_pipelines[i] = *opaque_pipeline;', '            draw.graphics_pipeline = *opaque_pipeline;'), ('            graphics_pipelines[i] = *premultiplied_pipeline;', '            draw.graphics_pipeline = *premultiplied_pipeline;'), ('            graphics_pipelines[i] = *coverage_pipeline;', '            draw.graphics_pipeline = *coverage_pipeline;'), ('            cmdbuf.BindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS, graphics_pipelines[i]);', '            cmdbuf.BindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS, draw.graphics_pipeline);'), ('&push_constants[i], &descriptor_sets[i]', '&draw.push_constants, &draw.descriptor_set'), ('    scheduler.Record([=](vk::CommandBuffer cmdbuf) {', '    scheduler.Record([=, draws = std::move(draws)](vk::CommandBuffer cmdbuf) {'), ('        for (size_t i = 0; i < layer_count; i++) {\n            cmdbuf.BindPipeline', '        for (size_t i = 0; i < layer_count; i++) {\n            const auto& draw = draws[i];\n            cmdbuf.BindPipeline'), ('                                 push_constants[i]);', '                                 draw.push_constants);'), ('                                      descriptor_sets[i], {});', '                                      draw.descriptor_set, {});')]
adapt('src/video_core/renderer_vulkan/present/window_adapt_pass.cpp', 'vulkan_window_adapt_pass.cpp', [
    ('#include "core/frontend/framebuffer_layout.h"',
     '#include "core/frontend/framebuffer_layout.h"\n#include "hud.h"\n#include "vulkan_hud_shaders.h"'),
    ('const Layout::FramebufferLayout& layout, Frame* dst) {',
     'const Layout::FramebufferLayout& layout, Frame* dst, bool draw_hud) {'),
    ('    scheduler.Record([=](vk::CommandBuffer cmdbuf) {',
     (vulkan_oracle / 'vulkan_hud_prepare.inc').read_text() + '\n    scheduler.Record([=](vk::CommandBuffer cmdbuf) {'),
    ('        cmdbuf.EndRenderPass();',
     (vulkan_oracle / 'vulkan_hud_draw.inc').read_text() + '\n        cmdbuf.EndRenderPass();'),
    *present_draw_edits,
])
# R328: Framebuffer dimension / format changes and runtime antialias setting
# changes can destroy old FXAA/SMAA images and descriptors with GPU work still
# in flight. The raw-image resource ticks are waited *after* emplace today,
# too late for the AA variant. Drain only if an AA pass actually exists.
# Do not impose idle waits on normal draws or when the filter is disabled.
adapt('src/video_core/renderer_vulkan/present/layer.cpp', 'vulkan_present_layer.cpp', [
    ("    if (!std::holds_alternative<std::monostate>(anti_alias) && anti_alias_setting == filters.get_anti_aliasing())\n        return;", "#ifdef PS5_NATIVE\n    const auto requested_aa = filters.get_anti_aliasing();\n    // Disabled AA has no GPU resources to rebuild. The old guard skipped\n    // only live FXAA/SMAA and reconstructed the monostate on every frame,\n    // including when the filter remained disabled across thousands of draws.\n    // A resize resets a live pass to monostate, so FXAA/SMAA still rebuild.\n    if (anti_alias_setting == requested_aa &&\n        (!std::holds_alternative<std::monostate>(anti_alias) ||\n         (requested_aa != Settings::AntiAliasing::Fxaa &&\n          requested_aa != Settings::AntiAliasing::Smaa))) {\n        return;\n    }\n#else\n    if (!std::holds_alternative<std::monostate>(anti_alias) && anti_alias_setting == filters.get_anti_aliasing())\n        return;\n#endif"),
    ("    resource_ticks.resize(image_count);\n    raw_images.resize(image_count);", "    // ReleaseRawImages waited for every old timeline use. Reusing its tick\n    // values after rebuilding the layer would cause redundant Wait calls on\n    // newly allocated images, although those old fences have retired.\n#ifdef PS5_NATIVE\n    resource_ticks.assign(image_count, 0);\n#else\n    resource_ticks.resize(image_count);\n#endif\n    raw_images.resize(image_count);"),
    ("void Layer::ReleaseRawImages() {\n    for (const u64 tick : resource_ticks) {\n        scheduler.Wait(tick);\n    }", "void Layer::ReleaseRawImages() {\n#ifdef PS5_NATIVE\n    // On this single Vulkan GPU timeline, the latest presentation resource\n    // tick subsumes all preceding image uses, including out-of-order slots.\n    const auto last_tick = std::max_element(resource_ticks.begin(), resource_ticks.end());\n    if (last_tick != resource_ticks.end() && *last_tick != 0) {\n        scheduler.Wait(*last_tick);\n    }\n#else\n    for (const u64 tick : resource_ticks) {\n        scheduler.Wait(tick);\n    }\n#endif"),
    # Never upload recycled staging bytes when the guest backing is missing.
    ("    if (host_ptr) {\n        Tegra::Texture::UnswizzleTexture(\n            mapped_span.subspan(image_offset, linear_size), std::span(host_ptr, tiled_size),\n            bytes_per_pixel, framebuffer.width, framebuffer.height, 1, block_height_log2, 0);\n        buffer.Flush();  // Ensure host writes are visible before the GPU copy.\n    }", "    const std::span<u8> linear_span = mapped_span.subspan(image_offset, linear_size);\n    if (host_ptr) {\n        Tegra::Texture::UnswizzleTexture(\n            linear_span, std::span(host_ptr, tiled_size),\n            bytes_per_pixel, framebuffer.width, framebuffer.height, 1, block_height_log2, 0);\n    } else {\n        // Never upload stale staging bytes if the guest framebuffer is missing.\n        std::fill(linear_span.begin(), linear_span.end(), u8{0});\n    }\n    buffer.Flush();  // Both the upload and missing-memory clear need visibility."),
    ("#include <variant>", "#include <algorithm>\n#include <variant>"),
    # R331: ReleaseRawImages destroys the VkImage before the VkImageView(s)
    # which reference it. Vulkan images must outlive their views. Free each
    # view first, then the image; this is used on resize and Layer destruction.
    ('    raw_images.clear();\n    buffer.reset();',
     '    raw_image_views.clear();\n    raw_images.clear();\n    buffer.reset();'),
    # R329: the staging buffer has exactly ci.size mapped bytes (pinned VMA
    # allocator), and that size depends on framebuffer STRIDE as well as the
    # visible extent/format. A same-size framebuffer with a different stride
    # must reallocate, or UpdateRawImage's subspan can exceed the buffer.
    # R330: for a pitch-only change, replace ONLY the upload buffer after
    # per-image tick waits; preserve AA resources and avoid vkDeviceWaitIdle.
    ('        framebuffer.pixel_format == pixel_format && !raw_images.empty()) {\n'
     '        return;\n    }',
     '''        framebuffer.pixel_format == pixel_format && !raw_images.empty() &&
        buffer.Mapped().size() == CalculateBufferSize(framebuffer)) {
        return;
    }
#ifdef PS5_NATIVE
    // Same dimensions and format, but the guest row pitch changed. Recycle
    // only the upload buffer after its last referenced GPU tick; AA images,
    // descriptors, renderpasses and pipelines remain valid. Do NOT trigger
    // a full-device WaitIdle or recreate the FXAA/SMAA pass on pitch changes.
    if (framebuffer.width == raw_width && framebuffer.height == raw_height &&
        framebuffer.pixel_format == pixel_format && !raw_images.empty()) {
        // All layer ticks share one monotonically increasing Vulkan GPU
        // timeline. Waiting for the maximum retires every earlier user of
        // the old upload staging buffer with one semaphore wait.
        const auto last_tick = std::max_element(resource_ticks.begin(), resource_ticks.end());
        if (last_tick != resource_ticks.end() && *last_tick != 0) {
            scheduler.Wait(*last_tick);
        }
        CreateStagingBuffer(device, framebuffer);
        return;
    }
#endif'''),
    ('    pixel_format = framebuffer.pixel_format;\n'
     '    anti_alias.emplace<std::monostate>();\n\n'
     '    ReleaseRawImages();',
     '''    pixel_format = framebuffer.pixel_format;
#ifdef PS5_NATIVE
    if (!std::holds_alternative<std::monostate>(anti_alias)) {
        // Existing FXAA/SMAA images and descriptors may still be referenced
        // by command buffers submitted for prior presentation frames.
        scheduler.Finish();
        device.GetLogical().WaitIdle();
    }
#endif
    anti_alias.emplace<std::monostate>();

    ReleaseRawImages();'''),
    ('    anti_alias_setting = filters.get_anti_aliasing();\n\n'
     '    const VkExtent2D render_area{',
     '''#ifdef PS5_NATIVE
    if (!std::holds_alternative<std::monostate>(anti_alias)) {
        // Swapping the AA variant frees GPU resources, not just host state.
        scheduler.Finish();
        device.GetLogical().WaitIdle();
    }
#endif
    anti_alias_setting = filters.get_anti_aliasing();

    const VkExtent2D render_area{'''),
    ("    const u64 tiled_size{Tegra::Texture::CalculateSize(\n        true, bytes_per_pixel, framebuffer.stride, framebuffer.height, 1, block_height_log2, 0)};\n    const std::span<u8> linear_span = mapped_span.subspan(image_offset, linear_size);\n    if (host_ptr) {\n        Tegra::Texture::UnswizzleTexture(", "#ifdef PS5_NATIVE\n    // An unmapped guest framebuffer has no tiled source to measure.\n    // Keep the exact raw-zero upload, but skip tiled-size/format arithmetic\n    // on repeated missing-frame fallbacks (HUD, scene changes).\n    const std::span<u8> linear_span = mapped_span.subspan(image_offset, linear_size);\n    if (host_ptr) {\n        const u64 tiled_size{Tegra::Texture::CalculateSize(\n            true, bytes_per_pixel, framebuffer.stride, framebuffer.height, 1, block_height_log2, 0)};\n#else\n    const u64 tiled_size{Tegra::Texture::CalculateSize(\n        true, bytes_per_pixel, framebuffer.stride, framebuffer.height, 1, block_height_log2, 0)};\n    const std::span<u8> linear_span = mapped_span.subspan(image_offset, linear_size);\n    if (host_ptr) {\n#endif\n        Tegra::Texture::UnswizzleTexture("),
    ("    const u64 image_offset = GetRawImageOffset(framebuffer, image_index);\n\n", "#ifndef PS5_NATIVE\n    const u64 image_offset = GetRawImageOffset(framebuffer, image_index);\n#endif\n\n"),
    ("    const u32 bytes_per_pixel = GetBytesPerPixel(framebuffer);\n    const u64 linear_size{GetSizeInBytes(framebuffer)};", "    const u32 bytes_per_pixel = GetBytesPerPixel(framebuffer);\n#ifdef PS5_NATIVE\n    // This raw upload already resolved the guest pixel format above. Do not\n    // decode that same format a second time through GetSizeInBytes every\n    // time the CPU reads back a guest framebuffer.\n    const u64 linear_size{\n        static_cast<std::size_t>(framebuffer.stride) *\n        static_cast<std::size_t>(framebuffer.height) * bytes_per_pixel};\n    // Staging slots have the same guest row pitch: do not decode BPP again\n    // through GetRawImageOffset for every non-accelerated presentation.\n    const u64 image_offset = linear_size * image_index;\n#else\n    const u64 linear_size{GetSizeInBytes(framebuffer)};\n#endif"),
])

adapt('src/video_core/renderer_vulkan/vk_blit_screen.cpp', 'vulkan_blit_screen.cpp', [
    # R327: a change in the number of guest presentation layers destroys
    # the prior descriptors, FSR/FXAA images, and views. The ordinary window
    # reconfiguration waits for outstanding GPU work, but this resize path
    # previously cleared layers immediately. Drain only when removing live
    # layers, never on steady frames or initial construction.
    ('    if (layers.size() != framebuffers.size()) {\n        layers.clear();',
     '''    if (layers.size() != framebuffers.size()) {
#ifdef PS5_NATIVE
        if (!layers.empty()) {
            // Old layer resources can still be in queued Vulkan draws.
            WaitIdle(device);
        }
#endif
        layers.clear();'''),
    ('VkFormat current_swapchain_view_format) {',
     'VkFormat current_swapchain_view_format, bool draw_hud) {'),
    ('image_index, layers, framebuffers, layout, frame);',
     'image_index, layers, framebuffers, layout, frame, draw_hud);'),
])
shader_header = '#pragma once\n#include <cstdint>\n'
for stage in ('vert', 'frag'):
    binary = output / f'vulkan_hud.{stage}.spv'
    # Source-only CI compares the tracked SPIR-V against its generated header
    # without depending on whatever glslang version the runner happens to use.
    # Original shader source SHA is asserted by the source-equivalence fixture.
    # The production renderer compiles pre-validated tracked SPIR-V directly.
    oracle_spv = Path(os.environ['EDEN_VULKAN_ORACLE_SPV_DIR']) if 'EDEN_VULKAN_ORACLE_SPV_DIR' in os.environ else None
    if oracle_spv is not None:
        binary.write_bytes((oracle_spv / binary.name).read_bytes())
    else:
        subprocess.run(['glslangValidator', '-V', '--target-env', 'vulkan1.0',
                        '-o', str(binary), str(port / f'vulkan_hud.{stage}')], check=True)
        subprocess.run(['spirv-val', '--target-env', 'vulkan1.0', str(binary)], check=True)
    data = binary.read_bytes()
    words = struct.unpack('<' + 'I' * (len(data) // 4), data)
    shader_header += f'inline constexpr uint32_t EDEN_HUD_{stage.upper()}_SPV[] = {{\n'
    shader_header += ','.join(hex(word) for word in words) + '\n};\n'
path = output / 'vulkan_hud_shaders.h'
if not path.exists() or path.read_text() != shader_header:
    path.write_text(shader_header)
adapt('src/video_core/vulkan_common/vulkan.h', 'include/video_core/vulkan_common/vulkan.h',
      [('#else\n#define VK_USE_PLATFORM_XLIB_KHR', '#elif defined(PS5_NATIVE)\n// Native display-plane presentation, no desktop window-system headers.\n#else\n#define VK_USE_PLATFORM_XLIB_KHR')])
adapt('src/video_core/vulkan_common/vulkan_instance.cpp', 'vulkan_instance.cpp', [
    ('namespace Vulkan {', 'extern "C" VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL vkGetInstanceProcAddr(VkInstance, const char*);\n\nnamespace Vulkan {'),
    ('    case Core::Frontend::WindowSystemType::Headless:', '    case Core::Frontend::WindowSystemType::PS5:\n        extensions.push_back(VK_KHR_DISPLAY_EXTENSION_NAME);\n        break;\n    case Core::Frontend::WindowSystemType::Headless:'),
    ('#else\n    case Core::Frontend::WindowSystemType::X11:', '#elif !defined(PS5_NATIVE)\n    case Core::Frontend::WindowSystemType::X11:'),
    ('''    if (!library.IsOpen()) {
        LOG_ERROR(Render_Vulkan, "Vulkan library not available");
        throw vk::Exception(VK_ERROR_INITIALIZATION_FAILED);
    }
    if (!library.GetSymbol("vkGetInstanceProcAddr", &dld.vkGetInstanceProcAddr)) {
        LOG_ERROR(Render_Vulkan, "vkGetInstanceProcAddr not present in Vulkan");
        throw vk::Exception(VK_ERROR_INITIALIZATION_FAILED);
    }''', '    (void)library;\n    dld.vkGetInstanceProcAddr = &::vkGetInstanceProcAddr;'),
])
adapt('src/video_core/vulkan_common/vulkan_library.cpp', 'vulkan_library.cpp', [
    ('#if defined(__ANDROID__) && defined(ARCHITECTURE_arm64)', '#if defined(PS5_NATIVE)\n    return std::make_shared<Common::DynamicLibrary>();\n#elif defined(__ANDROID__) && defined(ARCHITECTURE_arm64)'),
])
adapt('src/video_core/vulkan_common/vulkan_wrapper.h', 'include/video_core/vulkan_common/vulkan_wrapper.h', [
    ('#include <array>', '#include <array>\n#include <cstdio>\n#include "performance.h"'),
    ('return dld->vkQueueSubmit(queue,', 'auto timer = Eden::Performance::VulkanTimer(2);\n        return dld->vkQueueSubmit(queue,'),
    ('return dld->vkQueueSubmit2(queue,', 'auto timer = Eden::Performance::VulkanTimer(2);\n        return dld->vkQueueSubmit2(queue,'),
    ('return dld->vkWaitForFences(owner,', 'auto timer = Eden::Performance::VulkanTimer(3);\n        return dld->vkWaitForFences(owner,'),
    ('const VkResult result = dld->vkWaitSemaphores(owner,', 'auto timer = Eden::Performance::VulkanTimer(4);\n        const VkResult result = dld->vkWaitSemaphores(owner,'),
    ('return dld->vkDeviceWaitIdle(handle);', 'auto timer = Eden::Performance::VulkanTimer(5);\n        return dld->vkDeviceWaitIdle(handle);'),
    ('''inline void Check(VkResult result) {
    if (result != VK_SUCCESS) {
        throw Exception(result);''', '''inline void Check(VkResult result, const char* file = __builtin_FILE(),
                  int line = __builtin_LINE(), const char* operation = __builtin_FUNCTION()) {
    if (result != VK_SUCCESS) {
        std::fprintf(stderr, "[ProsperoEden] Vulkan failure: %s:%d (%s) VkResult=%d\\n",
                     file, line, operation, static_cast<int>(result));
        throw Exception(result);'''),
])
adapt('src/video_core/vulkan_common/vulkan_wrapper.cpp', 'vulkan_wrapper.cpp', [
    ('#include "video_core/vulkan_common/vulkan_wrapper.h"', '#include "video_core/vulkan_common/vulkan_wrapper.h"\n#include "performance.h"'),
    ('auto const result = dld->vkCreateGraphicsPipelines(', 'auto timer = Eden::Performance::VulkanTimer(0);\n    auto const result = dld->vkCreateGraphicsPipelines('),
    ('Check(dld->vkCreateComputePipelines(', 'auto timer = Eden::Performance::VulkanTimer(1);\n    Check(dld->vkCreateComputePipelines('),
])
download_source = (source / 'src/video_core/texture_cache/texture_cache.h').read_text()
download_begin = download_source.index('void TextureCache<P>::DownloadMemory(DAddr cpu_addr, size_t size)')
download_loop = download_source.index('    for (const ImageId image_id : images) {', download_begin)
download_prefix = download_source[download_begin:download_loop]
# Reuse DeleteImage's exact accounting to stop lookahead when its existing
# pressure policy changes. Fail on source drift rather than inventing a budget.
delete_begin = download_source.index('    if (image.HasScaled()) {', download_source.index('void TextureCache<P>::DeleteImage('))
delete_end = download_source.index('    const GPUVAddr gpu_addr', delete_begin)
reclaimed_bytes = download_source[delete_begin:delete_end].replace('total_used_memory -=', 'bytes +=')
gc_begin = download_source.index('void TextureCache<P>::RunGarbageCollector() {')
gc_end = download_source.index('\ntemplate <class P>', gc_begin)
gc_original = download_source[gc_begin:gc_end]
gc = gc_original
gc_setup = '''    const auto ReclaimedBytes = [&](const ImageBase& image) {
        u64 bytes = 0;
''' + reclaimed_bytes + '''        return bytes;
    };
''' + (vulkan_oracle / 'vulkan_gc_downloads.inc').read_text()
for old, new in [
    ('    const auto Cleanup = [this, &num_iterations, &high_priority_mode, &aggressive_mode]',
     gc_setup + '\n    const auto Cleanup = [&, this]'),
    ('        if (must_download) {', '        if (must_download && !UsePrefetched(image_id, image)) {'),
    ('(!high_priority_mode && must_download)) {', '(!DirtyEvictions() && must_download)) {'),
    ('    Configure(false);', '    Configure(false);\n    PrefetchDownloads();'),
    ('        Configure(true);', '        Configure(true);\n        PrefetchDownloads();'),
]:
    if gc.count(old) != 1:
        raise RuntimeError(f'Pinned GC anchor changed: {old}')
    gc = gc.replace(old, new)
# R439: independently bound visits and count actual evictions; reversible.
for old, new in [
    ("    size_t num_iterations = 0;", "    size_t num_iterations = 0;\n    size_t num_scanned = 0;\n    size_t total_scanned = 0;\n    size_t skipped = 0;\n    size_t evicted = 0;\n    constexpr size_t max_scanned = 8192;"),
    ("        if (num_iterations == 0) {\n            return true;\n        }\n        --num_iterations;", "        if (num_iterations == 0 || num_scanned >= max_scanned) {\n            return true;\n        }\n        ++num_scanned;\n        ++total_scanned;\n        if (::Eden::Performance::gc_count_visits.load(std::memory_order_relaxed)) {\n            --num_iterations;\n        }"),
    ("        if (True(image.flags & ImageFlagBits::IsDecoding)) {\n            return false;\n        }", "        if (True(image.flags & ImageFlagBits::IsDecoding)) {\n            ++skipped;\n            return false;\n        }"),
    ("        if ((!aggressive_mode && True(image.flags & ImageFlagBits::CostlyLoad)) || (!DirtyEvictions() && must_download)) {\n            return false;\n        }", "        if ((!aggressive_mode && True(image.flags & ImageFlagBits::CostlyLoad)) || (!DirtyEvictions() && must_download)) {\n            ++skipped;\n            return false;\n        }\n        if (!::Eden::Performance::gc_count_visits.load(std::memory_order_relaxed)) {\n            --num_iterations;\n        }"),
    ("        DeleteImage(image_id, image.scale_tick > frame_tick + 5);", "        DeleteImage(image_id, image.scale_tick > frame_tick + 5);\n        ++evicted;"),
    ("        Configure(true);\n        PrefetchDownloads();", "        Configure(true);\n        num_scanned = 0; // independent scan allowance for the aggressive pass\n        PrefetchDownloads();"),
]:
    if gc.count(old) != 1:
        raise RuntimeError(f'Pinned GC scan anchor changed: {old[:80]}')
    gc = gc.replace(old, new)
gc_ending = "    }\n}\n"
if not gc.endswith(gc_ending):
    raise RuntimeError('Pinned GC scan collector ending changed')
gc = gc[:-len(gc_ending)] + "    }\n    if constexpr (std::is_same_v<Runtime, Vulkan::TextureCacheRuntime>) {\n        if (::Eden::Performance::texture_budget_log.load(std::memory_order_relaxed) && frame_tick % 300 == 0)\n            std::printf(\"EDEN_VULKAN_GC_SCAN frame=%llu visits=%zu skipped=%zu evicted=%zu cap=%zu\\n\",\n                        static_cast<unsigned long long>(frame_tick), total_scanned, skipped, evicted, max_scanned);\n    }\n}\n"
# Upstream u64 frame_tick starts at zero and subtracts ages 10/25/50.
# It relied on unsigned wrap plus the pinned LRU signed comparison as an
# accidental startup grace period. Replace with a saturated cutoff and
# explicit age guards for both cleanup passes and Vulkan prefetch.
unsafe_cutoff = "frame_tick - ticks_to_destroy"
if gc.count(unsafe_cutoff) != 3:
    raise RuntimeError("Pinned GC needs three safe LRU cutoffs: prefetch and both cleanup passes")
gc = gc.replace(unsafe_cutoff,
                "::Eden::VulkanMemory::OldestEvictionTick(frame_tick, ticks_to_destroy)")
# The pinned LeastRecentlyUsedCache::ForEachItemBelow uses an inclusive
# comparison. Passing a saturated zero WITHOUT a guard would evict textures
# created at frame 0! Wait for the requested age before touching any entries.
cleanup_cutoff = ("    lru_cache.ForEachItemBelow("
                  "::Eden::VulkanMemory::OldestEvictionTick(frame_tick, ticks_to_destroy), Cleanup);")
if gc.count(cleanup_cutoff) != 2:
    raise RuntimeError("Pinned GC must preserve both cleanup passes")
gc = gc.replace(cleanup_cutoff,
                "    if (frame_tick >= ticks_to_destroy) {\n"
                "        lru_cache.ForEachItemBelow("
                "::Eden::VulkanMemory::OldestEvictionTick(frame_tick, ticks_to_destroy), Cleanup);\n"
                "    }")
# F07: bound kernel-backed dirty-GC pressure probes while the texture mutex
# is held. Keep the desktop path and the historical pinned GC oracle intact.
for old, new in [
    ("    const auto DirtyEvictions = [&] {\n        return high_priority_mode &&\n               (total_used_memory >= critical_memory || !::Eden::Performance::KeepDirtyTextures());\n    };", "    const auto DirtyEvictions = [&] {\n        return high_priority_mode &&\n               (total_used_memory >= critical_memory || !::Eden::Performance::KeepDirtyTextures());\n    };\n#ifdef PS5_NATIVE\n    // Keep the expensive direct-memory pressure probe out of every dirty LRU\n    // candidate under texture_cache.mutex. Recheck after at most eight visits,\n    // immediately after a deletion, and at the critical-pass boundary.\n    // Critical pressure always bypasses the cached answer.\n    constexpr unsigned kDirtyProbeReuse = 8;\n    unsigned dirty_probe_remaining = 0;\n    bool dirty_evict_cached = false;\n    const auto DirtyEvictionsForCleanup = [&]() {\n        if (!high_priority_mode) return false;\n        if (total_used_memory >= critical_memory) return true;\n        if (dirty_probe_remaining == 0) {\n            dirty_evict_cached = !::Eden::Performance::KeepDirtyTextures();\n            dirty_probe_remaining = kDirtyProbeReuse;\n        }\n        --dirty_probe_remaining;\n        return dirty_evict_cached;\n    };\n#endif"),
    ("        ++evicted;\n        if (aggressive_mode", "        ++evicted;\n#ifdef PS5_NATIVE\n        dirty_probe_remaining = 0;\n#endif\n        if (aggressive_mode"),
    ("        Configure(true);\n        num_scanned = 0; // independent scan allowance for the aggressive pass", "        Configure(true);\n#ifdef PS5_NATIVE\n        dirty_probe_remaining = 0;\n#endif\n        num_scanned = 0; // independent scan allowance for the aggressive pass"),
]:
    if gc.count(old) != 1:
        raise RuntimeError(f'Pinned native GC pressure-probe anchor changed: {old[:72]}')
    gc = gc.replace(old, new)

texture_costs = []
for signature, index in (
    ('RunGarbageCollector()', 13), ('DownloadMemory(DAddr cpu_addr, size_t size)', 14),
    ('PopAsyncFlushes()', 15),
):
    anchor = f'void TextureCache<P>::{signature} {{'
    scope = f'''
    std::optional<Eden::Performance::Timer> cost_timer;
    if constexpr (std::is_same_v<Runtime, Vulkan::TextureCacheRuntime>) {{
        if (Eden::Performance::vulkan_cost_enabled.load(std::memory_order_relaxed))
            cost_timer.emplace(Eden::Performance::vulkan_api[{index}]);
    }}
'''
    if index == 13:
        scope += '''    if constexpr (std::is_same_v<Runtime, Vulkan::TextureCacheRuntime>) {
        if ((cost_timer || Eden::Performance::texture_budget_log.load(std::memory_order_relaxed)) &&
            frame_tick % 300 == 0)
            std::printf("EDEN_VULKAN_TEXTURE_BUDGET frame=%llu usage=%llu expected=%llu critical=%llu "
                        "keep_dirty=%d memory_short=%d\\n",
                        static_cast<unsigned long long>(frame_tick),
                        static_cast<unsigned long long>(total_used_memory),
                        static_cast<unsigned long long>(expected_memory),
                        static_cast<unsigned long long>(critical_memory),
                        int(Eden::Performance::gc_keep_dirty.load(std::memory_order_relaxed)),
                        int(Eden::Performance::graphics_memory_short.load(std::memory_order_relaxed)));
    }
'''
    texture_costs.append((anchor, anchor + scope))
# R322: the old 1440p samples showed FillImageViews long outliers but
# could not attribute them to CPU image upload, alias scanning, or copying.
# Profile only if the R310 sampled draw TLS flag is true. The standard
# non-diagnostic code makes no clock reads and changes no image semantics.
texture_costs.extend([
    ('    image.flags &= ~ImageFlagBits::CpuModified;\n\n    TrackImage(image, image_id);',
     '#ifdef PS5_NATIVE\n'
     '    ::Eden::Performance::CachePhaseTimer upload_phase{\n'
     '        ::Eden::Performance::CachePhase::TextureCpuRefresh};\n'
     '#endif\n'
     '    image.flags &= ~ImageFlagBits::CpuModified;\n\n    TrackImage(image, image_id);'),
    ('    bool any_rescaled = True(image.flags & ImageFlagBits::Rescaled);\n'
     '    bool any_modified = True(image.flags & ImageFlagBits::GpuModified);',
     '#ifdef PS5_NATIVE\n'
     '    ::Eden::Performance::CachePhaseTimer alias_scan_phase{\n'
     '        ::Eden::Performance::CachePhase::TextureAliasScan};\n'
     '#endif\n'
     '    bool any_rescaled = True(image.flags & ImageFlagBits::Rescaled);\n'
     '    bool any_modified = True(image.flags & ImageFlagBits::GpuModified);'),
    ('    if (aliased_images.empty()) {\n'
     '        return;\n'
     '    }\n'
     '    const bool can_rescale = ImageCanRescale(image);',
     '    if (aliased_images.empty()) {\n'
     '        return;\n'
     '    }\n'
     '#ifdef PS5_NATIVE\n'
     '    alias_scan_phase.Stop();\n'
     '    ::Eden::Performance::CachePhaseTimer alias_copy_phase{\n'
     '        ::Eden::Performance::CachePhase::TextureAliasCopy};\n'
     '#endif\n'
     '    const bool can_rescale = ImageCanRescale(image);'),
])
# F07: distinguish the three unavoidable steps of a CPU-modified texture
# refresh, sampled inside its existing lock. Keep pinned-source generation
# authoritative: never hand-patch only the emitted texture_cache.h.
texture_costs.append((
    "    auto staging = runtime.UploadStagingBuffer(MapSizeBytes(image));\n    UploadImageContents(image, staging);\n    runtime.InsertUploadMemoryBarrier();",
    "#ifdef PS5_NATIVE\n    // F07: isolate staging allocation, CPU decode/unswizzle and the required\n    // upload barrier within the existing 1-in-16 sampled refresh.\n    // No lock, image flag, command order or guest-visible upload is changed.\n    ::Eden::Performance::CachePhaseTimer staging_phase{\n        ::Eden::Performance::CachePhase::TextureUploadStaging};\n#endif\n    auto staging = runtime.UploadStagingBuffer(MapSizeBytes(image));\n#ifdef PS5_NATIVE\n    staging_phase.Stop();\n    ::Eden::Performance::CachePhaseTimer contents_phase{\n        ::Eden::Performance::CachePhase::TextureUploadContents};\n#endif\n    UploadImageContents(image, staging);\n#ifdef PS5_NATIVE\n    contents_phase.Stop();\n    ::Eden::Performance::CachePhaseTimer barrier_phase{\n        ::Eden::Performance::CachePhase::TextureUploadBarrier};\n#endif\n    runtime.InsertUploadMemoryBarrier();\n#ifdef PS5_NATIVE\n    barrier_phase.Stop();\n#endif"
))

adapt('src/video_core/texture_cache/texture_cache.h',
      'vulkan-cache/video_core/texture_cache/texture_cache.h', [
    ('namespace VideoCommon {', '#include "performance.h"\n#include "image_pages.h"\n#include "vulkan_gc_budget.h"\n#include "common/scope_exit.h"\nnamespace Vulkan { class TextureCacheRuntime; }\n\nnamespace VideoCommon {'),
    # Retired images without a view have no cached view/framebuffer
    # references. Preserve all deletion/flush behavior for real view IDs.
    ("void TextureCache<P>::RemoveImageViewReferences(std::span<const ImageViewId> removed_views) {\n    for (size_t c : active_channel_ids) {", "void TextureCache<P>::RemoveImageViewReferences(std::span<const ImageViewId> removed_views) {\n#ifdef PS5_NATIVE\n    // Images created and retired without any view cannot be in a channel's\n    // descriptor-to-view map. Avoid scanning every channel on that path.\n    if (removed_views.empty()) {\n        return;\n    }\n#endif\n    for (size_t c : active_channel_ids) {"),
    ("void TextureCache<P>::RemoveFramebuffers(std::span<const ImageViewId> removed_views) {\n    runtime.FlushDeferredClear();", "void TextureCache<P>::RemoveFramebuffers(std::span<const ImageViewId> removed_views) {\n#ifdef PS5_NATIVE\n    // No framebuffer can contain an absent view. Do not flush deferred\n    // clears belonging to other render targets or scan the framebuffer map.\n    if (removed_views.empty()) {\n        return;\n    }\n#endif\n    runtime.FlushDeferredClear();"),
    # Native TIC/TSC table descriptors may outlive their channel map entry.
    # Restore absent cached view/sampler mappings rather than dereferencing end().
    # Keep all normal cached view reads and invalid TIC recovery unchanged.
    ("    return channel_state->sampler_ids.find(map_index)->second;", "#ifdef PS5_NATIVE\n    // A descriptor table can retain its bytes after a channel map entry\n    // is evicted/rebuilt. Never dereference a missing sampler mapping.\n    const auto it = channel_state->sampler_ids.find(map_index);\n    if (it == channel_state->sampler_ids.end()) {\n        const auto id = FindSampler(descriptor, compute);\n        channel_state->sampler_ids.insert_or_assign(map_index, id);\n        return id;\n    }\n    return it->second;\n#else\n    return channel_state->sampler_ids.find(map_index)->second;\n#endif"),
    ("    // Only revalidate previously NULL views: common valid views retain the\n    // original zero-overhead fast path and sparse TICs retain their semantics.\n    const bool remapped_cached_view =\n        it != channel_state->image_view_ids.end() && is_remapped_view(it->second);\n    if ((it == channel_state->image_view_ids.end() ||\n         it->second == NULL_IMAGE_VIEW_ID || remapped_cached_view) &&\n        IsValidEntry(*gpu_memory, descriptor)) {", "    // Revalidate NULL views and recover an unexpectedly absent channel\n    // mapping. Valid cached views retain their normal fast path.\n    const bool remapped_cached_view =\n        it != channel_state->image_view_ids.end() && is_remapped_view(it->second);\n    if ((it == channel_state->image_view_ids.end() ||\n         it->second == NULL_IMAGE_VIEW_ID || remapped_cached_view) &&\n        IsValidEntry(*gpu_memory, descriptor)) {"),
    ("        channel_state->image_view_ids.insert_or_assign(map_index, pair->second);\n        return pair->second;\n    }\n    if (it == channel_state->image_view_ids.end() || remapped_cached_view) {\n        // If its backing is not resident, publish NULL until it returns.\n        if (remapped_cached_view) {\n            ++texture_bindings_serial;\n        }\n        channel_state->image_view_ids.insert_or_assign(map_index, NULL_IMAGE_VIEW_ID);\n        return NULL_IMAGE_VIEW_ID;\n    }\n#endif\n    if (it->second != NULL_IMAGE_VIEW_ID)\n        PrepareImageView(it->second, false, false);\n    return it->second;", "        channel_state->image_view_ids.insert_or_assign(map_index, pair->second);\n        return pair->second;\n    }\n    // A cached, invalid TIC is allowed to have no live view. Materialize\n    // the NULL mapping so later page residency can revive it safely.\n    if (it == channel_state->image_view_ids.end() || remapped_cached_view) {\n        // If its backing is not resident, publish NULL until it returns.\n        if (remapped_cached_view) {\n            ++texture_bindings_serial;\n        }\n        channel_state->image_view_ids.insert_or_assign(map_index, NULL_IMAGE_VIEW_ID);\n        return NULL_IMAGE_VIEW_ID;\n    }\n#endif\n    if (it->second != NULL_IMAGE_VIEW_ID)\n        PrepareImageView(it->second, false, false);\n    return it->second;"),
    # R433: publish monotonic page occupancy before a slot-map entry exists.
    ("        auto map_id =\n            slot_map_views.insert(image.gpu_addr, image.cpu_addr, image.guest_size_bytes, image_id);", "        ::Eden::ImagePages::Mark(image.cpu_addr, image.guest_size_bytes);\n        auto map_id =\n            slot_map_views.insert(image.gpu_addr, image.cpu_addr, image.guest_size_bytes, image_id);"),
    ("            auto map_id = slot_map_views.insert(gpu_addr, cpu_addr, size, image_id);", "            ::Eden::ImagePages::Mark(cpu_addr, size);\n            auto map_id = slot_map_views.insert(gpu_addr, cpu_addr, size, image_id);"),
    (download_prefix, download_prefix + (vulkan_oracle / 'vulkan_download_batch.inc').read_text() + '\n'),
    (gc_original, gc),
    # Vulkan's total_used_memory may be a driver-reported snapshot rather than
    # the exact sum of per-image logical costs. Never allow a DeleteImage
    # subtraction to wrap u64 into enormous phantom VRAM pressure. OpenGL's
    # accounting remains unchanged.
    ('total_used_memory -= GetScaledImageSizeBytes(image);',
     'if constexpr (std::is_same_v<Runtime, Vulkan::TextureCacheRuntime>) {\n'
     '            total_used_memory = ::Eden::VulkanMemory::AfterProjectedEviction(\n'
     '                total_used_memory, GetScaledImageSizeBytes(image));\n'
     '        } else {\n'
     '            total_used_memory -= GetScaledImageSizeBytes(image);\n'
     '        }'),
    ('total_used_memory -= Common::AlignUp(tentative_size, 1024);',
     'if constexpr (std::is_same_v<Runtime, Vulkan::TextureCacheRuntime>) {\n'
     '        total_used_memory = ::Eden::VulkanMemory::AfterProjectedEviction(\n'
     '            total_used_memory, Common::AlignUp(tentative_size, 1024));\n'
     '    } else {\n'
     '        total_used_memory -= Common::AlignUp(tentative_size, 1024);\n'
     '    }'),
    # RADV reports all Vulkan allocations, not just cached textures. A game's
    # measured ~1.9 GiB working set triggered dirty eviction at the old 1.6 GiB
    # threshold despite a 4 GiB budget. Retain 40% headroom; keep the original
    # critical threshold and minimum 1 GiB spacing. OpenGL remains unchanged.
    ('const s64 min_vacancy_expected = (6 * mem_threshold) / 10;',
     'const s64 min_vacancy_expected =\n            ((std::is_same_v<Runtime, Vulkan::TextureCacheRuntime> ? 4 : 6) * mem_threshold) / 10;'),
] + texture_costs)

# R323 PS5: the Vulkan descriptor ring can call scheduler.Wait(previous
# frame tick) inside ConfigureDraw while BOTH rasterizer cache mutexes are
# held. Pre-drain that SAME frame fence before the locks only for graphics
# pipelines with descriptor-buffer payloads. No change to over-capacity GPU
# Finish fallback or to the original Allocate memory-ordering checks.
adapt('src/video_core/renderer_vulkan/vk_descriptor_buffer.h',
      'include/video_core/renderer_vulkan/vk_descriptor_buffer.h', [
    # Reject oversized descriptor layouts BEFORE alignment can wrap VkDeviceSize.
    ('    [[nodiscard]] bool CanAllocate(VkDeviceSize size) const noexcept {\n'
     '        return Common::AlignUp(size, alignment) <= chunk_capacity;\n'
     '    }',
     '    [[nodiscard]] bool CanAllocate(VkDeviceSize size) const noexcept {\n'
     '        // Validate unaligned size before AlignUp can overflow VkDeviceSize.\n'
     '        return size <= chunk_capacity && Common::AlignUp(size, alignment) <= chunk_capacity;\n'
     '    }'),
    ('    void TouchFrame(Scheduler& scheduler);',
     '    void TouchFrame(Scheduler& scheduler);\n'
     '#ifdef PS5_NATIVE\n'
     '    [[nodiscard]] bool PreflightFrameReuse(Scheduler& scheduler);\n'
     '    [[nodiscard]] bool PreflightCapacity(Scheduler& scheduler, VkDeviceSize size);\n'
     '#endif'),
])
adapt('src/video_core/renderer_vulkan/vk_descriptor_buffer.cpp',
      'vulkan_descriptor_buffer.cpp', [
    ('void DescriptorBufferRing::TouchFrame(Scheduler& scheduler) {\n'
     '    frame_ticks[frame_index] = scheduler.CurrentTick();\n'
     '}',
     '''void DescriptorBufferRing::TouchFrame(Scheduler& scheduler) {
    frame_ticks[frame_index] = scheduler.CurrentTick();
}
#ifdef PS5_NATIVE
bool DescriptorBufferRing::PreflightFrameReuse(Scheduler& scheduler) {
    // This is the GPU-owner thread, called before the paired buffer/texture
    // cache locks. Reuse the EXACT previous-frame tick the Allocate fallback
    // would wait for; preserve fallback in case no preflight ran.
    if (!frame_reused || chunks.empty())
        return false;
    // Only an unsignalled frame slot requires an expensive fence wait.
    // Returning false for already-retired slots avoids forcing a shader
    // reselection and guest invalidation flush on the first draw each frame.
    const u64 old_tick = frame_ticks[frame_index];
    if (old_tick == 0 || scheduler.IsFree(old_tick)) {
        frame_reused = false;
        return false;
    }
    scheduler.Wait(old_tick);
    frame_reused = false;
    return true;
}

bool DescriptorBufferRing::PreflightCapacity(Scheduler& scheduler,
                                             VkDeviceSize size) {
    // A previous generation or different payload count guarantees allocation.
    if (chunks.empty() || frame_reused || size == 0 || !CanAllocate(size))
        return false;
    const VkDeviceSize needed{Common::AlignUp(size, alignment)};
    if (needed <= chunk_capacity - cursor || chunk_cursor + 1 < chunks_per_frame)
        return false;
    // The same GPU completion as Allocate's full-ring fallback, BEFORE the
    // guest buffer and texture cache locks: no early GPU memory reuse.
    scheduler.Finish();
    chunk_cursor = 0;
    cursor = 0;
    ++generation;
    return true;
}
#endif'''),
])

# R313: adapt the original graphics pipeline ABI so the fast-first object
# owns both a valid first-use handle and a finished optimized Vulkan handle.
# No preloaded disk pipelines are rebuilt: the constructor's worker_thread
# is null for those. OptimizeState is allocated lazily, not per cached pipeline.
adapt('src/video_core/renderer_vulkan/vk_graphics_pipeline.h',
      'include/video_core/renderer_vulkan/vk_graphics_pipeline.h', [
    ('    [[nodiscard]] bool IsBuilt() const noexcept {\n'
     '        return is_built.load(std::memory_order::relaxed);\n    }',
     '    [[nodiscard]] bool IsBuilt() const noexcept {\n'
     '        return is_built.load(std::memory_order::relaxed);\n    }\n\n'
     '    // Queued worker checks pipeline readiness AFTER async build wait.\n'
     '    [[nodiscard]] bool CanExecuteDraw() const noexcept {\n'
     '        if (!is_built.load(std::memory_order::acquire)) return false;\n'
     '#ifdef PS5_NATIVE\n'
     '        // A fast-first driver build can fail without throwing while its\n'
     '        // independently queued optimized variant succeeds. ConfigureDraw\n'
     '        // already binds that published variant; do not discard the following\n'
     '        // Draw/DrawIndirect simply because the initial handle is null.\n'
     '        // The release/acquire flag publishes the optimized VkPipeline.\n'
     '        return static_cast<bool>(pipeline) ||\n'
     '               optimized_ready.load(std::memory_order_acquire);\n'
     '#else\n'
     '        return static_cast<bool>(pipeline);\n'
     '#endif\n'
     '    }\n'
     '    // Native Vulkan worker must use the pipeline actually selected by its\n'
     '    // preceding ConfigureDraw callback, not a variant published afterward.\n'
     '    // Desktop keeps the original readiness check.\n'
     '    [[nodiscard]] bool CanExecuteRecordedDraw() const noexcept {\n'
     '#ifdef PS5_NATIVE\n'
     '        return worker_draw_bind_valid;\n'
     '#else\n'
     '        return CanExecuteDraw();\n'
     '#endif\n'
     '    }'),
    ('    GraphicsPipeline(const GraphicsPipeline&) = delete;',
     '    GraphicsPipeline(const GraphicsPipeline&) = delete;\n    ~GraphicsPipeline();'),
    ("    void AddTransition(GraphicsPipeline* transition);", "    void AddTransition(GraphicsPipeline* transition);\n#ifdef PS5_NATIVE\n    // Reserve graphics descriptor scratch before acquiring both guest caches.\n    // No descriptor content is read outside the locks.\n    void PreflightDescriptorScratch();\n#endif"),
    ('    void MakePipeline(VkRenderPass render_pass);',
     '    void MakePipeline(VkRenderPass render_pass, VkPipelineCreateFlags extra_flags = 0,\n'
     '                      vk::Pipeline* target = nullptr);\n'
     '    void QueueOptimizedPipeline(VkRenderPass render_pass);'),
    ('    vk::Pipeline pipeline;',
     '    vk::Pipeline pipeline;\n'
     '    struct OptimizeState {\n'
     '        std::mutex mutex;\n'
     '        std::condition_variable done;\n'
     '        bool cancelled{false};\n'
     '        bool running{false};\n'
     '    };\n'
     '    std::shared_ptr<OptimizeState> optimize_state; // allocated ONLY for active R313 builds\n'
     '    vk::Pipeline optimized_pipeline;\n'
     '    std::atomic_bool optimized_ready{false};\n'
     '#ifdef PS5_NATIVE\n'
     '    // Set/read only on the ordered Vulkan command worker, immediately before\n'
     '    // each draw callback. Never use the later optimized_ready publication as\n'
     '    // proof that an earlier ConfigureDraw actually bound the recovered handle.\n'
     '    bool worker_draw_bind_valid{};\n'
     '#endif'),
    # Guard pre-drain to pipelines that can actually allocate descriptors.
    ('    bool HasDynamicVertexInput() const noexcept { return key.state.dynamic_vertex_input; }',
     '    bool HasDynamicVertexInput() const noexcept { return key.state.dynamic_vertex_input; }\n'
     '#ifdef PS5_NATIVE\n'
     '    [[nodiscard]] bool CanUseDescriptorBuffer() const noexcept {\n'
     '        return uses_descriptor_buffer && descriptor_set_layout;\n'
     '    }\n'
     '    [[nodiscard]] bool HasDescriptorEntries() const noexcept {\n'
     '        return num_descriptor_entries != 0;\n'
     '    }\n'
     '    [[nodiscard]] size_t DescriptorEntryReservation() const noexcept {\n'
     '        return num_descriptor_entries != 0 ? num_descriptor_entries : 0x400;\n'
     '    }\n'
     '    [[nodiscard]] VkDeviceSize DescriptorRingPreflightSize() const noexcept {\n        // Before reading guest descriptors, these are the only two conditions\n        // sufficient to PROVE the old descriptor allocation cannot be reused.\n        return CanUseDescriptorBuffer() &&\n               (last_descriptor_buffer_generation != descriptor_buffer_ring.CurrentGeneration() ||\n                last_descriptor_payload.size() != num_descriptor_entries)\n                   ? descriptor_buffer_layout.size : 0;\n    }\n'
     '#endif'),
    # Immutable image-stage presence flag prevents empty helper work on
    # zero-texture passes without disturbing stage buffer bindings.
    ("    u32 num_textures{};", "    u32 num_textures{};\n    std::array<bool, NUM_STAGES> stage_has_image_bindings{};\n    std::array<size_t, NUM_STAGES> stage_sampled_view_counts{};\n    std::array<size_t, NUM_STAGES> stage_storage_view_counts{};"),
    ('#include <atomic>', '#include <atomic>\n#include <memory>'),
])


# F07 native CPU hot path: a long transition list must not rescan dozens of
# heavyweight GraphicsPipelineCacheKey objects on each HUD/scene switch.
# The index is stable across vector reallocation; the small-list path and all
# non-PS5 builds retain the original lookup. No shader, draw or lock changes.
transition_header = output / 'include/video_core/renderer_vulkan/vk_graphics_pipeline.h'
transition_source = transition_header.read_text()
transition_next_old = "    [[nodiscard]] GraphicsPipeline* Next(const GraphicsPipelineCacheKey& current_key) noexcept {\n        if (key == current_key) {\n            return this;\n        }\n        const auto it{std::find(transition_keys.begin(), transition_keys.end(), current_key)};\n        return it != transition_keys.end() ? transitions[std::distance(transition_keys.begin(), it)]\n                                           : nullptr;\n    }"
transition_next_new = "    [[nodiscard]] GraphicsPipeline* Next(const GraphicsPipelineCacheKey& current_key) noexcept {\n        if (key == current_key) {\n            return this;\n        }\n#ifdef PS5_NATIVE\n        // Two frequent overlay/HUD edges avoid rescanning a large transition\n        // graph on each alternating draw. Store indices, never vector pointers.\n        if (transition_keys.size() >= 8) {\n            const size_t hot = hot_transition_indices[0];\n            if (hot < transition_keys.size() && transition_keys[hot] == current_key) {\n                return transitions[hot];\n            }\n            const size_t other = hot_transition_indices[1];\n            if (other != hot && other < transition_keys.size() &&\n                transition_keys[other] == current_key) {\n                std::swap(hot_transition_indices[0], hot_transition_indices[1]);\n                return transitions[other];\n            }\n        }\n#endif\n        const auto it{std::find(transition_keys.begin(), transition_keys.end(), current_key)};\n        if (it == transition_keys.end()) {\n            return nullptr;\n        }\n        const size_t index{static_cast<size_t>(std::distance(transition_keys.begin(), it))};\n#ifdef PS5_NATIVE\n        hot_transition_indices[1] = hot_transition_indices[0];\n        hot_transition_indices[0] = index;\n#endif\n        return transitions[index];\n    }"
transition_member_old = "    std::vector<GraphicsPipeline*> transitions;"
transition_member_new = "    std::vector<GraphicsPipeline*> transitions;\n#ifdef PS5_NATIVE\n    // GPU owner only. Two valid indices remain stable across vector growth.\n    std::array<size_t, 2> hot_transition_indices{};\n#endif"
if transition_source.count(transition_next_old) != 1 or transition_source.count(transition_member_old) != 1:
    raise RuntimeError('F07 graphics transition header source anchor drift')
transition_header.write_text(
    transition_source.replace(transition_next_old, transition_next_new, 1)
                     .replace(transition_member_old, transition_member_new, 1))

# F07: SCOPE_EXIT release-publishes the constructed Vulkan pipeline.
# IsBuilt is also queried before reading the non-atomic Vulkan handle,
# so its read must acquire that release rather than merely inspect a flag.
# No wait, mutex or shader-build scheduling changes.
ready_header = output / 'include/video_core/renderer_vulkan/vk_graphics_pipeline.h'
ready_source = ready_header.read_text()
ready_old = "    [[nodiscard]] bool IsBuilt() const noexcept {\n        return is_built.load(std::memory_order::relaxed);\n    }"
ready_new = "    [[nodiscard]] bool IsBuilt() const noexcept {\n        // Matches the release store in the builder's SCOPE_EXIT. Consumers\n        // can only inspect the constructed VkPipeline after acquiring it.\n        return is_built.load(std::memory_order::acquire);\n    }"
if ready_source.count(ready_old) != 1:
    raise RuntimeError('F07 IsBuilt publication source anchor drift')
ready_header.write_text(ready_source.replace(ready_old, ready_new, 1))

# Adapted from Mihawk PS5 fast-first pipelines with important corrections:
# * one optimizer worker to avoid contending with guest JIT cores
# * only runtime-discovered pipelines, not preloaded disk cache entries
# * no illegal VulkanTimer(24): timing array has 24 entries, indexed 0..23
# * lazy state so optimized baseline and disk-loaded pipelines add no heap work
# * cancellation is checked BEFORE touching an asynchronously destroyed pipeline
optimize_worker = """
namespace {
Common::ThreadWorker& OptimizeWorker() {
    static Common::ThreadWorker worker(1, "VkPipelineOptimize");
    return worker;
}
} // namespace

GraphicsPipeline::~GraphicsPipeline() {
    // The initial Vulkan builder also captures 'this'. It can still be in
    // the first-use queue when the pipeline cache evicts this object.
    // Join its completion BEFORE reading optimize_state, which the builder
    // may create when it schedules an optional optimized rebuild.
    if (!is_built.load(std::memory_order_acquire)) {
        std::unique_lock build_lock{build_mutex};
        build_condvar.wait(build_lock, [this] {
            return is_built.load(std::memory_order_acquire);
        });
    }
    const auto state = optimize_state;
    if (!state) return;
    std::unique_lock lock{state->mutex};
    state->cancelled = true;
    state->done.wait(lock, [&] { return !state->running; });
}

void GraphicsPipeline::QueueOptimizedPipeline(VkRenderPass render_pass) {
    optimize_state = std::make_shared<OptimizeState>();
    const auto state = optimize_state;
    // An accepted optimization is in flight even while queued. Otherwise the
    // owner can be destroyed before the worker begins, leaving a dangling 'this'.
    {
        std::scoped_lock lock{state->mutex};
        state->running = true;
    }
    try {
        OptimizeWorker().QueueWork([this, state, render_pass] {
        // Always release a pending/active job, including early cancellation and exceptions.
        struct CompletionGuard {
            const std::shared_ptr<OptimizeState>& state;
            ~CompletionGuard() {
                {
                    std::scoped_lock lock{state->mutex};
                    state->running = false;
                }
                state->done.notify_all();
            }
        } completion{state};
#ifdef PS5_NATIVE
        ::Eden::Performance::ProbeSchedulerOnce("VkPipelineOptimize");
        // R444: Speculative rebuilds must not compete with first-use shaders.
        // The prior 48 ms deadline could expire while cold gameplay pipelines
        // were still compiling, adding a second Vulkan compiler at the worst
        // moment. This background-only wait takes no GPU/guest locks.
        // Checking cancellation on each cycle guarantees prompt title teardown
        // even when a first-use shader worker remains stuck.
        while (pending_first_use_graphics_builds.load(std::memory_order_acquire) != 0) {
            {
                std::scoped_lock lock{state->mutex};
                if (state->cancelled) return;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
        }
#endif
        {
            std::scoped_lock lock{state->mutex};
            if (state->cancelled) return;
        }
        try {
            MakePipeline(render_pass, 0, &optimized_pipeline);
            // A non-throwing driver failure may still produce a null handle.
            // Keep using the working first-use pipeline in that case.
            if (optimized_pipeline) {
                optimized_ready.store(true, std::memory_order_release);
            }
        } catch (const std::exception& exception) {
            // Keep the already-built, valid first-use pipeline after any
            // optimization failure. Completion must always release shutdown.
            LOG_WARNING(Render_Vulkan, "Optimized pipeline rebuild failed: {}", exception.what());
        } catch (...) {
            LOG_WARNING(Render_Vulkan, "Optimized pipeline rebuild failed: unknown exception");
        }
        });
    } catch (...) {
        // QueueWork failed before the worker accepted ownership. Do not strand
        // a pending flag that would make the destructor wait forever.
        {
            std::scoped_lock lock{state->mutex};
            state->running = false;
        }
        state->done.notify_all();
        throw;
    }
}

void GraphicsPipeline::MakePipeline(VkRenderPass render_pass, VkPipelineCreateFlags extra_flags,
                                    vk::Pipeline* target) {"""

# These costs sit outside vkCreateGraphicsPipelines: guest shader translation,
# worker readiness, and background serialization can block different threads.
# Native compute gets public immutable descriptors for pre-lock preflights.
# The upstream header has no tracked fork; keep the ABI-preserving edit in
# the pinned generated copy used alongside vk_compute_pipeline_cost.cpp.
adapt('src/video_core/renderer_vulkan/vk_compute_pipeline.h',
      'include/video_core/renderer_vulkan/vk_compute_pipeline.h', [
    ("    bool IsBound() const noexcept {\n        return static_cast<bool>(pipeline);\n    }",
     "#ifdef PS5_NATIVE\n    [[nodiscard]] bool CanUseDescriptorBuffer() const noexcept {\n        return uses_descriptor_buffer;\n    }\n    [[nodiscard]] size_t DescriptorEntryReservation() const noexcept {\n        return num_descriptor_entries != 0 ? num_descriptor_entries : 0x400;\n    }\n    [[nodiscard]] VkDeviceSize DescriptorRingPreflightSize() const noexcept {\n        // Unlike graphics, every descriptor-buffer compute dispatch allocates.\n        return uses_descriptor_buffer ? descriptor_buffer_layout.size : 0;\n    }\n#endif\n    bool IsBound() const noexcept {\n        return static_cast<bool>(pipeline);\n    }"),
])

for name in ('vk_graphics_pipeline', 'vk_compute_pipeline'):
    replacements = [
        ('#include <algorithm>', '#include <algorithm>\n#include "performance.h"'),
        ('            std::unique_lock lock{build_mutex};',
         '            auto timer = Eden::Performance::VulkanTimer(16);\n            std::unique_lock lock{build_mutex};'),
        # Both graphics and compute can skip the queued wait entirely when
        # their builder already release-published the pipeline. The ready
        # check must acquire that publication, just as the queued callback does.
        ("    if (!is_built.load(std::memory_order::relaxed)) {",
         "    // Match the builder's release publication before using its pipeline handle.\n"
         "    // A ready fast path skips the queued wait, so relaxed is insufficient here.\n"
         "    if (!is_built.load(std::memory_order_acquire)) {"),
    ]
    if name == 'vk_graphics_pipeline':
        replacements.extend([
            # Pipeline construction precomputes immutable descriptor cursor
            # increments once, instead of rescanning two descriptor vectors
            # per enabled graphics stage while paired cache mutexes are held.
            ("        num_textures += Shader::NumDescriptors(info->texture_descriptors);\n        num_image_elements += Shader::NumDescriptors(info->texture_descriptors);\n        num_image_elements += Shader::NumDescriptors(info->image_descriptors);", "        // Descriptor ranges are immutable for this compiled pipeline.\n        // These two stage cursor offsets used to be rescanned per draw\n        // while both guest GPU caches were locked.\n        const size_t sampled_views = Shader::NumDescriptors(info->texture_descriptors);\n        const size_t storage_views = Shader::NumDescriptors(info->image_descriptors);\n        stage_sampled_view_counts[stage] = sampled_views;\n        stage_storage_view_counts[stage] = storage_views;\n        num_textures += sampled_views;\n        num_image_elements += sampled_views;\n        num_image_elements += storage_views;"),
            ("        texture_buffer_it += Shader::NumDescriptors(info.texture_descriptors);\n        if constexpr (Spec::has_images) {\n            texture_buffer_it += Shader::NumDescriptors(info.image_descriptors);\n        }", "        // Stage descriptor counts were recorded during construction,\n        // outside the paired guest buffer/texture cache lock.\n        texture_buffer_it += stage_sampled_view_counts[stage];\n        if constexpr (Spec::has_images) {\n            texture_buffer_it += stage_storage_view_counts[stage];\n        }"),
            # Source-proven no-image stage fast path; only stage metadata is
            # hoisted. The descriptor queue and image-view cursor are kept
            # untouched for empty stages, while bindings still execute.
            ("        stage_infos[stage] = *info;\n        enabled_uniform_buffer_masks[stage] = info->constant_buffer_mask;", "        stage_infos[stage] = *info;\n        // Immutable shader-stage metadata: avoid repeated empty descriptor\n        // walks while both guest buffer/texture caches are locked.\n        stage_has_image_bindings[stage] =\n            !info->texture_buffer_descriptors.empty() ||\n            !info->image_buffer_descriptors.empty() ||\n            !info->texture_descriptors.empty() ||\n            !info->image_descriptors.empty();\n        enabled_uniform_buffer_masks[stage] = info->constant_buffer_mask;"),
            ("        buffer_cache.BindHostStageBuffers(stage);\n        PushImageDescriptors(texture_cache, guest_descriptor_queue, stage_infos[stage], rescaling,\n                             samplers_it, views_it);\n        const auto& info{stage_infos[stage]};", "        buffer_cache.BindHostStageBuffers(stage);\n        const auto& info{stage_infos[stage]};\n        // No image or texture-buffer descriptors: PushImageDescriptors\n        // cannot change view cursors, descriptor queue or rescale constants.\n        // Uniform/storage buffer bindings above must still execute.\n        if (stage_has_image_bindings[stage]) {\n            PushImageDescriptors(texture_cache, guest_descriptor_queue, info, rescaling,\n                                 samplers_it, views_it);\n        }"),
            # R363: async failed pipeline can be dropped by the Vulkan worker
            # even after the earlier GPU-owner IsBuilt() check passed.
            ("        if (bind_pipeline) {\n            if (!pipeline) {\n                return;\n            }", "        if (bind_pipeline) {\n            if (!pipeline) {\n                // An asynchronously-built pipeline can fail after Configure's\n                // earlier IsBuilt()/pipeline check but before this worker\n                // callback executes. Count the actual GPU draw omission.\n                ::Eden::Performance::RecordGraphicsDrawDrop(\n                    ::Eden::Performance::GraphicsDrawDrop::WorkerPipelineFailed);\n                return;\n            }"),
            # R362: split the previously unaccounted ConfigureImpl costs into
            # stage texture handles, texture buffers, descriptor binds, render
            # targets, feedback-loop barriers and final graphics submission.
            # All timers are 1-in-16, nested inside the EXISTING cache mutexes.
            ("    buffer_cache.SetUniformBuffersState(enabled_uniform_buffer_masks, &uniform_buffer_sizes);", "    ::Eden::Performance::CachePhaseTimer stage_texture_phase{\n        ::Eden::Performance::CachePhase::StageTextureHandles};\n    buffer_cache.SetUniformBuffersState(enabled_uniform_buffer_masks, &uniform_buffer_sizes);"),
            ("    ASSERT(samplers.size() == num_textures);", "    ASSERT(samplers.size() == num_textures);\n    stage_texture_phase.Stop();"),
            ("    VideoCommon::ImageViewInOut* texture_buffer_it{views.data()};", "    ::Eden::Performance::CachePhaseTimer bind_texture_phase{\n        ::Eden::Performance::CachePhase::BindTextureBuffers};\n    VideoCommon::ImageViewInOut* texture_buffer_it{views.data()};"),
            ("    if (regs.transform_feedback_enabled != 0) {", "    bind_texture_phase.Stop();\n    if (regs.transform_feedback_enabled != 0) {"),
            ("    RescalingPushConstant rescaling;", "    ::Eden::Performance::CachePhaseTimer stage_descriptor_phase{\n        ::Eden::Performance::CachePhase::BindStageDescriptors};\n    RescalingPushConstant rescaling;"),
            ("    texture_cache.UpdateRenderTargets(false);", "    stage_descriptor_phase.Stop();\n    { ::Eden::Performance::CachePhaseTimer cost{\n        ::Eden::Performance::CachePhase::RefreshRenderTargets};\n        texture_cache.UpdateRenderTargets(false);\n    }"),
            ("    texture_cache.CheckFeedbackLoop(std::span<const VideoCommon::ImageViewInOut>{views.data(),\n                                                                                 views.size()});", "    { ::Eden::Performance::CachePhaseTimer cost{\n        ::Eden::Performance::CachePhase::CheckFeedbackLoop};\n        texture_cache.CheckFeedbackLoop(std::span<const VideoCommon::ImageViewInOut>{views.data(),\n                                                                                     views.size()});\n    }"),
            ("    return ConfigureDraw(rescaling, render_area);", "    { ::Eden::Performance::CachePhaseTimer cost{\n        ::Eden::Performance::CachePhase::CommitGraphicsDraw};\n        return ConfigureDraw(rescaling, render_area);\n    }"),
            # R361: attribute absent HUD/pitch to pipeline or descriptor skips.
            ("    if (IsBuilt() && !pipeline) {\n        return false;\n    }", "    if (IsBuilt() && !pipeline) {\n        ::Eden::Performance::RecordGraphicsDrawDrop(\n            ::Eden::Performance::GraphicsDrawDrop::BuiltPipelineFailed);\n        return false;\n    }"),
            ("            if (!alloc.host) {\n                LOG_DEBUG(Render_Vulkan, \"Failed to reserve descriptor memory, skipping draw\");\n                return false;\n            }", "            if (!alloc.host) {\n                ::Eden::Performance::RecordGraphicsDrawDrop(\n                    ::Eden::Performance::GraphicsDrawDrop::DescriptorBufferFull);\n                LOG_DEBUG(Render_Vulkan, \"Failed to reserve descriptor memory, skipping draw\");\n                return false;\n            }"),
            # R354: preserve the versioned GPU-only descriptor scratch reuse
            # without touching guest cache lock scopes or command ordering.
            ("#include <iostream>\n#include <span>",
             "#include <iostream>\n#include <memory>\n#include <optional>\n#include <span>"),
            ("constexpr size_t NUM_STAGES = Maxwell::MaxShaderStage;",
             "constexpr size_t NUM_STAGES = Maxwell::MaxShaderStage;\n\n// Descriptor-heavy titles can exceed small_vector's inline capacity on\n// thousands of draws per second. Keep the spare heap capacity on the GPU\n// owner thread instead of allocating/freeing it while the guest texture and\n// buffer caches are locked. Small layouts retain their original stack path.\n// Reentrant Configure() calls receive independent scratch storage.\nstruct GraphicsDescriptorScratch {\n    boost::container::small_vector<VideoCommon::ImageViewInOut, 64> views;\n    boost::container::small_vector<VideoCommon::SamplerId, 64> samplers;\n    bool in_use{};\n};\n\n// Two per-thread scratch slots cover ordinary and once-nested Configure.\n// A third recursive call retains the original safe heap allocation fallback.\nthread_local GraphicsDescriptorScratch graphics_descriptor_scratch;\nthread_local GraphicsDescriptorScratch graphics_descriptor_nested_scratch;\n\nclass GraphicsDescriptorScratchLease {\npublic:\n    GraphicsDescriptorScratchLease() {\n        if (!graphics_descriptor_scratch.in_use) {\n            current = &graphics_descriptor_scratch;\n            current->in_use = true;\n        } else if (!graphics_descriptor_nested_scratch.in_use) {\n            current = &graphics_descriptor_nested_scratch;\n            current->in_use = true;\n        } else {\n            nested = std::make_unique<GraphicsDescriptorScratch>();\n            current = nested.get();\n        }\n        current->views.clear();\n        current->samplers.clear();\n    }\n\n    ~GraphicsDescriptorScratchLease() {\n        if (!nested) current->in_use = false;\n    }\n\n    GraphicsDescriptorScratchLease(const GraphicsDescriptorScratchLease&) = delete;\n    GraphicsDescriptorScratchLease& operator=(const GraphicsDescriptorScratchLease&) = delete;\n\n    auto& Views() noexcept { return current->views; }\n    auto& Samplers() noexcept { return current->samplers; }\n\nprivate:\n    std::unique_ptr<GraphicsDescriptorScratch> nested;\n    GraphicsDescriptorScratch* current{};\n};"),
            ("    boost::container::small_vector<VideoCommon::ImageViewInOut, 64> views;\n    boost::container::small_vector<VideoCommon::SamplerId, 64> samplers;\n    views.reserve(num_image_elements);\n    samplers.reserve(num_textures);",
             "    // Reuse storage even for common <=64-descriptor draws: constructing two\n    // inline small_vectors for every draw still churned ~1 KiB of stack and\n    // capacity metadata while both guest GPU cache locks were held.\n    GraphicsDescriptorScratchLease scratch;\n    auto& views = scratch.Views();\n    auto& samplers = scratch.Samplers();\n    views.reserve(num_image_elements);\n    samplers.reserve(num_textures);"),
            ('#include <algorithm>',
             '#include <algorithm>\n#include <exception>\n#include "common/thread_worker.h"\n#include "dev_vulkan.h"'),
            ('auto func{[this, shader_notify, &render_pass_cache, pipeline_statistics] {',
             'auto func{[this, shader_notify, &render_pass_cache, pipeline_statistics, '
             'fast_first_runtime = (worker_thread != nullptr)] {'),
            ('            MakePipeline(render_pass);',
             '            if (::Eden::DevVulkan::fast_first_pipelines && fast_first_runtime) {\n'
             '                MakePipeline(render_pass, VK_PIPELINE_CREATE_DISABLE_OPTIMIZATION_BIT);\n'
             '                QueueOptimizedPipeline(render_pass);\n'
             '            } else {\n'
             '                MakePipeline(render_pass);\n'
             '            }'),
            ('void GraphicsPipeline::MakePipeline(VkRenderPass render_pass) {',
             optimize_worker),
            ('    pipeline = device.GetLogical().CreateGraphicsPipeline({',
             '    (target ? *target : pipeline) = device.GetLogical().CreateGraphicsPipeline({'),
            ('        .flags = flags,', '        .flags = flags | extra_flags,'),
            ('cmdbuf.BindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS, *pipeline);',
             'cmdbuf.BindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS,\n'
             '    optimized_ready.load(std::memory_order_acquire) ? *optimized_pipeline : *pipeline);'),
        ])
        # R356: reserve descriptor scratch on the GPU owner BEFORE the
        # dual guest cache lock. Counts are immutable; texture/descriptor
        # contents stay inside the lock.
        replacements.append(("void GraphicsPipeline::AddTransition(GraphicsPipeline* transition) {\n    transition_keys.push_back(transition->key);\n    transitions.push_back(transition);\n}", "void GraphicsPipeline::AddTransition(GraphicsPipeline* transition) {\n    transition_keys.push_back(transition->key);\n    transitions.push_back(transition);\n}\n\n#ifdef PS5_NATIVE\nvoid GraphicsPipeline::PreflightDescriptorScratch() {\n    // Called by the GPU owner before PrepareDraw acquires the buffer/texture\n    // cache pair. The immutable pipeline descriptor counts are safe here.\n    // Nested Configure calls use their own scratch and fall back to reserve\n    // under the lock; never corrupt an in-flight parent view list.\n    // Nested Configure reserves its private thread-local slot before the GPU\n    // cache mutexes. Depth >= 3 still has the existing safe fallback.\n    auto& scratch = graphics_descriptor_scratch.in_use\n                        ? graphics_descriptor_nested_scratch\n                        : graphics_descriptor_scratch;\n    if (scratch.in_use) return;\n    if (scratch.views.capacity() < num_image_elements)\n        scratch.views.reserve(num_image_elements);\n    if (scratch.samplers.capacity() < num_textures)\n        scratch.samplers.reserve(num_textures);\n    // Allocate the per-pipeline descriptor snapshot BEFORE the buffer/texture\n    // cache mutex pair. ConfigureDraw still reads, compares and publishes the\n    // actual guest descriptors only after taking both locks.\n    if (num_descriptor_entries != 0 && descriptor_set_layout &&\n        (uses_descriptor_buffer || !uses_push_descriptor) &&\n        last_descriptor_payload.capacity() < num_descriptor_entries) {\n        last_descriptor_payload.reserve(num_descriptor_entries);\n    }\n}\n#endif"))
        # The sample decision is set by the GPU owner's PrepareDraw, so the
        # nested stages measure exactly the same draw without extra clocks.
        for expression, phase in (
            ('texture_cache.SynchronizeDescriptors(false);', 'TextureDescriptorSync'),
            ('texture_cache.FillImageViews(std::span(views.data(), views.size()), false, Spec::has_images);', 'TextureFillImageViews'),
            ('buffer_cache.UpdateGraphicsBuffers(is_indexed);', 'GraphicsBufferUpdate'),
            ('guest_descriptor_queue.Acquire(scheduler, num_descriptor_entries, uses_descriptor_buffer);', 'DescriptorQueueAcquire'),
        ):
            if name == 'vk_graphics_pipeline' and phase == 'DescriptorQueueAcquire':
                # Zero descriptors are known from immutable Shader::Info counts.
                # Acquire(0) is a legacy 1024-entry reservation: don't block
                # both guest cache locks for a draw that writes no entries.
                replacements.append(
                    ('    ' + expression,
                     '    { ::Eden::Performance::CachePhaseTimer cost{'
                     '::Eden::Performance::CachePhase::DescriptorQueueAcquire};\n'
                     '        // Exact zero descriptor count: Acquire(0) otherwise reserves 1024\n'
                     '        // entries and can stall the GPU worker under both guest cache locks.\n'
                     '        if (num_descriptor_entries == 0) {\n'
                     '            guest_descriptor_queue.AcquireKnownEmpty(uses_descriptor_buffer);\n'
                     '        } else {\n'
                     '            ' + expression + '\n'
                     '        }\n'
                     '    }'))
                continue
            if name == 'vk_graphics_pipeline' and phase == 'TextureDescriptorSync':
                # No descriptors: skip TIC/TSC synchronization entirely for this
                # draw; table changes are consumed on the next textured draw.
                replacements.append(
                    ('    ' + expression,
                     '    // No TIC/TSC entries are read by a shader without image/image-buffer\n'
                     '    // descriptors. Leave dirty table state pending until a later textured\n'
                     '    // pipeline needs it; framebuffer bindings and shader invalidations are\n'
                     '    // independent of this table synchronization.\n'
                     '    if (num_image_elements != 0) {\n'
                     '        ::Eden::Performance::CachePhaseTimer cost{\n'
                     '            ::Eden::Performance::CachePhase::TextureDescriptorSync};\n'
                     '        ' + expression + '\n'
                     '    }'))
                continue
            replacements.append(
                ('    ' + expression,
                 '    { ::Eden::Performance::CachePhaseTimer cost{::Eden::Performance::CachePhase::' + phase +
                 '};\n        ' + expression + '\n    }'))
    # R378: a worker throwing outside the vk::Exception catch leaves GPU
    # build_condvar.wait waiting forever. Completion is a scope guard and
    # both graphics and compute paths catch non-Vulkan failures too.
    replacements.append(('#include <algorithm>',
                         '#include <algorithm>\n#include "common/scope_exit.h"'))
    if name == "vk_graphics_pipeline":
        replacements.append(('    auto func{[this, shader_notify, &render_pass_cache, pipeline_statistics, fast_first_runtime = (worker_thread != nullptr)] {\n        const VkRenderPass render_pass{render_pass_cache.Get(MakeRenderPassKey(key.state, device))};\n        Validate();\n        try {\n            if (::Eden::DevVulkan::fast_first_pipelines && fast_first_runtime) {\n                MakePipeline(render_pass, VK_PIPELINE_CREATE_DISABLE_OPTIMIZATION_BIT);\n                QueueOptimizedPipeline(render_pass);\n            } else {\n                MakePipeline(render_pass);\n            }\n        } catch (const vk::Exception& exception) {\n            LOG_CRITICAL(Render_Vulkan, "Graphics pipeline build failed: {}", exception.what());\n            std::scoped_lock lock{build_mutex};\n            is_built = true;\n            build_condvar.notify_one();\n            if (shader_notify) {\n                shader_notify->MarkShaderComplete();\n            }\n            return;\n        }\n        if (pipeline_statistics) {\n            pipeline_statistics->Collect(device, *pipeline);\n        }\n\n        std::scoped_lock lock{build_mutex};\n        is_built = true;\n        build_condvar.notify_one();\n        if (shader_notify) {\n            shader_notify->MarkShaderComplete();\n        }\n    }};\n',
                             '    auto func{[this, shader_notify, &render_pass_cache, pipeline_statistics, fast_first_runtime = (worker_thread != nullptr)] {\n        // Always release waiters, even when render-pass acquisition, shader\n        // validation, fast-first optimisation scheduling or statistics throws.\n        // A failed pipeline stays null and is rejected by the draw path.\n        SCOPE_EXIT {\n            {\n                std::scoped_lock lock{build_mutex};\n                is_built.store(true, std::memory_order_release);\n            }\n            build_condvar.notify_all();\n            if (shader_notify) {\n                shader_notify->MarkShaderComplete();\n            }\n        };\n        try {\n            const VkRenderPass render_pass{render_pass_cache.Get(MakeRenderPassKey(key.state, device))};\n            Validate();\n            if (::Eden::DevVulkan::fast_first_pipelines && fast_first_runtime) {\n                MakePipeline(render_pass, VK_PIPELINE_CREATE_DISABLE_OPTIMIZATION_BIT);\n                QueueOptimizedPipeline(render_pass);\n            } else {\n                MakePipeline(render_pass);\n            }\n            if (pipeline_statistics && pipeline) {\n                pipeline_statistics->Collect(device, *pipeline);\n            }\n        } catch (const std::exception& exception) {\n            LOG_CRITICAL(Render_Vulkan, "Graphics pipeline build failed: {}", exception.what());\n        } catch (...) {\n            LOG_CRITICAL(Render_Vulkan, "Graphics pipeline build failed: unknown exception");\n        }\n    }};\n'))
    else:
        replacements.append(('    auto func{[this, shader_notify, pipeline_statistics] {\n        const VkPipelineShaderStageRequiredSubgroupSizeCreateInfoEXT subgroup_size_ci{\n            .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_REQUIRED_SUBGROUP_SIZE_CREATE_INFO_EXT,\n            .pNext = nullptr,\n            .requiredSubgroupSize = GuestWarpSize,\n        };\n        VkPipelineCreateFlags flags{};\n        if (device.IsKhrPipelineExecutablePropertiesEnabled() && Settings::values.renderer_debug.GetValue()) {\n            flags |= VK_PIPELINE_CREATE_CAPTURE_STATISTICS_BIT_KHR;\n        }\n        if (uses_descriptor_buffer) {\n            flags |= VK_PIPELINE_CREATE_DESCRIPTOR_BUFFER_BIT_EXT;\n        }\n        const VkComputePipelineCreateInfo compute_ci{\n            .sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,\n            .pNext = nullptr,\n            .flags = flags,\n            .stage{\n                .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,\n                .pNext =\n                    device.IsExtSubgroupSizeControlSupported() ? &subgroup_size_ci : nullptr,\n                .flags = 0,\n                .stage = VK_SHADER_STAGE_COMPUTE_BIT,\n                .module = *spv_module,\n                .pName = "main",\n                .pSpecializationInfo = nullptr,\n            },\n            .layout = *pipeline_layout,\n            .basePipelineHandle = 0,\n            .basePipelineIndex = 0,\n        };\n        try {\n            pipeline = device.GetLogical().CreateComputePipeline(compute_ci, *pipeline_cache);\n        } catch (const vk::Exception& exception) {\n            LOG_CRITICAL(Render_Vulkan, "Adreno rejected compute shader {:016X}: {}", shader_hash,\n                         exception.what());\n            std::scoped_lock lock{build_mutex};\n            is_built = true;\n            build_condvar.notify_one();\n            if (shader_notify) {\n                shader_notify->MarkShaderComplete();\n            }\n            return;\n        }\n\n        // Log compute pipeline creation\n        if (GPU::Logging::IsActive()) {\n            GPU::Logging::GPULogger::GetInstance().LogPipelineStateChange(\n                "ComputePipeline created"\n            );\n        }\n\n        if (pipeline_statistics) {\n            pipeline_statistics->Collect(device, *pipeline);\n        }\n        std::scoped_lock lock{build_mutex};\n        is_built = true;\n        build_condvar.notify_one();\n        if (shader_notify) {\n            shader_notify->MarkShaderComplete();\n        }\n    }};\n',
                             '    auto func{[this, shader_notify, pipeline_statistics] {\n        // The Vulkan worker may throw before/after vkCreateComputePipelines;\n        // never leave scheduler GPU build_condvar waiters blocked forever.\n        SCOPE_EXIT {\n            {\n                std::scoped_lock lock{build_mutex};\n                is_built.store(true, std::memory_order_release);\n            }\n            build_condvar.notify_all();\n            if (shader_notify) {\n                shader_notify->MarkShaderComplete();\n            }\n        };\n        try {\n        const VkPipelineShaderStageRequiredSubgroupSizeCreateInfoEXT subgroup_size_ci{\n            .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_REQUIRED_SUBGROUP_SIZE_CREATE_INFO_EXT,\n            .pNext = nullptr,\n            .requiredSubgroupSize = GuestWarpSize,\n        };\n        VkPipelineCreateFlags flags{};\n        if (device.IsKhrPipelineExecutablePropertiesEnabled() && Settings::values.renderer_debug.GetValue()) {\n            flags |= VK_PIPELINE_CREATE_CAPTURE_STATISTICS_BIT_KHR;\n        }\n        if (uses_descriptor_buffer) {\n            flags |= VK_PIPELINE_CREATE_DESCRIPTOR_BUFFER_BIT_EXT;\n        }\n        const VkComputePipelineCreateInfo compute_ci{\n            .sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,\n            .pNext = nullptr,\n            .flags = flags,\n            .stage{\n                .sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,\n                .pNext =\n                    device.IsExtSubgroupSizeControlSupported() ? &subgroup_size_ci : nullptr,\n                .flags = 0,\n                .stage = VK_SHADER_STAGE_COMPUTE_BIT,\n                .module = *spv_module,\n                .pName = "main",\n                .pSpecializationInfo = nullptr,\n            },\n            .layout = *pipeline_layout,\n            .basePipelineHandle = 0,\n            .basePipelineIndex = 0,\n        };\n            pipeline = device.GetLogical().CreateComputePipeline(compute_ci, *pipeline_cache);\n        // Log compute pipeline creation\n        if (GPU::Logging::IsActive()) {\n            GPU::Logging::GPULogger::GetInstance().LogPipelineStateChange(\n                "ComputePipeline created"\n            );\n        }\n\n        if (pipeline_statistics && pipeline) {\n            pipeline_statistics->Collect(device, *pipeline);\n        }\n        } catch (const std::exception& exception) {\n            LOG_CRITICAL(Render_Vulkan, "Compute pipeline build failed {:016X}: {}",\n                         shader_hash, exception.what());\n        } catch (...) {\n            LOG_CRITICAL(Render_Vulkan, "Compute pipeline build failed {:016X}: unknown exception",\n                         shader_hash);\n        }\n    }};\n'))
    # R421: active first-use fairness stays equivalent to the Vulkan fork.
    # Insert after SCOPE_EXIT so the new queued wrapper may use its guard.
    if name == 'vk_graphics_pipeline':
        replacements.extend([
            ("#include <algorithm>", "#include <algorithm>\n#include <atomic>\n#include <chrono>\n#include <thread>"),
            ("constexpr size_t NUM_STAGES = Maxwell::MaxShaderStage;", "constexpr size_t NUM_STAGES = Maxwell::MaxShaderStage;\n#ifdef PS5_NATIVE\n// Counts cold first-use Vulkan graphics builds, not draws or cached pipelines.\n// Only the optional fast-first dev profile updates it; normal gameplay pays nothing.\nstd::atomic<unsigned> pending_first_use_graphics_builds{0};\n#endif"),
            ("    if (worker_thread) {\n        worker_thread->QueueWork(std::move(func));\n    } else {\n        func();\n    }\n    configure_func = ConfigureFunc(spv_modules, stage_infos);", "    if (worker_thread) {\n#ifdef PS5_NATIVE\n        if (::Eden::DevVulkan::fast_first_pipelines) {\n            // Cold first-use compilation has priority over speculative optimization.\n            // Publish BEFORE enqueuing, including work waiting in the builder queue.\n            pending_first_use_graphics_builds.fetch_add(1, std::memory_order_release);\n            try {\n                worker_thread->QueueWork([build = std::move(func)]() mutable {\n                    SCOPE_EXIT {\n                        pending_first_use_graphics_builds.fetch_sub(1, std::memory_order_release);\n                    };\n                    build();\n                });\n            } catch (...) {\n                pending_first_use_graphics_builds.fetch_sub(1, std::memory_order_release);\n                throw;\n            }\n        } else\n#endif\n        {\n            worker_thread->QueueWork(std::move(func));\n        }\n    } else {\n        func();\n    }\n    configure_func = ConfigureFunc(spv_modules, stage_infos);"),
        ])
    # R417: firmware scheduling readback from actual Vulkan compiler callbacks.
    # Deliberately no priority, affinity or mutex/command ordering changes.
    sched_probe_anchor = (
        '    auto func{[this, shader_notify, &render_pass_cache, pipeline_statistics, fast_first_runtime = (worker_thread != nullptr)] {\n'
        if name == 'vk_graphics_pipeline' else
        '    auto func{[this, shader_notify, pipeline_statistics] {\n'
    )
    replacements.append((sched_probe_anchor, sched_probe_anchor +
                         '#ifdef PS5_NATIVE\n'
                         '        ::Eden::Performance::ProbeSchedulerOnce("VkPipelineBuilder");\n'
                         '#endif\n'))
    # Completed async graphics pipelines may become ready before their
    # ordered GPU callback is dequeued. Their release-published completion
    # makes the build mutex and condition wait unnecessary in that case.
    # The same callback still waits normally while compilation is unfinished.
    # Both graphics and compute can finish between queuing and callback execution.
    if name in ('vk_graphics_pipeline', 'vk_compute_pipeline'):
        wait_phase = 'GraphicsPipelineWait' if name == 'vk_graphics_pipeline' else 'ComputePipelineWait'
        replacements.append((
            "        scheduler.Record([this](vk::CommandBuffer) {\n"
            "            auto timer = Eden::Performance::VulkanTimer(16);\n"
            "            std::unique_lock lock{build_mutex};",
            "        scheduler.Record([this](vk::CommandBuffer) {\n"
            "            // Builder published the pipeline before this ordered GPU callback.\n"
            "            // Acquire its completion without taking a redundant build mutex.\n"
            "            // An unfinished build still follows the original condition wait.\n"
            "            if (is_built.load(std::memory_order_acquire)) return;\n"
            "            auto timer = Eden::Performance::VulkanTimer(16);\n"
            "            // Only unfinished builds contribute a worker wait; no clock in quiet mode.\n"
            "            ::Eden::Performance::CachePhaseTimer pipeline_ready_wait{\n"
            f"                ::Eden::Performance::CachePhase::{wait_phase},\n"
            "                ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)};\n"
            "            std::unique_lock lock{build_mutex};",
        ))
    if name == 'vk_graphics_pipeline':
        # Zero-descriptor shaders must not pass a null vector pointer to
        # memcmp or construct a null [first,last) range. Preserve actual
        # descriptor-buffer allocations and Vulkan bind ordering unchanged.
        replacements.extend([
            ("            std::memcmp(last_descriptor_payload.data(), entries,\n                        num_descriptor_entries * sizeof(DescriptorUpdateEntry)) == 0;",
             "            (num_descriptor_entries == 0 ||\n             std::memcmp(last_descriptor_payload.data(), entries,\n                         num_descriptor_entries * sizeof(DescriptorUpdateEntry)) == 0);"),
            ("            std::memcmp(last_descriptor_payload.data(), entries,\n                        num_descriptor_entries * sizeof(DescriptorUpdateEntry)) != 0;",
             "            (num_descriptor_entries != 0 &&\n             std::memcmp(last_descriptor_payload.data(), entries,\n                         num_descriptor_entries * sizeof(DescriptorUpdateEntry)) != 0);"),
            ("            last_descriptor_buffer_generation = alloc.generation;\n            last_descriptor_payload.assign(entries, entries + num_descriptor_entries);",
             "            last_descriptor_buffer_generation = alloc.generation;\n            // Empty shader layouts have no descriptor payload to copy.\n            if (num_descriptor_entries != 0) {\n                last_descriptor_payload.assign(entries, entries + num_descriptor_entries);\n            } else {\n                last_descriptor_payload.clear();\n            }"),
            ("        if (update_descriptors) {\n            last_descriptor_payload.assign(entries, entries + num_descriptor_entries);\n        }",
             "        if (update_descriptors) {\n            if (num_descriptor_entries != 0) {\n                last_descriptor_payload.assign(entries, entries + num_descriptor_entries);\n            } else {\n                last_descriptor_payload.clear();\n            }\n        }")
        ])
    adapt(f'src/video_core/renderer_vulkan/{name}.cpp', name + '_cost.cpp', replacements)
shader_costs = [
    ('#include <algorithm>', '#include <algorithm>\n#include <cstdio>\n#include "pipeline_trace_registry.h"\n'
     '#include "performance.h"\n#include "dev_vulkan.h"\n#include "diagnostics.h"'),
    # Development crash probes: report each pipeline's first use (stage hashes) to klog,
    # which survives a GPU fault that kills the title.
    ('    current_pipeline = pipeline.get();\n    return BuiltPipeline(current_pipeline);\n}',
     '    current_pipeline = pipeline.get();\n'
     '    if (::Eden::DevVulkan::trace_pipelines) {\n'
     '        const auto first_use = ::Eden::PipelineTrace::graphics_first_use.Record(\n'
     '            ::Eden::DevVulkan::gpu_time_session.load(std::memory_order_acquire), current_pipeline);\n'
     '        if (first_use != 0) {\n'
     '            const auto& h = graphics_key.unique_hashes;\n'
     '            char text[256];\n'
     '            std::snprintf(text, sizeof(text), "G%zu p=%p new=%d va=%llx vb=%llx tc=%llx te=%llx gs=%llx fs=%llx",\n'
     '                          first_use, (const void*)current_pipeline, int(is_new), (unsigned long long)h[0], (unsigned long long)h[1],\n'
     '                          (unsigned long long)h[2], (unsigned long long)h[3], (unsigned long long)h[4],\n'
     '                          (unsigned long long)h[5]);\n'
     '            ::Eden::Report("pipeline", text);\n'
     '            LOG_INFO(Render_Vulkan, "EDEN_PIPELINE_FIRST_USE {}", text);\n'
     '        }\n'
     '    }\n'
     '    return BuiltPipeline(current_pipeline);\n}'),
    ('    if (!is_new) {\n        return pipeline.get();\n    }\n    pipeline = CreateComputePipeline(key, shader);\n    return pipeline.get();\n}',
     '    if (is_new) {\n'
     '        pipeline = CreateComputePipeline(key, shader);\n'
     '    }\n'
     '    if (::Eden::DevVulkan::trace_pipelines && pipeline) {\n'
     '        const auto first_use = ::Eden::PipelineTrace::compute_first_use.Record(\n'
     '            ::Eden::DevVulkan::gpu_time_session.load(std::memory_order_acquire), pipeline.get());\n'
     '        if (first_use != 0) {\n'
     '            char text[160];\n'
     '            std::snprintf(text, sizeof(text), "C%zu p=%p new=%d cs=%llx shared=%u wg=%u,%u,%u", first_use,\n'
     '                          (const void*)pipeline.get(), int(is_new), (unsigned long long)key.unique_hash, unsigned(key.shared_memory_size),\n'
     '                          unsigned(key.workgroup_size[0]), unsigned(key.workgroup_size[1]),\n'
     '                          unsigned(key.workgroup_size[2]));\n'
     '            ::Eden::Report("pipeline", text);\n'
     '            LOG_INFO(Render_Vulkan, "EDEN_PIPELINE_FIRST_USE {}", text);\n'
     '        }\n'
     '    }\n'
     '    return pipeline.get();\n}'),
    ('std::unique_ptr<GraphicsPipeline> PipelineCache::CreateGraphicsPipeline() {',
     'std::unique_ptr<GraphicsPipeline> PipelineCache::CreateGraphicsPipeline() {\n    auto timer = Eden::Performance::VulkanTimer(17);'),
    ('    const ComputePipelineCacheKey& key, const ShaderInfo* shader) {',
     '    const ComputePipelineCacheKey& key, const ShaderInfo* shader) {\n    auto timer = Eden::Performance::VulkanTimer(17);'),
    # The cache serializer is rewritten above, so its old "try" signature
     # no longer exists here. Instrument the FINAL generated signature.
     ('                                                 u32 cache_version) {\n#ifdef PS5_NATIVE',
     '                                                 u32 cache_version) {\n    auto timer = Eden::Performance::VulkanTimer(18);\n#ifdef PS5_NATIVE'),
    ('}\n\nPipelineCache::~PipelineCache()',
     '    if (Eden::Performance::vulkan_cost_enabled.load(std::memory_order_relaxed))\n'
     '        std::printf("EDEN_VULKAN_DYNAMIC blend=%u enables=%u vertex=%u\\n",\n'
     '                    unsigned(dynamic_features.has_extended_dynamic_state_3_blend),\n'
     '                    unsigned(dynamic_features.has_extended_dynamic_state_3_enables),\n'
     '                    unsigned(dynamic_features.has_dynamic_vertex_input));\n'
     '}\n\nPipelineCache::~PipelineCache()'),
    # Last vertex-binding state belongs to the old GPU pipeline cache.
    ('PipelineCache::~PipelineCache() {',
     'namespace {\nvoid EdenResetStaticVertexInputBinding() noexcept;\n} // namespace\n\n'
     'PipelineCache::~PipelineCache() {\n    EdenResetStaticVertexInputBinding();'),
    # Static vertex input (no attribute) for pipelines whose vertex shader reads no vertex attribute
    # (dev_vulkan.h static_vertex_input): with VK_EXT_vertex_input_dynamic_state the console's
    # driver drew them wrong (a full-screen triangle from the vertex index covering a game's
    # cutscenes with a flat colour). Building a pipeline records whether its vertex shader reads
    # attributes; the static key has no attribute, so the disk cache keeps loading it.
    ('#include "video_core/engines/maxwell_3d.h"',
     '#include "video_core/engines/maxwell_3d.h"\n#include "video_core/dirty_flags.h"\n'
     '#include <atomic>\n#include <mutex>\n#include <set>\n#include <unordered_set>\n'
     '#include "video_core/renderer_vulkan/vk_state_tracker.h"'),
    ('GraphicsPipeline* PipelineCache::CurrentGraphicsPipeline() {',
     """namespace {
std::mutex eden_attributeless_mutex;
using EdenVertexIdentity = std::array<u64, 2>;
std::set<EdenVertexIdentity> eden_attributeless_vertex;
std::atomic<u32> eden_attributeless_generation{0};
bool eden_static_vertex_input_bound = false;

void EdenResetStaticVertexInputBinding() noexcept {
    eden_static_vertex_input_bound = false;
}

void EdenRecordAttributeless(EdenVertexIdentity vertex_hash, const Shader::Info& info) {
    for (size_t index = 0; index < Shader::IR::NUM_GENERICS; ++index) {
        if (info.loads.Generic(index)) {
            return;
        }
    }
    std::scoped_lock lock{eden_attributeless_mutex};
    if (eden_attributeless_vertex.insert(vertex_hash).second) {
        eden_attributeless_generation.fetch_add(1, std::memory_order_release);
    }
}

// GPU thread: whether the vertex shader reads no attribute, as far as built pipelines tell.
bool EdenAttributeless(EdenVertexIdentity vertex_hash) {
    // The GPU thread owns this fixed 64-entry memo; builder threads publish
    // updates through the generation. Four-way sets prevent colliding vertex
    // shaders (especially alternating HUD/world keys) from taking the global
    // shader-set mutex on every draw. No allocation or lock on a cache hit.
    struct Lookup {
        EdenVertexIdentity hash{};
        u32 generation = ~0u;
        bool result = false;
    };
    struct Bucket {
        std::array<Lookup, 4> ways{};
        unsigned next_slot{};
    };
    static thread_local std::array<Bucket, 16> buckets{};
    // Same vertex shader across successive draws: skip bucket hashing,
    // four-way probes and even the epoch load for proven positive keys.
    // The builder-owned set only inserts; negative results must be
    // invalidated by a newly published generation.
    static thread_local Lookup last{};
    if (last.result && last.hash == vertex_hash) return true;
    const u32 generation = eden_attributeless_generation.load(std::memory_order_acquire);
    if (!last.result && last.hash == vertex_hash && last.generation == generation)
        return false;
    auto& bucket = buckets[(vertex_hash[0] ^ std::rotl(vertex_hash[1], 11)) &
                           (buckets.size() - 1)];
    for (const auto& lookup : bucket.ways) {
        // The builder-owned set only INSERTS attributeless shader keys.
        // A proven positive therefore remains valid across unrelated new
        // shader publications. Negatives still require the current epoch.
        if (lookup.hash == vertex_hash &&
            (lookup.result || lookup.generation == generation)) {
            last = lookup;
            return lookup.result;
        }
    }
    const std::scoped_lock lock{eden_attributeless_mutex};
    const bool result = eden_attributeless_vertex.contains(vertex_hash);
    auto& lookup = bucket.ways[bucket.next_slot];
    lookup.hash = vertex_hash;
    lookup.result = result;
    lookup.generation = generation;
    bucket.next_slot = (bucket.next_slot + 1) & (bucket.ways.size() - 1);
    last = lookup;
    return result;
}

// A static key without attributes (what the loader takes back from the disk cache).
bool EdenAttributelessStaticKey(const FixedPipelineState& state) {
    return state.dynamic_vertex_input == 0 &&
           std::ranges::none_of(state.attributes,
                                [](const auto& attribute) { return attribute.raw != 0; });
}
} // Anonymous namespace

GraphicsPipeline* PipelineCache::CurrentGraphicsPipeline() {"""),
    ('    graphics_key.state.Refresh(*maxwell3d, dynamic_features);\n',
     """    graphics_key.state.Refresh(*maxwell3d, dynamic_features);
    const bool static_vertex_input = graphics_key.state.dynamic_vertex_input != 0 &&
                                     ::Eden::DevVulkan::static_vertex_input &&
                                     EdenAttributeless({graphics_key.unique_hashes[0], graphics_key.unique_hashes[1]});
    if (static_vertex_input) {
        // Instance-rate streams as the registers set them (with every stream per vertex the
        // driver drew these wrong too); no attribute, so the key does not depend on what the
        // registers hold for attributes the shader does not read.
        const auto& regs = maxwell3d->regs;
        graphics_key.state.dynamic_vertex_input.Assign(0);
        graphics_key.state.enabled_divisors = 0;
        graphics_key.state.attributes = {};
        graphics_key.state.binding_divisors = {};
        for (size_t index = 0; index < Maxwell::NumVertexArrays; ++index) {
            const bool is_enabled = regs.vertex_stream_instances.IsInstancingEnabled(index);
            graphics_key.state.binding_divisors[index] =
                is_enabled ? regs.vertex_streams[index].frequency : 0;
            graphics_key.state.enabled_divisors |= (is_enabled ? u64{1} : 0) << index;
        }
        // The union's attribute_types now holds divisors: the next dynamic draw recomputes them
        // and sets its vertex input again (a static pipeline replaced it).
        maxwell3d->dirty.flags[Dirty::VertexInput] = true;
    }
    if (static_vertex_input && !eden_static_vertex_input_bound) {
        // Rebind the vertex buffers with their strides, dynamic state of the static pipeline.
        auto& flags = maxwell3d->dirty.flags;
        flags[VideoCommon::Dirty::VertexBuffers] = true;
        for (size_t index = 0; index < Maxwell::NumVertexArrays; ++index) {
            flags[VideoCommon::Dirty::VertexBuffer0 + index] = true;
        }
    }
    eden_static_vertex_input_bound = static_vertex_input;
"""),
    ('            (key.state.dynamic_vertex_input != 0) !=\n                dynamic_features.has_dynamic_vertex_input) {',
     '            ((key.state.dynamic_vertex_input != 0) !=\n'
     '                 dynamic_features.has_dynamic_vertex_input &&\n'
     '             !(dynamic_features.has_dynamic_vertex_input &&\n'
     '               ::Eden::DevVulkan::static_vertex_input &&\n'
     '               EdenAttributelessStaticKey(key.state)))) {'),
    ('    std::array<const Shader::Info*, Maxwell::MaxShaderStage> infos{};\n',
     '    if (uses_vertex_b) {\n'
     '        EdenRecordAttributeless({key.unique_hashes[0], key.unique_hashes[1]}, programs[1].info);\n'
     '    }\n'
     '    std::array<const Shader::Info*, Maxwell::MaxShaderStage> infos{};\n'),
]
# Time both graphics and compute preparation, without modifying the compiler or
# reading guest state on another thread. These intervals overlap shader_prepare.
shader_source = (source / 'src/video_core/renderer_vulkan/vk_pipeline_cache.cpp').read_text()
# The permanent Vulkan pipeline worker pool cannot safely be interrupted by
# StatefulThreadWorker::WaitForRequests(stop_token): it requests stop on each
# worker, so later on-demand shader compilation would lose its pool. Instead,
# initialize the game's persistent pipeline filenames/driver cache and return
# before scheduling any warmup tasks when an already-stopped token is passed.
# Real guest shaders still compile asynchronously and serialize during play.
lazy_vulkan_cache_anchor = '''    if (use_vulkan_pipeline_cache) {
        vulkan_pipeline_cache_filename = base_dir / "vulkan_pipelines.bin";
        vulkan_pipeline_cache =
            LoadVulkanPipelineCache(vulkan_pipeline_cache_filename, CACHE_VERSION);
    }

    struct {'''
lazy_vulkan_cache_replacement = '''    if (use_vulkan_pipeline_cache) {
        vulkan_pipeline_cache_filename = base_dir / "vulkan_pipelines.bin";
        vulkan_pipeline_cache =
            LoadVulkanPipelineCache(vulkan_pipeline_cache_filename, CACHE_VERSION);
    }

#ifdef PS5_NATIVE
    // The PS5 is launching one foreground game, so do not delay it by
    // compiling the full backlog of shaders from earlier sessions.
    // An already-stopped token is a special initialization-only request:
    // after naming the per-title cache, leave workers RUNNING for later jobs.
    if (stop_loading.stop_requested()) {
        LOG_INFO(Render_Vulkan, "PS5 lazy shader cache ready for {:016x}", title_id);
        return;
    }
#endif

    struct {'''
if shader_source.count(lazy_vulkan_cache_anchor) != 1:
    raise RuntimeError("Pinned Vulkan persistent-cache setup changed")
shader_source = shader_source.replace(lazy_vulkan_cache_anchor, lazy_vulkan_cache_replacement)
# A driver's VkPipelineCache blob can become incompatible after a RADV
# update without changing Eden's guest shader CACHE_VERSION. The SDK may
# reject initial data. Retry with an empty Vulkan cache instead of aborting
# the entire game at initialization; retain guest shader disk metadata.
vulkan_cache_create_anchor = '''        return device.GetLogical().CreatePipelineCache(pipeline_cache_ci);
    };
    try {
        std::ifstream file(filename, std::ios::binary | std::ios::ate);'''
vulkan_cache_create_replacement = '''        try {
            return device.GetLogical().CreatePipelineCache(pipeline_cache_ci);
        } catch (const std::exception& error) {
            if (data_size == 0) throw;
            LOG_WARNING(Render_Vulkan,
                        "Ignoring incompatible driver pipeline cache: {}", error.what());
            pipeline_cache_ci.initialDataSize = 0;
            pipeline_cache_ci.pInitialData = nullptr;
            return device.GetLogical().CreatePipelineCache(pipeline_cache_ci);
        }
    };
    try {
        std::ifstream file(filename, std::ios::binary | std::ios::ate);'''
if shader_source.count(vulkan_cache_create_anchor) != 1:
    raise RuntimeError("Pinned Vulkan pipeline-cache constructor changed")
shader_source = shader_source.replace(vulkan_cache_create_anchor, vulkan_cache_create_replacement)

# PS5 game exit and crashes must not truncate the *last valid* driver cache.
# Serialize off to a .new file and atomically rename over the current file
# only after flush/close succeed. A local mutex prevents two asynchronous
# serializations from sharing the same staging path during shutdown.
# The same directory guarantees an in-filesystem rename on PS5.
vulkan_cache_save_anchor = '''void PipelineCache::SerializeVulkanPipelineCache(const std::filesystem::path& filename,
                                                 const vk::PipelineCache& pipeline_cache,
                                                 u32 cache_version) try {
    std::ofstream file(filename, std::ios::binary);
    file.exceptions(std::ifstream::failbit);
    if (!file.is_open()) {
        LOG_ERROR(Common_Filesystem, "Failed to open Vulkan driver pipeline cache file {}",
                  Common::FS::PathToUTF8String(filename));
        return;
    }
    file.write(VULKAN_CACHE_MAGIC_NUMBER.data(), VULKAN_CACHE_MAGIC_NUMBER.size())
        .write(reinterpret_cast<const char*>(&cache_version), sizeof(cache_version));

    size_t cache_size = 0;
    std::vector<char> cache_data;
    if (pipeline_cache) {
        pipeline_cache.Read(&cache_size, nullptr);
        cache_data.resize(cache_size);
        pipeline_cache.Read(&cache_size, cache_data.data());
    }
    file.write(cache_data.data(), cache_size);

    LOG_INFO(Render_Vulkan, "Vulkan driver pipelines cached at: {}",
             Common::FS::PathToUTF8String(filename));

} catch (const std::ios_base::failure& e) {
    LOG_ERROR(Common_Filesystem, "{}", e.what());
    if (!Common::FS::RemoveFile(filename)) {
        LOG_ERROR(Common_Filesystem, "Failed to delete Vulkan driver pipeline cache file {}",
                  Common::FS::PathToUTF8String(filename));
    }
}
'''
vulkan_cache_save_replacement = '''void PipelineCache::SerializeVulkanPipelineCache(const std::filesystem::path& filename,
                                                 const vk::PipelineCache& pipeline_cache,
                                                 u32 cache_version) {
#ifdef PS5_NATIVE
    // The foreground title may exit while background serializer work exists.
    // Serialize staged files to one writer at a time. Never erase the
    // previously verified driver cache in a write/rename failure path.
    static std::mutex save_mutex;
    const std::lock_guard save_lock{save_mutex};
    auto staging = filename;
    staging += ".new";
    try {
        std::ofstream file;
        file.exceptions(std::ios::failbit | std::ios::badbit);
        file.open(staging, std::ios::binary | std::ios::trunc);
        file.write(VULKAN_CACHE_MAGIC_NUMBER.data(), VULKAN_CACHE_MAGIC_NUMBER.size())
            .write(reinterpret_cast<const char*>(&cache_version), sizeof(cache_version));

        size_t cache_size = 0;
        std::vector<char> cache_data;
        if (pipeline_cache) {
            pipeline_cache.Read(&cache_size, nullptr);
            cache_data.resize(cache_size);
            pipeline_cache.Read(&cache_size, cache_data.data());
        }
        if (cache_size != 0)
            file.write(cache_data.data(), static_cast<std::streamsize>(cache_size));
        file.flush();
        file.close();
        std::error_code rename_error;
        std::filesystem::rename(staging, filename, rename_error);
        if (rename_error) {
            LOG_WARNING(Common_Filesystem, "Driver cache rename failed: {}", rename_error.message());
            std::error_code cleanup_error;
            std::filesystem::remove(staging, cleanup_error);
            return;
        }
        LOG_INFO(Render_Vulkan, "Saved PS5 driver pipeline cache atomically: {}",
                 Common::FS::PathToUTF8String(filename));
    } catch (const std::exception& error) {
        LOG_WARNING(Common_Filesystem, "Retained old driver cache after failed save: {}", error.what());
        std::error_code cleanup_error;
        std::filesystem::remove(staging, cleanup_error);
    }
#else
    try {
        std::ofstream file(filename, std::ios::binary);
        file.exceptions(std::ifstream::failbit);
        if (!file.is_open())
            return;
        file.write(VULKAN_CACHE_MAGIC_NUMBER.data(), VULKAN_CACHE_MAGIC_NUMBER.size())
            .write(reinterpret_cast<const char*>(&cache_version), sizeof(cache_version));
        size_t cache_size = 0;
        std::vector<char> cache_data;
        if (pipeline_cache) {
            pipeline_cache.Read(&cache_size, nullptr);
            cache_data.resize(cache_size);
            pipeline_cache.Read(&cache_size, cache_data.data());
        }
        file.write(cache_data.data(), cache_size);
    } catch (const std::ios_base::failure& error) {
        LOG_ERROR(Common_Filesystem, "{}", error.what());
    }
#endif
}
'''
if shader_source.count(vulkan_cache_save_anchor) != 1:
    raise RuntimeError("Pinned Vulkan driver cache serializer changed")
shader_source = shader_source.replace(vulkan_cache_save_anchor, vulkan_cache_save_replacement)
# Native affinity masks describe the CPUs the *process can schedule on*;
# hardware_concurrency() can report more than the PS5 runtime permits.
pipeline_ps5_headers = f'''#ifdef PS5_NATIVE
#include <pthread.h>
#include <sched.h>
#include <sys/param.h>
#include <sys/cpuset.h>
#include <cstdio>
#include "performance.h"
#endif
'''
if shader_source.count('#include <thread>') != 1:
    raise RuntimeError('Pinned Vulkan pipeline header changed')
shader_source = shader_source.replace('#include <thread>', '#include <thread>\n' + pipeline_ps5_headers)
# PS5 shader worker occupancy must use the affinity of THIS thread,
# not a global count or a guess that every affinity mask still includes the
# guest/GPU primary cores. On R237 the native shader thread inherited an
# 8-logical-CPU secondary mask 0x1fe0, but this policy reserved 7 primary
# slots a SECOND time and launched ONE shader compiler. Compare the thread's
# actual affinity with the verified primary worker mask and reserve those
# primary slots only when they are actually in this mask. Keep two secondary
# logical slots for audio/presentation/services. Topology-unknown falls back
# to the original conservative 7-slot reservation. Cap builders at six.
pipeline_worker_anchor = '''    return max_core_threads;
#endif
}'''
pipeline_worker_replacement = '''#ifdef PS5_NATIVE
    const size_t reported = std::max<size_t>(static_cast<size_t>(std::thread::hardware_concurrency()), 2ULL);
    cpuset_t allowed{};
    const int affinity_rc = cpuset_getaffinity(CPU_LEVEL_WHICH, CPU_WHICH_TID, -1, 8, &allowed);
    size_t available = 0;
    std::uint64_t allowed_mask = 0;
    if (affinity_rc == 0) {
        for (unsigned cpu = 0; cpu < 64; ++cpu) {
            if (CPU_ISSET(cpu, &allowed)) {
                ++available;
                allowed_mask |= std::uint64_t{1} << cpu;
            }
        }
    }
    // Reserve only what is REALLY shared with guest/GPU workers in the
    // CURRENT thread's allowed mask. The masked-off primaries have already
    // been excluded by SetSecondaryPlacement: do NOT subtract them again.
    // The kernel's confirmed affinity is authoritative. C++ hardware_concurrency()
    // is only a hint: on constrained firmware it can under-report the CPUs
    // actually granted to this thread and silently starve shader compilers.
    // Never borrow CPUs outside the read-back allowed mask.
    const size_t schedulable = available ? available : std::min<size_t>(reported, 4);
    const std::uint64_t primary_mask = ::Eden::Performance::PinnedWorkerMask();
    size_t primary_in_mask = 0;
    if (affinity_rc == 0 && primary_mask) {
        for (unsigned cpu = 0; cpu < 64; ++cpu)
            if (CPU_ISSET(cpu, &allowed) && (primary_mask & (std::uint64_t{1} << cpu)))
                ++primary_in_mask;
    }
    // A logical-only dev A/B trial may have already pinned the SHADER
    // parent to a kernel-verified secondary mask. It is then wrong to
    // subtract the seven primary CPU/GPU services AGAIN. Do not equate
    // this proof of LOGICAL nonoverlap with physical/SMT core identity.
    const std::uint64_t secondary_mask = ::Eden::Performance::VerifiedSecondaryPlacementMask();
    const bool secondary_isolated = affinity_rc == 0 && allowed_mask != 0 &&
        secondary_mask != 0 && (allowed_mask & ~secondary_mask) == 0;
    constexpr size_t secondary_headroom = 2;
    constexpr size_t unverified_reserved = 7;
    constexpr size_t max_pipeline_workers = 6;
    const size_t reserved = affinity_rc == 0 && primary_mask ?
        primary_in_mask + secondary_headroom :
        secondary_isolated ? secondary_headroom : unverified_reserved;
    const size_t spare = schedulable > reserved ? schedulable - reserved : 0ULL;
    const size_t selected = std::max<size_t>(1ULL, std::min(spare, max_pipeline_workers));
    std::printf("EDEN_PS5_SHADER_WORKERS reported=%zu available=%zu workers=%zu "
                "reserved=%zu primary_in_mask=%zu physical_verified=%u logical_isolated=%u affinity_rc=%d "
                "allowed_mask=0x%llx primary_mask=0x%llx secondary_mask=0x%llx\\n",
                reported, available, selected, reserved, primary_in_mask,
                unsigned(primary_mask != 0), unsigned(secondary_isolated), affinity_rc,
                static_cast<unsigned long long>(allowed_mask),
                static_cast<unsigned long long>(primary_mask),
                static_cast<unsigned long long>(secondary_mask));
    return selected;
#else
    return max_core_threads;
#endif
#endif
}'''
if shader_source.count(pipeline_worker_anchor) != 1:
    raise RuntimeError('Pinned Vulkan pipeline worker policy changed')
shader_source = shader_source.replace(pipeline_worker_anchor, pipeline_worker_replacement)
for expression, index, count in (
    ('main_pools.ReleaseContents()', 19, 2),
    ('TranslateProgram(pools.inst, pools.block, env, cfg, host_info)', 21, 3),
    ('EmitSPIRV(profile, runtime_info, program, binding)', 22, 1),
    ('EmitSPIRV(profile, program)', 22, 1),
    ('BuildShader(device, code)', 23, 2),
):
    if shader_source.count(expression) != count:
        raise RuntimeError(f'Shader cost anchor changed: {expression}')
    shader_source = shader_source.replace(expression,
        f'([&] {{ auto cost = Eden::Performance::VulkanTimer({index}); '
        f'return {expression}; }}())')
for statement in (
    'Shader::Maxwell::Flow::CFG cfg(env, pools.flow_block, cfg_offset, index == 0);',
    'Shader::Maxwell::Flow::CFG cfg{env, pools.flow_block, env.StartAddress()};',
):
    expected = 2 if 'cfg_offset' in statement else 1  # graphics exception dump too
    if shader_source.count(statement) != expected:
        raise RuntimeError(f'Shader CFG anchor changed: {statement}')
    shader_source = shader_source.replace(statement,
        'auto cfg_cost = Eden::Performance::VulkanTimer(20);\n        ' + statement +
        '\n        cfg_cost.reset();')
for old, new in shader_costs:
    if shader_source.count(old) != 1:
        raise RuntimeError(f'Shader pipeline anchor changed: {old[:60]}')
    shader_source = shader_source.replace(old, new)
# F07 P0.1: profile actual cold shader work in the native detailed profile.
# Quiet mode does not take additional clock readings. Preserve exact source parity.
for shader_call, index, phase, expected in (
    ("main_pools.ReleaseContents()", 19, "ShaderPoolReset", 2),
    ("TranslateProgram(pools.inst, pools.block, env, cfg, host_info)", 21, "ShaderIr", 3),
    ("EmitSPIRV(profile, runtime_info, program, binding)", 22, "ShaderSpirv", 1),
    ("EmitSPIRV(profile, program)", 22, "ShaderSpirv", 1),
    ("BuildShader(device, code)", 23, "ShaderModule", 2),
):
    before = f'auto cost = Eden::Performance::VulkanTimer({index}); return {shader_call};'
    after = (f'auto cost = Eden::Performance::VulkanTimer({index}); '
             f'::Eden::Performance::CachePhaseTimer stage_cost{{::Eden::Performance::CachePhase::{phase}, '
             f'::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)}}; return {shader_call};')
    if shader_source.count(before) != expected:
        raise RuntimeError(f'F07 shader stage timing drift {phase}: {shader_call}')
    shader_source = shader_source.replace(before, after)
cfg_match = r'(?m)^( +)auto cfg_cost = Eden::Performance::VulkanTimer\(20\);$'
def add_shader_cfg_timer(match):
    indent = match.group(1)
    return (indent + '::Eden::Performance::CachePhaseTimer cfg_stage_cost{\n'
            + indent + '    ::Eden::Performance::CachePhase::ShaderCfg,\n'
            + indent + '    ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)};\n'
            + match.group(0))
if len(re.findall(cfg_match, shader_source)) != 3:
    raise RuntimeError('F07 shader CFG stage timer insertion mismatch')
shader_source = re.sub(cfg_match, add_shader_cfg_timer, shader_source)
cfg_done = '        cfg_cost.reset();'
if shader_source.count(cfg_done) != 3:
    raise RuntimeError('F07 shader CFG completion mismatch')
shader_source = shader_source.replace(cfg_done, cfg_done + '\n        cfg_stage_cost.Stop();')

# R403: On native PS5 do not silently discard a guest graphics draw just
# because its asynchronous shader pipeline is compiling. ConfigureDraw already
# waits via a GPU scheduler worker and R378 publishes completion even on error.
# Desktop/mobile retain upstream first-use skip policy.
ps5_first_use_old = (
    '    if (pipeline->IsBuilt()) {\n'
    '        return pipeline;\n'
    '    }\n'
    '    if (!use_asynchronous_shaders) {'
)
ps5_first_use_new = (
    '    if (pipeline->IsBuilt()) {\n'
    '        return pipeline;\n'
    '    }\n'
    '#ifdef PS5_NATIVE\n'
    '    // Prefer correct output over a missing shader draw. A not-yet-built\n'
    '    // async pipeline is safe to return: ConfigureDraw records an ordered\n'
    "    // scheduler-worker wait, and R378's SCOPE_EXIT publishes completion\n"
    '    // even on worker failure. No waiting under the guest cache pair here.\n'
    '    // The standard "skip complex first-use draws" policy stays unchanged\n'
    '    // on desktop/mobile, where it can improve cold first-use frame times.\n'
    '    return pipeline;\n'
    '#endif\n'
    '    if (!use_asynchronous_shaders) {'
)
if shader_source.count(ps5_first_use_old) != 1:
    raise RuntimeError('PS5 visual-first pipeline source anchor drift')
shader_source = shader_source.replace(ps5_first_use_old, ps5_first_use_new)

# F07: instrument ALL cold graphics pipeline CPU creations when detailed
# diagnostics are enabled; leave the quiet hot path and draw order unchanged.
f07_pipeline_old = "    if (is_new) {\n        pipeline = CreateGraphicsPipeline();\n    }"
f07_pipeline_new = "    if (is_new) {\n#ifdef PS5_NATIVE\n        // F07: first-use guest shader translation and SPIR-V generation are\n        // synchronous even when the Vulkan pipeline build is queued.\n        // Count EVERY cold miss with Detailed Logging, not one in 16 draws.\n        // Quiet releases take no clock readings on this path.\n        ::Eden::Performance::CachePhaseTimer first_use_cpu_phase{\n            ::Eden::Performance::CachePhase::GraphicsPipelineCreate,\n            ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)};\n#endif\n        pipeline = CreateGraphicsPipeline();\n    }"
if shader_source.count(f07_pipeline_old) != 1:
    raise RuntimeError('F07 pinned cold graphics pipeline source drift')
shader_source = shader_source.replace(f07_pipeline_old, f07_pipeline_new, 1)

# F07: a failed deferred driver-cache save/read must release its in-flight
# guard or all subsequent scheduled cache snapshots become permanently blocked.
# Fail closed on pinned shader cache source changes; keep the active native
# translation unit exactly reproducible from this generator.
f07_flush_old = "    serialization_thread.QueueWork([this] {\n        SerializeVulkanPipelineCache(vulkan_pipeline_cache_filename, vulkan_pipeline_cache,\n                                     CACHE_VERSION);\n        size_t size = 0;\n        vulkan_pipeline_cache.Read(&size, nullptr);\n        last_cache_size.store(size, std::memory_order_relaxed);\n        flush_in_flight.store(false, std::memory_order_release);\n    });"
f07_flush_new = "    // A transient driver-cache read or serializer exception must not pin\n    // flush_in_flight=true for the lifetime of the foreground title.\n    // Keep the existing periodic budget, filename and background worker.\n    try {\n        serialization_thread.QueueWork([this] {\n            struct ReleaseFlush {\n                std::atomic_bool& in_flight;\n                ~ReleaseFlush() { in_flight.store(false, std::memory_order_release); }\n            } release{flush_in_flight};\n            try {\n                SerializeVulkanPipelineCache(vulkan_pipeline_cache_filename, vulkan_pipeline_cache,\n                                             CACHE_VERSION);\n                size_t size = 0;\n                vulkan_pipeline_cache.Read(&size, nullptr);\n                last_cache_size.store(size, std::memory_order_relaxed);\n            } catch (const std::exception& error) {\n                LOG_WARNING(Render_Vulkan, \"Deferred driver cache flush failed: {}\", error.what());\n            } catch (...) {\n                LOG_WARNING(Render_Vulkan, \"Deferred driver cache flush failed: unknown exception\");\n            }\n        });\n    } catch (...) {\n        flush_in_flight.store(false, std::memory_order_release);\n        throw;\n    }"
# A rejected asynchronous cache-save job is non-fatal for gameplay.
# The generated fragment replaces only the C++ catch suffix, not the outer function.
f07_reject_old = '''    } catch (...) {
        flush_in_flight.store(false, std::memory_order_release);
        throw;
    }'''
f07_reject_new = '''    } catch (const std::exception& error) {
        flush_in_flight.store(false, std::memory_order_release);
        // Keep this checkpoint due for a later retry, without bypassing the
        // existing time gate if the serializer is temporarily unavailable.
        pipelines_since_flush = VULKAN_CACHE_FLUSH_PIPELINES;
        LOG_WARNING(Render_Vulkan, "Deferred cache flush queue rejected: {}", error.what());
    } catch (...) {
        flush_in_flight.store(false, std::memory_order_release);
        pipelines_since_flush = VULKAN_CACHE_FLUSH_PIPELINES;
        LOG_WARNING(Render_Vulkan, "Deferred cache flush queue rejected: unknown exception");
    }'''
if f07_flush_new.count(f07_reject_old) != 1:
    raise RuntimeError('F07 queue rejection source anchor drift')
f07_flush_new = f07_flush_new.replace(f07_reject_old, f07_reject_new, 1)
if shader_source.count(f07_flush_old) != 1:
    raise RuntimeError('F07 pipeline disk-cache flush anchor drift')
shader_source = shader_source.replace(f07_flush_old, f07_flush_new, 1)

# F07: PS5 restores a strictly bounded prefix of persisted title pipelines.
# Only the file-reader stop token is cancelled. Never pass that token to
# ThreadWorker::WaitForRequests: it would stop the persistent shader pool.
f07_warm_before_0 = "#include <span>\n#include <thread>"
f07_warm_after_0 = "#include <span>\n#include <stop_token>\n#include <thread>"
if shader_source.count(f07_warm_before_0) != 1:
    raise RuntimeError('F07 bounded cache prewarm anchor 0 moved')
shader_source = shader_source.replace(f07_warm_before_0, f07_warm_after_0)
f07_warm_before_1 = "    struct {\n        std::mutex mutex;\n        size_t total{};"
f07_warm_after_1 = "#ifdef PS5_NATIVE\n    // Restore a bounded prefix of a title\'s saved pipelines before gameplay.\n    // Games with fewer cached entries load only those entries. This policy\n    // applies to every title (NS1 and NS2) without any title ID exceptions.\n    // Keep the worker queue, draw order and GPU fences unchanged.\n    constexpr size_t kStartupPrewarmPipelines = 32;\n    std::stop_source startup_reader;\n#endif\n    struct {\n        std::mutex mutex;\n        size_t total{};"
if shader_source.count(f07_warm_before_1) != 1:
    raise RuntimeError('F07 bounded cache prewarm anchor 1 moved')
shader_source = shader_source.replace(f07_warm_before_1, f07_warm_after_1)
f07_warm_before_2 = "        ++state.total;\n    }};"
f07_warm_after_2 = "        ++state.total;\n#ifdef PS5_NATIVE\n        if (state.total == kStartupPrewarmPipelines)\n            startup_reader.request_stop();\n#endif\n    }};"
if shader_source.count(f07_warm_before_2) != 2:
    raise RuntimeError('F07 bounded cache prewarm anchor 2 moved')
shader_source = shader_source.replace(f07_warm_before_2, f07_warm_after_2)
f07_warm_before_3 = "    VideoCommon::LoadPipelines(stop_loading, pipeline_cache_filename, CACHE_VERSION, load_compute,\n                               load_graphics);"
f07_warm_after_3 = "    // Only the reader observes the quota stop. Passing this token to\n    // workers.WaitForRequests() would permanently request_stop() on the\n    // shader-builder pool, breaking first-use shaders later in gameplay.\n#ifdef PS5_NATIVE\n    const std::stop_token reader_token{startup_reader.get_token()};\n#else\n    const std::stop_token reader_token{stop_loading};\n#endif\n#ifdef PS5_NATIVE\n    // The progress callback below also runs before the normal drain and can\n    // throw. Keep locally borrowed prewarm state alive on EVERY exceptional\n    // exit, not only failures of the disk reader. No extra wait on success.\n    struct PrewarmDrain {\n        Common::ThreadWorker& compiler;\n        bool joined{};\n        ~PrewarmDrain() {\n            if (!joined) compiler.WaitForRequests();\n        }\n    } prewarm_drain{workers};\n#endif\n#ifdef PS5_NATIVE\n    // A damaged disk cache or an enqueue failure can interrupt the reader\n    // after jobs borrowed local state. Always reach the non-cancelling drain.\n    try {\n#endif\n        VideoCommon::LoadPipelines(reader_token, pipeline_cache_filename, CACHE_VERSION, load_compute,\n                                   load_graphics);\n#ifdef PS5_NATIVE\n    } catch (const std::exception& error) {\n        LOG_WARNING(Render_Vulkan, \"PS5 shader prewarm aborted: {}\", error.what());\n    } catch (...) {\n        LOG_WARNING(Render_Vulkan, \"PS5 shader prewarm aborted: unknown exception\");\n    }\n#endif"
if shader_source.count(f07_warm_before_3) != 1:
    raise RuntimeError('F07 bounded cache prewarm anchor 3 moved')
shader_source = shader_source.replace(f07_warm_before_3, f07_warm_after_3)
f07_warm_before_4 = "    workers.WaitForRequests(stop_loading);\n\n    if (use_vulkan_pipeline_cache) {"
f07_warm_after_4 = "#ifdef PS5_NATIVE\n    // A cancelled title-cache load must never stop the persistent shader\n    // compiler pool: StatefulThreadWorker::WaitForRequests(stop_token)\n    // requests stop on every worker when that token is cancelled.\n    // Only the disk reader observes cancellation. The bounded queued jobs\n    // must complete before their borrowed stack state can be destroyed.\n    workers.WaitForRequests();\n    prewarm_drain.joined = true;\n#else\n    workers.WaitForRequests(stop_loading);\n#endif\n#ifdef PS5_NATIVE\n    LOG_INFO(Render_Vulkan, \"PS5 shader cache bounded prewarm built {}/{} entries\",\n             state.built, state.total);\n#endif\n\n    if (use_vulkan_pipeline_cache) {"
if shader_source.count(f07_warm_before_4) != 1:
    raise RuntimeError('F07 bounded cache prewarm anchor 4 moved')
shader_source = shader_source.replace(f07_warm_before_4, f07_warm_after_4)

# F07: on PS5, drain queued shader-environment serialization at game exit.
# Without it ThreadWorker's jthread destruction can stop queued jobs before
# they are persisted; the next session recompiles the same first-use shaders.
# No gameplay-frame lock or additional disk write is introduced.
f07_drain_old = "PipelineCache::~PipelineCache() {\n    EdenResetStaticVertexInputBinding();"
f07_drain_new = "PipelineCache::~PipelineCache() {\n    EdenResetStaticVertexInputBinding();\n#ifdef PS5_NATIVE\n    // First-use shader environments are serialized on this worker. Let all\n    // accepted writes finish before destroying the worker and VkPipelineCache,\n    // or a later launch re-translates shaders that were never persisted.\n    // This is a shutdown-only drain, never a wait in the draw hot path.\n    serialization_thread.WaitForRequests();\n#endif"
if shader_source.count(f07_drain_old) != 1:
    raise RuntimeError('F07 pipeline-cache shutdown drain anchor drift')
shader_source = shader_source.replace(f07_drain_old, f07_drain_new, 1)

# Write only after ALL native pipeline-cache deltas, including startup prewarm.
# Earlier emission silently discarded the last five F07 transformations.
# F07: do not admit failed Vulkan handles into the bounded startup cache.
f07_preseed_compute_old = "            if (pipeline) {\n                compute_cache.emplace(key, std::move(pipeline));\n            }"
f07_preseed_compute_new = "            // Do not seed a failed Vulkan compute pipeline for future dispatches.\n            if (pipeline && pipeline->IsBound()) {\n                compute_cache.emplace(key, std::move(pipeline));\n            }"
if shader_source.count(f07_preseed_compute_old) != 1:
    raise RuntimeError('F07 compute warm cache insertion anchor drift')
shader_source = shader_source.replace(f07_preseed_compute_old, f07_preseed_compute_new, 1)
f07_preseed_graphics_old = "            if (pipeline) {\n                graphics_cache.emplace(key, std::move(pipeline));\n            }"
f07_preseed_graphics_new = "            // Leave a failed Vulkan build absent from the prewarm map,\n            // so the normal first-use path may try the key again.\n#ifdef PS5_NATIVE\n            if (pipeline && pipeline->CanExecuteDraw()) {\n#else\n            if (pipeline) {\n#endif\n                graphics_cache.emplace(key, std::move(pipeline));\n            }"
if shader_source.count(f07_preseed_graphics_old) != 1:
    raise RuntimeError('F07 graphics warm cache insertion anchor drift')
shader_source = shader_source.replace(f07_preseed_graphics_old, f07_preseed_graphics_new, 1)

# F07: report truly usable prewarmed Vulkan pipelines, not merely attempts.
# No measurements are taken during draw/dispatch; one line at game startup.
f07_prewarm_metrics_old_0 = "    constexpr size_t kStartupPrewarmPipelines = 32;\n    std::stop_source startup_reader;"
f07_prewarm_metrics_new_0 = "    constexpr size_t kStartupPrewarmPipelines = 32;\n    const auto startup_prewarm_started = std::chrono::steady_clock::now();\n    std::stop_source startup_reader;"
if shader_source.count(f07_prewarm_metrics_old_0) != 1:
    raise RuntimeError('F07 prewarm outcome metric anchor 0 changed')
shader_source = shader_source.replace(f07_prewarm_metrics_old_0, f07_prewarm_metrics_new_0, 1)
f07_prewarm_metrics_old_1 = "        size_t built{};\n        bool has_loaded{};"
f07_prewarm_metrics_new_1 = "        size_t built{};\n        size_t valid{};\n        bool has_loaded{};"
if shader_source.count(f07_prewarm_metrics_old_1) != 1:
    raise RuntimeError('F07 prewarm outcome metric anchor 1 changed')
shader_source = shader_source.replace(f07_prewarm_metrics_old_1, f07_prewarm_metrics_new_1, 1)
f07_prewarm_metrics_old_2 = "            if (pipeline && pipeline->IsBound()) {\n                compute_cache.emplace(key, std::move(pipeline));\n            }"
f07_prewarm_metrics_new_2 = "            if (pipeline && pipeline->IsBound()) {\n                compute_cache.emplace(key, std::move(pipeline));\n                ++state.valid;\n            }"
if shader_source.count(f07_prewarm_metrics_old_2) != 1:
    raise RuntimeError('F07 prewarm outcome metric anchor 2 changed')
shader_source = shader_source.replace(f07_prewarm_metrics_old_2, f07_prewarm_metrics_new_2, 1)
f07_prewarm_metrics_old_3 = "#ifdef PS5_NATIVE\n            if (pipeline && pipeline->CanExecuteDraw()) {\n#else\n            if (pipeline) {\n#endif\n                graphics_cache.emplace(key, std::move(pipeline));\n            }"
f07_prewarm_metrics_new_3 = "#ifdef PS5_NATIVE\n            if (pipeline && pipeline->CanExecuteDraw()) {\n#else\n            if (pipeline) {\n#endif\n                graphics_cache.emplace(key, std::move(pipeline));\n                ++state.valid;\n            }"
if shader_source.count(f07_prewarm_metrics_old_3) != 1:
    raise RuntimeError('F07 prewarm outcome metric anchor 3 changed')
shader_source = shader_source.replace(f07_prewarm_metrics_old_3, f07_prewarm_metrics_new_3, 1)
f07_prewarm_metrics_old_4 = "    LOG_INFO(Render_Vulkan, \"PS5 shader cache bounded prewarm built {}/{} entries\",\n             state.built, state.total);"
f07_prewarm_metrics_new_4 = "    // Completed attempts include failed native handles; track valid results.\n    // One startup summary, never a per-frame or per-draw instrumentation cost.\n    const auto startup_prewarm_ms = std::chrono::duration_cast<std::chrono::milliseconds>(\n        std::chrono::steady_clock::now() - startup_prewarm_started).count();\n    std::printf(\"EDEN_PS5_SHADER_PREWARM queued=%zu completed=%zu valid=%zu rejected=%zu prebuild_ms=%lld limit=%zu\\n\",\n                state.total, state.built, state.valid, state.built - state.valid,\n                static_cast<long long>(startup_prewarm_ms), kStartupPrewarmPipelines);"
if shader_source.count(f07_prewarm_metrics_old_4) != 1:
    raise RuntimeError('F07 prewarm outcome metric anchor 4 changed')
shader_source = shader_source.replace(f07_prewarm_metrics_old_4, f07_prewarm_metrics_new_4, 1)

# F07: shader-cache metadata is optional persistence, not admission of the
# already-compiled live graphics/compute pipeline. A serializer queue error
# must not permanently null-cache a valid shader after its first use.
f07_serializer_graphics_old = "    serialization_thread.QueueWork([this, key = graphics_key, envs = std::move(environments.envs)] {\n        boost::container::static_vector<const GenericEnvironment*, Maxwell::MaxShaderProgram>\n            env_ptrs;\n        for (size_t index = 0; index < Maxwell::MaxShaderProgram; ++index) {\n            if (key.unique_hashes[index] != 0) {\n                env_ptrs.push_back(&envs[index]);\n            }\n        }\n        SerializePipeline(key, env_ptrs, pipeline_cache_filename, CACHE_VERSION);\n    });"
f07_serializer_graphics_new = "#ifdef PS5_NATIVE\n    // Cache persistence is optional to running this shader. A rejected\n    // serializer job must not discard an otherwise usable Vulkan pipeline.\n    try {\n#endif\n    serialization_thread.QueueWork([this, key = graphics_key, envs = std::move(environments.envs)] {\n        boost::container::static_vector<const GenericEnvironment*, Maxwell::MaxShaderProgram>\n            env_ptrs;\n        for (size_t index = 0; index < Maxwell::MaxShaderProgram; ++index) {\n            if (key.unique_hashes[index] != 0) {\n                env_ptrs.push_back(&envs[index]);\n            }\n        }\n        SerializePipeline(key, env_ptrs, pipeline_cache_filename, CACHE_VERSION);\n    });\n#ifdef PS5_NATIVE\n    } catch (const std::exception& error) {\n        LOG_WARNING(Render_Vulkan, \"Graphics shader cache write not queued: {}\", error.what());\n    } catch (...) {\n        LOG_WARNING(Render_Vulkan, \"Graphics shader cache write not queued: unknown exception\");\n    }\n#endif"
f07_serializer_compute_old = "    serialization_thread.QueueWork([this, key, env_ = std::move(env)] {\n        SerializePipeline(key, std::array<const GenericEnvironment*, 1>{&env_},\n                          pipeline_cache_filename, CACHE_VERSION);\n    });"
f07_serializer_compute_new = "#ifdef PS5_NATIVE\n    // Cache persistence is optional to running this shader. A rejected\n    // serializer job must not discard an otherwise usable Vulkan pipeline.\n    try {\n#endif\n    serialization_thread.QueueWork([this, key, env_ = std::move(env)] {\n        SerializePipeline(key, std::array<const GenericEnvironment*, 1>{&env_},\n                          pipeline_cache_filename, CACHE_VERSION);\n    });\n#ifdef PS5_NATIVE\n    } catch (const std::exception& error) {\n        LOG_WARNING(Render_Vulkan, \"Compute shader cache write not queued: {}\", error.what());\n    } catch (...) {\n        LOG_WARNING(Render_Vulkan, \"Compute shader cache write not queued: unknown exception\");\n    }\n#endif"
for name, old, new in (
    ("graphics", f07_serializer_graphics_old, f07_serializer_graphics_new),
    ("compute", f07_serializer_compute_old, f07_serializer_compute_new),
):
    if shader_source.count(old) != 1:
        raise RuntimeError(f"F07 {name} shader-cache queue admission anchor drift")
    shader_source = shader_source.replace(old, new, 1)

# F07 P0.1: isolate the synchronous guest-environment preparation from
# shader CFG, IR and SPIR-V translation. This adds a clock only in Detailed
# Logging and never changes guest reads, pipeline order or worker ownership.
f07_environment_old = "    GetGraphicsEnvironments(environments, graphics_key.unique_hashes);"
f07_environment_new = "    // Preparing guest shader environments is distinct from CFG/IR/SPIR-V\n    // translation. Keep GPU-thread ownership and source read order unchanged.\n    // Quiet release does not read a clock or update counters.\n    {\n        ::Eden::Performance::CachePhaseTimer environment_cost{\n            ::Eden::Performance::CachePhase::GraphicsShaderEnvironment,\n            ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)};\n        GetGraphicsEnvironments(environments, graphics_key.unique_hashes);\n    }"
if shader_source.count(f07_environment_old) != 1:
    raise RuntimeError("F07 graphics shader environment timing anchor drift")
shader_source = shader_source.replace(f07_environment_old, f07_environment_new, 1)

# F07 B1: reader and workers share the prewarm progress counter.
# A worker may acquire state.mutex to inspect state.total before the
# disk reader has finished enqueueing. Keep both writes under that mutex.
# The stop token remains reader-only and is requested outside the lock.
f07_prewarm_total_old = "        ++state.total;\n#ifdef PS5_NATIVE\n        if (state.total == kStartupPrewarmPipelines)\n            startup_reader.request_stop();\n#endif\n    }};"
f07_prewarm_total_new = "        // Workers read total while holding state.mutex. Publish reader\n        // increments under the same lock to avoid a cache-prewarm data race.\n        {\n            std::scoped_lock count_lock{state.mutex};\n            ++state.total;\n        }\n#ifdef PS5_NATIVE\n        if (state.total == kStartupPrewarmPipelines)\n            startup_reader.request_stop();\n#endif\n    }};"
if shader_source.count(f07_prewarm_total_old) != 2:
    raise RuntimeError("F07 prewarm progress mutex anchor drift")
shader_source = shader_source.replace(f07_prewarm_total_old, f07_prewarm_total_new)

shader_output = output / 'vk_pipeline_cache_cost.cpp'
if not shader_output.exists() or shader_output.read_text() != shader_source:
    shader_output.write_text(shader_source)


# Scope only the existing synchronous operations; never alter their ordering.
# Report these caller costs separately from the overlapping API totals.
import re
# Development GPU fault probes (dev_vulkan.h): multi-range storage buffers are
# the one path that binds sparse ranges of the console's device memory.
probes = {
    'vk_fence_manager': [
        ("void InnerFence::Wait() {\n    if (is_stubbed) {\n        return;\n    }\n    { auto timer = Eden::Performance::VulkanTimer(6); scheduler.Wait(wait_tick); }\n}", "void InnerFence::Wait() {\n    if (is_stubbed || scheduler.IsFree(wait_tick)) {\n        return;\n    }\n    // Completed timeline ticks cannot become pending again. Avoid another\n    // scheduler wait, queue flush check and blocking host semaphore call.\n    { auto timer = Eden::Performance::VulkanTimer(6); scheduler.Wait(wait_tick); }\n}"),
    ],
    'vk_multi_range_buffer': [
        ("    if (sources.empty() || total == 0) {\n        return MultiRangeRef{};\n    }\n    if (!retired.empty()) {", "    if (sources.empty() || total == 0) {\n        return MultiRangeRef{};\n    }\n    // Gathered fallbacks must obey the same destination bounds as sparse binds.\n    // Reject an invalid source before allocating a GPU buffer or recording copies.\n    VkDeviceSize covered = 0;\n    for (const MultiRangeSource& source : sources) {\n        if (source.handle == VK_NULL_HANDLE || source.size == 0 ||\n            source.size > total - covered ||\n            source.offset > std::numeric_limits<VkDeviceSize>::max() - source.size) {\n            return MultiRangeRef{};\n        }\n        covered += source.size;\n    }\n    if (!retired.empty()) {"),
        ("    if (CanBindSparse(sources)) {\n        entry.sparse_handle = CreateSparse(device, scheduler, sources, total);\n        if (entry.sparse_handle) {\n            entry.owners.reserve(sources.size());\n            for (const MultiRangeSource& source : sources) {\n                entry.owners.push_back(source.handle);\n            }\n        }\n    }", "    // Both sparse and gathered bindings keep their source owners. Otherwise\n    // DropOwner cannot retire a gathered buffer after its input is destroyed.\n    entry.owners.reserve(sources.size());\n    for (const MultiRangeSource& source : sources) {\n        entry.owners.push_back(source.handle);\n    }\n    if (CanBindSparse(sources)) {\n        entry.sparse_handle = CreateSparse(device, scheduler, sources, total);\n    }"),
        ("    for (const MultiRangeSource& source : sources) {\n        mix(u64(source.handle));\n        mix(u64(source.offset));\n        mix(u64(source.size));\n    }", "    for (const MultiRangeSource& source : sources) {\n        mix(u64(source.handle));\n        mix(u64(source.memory));\n        mix(u64(source.memory_offset));\n        mix(u64(source.memory_type));\n        mix(u64(source.offset));\n        mix(u64(source.size));\n    }"),
        ("bool MultiRangeBufferCache::CanBindSparse(std::span<const MultiRangeSource> sources) const {\n    return use_sparse &&\n           std::none_of(sources.begin(), sources.end(),\n                        [block = block_size, bits = sparse_memory_type_bits](auto const& e) {\n                            const VkDeviceSize memory_offset = e.memory_offset + e.offset;\n                            return e.memory == VK_NULL_HANDLE || e.memory_type >= 32 ||\n                                   ((bits >> e.memory_type) & 1) == 0 ||\n                                   (memory_offset % block) != 0 || (e.size % block) != 0;\n                        });\n}\n", "bool MultiRangeBufferCache::CanBindSparse(std::span<const MultiRangeSource> sources) const {\n    if (!use_sparse || block_size == 0 || sources.empty()) {\n        return false;\n    }\n    return std::none_of(sources.begin(), sources.end(),\n                        [block = block_size, bits = sparse_memory_type_bits](auto const& e) {\n                            if (e.memory == VK_NULL_HANDLE || e.memory_type >= 32 ||\n                                ((bits >> e.memory_type) & 1) == 0 || e.size == 0 ||\n                                e.memory_offset > std::numeric_limits<VkDeviceSize>::max() - e.offset) {\n                                return true;\n                            }\n                            const VkDeviceSize memory_offset = e.memory_offset + e.offset;\n                            return memory_offset > std::numeric_limits<VkDeviceSize>::max() - e.size ||\n                                   (memory_offset % block) != 0 || (e.size % block) != 0;\n                        });\n}"),
        ("                                                 VkDeviceSize total) {\n    const VkDevice logical = *device.GetLogical();", "                                                 VkDeviceSize total) {\n    // Bound source offsets and destination extents before Vulkan allocation.\n    if (sources.empty() || total == 0 ||\n        sources.size() > std::numeric_limits<u32>::max()) {\n        return SparseBuffer{};\n    }\n    VkDeviceSize checked_total = 0;\n    for (const MultiRangeSource& source : sources) {\n        if (source.size == 0 || source.size > total - checked_total ||\n            source.memory_offset > std::numeric_limits<VkDeviceSize>::max() - source.offset ||\n            source.memory_offset + source.offset >\n                std::numeric_limits<VkDeviceSize>::max() - source.size) {\n            return SparseBuffer{};\n        }\n        checked_total += source.size;\n    }\n    const VkDevice logical = *device.GetLogical();"),
        ('#include <algorithm>', '#include <algorithm>\n#include <cstdio>\n#include <limits>\n#include "dev_vulkan.h"\n#include "diagnostics.h"'),
        ('    if (bind_result != VK_SUCCESS) {\n        return SparseBuffer{};\n    }',
         '    if (bind_result != VK_SUCCESS) {\n'
         '        if (::Eden::DevVulkan::trace_pipelines) ::Eden::Report("multirange", "sparse bind failed");\n'
         '        return SparseBuffer{};\n    }'),
        ('    retired.push_back(Retired{',
         '    if (::Eden::DevVulkan::trace_pipelines) {\n'
         '        static unsigned retires = 0;\n'
         '        if (++retires <= 64) {\n'
         '            char text[96];\n'
         '            std::snprintf(text, sizeof(text), "retire #%u sparse=%d tick=%llu", retires,\n'
         '                          int(bool(entry.sparse_handle)), (unsigned long long)scheduler.CurrentTick());\n'
         '            ::Eden::Report("multirange", text);\n'
         '        }\n'
         '    }\n'
         '    retired.push_back(Retired{'),
        ('    entries.emplace(key, std::move(entry));',
         '    if (::Eden::DevVulkan::trace_pipelines) {\n'
         '        static unsigned created = 0;\n'
         '        if (++created <= 256) {\n'
         '            char text[192];\n'
         '            std::snprintf(text, sizeof(text), "new #%u key=%llx total=%llu sources=%zu sparse=%d addr=%llx",\n'
         '                          created, (unsigned long long)key, (unsigned long long)total, sources.size(),\n'
         '                          int(bool(entry.sparse_handle)), (unsigned long long)entry.address);\n'
         '            ::Eden::Report("multirange", text);\n'
         '        }\n'
         '    }\n'
         '    entries.emplace(key, std::move(entry));'),
    ],
    'vk_buffer_cache': [
        # Capture the completed GPU tick once per resident-buffer scan.
        ("void BufferCacheRuntime::TickFrame(Common::SlotVector<Buffer>& slot_buffers) noexcept {\n    for (auto it = slot_buffers.begin(); it != slot_buffers.end(); it++) {\n        if (scheduler.IsFree(it->LastUsageTick())) {\n            it->ResetUsageTracking();\n        }\n    }\n}", "void BufferCacheRuntime::TickFrame(Common::SlotVector<Buffer>& slot_buffers) noexcept {\n#ifdef PS5_NATIVE\n    // No tracked buffers: avoid even the GPU-completion semaphore snapshot.\n    if (slot_buffers.begin() == slot_buffers.end()) {\n        return;\n    }\n#endif\n    // One monotone GPU completion snapshot per pass instead of an atomic load\n    // per resident buffer. A completion during this pass is reclaimed next frame.\n#ifdef PS5_NATIVE\n    // Idle resident buffers have zero usage ticks after retirement. Defer the\n    // GPU completion query until a nonzero tick actually needs inspection,\n    // rather than probing every rendered frame with no outstanding usage.\n    u64 completed_tick = 0;\n    bool sampled_completed_tick = false;\n#else\n    const u64 completed_tick = scheduler.GetMasterSemaphore().KnownGpuTick();\n#endif\n    for (auto it = slot_buffers.begin(); it != slot_buffers.end(); it++) {\n#ifdef PS5_NATIVE\n        // ResetUsageTracking resets the tick to zero. Don't rescan usage pages\n        // or query driver completion for any already retired buffer.\n        const u64 last_tick = it->LastUsageTick();\n        if (last_tick == 0) {\n            continue;\n        }\n        if (!sampled_completed_tick) {\n            completed_tick = scheduler.GetMasterSemaphore().KnownGpuTick();\n            sampled_completed_tick = true;\n        }\n        if (last_tick <= completed_tick) {\n#else\n        if (it->LastUsageTick() <= completed_tick) {\n#endif\n            it->ResetUsageTracking();\n        }\n    }\n}"),
        # An inverted/clipped guest vertex-binding range must not wrap u32.
        ("    const u32 min_binding = (std::min)(bindings.min_index, device_max);\n    const u32 max_binding = (std::min)(bindings.max_index, device_max);\n    const u32 binding_count = max_binding - min_binding;\n    if (binding_count == 0) {\n        return;\n    }", "    const u32 min_binding = (std::min)(bindings.min_index, device_max);\n    const u32 max_binding = (std::min)(bindings.max_index, device_max);\n    // Do not wrap a reversed binding range into a huge Vulkan binding count.\n    if (max_binding <= min_binding) {\n        return;\n    }\n    const u32 binding_count = max_binding - min_binding;"),
        # Incomplete quads and strips use the already-supported null index buffer.
        ("void BufferCacheRuntime::BindQuadIndexBuffer(PrimitiveTopology topology, u32 first, u32 count) {\n    if (count == 0) {", "void BufferCacheRuntime::BindQuadIndexBuffer(PrimitiveTopology topology, u32 first, u32 count) {\n    // A quad or quad strip requires four vertices for one primitive.\n    // Avoid creating a zero-size index LUT for incomplete draws.\n    if (count < 4) {"),
        # The first quad index LUT is a fresh buffer, not a resize of an in-flight
        # buffer. Avoid a full-device Finish while both guest caches are locked.
        ("        { auto timer = Eden::Performance::VulkanTimer(7); scheduler.Finish(); }\n\n        num_indices = num_indices_;",
         "        // The very first LUT has no previous device buffer to protect.\n        // Keep the original GPU fence when replacing an already-used buffer.\n        if (buffer) {\n            { auto timer = Eden::Performance::VulkanTimer(7); scheduler.Finish(); }\n        }\n\n        num_indices = num_indices_;"),
        ('#include <algorithm>', '#include <algorithm>\n#include "dev_vulkan.h"'),
        ('bool BufferCacheRuntime::BindMultiRangeStorageBuffer(u64 key, bool is_written) {\n',
         'bool BufferCacheRuntime::BindMultiRangeStorageBuffer(u64 key, bool is_written) {\n'
         '    if (::Eden::DevVulkan::disable_multi_range) {\n        return false;\n    }\n'),
    ],
    # With custom border colours off (the console default), report which clamp-to-border
    # samplers ask for a colour the three standard ones cannot give exactly.
    'vk_texture_cache': [
        ('#include <algorithm>', '#include <algorithm>\n#include <cstdio>\n#include "dev_vulkan.h"\n#include "diagnostics.h"'),
        ('    has_custom_border_colors = samples_border && device.IsCustomBorderColorUsable();',
         '    if (::Eden::DevVulkan::trace_pipelines && samples_border) {\n'
         '        static std::vector<std::array<float, 4>> reported;\n'
         '        const auto report = [](const std::array<float, 4>& c, const char* kind) {\n'
         '            if (c == std::array<float, 4>{0, 0, 0, 0} || c == std::array<float, 4>{0, 0, 0, 1} ||\n'
         '                c == std::array<float, 4>{1, 1, 1, 1} || reported.size() >= 32 ||\n'
         '                std::find(reported.begin(), reported.end(), c) != reported.end()) return;\n'
         '            reported.push_back(c);\n'
         '            char text[128];\n'
         '            std::snprintf(text, sizeof(text), "non-standard %s border %g %g %g %g", kind, c[0], c[1],\n'
         '                          c[2], c[3]);\n'
         '            ::Eden::Report("sampler", text);\n'
         '        };\n'
         '        report(border_color, "linear");\n'
         '        if (tsc.srgb_conversion) report(srgb_border_color, "srgb");\n'
         '    }\n'
         '    has_custom_border_colors = samples_border && device.IsCustomBorderColorUsable();'),
    ],
}
# Deferred commands own their final copy metadata; avoid copying heap-backed vectors.
deferred_copy_edits = {
    'vk_buffer_cache': [
        ('[src_buffer, dst_buffer, vk_copies](',
         '[src_buffer, dst_buffer, vk_copies = std::move(vk_copies)](', 1),
        ('[src_buffer, dst_buffer, vk_copies, barrier](',
         '[src_buffer, dst_buffer, vk_copies = std::move(vk_copies), barrier](', 1),
    ],
    'vk_texture_cache': [
        ('vk_copies](vk::CommandBuffer cmdbuf) {',
         'vk_copies = std::move(vk_copies)](vk::CommandBuffer cmdbuf) {', 5),
        ('            vk_copies;\n        for (size_t index = 0; index < buffers_span.size(); index++) {',
         '            vk_copies;\n        buffers_vector.reserve(buffers_span.size());\n        vk_copies.reserve(buffers_span.size());\n        for (size_t index = 0; index < buffers_span.size(); index++) {', 1),
        ('                vk_copies;\n            for (size_t index = 0; index < buffers_span.size(); index++) {',
         '                vk_copies;\n            buffers_vector.reserve(buffers_span.size());\n            vk_copies.reserve(buffers_span.size());\n            for (size_t index = 0; index < buffers_span.size(); index++) {', 1),
    ],
}
for name, index, expected in (
    ('vk_fence_manager', 6, 1), ('vk_buffer_cache', 7, 3),
    ('vk_texture_cache', 8, 1), ('vk_swapchain', 9, 6),
    ('vk_descriptor_buffer', 10, 4), ('vk_multi_range_buffer', 11, 1),
    ('vk_compute_pass', 12, 1),
):
    relative = f'src/video_core/renderer_vulkan/{name}.cpp'
    destination = 'vulkan_swapchain.cpp' if name == 'vk_swapchain' else name + '_cost.cpp'
    # The descriptor source is adapted earlier for R323, just like the swapchain
    # is adapted for error-recovery. The cost wrapper MUST preserve that source.
    # Native CMake links vk_descriptor_buffer_cost.cpp, not the intermediate
    # vulkan_descriptor_buffer.cpp; re-reading the pinned upstream here would
    # silently discard PreflightFrameReuse and break the PS5 link.
    path = output / destination
    if name == 'vk_descriptor_buffer':
        text = (output / 'vulkan_descriptor_buffer.cpp').read_text()
    elif name == 'vk_swapchain':
        text = path.read_text()
    else:
        text = (source / relative).read_text()
    pattern = r'(?m)^( +)(scheduler\.(?:Wait|Finish)\([^\n]*\);)$'
    matches = list(re.finditer(pattern, text))
    if len(matches) != expected:
        raise RuntimeError(f'Wait-site anchors changed: {name}: {len(matches)} != {expected}')
    text = re.sub(pattern, lambda m: m[1] + '{ auto timer = Eden::Performance::VulkanTimer('
                  + str(index) + '); ' + m[2] + ' }', text)
    if name == 'vk_descriptor_buffer':
        # R360: measure the exact full-ring stall that occurs inside cache locks.
        ring_finish = '{ auto timer = Eden::Performance::VulkanTimer(10); scheduler.Finish(); }'
        # R363 preflight also gets VulkanTimer(10); only the LATER
        # full-ring Allocate fallback runs while guest caches are locked.
        if text.count(ring_finish) != 2:
            raise RuntimeError('R360 descriptor fallback/preflight anchors changed')
        fallback_at = text.rindex(ring_finish)
        if fallback_at <= text.index('Descriptor buffer frame exhausted, stalling on the GPU'):
            raise RuntimeError('R360 selected the wrong Finish site')
        text = text[:fallback_at] + '''{ auto timer = Eden::Performance::VulkanTimer(10);
              // Exact rare full-ring fallback, not the usual 1-in-16 draw sample.
              // This wait still holds both guest GPU cache locks; do not skip
              // the fence or move it without proving descriptor reuse safety.
              ::Eden::Performance::CachePhaseTimer finish_cost{
                  ::Eden::Performance::CachePhase::DescriptorRingFinish,
                  ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)};
              scheduler.Finish(); }''' + text[fallback_at + len(ring_finish):]
        # Remaining first Finish site is the R363 outside-lock preflight.
        if text.count(ring_finish) != 1:
            raise RuntimeError('R363 descriptor preflight timer anchor changed')
        text = text.replace(ring_finish, '''{ auto timer = Eden::Performance::VulkanTimer(10);
      ::Eden::Performance::CachePhaseTimer preflight_cost{
          ::Eden::Performance::CachePhase::DescriptorRingPreflight,
          ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)};
      scheduler.Finish(); }''', 1)
        # F07: the fallback Allocate can execute without a GPU-owner
        # PreflightFrameReuse. Mirror the preflight's zero/completed tick
        # safety predicate, but do not alter the desktop wait policy.
        # The adapter runs after VulkanTimer wrapping, so both the selected
        # source and the strict pinned-generator replay use the same body.
        legacy_fallback = '''    if (frame_reused) {
        frame_reused = false;
        { auto timer = Eden::Performance::VulkanTimer(10); scheduler.Wait(frame_ticks[frame_index]); }
    }'''
        native_fallback = '''    if (frame_reused) {
        frame_reused = false;
#ifdef PS5_NATIVE
        // This fallback can run without a preceding GPU-owner preflight.
        // A zero tick has no prior frame, and an already-retired tick has no
        // outstanding descriptor readers. Mirror PreflightFrameReuse's exact
        // GPU completion test before issuing a potentially blocking Wait
        // while the guest buffer/texture cache pair is held.
        const u64 old_tick = frame_ticks[frame_index];
        if (old_tick != 0 && !scheduler.IsFree(old_tick)) {
            { auto timer = Eden::Performance::VulkanTimer(10); scheduler.Wait(old_tick); }
        }
#else
        { auto timer = Eden::Performance::VulkanTimer(10); scheduler.Wait(frame_ticks[frame_index]); }
#endif
    }'''
        if text.count(legacy_fallback) != 1:
            raise RuntimeError('F07 descriptor ring retired-frame fallback anchor drift')
        text = text.replace(legacy_fallback, native_fallback, 1)
    if name == 'vk_compute_pass':
        # ASTC decode has no CPU consumer. Its existing image barrier orders
        # later shaders, and staging/descriptor reuse is protected by ticks.
        text = text.replace('VulkanTimer(12); scheduler.Finish();',
                            'VulkanTimer(12); scheduler.Flush();')
    for probe_old, probe_new in probes.get(name, []):
        if text.count(probe_old) != 1:
            raise RuntimeError(f'Probe anchor changed: {name}: {probe_old[:60]}')
        text = text.replace(probe_old, probe_new)
    for copy_old, copy_new, copy_count in deferred_copy_edits.get(name, []):
        if text.count(copy_old) != copy_count:
            raise RuntimeError(f'Deferred copy anchor changed: {name}: {copy_old[:60]}')
        text = text.replace(copy_old, copy_new)
    text = '#include "performance.h"\n' + text
    if not path.exists() or path.read_text() != text:
        path.write_text(text)

# Compute zero-descriptor queue fast path: apply after every pinned Vulkan
# backport/cost transform, and require exact active source parity.
for relative, previous, corrected in (
    ("include/video_core/renderer_vulkan/vk_compute_pipeline.h", "#ifdef PS5_NATIVE\n    [[nodiscard]] bool CanUseDescriptorBuffer() const noexcept {", "#ifdef PS5_NATIVE\n    [[nodiscard]] bool HasDescriptorEntries() const noexcept {\n        return num_descriptor_entries != 0;\n    }\n    [[nodiscard]] bool CanUseDescriptorBuffer() const noexcept {"),
    ("vk_compute_pipeline_cost.cpp", "    guest_descriptor_queue.Acquire(scheduler, num_descriptor_entries, uses_descriptor_buffer);\n\n    buffer_cache.SetComputeUniformBufferState", "    // A descriptor-free compute shader must not reserve the legacy 1024\n    // guest entries or wait for a GPU worker while holding both cache locks.\n    if (num_descriptor_entries == 0) {\n        guest_descriptor_queue.AcquireKnownEmpty(uses_descriptor_buffer);\n    } else {\n        guest_descriptor_queue.Acquire(scheduler, num_descriptor_entries, uses_descriptor_buffer);\n    }\n\n    buffer_cache.SetComputeUniformBufferState"),
    ("vulkan_rasterizer.cpp", "    gpu_memory->FlushCaching();\n#ifdef PS5_NATIVE\n    // Compute Configure runs under both guest cache locks. Drain the common\n    // descriptor queue overflow BEFORE taking those locks, exactly as Draw.\n    // The GPU worker may publish guest invalidations while it drains.\n    if (guest_descriptor_queue.PreflightGuestDraw([this] { scheduler.WaitWorker(); })) {\n        gpu_memory->FlushCaching();\n    }\n#endif\n\n    ComputePipeline* pipeline{pipeline_cache.CurrentComputePipeline()};\n    if (!pipeline) {\n        return;\n    }\n#ifdef PS5_NATIVE\n    // Compute always allocates new descriptor-buffer space for a dispatch.", "    gpu_memory->FlushCaching();\n    ComputePipeline* pipeline{pipeline_cache.CurrentComputePipeline()};\n    if (!pipeline) {\n        return;\n    }\n#ifdef PS5_NATIVE\n    // Select first: descriptor-free compute dispatches must not drain the\n    // legacy 1024-entry guest queue. After a real wait, consume guest page\n    // invalidations and reselect the possibly changed compute shader.\n    bool initial_compute_descriptor_drain = false;\n    if (pipeline->HasDescriptorEntries() &&\n        guest_descriptor_queue.PreflightGuestDraw([this] { scheduler.WaitWorker(); },\n                                                pipeline->DescriptorEntryReservation())) {\n        initial_compute_descriptor_drain = true;\n        gpu_memory->FlushCaching();\n        pipeline = pipeline_cache.CurrentComputePipeline();\n        if (!pipeline) return;\n    }\n#endif\n#ifdef PS5_NATIVE\n    // Compute always allocates new descriptor-buffer space for a dispatch."),
    ("vk_compute_pipeline_cost.cpp", "    texture_cache.SynchronizeDescriptors(true);", "    // No TIC/TSC state is consumed by a shader that has no sampled,\n    // storage or texel-buffer images. Defer table synchronization until a\n    // later compute pipeline actually uses descriptor tables.\n    if (!info.texture_buffer_descriptors.empty() ||\n        !info.image_buffer_descriptors.empty() ||\n        !info.texture_descriptors.empty() ||\n        !info.image_descriptors.empty()) {\n        texture_cache.SynchronizeDescriptors(true);\n    }"),
):
    selected = output / relative
    text = selected.read_text()
    if text.count(previous) != 1:
        raise RuntimeError(f"Compute empty-descriptor native anchor changed: {relative}")
    selected.write_text(text.replace(previous, corrected))


# F01/F03 native parity: strictly reconstruct the reviewed pipeline-lifetime
# and feedback-view deltas from the immutable source generator's own output.
# Require each exact preimage once. Never copy the tracked active file into
# the generated tree or relax byte-for-byte validation.
def apply_reviewed_delta(relative, old, new, label, *, allow_preapplied=False):
    path = output / relative
    data = path.read_text()
    before = data.count(old)
    after = data.count(new)
    if before == 1 and after == 0:
        path.write_text(data.replace(old, new, 1))
        return
    # The shipping Eden backport now includes the exact empty-view fast path.
    # The generator also runs against pristine older bases: both are allowed,
    # but *only* this reviewed already-patched block may be skipped. All
    # other deltas still require their unmodified source anchors.
    if allow_preapplied and before == 0 and after == 1:
        return
    raise RuntimeError(f"Reviewed native Vulkan anchor drift: {label} "
                       f"(before={before}, after={after})")

# Keep zero-clear Vulkan render passes from capturing nine unneeded VkClearValues.
# This change is PS5 selected-only: a smaller Record closure for ordinary draws,
# with the original nine-slot bounded payload for actual clears.
apply_reviewed_delta("vulkan_scheduler.cpp", "    std::array<VkClearValue, 9> values{};\n    // The Vulkan pointer below owns exactly these nine entries. Never publish\n    // the caller's unchecked clearValueCount after clipping the copy.\n    const u32 bounded_clear_value_count =\n        clear_values ? (std::min)(clear_value_count, static_cast<u32>(values.size())) : 0;\n    for (u32 i = 0; i < bounded_clear_value_count; ++i) {\n        values[i] = clear_values[i];\n    }\n    Record([renderpass, framebuffer_handle, render_area, values, bounded_clear_value_count](\n               vk::CommandBuffer cmdbuf) {\n        const VkRenderPassBeginInfo renderpass_bi{\n            .sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,\n            .pNext = nullptr,\n            .renderPass = renderpass,\n            .framebuffer = framebuffer_handle,\n            .renderArea =\n                {\n                    .offset = {.x = 0, .y = 0},\n                    .extent = render_area,\n                },\n            .clearValueCount = bounded_clear_value_count,\n            .pClearValues = bounded_clear_value_count != 0 ? values.data() : nullptr,\n        };\n        cmdbuf.BeginRenderPass(renderpass_bi, VK_SUBPASS_CONTENTS_INLINE);\n    });",
                     "    // Most ordinary draws start a render pass without any clear values.\n    // Do not zero/copy nine VkClearValue entries into every zero-clear\n    // deferred command. The exact same Vulkan begin-info path remains shared.\n    const auto record_pass = [this, renderpass, framebuffer_handle, render_area](\n                                 auto values, u32 bounded_clear_value_count) {\n        Record([renderpass, framebuffer_handle, render_area, values, bounded_clear_value_count](\n                   vk::CommandBuffer cmdbuf) {\n            const VkRenderPassBeginInfo renderpass_bi{\n                .sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,\n                .pNext = nullptr,\n                .renderPass = renderpass,\n                .framebuffer = framebuffer_handle,\n                .renderArea =\n                    {\n                        .offset = {.x = 0, .y = 0},\n                        .extent = render_area,\n                    },\n                .clearValueCount = bounded_clear_value_count,\n                .pClearValues = bounded_clear_value_count != 0 ? values.data() : nullptr,\n            };\n            cmdbuf.BeginRenderPass(renderpass_bi, VK_SUBPASS_CONTENTS_INLINE);\n        });\n    };\n    if (!clear_values || clear_value_count == 0) {\n        // Empty std::array specializes the queued closure down to the\n        // render-pass handles/extents; no nine-slot clear payload or copy.\n        record_pass(std::array<VkClearValue, 0>{}, 0);\n    } else {\n        std::array<VkClearValue, 9> values{};\n        const u32 bounded_clear_value_count =\n            (std::min)(clear_value_count, static_cast<u32>(values.size()));\n        for (u32 i = 0; i < bounded_clear_value_count; ++i) {\n            values[i] = clear_values[i];\n        }\n        record_pass(values, bounded_clear_value_count);\n    }",
                     "F07 zero-clear render pass command payload")

pipeline = 'vk_graphics_pipeline_cost.cpp'
mark = '''    if (shader_notify) {
        shader_notify->MarkShaderBuilding();
    }
'''
guard = '''    // Layout creation and descriptor setup below can throw before a worker
    // owns the build. Return the shader notification if setup/queueing fails.
    bool build_handed_off = false;
    SCOPE_EXIT {
        if (!build_handed_off && shader_notify) {
            shader_notify->MarkShaderComplete();
        }
    };
'''
apply_reviewed_delta(pipeline, mark + '    for (size_t stage',
                     mark + guard + '    for (size_t stage',
                     'F01 shader notification RAII before metadata allocation')
apply_reviewed_delta(pipeline,
    '''    }};
    if (worker_thread) {''',
    '''    }};
    // Complete all potentially throwing pipeline configuration before
    // publishing the builder lambda that captures this pipeline by pointer.
    // The worker must never see a partially constructed ConfigureFunc.
    configure_func = ConfigureFunc(spv_modules, stage_infos);
    if (worker_thread) {''',
    'F01 configure before worker handoff')
apply_reviewed_delta(pipeline,
    '''            worker_thread->QueueWork(std::move(func));
        }
    } else {
        func();
    }
    configure_func = ConfigureFunc(spv_modules, stage_infos);''',
    '''            worker_thread->QueueWork(std::move(func));
        }
        // QueueWork returned successfully; the worker now owns completion,
        // including paths where pipeline validation or compilation fails.
        build_handed_off = true;
    } else {
        // Synchronous func() owns the completion callback from this point.
        build_handed_off = true;
        func();
    }''',
    'F01 release shader notification exactly once after QueueWork')

# F01 source-selected substage attribution. Nested under BindStageDescriptors,
# 1-in-16 Detailed Logging ONLY; no reordered host bindings/descriptors.
apply_reviewed_delta(pipeline, "        buffer_cache.BindHostStageBuffers(stage);\n        const auto& info{stage_infos[stage]};", "        // Detailed-only 1/16 sampling: separate host buffer synchronization\n        // from image descriptor push work inside the existing paired locks.\n        {\n            ::Eden::Performance::CachePhaseTimer phase{\n                ::Eden::Performance::CachePhase::StageHostBuffers};\n            buffer_cache.BindHostStageBuffers(stage);\n        }\n        const auto& info{stage_infos[stage]};",
    'F01 split host-stage buffer binding cost from descriptor image push')
apply_reviewed_delta(pipeline, "        if (stage_has_image_bindings[stage]) {\n            PushImageDescriptors(texture_cache, guest_descriptor_queue, info, rescaling,\n                                 samplers_it, views_it);\n        }", "        if (stage_has_image_bindings[stage]) {\n            ::Eden::Performance::CachePhaseTimer phase{\n                ::Eden::Performance::CachePhase::StageImageDescriptors};\n            PushImageDescriptors(texture_cache, guest_descriptor_queue, info, rescaling,\n                                 samplers_it, views_it);\n        }",
    'F01 isolate image descriptor push cost within stage binding')

# F07 P0.3: precompute immutable shader-stage host buffer usage.
# No image binding or invalidation behavior changes.
apply_reviewed_delta(
    'include/video_core/renderer_vulkan/vk_graphics_pipeline.h',
    "    std::array<bool, NUM_STAGES> stage_has_image_bindings{};",
    "    // Immutable shader layout: no UBO/SSBO/TBO means no host buffer work.\n    std::array<bool, NUM_STAGES> stage_has_host_buffer_bindings{};\n    std::array<bool, NUM_STAGES> stage_has_image_bindings{};",
    'F07 P0.3 host stage mask in pipeline header')
apply_reviewed_delta(
    pipeline,
    "        stage_has_image_bindings[stage] =\n            !info->texture_buffer_descriptors.empty() ||",
    "        // BindHostStageBuffers walks only uniform, storage, texture buffers.\n        stage_has_host_buffer_bindings[stage] = info->constant_buffer_mask != 0 ||\n            !info->storage_buffers_descriptors.empty() ||\n            !info->texture_buffer_descriptors.empty() ||\n            !info->image_buffer_descriptors.empty();\n        stage_has_image_bindings[stage] =\n            !info->texture_buffer_descriptors.empty() ||",
    'F07 P0.3 stage UBO SSBO TBO presence metadata')
apply_reviewed_delta(
    pipeline,
    "        {\n            ::Eden::Performance::CachePhaseTimer phase{\n                ::Eden::Performance::CachePhase::StageHostBuffers};\n            buffer_cache.BindHostStageBuffers(stage);\n        }\n        const auto& info{stage_infos[stage]};",
    "        // Skip three guaranteed-empty bitset walks under paired GPU locks.\n        // Image descriptors are handled independently and remain untouched.\n        if (stage_has_host_buffer_bindings[stage]) {\n            ::Eden::Performance::CachePhaseTimer phase{\n                ::Eden::Performance::CachePhase::StageHostBuffers};\n            buffer_cache.BindHostStageBuffers(stage);\n        }\n        const auto& info{stage_infos[stage]};",
    'F07 P0.3 omit empty host buffer stage walks')

texture = 'vulkan-cache/video_core/texture_cache/texture_cache.h'
apply_reviewed_delta(texture,
    '''#ifdef PS5_NATIVE
    // A feedback barrier is only possible for a sampled depth attachment.''',
    '''#ifdef PS5_NATIVE
    // No sampled view can participate in a framebuffer feedback loop.
    // Avoid even the view-key comparison and snapshot for untextured draws.
    if (views.empty()) {
        last_feedback_loop_serial = render_targets_serial;
        last_feedback_texture_serial = texture_bindings_serial;
        last_feedback_loop_result = false;
        last_feedback_view_ids.clear();
        return;
    }

    // A feedback barrier is only possible for a sampled depth attachment.''',
    'F03/F04 empty-sampler feedback loop fast path', allow_preapplied=True)


# F07 P0.4: a remapped view rebuilt as NULL still changes texture
# binding identity. Do not let a cached feedback/descriptor decision outlive
# that transition. The normal resident-view path stays unchanged.
apply_reviewed_delta(
    'vulkan-cache/video_core/texture_cache/texture_cache.h',
    "        // CheckFeedbackLoop caches barrier decisions by this serial. Reviving\n        // an image without rewriting its TIC must invalidate that decision.\n        if (pair->second != NULL_IMAGE_VIEW_ID)\n            ++texture_bindings_serial;",
    "        // A remapped cached view can rebuild to NULL even when the TIC bytes\n        // remain valid. Publish both valid->NULL and NULL->valid generation\n        // transitions so feedback/descriptor consumers never retain stale\n        // binding decisions after a failed or successful reconstruction.\n        if (pair->second != NULL_IMAGE_VIEW_ID || remapped_cached_view)\n            ++texture_bindings_serial;",
    'F07 P0.4 remap-to-NULL view binding generation')

# F07 P0.4: compositor must not reuse retired/CPU-dirty Vulkan
# framebuffer pixels. Reject stale candidates before selecting a view:
# the existing absent-view route uploads guest bytes instead. Unmodified
# GPU-owned framebuffer views retain accelerated display without readback.
apply_reviewed_delta(
    'vulkan-cache/video_core/texture_cache/texture_cache.h',
    "        if (image.cpu_addr != cpu_addr) {\n            continue;\n        }\n        if (image.image_view_ids.empty()) {",
    "        if (image.cpu_addr != cpu_addr) {\n            continue;\n        }\n#ifdef PS5_NATIVE\n        // A remapped image or one dirtied by guest CPU writes cannot be\n        // sampled as an unchanged accelerated display framebuffer. Fall back\n        // to the guest-memory upload until its Vulkan image is refreshed.\n        // Clean GPU-authored images keep the zero-copy presentation path.\n        if (True(image.flags & (ImageFlagBits::Remapped | ImageFlagBits::CpuModified))) {\n            continue;\n        }\n#endif\n        if (image.image_view_ids.empty()) {",
    'F07 P0.4 accelerated present rejects remapped or CPU-dirty framebuffer')

# F07 P0.4: CPU dirty is cleared when asynchronous decode is enqueued.
# Until that decode uploads its new bytes, accelerated display must not
# reuse the previous GPU image; prefer the regular raw framebuffer route.
apply_reviewed_delta(
    'vulkan-cache/video_core/texture_cache/texture_cache.h',
    "        // Clean GPU-authored images keep the zero-copy presentation path.\n        if (True(image.flags & (ImageFlagBits::Remapped | ImageFlagBits::CpuModified))) {",
    "        // An in-flight asynchronous decode has not published its new pixels.\n        // Clean GPU-authored images keep the zero-copy presentation path.\n        if (True(image.flags & (ImageFlagBits::Remapped | ImageFlagBits::CpuModified |\n                                ImageFlagBits::IsDecoding))) {",
    'F07 P0.4 exclude asynchronously decoding accelerated framebuffer')

# F07 P0.4: multiple image views can share a framebuffer guest address.
# Skipping only the decoding candidate can select a different, older "clean"
# candidate. Disallow accelerated present for the address while any matching
# image is in flight; normal raw guest upload remains the fallback.
apply_reviewed_delta(
    'vulkan-cache/video_core/texture_cache/texture_cache.h',
    "        // An in-flight asynchronous decode has not published its new pixels.\n        // Clean GPU-authored images keep the zero-copy presentation path.\n        if (True(image.flags & (ImageFlagBits::Remapped | ImageFlagBits::CpuModified |\n                                ImageFlagBits::IsDecoding))) {\n            continue;\n        }",
    "        // Another image for this same guest address can still be clean but\n        // older. While ANY matching image decodes new pixels, no accelerated\n        // candidate can prove freshness. Upload guest bytes for this frame.\n        if (True(image.flags & ImageFlagBits::IsDecoding)) {\n            return {};\n        }\n        // Clean GPU-authored images keep the zero-copy presentation path.\n        if (True(image.flags & (ImageFlagBits::Remapped | ImageFlagBits::CpuModified))) {\n            continue;\n        }",
    'F07 P0.4 prevent stale alternate framebuffer view during async decode')

# F07 P0.4: on PS5 select the newest usable framebuffer view during the
# already-required candidate scan. This removes vector growth and a second
# traversal under texture_cache.mutex, preserving first-wins ties and the
# decoding/dirty-address fallback. Desktop retains the original algorithm.
apply_reviewed_delta(
    'vulkan-cache/video_core/texture_cache/texture_cache.h',
    "    const auto& image_map_ids = it->second;\n    boost::container::small_vector<ImageId, 4> valid_image_ids;\n    for (const ImageMapId map_id : image_map_ids) {",
    "    const auto& image_map_ids = it->second;\n#ifdef PS5_NATIVE\n    // Keep the best admissible view during the scan: no small_vector growth or\n    // second pass while the compositor owns texture_cache.mutex.\n    ImageId freshest_id{};\n    bool freshest_found = false;\n#else\n    boost::container::small_vector<ImageId, 4> valid_image_ids;\n#endif\n    for (const ImageMapId map_id : image_map_ids) {",
    'F07 P0.4 framebuffer single-pass candidate declaration')

apply_reviewed_delta(
    'vulkan-cache/video_core/texture_cache/texture_cache.h',
    "        valid_image_ids.push_back(map.image_id);\n    }\n\n    const auto view_format =",
    "#ifdef PS5_NATIVE\n        // Match ranges::max_element: the first candidate wins equal ticks.\n        if (!freshest_found ||\n            slot_images[freshest_id].modification_tick < image.modification_tick) {\n            freshest_id = map.image_id;\n            freshest_found = true;\n        }\n#else\n        valid_image_ids.push_back(map.image_id);\n#endif\n    }\n\n    const auto view_format =",
    'F07 P0.4 framebuffer single-pass admission')

apply_reviewed_delta(
    'vulkan-cache/video_core/texture_cache/texture_cache.h',
    "    if (valid_image_ids.size() == 1) [[likely]] {\n        return GetImageViewForFramebuffer(valid_image_ids.front());\n    }\n\n    if (valid_image_ids.size() > 0) [[unlikely]] {\n        auto most_recent = std::ranges::max_element(valid_image_ids, [&](auto a, auto b) {\n            return slot_images[a].modification_tick < slot_images[b].modification_tick;\n        });\n        return GetImageViewForFramebuffer(*most_recent);\n    }\n\n    return {};\n}",
    "#ifdef PS5_NATIVE\n    if (freshest_found) [[likely]] {\n        return GetImageViewForFramebuffer(freshest_id);\n    }\n#else\n    if (valid_image_ids.size() == 1) [[likely]] {\n        return GetImageViewForFramebuffer(valid_image_ids.front());\n    }\n\n    if (valid_image_ids.size() > 0) [[unlikely]] {\n        auto most_recent = std::ranges::max_element(valid_image_ids, [&](auto a, auto b) {\n            return slot_images[a].modification_tick < slot_images[b].modification_tick;\n        });\n        return GetImageViewForFramebuffer(*most_recent);\n    }\n#endif\n    return {};\n}",
    'F07 P0.4 framebuffer single-pass first-tie selection')

# F07 P0.4: a remapped/CPU-dirty alias invalidates acceleration for the
# WHOLE guest framebuffer address, not just that image. Otherwise an older
# clean sibling can be selected under the same texture-cache lock.
# A GPU-owned clean address retains the single-pass zero-copy path.
apply_reviewed_delta(
    'vulkan-cache/video_core/texture_cache/texture_cache.h',
    "        // Clean GPU-authored images keep the zero-copy presentation path.\n        if (True(image.flags & (ImageFlagBits::Remapped | ImageFlagBits::CpuModified))) {\n            continue;\n        }",
    "        // A dirty or remapped sibling at the SAME guest address also\n        // invalidates older clean accelerated candidates. CPU guest bytes\n        // must win until all conflicting cache images have been refreshed.\n        if (True(image.flags & (ImageFlagBits::Remapped | ImageFlagBits::CpuModified))) {\n            return {};\n        }",
    'F07 P0.4 prevent stale sibling framebuffer on CPU write or remap')

# F07 P0.4: composite can be the first GPU consumer after a guest
# memory remap. Flush queued mapping invalidations ahead of the texture
# mutex, matching DrawTexture's lock ordering. This keeps the newly selected
# clean display-image fast path coherent with pending remap flags.
apply_reviewed_delta(
    'vulkan_rasterizer.cpp',
    "    if (!framebuffer_addr) {\n        return {};\n    }\n    std::scoped_lock lock{texture_cache.mutex};\n    const auto [image_view, scaled] =\n        texture_cache.TryFindFramebufferImageView(config, framebuffer_addr);",
    "    if (!framebuffer_addr) {\n        return {};\n    }\n#ifdef PS5_NATIVE\n    // Present may run after a guest page remap without another draw.\n    // Commit queued guest-memory invalidations before reading cached image\n    // flags, never while holding texture_cache.mutex (invalidation takes it).\n    gpu_memory->FlushCaching();\n#endif\n    std::scoped_lock lock{texture_cache.mutex};\n    const auto [image_view, scaled] =\n        texture_cache.TryFindFramebufferImageView(config, framebuffer_addr);",
    'F07 P0.4 present flushes remaps before inspecting image cache')

# F07 T01: select the newest DMA image during the original region walk
# instead of retaining all matches and scanning again under texture mutex.
# The exact pinned FindDMAImage preimage remains a strict review oracle.
apply_reviewed_delta(
    "vulkan-cache/video_core/texture_cache/texture_cache.h",
    "ImageId TextureCache<P>::FindDMAImage(const ImageInfo& info, GPUVAddr gpu_addr) {\n    std::optional<DAddr> cpu_addr = gpu_memory->GpuToCpuAddress(gpu_addr);\n    if (!cpu_addr) {\n        cpu_addr = gpu_memory->GpuToCpuAddress(gpu_addr, CalculateGuestSizeInBytes(info));\n        if (!cpu_addr) {\n            return ImageId{};\n        }\n    }\n    ImageId image_id{};\n    boost::container::small_vector<ImageId, 8> image_ids;\n    const auto lambda = [&](ImageId existing_image_id, ImageBase& existing_image) {\n        if (True(existing_image.flags & ImageFlagBits::Remapped)) {\n            return false;\n        }\n        if (info.type == ImageType::Linear || existing_image.info.type == ImageType::Linear)\n            [[unlikely]] {\n            const bool strict_size = True(existing_image.flags & ImageFlagBits::Strong);\n            const ImageInfo& existing = existing_image.info;\n            if (existing_image.gpu_addr == gpu_addr && existing.type == info.type &&\n                existing.pitch == info.pitch &&\n                IsPitchLinearSameSize(existing, info, strict_size) &&\n                IsViewCompatible(existing.format, info.format, false, true)) {\n                image_id = existing_image_id;\n                image_ids.push_back(existing_image_id);\n                return true;\n            }\n        } else if (IsSubCopy(info, existing_image, gpu_addr)) {\n            image_id = existing_image_id;\n            image_ids.push_back(existing_image_id);\n            return true;\n        }\n        return false;\n    };\n    ForEachImageInRegion(*cpu_addr, CalculateGuestSizeInBytes(info), lambda);\n    if (image_ids.size() <= 1) [[likely]] {\n        return image_id;\n    }\n    auto image_ids_compare = [this](ImageId a, ImageId b) {\n        auto& image_a = slot_images[a];\n        auto& image_b = slot_images[b];\n        return image_a.modification_tick < image_b.modification_tick;\n    };\n    return *std::ranges::max_element(image_ids, image_ids_compare);\n}\n",
    "ImageId TextureCache<P>::FindDMAImage(const ImageInfo& info, GPUVAddr gpu_addr) {\n    std::optional<DAddr> cpu_addr = gpu_memory->GpuToCpuAddress(gpu_addr);\n    if (!cpu_addr) {\n        cpu_addr = gpu_memory->GpuToCpuAddress(gpu_addr, CalculateGuestSizeInBytes(info));\n        if (!cpu_addr) {\n            return ImageId{};\n        }\n    }\n    ImageId image_id{};\n#ifdef PS5_NATIVE\n    // The DMA match scan already visits every candidate under the cache lock.\n    // Keep the freshest image as it arrives; avoid an inline vector and a\n    // second max_element pass on a HUD/texture DMA lookup. Equal ticks retain\n    // the FIRST candidate, exactly as max_element does.\n    const auto consider_candidate = [&](ImageId id, const ImageBase& image) {\n        if (!image_id ||\n            slot_images[image_id].modification_tick < image.modification_tick) {\n            image_id = id;\n        }\n    };\n#else\n    boost::container::small_vector<ImageId, 8> image_ids;\n#endif\n    const auto lambda = [&](ImageId existing_image_id, ImageBase& existing_image) {\n        if (True(existing_image.flags & ImageFlagBits::Remapped)) {\n            return false;\n        }\n        if (info.type == ImageType::Linear || existing_image.info.type == ImageType::Linear)\n            [[unlikely]] {\n            const bool strict_size = True(existing_image.flags & ImageFlagBits::Strong);\n            const ImageInfo& existing = existing_image.info;\n            if (existing_image.gpu_addr == gpu_addr && existing.type == info.type &&\n                existing.pitch == info.pitch &&\n                IsPitchLinearSameSize(existing, info, strict_size) &&\n                IsViewCompatible(existing.format, info.format, false, true)) {\n#ifdef PS5_NATIVE\n                consider_candidate(existing_image_id, existing_image);\n#else\n                image_id = existing_image_id;\n                image_ids.push_back(existing_image_id);\n#endif\n                return true;\n            }\n        } else if (IsSubCopy(info, existing_image, gpu_addr)) {\n#ifdef PS5_NATIVE\n            consider_candidate(existing_image_id, existing_image);\n#else\n            image_id = existing_image_id;\n            image_ids.push_back(existing_image_id);\n#endif\n            return true;\n        }\n        return false;\n    };\n    ForEachImageInRegion(*cpu_addr, CalculateGuestSizeInBytes(info), lambda);\n#ifdef PS5_NATIVE\n    return image_id;\n#else\n    if (image_ids.size() <= 1) [[likely]] {\n        return image_id;\n    }\n    auto image_ids_compare = [this](ImageId a, ImageId b) {\n        auto& image_a = slot_images[a];\n        auto& image_b = slot_images[b];\n        return image_a.modification_tick < image_b.modification_tick;\n    };\n    return *std::ranges::max_element(image_ids, image_ids_compare);\n#endif\n}\n",
    "F07 T01 single-pass freshest DMA image candidate selection")

# F07 C04: preserve live Layer identities on append, but FSR/SGSR
# constructor output extents must match the current screen rectangle.
apply_reviewed_delta(
    "vulkan_blit_screen.cpp",
    "    if (layers.size() != framebuffers.size()) {\n#ifdef PS5_NATIVE\n        if (!layers.empty()) {\n            // Old layer resources can still be in queued Vulkan draws.\n            WaitIdle(device);\n        }\n#endif\n        layers.clear();\n        for (size_t i = 0; i < framebuffers.size(); ++i) {\n            layers.emplace_back(device, memory_allocator, scheduler, device_memory, image_count,\n                                window_size, window_adapt->GetDescriptorSetLayout(), filters);\n        }\n    }",
    "#ifdef PS5_NATIVE\n    // Presentation layers live in std::list: appending one does not move\n    // existing Layer objects captured by queued Vulkan command callbacks.\n    // New HUD layers can be added without destroying old GPU resources or\n    // draining the entire device. A changed descriptor/layout contract\n    // still forces the existing idle + full rebuild below.\n    // FSR/SGSR allocate output-sized resources inside each Layer. The screen\n    // rectangle can change while the swapchain extent and layer count stay\n    // constant; keeping those old resources would mix incompatible sizes.\n    const bool output_sensitive =\n        scaling_filter == Settings::ScalingFilter::Fsr ||\n        scaling_filter == Settings::ScalingFilter::Sgsr ||\n        scaling_filter == Settings::ScalingFilter::SgsrEdge;\n    const bool output_size_changed =\n        !layers.empty() && (layer_window_size.width != window_size.width ||\n                            layer_window_size.height != window_size.height);\n    const bool rebuild_layers =\n        resource_update_required || (output_sensitive && output_size_changed);\n    if (!rebuild_layers && layers.size() < framebuffers.size()) {\n        for (size_t i = layers.size(); i < framebuffers.size(); ++i) {\n            layers.emplace_back(device, memory_allocator, scheduler, device_memory, image_count,\n                                window_size, window_adapt->GetDescriptorSetLayout(), filters);\n        }\n    } else if (rebuild_layers || layers.size() != framebuffers.size()) {\n        // Removal destroys GPU-referenced descriptors/images. Reconfiguration\n        // has already waited in the resource_update_required block above.\n        if (!resource_update_required && !layers.empty()) {\n            WaitIdle(device);\n        }\n        layers.clear();\n        for (size_t i = 0; i < framebuffers.size(); ++i) {\n            layers.emplace_back(device, memory_allocator, scheduler, device_memory, image_count,\n                                window_size, window_adapt->GetDescriptorSetLayout(), filters);\n        }\n    }\n    layer_window_size = window_size;\n#else\n    if (layers.size() != framebuffers.size()) {\n        layers.clear();\n        for (size_t i = 0; i < framebuffers.size(); ++i) {\n            layers.emplace_back(device, memory_allocator, scheduler, device_memory, image_count,\n                                window_size, window_adapt->GetDescriptorSetLayout(), filters);\n        }\n    }\n#endif",
    "F07 C04 append-only presentation layers without device idle")

# C04: Vulkan image/view handles may be lost independently of a clean
# guest framebuffer candidate. The compositor must use raw guest upload
# instead of a null accelerated image. No extra lock or driver wait.
apply_reviewed_delta(
    'vulkan_rasterizer.cpp',
    "    query_cache.NotifySegment(false);\n\n    const auto& resolution = Settings::values.resolution_info;\n\n    FramebufferTextureInfo info{};\n    info.image = image_view->ImageHandle();\n    info.image_view = image_view->Handle(Shader::TextureType::Color2D);\n    info.width = image_view->size.width;",
    "    FramebufferTextureInfo info{};\n    info.image = image_view->ImageHandle();\n    info.image_view = image_view->Handle(Shader::TextureType::Color2D);\n#ifdef PS5_NATIVE\n    // A valid guest image-map entry does not guarantee that its Vulkan image\n    // and color view survived GPU allocation/recreation. Never send a null\n    // attachment into the compositor; use the existing raw guest upload.\n    if (info.image == VK_NULL_HANDLE || info.image_view == VK_NULL_HANDLE) {\n        return {};\n    }\n#endif\n    query_cache.NotifySegment(false);\n\n    const auto& resolution = Settings::values.resolution_info;\n\n    info.width = image_view->size.width;",
    'F07 C04 accelerated framebuffer rejects missing Vulkan handles')

# Reviewed F04 scissor source body: reconstruct the exact overflow-safe
# method from the pinned upstream method, WITHOUT consulting active code or
# weakening the generated-versus-maintained source checker at runtime.
scissor_original_file = source / 'src/video_core/renderer_vulkan/vk_rasterizer.cpp'
scissor_original_source = scissor_original_file.read_text()
scissor_begin = 'VkRect2D GetScissorState('
scissor_end = '\nDrawParams MakeDrawParams('
if scissor_original_source.count(scissor_begin) != 1:
    raise RuntimeError('F04 pinned scissor signature changed')
scissor_original_start = scissor_original_source.index(scissor_begin)
scissor_original_stop = scissor_original_source.index(scissor_end, scissor_original_start)
scissor_original_method = scissor_original_source[
    scissor_original_start:scissor_original_stop]
apply_reviewed_delta(
    'vulkan_rasterizer.cpp', scissor_original_method,
    "VkRect2D GetScissorState(const Maxwell& regs, size_t index, u32 up_scale = 1, u32 down_shift = 0) {\n    const auto& src = regs.scissor_test[index];\n    VkRect2D scissor{};\n    // Handle guest scissor extremes without wrapping signed coordinate\n    // differences. Preserve the existing 32-bit results on ordinary draws.\n    const auto bounded_s32 = [](s64 value) -> s32 {\n        return static_cast<s32>((std::clamp)(\n            value, static_cast<s64>(std::numeric_limits<s32>::min()),\n            static_cast<s64>(std::numeric_limits<s32>::max())));\n    };\n    const auto scale_up = [&](s32 value) -> s32 {\n        if (value == 0) {\n            return 0;\n        }\n        const s64 scaled = static_cast<s64>(value) * static_cast<s64>(up_scale);\n        if (scaled >= std::numeric_limits<s32>::min() &&\n            scaled <= std::numeric_limits<s32>::max() && down_shift < 32) {\n            // Preserve pinned behavior: up_scale is unsigned, so the old\n            // value * up_scale and right shift operated on unsigned bits,\n            // even for negative guest coordinates. Sign-shifting would change\n            // otherwise valid clipping rectangles.\n            const u32 bits = static_cast<u32>(value) * up_scale;\n            const s32 as_i32 = static_cast<s32>(bits);\n            const s64 adjustment = (up_scale >> down_shift) == 0 ? as_i32 % 2 : 0;\n            const s64 shifted = static_cast<s32>(bits >> down_shift);\n            return bounded_s32(value < 0 ? (std::min)(shifted - adjustment, s64{-1})\n                                         : (std::max)(shifted + adjustment, s64{1}));\n        }\n        // Wide fallback for overflow-prone guest data or an oversized shift.\n        const u32 shift = (std::min)(down_shift, 63U);\n        const s64 adjustment = (down_shift >= 32 || (up_scale >> down_shift) == 0)\n                                   ? scaled % 2 : 0;\n        const s64 shifted = scaled >> shift;\n        return bounded_s32(value < 0 ? (std::min)(shifted - adjustment, s64{-1})\n                                     : (std::max)(shifted + adjustment, s64{1}));\n    };\n\n    const bool lower_left = regs.window_origin.mode != Maxwell::WindowOrigin::Mode::UpperLeft;\n    const s32 clip_height = regs.surface_clip.height;\n\n    // Flip coordinates without signed overflow before clamping to the render area.\n    s32 min_y = lower_left\n                    ? bounded_s32(static_cast<s64>(clip_height) - src.max_y)\n                    : src.min_y.Value();\n    s32 max_y = lower_left\n                    ? bounded_s32(static_cast<s64>(clip_height) - src.min_y)\n                    : src.max_y.Value();\n\n    // Bound to render area\n    min_y = (std::max)(min_y, 0);\n    max_y = (std::max)(max_y, 0);\n\n    if (src.enable) {\n        scissor.offset.x = scale_up(src.min_x);\n        scissor.offset.y = scale_up(min_y);\n        scissor.extent.width =\n            scale_up(bounded_s32(static_cast<s64>(src.max_x) - src.min_x));\n        scissor.extent.height =\n            scale_up(bounded_s32(static_cast<s64>(max_y) - min_y));\n    } else {\n        scissor.offset.x = 0;\n        scissor.offset.y = 0;\n        scissor.extent.width = (std::numeric_limits<s32>::max)();\n        scissor.extent.height = (std::numeric_limits<s32>::max)();\n    }\n    return scissor;\n}\n",
    'F04 overflow-safe scissor coordinates with pinned ordinary behavior')


# F01: keep the PS5 compute preflight in the source GENERATOR, not just
# in the tracked native output. Only immutable shader descriptor counts
# are read before guest buffer/texture locks; actual guest handles remain
# resolved within ComputePipeline::Configure.
compute = 'vk_compute_pipeline_cost.cpp'
apply_reviewed_delta(
    compute, '#include "performance.h"\n#include <vector>',
    '#include "performance.h"\n#include <memory>\n#include <vector>',
    'F01 compute RAII scratch explicit memory include')
apply_reviewed_delta(
    compute,
    '''using Tegra::Texture::TexturePair;

ComputePipeline::ComputePipeline(''',
    '''using Tegra::Texture::TexturePair;

#ifdef PS5_NATIVE
namespace {
// Per-GPU-thread compute descriptor storage. The lease keeps a nested dispatch
// from corrupting an outer dispatch's views or sampler cursors.
struct ComputeDescriptorScratch {
    boost::container::small_vector<VideoCommon::ImageViewInOut, 64> views;
    boost::container::small_vector<VideoCommon::SamplerId, 64> samplers;
    bool in_use{};
};
thread_local ComputeDescriptorScratch compute_descriptor_scratch;
thread_local ComputeDescriptorScratch compute_descriptor_nested_scratch;

class ComputeDescriptorScratchLease {
public:
    ComputeDescriptorScratchLease() {
        if (!compute_descriptor_scratch.in_use) {
            current = &compute_descriptor_scratch;
            current->in_use = true;
        } else if (!compute_descriptor_nested_scratch.in_use) {
            current = &compute_descriptor_nested_scratch;
            current->in_use = true;
        } else {
            nested = std::make_unique<ComputeDescriptorScratch>();
            current = nested.get();
        }
        current->views.clear();
        current->samplers.clear();
    }
    ~ComputeDescriptorScratchLease() {
        if (!nested) current->in_use = false;
    }
    ComputeDescriptorScratchLease(const ComputeDescriptorScratchLease&) = delete;
    ComputeDescriptorScratchLease& operator=(const ComputeDescriptorScratchLease&) = delete;
    auto& Views() noexcept { return current->views; }
    auto& Samplers() noexcept { return current->samplers; }

private:
    std::unique_ptr<ComputeDescriptorScratch> nested;
    ComputeDescriptorScratch* current{};
};
} // namespace
#endif

ComputePipeline::ComputePipeline(''',
    'F01 PS5 per-thread reentrant compute descriptor storage')
apply_reviewed_delta(
    compute,
    '''    num_descriptor_entries = NumDescriptorEntries(info);

    DescriptorLayoutBuilder builder{device};''',
    '''    num_descriptor_entries = NumDescriptorEntries(info);
#ifdef PS5_NATIVE
    // Fixed by the compiled compute shader; safe to read before cache locks.
    num_image_elements = Shader::NumDescriptors(info.texture_buffer_descriptors) +
                         Shader::NumDescriptors(info.image_buffer_descriptors) +
                         Shader::NumDescriptors(info.texture_descriptors) +
                         Shader::NumDescriptors(info.image_descriptors);
    num_textures = Shader::NumDescriptors(info.texture_descriptors);
#endif

    DescriptorLayoutBuilder builder{device};''',
    'F01 compute precompute shader descriptor sizes outside cache locks')
apply_reviewed_delta(
    compute,
    '''bool ComputePipeline::Configure(Tegra::Engines::KeplerCompute& kepler_compute,''',
    '''#ifdef PS5_NATIVE
void ComputePipeline::PreflightDescriptorScratch() {
    // No guest texture/cache data is consulted here: counts are immutable.
    // Skip the slot currently owned by a nested Configure invocation.
    auto& scratch = compute_descriptor_scratch.in_use
                        ? compute_descriptor_nested_scratch
                        : compute_descriptor_scratch;
    if (scratch.in_use) return;
    if (scratch.views.capacity() < num_image_elements)
        scratch.views.reserve(num_image_elements);
    if (scratch.samplers.capacity() < num_textures)
        scratch.samplers.reserve(num_textures);
}
#endif

bool ComputePipeline::Configure(Tegra::Engines::KeplerCompute& kepler_compute,''',
    'F01 reserve compute scratch before the paired GPU cache locks')
apply_reviewed_delta(
    compute,
    '''    boost::container::small_vector<VideoCommon::ImageViewInOut, 64> views;
    boost::container::small_vector<VideoCommon::SamplerId, 64> samplers;

    const auto& qmd{kepler_compute.launch_description};''',
    '''#ifdef PS5_NATIVE
    // Preallocated by DispatchCompute before its paired cache mutexes.
    // A nested call leases another slot rather than overwriting these IDs.
    ComputeDescriptorScratchLease scratch;
    auto& views = scratch.Views();
    auto& samplers = scratch.Samplers();
    views.reserve(num_image_elements);
    samplers.reserve(num_textures);
#else
    boost::container::small_vector<VideoCommon::ImageViewInOut, 64> views;
    boost::container::small_vector<VideoCommon::SamplerId, 64> samplers;
#endif

    const auto& qmd{kepler_compute.launch_description};''',
    'F01 compute draws retain scratch capacity without stale view IDs')
apply_reviewed_delta(
    'include/video_core/renderer_vulkan/vk_compute_pipeline.h',
    '''#ifdef PS5_NATIVE
    [[nodiscard]] bool HasDescriptorEntries() const noexcept {''',
    '''#ifdef PS5_NATIVE
    // Called on the GPU owner before the paired buffer/texture cache locks.
    void PreflightDescriptorScratch();
    [[nodiscard]] bool HasDescriptorEntries() const noexcept {''',
    'F01 compute preflight method exposed only to PS5 builds')
apply_reviewed_delta(
    'include/video_core/renderer_vulkan/vk_compute_pipeline.h',
    '''    u32 num_descriptor_entries{};

    VideoCommon::ComputeUniformBufferSizes uniform_buffer_sizes{};''',
    '''    u32 num_descriptor_entries{};
#ifdef PS5_NATIVE
    size_t num_image_elements{};
    size_t num_textures{};
#endif

    VideoCommon::ComputeUniformBufferSizes uniform_buffer_sizes{};''',
    'F01 immutable compute descriptor counts')
apply_reviewed_delta(
    'vulkan_rasterizer.cpp',
    '''#endif
    SCOPE_EXIT { SyncProbe(scheduler, "dispatch", pipeline); };
    std::scoped_lock lock{texture_cache.mutex, buffer_cache.mutex};
    if (!pipeline->Configure(*kepler_compute, *gpu_memory, scheduler, buffer_cache,
                             texture_cache)) {''',
    '''#endif
#ifdef PS5_NATIVE
    // Descriptor storage is bounded by this shader's immutable layout.
    // Reserve on the GPU owner thread BEFORE cache-pair acquisition.
    pipeline->PreflightDescriptorScratch();
#endif
    SCOPE_EXIT { SyncProbe(scheduler, "dispatch", pipeline); };
    std::scoped_lock lock{texture_cache.mutex, buffer_cache.mutex};
    if (!pipeline->Configure(*kepler_compute, *gpu_memory, scheduler, buffer_cache,
                             texture_cache)) {''',
    'F01 compute scratch reservation precedes both guest cache mutexes')


# F01: an immutable compute TSC table can repeat sampler IDs within one
# dispatch. Lookup memo is bounded and lives ONLY inside Configure: never
# reuse it after a compute descriptor remap or a new channel.
apply_reviewed_delta(
    'vk_compute_pipeline_cost.cpp',
    '#include <algorithm>\n#include "common/scope_exit.h"',
    '#include <algorithm>\n#include <array>\n#include "common/scope_exit.h"',
    'F01 compute sampler memo explicit array include')
apply_reviewed_delta(
    'vk_compute_pipeline_cost.cpp',
    '''    const bool via_header_index{qmd.linked_tsc != 0};
    const auto read_handle{[&](const auto& desc, u32 index) {''',
    '''    const bool via_header_index{qmd.linked_tsc != 0};
#ifdef PS5_NATIVE
    // Descriptor synchronization above fixes the TSC table for this dispatch.
    // This dispatch-local memo preserves all 16 distinct sampler handles
    // even when their low bits collide. No heap allocation or cross-dispatch
    // reuse; an overflowing table resolves the handle normally.
    struct ComputeSamplerMemo {
        u32 handle;
        VideoCommon::SamplerId id;
    };
    // Only a 16-bit occupancy mask needs zeroing for each compute dispatch.
    // Cold entries are never read until their handle/id have both been set.
    std::array<ComputeSamplerMemo, 16> sampler_memo;
    u32 occupied_sampler_slots{};
    const auto resolve_sampler{[&](u32 handle) -> VideoCommon::SamplerId {
        const std::size_t first = (handle ^ (handle >> 4)) & 15U;
        for (std::size_t offset = 0; offset < sampler_memo.size(); ++offset) {
            const std::size_t slot = (first + offset) & 15U;
            const u32 bit = u32{1} << slot;
            auto& entry = sampler_memo[slot];
            if (occupied_sampler_slots & bit) {
                if (entry.handle == handle) return entry.id;
                continue;
            }
            entry.id = texture_cache.GetSamplerId(handle, true);
            entry.handle = handle;
            occupied_sampler_slots |= bit;
            return entry.id;
        }
        return texture_cache.GetSamplerId(handle, true);
    }};
#endif
    const auto read_handle{[&](const auto& desc, u32 index) {''',
    'F01 16-slot compute sampler memo limited to each Configure call')
apply_reviewed_delta(
    'vk_compute_pipeline_cost.cpp',
    '''            VideoCommon::SamplerId sampler = texture_cache.GetSamplerId(handle.second, true);
            samplers.push_back(sampler);''',
    '''#ifdef PS5_NATIVE
            samplers.push_back(resolve_sampler(handle.second));
#else
            VideoCommon::SamplerId sampler = texture_cache.GetSamplerId(handle.second, true);
            samplers.push_back(sampler);
#endif''',
    'F01 PS5 compute sampler reuse with unchanged upstream path')


# F04 TIC image view validation: the pinned generator may run against either
# pristine sources or the ordered, already-shipping texture backport.
# In both cases its final selected C++ must be byte-identical to Encore.
apply_reviewed_delta(
    'vulkan-cache/video_core/texture_cache/texture_cache.h',
    '''ImageViewId TextureCache<P>::CreateImageView(const TICEntry& config) {
    const ImageInfo info(config);
    if (info.type == ImageType::Buffer) {
        const ImageViewInfo view_info(config, 0);
        return slot_image_views.insert(runtime, info, view_info, config.Address());
    }
    const u32 layer_offset = config.BaseLayer() * info.layer_stride;
    const GPUVAddr image_gpu_addr = config.Address() - layer_offset;
    const ImageId image_id = FindOrInsertImage(info, image_gpu_addr);
    if (!image_id) {
        return NULL_IMAGE_VIEW_ID;
    }
    ImageBase& image = slot_images[image_id];
    const SubresourceBase base = image.TryFindBase(config.Address()).value();
    ASSERT(base.level == 0);
    const ImageViewInfo view_info(config, base.layer);
    const ImageViewId image_view_id = FindOrEmplaceImageView(image_id, view_info);
    ImageViewBase& image_view = slot_image_views[image_view_id];
    image_view.flags |= ImageViewFlagBits::Strong;
    image.flags |= ImageFlagBits::Strong;
    return image_view_id;
}
''',
    '''ImageViewId TextureCache<P>::CreateImageView(const TICEntry& config) {
    const ImageInfo info(config);
    if (info.type == ImageType::Buffer) {
        const ImageViewInfo view_info(config, 0);
        return slot_image_views.insert(runtime, info, view_info, config.Address());
    }
#ifdef PS5_NATIVE
    // TIC base-layer offsets are byte addresses, not 32-bit arithmetic.
    // Reject invalid addresses before a wrapped image mapping is created.
    const u64 layer_offset = static_cast<u64>(config.BaseLayer()) * info.layer_stride;
    if (layer_offset > config.Address()) {
        return NULL_IMAGE_VIEW_ID;
    }
#else
    const u32 layer_offset = config.BaseLayer() * info.layer_stride;
#endif
    const GPUVAddr image_gpu_addr = config.Address() - layer_offset;
    const ImageId image_id = FindOrInsertImage(info, image_gpu_addr);
    if (!image_id) {
        return NULL_IMAGE_VIEW_ID;
    }
    ImageBase& image = slot_images[image_id];
#ifdef PS5_NATIVE
    // A remapped or incomplete texture may not contain the requested layer.
    // Defer this view instead of dereferencing an empty optional on the GPU
    // worker; the existing NULL-view retry path can rebuild it later.
    const auto base = image.TryFindBase(config.Address());
    if (!base) {
        return NULL_IMAGE_VIEW_ID;
    }
    ASSERT(base->level == 0);
    const ImageViewInfo view_info(config, base->layer);
#else
    const SubresourceBase base = image.TryFindBase(config.Address()).value();
    ASSERT(base.level == 0);
    const ImageViewInfo view_info(config, base.layer);
#endif
    const ImageViewId image_view_id = FindOrEmplaceImageView(image_id, view_info);
    ImageViewBase& image_view = slot_image_views[image_view_id];
    image_view.flags |= ImageViewFlagBits::Strong;
    image.flags |= ImageFlagBits::Strong;
    return image_view_id;
}
''',
    'F04 native TIC layer view safety', allow_preapplied=True)


# F03/F04: remapped framebuffer attachments must be marked dirty on PS5.
# Patched shipping Eden may already contain this exact guarded method; in
# pristine legacy generator fixtures, reconstruct the reviewed delta here.
apply_reviewed_delta(
    'vulkan-cache/video_core/texture_cache/texture_cache.h',
    '''void TextureCache<P>::UnmapGPUMemory(size_t as_id, GPUVAddr gpu_addr, size_t size) {
    boost::container::small_vector<ImageId, 16> deleted_images;
    ForEachImageInRegionGPU(as_id, gpu_addr, size,
                            [&](ImageId id, Image&) { deleted_images.push_back(id); });
    for (const ImageId id : deleted_images) {
        Image& image = slot_images[id];
        if (False(image.flags & ImageFlagBits::CpuModified)) {
            image.flags |= ImageFlagBits::CpuModified;
            if (True(image.flags & ImageFlagBits::Tracked)) {
                UntrackImage(image, id);
            }
        }
        if (True(image.flags & ImageFlagBits::Remapped)) {
            continue;
        }
        image.flags |= ImageFlagBits::Remapped;
    }
}
''',
    '''void TextureCache<P>::UnmapGPUMemory(size_t as_id, GPUVAddr gpu_addr, size_t size) {
    boost::container::small_vector<ImageId, 16> deleted_images;
    ForEachImageInRegionGPU(as_id, gpu_addr, size,
                            [&](ImageId id, Image&) { deleted_images.push_back(id); });
    for (const ImageId id : deleted_images) {
        Image& image = slot_images[id];
        if (False(image.flags & ImageFlagBits::CpuModified)) {
            image.flags |= ImageFlagBits::CpuModified;
            if (True(image.flags & ImageFlagBits::Tracked)) {
                UntrackImage(image, id);
            }
        }
        if (True(image.flags & ImageFlagBits::Remapped)) {
            continue;
        }
        image.flags |= ImageFlagBits::Remapped;
#ifdef PS5_NATIVE
        // A sampled view is checked on its next TIC lookup, but render
        // targets can bypass that lookup. Force only attached remapped views
        // through the normal framebuffer rebinding path on the next draw.
        bool framebuffer_affected = false;
        auto& dirty = maxwell3d->dirty.flags;
        for (const ImageViewId view_id : image.image_view_ids) {
            if (view_id == NULL_IMAGE_VIEW_ID) {
                continue;
            }
            if (view_id == render_targets.depth_buffer_id) {
                dirty[Dirty::ZetaBuffer] = true;
                framebuffer_affected = true;
            }
            for (size_t rt = 0; rt < NUM_RT; ++rt) {
                if (view_id == render_targets.color_buffer_ids[rt]) {
                    dirty[Dirty::ColorBuffer0 + rt] = true;
                    framebuffer_affected = true;
                }
            }
        }
        if (framebuffer_affected) {
            dirty[Dirty::RenderTargets] = true;
        }
#endif
    }
}
''',
    'F03 F04 remap framebuffer invalidation', allow_preapplied=True)


# F07: promote a completed optimized Vulkan pipeline without changing its
# owner pointer, shader translation or descriptor cache. Reproduce on every
# pinned source adaptation and fail closed on upstream source drift.
apply_reviewed_delta("include/video_core/renderer_vulkan/vk_scheduler.h",
    "    bool UpdateGraphicsPipeline(GraphicsPipeline* pipeline);",
    "    bool UpdateGraphicsPipeline(GraphicsPipeline* pipeline, bool optimized = false);",
    "F07 scheduler optimized variant declaration")
apply_reviewed_delta("include/video_core/renderer_vulkan/vk_scheduler.h",
    "        GraphicsPipeline* graphics_pipeline = nullptr;\n        bool is_rescaling = false;",
    "        GraphicsPipeline* graphics_pipeline = nullptr;\n        // GPU owner only: the optimized variant can become ready without\n        // changing the logical pipeline pointer.\n        bool graphics_pipeline_optimized = false;\n        bool is_rescaling = false;",
    "F07 scheduler optimized variant state")
apply_reviewed_delta("vulkan_scheduler.cpp",
    "bool Scheduler::UpdateGraphicsPipeline(GraphicsPipeline* pipeline) {\n    if (state.graphics_pipeline == pipeline) {\n        if (pipeline && pipeline->UsesExtendedDynamicState() &&\n            state.needs_state_enable_refresh) {\n            state_tracker.InvalidateStateEnableFlag();\n            state.needs_state_enable_refresh = false;\n        }\n        return false;\n    }\n\n    state.graphics_pipeline = pipeline;\n\n    if (!pipeline) {\n        return true;\n    }\n\n    if (!pipeline->UsesExtendedDynamicState()) {\n        state.needs_state_enable_refresh = true;\n    } else if (state.needs_state_enable_refresh) {\n        state_tracker.InvalidateStateEnableFlag();\n        state.needs_state_enable_refresh = false;\n    }\n\n    return true;\n}",
    "bool Scheduler::UpdateGraphicsPipeline(GraphicsPipeline* pipeline, bool optimized) {\n    if (state.graphics_pipeline == pipeline) {\n        if (pipeline && pipeline->UsesExtendedDynamicState() &&\n            state.needs_state_enable_refresh) {\n            state_tracker.InvalidateStateEnableFlag();\n            state.needs_state_enable_refresh = false;\n        }\n        // A completed optimized variant shares its cache key and owner pointer.\n        // Rebind once after publication even if the same shader keeps drawing.\n        const bool variant_changed = state.graphics_pipeline_optimized != optimized;\n        state.graphics_pipeline_optimized = optimized;\n        return variant_changed;\n    }\n\n    state.graphics_pipeline = pipeline;\n    state.graphics_pipeline_optimized = optimized;\n\n    if (!pipeline) {\n        return true;\n    }\n\n    if (!pipeline->UsesExtendedDynamicState()) {\n        state.needs_state_enable_refresh = true;\n    } else if (state.needs_state_enable_refresh) {\n        state_tracker.InvalidateStateEnableFlag();\n        state.needs_state_enable_refresh = false;\n    }\n\n    return true;\n}",
    "F07 scheduler variant change rebind")
apply_reviewed_delta("vulkan_scheduler.cpp",
    "void Scheduler::InvalidateState() {\n    state.graphics_pipeline = nullptr;\n    state.rescaling_defined = false;",
    "void Scheduler::InvalidateState() {\n    state.graphics_pipeline = nullptr;\n    state.graphics_pipeline_optimized = false;\n    state.rescaling_defined = false;",
    "F07 scheduler variant invalidation")
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "    const bool bind_pipeline{scheduler.UpdateGraphicsPipeline(this)};",
    "    // Publish a ready optimized variant at the next draw even if this\n    // logical pipeline stays selected across multiple command buffers.\n    const bool bind_pipeline{scheduler.UpdateGraphicsPipeline(\n        this, optimized_ready.load(std::memory_order_acquire))};",
    "F07 graphics optimize publication handoff")

# F07: the initial non-optimized first-use VkPipeline can be null while its
# separately rebuilt optimized handle has succeeded. Do not discard those
# draws: acquire the optimized publication before the worker failure branch.
# This replacement is deliberately after all pinned graphics source patches.
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "        if (bind_pipeline) {\n            if (!pipeline) {\n                // An asynchronously-built pipeline can fail after Configure's\n                // earlier IsBuilt()/pipeline check but before this worker\n                // callback executes. Count the actual GPU draw omission.\n                ::Eden::Performance::RecordGraphicsDrawDrop(\n                    ::Eden::Performance::GraphicsDrawDrop::WorkerPipelineFailed);\n                return;\n            }\n            cmdbuf.BindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS,\n    optimized_ready.load(std::memory_order_acquire) ? *optimized_pipeline : *pipeline);\n        }",
    "        if (bind_pipeline) {\n            // An initial fast-first Vulkan creation can return a null handle\n            // without throwing. Its subsequent optimized rebuild may still\n            // succeed. Acquire the published optimized handle before deciding\n            // whether this ordered draw must be discarded.\n            const bool use_optimized = optimized_ready.load(std::memory_order_acquire);\n            if (!pipeline && !use_optimized) {\n                ::Eden::Performance::RecordGraphicsDrawDrop(\n                    ::Eden::Performance::GraphicsDrawDrop::WorkerPipelineFailed);\n                return;\n            }\n            cmdbuf.BindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS,\n                                use_optimized ? *optimized_pipeline : *pipeline);\n        }",
    "F07 recovered optimized draw handle after initial fast-first failure")


# F07: recovered optimized pipelines must survive the GPU owner's built
# validity check, and command-buffer callbacks must not draw through an
# invalid/stale handle when a previous bind is cached. Rebind when the
# optimized release publication races with the scheduler record step.
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "    if (IsBuilt() && !pipeline) {",
    "    // The first-use VkPipeline may fail while a separately rebuilt optimized\n    // variant succeeds. Keep that recovered handle eligible for guest draws.\n    if (IsBuilt() && !pipeline && !optimized_ready.load(std::memory_order_acquire)) {",
    "F07 recover optimized built pipeline")
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "    const bool bind_pipeline{scheduler.UpdateGraphicsPipeline(\n        this, optimized_ready.load(std::memory_order_acquire))};",
    "    const bool optimized_at_record = optimized_ready.load(std::memory_order_acquire);\n    const bool bind_pipeline{scheduler.UpdateGraphicsPipeline(this, optimized_at_record)};",
    "F07 snapshot optimized variant")
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "    scheduler.Record([this, descriptor_data, bind_pipeline, update_descriptors,",
    "    scheduler.Record([this, descriptor_data, bind_pipeline, optimized_at_record, update_descriptors,",
    "F07 capture pipeline variant snapshot")
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "        if (bind_pipeline) {\n            // An initial fast-first Vulkan creation can return a null handle\n            // without throwing. Its subsequent optimized rebuild may still\n            // succeed. Acquire the published optimized handle before deciding\n            // whether this ordered draw must be discarded.\n            const bool use_optimized = optimized_ready.load(std::memory_order_acquire);\n            if (!pipeline && !use_optimized) {\n                ::Eden::Performance::RecordGraphicsDrawDrop(\n                    ::Eden::Performance::GraphicsDrawDrop::WorkerPipelineFailed);\n                return;\n            }\n            cmdbuf.BindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS,\n                                use_optimized ? *optimized_pipeline : *pipeline);\n        }",
    "        // The worker must verify validity on EVERY draw: a failed pipeline\n        // remains selected by the guest scheduler after the first attempted\n        // bind. Otherwise subsequent draws can accidentally reuse a previous\n        // shader while the optimized rebuild is still missing.\n        const bool use_optimized = optimized_ready.load(std::memory_order_acquire);\n        if (!pipeline && !use_optimized) {\n            ::Eden::Performance::RecordGraphicsDrawDrop(\n                ::Eden::Performance::GraphicsDrawDrop::WorkerPipelineFailed);\n            return;\n        }\n        // Optimization may publish between GPU-owner recording and ordered\n        // Vulkan-worker execution. Rebind the newly published handle in this\n        // callback even when the owner recorded no pipeline-key transition.\n        if (bind_pipeline || (use_optimized != optimized_at_record)) {\n            cmdbuf.BindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS,\n                                use_optimized ? *optimized_pipeline : *pipeline);\n        }",
    "F07 validate every worker draw and late publish")


# F07: bounded cold-shader retry. Preserve pinned Vulkan header verbatim;
# apply the native-only retry bookkeeping to its staged build copy. The
# normal successful pipeline hot path performs no retry lookup or clock read.
# The normal pinned cache header was not previously copied to the active
# Vulkan include tree. F07 failed-key retries add private PS5 cache state,
# so reproduce the complete header before applying its reviewed native delta.
adapt('src/video_core/renderer_vulkan/vk_pipeline_cache.h',
      'include/video_core/renderer_vulkan/vk_pipeline_cache.h', [])

apply_reviewed_delta("include/video_core/renderer_vulkan/vk_pipeline_cache.h",
    "    ::Common::unordered_map<GraphicsPipelineCacheKey, std::unique_ptr<GraphicsPipeline>> graphics_cache;\n\n    ShaderPools main_pools;",
    "    ::Common::unordered_map<GraphicsPipelineCacheKey, std::unique_ptr<GraphicsPipeline>> graphics_cache;\n#ifdef PS5_NATIVE\n    // Graphics cache entries with failed shader translation remain null.\n    // Allow one delayed recovery per failed key, never a retry per guest draw.\n    // Bounded to 64 keys so invalid shaders cannot consume unlimited metadata.\n    struct GraphicsRetryState {\n        std::chrono::steady_clock::time_point eligible_at{};\n        bool attempted{};\n    };\n    ::Common::unordered_map<GraphicsPipelineCacheKey, GraphicsRetryState> failed_graphics_retries;\n#endif\n\n    ShaderPools main_pools;",
    "F07 bounded failed graphics retry state")
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "        pipeline = CreateGraphicsPipeline();\n    }\n    if (!pipeline) {\n        return nullptr;\n    }",
    "        pipeline = CreateGraphicsPipeline();\n#ifdef PS5_NATIVE\n        if (!pipeline && failed_graphics_retries.size() < 64) {\n            // Cold misses are allowed to fail, but do not cache a transient\n            // translation error forever. Only failed keys allocate metadata.\n            failed_graphics_retries.try_emplace(\n                graphics_key, GraphicsRetryState{\n                    std::chrono::steady_clock::now() + std::chrono::seconds(2), false});\n        }\n#endif\n    }\n#ifdef PS5_NATIVE\n    else if (!pipeline) {\n        const auto failed = failed_graphics_retries.find(graphics_key);\n        if (failed != failed_graphics_retries.end() && !failed->second.attempted &&\n            std::chrono::steady_clock::now() >= failed->second.eligible_at) {\n            // Publish the attempted bit BEFORE the potentially expensive\n            // guest IR/SPIR-V translation. Repeated failed HUD draws stay O(1).\n            failed->second.attempted = true;\n            ::Eden::Performance::CachePhaseTimer retry_cpu_cost{\n                ::Eden::Performance::CachePhase::GraphicsPipelineCreate,\n                ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)};\n            pipeline = CreateGraphicsPipeline();\n            // The null graphics_cache entry itself guarantees at most one\n            // retry for this key. Retaining consumed retry metadata would\n            // exhaust the 64-key budget after unrelated transient failures.\n            failed_graphics_retries.erase(failed);\n        }\n    }\n#endif\n    if (!pipeline) {\n        return nullptr;\n    }",
    "F07 one delayed retry for failed graphics shader")


# F07: failed compute shader translations can strand a null cache entry.
# Modify only the generated PS5 header and maintained source, not the input pin.
apply_reviewed_delta("include/video_core/renderer_vulkan/vk_pipeline_cache.h",
    "    ::Common::unordered_map<GraphicsPipelineCacheKey, GraphicsRetryState> failed_graphics_retries;\n#endif\n\n    ShaderPools main_pools;",
    "    ::Common::unordered_map<GraphicsPipelineCacheKey, GraphicsRetryState> failed_graphics_retries;\n    // Independently bounded recovery for failed compute translations.\n    struct ComputeRetryState {\n        std::chrono::steady_clock::time_point eligible_at{};\n        bool attempted{};\n    };\n    ::Common::unordered_map<ComputePipelineCacheKey, ComputeRetryState> failed_compute_retries;\n#endif\n\n    ShaderPools main_pools;",
    "F07 bounded failed compute shader retry state")
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "    const auto [pair, is_new]{compute_cache.try_emplace(key)};\n    auto& pipeline{pair->second};\n    if (is_new) {\n        pipeline = CreateComputePipeline(key, shader);\n    }\n    if (::Eden::DevVulkan::trace_pipelines && pipeline) {",
    "    const auto [pair, is_new]{compute_cache.try_emplace(key)};\n    auto& pipeline{pair->second};\n    if (is_new) {\n        pipeline = CreateComputePipeline(key, shader);\n#ifdef PS5_NATIVE\n        if (!pipeline && failed_compute_retries.size() < 32) {\n            // A transient guest shader translation failure must not permanently\n            // suppress a compute dispatch. Track failures only.\n            failed_compute_retries.try_emplace(\n                key, ComputeRetryState{\n                    std::chrono::steady_clock::now() + std::chrono::seconds(2), false});\n        }\n#endif\n    }\n#ifdef PS5_NATIVE\n    else if (!pipeline) {\n        const auto failed = failed_compute_retries.find(key);\n        if (failed != failed_compute_retries.end() && !failed->second.attempted &&\n            std::chrono::steady_clock::now() >= failed->second.eligible_at) {\n            // Mark before translation: persistent failure must never spin\n            // within repeated compute dispatches.\n            failed->second.attempted = true;\n            pipeline = CreateComputePipeline(key, shader);\n            // A consumed retry cannot repeat: the null compute_cache entry\n            // is no longer marked retryable. Recycle its 32-key budget slot.\n            failed_compute_retries.erase(failed);\n        }\n    }\n#endif\n    if (::Eden::DevVulkan::trace_pipelines && pipeline) {",
    "F07 one delayed compute shader retry")

# F07: an early compute pipeline descriptor/layout or queue admission error
# can leave ShaderNotify in its building state. Mirror graphics ownership.
apply_reviewed_delta("vk_compute_pipeline_cost.cpp",
    "    if (shader_notify) {\n        shader_notify->MarkShaderBuilding();\n    }\n    std::copy_n(info.constant_buffer_used_sizes.begin()",
    "    if (shader_notify) {\n        shader_notify->MarkShaderBuilding();\n    }\n#ifdef PS5_NATIVE\n    // Layout setup and worker queue admission may throw. Return the shader\n    // notification unless ownership has passed to the worker or inline build.\n    bool build_handed_off = false;\n    SCOPE_EXIT {\n        if (!build_handed_off && shader_notify) {\n            shader_notify->MarkShaderComplete();\n        }\n    };\n#endif\n    std::copy_n(info.constant_buffer_used_sizes.begin()",
    "F07 compute shader build notification unwind")
apply_reviewed_delta("vk_compute_pipeline_cost.cpp",
    "    if (thread_worker) {\n        thread_worker->QueueWork(std::move(func));\n    } else {\n        func();\n    }\n",
    "    if (thread_worker) {\n        thread_worker->QueueWork(std::move(func));\n#ifdef PS5_NATIVE\n        build_handed_off = true;\n#endif\n    } else {\n#ifdef PS5_NATIVE\n        // Inline func() has its own completion guard.\n        build_handed_off = true;\n#endif\n        func();\n    }\n",
    "F07 compute worker completion ownership transfer")


# F07 P0.1/P0.2: protect first-use compute CFG, IR, SPIR-V and
# shader module work BEFORE the Vulkan builder task gets queued.
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "namespace Vulkan {\n\nnamespace {\nusing Shader::Backend::SPIRV::EmitSPIRV;",
    "namespace Vulkan {\n#ifdef PS5_NATIVE\n// The compute pipeline builder exposes this Vulkan-namespace atomic counter.\nextern std::atomic<unsigned> pending_first_use_compute_builds;\n#endif\n\nnamespace {\n#ifdef PS5_NATIVE\n// Keep the OPTIONAL graphics optimizer away from foreground compute\n// CFG/IR/SPIR-V translation, before the Vulkan driver worker is enqueued.\n// Only runtime first-use translation participates; preloaded cache jobs do not.\nstruct ComputeTranslationPriorityScope {\n    explicit ComputeTranslationPriorityScope(bool foreground_) : foreground{foreground_} {\n        if (foreground) {\n            pending_first_use_compute_builds.fetch_add(1, std::memory_order_release);\n        }\n    }\n    ~ComputeTranslationPriorityScope() {\n        if (foreground) {\n            pending_first_use_compute_builds.fetch_sub(1, std::memory_order_release);\n        }\n    }\n    bool foreground;\n};\n#endif\nusing Shader::Backend::SPIRV::EmitSPIRV;",
    "F07 foreground compute shader translation scope")
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "    PipelineStatistics* statistics, bool build_in_parallel) try {\n    auto hash = key.Hash();\n    if (device.HasBrokenCompute()) {",
    "    PipelineStatistics* statistics, bool build_in_parallel) try {\n#ifdef PS5_NATIVE\n    // Count cold shader translation as foreground work. The pipeline\n    // constructor separately counts the queued driver build; both stages\n    // now prevent speculative graphics optimization from competing.\n    ComputeTranslationPriorityScope translation_priority{build_in_parallel};\n#endif\n    auto hash = key.Hash();\n    if (device.HasBrokenCompute()) {",
    "F07 compute CFG IR SPIRV fairness before driver queue")

# F07 P0.1/P0.2: cold GRAPHICS CFG/IR/SPIR-V translation also
# precedes worker queue admission. Reserve the same foreground counter used
# by the first-use pipeline builder so optional optimization yields throughout.
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "extern std::atomic<unsigned> pending_first_use_compute_builds;\n#endif\n\nnamespace {", "extern std::atomic<unsigned> pending_first_use_compute_builds;\nextern std::atomic<unsigned> pending_first_use_graphics_builds;\n#endif\n\nnamespace {",
    "F07 graphics translation observes first-use worker counter")
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "    bool foreground;\n};\n#endif\nusing Shader::Backend::SPIRV::EmitSPIRV;", "    bool foreground;\n};\n// This foreground reservation is published BEFORE the renderer translates\n// cold graphics CFG/IR/SPIR-V and constructs shader modules. The normal\n// graphics builder owns a second reservation from QueueWork to completion.\nstruct GraphicsTranslationPriorityScope {\n    explicit GraphicsTranslationPriorityScope(bool foreground_) : foreground{foreground_} {\n        if (foreground) {\n            pending_first_use_graphics_builds.fetch_add(1, std::memory_order_release);\n        }\n    }\n    ~GraphicsTranslationPriorityScope() {\n        if (foreground) {\n            pending_first_use_graphics_builds.fetch_sub(1, std::memory_order_release);\n        }\n    }\n    GraphicsTranslationPriorityScope(const GraphicsTranslationPriorityScope&) = delete;\n    GraphicsTranslationPriorityScope& operator=(const GraphicsTranslationPriorityScope&) = delete;\n    bool foreground;\n};\n#endif\nusing Shader::Backend::SPIRV::EmitSPIRV;",
    "F07 graphics shader translation priority scope")
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "    bool build_in_parallel) try {\n    auto hash = key.Hash();\n    LOG_DEBUG(Render_Vulkan, \"{:#016x}\", hash);", "    bool build_in_parallel) try {\n#ifdef PS5_NATIVE\n    // The optional optimizer must yield to foreground graphics translation\n    // even before the first-use Vulkan pipeline reaches the worker queue.\n    // Disk prewarm passes build_in_parallel=false and remains uncounted.\n    GraphicsTranslationPriorityScope translation_priority{\n        build_in_parallel && ::Eden::DevVulkan::fast_first_pipelines};\n#endif\n    auto hash = key.Hash();\n    LOG_DEBUG(Render_Vulkan, \"{:#016x}\", hash);",
    "F07 reserve graphics translation before CFG IR SPIRV")

# F07 P0.4: stale multi-frame unswizzle uploads must be cancelled
# BEFORE the native frame throttle, but keep the pinned desktop ordering.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    if(current_unswizzle_frame > 0) {\n        current_unswizzle_frame--;\n        return;\n    }\n\n    PendingUnswizzle& task = unswizzle_queue.front();\n    Image& image = slot_images[task.image_id];\n\n    if (!task.initialized) {",
    "#ifndef PS5_NATIVE\n    if(current_unswizzle_frame > 0) {\n        current_unswizzle_frame--;\n        return;\n    }\n#endif\n\n    PendingUnswizzle& task = unswizzle_queue.front();\n    Image& image = slot_images[task.image_id];\n#ifdef PS5_NATIVE\n    // This task may span several frames. A new CPU write or guest remap\n    // invalidates its staged bytes even when texture dimensions do not change.\n    // Abandon the old content before dispatching another GPU upload batch.\n    if (True(image.flags & (ImageFlagBits::CpuModified | ImageFlagBits::Remapped))) {\n        if (task.initialized) {\n            // Previously submitted batches may still be on the GPU worker.\n            // Return their source buffer using the EXISTING deferred free.\n            runtime.FreeDeferredStagingBuffer(task.staging_buffer);\n        }\n        image.flags |= ImageFlagBits::CpuModified;\n        if (True(image.flags & ImageFlagBits::Tracked)) {\n            UntrackImage(image, task.image_id);\n        }\n        image.flags &= ~ImageFlagBits::IsDecoding;\n        unswizzle_queue.pop_front();\n        current_unswizzle_frame = 0u;\n        // No throttling after cancellation: the replacement can be queued\n        // as soon as RefreshContents observes the retained CPU modification.\n        return;\n    }\n#endif\n\n#ifdef PS5_NATIVE\n    if(current_unswizzle_frame > 0) {\n        current_unswizzle_frame--;\n        return;\n    }\n#endif\n\n    if (!task.initialized) {",
    "F07 cancel stale GPU unswizzle with deferred staging and native cooldown")

# F07 P0.4: guard multi-frame GPU unswizzle slice arithmetic before a
# staging copy. Zero, overflowing or incomplete slices must never reach
# divisions, slice batching, or a GPU upload.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        const u32 stride = width_blocks * bytes_per_block;\n        const u32 aligned_height = height_blocks;\n        task.bytes_per_slice = static_cast<size_t>(stride) * aligned_height;\n        task.last_submitted_offset = 0;",
    "#ifdef PS5_NATIVE\n        // Widen BEFORE multiplying: an overflowing u32 stride can become 0\n        // and trigger a division by zero in the multi-frame upload below.\n        const size_t stride = static_cast<size_t>(width_blocks) * bytes_per_block;\n#else\n        const u32 stride = width_blocks * bytes_per_block;\n#endif\n        const u32 aligned_height = height_blocks;\n#ifdef PS5_NATIVE\n        const bool slice_overflow =\n            aligned_height != 0 && stride > std::numeric_limits<size_t>::max() / aligned_height;\n        task.bytes_per_slice = slice_overflow ? 0 : stride * aligned_height;\n        // The current staging allocation must hold complete 3D slices.\n        // Reject zero, overflow and misaligned guest sizes before ANY read or\n        // accelerated upload; an incomplete final slice can overrun staging.\n        const bool invalid_slices =\n            task.bytes_per_slice == 0 || task.bytes_per_slice > task.total_size ||\n            task.total_size % task.bytes_per_slice != 0 ||\n            // This accelerated path admits one layer/level of 3D BCn;\n            // extra slices are as invalid as missing ones. Otherwise\n            // depth - z_start can underflow in the last upload batch.\n            task.total_size / task.bytes_per_slice != static_cast<size_t>(info.size.depth);\n        if (invalid_slices) {\n            runtime.FreeDeferredStagingBuffer(task.staging_buffer);\n            image.flags |= ImageFlagBits::CpuModified;\n            if (True(image.flags & ImageFlagBits::Tracked)) {\n                UntrackImage(image, task.image_id);\n            }\n            image.flags &= ~ImageFlagBits::IsDecoding;\n            unswizzle_queue.pop_front();\n            current_unswizzle_frame = 0u;\n            return;\n        }\n#else\n        task.bytes_per_slice = static_cast<size_t>(stride) * aligned_height;\n#endif\n        task.last_submitted_offset = 0;",
    "F07 guard 3D GPU unswizzle slices and staging bounds")

# F07 P0.4: validate the 3D slice geometry BEFORE allocating GPU
# staging, so invalid guest sizes cannot reserve a huge deferred buffer.
# Keep the pinned desktop allocation position unchanged.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        task.total_size = MapSizeBytes(image);\n        task.staging_buffer = runtime.UploadStagingBuffer(task.total_size, true);\n\n        const auto& info = image.info;",
    "        task.total_size = MapSizeBytes(image);\n#ifndef PS5_NATIVE\n        task.staging_buffer = runtime.UploadStagingBuffer(task.total_size, true);\n#endif\n\n        const auto& info = image.info;",
    "F07 allocate GPU unswizzle staging after native bounds validation")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if (invalid_slices) {\n            runtime.FreeDeferredStagingBuffer(task.staging_buffer);\n            image.flags |= ImageFlagBits::CpuModified;",
    "        if (invalid_slices) {\n            // No GPU staging exists yet; reject invalid geometry without\n            // reserving a potentially huge upload buffer.\n            image.flags |= ImageFlagBits::CpuModified;",
    "F07 reject invalid unswizzle geometry without staged allocation")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "#endif\n        task.last_submitted_offset = 0;\n        task.initialized = true;",
    "#endif\n#ifdef PS5_NATIVE\n        task.staging_buffer = runtime.UploadStagingBuffer(task.total_size, true);\n#endif\n        task.last_submitted_offset = 0;\n        task.initialized = true;",
    "F07 commit native 3D staging only after validation")

# F07 P0.2: cold compute driver builds must take priority over
# optional optimized graphics rebuilds, including builds still in queue.
apply_reviewed_delta("vk_compute_pipeline_cost.cpp",
    "#include <algorithm>", "#include <algorithm>\n#include <atomic>",
    "F07 compute fairness atomic include")
apply_reviewed_delta("vk_compute_pipeline_cost.cpp",
    "namespace Vulkan {\n\nusing Shader::ImageBufferDescriptor;", "namespace Vulkan {\n\n#ifdef PS5_NATIVE\n// Tracks queued and active first-use compute builds, not guest dispatches.\nstd::atomic<unsigned> pending_first_use_compute_builds{0};\n#endif\n\nusing Shader::ImageBufferDescriptor;",
    "F07 shared compute first-use backlog")
apply_reviewed_delta("vk_compute_pipeline_cost.cpp",
    "    if (thread_worker) {\n        thread_worker->QueueWork(std::move(func));\n#ifdef PS5_NATIVE\n        build_handed_off = true;\n#endif\n    } else {", "    if (thread_worker) {\n#ifdef PS5_NATIVE\n        // Reserve a slot BEFORE QueueWork: a pending compute shader has\n        // priority over a speculative optimized graphics rebuild.\n        pending_first_use_compute_builds.fetch_add(1, std::memory_order_release);\n        try {\n            thread_worker->QueueWork([build = std::move(func)]() mutable {\n                SCOPE_EXIT {\n                    pending_first_use_compute_builds.fetch_sub(1, std::memory_order_release);\n                };\n                build();\n            });\n        } catch (...) {\n            pending_first_use_compute_builds.fetch_sub(1, std::memory_order_release);\n            throw;\n        }\n        build_handed_off = true;\n#else\n        thread_worker->QueueWork(std::move(func));\n#endif\n    } else {",
    "F07 counted compute worker handoff")
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "namespace Vulkan {\nnamespace {\nusing boost::container::small_vector;", "namespace Vulkan {\n#ifdef PS5_NATIVE\n// The optional graphics optimizer also yields to cold compute builds.\nextern std::atomic<unsigned> pending_first_use_compute_builds;\n#endif\nnamespace {\nusing boost::container::small_vector;",
    "F07 graphics optimizer observes compute backlog")
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "while (pending_first_use_graphics_builds.load(std::memory_order_acquire) != 0) {", "while (pending_first_use_graphics_builds.load(std::memory_order_acquire) != 0 ||\n               pending_first_use_compute_builds.load(std::memory_order_acquire) != 0) {",
    "F07 optimized graphics yields to compute builds")

# F07 P0.2: avoid a speculative vkCreateGraphicsPipelines in the gap
# between two waves of HUD shader translations / first-use builds. Only the
# background optimized worker waits; foreground GPU work is not delayed.
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "        while (pending_first_use_graphics_builds.load(std::memory_order_acquire) != 0 ||\n               pending_first_use_compute_builds.load(std::memory_order_acquire) != 0) {\n            {\n                std::scoped_lock lock{state->mutex};\n                if (state->cancelled) return;\n            }\n            std::this_thread::sleep_for(std::chrono::milliseconds(2));\n        }",
    "        // A momentarily empty builder queue is not an idle GPU frame.\n        // Require a brief QUIET period before any OPTIONAL driver rebuild:\n        // new HUD shaders appearing in a burst reset the countdown. This\n        // sleep is confined to the optimizer worker, never the GPU owner.\n        constexpr auto quiet_window = std::chrono::milliseconds(16);\n        auto quiet_since = std::chrono::steady_clock::now();\n        for (;;) {\n            const bool cold_build_pending =\n                pending_first_use_graphics_builds.load(std::memory_order_acquire) != 0 ||\n                pending_first_use_compute_builds.load(std::memory_order_acquire) != 0;\n            if (cold_build_pending) {\n                quiet_since = std::chrono::steady_clock::now();\n            } else if (std::chrono::steady_clock::now() - quiet_since >= quiet_window) {\n                break;\n            }\n            {\n                std::scoped_lock lock{state->mutex};\n                if (state->cancelled) return;\n            }\n            std::this_thread::sleep_for(std::chrono::milliseconds(2));\n        }",
    "F07 quiet-window priority between cold pipeline bursts")

# F07 P0.4: protect the image BEFORE Tracked registration can throw.
# Successful async/MSAA exits explicitly commit their accepted handoff.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    image.flags &= ~ImageFlagBits::CpuModified;\n\n    TrackImage(image, image_id);",
    "    image.flags &= ~ImageFlagBits::CpuModified;\n#ifdef PS5_NATIVE\n    // Synchronous upload failure must not leave the CPU image incorrectly clean.\n    bool upload_completed = false;\n    SCOPE_EXIT {\n        if (!upload_completed) {\n            if (True(image.flags & ImageFlagBits::Tracked)) {\n                UntrackImage(image, image_id);\n            }\n            image.flags |= ImageFlagBits::CpuModified;\n        }\n    };\n#endif\n\n    TrackImage(image, image_id);",
    "F07 restore failed texture upload dirty state before registration")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        runtime.TransitionImageLayout(image);\n        return;",
    "        runtime.TransitionImageLayout(image);\n#ifdef PS5_NATIVE\n        upload_completed = true;  // Intentional unsupported MSAA fallback.\n#endif\n        return;",
    "F07 complete MSAA image handoff")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        QueueAsyncDecode(image, image_id);\n        return;",
    "        QueueAsyncDecode(image, image_id);\n#ifdef PS5_NATIVE\n        upload_completed = true;  // Decode handoff accepted.\n#endif\n        return;",
    "F07 complete decode image handoff")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        QueueAsyncUnswizzle(image, image_id);\n        return;",
    "        QueueAsyncUnswizzle(image, image_id);\n#ifdef PS5_NATIVE\n        upload_completed = true;  // Unswizzle handoff accepted.\n#endif\n        return;",
    "F07 complete unswizzle image handoff")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    runtime.InsertUploadMemoryBarrier();\n#ifdef PS5_NATIVE\n    barrier_phase.Stop();\n#endif\n}",
    "    runtime.InsertUploadMemoryBarrier();\n#ifdef PS5_NATIVE\n    barrier_phase.Stop();\n    upload_completed = true;\n#endif\n}",
    "F07 completed texture upload marker")


# F07 P0.4: keep async-decoding state recoverable if preparation or
# queue admission fails. These are native-only state changes; no GPU waits.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    image.flags |= ImageFlagBits::IsDecoding;\n    auto decode = std::make_unique<AsyncDecodeContext>();",
    "#ifdef PS5_NATIVE\n    // Never strand IsDecoding or a pending decode entry if preparation or\n    // worker queue admission throws. Preserve an already active decode.\n    const bool was_decoding = True(image.flags & ImageFlagBits::IsDecoding);\n    AsyncDecodeContext* incomplete_decode{};\n    bool decode_admitted = false;\n    SCOPE_EXIT {\n        if (!decode_admitted) {\n            if (!was_decoding) {\n                image.flags &= ~ImageFlagBits::IsDecoding;\n            }\n            if (incomplete_decode && !async_decodes.empty() &&\n                async_decodes.back().get() == incomplete_decode) {\n                async_decodes.pop_back();\n            }\n        }\n    };\n#endif\n    image.flags |= ImageFlagBits::IsDecoding;\n    auto decode = std::make_unique<AsyncDecodeContext>();",
    "F07 decode rollback on admission")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    auto* decode_ptr = decode.get();\n    decode->image_id = image_id;",
    "    auto* decode_ptr = decode.get();\n#ifdef PS5_NATIVE\n    incomplete_decode = decode_ptr;\n#endif\n    decode->image_id = image_id;",
    "F07 decode rollback pointer")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    texture_decode_worker.QueueWork(std::move(func));\n}",
    "    texture_decode_worker.QueueWork(std::move(func));\n#ifdef PS5_NATIVE\n    decode_admitted = true;\n#endif\n}",
    "F07 decode successful admission marker")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    image.flags |= ImageFlagBits::IsDecoding;\n\n    unswizzle_queue.push_back({\n        .image_id = image_id,\n        .info = image.info\n    });\n}",
    "#ifndef PS5_NATIVE\n    image.flags |= ImageFlagBits::IsDecoding;\n#endif\n    // Native: commit IsDecoding only after successful queue admission.\n    // A throwing allocation must not leave a permanently pending image.\n    unswizzle_queue.push_back({\n        .image_id = image_id,\n        .info = image.info\n    });\n#ifdef PS5_NATIVE\n    image.flags |= ImageFlagBits::IsDecoding;\n#endif\n}",
    "F07 unswizzle queue before pending flag")

# F07 P0.4: if a CPU write races an existing async upload, preserve
# CpuModified and do not enqueue another decode for the same image.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    if (False(image.flags & ImageFlagBits::CpuModified)) {\n        // Only upload modified images\n        return;\n    }\n\n#ifdef PS5_NATIVE\n    ::Eden::Performance::CachePhaseTimer upload_phase",
    "    if (False(image.flags & ImageFlagBits::CpuModified)) {\n        // Only upload modified images\n        return;\n    }\n#ifdef PS5_NATIVE\n    // A previous asynchronous upload still owns this image. Guest CPU\n    // writes must remain dirty until that decode completes; otherwise\n    // another RefreshContents could clear CpuModified and queue an older\n    // revision behind the in-flight job, leaving HUD pixels stale.\n    if (True(image.flags & ImageFlagBits::IsDecoding)) {\n        return;\n    }\n#endif\n\n#ifdef PS5_NATIVE\n    ::Eden::Performance::CachePhaseTimer upload_phase",
    "F07 defer CPU revision while decode is in flight")

# F07 P0.4: asynchronous decoded images must fit their CURRENT staging
# size, and the decode mutex must be unlocked before its owner is erased.
# Never mutate the pinned source; keep this reviewed native fork delta exact.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        Image& image = slot_images[async_decode->image_id];\n        auto staging = runtime.UploadStagingBuffer(MapSizeBytes(image));\n        std::memcpy(staging.mapped_span.data(), async_decode->decoded_data.data(),\n                    async_decode->decoded_data.size());",
    "        Image& image = slot_images[async_decode->image_id];\n#ifdef PS5_NATIVE\n        // A texture may have been remapped or resized while decode was queued.\n        // Do not copy the old revision beyond its current staging allocation.\n        const size_t expected_size = MapSizeBytes(image);\n        if (async_decode->decoded_data.size() != expected_size) {\n            image.flags &= ~ImageFlagBits::IsDecoding;\n            image.flags |= ImageFlagBits::CpuModified;\n            if (True(image.flags & ImageFlagBits::Tracked)) {\n                UntrackImage(image, async_decode->image_id);\n            }\n            // Erasing the context destroys its mutex. Drop our lock first.\n            lock.unlock();\n            i = async_decodes.erase(i);\n            continue;\n        }\n        auto staging = runtime.UploadStagingBuffer(expected_size);\n#else\n        auto staging = runtime.UploadStagingBuffer(MapSizeBytes(image));\n#endif\n        std::memcpy(staging.mapped_span.data(), async_decode->decoded_data.data(),\n                    async_decode->decoded_data.size());",
    "F07 async texture revision length guard")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        has_uploads = true;\n        i = async_decodes.erase(i);",
    "        has_uploads = true;\n        // The context owns async_decode->mutex. Unlock before destroying it.\n        lock.unlock();\n        i = async_decodes.erase(i);",
    "F07 async decode unlock before context erase")

apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if (async_decode->decoded_data.size() != expected_size) {\n            image.flags &= ~ImageFlagBits::IsDecoding;",
    "        if (async_decode->decoded_data.size() != expected_size ||\n            True(image.flags & ImageFlagBits::CpuModified)) {\n            // A newer guest CPU write invalidates the queued result even\n            // when dimensions have not changed (typical dynamic HUD).\n            // Keep CpuModified set so the newer content is re-uploaded.\n            image.flags &= ~ImageFlagBits::IsDecoding;",
    "F07 discard stale decoded HUD revision after CPU write")

# F07 P0.3: compute dispatch currently holds both guest cache mutexes but
# does not distinguish contention from descriptor/texture Configure work.
# Sample only Detailed Logging, mirroring the graphics paired-lock timer.
apply_reviewed_delta("vulkan_rasterizer.cpp",
    "    SCOPE_EXIT { SyncProbe(scheduler, \"dispatch\", pipeline); };\n    std::scoped_lock lock{texture_cache.mutex, buffer_cache.mutex};\n    if (!pipeline->Configure(*kepler_compute, *gpu_memory, scheduler, buffer_cache,\n                             texture_cache)) {\n        return;\n    }\n",
    "    SCOPE_EXIT { SyncProbe(scheduler, \"dispatch\", pipeline); };\n#ifdef PS5_NATIVE\n    // P0.3: sampled compute lock wait versus time spent holding both guest\n    // caches. No fence, shader, descriptor or lock ordering change.\n    const bool compute_sample = ::Eden::Performance::ShouldSampleCacheDraw();\n    ::Eden::Performance::CachePhaseTimer compute_pair_wait{\n        ::Eden::Performance::CachePhase::ComputePairWait, compute_sample};\n#endif\n    std::scoped_lock lock{texture_cache.mutex, buffer_cache.mutex};\n#ifdef PS5_NATIVE\n    compute_pair_wait.Stop();\n    ::Eden::Performance::CachePhaseTimer compute_pair_held{\n        ::Eden::Performance::CachePhase::ComputePairHeld, compute_sample};\n    ::Eden::Performance::CachePhaseTimer compute_configure{\n        ::Eden::Performance::CachePhase::ComputeConfigure, compute_sample};\n#endif\n    if (!pipeline->Configure(*kepler_compute, *gpu_memory, scheduler, buffer_cache,\n                             texture_cache)) {\n        return;\n    }\n#ifdef PS5_NATIVE\n    compute_configure.Stop();\n#endif\n",
    "F07 compute paired GPU cache profiling")

# F07 P0.1: graphics first-use shader translation references this global
# across two native translation units. The historical R421 insertion was
# in an anonymous namespace; relocate after the pinned deltas above.
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "namespace Vulkan {\n#ifdef PS5_NATIVE\n// The optional graphics optimizer also yields to cold compute builds.\nextern std::atomic<unsigned> pending_first_use_compute_builds;\n#endif\nnamespace {",
    "namespace Vulkan {\n#ifdef PS5_NATIVE\n// Graphics first-use builds and cold shader translation share this counter.\n// Export it from Vulkan, not the anonymous namespace, for native LTO.\nextern std::atomic<unsigned> pending_first_use_compute_builds;\nstd::atomic<unsigned> pending_first_use_graphics_builds{0};\n#endif\nnamespace {",
    "F07 graphics first-use counter exported at Vulkan namespace scope")
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "constexpr size_t NUM_STAGES = Maxwell::MaxShaderStage;\n#ifdef PS5_NATIVE\n// Counts cold first-use Vulkan graphics builds, not draws or cached pipelines.\n// Only the optional fast-first dev profile updates it; normal gameplay pays nothing.\nstd::atomic<unsigned> pending_first_use_graphics_builds{0};\n#endif",
    "constexpr size_t NUM_STAGES = Maxwell::MaxShaderStage;\n// The shared first-use graphics counter is defined at Vulkan namespace scope.",
    "F07 remove anonymous graphics counter shadow")

# F07 P0.4: reject decoded bytes from the old guest mapping before staging.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if (async_decode->decoded_data.size() != expected_size ||\n            True(image.flags & ImageFlagBits::CpuModified)) {\n            // A newer guest CPU write invalidates the queued result even\n            // when dimensions have not changed (typical dynamic HUD).\n            // Keep CpuModified set so the newer content is re-uploaded.",
    "        if (async_decode->decoded_data.size() != expected_size ||\n            True(image.flags & ImageFlagBits::CpuModified) ||\n            True(image.flags & ImageFlagBits::Remapped)) {\n            // A guest CPU revision OR remapping invalidates decoded bytes,\n            // even when dimensions have not changed (dynamic HUD).\n            // Retain CpuModified so the current mapping can be refreshed.",
    "F07 discard same-size async texture after guest remap")

# F07 P0.1/P0.2: foreground shader priority starts BEFORE environment
# acquisition/pool reset, not after that synchronous GPU owner-thread work.
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "std::unique_ptr<GraphicsPipeline> PipelineCache::CreateGraphicsPipeline() {\n    auto timer = Eden::Performance::VulkanTimer(17);\n    GraphicsEnvironments environments;",
    "std::unique_ptr<GraphicsPipeline> PipelineCache::CreateGraphicsPipeline() {\n    auto timer = Eden::Performance::VulkanTimer(17);\n#ifdef PS5_NATIVE\n    // Reserve priority before guest shader environment reads and pool reset.\n    // The inner translation scope overlaps this reservation, so there is no\n    // idle gap for speculative Vulkan optimization before the first-use build.\n    GraphicsTranslationPriorityScope first_use_preparation_priority{\n        ::Eden::DevVulkan::fast_first_pipelines};\n#endif\n    GraphicsEnvironments environments;",
    "F07 graphics environment first-use priority before shader translation")
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "std::unique_ptr<ComputePipeline> PipelineCache::CreateComputePipeline(\n    const ComputePipelineCacheKey& key, const ShaderInfo* shader) {\n    auto timer = Eden::Performance::VulkanTimer(17);\n    const GPUVAddr program_base{kepler_compute->regs.code_loc.Address()};",
    "std::unique_ptr<ComputePipeline> PipelineCache::CreateComputePipeline(\n    const ComputePipelineCacheKey& key, const ShaderInfo* shader) {\n    auto timer = Eden::Performance::VulkanTimer(17);\n#ifdef PS5_NATIVE\n    // Count compute environment setup and shader pool reset as foreground\n    // work, not only the downstream CFG/IR/SPIR-V translation.\n    ComputeTranslationPriorityScope first_use_preparation_priority{true};\n#endif\n    const GPUVAddr program_base{kepler_compute->regs.code_loc.Address()};",
    "F07 compute environment first-use priority before shader translation")

# F07 P0.2: cap queued/running OPTIONAL graphics rebuilds, never first-use
# pipelines. The worker owns a slot only after QueueWork admission succeeds.
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "namespace {\nCommon::ThreadWorker& OptimizeWorker() {",
    "namespace {\n#ifdef PS5_NATIVE\n// Only first-use pipelines are mandatory. Cap queued + running speculative\n// driver rebuilds so HUD shader bursts cannot accumulate unbounded work.\nconstexpr unsigned kMaxQueuedOptionalOptimizations = 16;\nstd::atomic<unsigned> pending_optional_optimizations{0};\n\nbool ReserveOptionalOptimizationSlot() noexcept {\n    unsigned pending = pending_optional_optimizations.load(std::memory_order_relaxed);\n    while (pending < kMaxQueuedOptionalOptimizations) {\n        if (pending_optional_optimizations.compare_exchange_weak(\n                pending, pending + 1, std::memory_order_acq_rel,\n                std::memory_order_relaxed)) {\n            return true;\n        }\n    }\n    return false;\n}\n#endif\nCommon::ThreadWorker& OptimizeWorker() {",
    "F07 bound optional Vulkan optimizer queue helper")
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "void GraphicsPipeline::QueueOptimizedPipeline(VkRenderPass render_pass) {\n    optimize_state = std::make_shared<OptimizeState>();",
    "void GraphicsPipeline::QueueOptimizedPipeline(VkRenderPass render_pass) {\n#ifdef PS5_NATIVE\n    // A skipped OPTIONAL rebuild keeps the already-built first-use pipeline.\n    // Reserve before allocations so an overloaded worker uses no extra memory.\n    if (!ReserveOptionalOptimizationSlot()) return;\n    bool optional_slot_handed_off = false;\n    SCOPE_EXIT {\n        if (!optional_slot_handed_off) {\n            pending_optional_optimizations.fetch_sub(1, std::memory_order_release);\n        }\n    };\n#endif\n    optimize_state = std::make_shared<OptimizeState>();",
    "F07 skip overloaded optional pipeline builds before allocation")
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "                state->done.notify_all();\n            }\n        } completion{state};",
    "                state->done.notify_all();\n#ifdef PS5_NATIVE\n                // Every accepted job releases its slot, including cancellation.\n                pending_optional_optimizations.fetch_sub(1, std::memory_order_release);\n#endif\n            }\n        } completion{state};",
    "F07 release optional pipeline slot on completion or cancellation")
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "        });\n    } catch (...) {\n        // QueueWork failed before the worker accepted ownership. Do not strand",
    "        });\n#ifdef PS5_NATIVE\n        // The queued worker now owns the slot. The caller's failure guard\n        // handles allocation/admission exceptions before this handoff.\n        optional_slot_handed_off = true;\n#endif\n    } catch (...) {\n        // QueueWork failed before the worker accepted ownership. Do not strand",
    "F07 hand off optional pipeline slot after successful queue admission")

# F07 P0.3: inline DMA writes to never-registered CPU pages cannot affect a
# pre-existing GPU buffer. Avoid the buffer mutex only on proven-empty spans;
# preserve the guest write, texture, shader and query invalidation order.
apply_reviewed_delta("vulkan_rasterizer.cpp",
    "    {\n        std::unique_lock<std::recursive_mutex> lock{buffer_cache.mutex};\n        if (!buffer_cache.InlineMemory(*cpu_addr, copy_size, memory)) {\n            buffer_cache.WriteMemory(*cpu_addr, copy_size);\n        }\n    }",
    "    // P0.3: an unregistered page has no buffer-backed GPU dirty bytes.\n    // Unknown, large and previously owned spans retain the original lock.\n    if (!::Eden::BufferPages::NeverRegistered(*cpu_addr, copy_size)) {\n        std::unique_lock<std::recursive_mutex> lock{buffer_cache.mutex};\n        if (!buffer_cache.InlineMemory(*cpu_addr, copy_size, memory)) {\n            buffer_cache.WriteMemory(*cpu_addr, copy_size);\n        }\n    }",
    "F07 elide never-owned inline DMA buffer cache mutex")

# F07 P0.3: the shipping Eden backport already contains consecutive-TIC
# reuse. Extend THAT reviewed source to a bounded nonadjacent draw-local memo.
# Deletion, NULL results and blacklist passes retain the full lookup.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "void TextureCache<P>::FillImageViews(std::span<ImageViewInOut> views, bool compute, bool blacklist) {\n    bool has_blacklisted = false;\n    do {\n        has_deleted_images = false;\n        if (blacklist) {\n            has_blacklisted = false;\n        }\n#ifdef PS5_NATIVE\n        // Reuse only the immediately preceding successful TIC binding in a\n        // read-only pass. Deletion, NULL recovery and blacklist effects must\n        // still visit every descriptor.\n        u32 previous_image_index{};\n        ImageViewId previous_view_id = NULL_IMAGE_VIEW_ID;\n#endif\n        for (ImageViewInOut& view : views) {\n#ifdef PS5_NATIVE\n            if (!blacklist && !has_deleted_images &&\n                previous_view_id != NULL_IMAGE_VIEW_ID &&\n                previous_image_index == view.index) {\n                view.id = previous_view_id;\n                continue;\n            }\n#endif\n            view.id = VisitImageView(view.index, compute);\n#ifdef PS5_NATIVE\n            previous_image_index = view.index;\n            previous_view_id = view.id;\n#endif\n            if (blacklist) {\n                if (view.blacklist && view.id != NULL_IMAGE_VIEW_ID) {\n                    const ImageViewBase& image_view = slot_image_views[view.id];\n                    auto& image = slot_images[image_view.image_id];\n                    has_blacklisted |= ScaleDown(image);\n                    image.scale_rating = 0;\n                }\n            }\n        }\n    } while (has_deleted_images || (blacklist && has_blacklisted));\n}",
    "void TextureCache<P>::FillImageViews(std::span<ImageViewInOut> views, bool compute, bool blacklist) {\n    bool has_blacklisted = false;\n    do {\n        has_deleted_images = false;\n        if (blacklist) {\n            has_blacklisted = false;\n        }\n#ifdef PS5_NATIVE\n        // P0.3: reuse nonadjacent TIC descriptors only in this stable draw pass.\n        // Never bypass NULL recovery, deletion-driven retry or blacklist work.\n        struct ViewMemo {\n            u32 index{};\n            ImageViewId id{NULL_IMAGE_VIEW_ID};\n        };\n        std::array<ViewMemo, 16> view_memo{};\n#endif\n        for (ImageViewInOut& view : views) {\n#ifdef PS5_NATIVE\n            if (!blacklist && !has_deleted_images) {\n                const auto& cached = view_memo[view.index & 15U];\n                if (cached.id != NULL_IMAGE_VIEW_ID && cached.index == view.index) {\n                    const auto& cached_view = slot_image_views[cached.id];\n                    // A different TIC can remap this image during the pass.\n                    // VisitImageView must rebuild remapped descriptors.\n                    const bool remapped = !cached_view.IsBuffer() &&\n                        True(slot_images[cached_view.image_id].flags & ImageFlagBits::Remapped);\n                    if (!remapped) {\n                        view.id = cached.id;\n                        // Reuse the lookup only: PrepareImageView still\n                        // refreshes dirty pixels and synchronizes aliases.\n                        PrepareImageView(cached.id, false, false);\n                        continue;\n                    }\n                }\n            }\n#endif\n            view.id = VisitImageView(view.index, compute);\n#ifdef PS5_NATIVE\n            if (!blacklist && !has_deleted_images) {\n                auto& cached = view_memo[view.index & 15U];\n                cached.index = view.index;\n                cached.id = view.id;\n            }\n#endif\n            if (blacklist) {\n                if (view.blacklist && view.id != NULL_IMAGE_VIEW_ID) {\n                    const ImageViewBase& image_view = slot_image_views[view.id];\n                    auto& image = slot_images[image_view.image_id];\n                    has_blacklisted |= ScaleDown(image);\n                    image.scale_rating = 0;\n                }\n            }\n        }\n    } while (has_deleted_images || (blacklist && has_blacklisted));\n}",
    "F07 bounded per-draw nonadjacent TIC memo and generator parity")

# F07 P0.3: clean render-target draws already have an authoritative active
# color/depth bitmask from their last dirty target refresh. Avoid preparing
# absent views while preserving live image refresh, ordering and dirty path.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    if (!flags[Dirty::RenderTargets]) {\n        for (size_t index = 0; index < NUM_RT; ++index) {\n            ImageViewId& color_buffer_id = render_targets.color_buffer_ids[index];\n            PrepareImageView(color_buffer_id, true, is_clear && IsFullClear(color_buffer_id));\n        }\n        const ImageViewId depth_buffer_id = render_targets.depth_buffer_id;\n        PrepareImageView(depth_buffer_id, true, is_clear && IsFullClear(depth_buffer_id));\n        return;\n    }",
    "    if (!flags[Dirty::RenderTargets]) {\n#ifdef PS5_NATIVE\n        // Cache the active attachment mask when render targets are reselected.\n        // On a clean draw it is current: only present views can be prepared.\n        // Preserve color-slot order, depth-last, and every live GPU refresh.\n        u32 active_colors = rt_active_mask & ((1U << NUM_RT) - 1U);\n        while (active_colors != 0) {\n            const size_t index = std::countr_zero(active_colors);\n            active_colors &= active_colors - 1U;\n            const ImageViewId color_buffer_id = render_targets.color_buffer_ids[index];\n            PrepareImageView(color_buffer_id, true, is_clear && IsFullClear(color_buffer_id));\n        }\n        if ((rt_active_mask & (1U << NUM_RT)) != 0) {\n            const ImageViewId depth_buffer_id = render_targets.depth_buffer_id;\n            PrepareImageView(depth_buffer_id, true, is_clear && IsFullClear(depth_buffer_id));\n        }\n#else\n        for (size_t index = 0; index < NUM_RT; ++index) {\n            ImageViewId& color_buffer_id = render_targets.color_buffer_ids[index];\n            PrepareImageView(color_buffer_id, true, is_clear && IsFullClear(color_buffer_id));\n        }\n        const ImageViewId depth_buffer_id = render_targets.depth_buffer_id;\n        PrepareImageView(depth_buffer_id, true, is_clear && IsFullClear(depth_buffer_id));\n#endif\n        return;\n    }",
    "F07 sparse clean render-target refresh using active attachment mask")

# F07 P0.3: skip zero-region Vulkan copies. For barrier-only batches,
# retain both ordering barriers; staging upload must not swallow them.
apply_reviewed_delta("vk_buffer_cache_cost.cpp",
    "    if (dst_buffer == VK_NULL_HANDLE || src_buffer == VK_NULL_HANDLE) {\n        return;\n    }\n    static constexpr VkMemoryBarrier READ_BARRIER{",
    "    if (dst_buffer == VK_NULL_HANDLE || src_buffer == VK_NULL_HANDLE) {\n        return;\n    }\n#ifdef PS5_NATIVE\n    // Vulkan copies require at least one region. An empty batch is a\n    // no-op unless the caller explicitly requested synchronization.\n    // Preserve both barriers without recording an invalid zero-region copy,\n    // including when a staging upload would otherwise bypass the barriers.\n    if (copies.empty()) {\n        if (barrier) {\n            PreCopyBarrier();\n            PostCopyBarrier();\n        }\n        return;\n    }\n#endif\n    static constexpr VkMemoryBarrier READ_BARRIER{",
    "F07 avoid barrier-free empty Vulkan buffer copies")

# F07 P0.3: a zero-byte clear has no guest-visible write. The Vulkan
# fill command requires a nonzero region; do not enqueue its empty transfer.
apply_reviewed_delta("vk_buffer_cache_cost.cpp",
    "void BufferCacheRuntime::ClearBuffer(VkBuffer dest_buffer, u32 offset, size_t size, u32 value) {\n    if (dest_buffer == VK_NULL_HANDLE) {\n        return;\n    }\n    static constexpr VkMemoryBarrier READ_BARRIER{",
    "void BufferCacheRuntime::ClearBuffer(VkBuffer dest_buffer, u32 offset, size_t size, u32 value) {\n    if (dest_buffer == VK_NULL_HANDLE) {\n        return;\n    }\n#ifdef PS5_NATIVE\n    // A zero-length fill has no memory side effects and is invalid for\n    // vkCmdFillBuffer. Do not record a transfer or its redundant barriers.\n    if (size == 0) {\n        return;\n    }\n#endif\n    static constexpr VkMemoryBarrier READ_BARRIER{",
    "F07 skip zero-sized Vulkan buffer fill")

# F07 P0.3: the same guest vertex binding range rejection should happen
# before Handle(), null-buffer reserve or host vector preparation. Do not
# reorder any valid-range Vulkan recording or change desktop behavior.
apply_reviewed_delta("vk_buffer_cache_cost.cpp",
    "void BufferCacheRuntime::BindVertexBuffers(VideoCommon::HostBindings<Buffer>& bindings) {\n    boost::container::static_vector<VkBuffer, VideoCommon::NUM_VERTEX_BUFFERS> buffer_handles(bindings.buffers.size());\n    for (u32 i = 0; i < bindings.buffers.size(); ++i) {\n        auto handle = bindings.buffers[i]->Handle();\n        if (handle == VK_NULL_HANDLE) {\n            bindings.offsets[i] = 0;\n            bindings.sizes[i] = VK_WHOLE_SIZE;\n            if (!device.HasNullDescriptor()) {\n                ReserveNullBuffer();\n                handle = *null_buffer;\n            }\n        }\n        buffer_handles[i] = handle;\n    }\n    const u32 device_max = device.GetMaxVertexInputBindings();\n    const u32 min_binding = (std::min)(bindings.min_index, device_max);\n    const u32 max_binding = (std::min)(bindings.max_index, device_max);\n    // Do not wrap a reversed binding range into a huge Vulkan binding count.\n    if (max_binding <= min_binding) {\n        return;\n    }\n    const u32 binding_count = max_binding - min_binding;",
    "void BufferCacheRuntime::BindVertexBuffers(VideoCommon::HostBindings<Buffer>& bindings) {\n    // Reject a reversed/empty/out-of-device-range draw BEFORE resolving guest\n    // vertex handles or reserving substitute null buffers under cache locks.\n    const u32 device_max = device.GetMaxVertexInputBindings();\n    const u32 min_binding = (std::min)(bindings.min_index, device_max);\n    const u32 max_binding = (std::min)(bindings.max_index, device_max);\n    // Do not wrap a reversed binding range into a huge Vulkan binding count.\n    if (max_binding <= min_binding) {\n        return;\n    }\n    const u32 binding_count = max_binding - min_binding;\n    boost::container::static_vector<VkBuffer, VideoCommon::NUM_VERTEX_BUFFERS> buffer_handles(bindings.buffers.size());\n    for (u32 i = 0; i < bindings.buffers.size(); ++i) {\n        auto handle = bindings.buffers[i]->Handle();\n        if (handle == VK_NULL_HANDLE) {\n            bindings.offsets[i] = 0;\n            bindings.sizes[i] = VK_WHOLE_SIZE;\n            if (!device.HasNullDescriptor()) {\n                ReserveNullBuffer();\n                handle = *null_buffer;\n            }\n        }\n        buffer_handles[i] = handle;\n    }",
    "F07 reject empty vertex binding ranges before cache handle resolution")

# F07 P0.3: the PS5 driver cap can truncate an otherwise valid host span.
# Resolve only the handles passed to Vulkan and reject mismatched host arrays
# before recording a deferred callback. Keep desktop semantics unchanged.
apply_reviewed_delta("vk_buffer_cache_cost.cpp",
    "    const u32 binding_count = max_binding - min_binding;\n    boost::container::static_vector<VkBuffer, VideoCommon::NUM_VERTEX_BUFFERS> buffer_handles(bindings.buffers.size());\n    for (u32 i = 0; i < bindings.buffers.size(); ++i) {",
    "    const u32 binding_count = max_binding - min_binding;\n#ifdef PS5_NATIVE\n    // Do not resolve or allocate handles for indices the device cannot bind.\n    // Both buffer-cache producers keep all host vectors aligned to the range.\n    // Reject malformed input before a deferred Vulkan command can read it.\n    if (bindings.buffers.size() < binding_count ||\n        bindings.offsets.size() < binding_count ||\n        bindings.sizes.size() < binding_count ||\n        bindings.strides.size() < binding_count) {\n        return;\n    }\n    const u32 handle_count = binding_count;\n#else\n    const u32 handle_count = static_cast<u32>(bindings.buffers.size());\n#endif\n    boost::container::static_vector<VkBuffer, VideoCommon::NUM_VERTEX_BUFFERS> buffer_handles(handle_count);\n    for (u32 i = 0; i < handle_count; ++i) {",
    "F07 trim vertex handles after device limit clamp")

# F07 P0.3: reuse same-generation compute descriptor payload without
# reading guest bytes before paired cache synchronization. Desktop unchanged.
apply_reviewed_delta(
    "include/video_core/renderer_vulkan/vk_compute_pipeline.h",
    "#include <mutex>\n",
    "#include <mutex>\n#include <vector>\n",
    "F07 compute header vector")

apply_reviewed_delta(
    "include/video_core/renderer_vulkan/vk_compute_pipeline.h",
    "    [[nodiscard]] VkDeviceSize DescriptorRingPreflightSize() const noexcept {\n        // Unlike graphics, every descriptor-buffer compute dispatch allocates.\n        return uses_descriptor_buffer ? descriptor_buffer_layout.size : 0;\n    }",
    "    [[nodiscard]] VkDeviceSize DescriptorRingPreflightSize() const noexcept {\n        // Only pre-drain guaranteed allocations; same-size changed data\n        // retains Allocate's normal fallback inside Configure.\n        return uses_descriptor_buffer &&\n                       (!last_descriptor_buffer_valid ||\n                        last_descriptor_buffer_generation !=\n                            descriptor_buffer_ring.CurrentGeneration() ||\n                        last_descriptor_payload.size() != num_descriptor_entries)\n                   ? descriptor_buffer_layout.size : 0;\n    }",
    "F07 compute ring reuse preflight")

apply_reviewed_delta(
    "include/video_core/renderer_vulkan/vk_compute_pipeline.h",
    "    u32 num_descriptor_entries{};\n#ifdef PS5_NATIVE\n    size_t num_image_elements{};",
    "    u32 num_descriptor_entries{};\n#ifdef PS5_NATIVE\n    // The last uploaded snapshot is valid only in its own ring generation.\n    std::vector<DescriptorUpdateEntry> last_descriptor_payload;\n    VkDeviceSize last_descriptor_buffer_offset{};\n    u32 last_descriptor_buffer_chunk{};\n    u64 last_descriptor_buffer_generation{};\n    bool last_descriptor_buffer_valid{};\n    size_t num_image_elements{};",
    "F07 compute descriptor snapshot fields")

apply_reviewed_delta(
    "vk_compute_pipeline_cost.cpp",
    "void ComputePipeline::PreflightDescriptorScratch() {\n    // No guest texture/cache data is consulted here: counts are immutable.",
    "void ComputePipeline::PreflightDescriptorScratch() {\n    // Reserve on the GPU owner, before the paired guest cache mutexes.\n    // Compare guest payload bytes only after their normal synchronization.\n    if (uses_descriptor_buffer &&\n        last_descriptor_payload.capacity() < num_descriptor_entries) {\n        last_descriptor_payload.reserve(num_descriptor_entries);\n    }\n    // No guest texture/cache data is consulted here: counts are immutable.",
    "F07 compute descriptor snapshot preflight")

apply_reviewed_delta(
    "vk_compute_pipeline_cost.cpp",
    "    const DescriptorUpdateEntry* const descriptor_data{guest_descriptor_queue.UpdateData()};\n    VkDeviceSize descriptor_buffer_offset{};\n    u32 descriptor_buffer_chunk{};\n    if (uses_descriptor_buffer) {\n        const DescriptorBufferRing::Allocation alloc{\n            descriptor_buffer_ring.Allocate(scheduler, descriptor_buffer_layout.size)};\n        if (!alloc.host) {\n            LOG_DEBUG(Render_Vulkan, \"Failed to reserve descriptor memory, skipping dispatch\");\n            return false;\n        }\n        WriteDescriptorBuffer(device, descriptor_buffer_layout, descriptor_data, alloc.host);\n        descriptor_buffer_offset = alloc.offset;\n        descriptor_buffer_chunk = alloc.chunk;\n    }\n\n",
    "    const DescriptorUpdateEntry* const descriptor_data{guest_descriptor_queue.UpdateData()};\n    VkDeviceSize descriptor_buffer_offset{};\n    u32 descriptor_buffer_chunk{};\n    if (uses_descriptor_buffer) {\n#ifdef PS5_NATIVE\n        // Same payload and generation: keep the previously uploaded bytes,\n        // extending the GPU ring tick without another allocation or upload.\n        const bool reuse_allocation =\n            last_descriptor_buffer_valid &&\n            last_descriptor_buffer_generation == descriptor_buffer_ring.CurrentGeneration() &&\n            last_descriptor_payload.size() == num_descriptor_entries &&\n            (num_descriptor_entries == 0 ||\n             std::memcmp(last_descriptor_payload.data(), descriptor_data,\n                         num_descriptor_entries * sizeof(DescriptorUpdateEntry)) == 0);\n        if (reuse_allocation) {\n            descriptor_buffer_offset = last_descriptor_buffer_offset;\n            descriptor_buffer_chunk = last_descriptor_buffer_chunk;\n            descriptor_buffer_ring.TouchFrame(scheduler);\n        } else\n#endif\n        {\n            const DescriptorBufferRing::Allocation alloc{\n                descriptor_buffer_ring.Allocate(scheduler, descriptor_buffer_layout.size)};\n            if (!alloc.host) {\n                LOG_DEBUG(Render_Vulkan, \"Failed to reserve descriptor memory, skipping dispatch\");\n                return false;\n            }\n            WriteDescriptorBuffer(device, descriptor_buffer_layout, descriptor_data, alloc.host);\n            descriptor_buffer_offset = alloc.offset;\n            descriptor_buffer_chunk = alloc.chunk;\n#ifdef PS5_NATIVE\n            last_descriptor_buffer_offset = alloc.offset;\n            last_descriptor_buffer_chunk = alloc.chunk;\n            last_descriptor_buffer_generation = alloc.generation;\n            if (num_descriptor_entries != 0) {\n                last_descriptor_payload.assign(descriptor_data,\n                                               descriptor_data + num_descriptor_entries);\n            } else {\n                last_descriptor_payload.clear();\n            }\n            last_descriptor_buffer_valid = true;\n#endif\n        }\n    }\n\n",
    "F07 compute descriptor payload fast reuse")

apply_reviewed_delta(
    "vulkan_rasterizer.cpp",
    "    // Compute always allocates new descriptor-buffer space for a dispatch.\n    // Drain only necessary GPU fences while neither guest cache is locked.",
    "    // Compute reuses same-generation identical descriptor payloads.\n    // Pre-drain guaranteed allocations, not uncertain changed payloads,\n    // while neither guest cache is locked.",
    "F07 compute preflight comment")

# F07: descriptor equality uses std::memcmp; do not rely on transitive includes.
apply_reviewed_delta(
    'vk_compute_pipeline_cost.cpp',
    "#include <memory>\n#include <vector>",
    "#include <cstring>\n#include <memory>\n#include <vector>",
    'F07 compute explicit cstring descriptor compare include')


# F07 P0.4: a background texture conversion can fail AFTER queue admission.
# Keep its worker alive and publish a zero-length completion sentinel. The
# native TickAsyncDecode then retires the stale context and re-dirties the
# guest image instead of keeping IsDecoding forever or uploading partial data.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    auto func = [out_size, copies, info = image.info,\n                 input = std::move(local_unswizzle_data_buffer),\n                 async_decode = decode_ptr]() mutable {\n        async_decode->decoded_data.resize_destructive(out_size);\n        std::span copies_span{copies.data(), copies.size()};\n        ConvertImage(input, info, async_decode->decoded_data, copies_span);\n\n        // TODO: Do we need this lock?\n        std::unique_lock lock{async_decode->mutex};\n        async_decode->copies = std::move(copies);\n        async_decode->complete = true;\n    };",
    "    auto func = [out_size, copies, info = image.info,\n                 input = std::move(local_unswizzle_data_buffer),\n                 async_decode = decode_ptr]() mutable {\n#ifdef PS5_NATIVE\n        try {\n#endif\n            async_decode->decoded_data.resize_destructive(out_size);\n            std::span copies_span{copies.data(), copies.size()};\n            ConvertImage(input, info, async_decode->decoded_data, copies_span);\n\n            std::unique_lock lock{async_decode->mutex};\n            async_decode->copies = std::move(copies);\n            async_decode->complete = true;\n#ifdef PS5_NATIVE\n        } catch (...) {\n            // Preserve worker liveness after a conversion/allocation failure.\n            // A zero-length completed decode is a retryable failed revision;\n            // TickAsyncDecode drops it without uploading partial HUD pixels.\n            std::unique_lock lock{async_decode->mutex};\n            async_decode->decoded_data.resize_destructive(0);\n            async_decode->complete = true;\n        }\n#endif\n    };",
    "F07 async decode worker exception handoff")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if (async_decode->decoded_data.size() != expected_size ||\n            True(image.flags & ImageFlagBits::CpuModified) ||",
    "        if (async_decode->decoded_data.size() == 0 ||\n            async_decode->decoded_data.size() != expected_size ||\n            True(image.flags & ImageFlagBits::CpuModified) ||",
    "F07 reject zero-length failed decode completion")

# F07 P0.3: avoid per-frame worker mutex acquisition for an incomplete decode.
# Keep the existing completion mutex and pending branch for desktop builds.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        auto* async_decode = i->get();\n        std::unique_lock lock{async_decode->mutex};\n        if (!async_decode->complete) {\n            ++i;\n            continue;\n        }",
    "        auto* async_decode = i->get();\n#ifdef PS5_NATIVE\n        // The worker publishes decoded bytes with the atomic completion flag.\n        // Poll unfinished decodes without contending on its mutex each frame.\n        if (!async_decode->complete.load(std::memory_order_acquire)) {\n            ++i;\n            continue;\n        }\n#endif\n        std::unique_lock lock{async_decode->mutex};\n#ifndef PS5_NATIVE\n        if (!async_decode->complete) {\n            ++i;\n            continue;\n        }\n#endif",
    "F07 atomic unfinished texture decode polling")

# F07: preserve parallel transition arrays under partial allocation failure.
# In native builds a failed pointer append must roll back the successful key
# append, or Next() may address a missing transition and crash. Normal lookup
# and the non-PS5 path are unchanged.
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "void GraphicsPipeline::AddTransition(GraphicsPipeline* transition) {\n    transition_keys.push_back(transition->key);\n    transitions.push_back(transition);\n}",
    "void GraphicsPipeline::AddTransition(GraphicsPipeline* transition) {\n    transition_keys.push_back(transition->key);\n#ifdef PS5_NATIVE\n    // Both arrays must describe the same transition index. An allocation\n    // failure while appending the pointer must not leave an orphaned key:\n    // Next() would later index past transitions and corrupt a guest draw.\n    try {\n        transitions.push_back(transition);\n    } catch (...) {\n        transition_keys.pop_back();\n        throw;\n    }\n#else\n    transitions.push_back(transition);\n#endif\n}",
    "F07 graphics transition append rollback")

# F07 P0.2: a fast transition edge is optional metadata, not the pipeline.
# Failure to append it must leave both vectors aligned AND not abort the
# active draw: CurrentGraphicsPipeline can use its canonical graphics cache.
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "    } catch (...) {\n        transition_keys.pop_back();\n        throw;\n    }\n#else\n    transitions.push_back(transition);",
    "    } catch (...) {\n        // Transition memoization is optional. The primary graphics cache\n        // already owns the pipeline; a later lookup can use its slow path.\n        // Do not abort a guest draw solely because this edge could not fit.\n        transition_keys.pop_back();\n        return;\n    }\n#else\n    transitions.push_back(transition);",
    "F07 optional transition OOM no-throw fallback")

# F07: the FIRST optional transition-vector append can also fail under
# low memory. Ignore its allocation failure on native PS5 just like a failed
# pointer append; neither failure should abort a draw when graphics_cache
# already owns the target pipeline. Non-PS5 behavior remains unchanged.
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "void GraphicsPipeline::AddTransition(GraphicsPipeline* transition) {\n    transition_keys.push_back(transition->key);\n#ifdef PS5_NATIVE\n    // Both arrays must describe the same transition index. An allocation",
    "void GraphicsPipeline::AddTransition(GraphicsPipeline* transition) {\n#ifdef PS5_NATIVE\n    // Both appends are optional memoization. The canonical graphics cache\n    // already owns the target and will resolve a missing edge on demand.\n    try {\n        transition_keys.push_back(transition->key);\n    } catch (...) {\n        return;\n    }\n#else\n    transition_keys.push_back(transition->key);\n#endif\n#ifdef PS5_NATIVE\n    // Both arrays must describe the same transition index. An allocation",
    "F07 optional transition first append OOM guard")

# F07 P0.4: completed async decodes must not strand IsDecoding after a
# Vulkan staging allocation exception or short mapping. Reject failed bytes,
# untrack the image and retain CpuModified for a later refresh.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        auto staging = runtime.UploadStagingBuffer(expected_size);\n#else\n        auto staging = runtime.UploadStagingBuffer(MapSizeBytes(image));\n#endif\n        std::memcpy(staging.mapped_span.data(), async_decode->decoded_data.data(),\n                    async_decode->decoded_data.size());",
    "        // Upload staging may fail after the decode worker completed.\n        // Never leave IsDecoding stuck or copy into an undersized buffer.\n        auto staging = [&]() -> decltype(runtime.UploadStagingBuffer(expected_size)) {\n            try {\n                return runtime.UploadStagingBuffer(expected_size);\n            } catch (...) {\n                return {};\n            }\n        }();\n        if (!staging.buffer || staging.mapped_span.size() < expected_size) {\n            image.flags &= ~ImageFlagBits::IsDecoding;\n            image.flags |= ImageFlagBits::CpuModified;\n            if (True(image.flags & ImageFlagBits::Tracked)) {\n                UntrackImage(image, async_decode->image_id);\n            }\n            lock.unlock();\n            i = async_decodes.erase(i);\n            continue;\n        }\n#else\n        auto staging = runtime.UploadStagingBuffer(MapSizeBytes(image));\n#endif\n        std::memcpy(staging.mapped_span.data(), async_decode->decoded_data.data(),\n                    async_decode->decoded_data.size());",
    "F07 async decoded staging allocation failure and short span recovery")

# F07 PS5 native: F07 reset idle unswizzle cooldown; retain the desktop source behavior.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "void TextureCache<P>::TickAsyncUnswizzle() {\n    if (unswizzle_queue.empty()) {\n        return;\n    }",
    "void TextureCache<P>::TickAsyncUnswizzle() {\n    if (unswizzle_queue.empty()) {\n#ifdef PS5_NATIVE\n        // Do not carry the prior batch's 4-frame cooldown across an idle\n        // period. A future texture is a fresh request, not a queued batch.\n        current_unswizzle_frame = 0u;\n#endif\n        return;\n    }",
    "F07 reset idle unswizzle cooldown")

# F07 PS5 native: F07 throttle only queued unswizzle batches; retain the desktop source behavior.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        // Wait 4 frames to process the next entry\n        current_unswizzle_frame = 4u;",
    "#ifdef PS5_NATIVE\n        // Throttle back-to-back queued uploads, not a later newly queued\n        // texture after an otherwise empty GPU frame.\n        current_unswizzle_frame = unswizzle_queue.empty() ? 0u : 4u;\n#else\n        // Wait 4 frames to process the next entry\n        current_unswizzle_frame = 4u;\n#endif",
    "F07 throttle only queued unswizzle batches")

# F07 PS5 native: F07 3D unswizzle staging OOM and short mapping recovery; retain the desktop source behavior.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "#ifdef PS5_NATIVE\n        task.staging_buffer = runtime.UploadStagingBuffer(task.total_size, true);\n#endif\n        task.last_submitted_offset = 0;",
    "#ifdef PS5_NATIVE\n        // A rejected/short staging allocation must not pin IsDecoding or\n        // permit guest DMA reads into an incomplete mapped GPU upload.\n        auto staging = [&]() -> decltype(runtime.UploadStagingBuffer(task.total_size, true)) {\n            try {\n                return runtime.UploadStagingBuffer(task.total_size, true);\n            } catch (...) {\n                return {};\n            }\n        }();\n        if (!staging.buffer || staging.mapped_span.size() < task.total_size) {\n            // A valid deferred buffer may have been returned with a short\n            // mapping. Release it through the existing GPU-tick mechanism.\n            if (staging.buffer) {\n                runtime.FreeDeferredStagingBuffer(staging);\n            }\n            image.flags |= ImageFlagBits::CpuModified;\n            if (True(image.flags & ImageFlagBits::Tracked)) {\n                UntrackImage(image, task.image_id);\n            }\n            image.flags &= ~ImageFlagBits::IsDecoding;\n            unswizzle_queue.pop_front();\n            current_unswizzle_frame = 0u;\n            return;\n        }\n        task.staging_buffer = staging;\n#endif\n        task.last_submitted_offset = 0;",
    "F07 3D unswizzle staging OOM and short mapping recovery")

# F07 P0.1: keep the existing 64/32-key failure budgets, but make retry
# admission fair when a HUD/scene burst contains more distinct failed shaders.
# O(capacity) eviction runs only once on an actual cold failure, never on a
# successful pipeline or steady draw. The oldest eligible_at is evicted.
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "        if (!pipeline && failed_graphics_retries.size() < 64) {\n            // Cold misses are allowed to fail, but do not cache a transient\n            // translation error forever. Only failed keys allocate metadata.\n            failed_graphics_retries.try_emplace(\n                graphics_key, GraphicsRetryState{\n                    std::chrono::steady_clock::now() + std::chrono::seconds(2), false});\n        }",
    "        if (!pipeline) {\n            // Failed-key retry metadata is capped, but a burst of >=64\n            // failures must not permanently deny NEW shaders their one\n            // delayed recovery attempt. Rotate only on failure, never on a\n            // successful draw or during the hot null-cache lookup.\n            if (failed_graphics_retries.size() >= 64) {\n                const auto oldest = std::min_element(\n                    failed_graphics_retries.begin(), failed_graphics_retries.end(),\n                    [](const auto& left, const auto& right) {\n                        return left.second.eligible_at < right.second.eligible_at;\n                    });\n                if (oldest != failed_graphics_retries.end()) {\n                    failed_graphics_retries.erase(oldest);\n                }\n            }\n            failed_graphics_retries.try_emplace(\n                graphics_key, GraphicsRetryState{\n                    std::chrono::steady_clock::now() + std::chrono::seconds(2), false});\n        }",
    "F07 bounded graphics retry fairness under failing shader burst")

# F07 P0.1: keep the existing 64/32-key failure budgets, but make retry
# admission fair when a HUD/scene burst contains more distinct failed shaders.
# O(capacity) eviction runs only once on an actual cold failure, never on a
# successful pipeline or steady draw. The oldest eligible_at is evicted.
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "        if (!pipeline && failed_compute_retries.size() < 32) {\n            // A transient guest shader translation failure must not permanently\n            // suppress a compute dispatch. Track failures only.\n            failed_compute_retries.try_emplace(\n                key, ComputeRetryState{\n                    std::chrono::steady_clock::now() + std::chrono::seconds(2), false});\n        }",
    "        if (!pipeline) {\n            // Bound recovery metadata without starving the latest failed\n            // compute shaders after 32 earlier failed keys. This scan runs\n            // ONLY on a new null pipeline, not per compute dispatch.\n            if (failed_compute_retries.size() >= 32) {\n                const auto oldest = std::min_element(\n                    failed_compute_retries.begin(), failed_compute_retries.end(),\n                    [](const auto& left, const auto& right) {\n                        return left.second.eligible_at < right.second.eligible_at;\n                    });\n                if (oldest != failed_compute_retries.end()) {\n                    failed_compute_retries.erase(oldest);\n                }\n            }\n            failed_compute_retries.try_emplace(\n                key, ComputeRetryState{\n                    std::chrono::steady_clock::now() + std::chrono::seconds(2), false});\n        }",
    "F07 bounded compute retry fairness under failing shader burst")

# F07: FIFO worker wait dedup; only native PS5 uses a per-pipeline owner flag.
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "    if (!is_built.load(std::memory_order_acquire)) {\n        // Wait for the pipeline to be built\n        scheduler.Record([this](vk::CommandBuffer) {",
    "    if (!is_built.load(std::memory_order_acquire)) {\n#ifdef PS5_NATIVE\n        // The Vulkan worker processes command chunks in FIFO order. Once a\n        // readiness wait precedes the first draw, later draws for this same\n        // pipeline are already ordered behind it. GPU-owner thread only.\n        if (!first_use_wait_recorded) {\n#endif\n        // Wait for the pipeline to be built\n        scheduler.Record([this](vk::CommandBuffer) {",
    "F07 FIFO once wait graphics start")

# F07: FIFO worker wait dedup; only native PS5 uses a per-pipeline owner flag.
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "        });\n    }\n    const bool is_rescaling",
    "        });\n#ifdef PS5_NATIVE\n        // Commit only after the callback was successfully enqueued.\n        first_use_wait_recorded = true;\n        }\n#endif\n    }\n    const bool is_rescaling",
    "F07 FIFO once wait graphics end")

# F07: FIFO worker wait dedup; only native PS5 uses a per-pipeline owner flag.
apply_reviewed_delta("vk_compute_pipeline_cost.cpp",
    "    if (!is_built.load(std::memory_order_acquire)) {\n        // Wait for the pipeline to be built\n        scheduler.Record([this](vk::CommandBuffer) {",
    "    if (!is_built.load(std::memory_order_acquire)) {\n#ifdef PS5_NATIVE\n        // The Vulkan worker processes command chunks in FIFO order. Once a\n        // readiness wait precedes the first draw, later draws for this same\n        // pipeline are already ordered behind it. GPU-owner thread only.\n        if (!first_use_wait_recorded) {\n#endif\n        // Wait for the pipeline to be built\n        scheduler.Record([this](vk::CommandBuffer) {",
    "F07 FIFO once wait compute start")

# F07: FIFO worker wait dedup; only native PS5 uses a per-pipeline owner flag.
apply_reviewed_delta("vk_compute_pipeline_cost.cpp",
    "        });\n    }\n\n    // Log compute pipeline binding",
    "        });\n#ifdef PS5_NATIVE\n        first_use_wait_recorded = true;\n        }\n#endif\n    }\n\n    // Log compute pipeline binding",
    "F07 FIFO once wait compute end")

# F07: FIFO worker wait dedup; only native PS5 uses a per-pipeline owner flag.
apply_reviewed_delta("include/video_core/renderer_vulkan/vk_graphics_pipeline.h",
    "    std::atomic_bool is_built{false};\n    bool uses_push_descriptor{false};",
    "    std::atomic_bool is_built{false};\n#ifdef PS5_NATIVE\n    // Only the GPU owner writes this after enqueueing the ordered worker wait.\n    bool first_use_wait_recorded{};\n#endif\n    bool uses_push_descriptor{false};",
    "F07 FIFO once wait graphics header end")

# F07: FIFO worker wait dedup; only native PS5 uses a per-pipeline owner flag.
apply_reviewed_delta("include/video_core/renderer_vulkan/vk_compute_pipeline.h",
    "    std::atomic_bool is_built{false};\n};\n\n} // namespace Vulkan",
    "    std::atomic_bool is_built{false};\n#ifdef PS5_NATIVE\n    // The first queued wait covers all following compute dispatches.\n    bool first_use_wait_recorded{};\n#endif\n};\n\n} // namespace Vulkan",
    "F07 FIFO once wait compute header end")

# F07 P0.1: shader translation exceptions are already expensive. Only build
# a SECOND CFG and write .ash diagnostic files when explicitly opted in on
# native PS5; preserve the primary shader error even if diagnostics fail.
# Desktop's original unconditional failed-shader dump behavior is untouched.
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "} catch (const Shader::Exception& exception) {\n    auto hash = key.Hash();\n    size_t env_index{0};\n    for (size_t index = 0; index < Maxwell::MaxShaderProgram; ++index) {\n        if (key.unique_hashes[index] == 0) {\n            continue;\n        }\n        Shader::Environment& env{*envs[env_index]};\n        ++env_index;\n\n        const u32 cfg_offset{static_cast<u32>(env.StartAddress() + sizeof(Shader::ProgramHeader))};\n        ::Eden::Performance::CachePhaseTimer cfg_stage_cost{\n            ::Eden::Performance::CachePhase::ShaderCfg,\n            ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)};\n        auto cfg_cost = Eden::Performance::VulkanTimer(20);\n        Shader::Maxwell::Flow::CFG cfg(env, pools.flow_block, cfg_offset, index == 0);\n        cfg_cost.reset();\n        cfg_stage_cost.Stop();\n        env.Dump(hash, key.unique_hashes[index]);\n    }\n    LOG_ERROR(Render_Vulkan, \"{}\", exception.what());\n    return nullptr;\n}",
    "} catch (const Shader::Exception& exception) {\n#ifdef PS5_NATIVE\n    // Failed first-use shaders can be retried. Do not rebuild their CFGs or\n    // write .ash dumps on the normal quiet PS5 path: this is optional debug\n    // work on the same GPU-owner thread that already failed translation.\n    if (Settings::values.dump_guest_shaders) {\n        try {\n#endif\n    auto hash = key.Hash();\n    size_t env_index{0};\n    for (size_t index = 0; index < Maxwell::MaxShaderProgram; ++index) {\n        if (key.unique_hashes[index] == 0) {\n            continue;\n        }\n        Shader::Environment& env{*envs[env_index]};\n        ++env_index;\n\n        const u32 cfg_offset{static_cast<u32>(env.StartAddress() + sizeof(Shader::ProgramHeader))};\n        ::Eden::Performance::CachePhaseTimer cfg_stage_cost{\n            ::Eden::Performance::CachePhase::ShaderCfg,\n            ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)};\n        auto cfg_cost = Eden::Performance::VulkanTimer(20);\n        Shader::Maxwell::Flow::CFG cfg(env, pools.flow_block, cfg_offset, index == 0);\n        cfg_cost.reset();\n        cfg_stage_cost.Stop();\n        env.Dump(hash, key.unique_hashes[index]);\n    }\n#ifdef PS5_NATIVE\n        } catch (const std::exception& dump_error) {\n            // Preserve the original shader failure even if the diagnostic\n            // CFG pass or the dump file itself fails.\n            LOG_WARNING(Render_Vulkan, \"Failed shader diagnostic dump: {}\", dump_error.what());\n        } catch (...) {\n            LOG_WARNING(Render_Vulkan, \"Failed shader diagnostic dump: unknown exception\");\n        }\n    }\n#endif\n    LOG_ERROR(Render_Vulkan, \"{}\", exception.what());\n    return nullptr;\n}",
    "F07 PS5 skip duplicate CFG and dumps after shader exception unless opted in")

# F07 P0.4: GPU image upload can throw *after* async conversion completed.
# Clear its outstanding decode flag and keep the CPU revision dirty instead
# of holding a completed worker context forever. Desktop stays unchanged.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        image.UploadMemory(staging, FixSmallVectorADL(async_decode->copies));\n        image.flags &= ~ImageFlagBits::IsDecoding;",
    "#ifdef PS5_NATIVE\n        // A failed GPU submission must not strand a completed worker decode.\n        // Staging here is non-deferred; the pool owns its lifetime. Keep the\n        // source image dirty so a later refresh can upload a fresh revision.\n        try {\n#endif\n        image.UploadMemory(staging, FixSmallVectorADL(async_decode->copies));\n#ifdef PS5_NATIVE\n        } catch (...) {\n            image.flags &= ~ImageFlagBits::IsDecoding;\n            image.flags |= ImageFlagBits::CpuModified;\n            if (True(image.flags & ImageFlagBits::Tracked)) {\n                UntrackImage(image, async_decode->image_id);\n            }\n            lock.unlock();\n            i = async_decodes.erase(i);\n            continue;\n        }\n#endif\n        image.flags &= ~ImageFlagBits::IsDecoding;",
    "F07 async decoded Vulkan submission failure recovery")

# F07 P0.4: failed BCn 3D GPU dispatch must not permanently pin the image's
# IsDecoding state or its staging buffer. Native only; desktop is unchanged.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if (z_count > 0) {\n            const auto uploads = FullUploadSwizzles(task.info);\n            runtime.AccelerateImageUpload(image, task.staging_buffer, FixSmallVectorADL(uploads), z_start, z_count);\n            task.last_submitted_offset += (static_cast<size_t>(z_count) * task.bytes_per_slice);\n        }",
    "        if (z_count > 0) {\n#ifdef PS5_NATIVE\n            try {\n#endif\n            const auto uploads = FullUploadSwizzles(task.info);\n            runtime.AccelerateImageUpload(image, task.staging_buffer, FixSmallVectorADL(uploads), z_start, z_count);\n#ifdef PS5_NATIVE\n            } catch (...) {\n                // Upload setup/recording may reject a batch. Submitted GPU\n                // commands keep their source alive through the deferred pool;\n                // reject the incomplete old revision and retry from guest data.\n                runtime.FreeDeferredStagingBuffer(task.staging_buffer);\n                image.flags |= ImageFlagBits::CpuModified;\n                if (True(image.flags & ImageFlagBits::Tracked)) {\n                    UntrackImage(image, task.image_id);\n                }\n                image.flags &= ~ImageFlagBits::IsDecoding;\n                unswizzle_queue.pop_front();\n                current_unswizzle_frame = 0u;\n                return;\n            }\n#endif\n            task.last_submitted_offset += (static_cast<size_t>(z_count) * task.bytes_per_slice);\n        }",
    "F07 failed 3D GPU upload dispatch recovery")

# F07 P0.4: a GPU guest-memory read can reject a partially staged BCn-3D
# image. Drop the in-flight task, release its GPU staging in deferred order,
# and keep CPU dirty so the next refresh reads the current guest revision.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        gpu_memory->ReadBlock(image.gpu_addr + task.current_offset,\n                              task.staging_buffer.mapped_span.data() + task.current_offset,\n                              copy_amount);\n        task.current_offset += copy_amount;",
    "#ifdef PS5_NATIVE\n        try {\n#endif\n        gpu_memory->ReadBlock(image.gpu_addr + task.current_offset,\n                              task.staging_buffer.mapped_span.data() + task.current_offset,\n                              copy_amount);\n#ifdef PS5_NATIVE\n        } catch (...) {\n            // A failed guest read invalidates the partial GPU staging data.\n            // Deferred release also protects batches submitted earlier.\n            runtime.FreeDeferredStagingBuffer(task.staging_buffer);\n            image.flags |= ImageFlagBits::CpuModified;\n            if (True(image.flags & ImageFlagBits::Tracked)) {\n                UntrackImage(image, task.image_id);\n            }\n            image.flags &= ~ImageFlagBits::IsDecoding;\n            unswizzle_queue.pop_front();\n            current_unswizzle_frame = 0u;\n            return;\n        }\n#endif\n        task.current_offset += copy_amount;",
    "F07 failed BCn 3D guest read recovery")

# F07 P0.2: optional Vulkan rebuild admission is not necessary to publish the
# already-built quick pipeline. Do not let a queue OOM/rejection reach the
# enclosing critical first-use build handler on the GPU builder worker.
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "                MakePipeline(render_pass, VK_PIPELINE_CREATE_DISABLE_OPTIMIZATION_BIT);\n                QueueOptimizedPipeline(render_pass);\n            } else {",
    "                MakePipeline(render_pass, VK_PIPELINE_CREATE_DISABLE_OPTIMIZATION_BIT);\n#ifdef PS5_NATIVE\n                // This speculative rebuild is not required by the first-use\n                // pipeline. Admission/OOM failures must not turn an already\n                // valid gameplay pipeline into a failed builder invocation.\n                try {\n                    QueueOptimizedPipeline(render_pass);\n                } catch (const std::exception& error) {\n                    LOG_WARNING(Render_Vulkan, \"Optional pipeline rebuild queue rejected: {}\", error.what());\n                } catch (...) {\n                    LOG_WARNING(Render_Vulkan, \"Optional pipeline rebuild queue rejected: unknown exception\");\n                }\n#else\n                QueueOptimizedPipeline(render_pass);\n#endif\n            } else {",
    "F07 isolate optional optimizer enqueue rejection from initial pipeline build")

# F07 P0.1: failures inside the async serializer must preserve the next
# cache-save checkpoint without writing non-atomic pipeline quota from the
# worker thread. Only the owner consumes the atomic failure flag, after which
# the unchanged 30s/size gate prevents a retry storm. Native only.
apply_reviewed_delta("include/video_core/renderer_vulkan/vk_pipeline_cache.h",
    "    std::atomic_bool flush_in_flight{};\n\n    Common::ThreadWorker workers;",
    "    std::atomic_bool flush_in_flight{};\n#ifdef PS5_NATIVE\n    // Written by the serializer; consumed only by the GPU-owner thread.\n    // Do not mutate pipelines_since_flush concurrently with Vulkan draws.\n    std::atomic_bool flush_worker_failed{};\n#endif\n\n    Common::ThreadWorker workers;",
    "F07 driver cache worker failure owner handoff state")
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "    if (++pipelines_since_flush < VULKAN_CACHE_FLUSH_PIPELINES) {",
    "#ifdef PS5_NATIVE\n    // Recover a failed background serialization without racing the owner's\n    // non-atomic quota. The existing time gate still bounds retry frequency.\n    if (flush_worker_failed.exchange(false, std::memory_order_acq_rel)) {\n        pipelines_since_flush = VULKAN_CACHE_FLUSH_PIPELINES;\n    }\n#endif\n    if (++pipelines_since_flush < VULKAN_CACHE_FLUSH_PIPELINES) {",
    "F07 restore failed cache flush quota on GPU owner")
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "            } catch (const std::exception& error) {\n                LOG_WARNING(Render_Vulkan, \"Deferred driver cache flush failed: {}\", error.what());\n            } catch (...) {\n                LOG_WARNING(Render_Vulkan, \"Deferred driver cache flush failed: unknown exception\");\n            }",
    "            } catch (const std::exception& error) {\n#ifdef PS5_NATIVE\n                // Signal a new checkpoint, but only the GPU owner may update\n                // the ordinary pipeline build quota on its next call.\n                flush_worker_failed.store(true, std::memory_order_release);\n#endif\n                LOG_WARNING(Render_Vulkan, \"Deferred driver cache flush failed: {}\", error.what());\n            } catch (...) {\n#ifdef PS5_NATIVE\n                flush_worker_failed.store(true, std::memory_order_release);\n#endif\n                LOG_WARNING(Render_Vulkan, \"Deferred driver cache flush failed: unknown exception\");\n            }",
    "F07 publish driver cache worker failure atomically")

# F07 P0.4: a transient PS5 staging/CPU conversion allocation exception
# must unwind via the existing dirty-image rollback instead of aborting.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    auto staging = runtime.UploadStagingBuffer(MapSizeBytes(image));\n#ifdef PS5_NATIVE\n    staging_phase.Stop();",
    "#ifdef PS5_NATIVE\n    try {\n#endif\n    auto staging = runtime.UploadStagingBuffer(MapSizeBytes(image));\n#ifdef PS5_NATIVE\n    staging_phase.Stop();",
    "F07 contain native sync texture allocation failure at upload entry")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    barrier_phase.Stop();\n    upload_completed = true;\n#endif\n}",
    "    barrier_phase.Stop();\n    upload_completed = true;\n    } catch (const std::bad_alloc&) {\n        // A transient staging/CPU conversion OOM must not abort the GPU owner.\n        // The existing scope guard untracks and keeps the revision dirty.\n        return;\n    }\n#endif\n}",
    "F07 dirty native sync texture retry after bad allocation")

# F07 P0.4: reject short non-deferred sync staging before any image transfer.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    auto staging = runtime.UploadStagingBuffer(MapSizeBytes(image));\n#ifdef PS5_NATIVE\n    staging_phase.Stop();",
    "#ifdef PS5_NATIVE\n    const size_t upload_size = MapSizeBytes(image);\n    auto staging = runtime.UploadStagingBuffer(upload_size);\n    if (!staging.buffer || staging.mapped_span.size_bytes() < upload_size) {\n        // No valid image bytes can be uploaded from an incomplete mapping.\n        // The existing rollback scope guard retains CpuModified for retry.\n        return;\n    }\n#else\n    auto staging = runtime.UploadStagingBuffer(MapSizeBytes(image));\n#endif\n#ifdef PS5_NATIVE\n    staging_phase.Stop();",
    "F07 reject short native sync upload staging")

# F07 P0.4: native BCn-3D upload cannot complete without a compute pass.
# The queued caller catches the failure and retains the CPU guest revision.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "#include <optional>\n#include <span>",
    "#include <optional>\n#include <stdexcept>\n#include <span>",
    "F07 native BCn 3D unavailable pass exception include")
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "        if (IsPixelFormatBCn(image.info.format) && image.info.type == ImageType::e3D) {\n            ASSERT(false && \"GPU unswizzle is disabled for BCn 3D texture\");\n        }\n        ASSERT(false);\n        return;",
    "        if (IsPixelFormatBCn(image.info.format) && image.info.type == ImageType::e3D) {\n#ifdef PS5_NATIVE\n            // Never silently acknowledge a BCn-3D upload with no compute\n            // pass. TickAsyncUnswizzle catches this and retries fresh pixels.\n            throw std::runtime_error(\"BCn 3D Vulkan unswizzle pass unavailable\");\n#else\n            ASSERT(false && \"GPU unswizzle is disabled for BCn 3D texture\");\n#endif\n        }\n        ASSERT(false);\n        return;",
    "F07 native BCn 3D unavailable pass retry signal")

# F07 P0.3: oversized BCn 3D slices must not bypass the configured
# per-frame guest read budget while the GPU owner holds texture_cache.mutex.
# Partial staging is safe: the existing bytes_ready/slice-count guard
# submits only complete slices. Desktop behavior is retained.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if (remaining > swizzle_chunk_size) {\n            copy_amount = (copy_amount / task.bytes_per_slice) * task.bytes_per_slice;\n            if (copy_amount == 0) copy_amount = task.bytes_per_slice;\n        }",
    "        if (remaining > swizzle_chunk_size) {\n            copy_amount = (copy_amount / task.bytes_per_slice) * task.bytes_per_slice;\n            if (copy_amount == 0) {\n#ifdef PS5_NATIVE\n                // One BCn-3D slice can exceed the per-frame read budget.\n                // Stage a partial slice; dispatch still waits until a full\n                // slice is ready. Do not copy >budget under texture mutex.\n                copy_amount = (std::min)(swizzle_chunk_size, remaining);\n#else\n                copy_amount = task.bytes_per_slice;\n#endif\n            }\n        }",
    "F07 bound oversized BCn 3D slice reads per native frame")

# F07: changing the live unswizzle setting can leave a queued task with a
# zero native read budget; avoid a zero-byte read that pins IsDecoding.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "                copy_amount = (std::min)(swizzle_chunk_size, remaining);\n#else",
    "                // A zero budget can occur if GPU unswizzle is toggled\n                // after cache construction. Retain forward progress instead\n                // of pinning IsDecoding forever on a zero-byte read.\n                copy_amount = swizzle_chunk_size != 0\n                    ? (std::min)(swizzle_chunk_size, remaining)\n                    : (std::min)(task.bytes_per_slice, remaining);\n#else",
    "F07 preserve BCn 3D read progress when budget is zero")

# F07 P0.3: TickAsyncDecode is invoked under texture_cache.mutex.
# Keep a fixed per-frame bound on completed decodes but preserve the full
# source-extracted GPU submission, stale-revision checks and upload barrier.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "void TextureCache<P>::TickAsyncDecode() {\n    bool has_uploads{};\n    auto i = async_decodes.begin();",
    "void TextureCache<P>::TickAsyncDecode() {\n    bool has_uploads{};\n#ifdef PS5_NATIVE\n    // TickFrame holds texture_cache.mutex: cap completed async uploads so\n    // a burst of HUD textures cannot occupy the entire cache lock in one\n    // frame. Work not processed this tick retains its decode context.\n    constexpr size_t kMaxCompletedDecodesPerTick = 4;\n    size_t completed_decodes = 0;\n#endif\n    auto i = async_decodes.begin();",
    "F07 native async texture completion quota")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if (!async_decode->complete.load(std::memory_order_acquire)) {\n            ++i;\n            continue;\n        }\n#endif\n        std::unique_lock lock{async_decode->mutex};",
    "        if (!async_decode->complete.load(std::memory_order_acquire)) {\n            ++i;\n            continue;\n        }\n        if (completed_decodes == kMaxCompletedDecodesPerTick) {\n            break;\n        }\n        ++completed_decodes;\n#endif\n        std::unique_lock lock{async_decode->mutex};",
    "F07 bounded ready decode completion under texture lock")

# F07: do not queue native BCn-3D GPU unswizzle when the optional setting
# was enabled after cache creation but chunk/slice budgets remain zero.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    if (gpu_unswizzle_enabled &&\n        IsPixelFormatBCn(image.info.format) &&",
    "    if (gpu_unswizzle_enabled &&\n#ifdef PS5_NATIVE\n        // Live GPU setting can enable unswizzle after cache construction;\n        // zero-sized chunks or batches cannot submit any GPU slices.\n        swizzle_chunk_size != 0 && swizzle_slices_per_batch != 0 &&\n#endif\n        IsPixelFormatBCn(image.info.format) &&",
    "F07 reject uninitialized BCn 3D async queue budgets")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    if (True(image.flags & (ImageFlagBits::CpuModified | ImageFlagBits::Remapped))) {",
    "    if (True(image.flags & (ImageFlagBits::CpuModified | ImageFlagBits::Remapped)) ||\n        swizzle_chunk_size == 0 || swizzle_slices_per_batch == 0) {",
    "F07 retire queued BCn 3D image when budget is zero")

# F07 P0.3: the GC's native direct-memory probe must run only for a dirty
# eviction candidate. Avoid up to 8192 kernel-backed probes for clean entries
# while holding texture_cache.mutex. No change to dirty eviction decisions.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if ((!aggressive_mode && True(image.flags & ImageFlagBits::CostlyLoad)) || (!DirtyEvictions() && must_download)) {",
    "        // A clean image has no guest readback. Do not query PS5 direct-memory\n        // pressure for it: the memory probe may be kernel-backed, and this\n        // entire LRU sweep runs under texture_cache.mutex.\n        if ((!aggressive_mode && True(image.flags & ImageFlagBits::CostlyLoad)) ||\n            (must_download && !DirtyEvictions())) {",
    "F07 skip texture GC memory pressure probes for clean LRU entries")
# Apply the PS5 cleanup-only probe budget AFTER the older clean-image rewrite:
# the early pinned GC builder still uses (!DirtyEvictions() && must_download).
# Keep the two reversible deltas in their actual source-generation order.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if ((!aggressive_mode && True(image.flags & ImageFlagBits::CostlyLoad)) ||\n            (must_download && !DirtyEvictions())) {",
    "#ifdef PS5_NATIVE\n        if ((!aggressive_mode && True(image.flags & ImageFlagBits::CostlyLoad)) ||\n            (must_download && !DirtyEvictionsForCleanup())) {\n#else\n        if ((!aggressive_mode && True(image.flags & ImageFlagBits::CostlyLoad)) ||\n            (must_download && !DirtyEvictions())) {\n#endif",
    "F07 bound native dirty GC pressure checks after clean-image rewrite")

# F07 P0.3: a missing guest compute-indirect buffer must not be dereferenced
# or recorded under the paired texture/buffer cache mutexes on PS5. This is
# the same fail-closed contract as the existing draw-indirect guard.
apply_reviewed_delta("vulkan_rasterizer.cpp",
    "        const auto [buffer, offset] =\n            buffer_cache.ObtainBuffer(*indirect_address, 12, sync_info, post_op);\n        scheduler.RequestOutsideRenderPassOperationContext();",
    "        const auto [buffer, offset] =\n            buffer_cache.ObtainBuffer(*indirect_address, 12, sync_info, post_op);\n#ifdef PS5_NATIVE\n        // A guest indirect-command address can become unmapped after a\n        // shader/descriptor remap. Reject the missing binding before Vulkan\n        // barriers or a worker lambda captures buffer->Handle().\n        if (!buffer) {\n            return;\n        }\n#endif\n        scheduler.RequestOutsideRenderPassOperationContext();",
    "F07 reject unmapped indirect compute buffer before Vulkan commands")

# F07 P0.4: texture reinterpretation can request an invalid zero-sized
# scratch VkBuffer (GetTemporaryBuffer computes needed_size - 1) or overflow
# u32/size_t when accumulating 3D copy extents. Refuse the upload on PS5.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "void TextureCacheRuntime::ReinterpretImage(Image& dst, Image& src,\n                                           std::span<const VideoCommon::ImageCopy> copies) {\n    if (ENABLE_MSAA_RESOLVE_CONSUME) {",
    "void TextureCacheRuntime::ReinterpretImage(Image& dst, Image& src,\n                                           std::span<const VideoCommon::ImageCopy> copies) {\n#ifdef PS5_NATIVE\n    // An empty reinterpret has no image pixels or valid VkBufferImageCopy.\n    // Never ask GetTemporaryBuffer to classify a zero-sized allocation.\n    if (copies.empty()) {\n        return;\n    }\n#endif\n    if (ENABLE_MSAA_RESOLVE_CONSUME) {",
    "F07 reject empty native Vulkan reinterpret image copies")
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "    const u32 img_bpp = BytesPerBlock(dst.info.format);\n    size_t total_size = 0;\n    for (const auto& copy : copies) {\n        total_size += copy.extent.width * copy.extent.height * copy.extent.depth * img_bpp;\n    }\n    const VkBuffer copy_buffer = GetTemporaryBuffer(total_size);",
    "    const u32 img_bpp = BytesPerBlock(dst.info.format);\n    size_t total_size = 0;\n#ifdef PS5_NATIVE\n    // Prevent u32 intermediate overflow and size_t wrap before asking for\n    // a scratch VkBuffer. Invalid extents cannot be recorded as Vulkan copies.\n    constexpr size_t max_size = (std::numeric_limits<size_t>::max)();\n    for (const auto& copy : copies) {\n        const size_t width = copy.extent.width;\n        const size_t height = copy.extent.height;\n        const size_t depth = copy.extent.depth;\n        if (width == 0 || height == 0 || depth == 0 || img_bpp == 0 ||\n            width > max_size / height) {\n            return;\n        }\n        const size_t area = width * height;\n        if (area > max_size / depth) {\n            return;\n        }\n        const size_t volume = area * depth;\n        if (volume > max_size / img_bpp) {\n            return;\n        }\n        const size_t bytes = volume * img_bpp;\n        if (total_size > max_size - bytes) {\n            return;\n        }\n        total_size += bytes;\n    }\n#else\n    for (const auto& copy : copies) {\n        total_size += copy.extent.width * copy.extent.height * copy.extent.depth * img_bpp;\n    }\n#endif\n    const VkBuffer copy_buffer = GetTemporaryBuffer(total_size);",
    "F07 validate native Vulkan reinterpret scratch byte budget")

# F07: GetTemporaryBuffer indexes exactly 8*sizeof(size_t) scratch slots,
# so values above the largest power-of-two slot must be rejected BEFORE it.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "        total_size += bytes;\n    }\n#else\n    for (const auto& copy : copies) {",
    "        total_size += bytes;\n    }\n    // GetTemporaryBuffer indexes an array of 8*sizeof(size_t) buffers with\n    // ceil(log2(size)). Values above the highest power of two index the\n    // array one past its end even though size_t arithmetic did not overflow.\n    constexpr size_t scratch_max = size_t{1} << (std::numeric_limits<size_t>::digits - 1);\n    if (total_size > scratch_max) {\n        return;\n    }\n#else\n    for (const auto& copy : copies) {",
    "F07 reject scratch sizes outside Vulkan transient buffer slots")

apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    constexpr size_t kMaxCompletedDecodesPerTick = 4;\n    size_t completed_decodes = 0;\n#endif",
    "    constexpr size_t kMaxCompletedDecodesPerTick = 4;\n    size_t completed_decodes = 0;\n    // Keep every successfully submitted native texture ID in fixed storage:\n    // a rejected visibility barrier must invalidate the whole upload batch.\n    std::array<ImageId, kMaxCompletedDecodesPerTick> submitted_images{};\n    size_t submitted_count = 0;\n#endif",
    "F07 track native async uploaded images for barrier rollback")

apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        image.flags &= ~ImageFlagBits::IsDecoding;\n        has_uploads = true;\n        // The context owns async_decode->mutex. Unlock before destroying it.",
    "        image.flags &= ~ImageFlagBits::IsDecoding;\n        has_uploads = true;\n#ifdef PS5_NATIVE\n        submitted_images[submitted_count++] = async_decode->image_id;\n#endif\n        // The context owns async_decode->mutex. Unlock before destroying it.",
    "F07 remember every successful GPU texture upload ID")

apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    if (has_uploads) {\n        runtime.InsertUploadMemoryBarrier();\n    }\n}",
    "    if (has_uploads) {\n#ifdef PS5_NATIVE\n        try {\n#endif\n            runtime.InsertUploadMemoryBarrier();\n#ifdef PS5_NATIVE\n        } catch (...) {\n            // Re-upload current guest revisions after a rejected visibility\n            // barrier. All decoder contexts were unlocked/erased above.\n            for (size_t j = 0; j < submitted_count; ++j) {\n                const ImageId id = submitted_images[j];\n                Image& image = slot_images[id];\n                image.flags |= ImageFlagBits::CpuModified;\n                if (True(image.flags & ImageFlagBits::Tracked)) {\n                    UntrackImage(image, id);\n                }\n            }\n        }\n#endif\n    }\n}",
    "F07 mark entire decoded texture batch dirty after barrier failure")

# F07 P0.3/P0.4: stale HUD decode revisions and rejected staging are
# cheap to retire and must not consume one of the four actual upload slots.
# A separate 16-context completion budget protects the texture lock against
# unbounded runs of expired/failed results on a single frame.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    constexpr size_t kMaxCompletedDecodesPerTick = 4;\n"
    "    size_t completed_decodes = 0;\n"
    "    // Keep every successfully submitted native texture ID in fixed storage:",
    "    constexpr size_t kMaxCompletedDecodesPerTick = 4;\n"
    "    // Invalid/stale decodes must not consume the four REAL upload slots.\n"
    "    // Still cap retirements to keep the texture mutex responsive on a burst.\n"
    "    constexpr size_t kMaxRetiredDecodesPerTick = 16;\n"
    "    size_t completed_decodes = 0;\n"
    "    size_t retired_decodes = 0;\n"
    "    // Keep every successfully submitted native texture ID in fixed storage:",
    "F07 count only accepted async HUD uploads under independent retired decode budget")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if (completed_decodes == kMaxCompletedDecodesPerTick) {\n"
    "            break;\n"
    "        }\n"
    "        ++completed_decodes;\n"
    "#endif\n"
    "        std::unique_lock lock{async_decode->mutex};",
    "        if (completed_decodes == kMaxCompletedDecodesPerTick ||\n"
    "            retired_decodes == kMaxRetiredDecodesPerTick) {\n"
    "            break;\n"
    "        }\n"
    "        ++retired_decodes;\n"
    "#endif\n"
    "        std::unique_lock lock{async_decode->mutex};",
    "F07 bound completion retirements while skipping invalid async decode slots")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        submitted_images[submitted_count++] = async_decode->image_id;\n"
    "#endif\n"
    "        // The context owns async_decode->mutex.",
    "        submitted_images[submitted_count++] = async_decode->image_id;\n"
    "        ++completed_decodes;\n"
    "#endif\n"
    "        // The context owns async_decode->mutex.",
    "F07 increment successful async decode quota only after GPU submission")

# F07 P0.3: the decoder worker can publish complete=true while still
# holding its context mutex. Under texture_cache.mutex, polling that worker
# mutex must not block the GPU owner; skip the busy task and retry next frame.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        ++retired_decodes;\n#endif\n        std::unique_lock lock{async_decode->mutex};\n#ifndef PS5_NATIVE", "#endif\n#ifdef PS5_NATIVE\n        // The worker publishes completion before releasing its mutex. Do\n        // not block texture_cache.mutex just because its final handoff is\n        // still locked: retry this completed item on the following frame.\n        std::unique_lock lock{async_decode->mutex, std::try_to_lock};\n        if (!lock.owns_lock()) {\n            ++i;\n            continue;\n        }\n        ++retired_decodes;\n#else\n        std::unique_lock lock{async_decode->mutex};\n#endif\n#ifndef PS5_NATIVE",
    "F07 nonblocking completed async texture decode worker handoff")

# F07 P0.3: no render-target channel was selected on a raw clear.
# Preserve the pre-existing scheduler FlushWork and the desktop path. A
# native masked-out clear does not read textures or modify GPU pixels, so
# defer guest memory remap draining until the next real rendering operation.
apply_reviewed_delta("vulkan_rasterizer.cpp",
    "    FlushWork();\n"
    "    gpu_memory->FlushCaching();\n"
    "\n"
    "    auto& regs = maxwell3d->regs;\n"
    "    const bool use_color = regs.clear_surface.R || regs.clear_surface.G || regs.clear_surface.B ||\n"
    "                           regs.clear_surface.A;\n"
    "    const bool use_depth = regs.clear_surface.Z;\n"
    "    const bool use_stencil = regs.clear_surface.S;\n"
    "    if (!use_color && !use_depth && !use_stencil) {\n"
    "        return;\n"
    "    }\n"
    "\n"
    "    std::scoped_lock lock{texture_cache.mutex};",
    "    FlushWork();\n"
    "#ifndef PS5_NATIVE\n"
    "    gpu_memory->FlushCaching();\n"
    "#endif\n"
    "\n"
    "    auto& regs = maxwell3d->regs;\n"
    "    const bool use_color = regs.clear_surface.R || regs.clear_surface.G || regs.clear_surface.B ||\n"
    "                           regs.clear_surface.A;\n"
    "    const bool use_depth = regs.clear_surface.Z;\n"
    "    const bool use_stencil = regs.clear_surface.S;\n"
    "    if (!use_color && !use_depth && !use_stencil) {\n"
    "        return;\n"
    "    }\n"
    "#ifdef PS5_NATIVE\n"
    "    // An all-masked clear is not a GPU write. Preserve FlushWork and the\n"
    "    // debug probe but do not pay for guest remap/invalidation processing here;\n"
    "    // the next real rendering operation drains it before reading textures.\n"
    "    gpu_memory->FlushCaching();\n"
    "#endif\n"
    "    std::scoped_lock lock{texture_cache.mutex};",
    "F07 skip guest memory remap drain for all-masked native clear")

# F07 P0.1/P0.3: native raw blits must not trigger either alpha-state guest
# shader lookup under the texture cache mutex. A guest draw uses the already
# prepared pipeline; desktop preserves its original lookup behavior.
apply_reviewed_delta("vulkan_rasterizer.cpp",
    "    GraphicsPipeline* const pipeline = pipeline_cache.CurrentGraphicsPipeline();\n"
    "    const bool enable = pipeline != nullptr && pipeline->SupportsAlphaToCoverage() &&",
    "#ifdef PS5_NATIVE\n"
    "    // Guest draws have already selected their pipeline; raw DrawTexture blits\n"
    "    // must not translate an unrelated cold guest shader under texture lock.\n"
    "    GraphicsPipeline* const pipeline = prepared_pipeline;\n"
    "#else\n"
    "    GraphicsPipeline* const pipeline = pipeline_cache.CurrentGraphicsPipeline();\n"
    "#endif\n"
    "    const bool enable = pipeline != nullptr && pipeline->SupportsAlphaToCoverage() &&",
    "F07 avoid raw blit guest shader lookup for native AlphaToCoverage")

apply_reviewed_delta("vulkan_rasterizer.cpp",
    "    GraphicsPipeline* const pipeline = pipeline_cache.CurrentGraphicsPipeline();\n"
    "    const bool enable = pipeline != nullptr && pipeline->SupportsAlphaToOne() &&",
    "#ifdef PS5_NATIVE\n"
    "    // Guest draws have already selected their pipeline; raw DrawTexture blits\n"
    "    // must not translate an unrelated cold guest shader under texture lock.\n"
    "    GraphicsPipeline* const pipeline = prepared_pipeline;\n"
    "#else\n"
    "    GraphicsPipeline* const pipeline = pipeline_cache.CurrentGraphicsPipeline();\n"
    "#endif\n"
    "    const bool enable = pipeline != nullptr && pipeline->SupportsAlphaToOne() &&",
    "F07 avoid raw blit guest shader lookup for native AlphaToOne")

# F07: avoid a per-revision INFO log on the high-frequency native HUD
# async decode queue when detailed GPU profiling is disabled. Preserve desktop
# diagnostics and allow explicit native diagnostics when requested.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "void TextureCache<P>::QueueAsyncDecode(Image& image, ImageId image_id) {\n"
    "    UNIMPLEMENTED_IF(False(image.flags & ImageFlagBits::Converted));\n"
    "    LOG_INFO(HW_GPU, \"Queuing async texture decode\");",
    "void TextureCache<P>::QueueAsyncDecode(Image& image, ImageId image_id) {\n"
    "    UNIMPLEMENTED_IF(False(image.flags & ImageFlagBits::Converted));\n"
    "#ifdef PS5_NATIVE\n"
    "    // Dynamic HUD revisions can enqueue many decodes per second. Quiet\n"
    "    // releases need no per-texture INFO formatting or log queue traffic.\n"
    "    if (::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)) {\n"
    "        LOG_INFO(HW_GPU, \"Queuing async texture decode\");\n"
    "    }\n"
    "#else\n"
    "    LOG_INFO(HW_GPU, \"Queuing async texture decode\");\n"
    "#endif",
    "F07 gate per-HUD native decode INFO log behind detailed profile")

# F07 P0.3: the pinned alias backport already installs the tick short-
# circuit, but the Vulkan generator otherwise leaves the small_vector
# constructor ahead of it. Match the selected source and move construction
# behind the no-op return. Keep source/patch/generator byte-identical.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "void TextureCache<P>::SynchronizeAliases(ImageId image_id) {\n"
    "    boost::container::small_vector<const AliasedImage*, 8> aliased_images;\n"
    "    Image& image = slot_images[image_id];\n"
    "#ifdef PS5_NATIVE\n"
    "    // MarkModification advances the cache-wide tick monotonically. If this\n"
    "    // image already owns the latest tick, no alias can have a strictly newer\n"
    "    // modification, so the search, sort and copy cannot do useful work.\n"
    "    if (image.modification_tick == modification_tick) {\n"
    "        return;\n"
    "    }\n"
    "#endif",
    "void TextureCache<P>::SynchronizeAliases(ImageId image_id) {\n"
    "    Image& image = slot_images[image_id];\n"
    "#ifdef PS5_NATIVE\n"
    "    // MarkModification advances the cache-wide tick monotonically. If this\n"
    "    // image already owns the latest tick, no alias can have a strictly newer\n"
    "    // modification, so the search, sort and copy cannot do useful work.\n"
    "    if (image.modification_tick == modification_tick) {\n"
    "        return;\n"
    "    }\n"
    "#endif\n"
    "    // Avoid constructing the inline alias vector on a common no-op HUD lookup.\n"
    "    boost::container::small_vector<const AliasedImage*, 8> aliased_images;",
    "F07 avoid constructing alias vector on unchanged native image")

# F07: one newer alias needs no sort. Multiple newer aliases retain the
# existing monotonic modification-tick order (important for HUD freshness).
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    std::ranges::sort(aliased_images, [this](const AliasedImage* lhs, const AliasedImage* rhs) {\n"
    "        const ImageBase& lhs_image = slot_images[lhs->id];\n"
    "        const ImageBase& rhs_image = slot_images[rhs->id];\n"
    "        return lhs_image.modification_tick < rhs_image.modification_tick;\n"
    "    });",
    "#ifdef PS5_NATIVE\n"
    "    // Most alias refreshes have only one newer source. Sorting a single\n"
    "    // entry cannot change upload ordering and adds work under texture lock.\n"
    "    if (aliased_images.size() > 1) {\n"
    "#endif\n"
    "    std::ranges::sort(aliased_images, [this](const AliasedImage* lhs, const AliasedImage* rhs) {\n"
    "        const ImageBase& lhs_image = slot_images[lhs->id];\n"
    "        const ImageBase& rhs_image = slot_images[rhs->id];\n"
    "        return lhs_image.modification_tick < rhs_image.modification_tick;\n"
    "    });\n"
    "#ifdef PS5_NATIVE\n"
    "    }\n"
    "#endif",
    "F07 skip singleton native alias sort while preserving multi-alias order")

# F07 P0.4: ImageCanRescale can recursively traverse alias graphs and
# mutate lazy rescaling metadata. It is unnecessary when all involved images
# are unscaled: all branches simply copy the original pixel regions.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    const bool can_rescale = ImageCanRescale(image);\n"
    "    if (any_rescaled) {",
    "#ifdef PS5_NATIVE\n"
    "    // If neither this image nor its newer aliases are rescaled, the copy\n"
    "    // path does not use can_rescale. Avoid recursive alias-graph scans and\n"
    "    // lazy rescalability bookkeeping while the texture mutex is held.\n"
    "    const bool can_rescale = any_rescaled && ImageCanRescale(image);\n"
    "#else\n"
    "    const bool can_rescale = ImageCanRescale(image);\n"
    "#endif\n"
    "    if (any_rescaled) {",
    "F07 bypass recursive alias rescale checks when every source is unscaled")

# F07 P0.4: the pooled staging span may be rounded up to the next
# power of two. Read only the bytes requested by MapSizeBytes(image) in the
# accelerated upload; RefreshContents already validates handle and length.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    if (True(image.flags & ImageFlagBits::AcceleratedUpload)) {\n"
    "        gpu_memory->ReadBlock(gpu_addr, mapped_span.data(), mapped_span.size_bytes(),\n"
    "                              VideoCommon::CacheType::NoTextureCache);\n"
    "        const auto uploads = FullUploadSwizzles(image.info);",
    "    if (True(image.flags & ImageFlagBits::AcceleratedUpload)) {\n"
    "#ifdef PS5_NATIVE\n"
    "        // A pooled staging buffer may be power-of-two rounded and expose\n"
    "        // more mapped bytes than the image requested. Do not read unrelated\n"
    "        // guest memory or waste CPU DMA time filling the unused tail.\n"
    "        gpu_memory->ReadBlock(gpu_addr, mapped_span.data(), MapSizeBytes(image),\n"
    "                              VideoCommon::CacheType::NoTextureCache);\n"
    "#else\n"
    "        gpu_memory->ReadBlock(gpu_addr, mapped_span.data(), mapped_span.size_bytes(),\n"
    "                              VideoCommon::CacheType::NoTextureCache);\n"
    "#endif\n"
    "        const auto uploads = FullUploadSwizzles(image.info);",
    "F07 bound native accelerated texture guest read to requested upload size")

# F07 P0.4: the native async decode intermediate is wholly filled
# by UnswizzleImage for its emitted copy regions. Use the already available
# default-initialized move-only scratch buffer instead of a zero-filled vector
# before an expensive HUD decode. The worker accepts move-only tasks.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    std::vector<u8> local_unswizzle_data_buffer(image.unswizzled_size_bytes, 0);\n"
    "    Tegra::Memory::GpuGuestMemory<u8, Tegra::Memory::GuestMemoryFlags::UnsafeRead> swizzle_data",
    "#ifdef PS5_NATIVE\n"
    "    // UnswizzleImage writes each copy's destination bytes before ConvertImage\n"
    "    // reads them. Avoid zero-filling the entire intermediate texture under\n"
    "    // the texture-cache mutex; the move-only scratch buffer is accepted by\n"
    "    // Common::UniqueFunction in the asynchronous decode worker queue.\n"
    "    Common::ScratchBuffer<u8> local_unswizzle_data_buffer;\n"
    "    local_unswizzle_data_buffer.resize_destructive(image.unswizzled_size_bytes);\n"
    "#else\n"
    "    std::vector<u8> local_unswizzle_data_buffer(image.unswizzled_size_bytes, 0);\n"
    "#endif\n"
    "    Tegra::Memory::GpuGuestMemory<u8, Tegra::Memory::GuestMemoryFlags::UnsafeRead> swizzle_data",
    "F07 avoid zero-filling native asynchronous texture decode input")

# F07: Vulkan forbids VkBufferCopy.size==0. Filter empty regions in
# one pass before recording native GPU uploads; preserve relative copy order
# and the standalone barriers if the entire batch was filtered out.
apply_reviewed_delta("vk_buffer_cache_cost.cpp",
    "    boost::container::small_vector<VkBufferCopy, 8> vk_copies(copies.size());\n"
    "    std::ranges::transform(copies, vk_copies.begin(), MakeBufferCopy);",
    "#ifdef PS5_NATIVE\n"
    "    // Zero-sized VkBufferCopy regions are invalid Vulkan commands. Build the\n"
    "    // batch in one pass, retaining order and the original barrier contract.\n"
    "    boost::container::small_vector<VkBufferCopy, 8> vk_copies;\n"
    "    vk_copies.reserve(copies.size());\n"
    "    for (const auto& copy : copies) {\n"
    "        if (copy.size != 0) {\n"
    "            vk_copies.push_back(MakeBufferCopy(copy));\n"
    "        }\n"
    "    }\n"
    "    if (vk_copies.empty()) {\n"
    "        if (barrier) {\n"
    "            PreCopyBarrier();\n"
    "            PostCopyBarrier();\n"
    "        }\n"
    "        return;\n"
    "    }\n"
    "#else\n"
    "    boost::container::small_vector<VkBufferCopy, 8> vk_copies(copies.size());\n"
    "    std::ranges::transform(copies, vk_copies.begin(), MakeBufferCopy);\n"
    "#endif",
    "F07 reject zero-sized Vulkan buffer copy regions")

# F07: a source staging buffer eligible for the upload command buffer can
# still carry an explicit read/write barrier. Its barriers only exist on the
# ordered graphics/compute path; do not silently reorder such copies on PS5.
apply_reviewed_delta("vk_buffer_cache_cost.cpp",
    "    if (src_buffer == staging_pool.StreamBuf() && can_reorder_upload) {\n"
    "        scheduler.RecordWithUploadBuffer(",
    "#ifdef PS5_NATIVE\n"
    "    // An explicit transfer barrier cannot be represented by the reordered\n"
    "    // upload queue. Keep its copy and synchronization in the ordered stream.\n"
    "    if (src_buffer == staging_pool.StreamBuf() && can_reorder_upload && !barrier) {\n"
    "#else\n"
    "    if (src_buffer == staging_pool.StreamBuf() && can_reorder_upload) {\n"
    "#endif\n"
    "        scheduler.RecordWithUploadBuffer(",
    "F07 preserve explicit barriers when deciding native staging upload reordering")

# F07: mapped staging without a real Vulkan buffer is invalid even when
# its CPU span is large enough. Reject buffer-cache DMA/index/readback uploads
# before recording GPU copies; return rejected deferred staging to the pool.
# Desktop keeps pinned behavior.
apply_reviewed_delta("vk_buffer_cache_cost.cpp",
    "#include <cstring>\n#include <span>",
    "#include <cstring>\n#include <new>\n#include <span>",
    "F07 include buffer cache staging allocation exception")
apply_reviewed_delta("vk_buffer_cache_cost.cpp",
    "StagingBufferRef BufferCacheRuntime::UploadStagingBuffer(size_t size) {\n"
    "    return staging_pool.Request(size, MemoryUsage::Upload);\n"
    "}\n"
    "\n"
    "StagingBufferRef BufferCacheRuntime::DownloadStagingBuffer(size_t size, bool deferred) {\n"
    "    return staging_pool.Request(size, MemoryUsage::Download, deferred);\n"
    "}",
    "StagingBufferRef BufferCacheRuntime::UploadStagingBuffer(size_t size) {\n"
    "#ifdef PS5_NATIVE\n"
    "    auto map = staging_pool.Request(size, MemoryUsage::Upload);\n"
    "    // A mapped CPU span alone does not prove a valid Vulkan buffer handle.\n"
    "    if (size != 0 && (!map.buffer || map.mapped_span.size_bytes() < size)) {\n"
    "        throw std::bad_alloc{};\n"
    "    }\n"
    "    return map;\n"
    "#else\n"
    "    return staging_pool.Request(size, MemoryUsage::Upload);\n"
    "#endif\n"
    "}\n"
    "\n"
    "StagingBufferRef BufferCacheRuntime::DownloadStagingBuffer(size_t size, bool deferred) {\n"
    "#ifdef PS5_NATIVE\n"
    "    auto map = staging_pool.Request(size, MemoryUsage::Download, deferred);\n"
    "    if (size != 0 && (!map.buffer || map.mapped_span.size_bytes() < size)) {\n"
    "        if (deferred && map.buffer) staging_pool.FreeDeferred(map);\n"
    "        throw std::bad_alloc{};\n"
    "    }\n"
    "    return map;\n"
    "#else\n"
    "    return staging_pool.Request(size, MemoryUsage::Download, deferred);\n"
    "#endif\n"
    "}",
    "F07 validate native upload and download buffer cache staging handles")
# F07: transform-feedback descriptors come from guest state and can be empty
# or partially reset after an unbind. Never record a zero-count Vulkan bind,
# overrun the inline static_vector, or index a missing offset/size on PS5.
apply_reviewed_delta("vk_buffer_cache_cost.cpp",
    "    boost::container::static_vector<VkBuffer, VideoCommon::NUM_VERTEX_BUFFERS> buffer_handles(bindings.buffers.size());", "#ifdef PS5_NATIVE\n    // The guest may unbind transform feedback entirely or supply an invalid\n    // binding table. Do not record a zero-count Vulkan command, construct an\n    // over-capacity static_vector or read a missing offset/size under cache locks.\n    const size_t binding_count = bindings.buffers.size();\n    if (binding_count == 0 || binding_count > VideoCommon::NUM_VERTEX_BUFFERS ||\n        bindings.offsets.size() < binding_count ||\n        bindings.sizes.size() < binding_count) {\n        return;\n    }\n#endif\n    boost::container::static_vector<VkBuffer, VideoCommon::NUM_VERTEX_BUFFERS> buffer_handles(bindings.buffers.size());",
    "F07 reject malformed native transform-feedback binding arrays")
# F07: a lost/null guest index buffer uses the four-byte substitute. Keep its
# offset inside that substitute, like the existing null vertex/TFB bindings.
apply_reviewed_delta("vk_buffer_cache_cost.cpp",
    "    if (vk_buffer == VK_NULL_HANDLE) {\n        // Vulkan doesn't support null index buffers. Replace it with our own null buffer.\n        ReserveNullBuffer();\n        vk_buffer = *null_buffer;\n    }", "    if (vk_buffer == VK_NULL_HANDLE) {\n        // Vulkan doesn't support null index buffers. Replace it with our own null buffer.\n        ReserveNullBuffer();\n        vk_buffer = *null_buffer;\n#ifdef PS5_NATIVE\n        // The fallback buffer is only four bytes. A stale guest index\n        // offset must not survive the handle substitution or Vulkan may\n        // bind beyond that allocation (same rule as null vertex/TFB).\n        vk_offset = 0;\n#endif\n    }",
    "F07 reset native null index fallback byte offset")



# F07 P0.3: empty sampled/storage image descriptor batches only reset
# the deletion retry latch. Avoid constructing the TIC memo under paired GPU
# locks when the descriptor span is empty. Preserve desktop original loop.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "void TextureCache<P>::FillImageViews(std::span<ImageViewInOut> views, bool compute, bool blacklist) {\n"
    "    bool has_blacklisted = false;",
    "void TextureCache<P>::FillImageViews(std::span<ImageViewInOut> views, bool compute, bool blacklist) {\n"
    "#ifdef PS5_NATIVE\n"
    "    // The empty descriptor pass only clears the deletion/retry latch.\n"
    "    // Avoid initializing the draw-local TIC memo and entering the retry\n"
    "    // loop when no view can possibly be visited or blacklisted.\n"
    "    if (views.empty()) {\n"
    "        has_deleted_images = false;\n"
    "        return;\n"
    "    }\n"
    "#endif\n"
    "    bool has_blacklisted = false;",
    "F07 bypass draw-local texture memo on empty image descriptor batches")

# F07 P0.4: no pending async HUD decodes means no frame-local staging,
# semaphore/barrier or completion scanning. Keep desktop source unchanged.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "void TextureCache<P>::TickAsyncDecode() {\n"
    "    bool has_uploads{};",
    "void TextureCache<P>::TickAsyncDecode() {\n"
    "#ifdef PS5_NATIVE\n"
    "    // Usually no async decode is pending. Skip frame-local upload tracking\n"
    "    // and completion machinery entirely until the worker queues a context.\n"
    "    if (async_decodes.empty()) {\n"
    "        return;\n"
    "    }\n"
    "#endif\n"
    "    bool has_uploads{};",
    "F07 skip idle native async texture decode completion machinery")

# F07 P0.4: a zero-region image upload cannot alter a texture.
# Native PS5 skips resolve invalidation, MSAA scratch, rescale and command
# recording entirely; desktop retains its historical behavior.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "void Image::UploadMemory(VkBuffer buffer, VkDeviceSize offset,\n"
    "                         std::span<const VideoCommon::BufferImageCopy> copies) {\n"
    "    // TODO: Move this to another API",
    "void Image::UploadMemory(VkBuffer buffer, VkDeviceSize offset,\n"
    "                         std::span<const VideoCommon::BufferImageCopy> copies) {\n"
    "#ifdef PS5_NATIVE\n"
    "    // Empty guest upload regions cannot write any destination pixels. Avoid\n"
    "    // invalidating a valid MSAA resolve, rescaling, scratch acquisition and\n"
    "    // a Vulkan command with no copy regions.\n"
    "    if (copies.empty()) {\n"
    "        return;\n"
    "    }\n"
    "#endif\n"
    "    // TODO: Move this to another API",
    "F07 avoid empty native image upload and unnecessary MSAA resolve invalidation")

# F07 P0.4: texture reinterpret bpp conversion precedes scratch validation.
# Keep native scalar coordinates wide until the signed offset/unsigned Vk
# extent fit checks, and reject unknown zero-sized block ratios early.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "    const auto bpp_in = BytesPerBlock(src.info.format) / DefaultBlockWidth(src.info.format);\n    const auto bpp_out = BytesPerBlock(dst.info.format) / DefaultBlockWidth(dst.info.format);\n    std::ranges::transform(copies, vk_in_copies.begin(),\n                           [src_aspect_mask, bpp_in, bpp_out](const auto& copy) {\n                               auto copy2 = copy;\n                               copy2.src_offset.x = (bpp_out * copy.src_offset.x) / bpp_in;\n                               copy2.extent.width = (bpp_out * copy.extent.width) / bpp_in;\n                               return MakeBufferImageCopy(copy2, true, src_aspect_mask);\n                           });",
    "#ifdef PS5_NATIVE\n    // Do not divide by an invalid format width or truncate converted source\n    // coordinates before the scratch-size check. Conversion is calculated\n    // wide, but must still fit the signed offset and unsigned Vk extent.\n    const auto src_block_width = DefaultBlockWidth(src.info.format);\n    const auto dst_block_width = DefaultBlockWidth(dst.info.format);\n    if (src_block_width == 0 || dst_block_width == 0) {\n        return;\n    }\n    const auto bpp_in = BytesPerBlock(src.info.format) / src_block_width;\n    const auto bpp_out = BytesPerBlock(dst.info.format) / dst_block_width;\n    if (bpp_in == 0 || bpp_out == 0) {\n        return;\n    }\n    for (const auto& copy : copies) {\n        if (static_cast<s64>(copy.src_offset.x) < 0) {\n            return;\n        }\n        const u64 scaled_offset =\n            (static_cast<u64>(bpp_out) * static_cast<u64>(copy.src_offset.x)) / bpp_in;\n        const u64 scaled_width =\n            (static_cast<u64>(bpp_out) * copy.extent.width) / bpp_in;\n        if (scaled_offset > static_cast<u64>(\n                (std::numeric_limits<decltype(copy.src_offset.x)>::max)()) ||\n            scaled_width == 0 || scaled_width > static_cast<u64>(\n                (std::numeric_limits<decltype(copy.extent.width)>::max)())) {\n            return;\n        }\n    }\n#else\n    const auto bpp_in = BytesPerBlock(src.info.format) / DefaultBlockWidth(src.info.format);\n    const auto bpp_out = BytesPerBlock(dst.info.format) / DefaultBlockWidth(dst.info.format);\n#endif\n    std::ranges::transform(copies, vk_in_copies.begin(),\n                           [src_aspect_mask, bpp_in, bpp_out](const auto& copy) {\n                               auto copy2 = copy;\n#ifdef PS5_NATIVE\n                               copy2.src_offset.x = static_cast<decltype(copy2.src_offset.x)>(\n                                   (static_cast<u64>(bpp_out) * static_cast<u64>(copy.src_offset.x)) / bpp_in);\n                               copy2.extent.width = static_cast<decltype(copy2.extent.width)>(\n                                   (static_cast<u64>(bpp_out) * copy.extent.width) / bpp_in);\n#else\n                               copy2.src_offset.x = (bpp_out * copy.src_offset.x) / bpp_in;\n                               copy2.extent.width = (bpp_out * copy.extent.width) / bpp_in;\n#endif\n                               return MakeBufferImageCopy(copy2, true, src_aspect_mask);\n                           });",
    "F07 validate native reinterpret pixel ratios before coordinate conversion")

# F07: a collapsed Vulkan blit has no valid image pixels and must
# not lock/dispatch any color or MSAA helper pipeline on native PS5.
# Preserve the desktop path and inverted nonzero rectangles.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "void TextureCacheRuntime::BlitImage(Framebuffer* dst_framebuffer, ImageView& dst, ImageView& src,\n"
    "                                    const Region2D& dst_region, const Region2D& src_region,\n"
    "                                    Tegra::Engines::Fermi2D::Filter filter,\n"
    "                                    Tegra::Engines::Fermi2D::Operation operation) {\n"
    "    const VkImageAspectFlags aspect_mask = ImageAspectMask(src.format);",
    "void TextureCacheRuntime::BlitImage(Framebuffer* dst_framebuffer, ImageView& dst, ImageView& src,\n"
    "                                    const Region2D& dst_region, const Region2D& src_region,\n"
    "                                    Tegra::Engines::Fermi2D::Filter filter,\n"
    "                                    Tegra::Engines::Fermi2D::Operation operation) {\n"
    "#ifdef PS5_NATIVE\n"
    "    // A collapsed source or destination axis cannot transfer image pixels.\n"
    "    // Keep flipped blits (reversed, nonempty coordinates) fully supported.\n"
    "    if (dst_region.start.x == dst_region.end.x ||\n"
    "        dst_region.start.y == dst_region.end.y ||\n"
    "        src_region.start.x == src_region.end.x ||\n"
    "        src_region.start.y == src_region.end.y) {\n"
    "        return;\n"
    "    }\n"
    "#endif\n"
    "    const VkImageAspectFlags aspect_mask = ImageAspectMask(src.format);",
    "F07 skip zero-area native Vulkan image blits")

# F07: CopyImage can delegate a size-incompatible copy to ReinterpretImage,
# which rejects invalid staging before changing destination pixels. The outer
# copy must not invalidate the MSAA resolve first; the delegated method owns
# invalidation after successful scratch admission. Desktop stays unchanged.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "void TextureCacheRuntime::CopyImage(Image& dst, Image& src,\n"
    "                                    std::span<const VideoCommon::ImageCopy> copies) {\n"
    "    if (ENABLE_MSAA_RESOLVE_CONSUME) {\n"
    "        InvalidateResolveShadow(dst.Handle());\n"
    "    }",
    "void TextureCacheRuntime::CopyImage(Image& dst, Image& src,\n"
    "                                    std::span<const VideoCommon::ImageCopy> copies) {\n"
    "#ifdef PS5_NATIVE\n"
    "    // ReinterpretImage owns invalidation after validating its copy and scratch\n"
    "    // buffer. Do not stale the old MSAA resolve when it rejects the operation.\n"
    "    if (ENABLE_MSAA_RESOLVE_CONSUME &&\n"
    "        BytesPerBlock(src.info.format) == BytesPerBlock(dst.info.format)) {\n"
    "        InvalidateResolveShadow(dst.Handle());\n"
    "    }\n"
    "#else\n"
    "    if (ENABLE_MSAA_RESOLVE_CONSUME) {\n"
    "        InvalidateResolveShadow(dst.Handle());\n"
    "    }\n"
    "#endif",
    "F07 preserve resolve validity on rejected size-incompatible CopyImage")

# F07: a zero-region, size-compatible image copy is a true no-op.
# Skip invalidating the MSAA resolve and enqueuing an empty Vulkan barrier.
# Size-incompatible calls construct a whole-image region even if copies is empty.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "void TextureCacheRuntime::CopyImage(Image& dst, Image& src,\n"
    "                                    std::span<const VideoCommon::ImageCopy> copies) {\n"
    "#ifdef PS5_NATIVE\n"
    "    // ReinterpretImage owns invalidation",
    "void TextureCacheRuntime::CopyImage(Image& dst, Image& src,\n"
    "                                    std::span<const VideoCommon::ImageCopy> copies) {\n"
    "#ifdef PS5_NATIVE\n"
    "    // A compatible-format copy with zero regions records no image writes.\n"
    "    // Preserve the resolved shadow and avoid an empty Vulkan command batch.\n"
    "    // Size-INcompatible calls still reinterpret the whole image independently\n"
    "    // of the supplied region list, so they must not take this return.\n"
    "    if (copies.empty() &&\n"
    "        BytesPerBlock(src.info.format) == BytesPerBlock(dst.info.format)) {\n"
    "        return;\n"
    "    }\n"
    "    // ReinterpretImage owns invalidation",
    "F07 skip empty size-compatible native Vulkan CopyImage without stale resolve")

# F07 P0.1/P0.3: DrawTexture uses a self-contained raw blit pipeline.
# On native PS5 its UpdateDynamicStates call previously queried a cold guest
# graphics pipeline UNDER texture_cache.mutex, translating a shader that the
# blit will never use. Guest PrepareDraw already selects the real pipeline
# before taking paired cache locks; it alone needs dynamic vertex state.
# Leave desktop behavior unchanged and keep all non-vertex states intact.
apply_reviewed_delta("vulkan_rasterizer.cpp",
    "    if (device.IsExtVertexInputDynamicStateSupported()) {\n"
    "        if (auto* gp = prepared_pipeline ? prepared_pipeline : pipeline_cache.CurrentGraphicsPipeline();\n"
    "            gp && gp->HasDynamicVertexInput()) {\n"
    "            UpdateVertexInput(regs);\n"
    "        }\n"
    "    }",
    "    if (device.IsExtVertexInputDynamicStateSupported()) {\n"
    "#ifdef PS5_NATIVE\n"
    "        // DrawTexture uses its own blit pipeline, not a guest graphics\n"
    "        // pipeline. Do not translate a cold guest shader while holding the\n"
    "        // texture-cache lock just to set unused vertex input state. The next\n"
    "        // guest PrepareDraw has prepared_pipeline and will bind it normally.\n"
    "        if (prepared_pipeline && prepared_pipeline->HasDynamicVertexInput()) {\n"
    "            UpdateVertexInput(regs);\n"
    "        }\n"
    "#else\n"
    "        if (auto* gp = prepared_pipeline ? prepared_pipeline : pipeline_cache.CurrentGraphicsPipeline();\n"
    "            gp && gp->HasDynamicVertexInput()) {\n"
    "            UpdateVertexInput(regs);\n"
    "        }\n"
    "#endif\n"
    "    }",
    "F07 bypass cold guest graphics shader lookup in native raw DrawTexture")

# F07: empty MSAA copies are true no-ops; the helper's GPU pipeline
# dispatch cannot mutate any destination pixels with no copy regions.
# Preserve desktop's original path for source parity and diagnostics.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "void TextureCacheRuntime::CopyImageMSAA(Image& dst, Image& src,\n"
    "                                        std::span<const VideoCommon::ImageCopy> copies) {\n"
    "    const bool msaa_to_non_msaa = src.info.num_samples > 1 && dst.info.num_samples == 1;",
    "void TextureCacheRuntime::CopyImageMSAA(Image& dst, Image& src,\n"
    "                                        std::span<const VideoCommon::ImageCopy> copies) {\n"
    "#ifdef PS5_NATIVE\n"
    "    // A zero-region MSAA transfer cannot write any pixels. Avoid building\n"
    "    // depth/color helper pipelines and recording a useless Vulkan batch.\n"
    "    if (copies.empty()) {\n"
    "        return;\n"
    "    }\n"
    "#endif\n"
    "    const bool msaa_to_non_msaa = src.info.num_samples > 1 && dst.info.num_samples == 1;",
    "F07 skip empty native MSAA image copies before helper GPU dispatch")

# F07 P0.4: on PS5, a zero/invalid texture reinterpret must not mark the
# existing MSAA resolve shadow stale. Move invalidation after scratch allocation
# and bounds checks, retaining it before the actual Vulkan command recording.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "    if (ENABLE_MSAA_RESOLVE_CONSUME) {\n        InvalidateResolveShadow(dst.Handle());\n    }\n    boost::container::small_vector<VkBufferImageCopy, 16> vk_in_copies(copies.size());",
    "#ifndef PS5_NATIVE\n    if (ENABLE_MSAA_RESOLVE_CONSUME) {\n        InvalidateResolveShadow(dst.Handle());\n    }\n#endif\n    boost::container::small_vector<VkBufferImageCopy, 16> vk_in_copies(copies.size());",
    "F07 defer native reinterpret resolve invalidation until valid allocation")
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "    const VkBuffer copy_buffer = GetTemporaryBuffer(total_size);\n    const VkImage dst_image = dst.Handle();",
    "    const VkBuffer copy_buffer = GetTemporaryBuffer(total_size);\n#ifdef PS5_NATIVE\n    // A rejected reinterpretation does not alter the destination image.\n    // Invalidate its resolved shadow only after native validation and\n    // scratch allocation succeeded, before submitting Vulkan commands.\n    if (ENABLE_MSAA_RESOLVE_CONSUME) {\n        InvalidateResolveShadow(dst.Handle());\n    }\n#endif\n    const VkImage dst_image = dst.Handle();",
    "F07 invalidate native reinterpret resolve after scratch allocation")

# F07 P0.3: under the GPU cache lock, a deferred GC readback may receive a
# short/failed staging allocation. Do not publish that as copied guest data:
# release a partial deferred map and stop speculative admission while leaving
# the authoritative Cleanup path, its GPU Finish and eviction order unchanged.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "                auto map = runtime.DownloadStagingBuffer(image.unswizzled_size_bytes, true);\n                // The pinned StagingBufferRef is a POD handle, not a RAII",
    "#ifdef PS5_NATIVE\n                // A short staging map or an allocation failure is NOT a GPU\n                // copy. Do not record a readback into unmapped memory or\n                // advertise it to Cleanup as prefetched. The ordinary\n                // eviction path may retry after the staged batch finishes.\n                auto map = [&]() -> decltype(runtime.DownloadStagingBuffer(image.unswizzled_size_bytes, true)) {\n                    try {\n                        return runtime.DownloadStagingBuffer(image.unswizzled_size_bytes, true);\n                    } catch (...) {\n                        return {};\n                    }\n                }();\n                if (!map.buffer || map.mapped_span.size_bytes() < image.unswizzled_size_bytes) {\n                    if (map.buffer) runtime.FreeDeferredStagingBuffer(map);\n                    return true;\n                }\n#else\n                auto map = runtime.DownloadStagingBuffer(image.unswizzled_size_bytes, true);\n#endif\n                // The pinned StagingBufferRef is a POD handle, not a RAII",
    "F07 reject failed or undersized dirty GC prefetch staging")

# F07 P0.4: the authoritative dirty-image GC fallback cannot discard guest
# pixels when a short or rejected Vulkan staging download is returned.
# Preserve other clean eviction opportunities and the existing GPU Finish.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if (must_download && !UsePrefetched(image_id, image)) {\n            auto map = runtime.DownloadStagingBuffer(image.unswizzled_size_bytes);\n            const auto copies = FixSmallVectorADL(FullDownloadCopies(image.info));",
    "        if (must_download && !UsePrefetched(image_id, image)) {\n#ifdef PS5_NATIVE\n            // Never evict dirty GPU bytes if the fallback guest readback could\n            // not obtain a COMPLETE staging mapping under memory pressure.\n            auto map = [&]() -> decltype(runtime.DownloadStagingBuffer(image.unswizzled_size_bytes)) {\n                try {\n                    return runtime.DownloadStagingBuffer(image.unswizzled_size_bytes);\n                } catch (const std::bad_alloc&) {\n                    return {};\n                }\n            }();\n            if (!map.buffer || map.mapped_span.size_bytes() < image.unswizzled_size_bytes) {\n                ++skipped;\n                return false;\n            }\n#else\n            auto map = runtime.DownloadStagingBuffer(image.unswizzled_size_bytes);\n#endif\n            const auto copies = FixSmallVectorADL(FullDownloadCopies(image.info));",
    "F07 leave dirty GPU image resident on failed cleanup readback")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "#include <limits>\n#include <optional>",
    "#include <limits>\n#ifdef PS5_NATIVE\n#include <new>\n#endif\n#include <optional>",
    "F07 declare bad alloc for native dirty GC rollback")


# F07 P0.4: an authoritative DownloadMemory failure must not leave the
# guest-visible GPU-dirty bit cleared, including after partial readbacks.
# Keep the historical Vulkan batching oracle byte-identical.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    boost::container::small_vector<ImageId, 16> images;\n    ForEachImageInRegion(cpu_addr, size, [this, &images](ImageId image_id, ImageBase& image) {\n        if (!IsDownloadable(image)) {\n            return;\n        }\n        image.flags &= ~ImageFlagBits::GpuModified;\n        images.push_back(image_id);\n    });",
    "    boost::container::small_vector<ImageId, 16> images;\n#ifdef PS5_NATIVE\n    // DownloadMemory can fail after clearing GPU-dirty state but before guest\n    // pixels are published. Restore every touched image on unwinding, even\n    // when an earlier staged image was already copied successfully.\n    const int uncaught_before_readback = std::uncaught_exceptions();\n    SCOPE_EXIT {\n        if (std::uncaught_exceptions() > uncaught_before_readback) {\n            for (const ImageId id : images) {\n                slot_images[id].flags |= ImageFlagBits::GpuModified;\n            }\n        }\n    };\n#endif\n    ForEachImageInRegion(cpu_addr, size, [this, &images](ImageId image_id, ImageBase& image) {\n        if (!IsDownloadable(image)) {\n            return;\n        }\n#ifdef PS5_NATIVE\n        // The list can allocate: track the image BEFORE clearing its flag.\n        images.push_back(image_id);\n        image.flags &= ~ImageFlagBits::GpuModified;\n#else\n        image.flags &= ~ImageFlagBits::GpuModified;\n        images.push_back(image_id);\n#endif\n    });",
    "F07 restore GPU dirty image flags on readback exception")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "#ifdef PS5_NATIVE\n#include <new>",
    "#ifdef PS5_NATIVE\n#include <exception>\n#include <new>",
    "F07 include uncaught exception counter for readback rollback")

# F07 P0.4: validate readback staging at the runtime boundary; keep the
# historical 40-image batch oracle byte-for-byte unchanged.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "StagingBufferRef TextureCacheRuntime::DownloadStagingBuffer(size_t size, bool deferred) {\n    return staging_buffer_pool.Request(size, MemoryUsage::Download, deferred);\n}",
    "StagingBufferRef TextureCacheRuntime::DownloadStagingBuffer(size_t size, bool deferred) {\n#ifdef PS5_NATIVE\n    // Reject broken readback staging before the pinned batch can record copies.\n    // Never trust a mapped CPU span without a real Vulkan buffer handle.\n    auto map = staging_buffer_pool.Request(size, MemoryUsage::Download, deferred);\n    if (!map.buffer || map.mapped_span.size_bytes() < size) {\n        if (deferred && map.buffer) staging_buffer_pool.FreeDeferred(map);\n        throw std::bad_alloc{};\n    }\n    return map;\n#else\n    return staging_buffer_pool.Request(size, MemoryUsage::Download, deferred);\n#endif\n}",
    "F07 reject invalid Vulkan guest readback staging in runtime")
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "#include <memory>\n#include <utility>",
    "#include <memory>\n#ifdef PS5_NATIVE\n#include <new>\n#endif\n#include <utility>",
    "F07 add explicit PS5 native bad_alloc header for staging readback")

# F07 P0.4: a rejected Vulkan DMA staging request or command submission must
# unwind the async buffer slot and request queue in the correct reverse order.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        const BufferDownload new_buffer_download{address, size};\n        auto slot = slot_buffer_downloads.insert(new_buffer_download);\n        const PendingDownload new_download{false, uncommitted_async_buffers.size(), slot};\n        uncommitted_downloads.emplace_back(new_download);\n        auto download_map = runtime.DownloadStagingBuffer(size, true);\n        uncommitted_async_buffers.emplace_back(download_map);\n        std::array buffers{\n            buffer,\n            download_map.buffer,\n        };\n        std::array<size_t, 2> buffer_offsets{\n            buffer_offset,\n            download_map.offset,\n        };\n        image->DownloadMemory(buffers, buffer_offsets, copies);",
    "        const BufferDownload new_buffer_download{address, size};\n        auto slot = slot_buffer_downloads.insert(new_buffer_download);\n#ifdef PS5_NATIVE\n        // If staging or command submission fails, the DMA must not remain\n        // registered as a completed/pending guest-memory download.\n        bool pending_recorded = false;\n        bool staging_recorded = false;\n        bool download_submitted = false;\n        SCOPE_EXIT {\n            if (!download_submitted) {\n                if (staging_recorded) {\n                    runtime.FreeDeferredStagingBuffer(uncommitted_async_buffers.back());\n                    uncommitted_async_buffers.pop_back();\n                }\n                if (pending_recorded) uncommitted_downloads.pop_back();\n                slot_buffer_downloads.erase(slot);\n            }\n        };\n#endif\n        const PendingDownload new_download{false, uncommitted_async_buffers.size(), slot};\n        uncommitted_downloads.emplace_back(new_download);\n#ifdef PS5_NATIVE\n        pending_recorded = true;\n#endif\n        auto download_map = runtime.DownloadStagingBuffer(size, true);\n#ifdef PS5_NATIVE\n        try {\n            uncommitted_async_buffers.emplace_back(download_map);\n        } catch (...) {\n            // A non-owning staging handle still needs a deferred pool return.\n            runtime.FreeDeferredStagingBuffer(download_map);\n            throw;\n        }\n        staging_recorded = true;\n#else\n        uncommitted_async_buffers.emplace_back(download_map);\n#endif\n        std::array buffers{\n            buffer,\n            download_map.buffer,\n        };\n        std::array<size_t, 2> buffer_offsets{\n            buffer_offset,\n            download_map.offset,\n        };\n        image->DownloadMemory(buffers, buffer_offsets, copies);\n#ifdef PS5_NATIVE\n        download_submitted = true;\n#endif",
    "F07 rollback asynchronous DMA slot and staging on failed guest readback")

# F07 P0.4: deferred staging remains owned by the local async-flush batch
# until it is successfully placed in the committed buffer queue.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if (any_none_dma) {\n            auto download_map = runtime.DownloadStagingBuffer(total_size_bytes, true);\n            for (const PendingDownload& download_info : download_ids) {\n                if (download_info.is_swizzle) {\n                    Image& image = slot_images[download_info.object_id];\n                    const auto copies = FixSmallVectorADL(FullDownloadCopies(image.info));\n                    image.DownloadMemory(download_map, copies);\n                    download_map.offset += Common::AlignUp(image.unswizzled_size_bytes, 64);\n                }\n            }\n            uncommitted_async_buffers.emplace_back(download_map);\n        }",
    "        if (any_none_dma) {\n            auto download_map = runtime.DownloadStagingBuffer(total_size_bytes, true);\n#ifdef PS5_NATIVE\n            // The pinned staging handle does not own its pool reservation.\n            // If command recording or queue growth fails, keep this buffer\n            // GPU-safe in the deferred pool and leave the commit retryable.\n            bool staging_transferred = false;\n            SCOPE_EXIT {\n                if (!staging_transferred) runtime.FreeDeferredStagingBuffer(download_map);\n            };\n#endif\n            for (const PendingDownload& download_info : download_ids) {\n                if (download_info.is_swizzle) {\n                    Image& image = slot_images[download_info.object_id];\n                    const auto copies = FixSmallVectorADL(FullDownloadCopies(image.info));\n                    image.DownloadMemory(download_map, copies);\n                    download_map.offset += Common::AlignUp(image.unswizzled_size_bytes, 64);\n                }\n            }\n            uncommitted_async_buffers.emplace_back(download_map);\n#ifdef PS5_NATIVE\n            staging_transferred = true;\n#endif\n        }",
    "F07 return deferred staging when async flush batch preparation fails")

# F07 P0.4: publish async downloads and their staging buffers atomically on PS5.
# Keep native retryable on an exception from the second queue and return only
# the newly-created swizzle staging; preserve earlier queued DMA sources.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if (download_ids.empty()) {\n            committed_downloads.emplace_back(std::move(uncommitted_downloads));\n            uncommitted_downloads.clear();\n            async_buffers.emplace_back(std::move(uncommitted_async_buffers));\n            uncommitted_async_buffers.clear();\n            return;\n        }\n        size_t total_size_bytes = 0;",
    "        if (download_ids.empty()) {\n#ifndef PS5_NATIVE\n            committed_downloads.emplace_back(std::move(uncommitted_downloads));\n            uncommitted_downloads.clear();\n            async_buffers.emplace_back(std::move(uncommitted_async_buffers));\n            uncommitted_async_buffers.clear();\n            return;\n#endif\n            // Native empty batches use the same atomic pair-publication below.\n        }\n#ifdef PS5_NATIVE\n        // Already-enqueued DMA staging belongs to its existing pending slots.\n        // Only the extra swizzle batch allocated below may be discarded on\n        // failed publication; never lose or duplicate earlier DMA reservations.\n        const size_t initial_staging_count = uncommitted_async_buffers.size();\n        bool batch_published = false;\n        SCOPE_EXIT {\n            if (!batch_published) {\n                while (uncommitted_async_buffers.size() > initial_staging_count) {\n                    runtime.FreeDeferredStagingBuffer(uncommitted_async_buffers.back());\n                    uncommitted_async_buffers.pop_back();\n                }\n            }\n        };\n#endif\n        size_t total_size_bytes = 0;",
    "F07 preserve prior async DMA staging during failed pair publication")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        async_buffers.emplace_back(std::move(uncommitted_async_buffers));\n        uncommitted_async_buffers.clear();\n    }\n    committed_downloads.emplace_back(std::move(uncommitted_downloads));\n    uncommitted_downloads.clear();",
    "#ifdef PS5_NATIVE\n        // Publish the buffers and their identifiers as one logical pair.\n        // A rejected second deque insertion must restore the first queue\n        // before allowing another batch to reuse these staging indices.\n        async_buffers.emplace_back(std::move(uncommitted_async_buffers));\n        try {\n            committed_downloads.emplace_back(std::move(uncommitted_downloads));\n        } catch (...) {\n            uncommitted_async_buffers = std::move(async_buffers.back());\n            async_buffers.pop_back();\n            throw;\n        }\n        batch_published = true;\n        uncommitted_async_buffers.clear();\n        uncommitted_downloads.clear();\n        return;\n#else\n        async_buffers.emplace_back(std::move(uncommitted_async_buffers));\n        uncommitted_async_buffers.clear();\n#endif\n    }\n    committed_downloads.emplace_back(std::move(uncommitted_downloads));\n    uncommitted_downloads.clear();",
    "F07 rollback async download queue pair on second insertion failure")

# F07 P0.4: drain orphanable deferred staging in empty async batches.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if (download_ids.empty()) {\n            committed_downloads.pop_front();\n            async_buffers.pop_front();\n            return;\n        }",
    "        if (download_ids.empty()) {\n#ifdef PS5_NATIVE\n            // An empty async batch can still own deferred staging handles\n            // after an interrupted DMA or an empty pair publication.\n            // StagingBufferRef is non-owning: dequeueing it is not a free.\n            for (auto& buffer : async_buffers.front()) {\n                runtime.FreeDeferredStagingBuffer(buffer);\n            }\n#endif\n            committed_downloads.pop_front();\n            async_buffers.pop_front();\n            return;\n        }",
    "F07 release deferred staging from empty async download batch")

# F07 P0.4: reject async readback batches whose 64-byte aligned size
# would overflow before allocating or recording GPU copies.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "            if (download_info.is_swizzle) {\n                total_size_bytes +=\n                    Common::AlignUp(slot_images[download_info.object_id].unswizzled_size_bytes, 64);\n                any_none_dma = true;\n                download_info.async_buffer_id = last_async_buffer_id;\n            }",
    "            if (download_info.is_swizzle) {\n#ifdef PS5_NATIVE\n                // Both 64-byte alignment and batch accumulation must fit in\n                // size_t BEFORE staging allocation. An overflow would make a\n                // mapped buffer look large enough for a smaller, wrapped batch.\n                const size_t bytes = slot_images[download_info.object_id].unswizzled_size_bytes;\n                constexpr size_t max_bytes = (std::numeric_limits<size_t>::max)();\n                if (bytes > max_bytes - 63) {\n                    throw std::bad_alloc{};\n                }\n                const size_t aligned_bytes = Common::AlignUp(bytes, size_t{64});\n                if (aligned_bytes > max_bytes - total_size_bytes) {\n                    throw std::bad_alloc{};\n                }\n                total_size_bytes += aligned_bytes;\n#else\n                total_size_bytes +=\n                    Common::AlignUp(slot_images[download_info.object_id].unswizzled_size_bytes, 64);\n#endif\n                any_none_dma = true;\n                download_info.async_buffer_id = last_async_buffer_id;\n            }",
    "F07 guard overflow before async swizzle staging allocation")

# F07 P0.3: stabilize legacy texel-view descriptor snapshots on PS5; avoid
# false memcmp misses and redundant driver descriptor uploads on HUD draws.
apply_reviewed_delta("include/video_core/renderer_vulkan/vk_update_descriptor.h",
    "    void AddTexelBuffer(VkBufferView texel_buffer) {\n        *(payload_cursor++) = texel_buffer;\n    }",
    "    void AddTexelBuffer(VkBufferView texel_buffer) {\n#ifdef PS5_NATIVE\n        // Descriptor snapshots are compared byte-for-byte on later draws.\n        // A texel view fills only the first union field: stale padding from\n        // a previous descriptor otherwise defeats payload reuse on the HUD.\n        auto* const entry = payload_cursor++;\n        std::memset(entry, 0, sizeof(*entry));\n        entry->texel_buffer = texel_buffer;\n#else\n        *(payload_cursor++) = texel_buffer;\n#endif\n    }",
    "F07 zero unused native texel descriptor payload bytes")

# F07 P0.3: both legacy descriptor sets and descriptor buffers compare raw
# image entry bytes; make sampled/storage image snapshots deterministic on PS5.
apply_reviewed_delta("include/video_core/renderer_vulkan/vk_update_descriptor.h",
    "    void AddSampledImage(VkImageView image_view, VkSampler sampler) {\n#ifdef PS5_NATIVE\n        if (use_descriptor_buffer) {\n            // Descriptor-buffer reuse compares raw entries. Fully initialize\n            // inactive union bytes and struct padding, not only Vulkan fields.\n            auto* const entry = payload_cursor++;\n            std::memset(entry, 0, sizeof(*entry));\n            entry->image.sampler = sampler;\n            entry->image.imageView = image_view;\n            entry->image.imageLayout = VK_IMAGE_LAYOUT_GENERAL;\n            return;\n        }\n#endif\n        *(payload_cursor++) = VkDescriptorImageInfo{\n            .sampler = sampler,\n            .imageView = image_view,\n            .imageLayout = VK_IMAGE_LAYOUT_GENERAL,\n        };\n    }\n\n    void AddImage(VkImageView image_view) {\n#ifdef PS5_NATIVE\n        if (use_descriptor_buffer) {\n            auto* const entry = payload_cursor++;\n            std::memset(entry, 0, sizeof(*entry));\n            entry->image.sampler = VK_NULL_HANDLE;\n            entry->image.imageView = image_view;\n            entry->image.imageLayout = VK_IMAGE_LAYOUT_GENERAL;\n            return;\n        }\n#endif\n        *(payload_cursor++) = VkDescriptorImageInfo{\n            .sampler = VK_NULL_HANDLE,\n            .imageView = image_view,\n            .imageLayout = VK_IMAGE_LAYOUT_GENERAL,\n        };\n    }",
    "    void AddSampledImage(VkImageView image_view, VkSampler sampler) {\n#ifdef PS5_NATIVE\n        // Both descriptor-buffer and descriptor-set paths compare snapshots.\n        // Initialize the entire union including unused Vulkan image padding.\n        auto* const entry = payload_cursor++;\n        std::memset(entry, 0, sizeof(*entry));\n        entry->image.sampler = sampler;\n        entry->image.imageView = image_view;\n        entry->image.imageLayout = VK_IMAGE_LAYOUT_GENERAL;\n#else\n        *(payload_cursor++) = VkDescriptorImageInfo{\n            .sampler = sampler,\n            .imageView = image_view,\n            .imageLayout = VK_IMAGE_LAYOUT_GENERAL,\n        };\n#endif\n    }\n\n    void AddImage(VkImageView image_view) {\n#ifdef PS5_NATIVE\n        auto* const entry = payload_cursor++;\n        std::memset(entry, 0, sizeof(*entry));\n        entry->image.sampler = VK_NULL_HANDLE;\n        entry->image.imageView = image_view;\n        entry->image.imageLayout = VK_IMAGE_LAYOUT_GENERAL;\n#else\n        *(payload_cursor++) = VkDescriptorImageInfo{\n            .sampler = VK_NULL_HANDLE,\n            .imageView = image_view,\n            .imageLayout = VK_IMAGE_LAYOUT_GENERAL,\n        };\n#endif\n    }",
    "F07 zero native image descriptor payload bytes for legacy and buffer reuse")

# F07 P0.4: failure during a native guest swizzle or DMA copy must not leave
# committed download IDs paired with a moved-from staging vector.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        auto download_map = std::move(async_buffers.front());\n        for (size_t i = download_ids.size(); i > 0; i--) {\n            auto& download_info = download_ids[i - 1];\n            auto& download_buffer = download_map[download_info.async_buffer_id];\n            if (download_info.is_swizzle) {\n                const ImageBase& image = slot_images[download_info.object_id];\n                const auto copies = FixSmallVectorADL(FullDownloadCopies(image.info));\n                download_buffer.offset -= Common::AlignUp(image.unswizzled_size_bytes, 64);\n                std::span<u8> download_span =\n                    download_buffer.mapped_span.subspan(download_buffer.offset);\n                SwizzleImage(*gpu_memory, image.gpu_addr, image.info, copies, download_span, swizzle_data_buffer);\n            } else {\n                const BufferDownload& buffer_info = slot_buffer_downloads[download_info.object_id];\n                std::span<u8> download_span =\n                    download_buffer.mapped_span.subspan(download_buffer.offset);\n                gpu_memory->WriteBlockUnsafe(buffer_info.address, download_span.data(),\n                                             buffer_info.size);\n                slot_buffer_downloads.erase(download_info.object_id);\n            }\n        }\n        for (auto& download_buffer : download_map) {\n            async_buffers_death_ring.emplace_back(download_buffer);\n        }\n        committed_downloads.pop_front();\n        async_buffers.pop_front();",
    "#ifdef PS5_NATIVE\n        // Keep staging queued until the entire guest download is consumed.\n        // Save only offsets (usually <= 4), not a full vector of handles.\n        auto& download_map = async_buffers.front();\n        boost::container::small_vector<size_t, 4> remaining_offsets;\n        remaining_offsets.reserve(download_map.size());\n        for (const auto& buffer : download_map) {\n            remaining_offsets.push_back(buffer.offset);\n        }\n        // Reserve deferred returns BEFORE guest writes. On any failure,\n        // discard only newly queued returns and retry the intact batch.\n        const size_t previous_death_count = async_buffers_death_ring.size();\n        bool batch_consumed = false;\n        SCOPE_EXIT {\n            if (!batch_consumed) {\n                while (async_buffers_death_ring.size() > previous_death_count) {\n                    async_buffers_death_ring.pop_back();\n                }\n            }\n        };\n        for (const auto& buffer : download_map) {\n            async_buffers_death_ring.emplace_back(buffer);\n        }\n        for (size_t i = download_ids.size(); i > 0; --i) {\n            const auto& download_info = download_ids[i - 1];\n            if (download_info.async_buffer_id >= download_map.size()) {\n                throw std::bad_alloc{};\n            }\n            const auto& download_buffer = download_map[download_info.async_buffer_id];\n            auto& offset = remaining_offsets[download_info.async_buffer_id];\n            if (!download_buffer.buffer || offset > download_buffer.mapped_span.size()) {\n                throw std::bad_alloc{};\n            }\n            if (download_info.is_swizzle) {\n                const ImageBase& image = slot_images[download_info.object_id];\n                const auto copies = FixSmallVectorADL(FullDownloadCopies(image.info));\n                const size_t bytes = image.unswizzled_size_bytes;\n                if (bytes > (std::numeric_limits<size_t>::max)() - 63) {\n                    throw std::bad_alloc{};\n                }\n                const size_t aligned = Common::AlignUp(bytes, size_t{64});\n                if (aligned > offset) {\n                    throw std::bad_alloc{};\n                }\n                offset -= aligned;\n                std::span<u8> download_span = download_buffer.mapped_span.subspan(offset);\n                SwizzleImage(*gpu_memory, image.gpu_addr, image.info, copies, download_span,\n                             swizzle_data_buffer);\n            } else {\n                const BufferDownload& buffer_info = slot_buffer_downloads[download_info.object_id];\n                if (buffer_info.size > download_buffer.mapped_span.size() - offset) {\n                    throw std::bad_alloc{};\n                }\n                std::span<u8> download_span = download_buffer.mapped_span.subspan(offset);\n                gpu_memory->WriteBlockUnsafe(buffer_info.address, download_span.data(),\n                                             buffer_info.size);\n            }\n        }\n        // Do not erase DMA slots until every guest write has succeeded.\n        for (const auto& download_info : download_ids) {\n            if (!download_info.is_swizzle) {\n                slot_buffer_downloads.erase(download_info.object_id);\n            }\n        }\n        committed_downloads.pop_front();\n        async_buffers.pop_front();\n        batch_consumed = true;\n#else\n        auto download_map = std::move(async_buffers.front());\n        for (size_t i = download_ids.size(); i > 0; i--) {\n            auto& download_info = download_ids[i - 1];\n            auto& download_buffer = download_map[download_info.async_buffer_id];\n            if (download_info.is_swizzle) {\n                const ImageBase& image = slot_images[download_info.object_id];\n                const auto copies = FixSmallVectorADL(FullDownloadCopies(image.info));\n                download_buffer.offset -= Common::AlignUp(image.unswizzled_size_bytes, 64);\n                std::span<u8> download_span =\n                    download_buffer.mapped_span.subspan(download_buffer.offset);\n                SwizzleImage(*gpu_memory, image.gpu_addr, image.info, copies, download_span, swizzle_data_buffer);\n            } else {\n                const BufferDownload& buffer_info = slot_buffer_downloads[download_info.object_id];\n                std::span<u8> download_span =\n                    download_buffer.mapped_span.subspan(download_buffer.offset);\n                gpu_memory->WriteBlockUnsafe(buffer_info.address, download_span.data(),\n                                             buffer_info.size);\n                slot_buffer_downloads.erase(download_info.object_id);\n            }\n        }\n        for (auto& download_buffer : download_map) {\n            async_buffers_death_ring.emplace_back(download_buffer);\n        }\n        committed_downloads.pop_front();\n        async_buffers.pop_front();\n#endif",
    "F07 transactional native async download replay and deferred release")

# F07 P0.3: reduce driver memory-budget polling while far below the GC
# watermark; return to per-frame monitoring before allocation pressure.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    if (runtime.CanReportMemoryUsage()) {\n        total_used_memory = runtime.GetDeviceMemoryUsage();\n    }",
    "    if (runtime.CanReportMemoryUsage()) {\n#ifdef PS5_NATIVE\n        // A driver memory-budget probe can run under texture_cache.mutex.\n        // While comfortably below the GC watermark, sample every other\n        // frame; at 2/3 of the watermark or higher, sample EVERY frame to\n        // preserve prompt reclaim and avoid an allocation-pressure blind spot.\n        const bool near_gc_watermark =\n            total_used_memory >= minimum_memory - minimum_memory / 3;\n        if (near_gc_watermark || (frame_tick & 1u) == 0) {\n            total_used_memory = runtime.GetDeviceMemoryUsage();\n        }\n#else\n        total_used_memory = runtime.GetDeviceMemoryUsage();\n#endif\n    }",
    "F07 native memory pressure sampling outside near GC watermark")

# F07 P0.3: sparse depth+color renderpasses should inspect ONLY attached
# color slots while resolving sampled-depth feedback (desktop unchanged).
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "                for (size_t i = 0; i < 8; ++i)\n                    is_continue |= (rt_active_mask & (1u << i)) && view.id == render_targets.color_buffer_ids[i];",
    "#ifdef PS5_NATIVE\n                // Only visit color targets actually attached to this depth pass.\n                u32 color_slots = rt_active_mask & ((1u << NUM_RT) - 1);\n                while (color_slots) {\n                    const u32 slot = std::countr_zero(color_slots);\n                    is_continue |= view.id == render_targets.color_buffer_ids[slot];\n                    color_slots &= color_slots - 1;\n                }\n#else\n                for (size_t i = 0; i < 8; ++i)\n                    is_continue |= (rt_active_mask & (1u << i)) && view.id == render_targets.color_buffer_ids[i];\n#endif",
    "F07 enumerate active color slots for feedback view IDs")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "                for (size_t i = 0; i < 8; ++i)\n                    is_continue |= (rt_active_mask & (1u << i)) && view_image_id == rt_image_id[i];",
    "#ifdef PS5_NATIVE\n                u32 color_slots = rt_active_mask & ((1u << NUM_RT) - 1);\n                while (color_slots) {\n                    const u32 slot = std::countr_zero(color_slots);\n                    is_continue |= view_image_id == rt_image_id[slot];\n                    color_slots &= color_slots - 1;\n                }\n#else\n                for (size_t i = 0; i < 8; ++i)\n                    is_continue |= (rt_active_mask & (1u << i)) && view_image_id == rt_image_id[i];\n#endif",
    "F07 enumerate active color slots for feedback image IDs")

# F07 P0.3: sparse feedback alias checks have no observable comparisons
# after finding an active color attachment. Exit immediately on a match.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "                    is_continue |= view.id == render_targets.color_buffer_ids[slot];\n                    color_slots &= color_slots - 1;",
    "                    if (view.id == render_targets.color_buffer_ids[slot]) {\n                        is_continue = true;\n                        break;\n                    }\n                    color_slots &= color_slots - 1;",
    "F07 short circuit active color view feedback match")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "                    is_continue |= view_image_id == rt_image_id[slot];\n                    color_slots &= color_slots - 1;",
    "                    if (view_image_id == rt_image_id[slot]) {\n                        is_continue = true;\n                        break;\n                    }\n                    color_slots &= color_slots - 1;",
    "F07 short circuit active color image feedback match")

# F07 P0.3: invalid native DMA buffer/image byte counts cannot use a GPU
# span; reject them before waiting for BOTH guest cache mutexes.
apply_reviewed_delta("vulkan_rasterizer.cpp",
    "    std::scoped_lock lock{buffer_cache.mutex, texture_cache.mutex};\n    const auto image_id = texture_cache.DmaImageId(image_operand, IS_IMAGE_UPLOAD);\n    if (image_id == VideoCommon::NULL_IMAGE_ID) {\n        return false;\n    }\n    // Widen before multiplying, then respect the u32 buffer-cache span.\n    const u64 buffer_size_wide = static_cast<u64>(buffer_operand.pitch) * buffer_operand.height;\n    if (buffer_size_wide > static_cast<u64>(~u32{0})) {\n        return false;\n    }\n    const u32 buffer_size = static_cast<u32>(buffer_size_wide);",
    "#ifdef PS5_NATIVE\n    // Invalid DMA images have no buffer-cache allocation or GPU work.\n    // Reject them before the paired guest cache mutexes, so HUD bursts\n    // cannot queue behind an unrelated texture update for a no-op copy.\n    const u64 checked_bytes = static_cast<u64>(buffer_operand.pitch) * buffer_operand.height;\n    if (checked_bytes == 0 || checked_bytes > static_cast<u64>(~u32{0})) {\n        return false;\n    }\n#endif\n    std::scoped_lock lock{buffer_cache.mutex, texture_cache.mutex};\n    const auto image_id = texture_cache.DmaImageId(image_operand, IS_IMAGE_UPLOAD);\n    if (image_id == VideoCommon::NULL_IMAGE_ID) {\n        return false;\n    }\n#ifdef PS5_NATIVE\n    const u32 buffer_size = static_cast<u32>(checked_bytes);\n#else\n    // Widen before multiplying, then respect the u32 buffer-cache span.\n    const u64 buffer_size_wide = static_cast<u64>(buffer_operand.pitch) * buffer_operand.height;\n    if (buffer_size_wide > static_cast<u64>(~u32{0})) {\n        return false;\n    }\n    const u32 buffer_size = static_cast<u32>(buffer_size_wide);\n#endif",
    "F07 native DMA image byte guard before paired cache mutex")

# F07 native DMA and compute-indirect must refuse null Vulkan handles, even
# when their guest buffer objects and requested spans are valid.

apply_reviewed_delta("vulkan_rasterizer.cpp",
    "        if (!buffer) {\n            return;\n        }\n#endif\n        scheduler.RequestOutsideRenderPassOperationContext();",
    "        if (!buffer || buffer->Handle() == VK_NULL_HANDLE) {\n            return;\n        }\n#endif\n        scheduler.RequestOutsideRenderPassOperationContext();",
    "F07 compute indirect reject null Vulkan handles")

apply_reviewed_delta("vulkan_rasterizer.cpp",
    "    const auto [buffer, offset] =\n        buffer_cache.ObtainBuffer(buffer_operand.address, buffer_size, sync_info, post_op);\n\n    const auto [image, copy]",
    "    const auto [buffer, offset] =\n        buffer_cache.ObtainBuffer(buffer_operand.address, buffer_size, sync_info, post_op);\n#ifdef PS5_NATIVE\n    // Guest size alone does not prove a valid GPU buffer handle.\n    if (!buffer || buffer->Handle() == VK_NULL_HANDLE) {\n        return false;\n    }\n#endif\n\n    const auto [image, copy]",
    "F07 DMA image reject null Vulkan handles")

# F07 PS5: DMA clear sizes count u32 words and are already rejected by the
# buffer cache. Refuse impossible counts before contending on its mutex.
apply_reviewed_delta("vulkan_rasterizer.cpp",
    "bool AccelerateDMA::BufferClear(GPUVAddr src_address, u64 amount, u32 value) {\n    std::scoped_lock lock{buffer_cache.mutex};\n    return buffer_cache.DMAClear(src_address, amount, value);\n}",
    "bool AccelerateDMA::BufferClear(GPUVAddr src_address, u64 amount, u32 value) {\n#ifdef PS5_NATIVE\n    // The DMA clear count is in u32 words. Reject zero and oversized GPU\n    // fills before waiting for the guest buffer-cache mutex.\n    if (amount == 0 || amount > static_cast<u64>(~u32{0}) / sizeof(u32)) {\n        return false;\n    }\n#endif\n    std::scoped_lock lock{buffer_cache.mutex};\n    return buffer_cache.DMAClear(src_address, amount, value);\n}",
    "F07 reject invalid DMA clear words before the buffer mutex")

# F07 P0.1: record complete cold compute CPU translation, separately from
# Vulkan worker wait. Detailed Logging only; no hot-path clock sampling.
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "    if (is_new) {\n        pipeline = CreateComputePipeline(key, shader);\n#ifdef PS5_NATIVE\n        if (!pipeline) {",
    "    if (is_new) {\n#ifdef PS5_NATIVE\n        // P0.1: time every cold compute CPU translation and driver enqueue.\n        // The asynchronous Vulkan pipeline wait is reported separately.\n        ::Eden::Performance::CachePhaseTimer first_use_compute_cost{\n            ::Eden::Performance::CachePhase::ComputePipelineCreate,\n            ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)};\n#endif\n        pipeline = CreateComputePipeline(key, shader);\n#ifdef PS5_NATIVE\n        if (!pipeline) {",
    "F07 detailed CPU timing for cold compute first use")
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "            failed->second.attempted = true;\n            pipeline = CreateComputePipeline(key, shader);\n            // A consumed retry",
    "            failed->second.attempted = true;\n            ::Eden::Performance::CachePhaseTimer retry_compute_cost{\n                ::Eden::Performance::CachePhase::ComputePipelineCreate,\n                ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)};\n            pipeline = CreateComputePipeline(key, shader);\n            // A consumed retry",
    "F07 detailed CPU timing for delayed compute retry")

# F07 P0.4: BCn 3D output-buffer growth is transactional. Preserve the
# old buffer size on allocation failure, reject zero and overflowing copies
# before recording GPU compute work. Desktop keeps the pinned behavior.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "void Image::AllocateComputeUnswizzleBuffer(u32 max_slices) {\n    using VideoCore::Surface::BytesPerBlock;\n\n    const u32 block_bytes  = BytesPerBlock(info.format); // 8 for BC1, 16 for BC6H\n    const u32 block_width  = 4;\n    const u32 block_height = 4;\n\n    // BCn is 4x4x1 blocks\n    const u32 blocks_x = (info.size.width  + block_width  - 1) / block_width;\n    const u32 blocks_y = (info.size.height + block_height - 1) / block_height;\n    const u32 blocks_z = (std::min)(max_slices, info.size.depth);\n\n    const u64 block_count =\n        static_cast<u64>(blocks_x) *\n        static_cast<u64>(blocks_y) *\n        static_cast<u64>(blocks_z);\n\n    const VkDeviceSize required_size = block_count * block_bytes;\n    if (has_compute_unswizzle_buffer && required_size <= compute_unswizzle_buffer_size) {\n        return;\n    }\n\n    compute_unswizzle_buffer_size = required_size;\n\n    VkBufferCreateInfo ci{\n        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,\n        .pNext = nullptr,\n        .flags = 0,\n        .size = compute_unswizzle_buffer_size,\n        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT |\n                 VK_BUFFER_USAGE_TRANSFER_SRC_BIT,\n        .sharingMode = VK_SHARING_MODE_EXCLUSIVE,\n        .queueFamilyIndexCount = 0,\n        .pQueueFamilyIndices = nullptr,\n    };\n\n    compute_unswizzle_buffer =\n        runtime->memory_allocator.CreateBuffer(ci, MemoryUsage::DeviceLocal);\n\n    has_compute_unswizzle_buffer = true;\n}\n",
    "void Image::AllocateComputeUnswizzleBuffer(u32 max_slices) {\n    using VideoCore::Surface::BytesPerBlock;\n\n    const u32 block_bytes  = BytesPerBlock(info.format); // 8 for BC1, 16 for BC6H\n    const u32 block_width  = 4;\n    const u32 block_height = 4;\n\n#ifdef PS5_NATIVE\n    // The compute pass also rounds width/height in u32. Reject invalid\n    // dimensions before either rounding can wrap or the GPU batch can stall.\n    if (info.size.width == 0 || info.size.height == 0 || max_slices == 0 ||\n        info.size.depth == 0 || block_bytes == 0 ||\n        info.size.width > ~u32{0} - (block_width - 1) ||\n        info.size.height > ~u32{0} - (block_height - 1)) {\n        throw std::bad_alloc{};\n    }\n#endif\n    // BCn is 4x4x1 blocks\n    const u32 blocks_x = (info.size.width  + block_width  - 1) / block_width;\n    const u32 blocks_y = (info.size.height + block_height - 1) / block_height;\n    const u32 blocks_z = (std::min)(max_slices, info.size.depth);\n\n#ifdef PS5_NATIVE\n    // Check every multiplication before allocating the BCn 3D output.\n    // An unsigned wrap could otherwise allocate a tiny Vulkan buffer for\n    // an enormous compute write while keeping texture_cache.mutex held.\n    constexpr VkDeviceSize max_buffer = (std::numeric_limits<VkDeviceSize>::max)();\n    if (blocks_z == 0 || static_cast<u64>(blocks_x) > max_buffer / blocks_y) {\n        throw std::bad_alloc{};\n    }\n    const u64 blocks_xy = static_cast<u64>(blocks_x) * blocks_y;\n    if (blocks_xy > max_buffer / blocks_z ||\n        blocks_xy * blocks_z > max_buffer / block_bytes) {\n        throw std::bad_alloc{};\n    }\n#endif\n    const u64 block_count =\n        static_cast<u64>(blocks_x) *\n        static_cast<u64>(blocks_y) *\n        static_cast<u64>(blocks_z);\n\n    const VkDeviceSize required_size = block_count * block_bytes;\n    if (has_compute_unswizzle_buffer && required_size <= compute_unswizzle_buffer_size) {\n        return;\n    }\n\n#ifndef PS5_NATIVE\n    compute_unswizzle_buffer_size = required_size;\n#endif\n\n    VkBufferCreateInfo ci{\n        .sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,\n        .pNext = nullptr,\n        .flags = 0,\n        .size = required_size,\n        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT |\n                 VK_BUFFER_USAGE_TRANSFER_SRC_BIT,\n        .sharingMode = VK_SHARING_MODE_EXCLUSIVE,\n        .queueFamilyIndexCount = 0,\n        .pQueueFamilyIndices = nullptr,\n    };\n\n    // The previous buffer remains valid if the allocator rejects growth.\n    // Publish its NEW size only after Vulkan returned a replacement handle.\n    compute_unswizzle_buffer =\n        runtime->memory_allocator.CreateBuffer(ci, MemoryUsage::DeviceLocal);\n#ifdef PS5_NATIVE\n    compute_unswizzle_buffer_size = required_size;\n#endif\n    has_compute_unswizzle_buffer = true;\n}\n",
    "F07 PS5 transactional BCn 3D compute output buffer")

# F07: a successful allocation request can still expose a null Vulkan
# handle. Reject it before publishing the enlarged 3D compute scratch size.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "    // The previous buffer remains valid if the allocator rejects growth.\n    // Publish its NEW size only after Vulkan returned a replacement handle.\n    compute_unswizzle_buffer =\n        runtime->memory_allocator.CreateBuffer(ci, MemoryUsage::DeviceLocal);\n#ifdef PS5_NATIVE\n    compute_unswizzle_buffer_size = required_size;\n#endif\n    has_compute_unswizzle_buffer = true;",
    "#ifdef PS5_NATIVE\n    // Allocation can return an empty Vulkan handle without throwing. Never\n    // publish a fictitious grown capacity or discard the old valid buffer.\n    auto replacement = runtime->memory_allocator.CreateBuffer(ci, MemoryUsage::DeviceLocal);\n    if (!replacement) {\n        throw std::bad_alloc{};\n    }\n    compute_unswizzle_buffer = std::move(replacement);\n    compute_unswizzle_buffer_size = required_size;\n#else\n    compute_unswizzle_buffer =\n        runtime->memory_allocator.CreateBuffer(ci, MemoryUsage::DeviceLocal);\n#endif\n    has_compute_unswizzle_buffer = true;",
    "F07 reject null native BCn 3D output buffer handle")

# F07 P0.4: an unaccepted upload command must not publish a valid GPU
# initialization state. Preserve desktop behavior and move native commit
# until immediately AFTER successful FIFO insertion into the scheduler.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "    const bool was_initialized = std::exchange(initialized, true);\n\n    scheduler->Record([src_buffer, vk_image, vk_aspect_mask, was_initialized,\n                       vk_copies = std::move(vk_copies)](vk::CommandBuffer cmdbuf) {\n        CopyBufferToImage(cmdbuf, src_buffer, vk_image, vk_aspect_mask, was_initialized, VideoCommon::FixSmallVectorADL(vk_copies));\n    });",
    "#ifdef PS5_NATIVE\n    // Record can reject before accepting this copy. Keep the old layout state\n    // until a Vulkan command has actually entered the scheduler queue.\n    const bool was_initialized = initialized;\n#else\n    const bool was_initialized = std::exchange(initialized, true);\n#endif\n\n    scheduler->Record([src_buffer, vk_image, vk_aspect_mask, was_initialized,\n                       vk_copies = std::move(vk_copies)](vk::CommandBuffer cmdbuf) {\n        CopyBufferToImage(cmdbuf, src_buffer, vk_image, vk_aspect_mask, was_initialized, VideoCommon::FixSmallVectorADL(vk_copies));\n    });\n#ifdef PS5_NATIVE\n    initialized = true;\n#endif",
    "F07 native image initialized only after accepted upload record")

# F07 P0.4: the legacy descriptor-set memo is only valid after the Vulkan
# worker command was accepted. A rejected Record must not suppress a later
# changed HUD descriptor. Leave the desktop path and descriptor-buffer cache.
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "        if (update_descriptors) {\n            if (num_descriptor_entries != 0) {\n                last_descriptor_payload.assign(entries, entries + num_descriptor_entries);\n            } else {\n                last_descriptor_payload.clear();\n            }\n        }\n    }\n    scheduler.Record([this, descriptor_data, bind_pipeline, optimized_at_record, update_descriptors,",
    "#ifndef PS5_NATIVE\n        // The legacy desktop path preserves its existing early cache memo.\n        if (update_descriptors) {\n            if (num_descriptor_entries != 0) {\n                last_descriptor_payload.assign(entries, entries + num_descriptor_entries);\n            } else {\n                last_descriptor_payload.clear();\n            }\n        }\n#endif\n    }\n    scheduler.Record([this, descriptor_data, bind_pipeline, optimized_at_record, update_descriptors,",
    "F07 defer PS5 legacy descriptor memo until accepted Vulkan draw")
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "    });\n    return true;\n}\n\n\nnamespace {\n#ifdef PS5_NATIVE\n// Only first-use pipelines are mandatory.",
    "    });\n#ifdef PS5_NATIVE\n    // Descriptor-set updates are encoded by the Vulkan worker. If Record\n    // throws before accepting the draw, retaining the old memo forces the\n    // next HUD draw to publish its changed descriptors instead of reusing\n    // an unsubmitted descriptor set.\n    if (descriptor_set_layout && !uses_push_descriptor && !uses_descriptor_buffer &&\n        update_descriptors) {\n        const auto* const entries = static_cast<const DescriptorUpdateEntry*>(descriptor_data);\n        if (num_descriptor_entries != 0) {\n            last_descriptor_payload.assign(entries, entries + num_descriptor_entries);\n        } else {\n            last_descriptor_payload.clear();\n        }\n    }\n#endif\n    return true;\n}\n\n\nnamespace {\n#ifdef PS5_NATIVE\n// Only first-use pipelines are mandatory.",
    "F07 publish PS5 legacy descriptor memo after accepted Vulkan draw")

# F07 P0.4: a null VkBuffer from the transient image-reinterpret pool is
# NOT a valid scratch copy. Keep the destination resolve intact on rejection.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "    const VkBuffer copy_buffer = GetTemporaryBuffer(total_size);\n#ifdef PS5_NATIVE\n    // A rejected reinterpretation does not alter the destination image.",
    "    const VkBuffer copy_buffer = GetTemporaryBuffer(total_size);\n#ifdef PS5_NATIVE\n    // A mapped scratch allocation can still contain a null Vulkan handle.\n    // Reject before invalidating the resolve or enqueueing any GPU copies.\n    if (copy_buffer == VK_NULL_HANDLE) {\n        return;\n    }\n    // A rejected reinterpretation does not alter the destination image.",
    "F07 reject null native image reinterpret scratch handle")

# F07 P0.3: BCn 3D uses precisely two storage-buffer descriptors. Do not
# reserve a third entry (and potentially drain the worker) on PS5.
apply_reviewed_delta("vk_compute_pass_cost.cpp",
    "    compute_pass_descriptor_queue.Acquire(scheduler, 3);\n    compute_pass_descriptor_queue.AddBuffer(swizzled.buffer,",
    "#ifdef PS5_NATIVE\n    // The BCn 3D pass has exactly two storage-buffer bindings. Reserving\n    // three entries can force an unnecessary queue drain when the cursor\n    // is near its frame limit, under texture-cache synchronization.\n    compute_pass_descriptor_queue.Acquire(scheduler, 2);\n#else\n    compute_pass_descriptor_queue.Acquire(scheduler, 3);\n#endif\n    compute_pass_descriptor_queue.AddBuffer(swizzled.buffer,",
    "F07 reserve exact two native BCn3D compute descriptors")

# F07 P0.4: reject invalid BCn3D Z ranges and offset arithmetic before
# allocating compute scratch or acquiring GPU descriptors. The staging map
# may be packed and smaller than the padded guest memory span; do NOT use
# it as the guest descriptor bound. Desktop preserves the pinned behavior.
apply_reviewed_delta("vk_compute_pass_cost.cpp",
    "    using namespace VideoCommon::Accelerated;\n\n    const u32 MAX_BATCH_SLICES = (std::min)(z_count, image.info.size.depth);",
    "    using namespace VideoCommon::Accelerated;\n\n#ifdef PS5_NATIVE\n    // Reject malformed batches before allocating the BCn compute output or\n    // touching the descriptor ring. Preserve guest dirty state for retry.\n    if (swizzles.size() != 1 || swizzled.buffer == VK_NULL_HANDLE ||\n        z_count == 0 || z_start >= image.info.size.depth ||\n        z_count > image.info.size.depth - z_start) {\n        throw std::bad_alloc{};\n    }\n    const auto& input = swizzles[0];\n    // The descriptor below subtracts this offset from guest_size_bytes and\n    // adds it to the Vulkan buffer offset. Both operations must be valid.\n    // Do not compare against mapped_span: guest block-linear and linear\n    // staging byte counts can intentionally differ.\n    if (input.buffer_offset >= image.guest_size_bytes ||\n        input.buffer_offset > (~VkDeviceSize{0} - swizzled.offset)) {\n        throw std::bad_alloc{};\n    }\n#endif\n\n    const u32 MAX_BATCH_SLICES = (std::min)(z_count, image.info.size.depth);",
    "F07 reject native BCn3D invalid slice and descriptor offsets before allocation")

# F07 P0.3: move BCn3D VkDescriptorSet allocator into the FIFO worker,
# matching the other five native compute passes, without moving the
# descriptor payload or changing desktop's original allocation order.
apply_reviewed_delta("vk_compute_pass_cost.cpp",
    "    const void* descriptor_data = compute_pass_descriptor_queue.UpdateData();\n    const VkDescriptorSet set = descriptor_allocator.Commit();\n\n    const u32 gx =",
    "    const void* descriptor_data = compute_pass_descriptor_queue.UpdateData();\n#ifndef PS5_NATIVE\n    const VkDescriptorSet set = descriptor_allocator.Commit();\n#endif\n\n    const u32 gx =",
    "F07 defer PS5 BCn3D descriptor set allocation from owner")


# F07 P0.3: move BCn3D VkDescriptorSet allocator into the FIFO worker,
# matching the other five native compute passes, without moving the
# descriptor payload or changing desktop's original allocation order.
apply_reviewed_delta("vk_compute_pass_cost.cpp",
    "    scheduler.Record([this, set, descriptor_data, pc, gx, gy, gz, z_start, z_count,\n                      barrier_size, is_first_chunk, out_buffer, dst_image, aspect,\n                      image_width, image_height\n                      ](vk::CommandBuffer cmdbuf) {",
    "#ifdef PS5_NATIVE\n    scheduler.Record([this, descriptor_data, pc, gx, gy, gz, z_start, z_count,\n#else\n    scheduler.Record([this, set, descriptor_data, pc, gx, gy, gz, z_start, z_count,\n#endif\n                      barrier_size, is_first_chunk, out_buffer, dst_image, aspect,\n                      image_width, image_height\n                      ](vk::CommandBuffer cmdbuf) {",
    "F07 omit BCn3D descriptor set owner capture on native worker")


# F07 P0.3: move BCn3D VkDescriptorSet allocator into the FIFO worker,
# matching the other five native compute passes, without moving the
# descriptor payload or changing desktop's original allocation order.
apply_reviewed_delta("vk_compute_pass_cost.cpp",
    "        if (dst_image == VK_NULL_HANDLE || out_buffer == VK_NULL_HANDLE) {\n            return;\n        }\n\n        device.GetLogical().UpdateDescriptorSet(set, *descriptor_template, descriptor_data);",
    "        if (dst_image == VK_NULL_HANDLE || out_buffer == VK_NULL_HANDLE) {\n            return;\n        }\n\n#ifdef PS5_NATIVE\n        // Mirror the other compute passes: allocate the Vulkan descriptor set\n        // on the FIFO worker, outside the caller's texture-cache lock.\n        const VkDescriptorSet set = descriptor_allocator.Commit();\n#endif\n        device.GetLogical().UpdateDescriptorSet(set, *descriptor_template, descriptor_data);",
    "F07 commit native BCn3D descriptor set on Vulkan worker")

# F07 P0.4: every BCn 3D batch leaves its image in GENERAL. A later
# Z batch must transition from GENERAL, with a source stage that covers
# intervening readers/writers, instead of claiming TRANSFER_DST_OPTIMAL.
apply_reviewed_delta("vk_compute_pass_cost.cpp",
    "        // Image layout transition\n        const VkImageMemoryBarrier pre_barrier{\n            .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,\n            .pNext = nullptr,\n            .srcAccessMask = is_first_chunk ? VkAccessFlags{} :\n                            static_cast<VkAccessFlags>(VK_ACCESS_TRANSFER_WRITE_BIT),\n            .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,\n            .oldLayout = is_first_chunk ? VK_IMAGE_LAYOUT_UNDEFINED :\n                        VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,\n            .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,",
    "        // Image layout transition. Each previous BCn 3D batch ended in\n        // GENERAL, not TRANSFER_DST_OPTIMAL. On PS5 a later Z batch must\n        // transition from its actual layout and synchronize any intervening\n        // shader reads/writes before the next transfer.\n        const VkImageMemoryBarrier pre_barrier{\n            .sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,\n            .pNext = nullptr,\n#ifdef PS5_NATIVE\n            .srcAccessMask = is_first_chunk ? VkAccessFlags{} :\n                            static_cast<VkAccessFlags>(VK_ACCESS_MEMORY_READ_BIT |\n                                                       VK_ACCESS_MEMORY_WRITE_BIT),\n#else\n            .srcAccessMask = is_first_chunk ? VkAccessFlags{} :\n                            static_cast<VkAccessFlags>(VK_ACCESS_TRANSFER_WRITE_BIT),\n#endif\n            .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,\n#ifdef PS5_NATIVE\n            .oldLayout = is_first_chunk ? VK_IMAGE_LAYOUT_UNDEFINED : VK_IMAGE_LAYOUT_GENERAL,\n#else\n            .oldLayout = is_first_chunk ? VK_IMAGE_LAYOUT_UNDEFINED :\n                        VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,\n#endif\n            .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,",
    "F07 preserve native BCn 3D image layout between GPU batches")
apply_reviewed_delta("vk_compute_pass_cost.cpp",
    "        // Single barrier handles both buffer and image\n        cmdbuf.PipelineBarrier(\n            VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,\n            VK_PIPELINE_STAGE_TRANSFER_BIT,\n            0,\n            nullptr, buffer_barrier, pre_barrier\n        );",
    "        // Single barrier handles both buffer and image.\n        // The previous batch can have been sampled by any graphics stage;\n        // match the GENERAL image read/write access in the native barrier.\n        cmdbuf.PipelineBarrier(\n#ifdef PS5_NATIVE\n            VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,\n#else\n            VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,\n#endif\n            VK_PIPELINE_STAGE_TRANSFER_BIT,\n            0,\n            nullptr, buffer_barrier, pre_barrier\n        );",
    "F07 synchronize native BCn 3D reused image before transfer")

# F07 P0.4: never queue BCn 3D GPU chunks for an invalid output image.
# Keep native rejection on the owner so async dirty state remains retryable.
apply_reviewed_delta("vk_compute_pass_cost.cpp",
    "    // Allocate or grow to cover this batch's slice count\n    image.AllocateComputeUnswizzleBuffer(MAX_BATCH_SLICES);\n\n    ASSERT(swizzles.size() == 1);",
    "    // Allocate or grow to cover this batch's slice count\n    image.AllocateComputeUnswizzleBuffer(MAX_BATCH_SLICES);\n#ifdef PS5_NATIVE\n    // A failed destination image is not a successful async BCn upload.\n    // Reject on the GPU owner BEFORE queuing chunks; the async caller will\n    // retain the guest dirty flag and retry rather than acknowledge no pixels.\n    if (image.Handle() == VK_NULL_HANDLE ||\n        !image.compute_unswizzle_buffer ||\n        *image.compute_unswizzle_buffer == VK_NULL_HANDLE) {\n        throw std::bad_alloc{};\n    }\n#endif\n\n    ASSERT(swizzles.size() == 1);",
    "F07 native reject null BCn3D destination before GPU upload")

# F07 P0.4: make the native bad_alloc signal's header explicit in the
# generated compute-pass TU instead of relying on a transitive include.
apply_reviewed_delta("vk_compute_pass_cost.cpp",
    "#include <memory>\n#include <numeric>",
    "#include <memory>\n#include <new>\n#include <numeric>",
    "F07 explicitly include std bad_alloc for native BCn3D output preflight")

# F07 P0.3/P0.4: reject a null image BEFORE allocating BCn 3D scratch,
# then check the output handle after the allocation. No change to desktop.
apply_reviewed_delta("vk_compute_pass_cost.cpp",
    "    const u32 MAX_BATCH_SLICES = (std::min)(z_count, image.info.size.depth);\n\n    // Allocate or grow to cover this batch's slice count\n    image.AllocateComputeUnswizzleBuffer(MAX_BATCH_SLICES);\n#ifdef PS5_NATIVE\n    // A failed destination image is not a successful async BCn upload.\n    // Reject on the GPU owner BEFORE queuing chunks; the async caller will\n    // retain the guest dirty flag and retry rather than acknowledge no pixels.\n    if (image.Handle() == VK_NULL_HANDLE ||\n        !image.compute_unswizzle_buffer ||\n        *image.compute_unswizzle_buffer == VK_NULL_HANDLE) {\n        throw std::bad_alloc{};\n    }\n#endif\n\n    ASSERT(swizzles.size() == 1);",
    "    const u32 MAX_BATCH_SLICES = (std::min)(z_count, image.info.size.depth);\n\n#ifdef PS5_NATIVE\n    // A null destination must not allocate an otherwise wasted device-local\n    // decompression buffer. Reject before ANY Vulkan output allocation.\n    if (image.Handle() == VK_NULL_HANDLE) {\n        throw std::bad_alloc{};\n    }\n#endif\n    // Allocate or grow to cover this batch's slice count\n    image.AllocateComputeUnswizzleBuffer(MAX_BATCH_SLICES);\n#ifdef PS5_NATIVE\n    // Allocation can still return a null output handle. Reject before\n    // queueing a no-op GPU callback, retaining dirty guest pixels for retry.\n    if (!image.compute_unswizzle_buffer ||\n        *image.compute_unswizzle_buffer == VK_NULL_HANDLE) {\n        throw std::bad_alloc{};\n    }\n#endif\n\n    ASSERT(swizzles.size() == 1);",
    "F07 avoid wasted BCn3D output allocation for null native image")

# F07 P0.3: the initial BCn3D image is UNDEFINED, with only a preceding
# compute shader write to the decompressed scratch buffer. Keep ALL_COMMANDS
# only for reused GENERAL image chunks on the PS5, preserving desktop.
apply_reviewed_delta("vk_compute_pass_cost.cpp",
    "        // Single barrier handles both buffer and image.\n        // The previous batch can have been sampled by any graphics stage;\n        // match the GENERAL image read/write access in the native barrier.\n        cmdbuf.PipelineBarrier(\n#ifdef PS5_NATIVE\n            VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,\n#else\n            VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,\n#endif\n            VK_PIPELINE_STAGE_TRANSFER_BIT,\n            0,\n            nullptr, buffer_barrier, pre_barrier\n        );",
    "        // Single barrier handles both buffer and image.\n        // A new image starts UNDEFINED: its compute output is the only\n        // dependency. A reused Z batch may have been sampled by graphics,\n        // and still needs the full GENERAL read/write synchronization.\n        cmdbuf.PipelineBarrier(\n#ifdef PS5_NATIVE\n            is_first_chunk ? VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT :\n                             VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,\n#else\n            VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,\n#endif\n            VK_PIPELINE_STAGE_TRANSFER_BIT,\n            0,\n            nullptr, buffer_barrier, pre_barrier\n        );",
    "F07 avoid all commands source barrier for first native BCn3D batch")

# F07 P0.2/P0.4: a failed native scheduler enqueue must invalidate cached
# pipeline/rescaling/descriptor state, or the next HUD draw may skip binds.
# Leave active renderpass, accepted FIFO work and desktop behavior untouched.
apply_reviewed_delta("include/video_core/renderer_vulkan/vk_scheduler.h",
    "    void RecordWithUploadBuffer(T&& command) {\n        if (chunk->Record(command)) {\n            return;\n        }\n        DispatchWork();\n        (void)chunk->Record(command);\n    }",
    "    void RecordWithUploadBuffer(T&& command) {\n#ifdef PS5_NATIVE\n        // ConfigureDraw/Configure can memoize pipeline, rescaling and\n        // descriptor bindings before enqueueing. If a chunk record or\n        // rollover throws, those bindings were never accepted by the FIFO.\n        // Invalidate ONLY the owner's cached command state; the current\n        // renderpass and already-queued commands are left intact.\n        try {\n#endif\n        if (chunk->Record(command)) {\n            return;\n        }\n        DispatchWork();\n        (void)chunk->Record(command);\n#ifdef PS5_NATIVE\n        } catch (...) {\n            InvalidateState();\n            throw;\n        }\n#endif\n    }",
    "F07 invalidate native Vulkan binding memo after rejected record")

# F07 P0.2/P0.4: the second record after a chunk rollover is not optional.
# Preserve desktop behavior; an unaccepted native command must invalidate
# memoized Vulkan bindings rather than silently skip its draw/upload.
apply_reviewed_delta("include/video_core/renderer_vulkan/vk_scheduler.h",
    "        DispatchWork();\n        (void)chunk->Record(command);\n#ifdef PS5_NATIVE\n        } catch (...) {",
    "        DispatchWork();\n#ifdef PS5_NATIVE\n        // Even after rollover the new chunk can refuse the command.\n        // Never treat a missing draw/descriptor upload as successfully queued.\n        if (!chunk->Record(command)) {\n            throw std::bad_alloc{};\n        }\n#else\n        (void)chunk->Record(command);\n#endif\n#ifdef PS5_NATIVE\n        } catch (...) {",
    "F07 reject native scheduler second record refusal after rollover")

# F07 native scheduler failure path references std::bad_alloc explicitly.
# Keep the regenerated pinned Vulkan header identical to the shipped fork.
apply_reviewed_delta("include/video_core/renderer_vulkan/vk_scheduler.h",
    "#include <memory>\n",
    "#include <memory>\n#include <new>\n",
    "F07 include bad_alloc declaration for native rejected scheduler rollover")

# F07 P0.3: do not poll the GPU completion semaphore once per cached MSAA
# scratch object or pending resolve during normal frame cleanup. A single
# monotone completed tick is conservative: late completions wait one pass.
# Preserve the original desktop scheduler.IsFree path.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "    for (MsaaScratchImage& scratch : msaa_scratch_images) {\n        if (scratch.key != key || !scheduler.IsFree(scratch.tick)) {\n            continue;\n        }",
    "#ifdef PS5_NATIVE\n    // One monotone GPU-completion snapshot for the scratch search. A fence\n    // completed during this scan becomes reusable at the next allocation.\n    const u64 completed_tick = scheduler.GetMasterSemaphore().KnownGpuTick();\n#endif\n    for (MsaaScratchImage& scratch : msaa_scratch_images) {\n#ifdef PS5_NATIVE\n        if (scratch.key != key || scratch.tick > completed_tick) {\n#else\n        if (scratch.key != key || !scheduler.IsFree(scratch.tick)) {\n#endif\n            continue;\n        }",
    "F07 snapshot native MSAA scratch reuse GPU completion")
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "void TextureCacheRuntime::TickFrame() {\n    static constexpr u32 MAX_UNUSED_SCRATCH_FRAMES = 60;\n    std::erase_if(msaa_scratch_images, [this](MsaaScratchImage& scratch) {\n        if (!scheduler.IsFree(scratch.tick)) {\n            scratch.unused_frames = 0;\n            return false;\n        }\n        return ++scratch.unused_frames > MAX_UNUSED_SCRATCH_FRAMES;\n    });\n    std::erase_if(pending_resolve_shadows, [this](const auto& pending) {\n        return scheduler.IsFree(pending.first);\n    });\n}",
    "void TextureCacheRuntime::TickFrame() {\n    static constexpr u32 MAX_UNUSED_SCRATCH_FRAMES = 60;\n#ifdef PS5_NATIVE\n    // One conservative GPU completion sample for both cleanup scans, not a\n    // semaphore query per scratch/resolve. Late completions wait one frame.\n    const u64 completed_tick = scheduler.GetMasterSemaphore().KnownGpuTick();\n    const auto is_free = [completed_tick](u64 tick) noexcept {\n        return tick <= completed_tick;\n    };\n#else\n    const auto is_free = [this](u64 tick) { return scheduler.IsFree(tick); };\n#endif\n    std::erase_if(msaa_scratch_images, [is_free](MsaaScratchImage& scratch) {\n        if (!is_free(scratch.tick)) {\n            scratch.unused_frames = 0;\n            return false;\n        }\n        return ++scratch.unused_frames > MAX_UNUSED_SCRATCH_FRAMES;\n    });\n    std::erase_if(pending_resolve_shadows, [is_free](const auto& pending) {\n        return is_free(pending.first);\n    });\n}",
    "F07 snapshot native MSAA scratch and resolve cleanup GPU completion")

# F07: a cold MSAA allocation has no scratch candidates to test;
# a completely idle MSAA/resolve GC frame has no retirement work either.
# Avoid native semaphore samples in both empty cases; existing completion
# comparisons and the desktop scheduler.IsFree path are unchanged.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "    const u64 completed_tick = scheduler.GetMasterSemaphore().KnownGpuTick();\n"
    "#endif\n"
    "    for (MsaaScratchImage& scratch : msaa_scratch_images) {",
    "    // No candidate exists on the first allocation: avoid a semaphore\n"
    "    // probe until a cached scratch can actually be reused.\n"
    "    const u64 completed_tick = msaa_scratch_images.empty()\n"
    "        ? 0 : scheduler.GetMasterSemaphore().KnownGpuTick();\n"
    "#endif\n"
    "    for (MsaaScratchImage& scratch : msaa_scratch_images) {",
    "F07 skip GPU completion probe on empty native MSAA scratch list")
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "void TextureCacheRuntime::TickFrame() {\n"
    "    static constexpr u32 MAX_UNUSED_SCRATCH_FRAMES = 60;\n"
    "#ifdef PS5_NATIVE\n"
    "    // One conservative GPU completion sample for both cleanup scans, not a",
    "void TextureCacheRuntime::TickFrame() {\n"
    "    static constexpr u32 MAX_UNUSED_SCRATCH_FRAMES = 60;\n"
    "#ifdef PS5_NATIVE\n"
    "    // With neither MSAA scratch nor resolve retirements pending, there is\n"
    "    // nothing to collect and no reason to sample the GPU semaphore.\n"
    "    if (msaa_scratch_images.empty() && pending_resolve_shadows.empty()) {\n"
    "        return;\n"
    "    }\n"
    "    // One conservative GPU completion sample for both cleanup scans, not a",
    "F07 skip GPU completion probe on empty native MSAA GC frame")
# F07: a nonempty scratch list can still contain no matching image key.
# The GPU completion snapshot is needed only if a matching candidate exists.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "#ifdef PS5_NATIVE\n    // One monotone GPU-completion snapshot for the scratch search. A fence\n    // completed during this scan becomes reusable at the next allocation.\n    // No candidate exists on the first allocation: avoid a semaphore\n    // probe until a cached scratch can actually be reused.\n    const u64 completed_tick = msaa_scratch_images.empty()\n        ? 0 : scheduler.GetMasterSemaphore().KnownGpuTick();\n#endif\n    for (MsaaScratchImage& scratch : msaa_scratch_images) {\n#ifdef PS5_NATIVE\n        if (scratch.key != key || scratch.tick > completed_tick) {\n#else\n        if (scratch.key != key || !scheduler.IsFree(scratch.tick)) {\n#endif\n            continue;\n        }",
    "#ifdef PS5_NATIVE\n    // A scratch with a different image key is never reusable. Avoid sampling\n    // GPU completion unless this allocation actually has a matching candidate;\n    // take at most one monotone snapshot, before comparing its usage tick.\n    u64 completed_tick = 0;\n    bool sampled_completed_tick = false;\n#endif\n    for (MsaaScratchImage& scratch : msaa_scratch_images) {\n#ifdef PS5_NATIVE\n        if (scratch.key != key) {\n            continue;\n        }\n        if (!sampled_completed_tick) {\n            completed_tick = scheduler.GetMasterSemaphore().KnownGpuTick();\n            sampled_completed_tick = true;\n        }\n        if (scratch.tick > completed_tick) {\n#else\n        if (scratch.key != key || !scheduler.IsFree(scratch.tick)) {\n#endif\n            continue;\n        }",
    "F07 avoid native MSAA GPU completion probe without matching image key")
# F07: while every MSAA scratch image is checked out (UINT64_MAX) and there
# are no resolve shadows pending, neither reuse-age nor eviction can advance.
# Avoid the kernel-backed completion snapshot while texture_cache.mutex is held.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "    if (msaa_scratch_images.empty() && pending_resolve_shadows.empty()) {\n        return;\n    }\n    // One conservative GPU completion sample for both cleanup scans, not a",
    "    if (msaa_scratch_images.empty() && pending_resolve_shadows.empty()) {\n        return;\n    }\n    // A live scratch is marked UINT64_MAX until the caller releases it.\n    // With no released scratch and no pending resolve shadow, no frame can\n    // age or retire an image: skip the GPU completion probe entirely.\n    if (pending_resolve_shadows.empty() &&\n        std::all_of(msaa_scratch_images.begin(), msaa_scratch_images.end(),\n                    [](const MsaaScratchImage& scratch) {\n                        return scratch.tick == (std::numeric_limits<u64>::max)();\n                    })) {\n        return;\n    }\n    // One conservative GPU completion sample for both cleanup scans, not a",
    "F07 skip MSAA GPU probe when every scratch image is checked out")

# F07: GPU timestamp diagnostics used to query one completed command buffer
# per Vulkan API call. Keep the normal release path unchanged; the native
# diagnostic path batches up to 32 available timestamp pairs without waiting
# for an unfinished query or crossing the ring boundary.
apply_reviewed_delta("vulkan_scheduler.cpp",
    "    while (gpu_time.first_pending + 1 < gpu_time.next) {\n        const u32 slot = static_cast<u32>(gpu_time.first_pending % GpuTimeProbe::SLOTS);\n        std::array<u64, 2> stamps{};\n        if (device.GetLogical().GetQueryResults(*gpu_time.pool, slot * 2, 2, sizeof(stamps), stamps.data(),\n                                               sizeof(u64), VK_QUERY_RESULT_64_BIT) != VK_SUCCESS) break;\n        const u64 ns = stamps[1] > stamps[0]\n                           ? static_cast<u64>(double(stamps[1] - stamps[0]) * gpu_time.period_ns) : 0;\n        gpu_time.busy_ns += ns;\n        gpu_time.max_ns = (std::max)(gpu_time.max_ns, ns);\n        ++gpu_time.submissions;\n        ++gpu_time.first_pending;\n    }",
    "#ifdef PS5_NATIVE\n    // The optional GPU-time probe previously issued one driver query per\n    // completed command buffer. Fetch up to 32 consecutive timestamp pairs\n    // in one nonblocking call, stopping at the first unavailable pair.\n    // Never cross the 512-slot ring boundary or consume the newest submit.\n    constexpr u32 kQueryBatch = 32;\n    std::array<u64, kQueryBatch * 4> samples{};\n    while (gpu_time.first_pending + 1 < gpu_time.next) {\n        const u32 slot = static_cast<u32>(gpu_time.first_pending % GpuTimeProbe::SLOTS);\n        const u32 candidates = static_cast<u32>((std::min)(\n            u64{kQueryBatch}, gpu_time.next - gpu_time.first_pending - 1));\n        const u32 count = (std::min)(candidates, GpuTimeProbe::SLOTS - slot);\n        // Unavailable results are undefined; clear availability words before\n        // each poll so a reused batch cannot masquerade as completed.\n        samples.fill(0);\n        const VkResult result = device.GetLogical().GetQueryResults(\n            *gpu_time.pool, slot * 2, count * 2, count * 4 * sizeof(u64),\n            samples.data(), 2 * sizeof(u64),\n            VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WITH_AVAILABILITY_BIT);\n        if (result != VK_SUCCESS && result != VK_NOT_READY) break;\n        u32 completed = 0;\n        for (; completed < count; ++completed) {\n            const u64* const pair = samples.data() + completed * 4;\n            if (pair[1] == 0 || pair[3] == 0) break;\n            const u64 ns = pair[2] > pair[0]\n                               ? static_cast<u64>(double(pair[2] - pair[0]) * gpu_time.period_ns) : 0;\n            gpu_time.busy_ns += ns;\n            gpu_time.max_ns = (std::max)(gpu_time.max_ns, ns);\n            ++gpu_time.submissions;\n            ++gpu_time.first_pending;\n        }\n        if (completed != count) break;\n    }\n#else\n    while (gpu_time.first_pending + 1 < gpu_time.next) {\n        const u32 slot = static_cast<u32>(gpu_time.first_pending % GpuTimeProbe::SLOTS);\n        std::array<u64, 2> stamps{};\n        if (device.GetLogical().GetQueryResults(*gpu_time.pool, slot * 2, 2, sizeof(stamps), stamps.data(),\n                                               sizeof(u64), VK_QUERY_RESULT_64_BIT) != VK_SUCCESS) break;\n        const u64 ns = stamps[1] > stamps[0]\n                           ? static_cast<u64>(double(stamps[1] - stamps[0]) * gpu_time.period_ns) : 0;\n        gpu_time.busy_ns += ns;\n        gpu_time.max_ns = (std::max)(gpu_time.max_ns, ns);\n        ++gpu_time.submissions;\n        ++gpu_time.first_pending;\n    }\n#endif",
    "F07 batch native GPU timestamp queries without blocking the Vulkan worker")


# F07 S01: first-use CPU attribution by actual cold graphics/compute cache key.
# Profile only cache misses and the one bounded retry. The print happens after
# the clock stop and cannot inflate measured translation/worker-admission time.
# Keep the generated native C++ byte-for-byte equivalent to the maintained fork.
apply_reviewed_delta(
    "vk_pipeline_cache_cost.cpp",
    "#include <algorithm>\n#include <cstdio>",
    "#include <algorithm>\n#include <chrono>\n#include <cstdio>",
    "F07 keyed cold shader trace chrono include")
apply_reviewed_delta(
    "vk_pipeline_cache_cost.cpp",
    "namespace {\n#ifdef PS5_NATIVE\n// Keep the OPTIONAL graphics optimizer",
    r'''namespace {
#ifdef PS5_NATIVE
// Detailed-only, per-cache-key CPU translation/admission cost. This NEVER
// waits for the Vulkan driver worker and does not run on cache-hit draws.
// The timer ends before emitting its diagnostic, avoiding log-I/O inflation.
struct ColdShaderMissTrace {
    const char* kind;
    u64 key_hash;
    bool retry;
    bool enabled;
    ::Eden::Performance::ShaderMissStageCosts stages{};
    ::Eden::Performance::ShaderMissStageCosts* previous{};
    std::chrono::steady_clock::time_point started{};

    ColdShaderMissTrace(const char* kind_, u64 key_hash_, bool retry_)
        : kind(kind_), key_hash(key_hash_), retry(retry_),
          enabled(::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed)),
          previous(enabled ? ::Eden::Performance::shader_miss_stage_active : nullptr),
          started(enabled ? std::chrono::steady_clock::now()
                          : std::chrono::steady_clock::time_point{}) {
        if (enabled) ::Eden::Performance::shader_miss_stage_active = &stages;
    }
    ColdShaderMissTrace(const ColdShaderMissTrace&) = delete;
    ColdShaderMissTrace& operator=(const ColdShaderMissTrace&) = delete;
    ~ColdShaderMissTrace() {
        if (enabled && ::Eden::Performance::shader_miss_stage_active == &stages)
            ::Eden::Performance::shader_miss_stage_active = previous;
    }
    void Complete(bool success) {
        if (!enabled) return;
        // Stop attributing before print I/O or subsequent cache work.
        if (::Eden::Performance::shader_miss_stage_active == &stages)
            ::Eden::Performance::shader_miss_stage_active = previous;
        const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now() - started).count();
        std::printf("EDEN_VULKAN_SHADER_MISS kind=%s key=%016llx retry=%u "
                    "success=%u cpu_ns=%llu env_ns=%llu pool_ns=%llu "
                    "cfg_ns=%llu ir_ns=%llu spirv_ns=%llu module_ns=%llu\n", kind,
                    static_cast<unsigned long long>(key_hash), unsigned(retry),
                    unsigned(success), static_cast<unsigned long long>(ns),
                    stages.env_ns, stages.pool_ns, stages.cfg_ns, stages.ir_ns,
                    stages.spirv_ns, stages.module_ns);
    }
};
#endif
#ifdef PS5_NATIVE
// Keep the OPTIONAL graphics optimizer''',
    "F07 per-key detailed-only cold shader CPU timer")
apply_reviewed_delta(
    "vk_pipeline_cache_cost.cpp",
    r'''        pipeline = CreateComputePipeline(key, shader);
#ifdef PS5_NATIVE
        if (!pipeline) {''',
    r'''#ifdef PS5_NATIVE
        ColdShaderMissTrace cold_miss{"compute", key.Hash(), false};
#endif
        pipeline = CreateComputePipeline(key, shader);
#ifdef PS5_NATIVE
        first_use_compute_cost.Stop();
        cold_miss.Complete(static_cast<bool>(pipeline));
        if (!pipeline) {''',
    "F07 record exact compute cold first-use CPU cost")
apply_reviewed_delta(
    "vk_pipeline_cache_cost.cpp",
    r'''            pipeline = CreateComputePipeline(key, shader);
            // A consumed retry cannot repeat:''',
    r'''            ColdShaderMissTrace cold_retry{"compute", key.Hash(), true};
            pipeline = CreateComputePipeline(key, shader);
            retry_compute_cost.Stop();
            cold_retry.Complete(static_cast<bool>(pipeline));
            // A consumed retry cannot repeat:''',
    "F07 record exact compute bounded retry CPU cost")
apply_reviewed_delta(
    "vk_pipeline_cache_cost.cpp",
    r'''        pipeline = CreateGraphicsPipeline();
#ifdef PS5_NATIVE
        if (!pipeline) {''',
    r'''#ifdef PS5_NATIVE
        ColdShaderMissTrace cold_miss{"graphics", graphics_key.Hash(), false};
#endif
        pipeline = CreateGraphicsPipeline();
#ifdef PS5_NATIVE
        first_use_cpu_phase.Stop();
        cold_miss.Complete(static_cast<bool>(pipeline));
        if (!pipeline) {''',
    "F07 record exact graphics cold first-use CPU cost")
apply_reviewed_delta(
    "vk_pipeline_cache_cost.cpp",
    r'''            pipeline = CreateGraphicsPipeline();
            // The null graphics_cache entry itself guarantees at most one''',
    r'''            ColdShaderMissTrace cold_retry{"graphics", graphics_key.Hash(), true};
            pipeline = CreateGraphicsPipeline();
            retry_cpu_cost.Stop();
            cold_retry.Complete(static_cast<bool>(pipeline));
            // The null graphics_cache entry itself guarantees at most one''',
    "F07 record exact graphics bounded retry CPU cost")


# F07 V01: measure only genuinely blocked FIFO pipeline callbacks, after
# acquiring build completion. Never log/clock a hot draw or move a Vulkan wait.
# This is worker wall-time, not the duration of a guest presentation frame.
apply_reviewed_delta(
    "vk_graphics_pipeline_cost.cpp",
    "            if (is_built.load(std::memory_order_acquire)) return;\n            auto timer = Eden::Performance::VulkanTimer(16);", "            if (is_built.load(std::memory_order_acquire)) return;\n#ifdef PS5_NATIVE\n            // Publication can race the initial fast acquire. The build owner\n            // holds this mutex when publishing, so a false result here means\n            // the condition wait must actually release the lock.\n            std::unique_lock lock{build_mutex};\n            if (is_built.load(std::memory_order_acquire)) return;\n            ::Eden::Performance::PipelineWaitTrace keyed_wait;\n#endif\n            auto timer = Eden::Performance::VulkanTimer(16);",
    "F07 keyed graphics worker-wait diagnostic admission")
apply_reviewed_delta(
    "vk_compute_pipeline_cost.cpp",
    "            if (is_built.load(std::memory_order_acquire)) return;\n            auto timer = Eden::Performance::VulkanTimer(16);", "            if (is_built.load(std::memory_order_acquire)) return;\n#ifdef PS5_NATIVE\n            // Publication can race the initial fast acquire. The build owner\n            // holds this mutex when publishing, so a false result here means\n            // the condition wait must actually release the lock.\n            std::unique_lock lock{build_mutex};\n            if (is_built.load(std::memory_order_acquire)) return;\n            ::Eden::Performance::PipelineWaitTrace keyed_wait;\n#endif\n            auto timer = Eden::Performance::VulkanTimer(16);",
    "F07 keyed compute worker-wait diagnostic admission")
apply_reviewed_delta(
    "vk_graphics_pipeline_cost.cpp",
    "            std::unique_lock lock{build_mutex};\n            build_condvar.wait(lock, [this] { return is_built.load(std::memory_order::relaxed); });\n        });", "#ifndef PS5_NATIVE\n            std::unique_lock lock{build_mutex};\n#endif\n            build_condvar.wait(lock, [this] { return is_built.load(std::memory_order::relaxed); });\n#ifdef PS5_NATIVE\n            lock.unlock();\n            pipeline_ready_wait.Stop();\n            timer.reset(); // Exclude diagnostic print I/O from VulkanTimer(16).\n            keyed_wait.Complete(\"graphics\", key.Hash(), CanExecuteDraw());\n#endif\n        });",
    "F07 keyed graphics worker-wait after mutex release")
apply_reviewed_delta(
    "vk_compute_pipeline_cost.cpp",
    "            std::unique_lock lock{build_mutex};\n            build_condvar.wait(lock, [this] { return is_built.load(std::memory_order::relaxed); });\n        });", "#ifndef PS5_NATIVE\n            std::unique_lock lock{build_mutex};\n#endif\n            build_condvar.wait(lock, [this] { return is_built.load(std::memory_order::relaxed); });\n#ifdef PS5_NATIVE\n            lock.unlock();\n            pipeline_ready_wait.Stop();\n            timer.reset(); // Exclude diagnostic print I/O from VulkanTimer(16).\n            keyed_wait.Complete(\"compute\", diagnostic_cache_key_hash, IsBound());\n#endif\n        });",
    "F07 keyed compute worker-wait after mutex release")
# V01: align the keyed worker-wait timer's stated scope with the
# actual GPU-owner mutex and condvar latency. The timer is completed only
# after a genuinely unfinished builder; a racing ready build stays quiet.
for pipeline_file in ("vk_graphics_pipeline_cost.cpp", "vk_compute_pipeline_cost.cpp"):
    apply_reviewed_delta(
        pipeline_file,
        "            std::unique_lock lock{build_mutex};\n            if (is_built.load(std::memory_order_acquire)) return;\n            ::Eden::Performance::PipelineWaitTrace keyed_wait;",
        "            // Include contention acquiring build_mutex in the keyed\n            // diagnostic; a genuinely blocked condvar wait must not omit\n            // the GPU worker's preceding mutex delay.\n            ::Eden::Performance::PipelineWaitTrace keyed_wait;\n            std::unique_lock lock{build_mutex};\n            if (is_built.load(std::memory_order_acquire)) return;",
        f"F07 V01 include build mutex acquisition in keyed {pipeline_file} wait")

# V01: split genuinely blocked GPU-worker wait into the build mutex
# contention and post-acquire/condvar portions. The sums use one end stamp.
for pipeline_file in ("vk_graphics_pipeline_cost.cpp", "vk_compute_pipeline_cost.cpp"):
    apply_reviewed_delta(
        pipeline_file,
        "            std::unique_lock lock{build_mutex};\n            if (is_built.load(std::memory_order_acquire)) return;\n#endif\n            auto timer = Eden::Performance::VulkanTimer(16);",
        "            std::unique_lock lock{build_mutex};\n            keyed_wait.MarkLockAcquired();\n            if (is_built.load(std::memory_order_acquire)) return;\n#endif\n            auto timer = Eden::Performance::VulkanTimer(16);",
        f"F07 V01 keyed {pipeline_file} mutex-versus-postlock phase split")

apply_reviewed_delta(
    "include/video_core/renderer_vulkan/vk_compute_pipeline.h",
    "    void PreflightDescriptorScratch();\n    [[nodiscard]] bool HasDescriptorEntries() const noexcept {",
    "    void PreflightDescriptorScratch();\n    // Set before publication from PipelineCache; read by the FIFO GPU callback.\n    void SetDiagnosticCacheKeyHash(u64 hash) noexcept { diagnostic_cache_key_hash = hash; }\n    [[nodiscard]] bool HasDescriptorEntries() const noexcept {",
    "F07 exact compute key setter")
apply_reviewed_delta(
    "include/video_core/renderer_vulkan/vk_compute_pipeline.h",
    "    u64 shader_hash{};\n    u32 num_descriptor_entries{};",
    "    u64 shader_hash{};\n#ifdef PS5_NATIVE\n    u64 diagnostic_cache_key_hash{};\n#endif\n    u32 num_descriptor_entries{};",
    "F07 exact compute key storage")
apply_reviewed_delta(
    "vk_pipeline_cache_cost.cpp",
    "    return std::make_unique<ComputePipeline>(device, scheduler, vulkan_pipeline_cache, descriptor_pool,\n                                             guest_descriptor_queue, descriptor_buffer_ring,\n                                             thread_worker, statistics,\n                                             &shader_notify, program.info, std::move(spv_module),\n                                             key.unique_hash);", "#ifdef PS5_NATIVE\n    auto result = std::make_unique<ComputePipeline>(device, scheduler, vulkan_pipeline_cache, descriptor_pool,\n                                                    guest_descriptor_queue, descriptor_buffer_ring,\n                                                    thread_worker, statistics,\n                                                    &shader_notify, program.info, std::move(spv_module),\n                                                    key.unique_hash);\n    // The shader stage hash is not the compute CACHE key: include workgroup\n    // sizes and shared memory for correlation with S01's exact key.Hash().\n    result->SetDiagnosticCacheKeyHash(key.Hash());\n    return result;\n#else\n    return std::make_unique<ComputePipeline>(device, scheduler, vulkan_pipeline_cache, descriptor_pool,\n                                             guest_descriptor_queue, descriptor_buffer_ring,\n                                             thread_worker, statistics,\n                                             &shader_notify, program.info, std::move(spv_module),\n                                             key.unique_hash);\n#endif",
    "F07 publish diagnostic compute cache key before first Configure")

# F07: Vulkan worker callbacks are FIFO. Do not confuse a pipeline variant
# published AFTER ConfigureDraw with one that ConfigureDraw actually bound.
# The four raster Draw/DrawIndirect callbacks observe this per-worker latch.
apply_reviewed_delta(
    "vk_graphics_pipeline_cost.cpp",
    """        const bool use_optimized = optimized_ready.load(std::memory_order_acquire);
        if (!pipeline && !use_optimized) {""",
    """        const bool use_optimized = optimized_ready.load(std::memory_order_acquire);
#ifdef PS5_NATIVE
        // Reset BEFORE any early failure. Availability observed by a later
        // Draw callback is insufficient: its ConfigureDraw may already have
        // returned without binding anything when the rebuild was still cold.
        worker_draw_bind_valid = false;
#endif
        if (!pipeline && !use_optimized) {""",
    "F07 native worker bound-pipeline validity reset")
apply_reviewed_delta(
    "vk_graphics_pipeline_cost.cpp",
    """        if (bind_pipeline || (use_optimized != optimized_at_record)) {
            cmdbuf.BindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS,
                                use_optimized ? *optimized_pipeline : *pipeline);
        }
        cmdbuf.PushConstants""",
    """        if (bind_pipeline || (use_optimized != optimized_at_record)) {
            cmdbuf.BindPipeline(VK_PIPELINE_BIND_POINT_GRAPHICS,
                                use_optimized ? *optimized_pipeline : *pipeline);
        }
#ifdef PS5_NATIVE
        // This callback precedes its Draw/DrawIndirect in scheduler FIFO.
        // A late optimized-ready signal cannot retroactively validate an
        // earlier skipped BindPipeline.
        worker_draw_bind_valid = true;
#endif
        cmdbuf.PushConstants""",
    "F07 native worker bound-pipeline validity publish")


# F07 T04: the MSAA staging image is checked out with tick UINT64_MAX.
# Exceptions while queuing upload/copy/blit must return it to the retirement
# ring using the *current scheduler tick*, never to immediate GPU reuse.
# Keep successful release at the original call site; the scope guard runs
# only for failed work. No change to desktop code paths.
apply_reviewed_delta(
    "vk_texture_cache_cost.cpp",
    "#include <algorithm>\n#include <cstdio>",
    '#include <algorithm>\n#include "common/scope_exit.h"\n#include <cstdio>',
    "F07 MSAA scratch failure-guard include")
apply_reviewed_delta(
    "vk_texture_cache_cost.cpp",
    """        const VkImage temp_vk_image = runtime->AcquireMsaaScratchImage(image_ci);

        scheduler->RequestOutsideRenderPassOperationContext();""",
    """        const VkImage temp_vk_image = runtime->AcquireMsaaScratchImage(image_ci);
#ifdef PS5_NATIVE
        // An allocation, Vulkan Record or blit failure before the ordinary
        // Release leaves this scratch at UINT64_MAX ("checked out") forever.
        // Return it against CurrentTick even when partially enqueued GPU
        // commands must still retire; never make it reusable immediately.
        bool scratch_released = false;
        SCOPE_EXIT {
            if (!scratch_released) runtime->ReleaseMsaaScratchImage(temp_vk_image);
        };
#endif

        scheduler->RequestOutsideRenderPassOperationContext();""",
    "F07 MSAA upload scratch exception safe release")
apply_reviewed_delta(
    "vk_texture_cache_cost.cpp",
    """        initialized = true;
        runtime->ReleaseMsaaScratchImage(temp_vk_image);

        if (is_rescaled) {""",
    """        initialized = true;
        runtime->ReleaseMsaaScratchImage(temp_vk_image);
#ifdef PS5_NATIVE
        scratch_released = true;
#endif

        if (is_rescaled) {""",
    "F07 MSAA upload scratch normal release unchanged")


# F07 T04: MSAA readback uses the same scratch-pool admission as uploads.
# An exception during image-copy staging, Vulkan record or resolve must
# retire the checked-out image against the GPU tick, not leak it forever.
apply_reviewed_delta(
    "vk_texture_cache_cost.cpp",
    """            const VkImage temp_vk_image = runtime->AcquireMsaaScratchImage(image_ci);

            const VkImageAspectFlags temp_aspect_mask = aspect_mask;""",
    """            const VkImage temp_vk_image = runtime->AcquireMsaaScratchImage(image_ci);
#ifdef PS5_NATIVE
            // A rejected Record, failed blit or staging allocation must not
            // strand this scratch at UINT64_MAX. The returned CurrentTick
            // still protects commands already submitted to the GPU worker.
            bool scratch_released = false;
            SCOPE_EXIT {
                if (!scratch_released) runtime->ReleaseMsaaScratchImage(temp_vk_image);
            };
#endif

            const VkImageAspectFlags temp_aspect_mask = aspect_mask;""",
    "F07 MSAA download scratch failure release")
apply_reviewed_delta(
    "vk_texture_cache_cost.cpp",
    """            runtime->ReleaseMsaaScratchImage(temp_vk_image);
        }
        if (is_rescaled) {""",
    """            runtime->ReleaseMsaaScratchImage(temp_vk_image);
#ifdef PS5_NATIVE
            scratch_released = true;
#endif
        }
        if (is_rescaled) {""",
    "F07 MSAA download scratch success release unchanged")


# F07 T04: memory allocators can return a null Vulkan image without throwing.
# A null scratch must not enter the cached MSAA pool, nor be used in blits.
apply_reviewed_delta(
    "vk_texture_cache_cost.cpp",
    """    MsaaScratchImage scratch{
        .key = key,
        .image = memory_allocator.CreateImage(image_ci),
        .tick = (std::numeric_limits<u64>::max)(),
        .unused_frames = 0,
    };
    const VkImage handle = *scratch.image;""",
    """    MsaaScratchImage scratch{
        .key = key,
        .image = memory_allocator.CreateImage(image_ci),
        .tick = (std::numeric_limits<u64>::max)(),
        .unused_frames = 0,
    };
#ifdef PS5_NATIVE
    // Some allocation backends report failure as an empty Vulkan image
    // without throwing. Never cache it or submit a null VkImage as MSAA
    // resolve scratch; the caller must take its existing failure path.
    if (!scratch.image) {
        throw std::bad_alloc{};
    }
#endif
    const VkImage handle = *scratch.image;""",
    "F07 MSAA null scratch image rejected before caching")


# F07 T04/M02: skip no-op readback before any rescale, MSAA scratch,
# staging or Vulkan command. Malformed destination arrays must throw rather
# than silently claim a dirty image's data was downloaded.
apply_reviewed_delta(
    "vk_texture_cache_cost.cpp",
    """void Image::DownloadMemory(std::span<VkBuffer> buffers_span, std::span<size_t> offsets_span,
                            std::span<const VideoCommon::BufferImageCopy> copies) {
    const bool is_rescaled = True(flags & ImageFlagBits::Rescaled);""",
    """void Image::DownloadMemory(std::span<VkBuffer> buffers_span, std::span<size_t> offsets_span,
                            std::span<const VideoCommon::BufferImageCopy> copies) {
#ifdef PS5_NATIVE
    // A readback without copy regions has no guest bytes to return. Avoid
    // scaling, a scratch acquisition and even a zero-command Vulkan Record.
    if (copies.empty()) {
        return;
    }
    // Every copy batch indexes both parallel destination arrays. A malformed
    // caller must fail before recording GPU writes; a silent return here
    // would let dirty texture eviction treat uncopied guest bytes as valid.
    if (buffers_span.empty() || offsets_span.size() != buffers_span.size()) {
        throw std::invalid_argument("Malformed Vulkan texture readback batch");
    }
#endif
    const bool is_rescaled = True(flags & ImageFlagBits::Rescaled);""",
    "F07 empty and malformed GPU readback preflight")


# F07 M02: empty download regions must not project dirty guest data as
# evicted, or be swizzled from uninitialized Vulkan staging. The native-only
# guards run before both GC prefetch and fallback dirty eviction.
apply_reviewed_delta(
    "vulkan-cache/video_core/texture_cache/texture_cache.h",
    """                if (!dirty || !image.aliased_images.empty() || !image.overlapping_images.empty() ||
                    image.info.num_samples != 1 ||
                    image.unswizzled_size_bytes > 32_MiB)
                    return NoteProjectedEviction(image);
                // Full descriptor/byte capacity is a true batch boundary.""",
    """                if (!dirty || !image.aliased_images.empty() || !image.overlapping_images.empty() ||
                    image.info.num_samples != 1 ||
                    image.unswizzled_size_bytes > 32_MiB)
                    return NoteProjectedEviction(image);
#ifdef PS5_NATIVE
                // A no-region download is not a successful readback of dirty
                // GPU bytes. Do not prefetch, or project this image evicted:
                // Cleanup must leave it resident until guest copy regions
                // can be represented.
                if (FullDownloadCopies(image.info).empty()) return false;
#endif
                // Full descriptor/byte capacity is a true batch boundary.""",
    "F07 preserve dirty image when prefetch has no readback copy regions")
apply_reviewed_delta(
    "vulkan-cache/video_core/texture_cache/texture_cache.h",
    """        if (must_download && !UsePrefetched(image_id, image)) {
#ifdef PS5_NATIVE
            // Never evict dirty GPU bytes if the fallback guest readback could""",
    """        if (must_download && !UsePrefetched(image_id, image)) {
#ifdef PS5_NATIVE
            // A zero-region readback leaves the staging bytes undefined.
            // Never SwizzleImage those bytes or delete the only dirty GPU
            // copy; keep it resident and retry on a later eligible frame.
            if (FullDownloadCopies(image.info).empty()) {
                ++skipped;
                return false;
            }
            // Never evict dirty GPU bytes if the fallback guest readback could""",
    "F07 preserve dirty image on zero-region fallback readback")


# F07 M02: dirty GC prefetch can enqueue GPU copies before the staging batch
# fails. Drain partially queued commands and retire every held staging map,
# then keep the dirty guest image resident. Preserve desktop unchanged.
apply_reviewed_delta(
    "vulkan-cache/video_core/texture_cache/texture_cache.h",
    "#ifdef PS5_NATIVE\n#include <exception>\n#include <new>\n#endif",
    "#ifdef PS5_NATIVE\n#include <exception>\n#include <new>\n#include <stdexcept>\n#endif",
    "F07 dirty GC prefetch exception type header")
apply_reviewed_delta(
    "vulkan-cache/video_core/texture_cache/texture_cache.h",
    """                // The pinned StagingBufferRef is a POD handle, not a RAII
                // owner. The pool tracks deferred lifetime until FreeDeferred.
                gc_downloads.emplace_back(id, map);
                const auto copies = FixSmallVectorADL(FullDownloadCopies(image.info));
                image.DownloadMemory(map, copies);
                bytes += image.unswizzled_size_bytes;""",
    """                // The pinned StagingBufferRef is a POD handle, not a RAII
                // owner. The pool tracks deferred lifetime until FreeDeferred.
#ifdef PS5_NATIVE
                // Do not let a failed Record/download advertise this texture
                // as prefetched. Some commands may already be queued, so the
                // staging maps must retire only AFTER draining those commands.
                bool map_owned_by_batch = false;
                SCOPE_EXIT {
                    if (!map_owned_by_batch) runtime.FreeDeferredStagingBuffer(map);
                };
                const auto RetireFailedBatch = [&] {
                    if (!gc_downloads.empty()) runtime.Finish();
                    ReleaseDownloads();
                };
                try {
                    gc_downloads.emplace_back(id, map);
                    map_owned_by_batch = true;
                    const auto copies = FixSmallVectorADL(FullDownloadCopies(image.info));
                    image.DownloadMemory(map, copies);
                } catch (const std::bad_alloc&) {
                    RetireFailedBatch();
                    return true;
                } catch (const std::invalid_argument&) {
                    RetireFailedBatch();
                    return true;
                } catch (...) {
                    RetireFailedBatch();
                    throw;
                }
#else
                gc_downloads.emplace_back(id, map);
                const auto copies = FixSmallVectorADL(FullDownloadCopies(image.info));
                image.DownloadMemory(map, copies);
#endif
                bytes += image.unswizzled_size_bytes;""",
    "F07 rollback partial Vulkan dirty GC prefetch before staging release")

# F07 C01/C03: sampled frame-housekeeping ownership, GPU thread only.
# Same texture-then-buffer acquisition and same TickFrame call ordering.
# No driver wait, allocation or telemetry in the quiet path.
apply_reviewed_delta(
    "vulkan_rasterizer.cpp",
    "void RasterizerVulkan::TickFrame() {\n    draw_counter = 0;\n    guest_descriptor_queue.TickFrame();\n    compute_pass_descriptor_queue.TickFrame();\n    descriptor_buffer_ring.TickFrame();\n    fence_manager.TickFrame();\n    staging_pool.TickFrame();\n    {\n        std::scoped_lock lock{texture_cache.mutex};\n        texture_cache.TickFrame();\n    }\n    {\n        std::scoped_lock lock{buffer_cache.mutex};\n        buffer_cache.TickFrame();\n    }\n}",
    "void RasterizerVulkan::TickFrame() {\n    draw_counter = 0;\n    guest_descriptor_queue.TickFrame();\n    compute_pass_descriptor_queue.TickFrame();\n    descriptor_buffer_ring.TickFrame();\n    fence_manager.TickFrame();\n    staging_pool.TickFrame();\n#ifdef PS5_NATIVE\n    // C01/C03: identify who holds the cache lock during frame housekeeping.\n    // One of 16 frames with detailed logging; no clocks or changed locks in\n    // quiet release. Wait and held intervals use disjoint timer scopes.\n    const bool frame_sample = ::Eden::Performance::ShouldSampleCacheFrame();\n#endif\n    {\n#ifdef PS5_NATIVE\n        ::Eden::Performance::CachePhaseTimer texture_wait{\n            ::Eden::Performance::CachePhase::FrameTextureWait, frame_sample};\n#endif\n        std::scoped_lock lock{texture_cache.mutex};\n#ifdef PS5_NATIVE\n        texture_wait.Stop();\n        ::Eden::Performance::CachePhaseTimer texture_held{\n            ::Eden::Performance::CachePhase::FrameTextureHeld, frame_sample};\n#endif\n        texture_cache.TickFrame();\n    }\n    {\n#ifdef PS5_NATIVE\n        ::Eden::Performance::CachePhaseTimer buffer_wait{\n            ::Eden::Performance::CachePhase::FrameBufferWait, frame_sample};\n#endif\n        std::scoped_lock lock{buffer_cache.mutex};\n#ifdef PS5_NATIVE\n        buffer_wait.Stop();\n        ::Eden::Performance::CachePhaseTimer buffer_held{\n            ::Eden::Performance::CachePhase::FrameBufferHeld, frame_sample};\n#endif\n        buffer_cache.TickFrame();\n    }\n}",
    "F07 frame GC texture and buffer lock ownership instrumentation")


# F07 C03: exact memory-budget/GC time and bounded sampled housekeeping.
# Keep budget, collection, retirement and deferred releases in original order.
apply_reviewed_delta(
    "vulkan-cache/video_core/texture_cache/texture_cache.h",
    "void TextureCache<P>::TickFrame() {\n    // If we can obtain the memory info, use it instead of the estimate.\n    if (runtime.CanReportMemoryUsage()) {\n#ifdef PS5_NATIVE\n        // A driver memory-budget probe can run under texture_cache.mutex.\n        // While comfortably below the GC watermark, sample every other\n        // frame; at 2/3 of the watermark or higher, sample EVERY frame to\n        // preserve prompt reclaim and avoid an allocation-pressure blind spot.\n        const bool near_gc_watermark =\n            total_used_memory >= minimum_memory - minimum_memory / 3;\n        if (near_gc_watermark || (frame_tick & 1u) == 0) {\n            total_used_memory = runtime.GetDeviceMemoryUsage();\n        }\n#else\n        total_used_memory = runtime.GetDeviceMemoryUsage();\n#endif\n    }\n    if (total_used_memory > minimum_memory) {\n        RunGarbageCollector();\n    }\n    sentenced_images.Tick();\n    sentenced_framebuffers.Tick();\n    sentenced_image_view.Tick();\n    TickAsyncDecode();\n    TickAsyncUnswizzle();\n\n    runtime.TickFrame();\n    ++frame_tick;\n\n    if constexpr (IMPLEMENTS_ASYNC_DOWNLOADS) {\n        for (auto& buffer : async_buffers_death_ring) {\n            runtime.FreeDeferredStagingBuffer(buffer);\n        }\n        async_buffers_death_ring.clear();\n    }\n}",
    "void TextureCache<P>::TickFrame() {\n#ifdef PS5_NATIVE\n    // C03: exact driver budget/GC events plus 1-in-16 async/runtime samples.\n    // Timers run only in Detailed Logging; the order and cache locks remain.\n    const bool detailed = ::Eden::Performance::detailed_gpu_profile.load(std::memory_order_relaxed);\n    const bool sample_housekeeping = detailed && ::Eden::Performance::ShouldSampleTextureHousekeeping();\n#endif\n    // If we can obtain the memory info, use it instead of the estimate.\n    if (runtime.CanReportMemoryUsage()) {\n#ifdef PS5_NATIVE\n        // A driver memory-budget probe can run under texture_cache.mutex.\n        // While comfortably below the GC watermark, sample every other\n        // frame; at 2/3 of the watermark or higher, sample EVERY frame to\n        // preserve prompt reclaim and avoid an allocation-pressure blind spot.\n        const bool near_gc_watermark =\n            total_used_memory >= minimum_memory - minimum_memory / 3;\n        if (near_gc_watermark || (frame_tick & 1u) == 0) {\n            ::Eden::Performance::CachePhaseTimer budget_query{\n                ::Eden::Performance::CachePhase::TextureBudgetQuery, detailed};\n            total_used_memory = runtime.GetDeviceMemoryUsage();\n        }\n#else\n        total_used_memory = runtime.GetDeviceMemoryUsage();\n#endif\n    }\n    if (total_used_memory > minimum_memory) {\n#ifdef PS5_NATIVE\n        ::Eden::Performance::CachePhaseTimer gc_collect{\n            ::Eden::Performance::CachePhase::TextureGcCollect, detailed};\n#endif\n        RunGarbageCollector();\n    }\n    sentenced_images.Tick();\n    sentenced_framebuffers.Tick();\n    sentenced_image_view.Tick();\n#ifdef PS5_NATIVE\n    ::Eden::Performance::CachePhaseTimer async_tick{\n        ::Eden::Performance::CachePhase::TextureAsyncTick, sample_housekeeping};\n#endif\n    TickAsyncDecode();\n    TickAsyncUnswizzle();\n#ifdef PS5_NATIVE\n    async_tick.Stop();\n    ::Eden::Performance::CachePhaseTimer runtime_tick{\n        ::Eden::Performance::CachePhase::TextureRuntimeTick, sample_housekeeping};\n#endif\n    runtime.TickFrame();\n#ifdef PS5_NATIVE\n    runtime_tick.Stop();\n#endif\n    ++frame_tick;\n\n    if constexpr (IMPLEMENTS_ASYNC_DOWNLOADS) {\n        for (auto& buffer : async_buffers_death_ring) {\n            runtime.FreeDeferredStagingBuffer(buffer);\n        }\n        async_buffers_death_ring.clear();\n    }\n}",
    "F07 texture frame GC and driver probe phase attribution")

# F07 P0.4: avoid heap work and copy conversion on rejected reinterpret
# batches while the texture cache owns its mutex; valid GPU ordering unchanged.
apply_reviewed_delta("vk_texture_cache_cost.cpp",
    "    boost::container::small_vector<VkBufferImageCopy, 16> vk_in_copies(copies.size());\n    boost::container::small_vector<VkBufferImageCopy, 16> vk_out_copies(copies.size());\n    const VkImageAspectFlags src_aspect_mask = src.AspectMask();\n    const VkImageAspectFlags dst_aspect_mask = dst.AspectMask();\n\n#ifdef PS5_NATIVE\n    // Do not divide by an invalid format width or truncate converted source\n    // coordinates before the scratch-size check. Conversion is calculated\n    // wide, but must still fit the signed offset and unsigned Vk extent.\n    const auto src_block_width = DefaultBlockWidth(src.info.format);\n    const auto dst_block_width = DefaultBlockWidth(dst.info.format);\n    if (src_block_width == 0 || dst_block_width == 0) {\n        return;\n    }\n    const auto bpp_in = BytesPerBlock(src.info.format) / src_block_width;\n    const auto bpp_out = BytesPerBlock(dst.info.format) / dst_block_width;\n    if (bpp_in == 0 || bpp_out == 0) {\n        return;\n    }\n    for (const auto& copy : copies) {\n        if (static_cast<s64>(copy.src_offset.x) < 0) {\n            return;\n        }\n        const u64 scaled_offset =\n            (static_cast<u64>(bpp_out) * static_cast<u64>(copy.src_offset.x)) / bpp_in;\n        const u64 scaled_width =\n            (static_cast<u64>(bpp_out) * copy.extent.width) / bpp_in;\n        if (scaled_offset > static_cast<u64>(\n                (std::numeric_limits<decltype(copy.src_offset.x)>::max)()) ||\n            scaled_width == 0 || scaled_width > static_cast<u64>(\n                (std::numeric_limits<decltype(copy.extent.width)>::max)())) {\n            return;\n        }\n    }\n#else\n    const auto bpp_in = BytesPerBlock(src.info.format) / DefaultBlockWidth(src.info.format);\n    const auto bpp_out = BytesPerBlock(dst.info.format) / DefaultBlockWidth(dst.info.format);\n#endif\n    std::ranges::transform(copies, vk_in_copies.begin(),\n                           [src_aspect_mask, bpp_in, bpp_out](const auto& copy) {\n                               auto copy2 = copy;\n#ifdef PS5_NATIVE\n                               copy2.src_offset.x = static_cast<decltype(copy2.src_offset.x)>(\n                                   (static_cast<u64>(bpp_out) * static_cast<u64>(copy.src_offset.x)) / bpp_in);\n                               copy2.extent.width = static_cast<decltype(copy2.extent.width)>(\n                                   (static_cast<u64>(bpp_out) * copy.extent.width) / bpp_in);\n#else\n                               copy2.src_offset.x = (bpp_out * copy.src_offset.x) / bpp_in;\n                               copy2.extent.width = (bpp_out * copy.extent.width) / bpp_in;\n#endif\n                               return MakeBufferImageCopy(copy2, true, src_aspect_mask);\n                           });\n    std::ranges::transform(copies, vk_out_copies.begin(), [dst_aspect_mask](const auto& copy) {\n        return MakeBufferImageCopy(copy, false, dst_aspect_mask);\n    });\n    const u32 img_bpp = BytesPerBlock(dst.info.format);\n    size_t total_size = 0;\n#ifdef PS5_NATIVE\n    // Prevent u32 intermediate overflow and size_t wrap before asking for\n    // a scratch VkBuffer. Invalid extents cannot be recorded as Vulkan copies.\n    constexpr size_t max_size = (std::numeric_limits<size_t>::max)();\n    for (const auto& copy : copies) {\n        const size_t width = copy.extent.width;\n        const size_t height = copy.extent.height;\n        const size_t depth = copy.extent.depth;\n        if (width == 0 || height == 0 || depth == 0 || img_bpp == 0 ||\n            width > max_size / height) {\n            return;\n        }\n        const size_t area = width * height;\n        if (area > max_size / depth) {\n            return;\n        }\n        const size_t volume = area * depth;\n        if (volume > max_size / img_bpp) {\n            return;\n        }\n        const size_t bytes = volume * img_bpp;\n        if (total_size > max_size - bytes) {\n            return;\n        }\n        total_size += bytes;\n    }\n    // GetTemporaryBuffer indexes an array of 8*sizeof(size_t) buffers with\n    // ceil(log2(size)). Values above the highest power of two index the\n    // array one past its end even though size_t arithmetic did not overflow.\n    constexpr size_t scratch_max = size_t{1} << (std::numeric_limits<size_t>::digits - 1);\n    if (total_size > scratch_max) {\n        return;\n    }\n#else\n    for (const auto& copy : copies) {\n        total_size += copy.extent.width * copy.extent.height * copy.extent.depth * img_bpp;\n    }\n#endif\n",
    "    // Scratch vectors are created after native extent and budget validation.\n    const VkImageAspectFlags src_aspect_mask = src.AspectMask();\n    const VkImageAspectFlags dst_aspect_mask = dst.AspectMask();\n\n#ifdef PS5_NATIVE\n    // Do not divide by an invalid format width or truncate converted source\n    // coordinates before the scratch-size check. Conversion is calculated\n    // wide, but must still fit the signed offset and unsigned Vk extent.\n    const auto src_block_width = DefaultBlockWidth(src.info.format);\n    const auto dst_block_width = DefaultBlockWidth(dst.info.format);\n    if (src_block_width == 0 || dst_block_width == 0) {\n        return;\n    }\n    const auto bpp_in = BytesPerBlock(src.info.format) / src_block_width;\n    const auto bpp_out = BytesPerBlock(dst.info.format) / dst_block_width;\n    if (bpp_in == 0 || bpp_out == 0) {\n        return;\n    }\n    for (const auto& copy : copies) {\n        if (static_cast<s64>(copy.src_offset.x) < 0) {\n            return;\n        }\n        const u64 scaled_offset =\n            (static_cast<u64>(bpp_out) * static_cast<u64>(copy.src_offset.x)) / bpp_in;\n        const u64 scaled_width =\n            (static_cast<u64>(bpp_out) * copy.extent.width) / bpp_in;\n        if (scaled_offset > static_cast<u64>(\n                (std::numeric_limits<decltype(copy.src_offset.x)>::max)()) ||\n            scaled_width == 0 || scaled_width > static_cast<u64>(\n                (std::numeric_limits<decltype(copy.extent.width)>::max)())) {\n            return;\n        }\n    }\n#else\n    const auto bpp_in = BytesPerBlock(src.info.format) / DefaultBlockWidth(src.info.format);\n    const auto bpp_out = BytesPerBlock(dst.info.format) / DefaultBlockWidth(dst.info.format);\n#endif\n    const u32 img_bpp = BytesPerBlock(dst.info.format);\n    size_t total_size = 0;\n#ifdef PS5_NATIVE\n    // Prevent u32 intermediate overflow and size_t wrap before asking for\n    // a scratch VkBuffer. Invalid extents cannot be recorded as Vulkan copies.\n    constexpr size_t max_size = (std::numeric_limits<size_t>::max)();\n    for (const auto& copy : copies) {\n        const size_t width = copy.extent.width;\n        const size_t height = copy.extent.height;\n        const size_t depth = copy.extent.depth;\n        if (width == 0 || height == 0 || depth == 0 || img_bpp == 0 ||\n            width > max_size / height) {\n            return;\n        }\n        const size_t area = width * height;\n        if (area > max_size / depth) {\n            return;\n        }\n        const size_t volume = area * depth;\n        if (volume > max_size / img_bpp) {\n            return;\n        }\n        const size_t bytes = volume * img_bpp;\n        if (total_size > max_size - bytes) {\n            return;\n        }\n        total_size += bytes;\n    }\n    // GetTemporaryBuffer indexes an array of 8*sizeof(size_t) buffers with\n    // ceil(log2(size)). Values above the highest power of two index the\n    // array one past its end even though size_t arithmetic did not overflow.\n    constexpr size_t scratch_max = size_t{1} << (std::numeric_limits<size_t>::digits - 1);\n    if (total_size > scratch_max) {\n        return;\n    }\n#else\n    for (const auto& copy : copies) {\n        total_size += copy.extent.width * copy.extent.height * copy.extent.depth * img_bpp;\n    }\n#endif\n    // Rejected reinterpret copies must not allocate or convert while holding the texture lock.\n    boost::container::small_vector<VkBufferImageCopy, 16> vk_in_copies(copies.size());\n    boost::container::small_vector<VkBufferImageCopy, 16> vk_out_copies(copies.size());\n    std::ranges::transform(copies, vk_in_copies.begin(),\n                           [src_aspect_mask, bpp_in, bpp_out](const auto& copy) {\n                               auto copy2 = copy;\n#ifdef PS5_NATIVE\n                               copy2.src_offset.x = static_cast<decltype(copy2.src_offset.x)>(\n                                   (static_cast<u64>(bpp_out) * static_cast<u64>(copy.src_offset.x)) / bpp_in);\n                               copy2.extent.width = static_cast<decltype(copy2.extent.width)>(\n                                   (static_cast<u64>(bpp_out) * copy.extent.width) / bpp_in);\n#else\n                               copy2.src_offset.x = (bpp_out * copy.src_offset.x) / bpp_in;\n                               copy2.extent.width = (bpp_out * copy.extent.width) / bpp_in;\n#endif\n                               return MakeBufferImageCopy(copy2, true, src_aspect_mask);\n                           });\n    std::ranges::transform(copies, vk_out_copies.begin(), [dst_aspect_mask](const auto& copy) {\n        return MakeBufferImageCopy(copy, false, dst_aspect_mask);\n    });\n",
    "F07 preflight reinterpret before allocating Vulkan copy vectors")

# F07 P0.4: PrepareImage already touches this exact image as its final
# operation. Preserve desktop legacy, avoid the second native DMA LRU touch.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    PrepareImage(dst_id, mark_as_modified, false);\n    const auto& new_image = slot_images[dst_id];\n    lru_cache.Touch(new_image.lru_index, frame_tick);\n    return std::make_pair(base->level, base->layer);",
    "    PrepareImage(dst_id, mark_as_modified, false);\n#ifndef PS5_NATIVE\n    const auto& new_image = slot_images[dst_id];\n    lru_cache.Touch(new_image.lru_index, frame_tick);\n#else\n    // PrepareImage already touched the same LRU entry at the end; a second\n    // immediate touch adds list work under the texture mutex for DMA uploads.\n#endif\n    return std::make_pair(base->level, base->layer);",
    "F07 avoid duplicate native DMA image LRU touch")

# F07 T01: the texture mutex keeps candidate ticks stable for this DMA scan.
# Track the winning tick locally, rather than reindexing SlotVector for each match.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    const auto consider_candidate = [&](ImageId id, const ImageBase& image) {\n        if (!image_id ||\n            slot_images[image_id].modification_tick < image.modification_tick) {\n            image_id = id;\n        }\n    };",
    "    // Keep the winning timestamp in a register. Reloading the previous\n    // slot image for every candidate adds a cache lookup under texture lock.\n    std::uint64_t newest_candidate_tick = 0;\n    const auto consider_candidate = [&](ImageId id, const ImageBase& image) {\n        if (!image_id || newest_candidate_tick < image.modification_tick) {\n            image_id = id;\n            newest_candidate_tick = image.modification_tick;\n        }\n    };",
    "F07 reuse newest DMA candidate tick without slot vector relookup")

# F07 C04: sample candidate modification_tick once; previous winner's tick
# stays stable while the texture cache mutex owns this framebuffer selection.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    ImageId freshest_id{};\n    bool freshest_found = false;",
    "    ImageId freshest_id{};\n    bool freshest_found = false;\n    std::uint64_t freshest_tick{};",
    "F07 retain newest present candidate tick within cache scan declaration")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        if (!freshest_found ||\n            slot_images[freshest_id].modification_tick < image.modification_tick) {\n            freshest_id = map.image_id;\n            freshest_found = true;\n        }",
    "        if (!freshest_found ||\n            freshest_tick < image.modification_tick) {\n            freshest_id = map.image_id;\n            freshest_tick = image.modification_tick;\n            freshest_found = true;\n        }",
    "F07 retain newest present candidate tick within cache scan comparison")

# F07 texture hot path: most standalone HUD images have no alias graph.
# This is a pure early return before allocating the scan vector.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "    if (image.modification_tick == modification_tick) {\n        return;\n    }\n#endif\n    // Avoid constructing the inline alias vector on a common no-op HUD lookup.",
    "    if (image.modification_tick == modification_tick) {\n        return;\n    }\n    // No alias graph means no scan/copy, regardless of the global tick.\n    // Avoid constructing the vector and sampling the cache lock phase.\n    if (image.aliased_images.empty()) {\n        return;\n    }\n#endif\n    // Avoid constructing the inline alias vector on a common no-op HUD lookup.",
    "F07 avoid alias scan setup for native images without aliases")

# F07 C02: the per-draw TIC memo has no possible hit for one sampled
# view or a blacklist pass. Preserve its full cache for multi-view draws.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        std::array<ViewMemo, 16> view_memo{};",
    "        // A single view or blacklist pass never gets a memo hit. Avoid\n        // zeroing all 16 memo slots while holding the texture-cache lock.\n        std::optional<std::array<ViewMemo, 16>> view_memo;\n        if (!blacklist && views.size() > 1) {\n            view_memo.emplace();\n        }",
    "F07 initialize native TIC memo only for multi-view non-blacklist draws storage")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "            if (!blacklist && !has_deleted_images) {\n                const auto& cached = view_memo[view.index & 15U];",
    "            if (view_memo && !has_deleted_images) {\n                const auto& cached = (*view_memo)[view.index & 15U];",
    "F07 initialize native TIC memo only for multi-view non-blacklist draws 0")
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "            if (!blacklist && !has_deleted_images) {\n                auto& cached = view_memo[view.index & 15U];",
    "            if (view_memo && !has_deleted_images) {\n                auto& cached = (*view_memo)[view.index & 15U];",
    "F07 initialize native TIC memo only for multi-view non-blacklist draws 1")

# F07 V05/C01: a writable multi-range cannot use the gathered fallback.
# When the device has no sparse-binding capability, bypass the doomed GPU
# allocation and its cache/retirement work. Read-only and desktop paths stay.
apply_reviewed_delta("vk_buffer_cache_cost.cpp",
    "    if (multi_range_sources.empty() || multi_range_total == 0) {\n        return false;\n    }\n    const MultiRangeRef ref = multi_range_buffers.Get(device, scheduler, memory_allocator, key,",
    "    if (multi_range_sources.empty() || multi_range_total == 0) {\n        return false;\n    }\n#ifdef PS5_NATIVE\n    // A gathered buffer cannot be bound for GPU writes. If sparse binding\n    // is unavailable globally, don't construct and cache a doomed Vulkan\n    // fallback allocation just to reject it below while holding cache locks.\n    if (is_written && !multi_range_buffers.use_sparse) {\n        return false;\n    }\n#endif\n    const MultiRangeRef ref = multi_range_buffers.Get(device, scheduler, memory_allocator, key,",
    "F07 reject unsupported native writable multirange before fallback allocation")

# F07 C01/V05: during a multi-range deferred-release scan, sample GPU
# completion once. All entries have monotonically increasing fence ticks,
# so one conservative snapshot can only delay, never prematurely free them.
apply_reviewed_delta("vk_multi_range_buffer_cost.cpp",
    "void MultiRangeBufferCache::DrainRetired(Scheduler& scheduler) {\n    size_t index = 0;\n    while (index < retired.size()) {\n        if (scheduler.IsFree(retired[index].tick)) {",
    "void MultiRangeBufferCache::DrainRetired(Scheduler& scheduler) {\n#ifdef PS5_NATIVE\n    // A single conservative GPU completion snapshot avoids a driver query\n    // for every retired allocation while the guest cache owner is active.\n    if (retired.empty()) {\n        return;\n    }\n    const u64 completed_tick = scheduler.GetMasterSemaphore().KnownGpuTick();\n#endif\n    size_t index = 0;\n    while (index < retired.size()) {\n#ifdef PS5_NATIVE\n        if (retired[index].tick <= completed_tick) {\n#else\n        if (scheduler.IsFree(retired[index].tick)) {\n#endif",
    "F07 snapshot native multi-range retirement GPU completion once per pass")

# F07 C01: sparse Vulkan bindings alias live memory; only gathered copies
# require content/write_tick hashing to decide when to upload fresh bytes.
apply_reviewed_delta("vk_multi_range_buffer_cost.cpp",
    "    const u64 geometry = HashSources(sources);\n    const u64 content = HashContent(sources);\n    const auto it = entries.find(key);\n    if (it != entries.end() && it->second.geometry == geometry && it->second.size == total) {",
    "    const u64 geometry = HashSources(sources);\n#ifdef PS5_NATIVE\n    const auto it = entries.find(key);\n    // A sparse binding reads its original backing memory directly. Guest\n    // write ticks cannot stale it, unlike the gathered copy. Skip the\n    // second source walk and dirty-state bookkeeping on a sparse cache hit.\n    if (it != entries.end() && it->second.geometry == geometry &&\n        it->second.size == total && it->second.sparse_handle) {\n        const Entry& entry = it->second;\n        return MultiRangeRef{\n            .handle = *entry.sparse_handle,\n            .address = entry.address,\n            .size = entry.size,\n            .sparse = true,\n            .needs_gather = false,\n        };\n    }\n    const u64 content = HashContent(sources);\n#else\n    const u64 content = HashContent(sources);\n    const auto it = entries.find(key);\n#endif\n    if (it != entries.end() && it->second.geometry == geometry && it->second.size == total) {",
    "F07 omit native sparse multi-range content hash on stable geometry hits")

# F07 C01/V05: a failed native gathered fallback may return a null Vulkan
# buffer without throwing. Never query its device address or cache it.
apply_reviewed_delta("vk_multi_range_buffer_cost.cpp",
    "        entry.gathered = memory_allocator.CreateBuffer(gather_ci, MemoryUsage::DeviceLocal);\n        entry.dirty = true;\n    }\n    if (device.IsBufferDeviceAddressSupported()) {",
    "        entry.gathered = memory_allocator.CreateBuffer(gather_ci, MemoryUsage::DeviceLocal);\n        entry.dirty = true;\n    }\n#ifdef PS5_NATIVE\n    // A failed gathered fallback must not query a device address for a null\n    // VkBuffer or cache an invalid entry. Let the caller take its safe path.\n    if (!entry.sparse_handle && !entry.gathered) {\n        return MultiRangeRef{};\n    }\n#endif\n    if (device.IsBufferDeviceAddressSupported()) {",
    "F07 reject null native multirange gather before device-address query")

# F07 C01: new sparse bindings do not copy bytes, hence need no write-tick
# hash. Recompute content for genuine gathered hits or after sparse fallback.
apply_reviewed_delta("vk_multi_range_buffer_cost.cpp",
    "    const u64 content = HashContent(sources);\n#else\n    const u64 content = HashContent(sources);",
    "    // A new sparse allocation references guest backing directly; its content\n    // hash has no consumer. Compute the hash on cache hits that may gather.\n    const bool same_geometry = it != entries.end() &&\n        it->second.geometry == geometry && it->second.size == total;\n    const u64 content = same_geometry ? HashContent(sources) : 0;\n#else\n    const u64 content = HashContent(sources);",
    "F07 hash native multi-range content only for gathered fallback lookup")
apply_reviewed_delta("vk_multi_range_buffer_cost.cpp",
    "    if (!entry.sparse_handle) {\n        VkBufferUsageFlags flags = VK_BUFFER_USAGE_TRANSFER_SRC_BIT |",
    "    if (!entry.sparse_handle) {\n#ifdef PS5_NATIVE\n        // Sparse allocation was unavailable: capture write ticks for the\n        // newly created gathered buffer before it enters the reuse cache.\n        entry.content = HashContent(sources);\n#endif\n        VkBufferUsageFlags flags = VK_BUFFER_USAGE_TRANSFER_SRC_BIT |",
    "F07 hash native multi-range content only for gathered fallback gather")

# F07 C01: owner references only require membership for DropOwner.
# Avoid repeated adjacent VkBuffer handles in their retirement vector.
apply_reviewed_delta("vk_multi_range_buffer_cost.cpp",
    "    entry.owners.reserve(sources.size());\n    for (const MultiRangeSource& source : sources) {\n        entry.owners.push_back(source.handle);\n    }",
    "    entry.owners.reserve(sources.size());\n    for (const MultiRangeSource& source : sources) {\n#ifdef PS5_NATIVE\n        // The retirement lookup only tests ownership membership. Repeated\n        // contiguous segments of the same VkBuffer do not need duplicate\n        // owner entries (common with sparse/tiled guest buffer slices).\n        if (!entry.owners.empty() && entry.owners.back() == source.handle) {\n            continue;\n        }\n#endif\n        entry.owners.push_back(source.handle);\n    }",
    "F07 deduplicate adjacent native multi-range buffer owners")

# F07 C01/T01: choose highest-tick native texture cache hit during the page
# walk. Desktop still constructs its existing vector and calls max_element.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "ImageId TextureCache<P>::FindImage(const ImageInfo& info, GPUVAddr gpu_addr,\n                                   RelaxedOptions options) {\n    std::optional<DAddr> cpu_addr = gpu_memory->GpuToCpuAddress(gpu_addr);\n    if (!cpu_addr) {\n        cpu_addr = gpu_memory->GpuToCpuAddress(gpu_addr, CalculateGuestSizeInBytes(info));\n        if (!cpu_addr) {\n            return ImageId{};\n        }\n    }\n    const bool broken_views =\n        runtime.HasBrokenTextureViewFormats() || True(options & RelaxedOptions::ForceBrokenViews);\n    const bool native_bgr = runtime.HasNativeBgr();\n    const bool flexible_formats = True(options & RelaxedOptions::Format);\n    ImageId image_id{};\n    boost::container::small_vector<ImageId, 8> image_ids;\n    const auto lambda = [&](ImageId existing_image_id, ImageBase& existing_image) {\n        if (True(existing_image.flags & ImageFlagBits::Remapped)) {\n            return false;\n        }\n        if (info.type == ImageType::Linear || existing_image.info.type == ImageType::Linear)\n            [[unlikely]] {\n            const bool strict_size = False(options & RelaxedOptions::Size) &&\n                                     True(existing_image.flags & ImageFlagBits::Strong);\n            const ImageInfo& existing = existing_image.info;\n            if (existing_image.gpu_addr == gpu_addr && existing.type == info.type &&\n                existing.pitch == info.pitch &&\n                IsPitchLinearSameSize(existing, info, strict_size) &&\n                IsViewCompatible(existing.format, info.format, broken_views, native_bgr)) {\n                image_id = existing_image_id;\n                image_ids.push_back(existing_image_id);\n                return !flexible_formats && existing.format == info.format;\n            }\n        } else if (IsSubresource(info, existing_image, gpu_addr, options, broken_views,\n                                 native_bgr)) {\n            image_id = existing_image_id;\n            image_ids.push_back(existing_image_id);\n            return !flexible_formats && existing_image.info.format == info.format;\n        }\n        return false;\n    };\n    ForEachImageInRegion(*cpu_addr, CalculateGuestSizeInBytes(info), lambda);\n    if (image_ids.size() <= 1) [[likely]] {\n        return image_id;\n    }\n    auto image_ids_compare = [this](ImageId a, ImageId b) {\n        auto& image_a = slot_images[a];\n        auto& image_b = slot_images[b];\n        return image_a.modification_tick < image_b.modification_tick;\n    };\n    return *std::ranges::max_element(image_ids, image_ids_compare);\n}\n",
    "ImageId TextureCache<P>::FindImage(const ImageInfo& info, GPUVAddr gpu_addr,\n                                   RelaxedOptions options) {\n    std::optional<DAddr> cpu_addr = gpu_memory->GpuToCpuAddress(gpu_addr);\n    if (!cpu_addr) {\n        cpu_addr = gpu_memory->GpuToCpuAddress(gpu_addr, CalculateGuestSizeInBytes(info));\n        if (!cpu_addr) {\n            return ImageId{};\n        }\n    }\n    const bool broken_views =\n        runtime.HasBrokenTextureViewFormats() || True(options & RelaxedOptions::ForceBrokenViews);\n    const bool native_bgr = runtime.HasNativeBgr();\n    const bool flexible_formats = True(options & RelaxedOptions::Format);\n    ImageId image_id{};\n#ifdef PS5_NATIVE\n    // Keep the first highest-tick match during the existing region walk:\n    // no candidate vector, no second texture-cache slot scan under its mutex.\n    u64 newest_candidate_tick{};\n    bool has_candidate = false;\n    const auto SelectCandidate = [&](ImageId id, const ImageBase& image) {\n        if (!has_candidate || newest_candidate_tick < image.modification_tick) {\n            image_id = id;\n            newest_candidate_tick = image.modification_tick;\n            has_candidate = true;\n        }\n    };\n#else\n    boost::container::small_vector<ImageId, 8> image_ids;\n#endif\n    const auto lambda = [&](ImageId existing_image_id, ImageBase& existing_image) {\n        if (True(existing_image.flags & ImageFlagBits::Remapped)) {\n            return false;\n        }\n        if (info.type == ImageType::Linear || existing_image.info.type == ImageType::Linear)\n            [[unlikely]] {\n            const bool strict_size = False(options & RelaxedOptions::Size) &&\n                                     True(existing_image.flags & ImageFlagBits::Strong);\n            const ImageInfo& existing = existing_image.info;\n            if (existing_image.gpu_addr == gpu_addr && existing.type == info.type &&\n                existing.pitch == info.pitch &&\n                IsPitchLinearSameSize(existing, info, strict_size) &&\n                IsViewCompatible(existing.format, info.format, broken_views, native_bgr)) {\n                #ifdef PS5_NATIVE\n                SelectCandidate(existing_image_id, existing_image);\n                #else\n                image_id = existing_image_id;\n                image_ids.push_back(existing_image_id);\n                #endif\n                return !flexible_formats && existing.format == info.format;\n            }\n        } else if (IsSubresource(info, existing_image, gpu_addr, options, broken_views,\n                                 native_bgr)) {\n            #ifdef PS5_NATIVE\n            SelectCandidate(existing_image_id, existing_image);\n            #else\n            image_id = existing_image_id;\n            image_ids.push_back(existing_image_id);\n            #endif\n            return !flexible_formats && existing_image.info.format == info.format;\n        }\n        return false;\n    };\n    ForEachImageInRegion(*cpu_addr, CalculateGuestSizeInBytes(info), lambda);\n#ifdef PS5_NATIVE\n    // A strict less-than comparison preserves the first equal-tick match,\n    // including ForEachImageInRegion's existing exact-match early exit.\n    return image_id;\n#else\n    if (image_ids.size() <= 1) [[likely]] {\n        return image_id;\n    }\n    auto image_ids_compare = [this](ImageId a, ImageId b) {\n        auto& image_a = slot_images[a];\n        auto& image_b = slot_images[b];\n        return image_a.modification_tick < image_b.modification_tick;\n    };\n    return *std::ranges::max_element(image_ids, image_ids_compare);\n#endif\n}\n",
    "F07 select native texture-image candidates in one region pass")

# F07 PS5 native multi-range hit path: bounds checking and the identical
# FNV-1a fingerprint share one linear pass, without touching desktop.
apply_reviewed_delta("vk_multi_range_buffer_cost.cpp",
    "    VkDeviceSize covered = 0;\n    for (const MultiRangeSource& source : sources) {\n        if (source.handle == VK_NULL_HANDLE || source.size == 0 ||\n            source.size > total - covered ||\n            source.offset > std::numeric_limits<VkDeviceSize>::max() - source.size) {\n            return MultiRangeRef{};\n        }\n        covered += source.size;\n    }",
    "#ifdef PS5_NATIVE\n    // A multi-range hit formerly scanned the same segments twice under the\n    // buffer-cache mutex: bounds/handle validation, then FNV geometry hash.\n    // Fuse both without changing hash order, invalid-input rejection or\n    // the desktop implementation.\n    u64 geometry = 0xcbf29ce484222325ULL;\n    const auto mix_geometry = [&geometry](u64 value) {\n        geometry ^= value;\n        geometry *= 0x100000001b3ULL;\n    };\n#endif\n    VkDeviceSize covered = 0;\n    for (const MultiRangeSource& source : sources) {\n        if (source.handle == VK_NULL_HANDLE || source.size == 0 ||\n            source.size > total - covered ||\n            source.offset > std::numeric_limits<VkDeviceSize>::max() - source.size) {\n            return MultiRangeRef{};\n        }\n#ifdef PS5_NATIVE\n        mix_geometry(u64(source.handle));\n        mix_geometry(u64(source.memory));\n        mix_geometry(u64(source.memory_offset));\n        mix_geometry(u64(source.memory_type));\n        mix_geometry(u64(source.offset));\n        mix_geometry(u64(source.size));\n#endif\n        covered += source.size;\n    }",
    "F07 merge native multi-range geometry fingerprint into validation walk validation")
apply_reviewed_delta("vk_multi_range_buffer_cost.cpp",
    "    const u64 geometry = HashSources(sources);\n#ifdef PS5_NATIVE\n    const auto it = entries.find(key);",
    "#ifndef PS5_NATIVE\n    const u64 geometry = HashSources(sources);\n#else\n    // geometry was computed in the validation walk above.\n#endif\n#ifdef PS5_NATIVE\n    const auto it = entries.find(key);",
    "F07 merge native multi-range geometry fingerprint into validation walk hash reuse")

# F07 C01/T01: collisions of the old direct-mapped 16-slot TIC memo
# caused duplicate VisitImageView calls under the GPU texture-cache mutex.
# Open addressing is bounded and draw-local; NULL/remapped/retry contracts
# are preserved exactly. Keep the selected file byte-reproducible.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "void TextureCache<P>::FillImageViews(std::span<ImageViewInOut> views, bool compute, bool blacklist) {\n#ifdef PS5_NATIVE\n    // The empty descriptor pass only clears the deletion/retry latch.\n    // Avoid initializing the draw-local TIC memo and entering the retry\n    // loop when no view can possibly be visited or blacklisted.\n    if (views.empty()) {\n        has_deleted_images = false;\n        return;\n    }\n#endif\n    bool has_blacklisted = false;\n    do {\n        has_deleted_images = false;\n        if (blacklist) {\n            has_blacklisted = false;\n        }\n#ifdef PS5_NATIVE\n        // P0.3: reuse nonadjacent TIC descriptors only in this stable draw pass.\n        // Never bypass NULL recovery, deletion-driven retry or blacklist work.\n        struct ViewMemo {\n            u32 index{};\n            ImageViewId id{NULL_IMAGE_VIEW_ID};\n        };\n        // A single view or blacklist pass never gets a memo hit. Avoid\n        // zeroing all 16 memo slots while holding the texture-cache lock.\n        std::optional<std::array<ViewMemo, 16>> view_memo;\n        if (!blacklist && views.size() > 1) {\n            view_memo.emplace();\n        }\n#endif\n        for (ImageViewInOut& view : views) {\n#ifdef PS5_NATIVE\n            if (view_memo && !has_deleted_images) {\n                const auto& cached = (*view_memo)[view.index & 15U];\n                if (cached.id != NULL_IMAGE_VIEW_ID && cached.index == view.index) {\n                    const auto& cached_view = slot_image_views[cached.id];\n                    // A different TIC can remap this image during the pass.\n                    // VisitImageView must rebuild remapped descriptors.\n                    const bool remapped = !cached_view.IsBuffer() &&\n                        True(slot_images[cached_view.image_id].flags & ImageFlagBits::Remapped);\n                    if (!remapped) {\n                        view.id = cached.id;\n                        // Reuse the lookup only: PrepareImageView still\n                        // refreshes dirty pixels and synchronizes aliases.\n                        PrepareImageView(cached.id, false, false);\n                        continue;\n                    }\n                }\n            }\n#endif\n            view.id = VisitImageView(view.index, compute);\n#ifdef PS5_NATIVE\n            if (view_memo && !has_deleted_images) {\n                auto& cached = (*view_memo)[view.index & 15U];\n                cached.index = view.index;\n                cached.id = view.id;\n            }\n#endif\n            if (blacklist) {\n                if (view.blacklist && view.id != NULL_IMAGE_VIEW_ID) {\n                    const ImageViewBase& image_view = slot_image_views[view.id];\n                    auto& image = slot_images[image_view.image_id];\n                    has_blacklisted |= ScaleDown(image);\n                    image.scale_rating = 0;\n                }\n            }\n        }\n    } while (has_deleted_images || (blacklist && has_blacklisted));\n}",
    "void TextureCache<P>::FillImageViews(std::span<ImageViewInOut> views, bool compute, bool blacklist) {\n#ifdef PS5_NATIVE\n    // The empty descriptor pass only clears the deletion/retry latch.\n    // Avoid initializing the draw-local TIC memo and entering the retry\n    // loop when no view can possibly be visited or blacklisted.\n    if (views.empty()) {\n        has_deleted_images = false;\n        return;\n    }\n#endif\n    bool has_blacklisted = false;\n    do {\n        has_deleted_images = false;\n        if (blacklist) {\n            has_blacklisted = false;\n        }\n#ifdef PS5_NATIVE\n        // P0.3: reuse nonadjacent TIC descriptors only in this stable draw pass.\n        // Never bypass NULL recovery, deletion-driven retry or blacklist work.\n        struct ViewMemo {\n            u32 index{};\n            ImageViewId id{NULL_IMAGE_VIEW_ID};\n        };\n        // A single view or blacklist pass never gets a memo hit. Avoid\n        // zeroing all 16 memo slots while holding the texture-cache lock.\n        std::optional<std::array<ViewMemo, 16>> view_memo;\n        if (!blacklist && views.size() > 1) {\n            view_memo.emplace();\n        }\n#endif\n        for (ImageViewInOut& view : views) {\n#ifdef PS5_NATIVE\n            // On a hot multi-texture HUD pass, several TIC indices may have\n            // the same low four bits. Preserve up to 16 distinct positive\n            // results without additional heap work or cross-draw caching.\n            ViewMemo* memo_slot = nullptr;\n            bool memo_hit = false;\n            if (view_memo && !has_deleted_images) {\n                auto& memo = *view_memo;\n                const std::size_t start = (view.index ^ (view.index >> 4)) & 15U;\n                for (std::size_t offset = 0; offset < memo.size(); ++offset) {\n                    auto& cached = memo[(start + offset) & 15U];\n                    if (cached.id == NULL_IMAGE_VIEW_ID) {\n                        memo_slot = &cached;\n                        break;\n                    }\n                    if (cached.index != view.index) continue;\n                    memo_slot = &cached;\n                    const auto& cached_view = slot_image_views[cached.id];\n                    // Never reuse a remapped view without rebuilding it.\n                    const bool remapped = !cached_view.IsBuffer() &&\n                        True(slot_images[cached_view.image_id].flags & ImageFlagBits::Remapped);\n                    if (!remapped) {\n                        view.id = cached.id;\n                        // A positive TIC hit still refreshes dirty pixels.\n                        PrepareImageView(cached.id, false, false);\n                        memo_hit = true;\n                    }\n                    break;\n                }\n            }\n            if (memo_hit) continue;\n#endif\n            view.id = VisitImageView(view.index, compute);\n#ifdef PS5_NATIVE\n            // A full table falls back to the original lookup without\n            // evicting any live descriptor in this draw. A deletion-driven\n            // retry uses a fresh table in the next do/while iteration.\n            if (memo_slot && !has_deleted_images) {\n                memo_slot->index = view.index;\n                memo_slot->id = view.id;\n            }\n#endif\n            if (blacklist) {\n                if (view.blacklist && view.id != NULL_IMAGE_VIEW_ID) {\n                    const ImageViewBase& image_view = slot_image_views[view.id];\n                    auto& image = slot_images[image_view.image_id];\n                    has_blacklisted |= ScaleDown(image);\n                    image.scale_rating = 0;\n                }\n            }\n        }\n    } while (has_deleted_images || (blacklist && has_blacklisted));\n}",
    "F07 retain distinct draw-local TIC view IDs across sampler-index collisions")

# F07 V01: pipeline may publish while the GPU worker is blocked acquiring
# build_mutex. Preserve a real >1ms mutex-only stall, but no extra log for
# an already-completed or uncontended pipeline. The earlier release/acquire
# and FIFO semantics are unchanged.
apply_reviewed_delta("vk_graphics_pipeline_cost.cpp",
    "            keyed_wait.MarkLockAcquired();\n            if (is_built.load(std::memory_order_acquire)) return;\n#endif",
    "            keyed_wait.MarkLockAcquired();\n            if (is_built.load(std::memory_order_acquire)) {\n                lock.unlock();\n                // A publisher may complete while this GPU callback waits\n                // for build_mutex. Do not call condvar; report only genuine\n                // (>1ms) mutex contention, never an instant ready callback.\n                if (keyed_wait.WasBlockedOnMutex())\n                    keyed_wait.Complete(\"graphics\", key.Hash(), CanExecuteDraw());\n                return;\n            }\n#endif",
    "F07 V01 retain graphics mutex-only blocked publication attribution")
apply_reviewed_delta("vk_compute_pipeline_cost.cpp",
    "            keyed_wait.MarkLockAcquired();\n            if (is_built.load(std::memory_order_acquire)) return;\n#endif",
    "            keyed_wait.MarkLockAcquired();\n            if (is_built.load(std::memory_order_acquire)) {\n                lock.unlock();\n                // A publisher may complete while this GPU callback waits\n                // for build_mutex. Do not call condvar; report only genuine\n                // (>1ms) mutex contention, never an instant ready callback.\n                if (keyed_wait.WasBlockedOnMutex())\n                    keyed_wait.Complete(\"compute\", diagnostic_cache_key_hash, IsBound());\n                return;\n            }\n#endif",
    "F07 V01 retain compute mutex-only blocked publication attribution")

# F07 compute: avoid repeated unordered-map probes for the same healthy
# compute key. Only a positive per-owner entry is reused; null failures
# still take the delayed retry, and DEV first-use tracing stays unchanged.
apply_reviewed_delta("include/video_core/renderer_vulkan/vk_pipeline_cache.h",
    "    ::Common::unordered_map<ComputePipelineCacheKey, std::unique_ptr<ComputePipeline>> compute_cache;\n",
    "    ::Common::unordered_map<ComputePipelineCacheKey, std::unique_ptr<ComputePipeline>> compute_cache;\n#ifdef PS5_NATIVE\n    // GPU-owner-only: four fixed positive entries avoid repeatedly hashing\n    // alternating compute shaders. The map owns these pipeline objects for\n    // this PipelineCache's lifetime. Failed keys are never memoized.\n    struct ComputePositive {\n        ComputePipelineCacheKey key{};\n        ComputePipeline* pipeline{};\n    };\n    std::array<ComputePositive, 4> recent_compute_pipelines{};\n    unsigned next_compute_positive{};\n    unsigned preferred_compute_positive{};\n#endif\n",
    "F07 compute positive owner cache fields")
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "    const auto [pair, is_new]{compute_cache.try_emplace(key)};",
    "#ifdef PS5_NATIVE\n    // Alternating successful compute shaders need no unordered-map hash or\n    // probe. Four fixed owner-local entries cover common dispatch sequences,\n    // while failed keys and development first-use tracing retain the map path.\n    if (!::Eden::DevVulkan::trace_pipelines) {\n        // Most dispatches reuse the last key. Probe its slot first rather\n        // than scanning four hints on each call after several shaders load.\n        const auto& preferred = recent_compute_pipelines[preferred_compute_positive];\n        if (preferred.pipeline && preferred.key == key) return preferred.pipeline;\n        for (unsigned i = 0; i < recent_compute_pipelines.size(); ++i) {\n            if (i == preferred_compute_positive) continue;\n            const auto& recent = recent_compute_pipelines[i];\n            // Positive slots fill contiguously before the four-entry ring\n            // wraps. A cold lookup need not compare the unused tail.\n            if (!recent.pipeline) break;\n            if (recent.key == key) {\n                // With only two active shaders, the newest preferred slot\n                // handles one key and the other is always at most one probe\n                // away. Avoid a cache-line write on every A/B dispatch.\n                if (recent_compute_pipelines[2].pipeline)\n                    preferred_compute_positive = i;\n                return recent.pipeline;\n            }\n        }\n    }\n#endif\n    const auto [pair, is_new]{compute_cache.try_emplace(key)};",
    "F07 compute same-key skip map probe")
apply_reviewed_delta("vk_pipeline_cache_cost.cpp",
    "    }\n    return pipeline.get();\n}\n\nvoid PipelineCache::LoadDiskResources",
    "    }\n#ifdef PS5_NATIVE\n    // Only successful pipelines enter the bounded owner-local memo.\n    // A null shader still reaches the map's delayed one-shot retry on every\n    // dispatch, without disturbing other valid compute pipeline keys.\n    if (pipeline && !::Eden::DevVulkan::trace_pipelines) {\n        auto& recent = recent_compute_pipelines[next_compute_positive];\n        recent.key = key;\n        recent.pipeline = pipeline.get();\n        preferred_compute_positive = next_compute_positive;\n        next_compute_positive = (next_compute_positive + 1) & 3u;\n    }\n#endif\n    return pipeline.get();\n}\n\nvoid PipelineCache::LoadDiskResources",
    "F07 compute null-safe positive memo publication")

# F07 P0.3: finalize TIC memo without per-draw zero clearing under cache mutex.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "        struct ViewMemo {\n            u32 index{};\n            ImageViewId id{NULL_IMAGE_VIEW_ID};\n        };\n        // A single view or blacklist pass never gets a memo hit. Avoid\n        // zeroing all 16 memo slots while holding the texture-cache lock.\n        std::optional<std::array<ViewMemo, 16>> view_memo;\n        if (!blacklist && views.size() > 1) {\n            view_memo.emplace();\n        }",
    "        struct ViewMemo {\n            u32 index;\n            ImageViewId id;\n        };\n        // Use a mask instead of clearing sixteen keys under the texture lock.\n        // Unoccupied entries are never read, NULL IDs never memoized.\n        std::array<ViewMemo, 16> view_memo;\n        u32 occupied_view_slots = 0;\n        const bool memo_enabled = !blacklist && views.size() > 1;",
    "F07 occupancy-mask memo storage and mask")

# F07 P0.3: finalize TIC memo without per-draw zero clearing under cache mutex.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "            ViewMemo* memo_slot = nullptr;\n            bool memo_hit = false;\n            if (view_memo && !has_deleted_images) {\n                auto& memo = *view_memo;\n                const std::size_t start = (view.index ^ (view.index >> 4)) & 15U;\n                for (std::size_t offset = 0; offset < memo.size(); ++offset) {\n                    auto& cached = memo[(start + offset) & 15U];\n                    if (cached.id == NULL_IMAGE_VIEW_ID) {\n                        memo_slot = &cached;\n                        break;\n                    }\n                    if (cached.index != view.index) continue;\n                    memo_slot = &cached;",
    "            ViewMemo* memo_slot = nullptr;\n            u32 memo_bit = 0;\n            bool memo_hit = false;\n            if (memo_enabled && !has_deleted_images) {\n                const std::size_t start = (view.index ^ (view.index >> 4)) & 15U;\n                for (std::size_t offset = 0; offset < view_memo.size(); ++offset) {\n                    const std::size_t slot = (start + offset) & 15U;\n                    const u32 bit = u32{1} << slot;\n                    auto& cached = view_memo[slot];\n                    if (!(occupied_view_slots & bit)) {\n                        memo_slot = &cached;\n                        memo_bit = bit;\n                        break;\n                    }\n                    if (cached.index != view.index) continue;\n                    memo_slot = &cached;\n                    memo_bit = bit;",
    "F07 occupancy-mask memo lookup")

# F07 P0.3: finalize TIC memo without per-draw zero clearing under cache mutex.
apply_reviewed_delta("vulkan-cache/video_core/texture_cache/texture_cache.h",
    "            if (memo_slot && !has_deleted_images) {\n                memo_slot->index = view.index;\n                memo_slot->id = view.id;\n            }",
    "            if (memo_slot && !has_deleted_images && view.id != NULL_IMAGE_VIEW_ID) {\n                memo_slot->index = view.index;\n                memo_slot->id = view.id;\n                occupied_view_slots |= memo_bit;\n            }",
    "F07 occupancy-mask memo positive publication")

# F07 PS5: reduce Vulkan scheduler command count for gathered multirange
# slices sharing a VkBuffer. Group no more than 8 ordered copies on stack.
# Read-only desktop and all barrier semantics remain unchanged.
apply_reviewed_delta("vk_buffer_cache_cost.cpp",
    "    if (ref.needs_gather) {\n        PreCopyBarrier();\n        VkDeviceSize dst_offset = 0;\n        for (const MultiRangeSource& source : multi_range_sources) {\n            const std::array<VideoCommon::BufferCopy, 1> copy{VideoCommon::BufferCopy{\n                .src_offset = u64(source.offset),\n                .dst_offset = u64(dst_offset),\n                .size = size_t(source.size),\n            }};\n            CopyBuffer(ref.handle, source.handle, copy, false);\n            dst_offset += source.size;\n        }\n        PostCopyBarrier();\n        multi_range_buffers.MarkGathered(key);\n    }",
    "    if (ref.needs_gather) {\n        PreCopyBarrier();\n        VkDeviceSize dst_offset = 0;\n#ifdef PS5_NATIVE\n        // One command can copy multiple non-overlapping slices from the\n        // same source buffer. Group adjacent owner runs in an eight-entry\n        // stack batch, never reorder guest bytes or change the barrier pair.\n        // A different source, or a full batch, flushes in FIFO order.\n        VkBuffer grouped_source = VK_NULL_HANDLE;\n        std::array<VideoCommon::BufferCopy, 8> grouped_copies{};\n        std::size_t grouped_count = 0;\n        const auto flush_group = [&] {\n            if (grouped_count == 0) return;\n            CopyBuffer(ref.handle, grouped_source,\n                       std::span<const VideoCommon::BufferCopy>{grouped_copies.data(), grouped_count},\n                       false);\n            grouped_count = 0;\n        };\n        for (const MultiRangeSource& source : multi_range_sources) {\n            if (source.handle != grouped_source || grouped_count == grouped_copies.size())\n                flush_group();\n            grouped_source = source.handle;\n            grouped_copies[grouped_count++] = VideoCommon::BufferCopy{\n                .src_offset = u64(source.offset),\n                .dst_offset = u64(dst_offset),\n                .size = size_t(source.size),\n            };\n            dst_offset += source.size;\n        }\n        flush_group();\n#else\n        for (const MultiRangeSource& source : multi_range_sources) {\n            const std::array<VideoCommon::BufferCopy, 1> copy{VideoCommon::BufferCopy{\n                .src_offset = u64(source.offset),\n                .dst_offset = u64(dst_offset),\n                .size = size_t(source.size),\n            }};\n            CopyBuffer(ref.handle, source.handle, copy, false);\n            dst_offset += source.size;\n        }\n#endif\n        PostCopyBarrier();\n        multi_range_buffers.MarkGathered(key);\n    }",
    "F07 coalesce adjacent native multirange gather slices into bounded FIFO batches")

# F07 PS5 contiguous gathered-buffer slices: fuse whole Vulkan COPY regions
# only when source/destination adjacency are both proven. No new allocations.
apply_reviewed_delta("vk_buffer_cache_cost.cpp",
    "        for (const MultiRangeSource& source : multi_range_sources) {\n            if (source.handle != grouped_source || grouped_count == grouped_copies.size())\n                flush_group();\n            grouped_source = source.handle;\n            grouped_copies[grouped_count++] = VideoCommon::BufferCopy{\n                .src_offset = u64(source.offset),\n                .dst_offset = u64(dst_offset),\n                .size = size_t(source.size),\n            };\n            dst_offset += source.size;\n        }\n        flush_group();",
    "        for (const MultiRangeSource& source : multi_range_sources) {\n            // Consecutive guest ranges that also occupy adjacent bytes in\n            // the SAME source buffer are one Vulkan region, not merely one\n            // scheduler command. Get() already checked each size and\n            // destination sum against the allocated gathered-buffer extent.\n            if (grouped_count && source.handle == grouped_source) {\n                auto& last = grouped_copies[grouped_count - 1];\n                if (last.src_offset + last.size == source.offset &&\n                    last.dst_offset + last.size == dst_offset) {\n                    last.size += size_t(source.size);\n                    dst_offset += source.size;\n                    continue;\n                }\n            }\n            if (source.handle != grouped_source || grouped_count == grouped_copies.size())\n                flush_group();\n            grouped_source = source.handle;\n            grouped_copies[grouped_count++] = VideoCommon::BufferCopy{\n                .src_offset = u64(source.offset),\n                .dst_offset = u64(dst_offset),\n                .size = size_t(source.size),\n            };\n            dst_offset += source.size;\n        }\n        flush_group();",
    "F07 fuse adjacent Vulkan multirange guest bytes within source-local copy batch")

# F07: merge physically contiguous sparse bindings with same VkDeviceMemory.
# All sources are overflow/alignment-validated before CreateSparse allocation.
apply_reviewed_delta("vk_multi_range_buffer_cost.cpp",
    "    for (const MultiRangeSource& source : sources) {\n        binds.push_back(VkSparseMemoryBind{\n            .resourceOffset = resource_offset,\n            .size = source.size,\n            .memory = source.memory,\n            .memoryOffset = source.memory_offset + source.offset,\n            .flags = 0,\n        });\n        resource_offset += source.size;\n    }",
    "    for (const MultiRangeSource& source : sources) {\n        const VkDeviceSize physical_offset = source.memory_offset + source.offset;\n#ifdef PS5_NATIVE\n        // Adjacent virtual pages backed by adjacent bytes of the SAME Vulkan\n        // allocation need only one sparse bind descriptor. Both sides were\n        // validated for overflow and alignment before creating this buffer.\n        // Keep different allocations and physical gaps as separate bindings.\n        if (!binds.empty() && binds.back().memory == source.memory &&\n            binds.back().resourceOffset + binds.back().size == resource_offset &&\n            binds.back().memoryOffset + binds.back().size == physical_offset) {\n            binds.back().size += source.size;\n        } else\n#endif\n        {\n            binds.push_back(VkSparseMemoryBind{\n                .resourceOffset = resource_offset,\n                .size = source.size,\n                .memory = source.memory,\n                .memoryOffset = physical_offset,\n                .flags = 0,\n            });\n        }\n        resource_offset += source.size;\n    }",
    "F07 merge contiguous native Vulkan sparse bindings safely")
