#!/usr/bin/env python3
"""Verify tracked native Vulkan C++ fork exactly matches validated R337 source generator."""
from pathlib import Path
import filecmp
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
root=Path(__file__).resolve().parents[1]
active=root/'vendor/encore-active/eden-vulkan'
upstream=root/'vendor/sources/eden'
assert (upstream/'VENDOR-ORIGIN.json').exists()
assert (active/'vulkan_renderer.cpp').exists()
with tempfile.TemporaryDirectory(prefix='eden-vulkan-fork-compare-') as d:
    temp=Path(d)
    # The *production* renderer has always consumed Eden AFTER the ordered
    # 43 shipping backports, not the pristine archive. Reproduce that exact
    # working source before comparing the versioned Vulkan C++ translation
    # units; otherwise stale GPU lifetime / texture-cache patches leak in.
    patched=temp/'patched-eden'
    shutil.copytree(upstream,patched,symlinks=True)
    (patched/'GIT-COMMIT').write_text('5f142c7926d0c7fcbbd0ce30794d72f638a43b2a\n')
    subprocess.run([sys.executable,'-B',str(root/'tools/install-vendored-eden-backports.py'),
                    str(patched)],check=True,timeout=50,capture_output=True,text=True)
    # Pin shader input text separately from binary reproducibility. Avoid
    # depending on a nondeterministic host glslangValidator version in CI.
    expected_shaders={
        'vert':'b7efb0f17a2cfb2ac044d0d678dfd7f970323deef86c10d25dde8ed723ef0290',
        'frag':'eb91764f71e68593be5ddcc71599b9d66ed9d67ec49b44ff7b52473800ea3783',
    }
    for stage, digest in expected_shaders.items():
        source=root/'headless'/f'vulkan_hud.{stage}'
        assert hashlib.sha256(source.read_bytes()).hexdigest()==digest,source
        assert (active/f'vulkan_hud.{stage}.spv').is_file()
    env=os.environ.copy()
    env['EDEN_VULKAN_ORACLE_SPV_DIR']=str(active)
    oracle_script=(root/'tools/prepare-vulkan-port.py').read_text()
    vulkan_cmake=(root/'headless/vulkan.cmake').read_text()
    assert "vulkan_oracle = Path(__file__).resolve().parents[1] / 'vendor/encore-active/eden-vulkan-oracles'" in oracle_script
    for part in ("vulkan_loading.inc", "vulkan_hud_prepare.inc", "vulkan_hud_draw.inc",
                 "vulkan_gc_downloads.inc", "vulkan_download_batch.inc"):
        assert (root/'vendor/encore-active/eden-vulkan-oracles'/part).is_file()
        assert not (root/'headless'/part).exists()
        assert (f"vulkan_oracle / '{part}'") in oracle_script
        assert part not in vulkan_cmake, ("oracle accidentally tracked as compiled Vulkan input", part)
    subprocess.run([sys.executable,'-B',str(root/'tools/prepare-vulkan-port.py'),str(patched),str(temp/'generated')],check=True,timeout=150,env=env)
    actual={str(p.relative_to(temp/'generated')):p for p in (temp/'generated').rglob('*') if p.is_file()}
    expected={str(p.relative_to(active)):p for p in active.rglob('*') if p.is_file()}
    # Two intentional native-only sources are not generator outputs:
    # a synchronization helper and the F07 Vulkan allocator OOM diagnostics.
    # All generated Vulkan translation units still remain byte-identical.
    helper='include/video_core/renderer_vulkan/striped_wait.h'
    allocator='vulkan_memory_allocator.cpp'
    # Shared native GPU budget admission owner, usable by both NS1 and NS2.
    # It is additive, never regenerated from the original upstream Vulkan.
    pool_policy='include/video_core/renderer_vulkan/vk_shared_gpu_budget.h'
    assert pool_policy not in actual, 'native GPU budget leaked into generator'
    assert subprocess.check_output(
        ['git','hash-object',str(expected[pool_policy])],text=True
    ).strip() == '85cc400399ee8daf82037dfc0f070d3d66eebb68', 'shared GPU policy drift'
    oom_check = subprocess.run(
        [sys.executable, '-B', str(root/'tools/check-ps5-vulkan-oom-source.py')],
        timeout=15, capture_output=True, text=True)
    if oom_check.returncode != 0:
        raise RuntimeError('F07 allocator source parity failed (code %d):\n%s\n%s' % (
            oom_check.returncode, oom_check.stdout, oom_check.stderr))
    assert allocator not in actual, 'generated Vulkan port unexpectedly owns the allocator'
    assert set(actual)==set(expected)-{helper, allocator, pool_policy}, (
        f'missing: {set(actual)-set(expected)}, extras: {set(expected)-set(actual)}')
    helper_file=expected[helper]
    assert subprocess.check_output(['git','hash-object',str(helper_file)],text=True).strip()==(
        '16749faa8c0f1047de0485af53ff2de65d66be7d'), 'upstream wait primitive drift'
    for name in (
        'include/video_core/renderer_vulkan/vk_graphics_pipeline.h',
        'include/video_core/renderer_vulkan/vk_compute_pipeline.h',
    ):
        source=actual[name].read_text()
        old='    std::condition_variable build_condvar;\n    std::mutex build_mutex;'
        new='    ::Eden::StripedCondition build_condvar;\n    ::Eden::StripedMutex build_mutex;'
        inc='#include "common/thread_worker.h"'
        assert source.count(old)==source.count(inc)==1, ('pipeline source moved',name)
        modified=source.replace(inc,inc+'\n#include "video_core/renderer_vulkan/striped_wait.h"').replace(old,new)
        actual[name].write_text(modified)
    # The selected native rasterizer intentionally fails closed on an absent
    # indirect-command/count binding. Mirror ONLY those two reviewed guards
    # in the temporary oracle; the production source stays in encore-active.
    raster_path = actual['vulkan_rasterizer.cpp']
    raster = raster_path.read_text()
    native_guards = (
        (
            "        const auto& buffer = indirect_buffer.first;\n"
            "        const auto& offset = indirect_buffer.second;\n"
            "        if (params.is_byte_count) {",
            "        const auto& buffer = indirect_buffer.first;\n"
            "        const auto& offset = indirect_buffer.second;\n"
            "        // UpdateDrawIndirect can deliberately reject an unmapped/overflowing\n"
            "        // guest command span. Never record a Vulkan draw with a null buffer.\n"
            "        if (!buffer) {\n"
            "            return;\n"
            "        }\n"
            "        if (params.is_byte_count) {",
        ),
        (
            "            const auto& draw_buffer = count.first;\n"
            "            const auto& offset_base = count.second;\n"
            "            scheduler.Record([draw_buffer_obj = draw_buffer->Handle(),",
            "            const auto& draw_buffer = count.first;\n"
            "            const auto& offset_base = count.second;\n"
            "            if (!draw_buffer) {\n"
            "                return;\n"
            "            }\n"
            "            scheduler.Record([draw_buffer_obj = draw_buffer->Handle(),",
        ),
    )
    for old, new in native_guards:
        assert raster.count(old) == 1, "pinned Vulkan indirect draw moved"
        raster = raster.replace(old, new)
    # The pinned draw path has its own null-pointer guard. Compute-indirect
    # and DMA image now also require a live Vulkan handle, not just Buffer*.
    # Verify all three paths independently, not a combined obsolete count.
    assert raster.count("if (!buffer)") == 1, "draw indirect pointer guard drift"
    native_vk_guard = "if (!buffer || buffer->Handle() == VK_NULL_HANDLE)"
    assert raster.count(native_vk_guard) == 2, "compute/DMA Vulkan handle guard drift"
    assert raster.count("if (!draw_buffer)") == 1, "counted draw buffer guard drift"
    dispatch = raster.split("void RasterizerVulkan::DispatchCompute() {", 1)[1].split(
        "void RasterizerVulkan::ResetCounter(", 1)[0]
    assert dispatch.count(native_vk_guard) == 1, "compute indirect VkBuffer guard drift"
    dma = raster.split("bool AccelerateDMA::DmaBufferImageCopy(", 1)[1].split(
        "bool AccelerateDMA::ImageToBuffer(", 1)[0]
    assert dma.count(native_vk_guard) == 1, "DMA image VkBuffer guard drift"
    assert "if (!buffer)" in raster.split("void RasterizerVulkan::DrawIndirect() {", 1)[1].split(
        "void RasterizerVulkan::DispatchCompute() {", 1)[0], "draw indirect guard drift"
    raster_path.write_text(raster)
    # Native GPU hot-path deltas are audited against the pinned generated
    # Vulkan source. Reconstruct exactly; never silently accept another drift.
    pipeline_src = actual['vk_graphics_pipeline_cost.cpp']
    pipeline_text = pipeline_src.read_text()
    optimized_pipeline_deltas = (
        ("        for (const auto& desc : info.texture_descriptors) {\n            for (u32 index = 0; index < desc.count; ++index) {\n                const auto handle{read_handle(desc, index)};\n                views.push_back({handle.first});\n\n                VideoCommon::SamplerId sampler{texture_cache.GetSamplerId(handle.second, false)};\n                samplers.push_back(sampler);\n            }\n        }", "        // A descriptor array frequently shares its sampler handle.\n        // Reuse only consecutive equal handles within this stage/configuration:\n        // no sampler id survives a pipeline change or guest invalidation.\n        bool last_sampler_valid = false;\n        u32 last_sampler_handle{};\n        VideoCommon::SamplerId last_sampler_id{};\n        for (const auto& desc : info.texture_descriptors) {\n            for (u32 index = 0; index < desc.count; ++index) {\n                const auto handle{read_handle(desc, index)};\n                views.push_back({handle.first});\n\n                if (!last_sampler_valid || last_sampler_handle != handle.second) {\n                    last_sampler_id = texture_cache.GetSamplerId(handle.second, false);\n                    last_sampler_handle = handle.second;\n                    last_sampler_valid = true;\n                }\n                samplers.push_back(last_sampler_id);\n            }\n        }"),
        ("    { ::Eden::Performance::CachePhaseTimer cost{::Eden::Performance::CachePhase::TextureFillImageViews};\n        texture_cache.FillImageViews(std::span(views.data(), views.size()), false, Spec::has_images);\n    }", "    // FillImageViews resets the image-deletion/retry latch even for no images.\n    // Keep that state transition for graphics as for compute; no TIC is resolved.\n    { ::Eden::Performance::CachePhaseTimer cost{\n        ::Eden::Performance::CachePhase::TextureFillImageViews};\n        texture_cache.FillImageViews(std::span(views.data(), views.size()), false,\n                                     Spec::has_images);\n    }"),
    )
    for pinned_fragment, native_fragment in optimized_pipeline_deltas:
        assert pipeline_text.count(pinned_fragment) == 1, "pinned sampler stage moved"
        pipeline_text = pipeline_text.replace(pinned_fragment, native_fragment)
    # Reconstruct the reviewed per-draw sampler memo separately from the
    # older consecutive-only optimization. Fail on source/anchor drift.
    sampler_previous = "        // A descriptor array frequently shares its sampler handle.\n        // Reuse only consecutive equal handles within this stage/configuration:\n        // no sampler id survives a pipeline change or guest invalidation.\n        bool last_sampler_valid = false;\n        u32 last_sampler_handle{};\n        VideoCommon::SamplerId last_sampler_id{};\n        for (const auto& desc : info.texture_descriptors) {\n            for (u32 index = 0; index < desc.count; ++index) {\n                const auto handle{read_handle(desc, index)};\n                views.push_back({handle.first});\n\n                if (!last_sampler_valid || last_sampler_handle != handle.second) {\n                    last_sampler_id = texture_cache.GetSamplerId(handle.second, false);\n                    last_sampler_handle = handle.second;\n                    last_sampler_valid = true;\n                }\n                samplers.push_back(last_sampler_id);\n            }\n        }"
    sampler_current = "        for (const auto& desc : info.texture_descriptors) {\n            for (u32 index = 0; index < desc.count; ++index) {\n                const auto handle{read_handle(desc, index)};\n                views.push_back({handle.first});\n                samplers.push_back(resolve_sampler(handle.second));\n            }\n        }"
    sampler_memo = "    // Sampler table mapping is stable while the paired guest cache locks are\n    // held. Cache repeated handles only for this draw: never reuse an ID after\n    // a later guest descriptor invalidation, channel switch or pipeline change.\n    // Keep all 16 distinct sampler handles in one draw even if they share\n    // the low four bits. A direct-mapped memo re-resolved each alternating\n    // handle under the GPU texture-cache mutex. Open addressing has no heap\n    // allocations; saturation falls back to the original lookup, never a\n    // stale ID. Descriptor invalidation cannot cross this draw-local scope.\n    struct SamplerMemo {\n        u32 handle;\n        VideoCommon::SamplerId id;\n    };\n    // A single occupancy mask replaces per-entry valid-byte clearing on\n    // every graphics draw. A slot becomes visible only after lookup success.\n    std::array<SamplerMemo, 16> sampler_memo;\n    u32 occupied_sampler_slots{};\n    const auto resolve_sampler{[&](u32 handle) -> VideoCommon::SamplerId {\n        const std::size_t first = (handle ^ (handle >> 4)) & 15U;\n        for (std::size_t offset = 0; offset < sampler_memo.size(); ++offset) {\n            const std::size_t slot = (first + offset) & 15U;\n            const u32 bit = u32{1} << slot;\n            auto& entry = sampler_memo[slot];\n            if (occupied_sampler_slots & bit) {\n                if (entry.handle == handle) return entry.id;\n                continue;\n            }\n            // A failed sampler lookup never publishes the occupied bit.\n            entry.id = texture_cache.GetSamplerId(handle, false);\n            entry.handle = handle;\n            occupied_sampler_slots |= bit;\n            return entry.id;\n        }\n        return texture_cache.GetSamplerId(handle, false);\n    }};\n"
    sampler_stage = '    const auto config_stage{[&](size_t stage) LAMBDA_FORCEINLINE {'
    assert pipeline_text.count(sampler_previous) == 1
    assert pipeline_text.count(sampler_stage) == 1
    assert pipeline_text.count('#include <algorithm>\n') == 1
    assert '#include <array>\n' not in pipeline_text
    pipeline_text = pipeline_text.replace('#include <algorithm>\n',
                                          '#include <algorithm>\n#include <array>\n', 1)
    pipeline_text = pipeline_text.replace(sampler_previous, sampler_current)
    pipeline_text = pipeline_text.replace(sampler_stage, sampler_memo + sampler_stage)
    assert pipeline_text.count('std::array<SamplerMemo, 16> sampler_memo;') == 1
    assert pipeline_text.count('samplers.push_back(resolve_sampler(handle.second));') == 1
    pipeline_src.write_text(pipeline_text)

    # AMD logic-op host-state projection: never mutate guest Maxwell regs.
    # Replay exact source deltas against the pinned Vulkan renderer.
    raster_src = actual['vulkan_rasterizer.cpp']
    raster_data = raster_src.read_text()
    for old, new in (
        ("        // AMD Workaround: LogicOp incompatible with float render targets\n        if (device.GetDriverID() == VkDriverIdKHR::VK_DRIVER_ID_AMD_OPEN_SOURCE ||\n            device.GetDriverID() == VkDriverIdKHR::VK_DRIVER_ID_AMD_PROPRIETARY) {\n            const auto has_float = std::any_of(\n                regs.vertex_attrib_format.begin(), regs.vertex_attrib_format.end(),\n                [](const auto& attrib) {\n                    return attrib.type == Maxwell3D::Regs::VertexAttribute::Type::Float;\n                }\n            );\n            if (regs.logic_op.enable) {\n                regs.logic_op.enable = static_cast<u32>(!has_float);\n            }\n        }\n        UpdateLogicOpEnable(regs);", "        // The AMD host workaround depends on vertex formats as well as the\n        // guest logic-op register. A vertex format change must rebind the\n        // effective Vulkan state without overwriting the guest register.\n        if (regs.logic_op.enable != 0 && flags[Dirty::VertexInput] &&\n            (device.GetDriverID() == VkDriverIdKHR::VK_DRIVER_ID_AMD_OPEN_SOURCE ||\n             device.GetDriverID() == VkDriverIdKHR::VK_DRIVER_ID_AMD_PROPRIETARY)) {\n            flags[Dirty::LogicOpEnable] = true;\n        }\n        UpdateLogicOpEnable(regs);"),
        ("void RasterizerVulkan::UpdateLogicOpEnable(Tegra::Engines::Maxwell3D::Regs& regs) {\n    if (!state_tracker.TouchLogicOpEnable()) {\n        return;\n    }\n    if (!device.SupportsDynamicState3LogicOpEnable()) {\n        return;\n    }\n    scheduler.Record([enable = regs.logic_op.enable](vk::CommandBuffer cmdbuf) {\n        cmdbuf.SetLogicOpEnableEXT(enable != 0);\n    });\n}", "void RasterizerVulkan::UpdateLogicOpEnable(Tegra::Engines::Maxwell3D::Regs& regs) {\n    if (!state_tracker.TouchLogicOpEnable()) {\n        return;\n    }\n    if (!device.SupportsDynamicState3LogicOpEnable()) {\n        return;\n    }\n    bool enable = regs.logic_op.enable != 0;\n    if (enable &&\n        (device.GetDriverID() == VkDriverIdKHR::VK_DRIVER_ID_AMD_OPEN_SOURCE ||\n         device.GetDriverID() == VkDriverIdKHR::VK_DRIVER_ID_AMD_PROPRIETARY)) {\n        // The existing AMD float-vertex workaround applies to Vulkan only.\n        // Never mutate a Maxwell register: the guest can reuse its original\n        // logic-op value on a later draw with a different vertex format.\n        enable = !std::any_of(\n            regs.vertex_attrib_format.begin(), regs.vertex_attrib_format.end(),\n            [](const auto& attrib) {\n                return attrib.type ==\n                       Tegra::Engines::Maxwell3D::Regs::VertexAttribute::Type::Float;\n            });\n    }\n    scheduler.Record([enable](vk::CommandBuffer cmdbuf) {\n        cmdbuf.SetLogicOpEnableEXT(enable);\n    });\n}"),
    ):
        assert raster_data.count(old) == 1, "pinned Vulkan AMD logic-op path moved"
        raster_data = raster_data.replace(old, new)
    raster_src.write_text(raster_data)
    # F04: reconstruct ONLY the reviewed upload-barrier stage/access deltas
    # from the pinned source. Never replace this with the active file or
    # weaken the full-file oracle: unrelated Vulkan drift must still fail.
    upload_path = actual["vk_texture_cache_cost.cpp"]
    upload_source = upload_path.read_text()
    upload_deltas = (
        # The native missing-pass guard is replayed by prepare-vulkan-port.py.
        # Only five independent post-generator source transformations are here.
    # F07 P0.4: a device without image-format-list still needs its optional
    # BCn 3D compute-buffer pass to complete native asynchronous uploads.
    ("    if (!device.IsKhrImageFormatListSupported()) {\n        return;\n    }",
     "    if (!device.IsKhrImageFormatListSupported()) {\n#ifdef PS5_NATIVE\n        // BCn 3D unswizzle is a compute-buffer pass; it does not require\n        // VK_KHR_image_format_list. Without a pass here, native queued 3D\n        // uploads can be marked complete without ever submitting pixels.\n        if (Settings::values.gpu_unswizzle_enabled.GetValue()) {\n            bl3d_unswizzle_pass.emplace(device, scheduler, descriptor_pool,\n                                       staging_buffer_pool, compute_pass_descriptor_queue);\n        }\n#endif\n        return;\n    }"),
    ("VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT;\n    static constexpr VkAccessFlags READ_ACCESS_FLAGS",
     "VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_WRITE_BIT | VK_ACCESS_TRANSFER_WRITE_BIT;\n    static constexpr VkAccessFlags READ_ACCESS_FLAGS"),
    ("VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_READ_BIT;\n\n    //  Compute exact mip/layer range being written to",
     "VK_ACCESS_DEPTH_STENCIL_ATTACHMENT_READ_BIT | VK_ACCESS_TRANSFER_READ_BIT;\n\n    //  Compute exact mip/layer range being written to"),
    ("    cmdbuf.PipelineBarrier(VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT |\n                           VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT |\n                           VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0,\n                           read_barrier);",
     "    // Include shader and transfer producers of the previous contents. Color\n    // attachment and late-depth alone cannot order vertex/fragment writers,\n    // early depth, or a preceding copy to the same image.\n    cmdbuf.PipelineBarrier(VK_PIPELINE_STAGE_VERTEX_SHADER_BIT |\n                           VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT |\n                           VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT |\n                           VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT |\n                           VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT |\n                           VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT |\n                           VK_PIPELINE_STAGE_TRANSFER_BIT,\n                           VK_PIPELINE_STAGE_TRANSFER_BIT, 0, read_barrier);"),
    ("    cmdbuf.PipelineBarrier(\n            VK_PIPELINE_STAGE_TRANSFER_BIT,\n            VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT |\n            VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT |\n            VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,\n            0, nullptr, nullptr, write_barrier);",
     "    // After copying, fragment/vertex texture sampling must see the upload.\n    // The existing destination access mask already names shader reads, but\n    // without those stage bits they are outside the destination scope.\n    cmdbuf.PipelineBarrier(\n            VK_PIPELINE_STAGE_TRANSFER_BIT,\n            VK_PIPELINE_STAGE_VERTEX_SHADER_BIT |\n            VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT |\n            VK_PIPELINE_STAGE_EARLY_FRAGMENT_TESTS_BIT |\n            VK_PIPELINE_STAGE_LATE_FRAGMENT_TESTS_BIT |\n            VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT |\n            VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT |\n            VK_PIPELINE_STAGE_TRANSFER_BIT,\n            0, nullptr, nullptr, write_barrier);"),
    )
    for pinned_fragment, reviewed_fragment in upload_deltas:
        assert upload_source.count(pinned_fragment) == 1, "pinned image upload barrier moved"
        upload_source = upload_source.replace(pinned_fragment, reviewed_fragment)
    upload_path.write_text(upload_source)
    # The renderer retains its pinned SPIR-V for the regular in-game HUD.
    # Replay only the reviewed source-owned no-second-splash handoff change,
    # preserving byte-for-byte comparison of EVERY generated native file.
    loader_path = actual["vulkan_window_adapt_pass.cpp"]
    loader_source = loader_path.read_text()
    for before, after in (
        ("    const auto hud = draw_hud ? Eden::GetVulkanHud() : Eden::HudSnapshot{};\n    if (hud.width && !hud_pipeline) {",
         "    const auto hud = draw_hud ? Eden::GetVulkanHud() : Eden::HudSnapshot{};\n    // The 3D jacket in the native launcher is the ONE authored loading\n    // animation. The checked-in Vulkan SPIR-V includes an obsolete purple\n    // loading scene; keep the shader binary pinned for normal FPS HUD only.\n    // Rendering the loader without an overlay retains the GPU warm-up\n    // swapchain presents, acquire/release order and first-frame handoff.\n    const bool quiet_loading_handoff = hud.loading != 0;\n    if (hud.width && !quiet_loading_handoff && !hud_pipeline) {"),
        ("        const f32 bg_red = Settings::values.bg_red.GetValue() / 255.0f;\n        const f32 bg_green = Settings::values.bg_green.GetValue() / 255.0f;\n        const f32 bg_blue = Settings::values.bg_blue.GetValue() / 255.0f;",
         "        // The launcher has already faded to this ink. Avoid a visibly\n        // different second loading screen, without dropping empty-frame\n        // presents while Vulkan/guest shaders initialize.\n        const f32 bg_red = quiet_loading_handoff ? 0.024f :\n            Settings::values.bg_red.GetValue() / 255.0f;\n        const f32 bg_green = quiet_loading_handoff ? 0.035f :\n            Settings::values.bg_green.GetValue() / 255.0f;\n        const f32 bg_blue = quiet_loading_handoff ? 0.039f :\n            Settings::values.bg_blue.GetValue() / 255.0f;"),
        ("        if (hud.width && (hud.loading || (render_area.width >= hud_units(hud.width + 16) &&\n                                          render_area.height >= hud_units(64)))) {",
         "        if (hud.width && !quiet_loading_handoff &&\n            render_area.width >= hud_units(hud.width + 16) &&\n            render_area.height >= hud_units(64)) {"),
        ("            const VkRect2D scissor = hud.loading ? VkRect2D{{0, 0}, render_area} :\n                VkRect2D{{static_cast<int32_t>(hud_units(16)), static_cast<int32_t>(hud_units(16))},\n                         {hud_units(hud.width), hud_units(48)}};",
         "            const VkRect2D scissor{\n                {static_cast<int32_t>(hud_units(16)), static_cast<int32_t>(hud_units(16))},\n                {hud_units(hud.width), hud_units(48)}};"),
        ("            if (hud.loading) {\n                // The loading scene fills the picture: tell it how large that is.\n                constants.x = render_area.width;\n                constants.y = render_area.height;\n            } else {\n                // Where the text starts in this picture, and the picture's height for its size.\n                constants.x = hud_units(hud.x);\n                constants.y = hud_units(hud.y);\n                constants.width = render_area.height;\n            }",
         "            // Only the regular FPS overlay reaches this pass. No second\n            // full-screen splash is submitted on the warm-up swapchain.\n            constants.x = hud_units(hud.x);\n            constants.y = hud_units(hud.y);\n            constants.width = render_area.height;"),
    ):
        assert loader_source.count(before) == 1, "pinned native loader overlay moved"
        assert expected["vulkan_window_adapt_pass.cpp"].read_text().count(after) == 1, "native loader delta changed"
        loader_source = loader_source.replace(before, after)
    loader_path.write_text(loader_source)
    # R01: reconstruct only the exact opt-in graphics telemetry deltas on top
    # of the formerly validated generator output. The active Vulkan fork and
    # shader owners remain full checked-in sources; generator only acts as a
    # BYTE-FOR-BYTE parity oracle, never as production patcher.
    metrics_deltas = {
        "vulkan_renderer.cpp": [
            ("#include \"display_refresh.h\"", "#include \"display_refresh.h\"\n#include \"frame_metrics.h\""),
            ("    RenderScreenshot(framebuffers);\n    if (::Eden::Display::SkipFrame()) {", "    RenderScreenshot(framebuffers);\n    // Count a source callback separately from submitted or displayed frames.\n    ::Eden::FrameMetrics::OnSourceComposite();\n    if (::Eden::Display::SkipFrame()) {\n        ::Eden::FrameMetrics::OnSourceSkipped();"),
            ("        present_manager.Present(generated);\n    }\n#endif", "        present_manager.Present(generated);\n        ::Eden::FrameMetrics::OnGeneratedQueued();\n    }\n#endif"),
            ("    present_manager.Present(frame);\n    scheduler.DispatchWork();", "    present_manager.Present(frame);\n    ::Eden::FrameMetrics::OnRealQueued();\n    scheduler.DispatchWork();"),
            ("    scheduler.Flush(*frame->render_ready);\n    present_manager.Present(frame);\n}\n\nvoid RendererVulkan::Report() const {", "    scheduler.Flush(*frame->render_ready);\n    present_manager.Present(frame);\n    ::Eden::FrameMetrics::OnLoadingQueued();\n}\n\nvoid RendererVulkan::Report() const {"),
        ],
        "vulkan_present_manager.cpp": [
            ("#include \"common/settings.h\"", "#include \"common/settings.h\"\n#include \"frame_metrics.h\""),
            ("    // Present\n    swapchain.Present(render_semaphore);\n}", "    // CPU API return only, not proof of HDMI scanout.\n    swapchain.Present(render_semaphore);\n    ::Eden::FrameMetrics::OnSwapchainPresentReturned();\n}"),
        ],
    }
    for file_name, replacements in metrics_deltas.items():
        path = actual[file_name]
        contents = path.read_text()
        for old, updated in replacements:
            assert contents.count(old) == 1, ("R01 pinned Vulkan site drift", file_name, old[:75])
            contents = contents.replace(old, updated)
        assert contents.count('::Eden::FrameMetrics::') == (5 if file_name == 'vulkan_renderer.cpp' else 1), ("telemetry count drift", file_name)
        path.write_text(contents)

    # N65: vendor's generic sparse requirements query is a reviewed
    # additive API. Reconstruct the exact generator baseline from the
    # maintained vendor header/implementation, not by skipping those files.
    # The independent N65 compiled host oracle checks behavior and failures.
    normalized_expected = {}
    hname = 'include/video_core/vulkan_common/vulkan_wrapper.h'
    cname = 'vulkan_wrapper.cpp'
    # N66: keep the production generator deterministic. The one additive
    # research native sparse queue API is maintained in vendor, and its actual
    # implementation is executed by check_native_sparse_bind.py (UBSan).
    # For byte parity remove only that exact method, never waive the header.
    n66_header = expected[hname].read_text()
    n66_start = '    VkResult BindSparse(Span<VkBindSparseInfo> bind_infos,'
    n66_end = '    VkResult Present(const VkPresentInfoKHR& present_info)'
    assert n66_header.count(n66_start) == 1 and n66_header.count(n66_end) == 1
    n66_begin = n66_header.index(n66_start)
    n66_finish = n66_header.index(n66_end, n66_begin)
    n66_extension = n66_header[n66_begin:n66_finish]
    assert n66_extension.count('BindSparseImage(VkImage image') == 1
    assert 'if (!queue || !dld || !dld->vkQueueBindSparse)' in n66_extension
    assert 'return BindSparse(submit, completion);' in n66_extension
    assert 'VkSparseImageMemoryBindInfo image_info' in n66_extension
    assert 'VkSparseImageOpaqueMemoryBindInfo tail_info' in n66_extension
    assert 'wait_semaphore ? &wait_semaphore : nullptr' in n66_extension
    assert 'signal_semaphore ? &signal_semaphore : nullptr' in n66_extension
    assert 'wait_semaphore == signal_semaphore' in n66_extension
    baseline_queue = '''    VkResult BindSparse(Span<VkBindSparseInfo> bind_infos,
                        VkFence fence = VK_NULL_HANDLE) const noexcept {
        return dld->vkQueueBindSparse(queue, bind_infos.size(), bind_infos.data(), fence);
    }

'''
    stripped_n66 = n66_header[:n66_begin] + baseline_queue + n66_header[n66_finish:]
    n66_path = temp / 'normalized-vendor-n66' / hname
    n66_path.parent.mkdir(parents=True, exist_ok=True)
    n66_path.write_text(stripped_n66)
    normalized_expected[hname] = n66_path

    header = normalized_expected[hname].read_text()
    anchor = '    VkMemoryRequirements GetImageMemoryRequirements(VkImage image) const noexcept;'
    extension = '''

    // N65: query the actual sparse 2D tile/mip-tail requirements.
    // No DeviceDispatch layout change: resolve entrypoint on demand.
    [[nodiscard]] std::vector<VkSparseImageMemoryRequirements>
        GetSparseImageMemoryRequirements(VkImage image) const;'''
    assert header.count(anchor + extension) == 1, 'N65 vendor sparse header changed'
    normalized_h = header.replace(anchor + extension, anchor)
    source = expected[cname].read_text()
    begin = 'std::vector<VkSparseImageMemoryRequirements>\nDevice::GetSparseImageMemoryRequirements(VkImage image) const {'
    end = 'std::vector<VkPipelineExecutablePropertiesKHR> Device::GetPipelineExecutablePropertiesKHR('
    assert source.count(begin) == 1 and source.count(end) == 1, 'N65 wrapper owner moved'
    start = source.index(begin)
    finish = source.index(end, start)
    ext = source[start:finish]
    assert ext.count('GetSparseImageMemoryRequirements(VkImage image)') == 1
    assert 'vkGetImageSparseMemoryRequirements' in ext
    assert 'if (!fn) return {};' in ext
    assert 'if (!count || count > 64) return {};' in ext
    assert 'if (!count || count > requirements.size()) return {};' in ext
    normalized_c = source[:start] + source[finish:]
    for name, value in ((hname, normalized_h), (cname, normalized_c)):
        p = temp/'normalized-vendor-n65'/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value)
        normalized_expected[name] = p

    # N56: compare the source generator to the exact pre-experiment owner.
    # The driver-cache guard is compiled only by opt-in NS2 research builds.
    n56_name = 'vk_pipeline_cache_cost.cpp'
    n56_before = '        u32 cache_version;\n        file.read(magic_number.data(), magic_number.size())'
    n56_after = '''        u32 cache_version;
#ifdef EDEN_NS2_PIPELINE_CACHE_GUARD
        // Reject truncated (including failed tellg) Vulkan driver cache headers
        // before reading or subtracting an unsigned header size.
        if (end < std::streampos{static_cast<std::streamoff>(
                      magic_number.size() + sizeof(cache_version))}) {
            file.close();
            LOG_WARNING(Common_Filesystem, "Short Vulkan driver cache; rebuilding fresh");
            Common::FS::RemoveFile(filename);
            return create_pipeline_cache(0, nullptr);
        }
#endif
        file.read(magic_number.data(), magic_number.size())'''
    n56_current = expected[n56_name].read_text()
    assert n56_current.count(n56_after) == 1, 'N56 vendor guard differs from exact owner'
    assert n56_current.count('Saved PS5 driver pipeline cache atomically') == 1
    n56_baseline = n56_current.replace(n56_after, n56_before)
    n56_file = temp/'normalized-vendor-n56'/n56_name
    n56_file.parent.mkdir(parents=True, exist_ok=True)
    n56_file.write_text(n56_baseline)
    normalized_expected[n56_name] = n56_file
    # N57's optional ASTC methods are owned by these SAME vendor Vulkan TUs.
    # Reverse only exact reviewed additions, then require original F07 SHA
    # and full generated-source byte parity. No generator files or exemptions.
    from ns2.native_astc_vendor_parity import normalized as normalize_n57
    for name, baseline in normalize_n57(root).items():
        p = temp/'normalized-vendor-n57'/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(baseline)
        normalized_expected[name] = p

    # N72: exact vendor-owned serialized sparse submit API. Preserve full
    # baseline byte-equivalence after removing only these additive guards.
    n72_additions = {
        'include/video_core/renderer_vulkan/vk_scheduler.h': (
            '    // NS2 N72 BEGIN: route sparse page binds through the same submit mutex',
            '    // NS2 N72 END\n',
        ),
        'vulkan_scheduler.cpp': (
            '// NS2 N72 BEGIN: serialized sparse Vulkan page submission',
            '// NS2 N72 END\n\n',
        ),
    }
    for name, (begin, end) in n72_additions.items():
        source = normalized_expected.get(name, expected[name]).read_text()
        assert source.count(begin) == 1 and source.count(end) == 1, (name, 'N72 owner changed')
        first, last = source.index(begin), source.index(end)
        extension = source[first:last + len(end)]
        assert '#ifdef EDEN_NS2_SPARSE_QUEUE_BRIDGE' in extension
        assert 'BindSparseImage(' in extension
        if name.endswith('.cpp'):
            assert 'std::scoped_lock lock{submit_mutex};' in extension
            assert 'device.GetGraphicsQueue().BindSparseImage(' in extension
            assert extension.index('std::scoped_lock lock{submit_mutex};') < extension.index(
                'device.GetGraphicsQueue().BindSparseImage(')
        suffix = last + len(end)
        # Header integration inserted one spacer newline beyond the marker.
        if name.endswith('vk_scheduler.h'):
            assert source[suffix:suffix + 2] == '\n\n', 'N72 header spacing changed'
            suffix += 2
        baseline = source[:first] + source[suffix:]
        normalized = temp/'normalized-vendor-n72'/name
        normalized.parent.mkdir(parents=True, exist_ok=True)
        normalized.write_text(baseline)
        normalized_expected[name] = normalized

    mismatches=[name for name in sorted(actual) if not filecmp.cmp(actual[name],normalized_expected.get(name, expected[name]),shallow=False)]
    if mismatches:
        # Print a tightly bounded exact diff before failing. The generator and
        # active files previously looked equivalent in high-level assertions,
        # forcing repeated CI runs to diagnose a single byte of drift.
        from difflib import unified_diff
        from itertools import islice
        for name in mismatches[:5]:
            generated, versioned = actual[name], normalized_expected.get(name, expected[name])
            if not name.endswith(('.cpp', '.h', '.py', '.cmake')):
                print(f'VULKAN_ORACLE_BINARY_DIFF {name} SHA256={hashlib.sha256(generated.read_bytes()).hexdigest()} '
                      f'active_SHA256={hashlib.sha256(versioned.read_bytes()).hexdigest()}', flush=True)
                continue
            diff = unified_diff(generated.read_text().splitlines(keepends=True),
                                versioned.read_text().splitlines(keepends=True),
                                fromfile=f'generated/{name}', tofile=f'active/{name}')
            for line in islice(diff, 130):
                print(line, end='', flush=True)
        raise AssertionError(f'vendored Vulkan C++ differs from pinned generated source: {mismatches}')
    # Versioned code must compile after fresh clone at a different checkout
    # path: forbids CMake/host absolute paths embedded in generated C++.
    for name, file in expected.items():
        if name.endswith(('.cpp', '.h')):
            data=file.read_text()
            assert '#include "/private/tmp/' not in data and '#include "/home/runner/' not in data,(name,'checkout-specific include')
    assert '#include "performance.h"' in expected['vk_pipeline_cache_cost.cpp'].read_text()
    assert len(actual)>=35
    cmake=(root/'headless/vulkan.cmake').read_text()
    assert 'vendor/encore-active/eden-vulkan' in cmake
    assert 'file(COPY "${EDEN_ACTIVE_VULKAN}/" DESTINATION "${PORT_BUILD_DIR}")' in cmake
    assert 'execute_process(COMMAND python3 "${PORT_ROOT}/tools/prepare-vulkan-port.py"' not in cmake
    print(f'VENDORED_VULKAN_FORK_EQUIVALENT_OK files={len(actual)} active=versioned not regenerated')
