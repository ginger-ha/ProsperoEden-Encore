#!/usr/bin/env python3
"""Static source-owner guard for research NS2 CMake overlays, not a native build."""
from __future__ import annotations
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
CMAKE = (ROOT / "headless/CMakeLists.txt").read_text(encoding="utf-8")
NS2 = ROOT / "vendor/encore-active/ns2-experimental/src/core"

def require(condition: bool, reason: str) -> None:
    if not condition:
        raise AssertionError(reason)

def main() -> int:
    try:
        # Imported emulator patches are credited in docs, never build options.
        require("Eglantine" not in CMAKE and "EGLANTINE_" not in CMAKE,
                "External emulator name leaked into native build options")
        for feature in ("GPU_RANGE_BATCH", "PIPELINE_CACHE", "VIEW", "CONTINUITY"):
            flag = f"EDEN_NS2_{feature}_EXPERIMENTAL"
            require(f"option({flag}" in CMAKE and f"if({flag})" in CMAKE and
                    f"{flag} OR" in CMAKE.split("# Release gate: Vulkan/RADV", 1)[1],
                    "NS2 research flag not release-forbidden: " + flag)
        # QMD3's virtual RasterizerInterface must be the SAME reviewed
        # header in every research native consumer; a private override in
        # RasterizerVulkan alone does not compile or preserve the vtable ABI.
        rasterizer_abi = (ROOT / "vendor/sources/eden/src/video_core/rasterizer_interface.h").read_text()
        require('virtual bool DispatchNativeCompute(const Tegra::NativeComputeLaunch&)' in rasterizer_abi and
                'configure_file("${EDEN_NS2_RASTERIZER_INTERFACE}"' in CMAKE and
                'target_compile_definitions(video_core PUBLIC EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL=1)' in CMAKE and
                'target_compile_definitions(core PUBLIC EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL=1)' in CMAKE,
                "Native QMD3 RasterizerInterface selector or public ABI guard missing")
        # Experimental engine code may have only one maintained vendor owner.
        require((ROOT / "vendor/encore-active/ns2-helpers/include/npdm_layout.h").is_file(),
                "The NPDM parser must use the maintained vendor ACID helper")
        legacy_engine = ROOT / "headless/ns2"
        remaining = {str(path.relative_to(legacy_engine))
                     for path in legacy_engine.rglob("*") if path.is_file()}
        require(not remaining,
                "Unexpected NSW2 source outside vendor: " + repr(remaining))
        for group in ("am", "ampere", "cpu6", "gpu_session",
                      "graphics_supervisor", "hle", "nvdrv", "nvdrv_as",
                      "nvdrv_gpu", "self_controller"):
            require((ROOT / "vendor/encore-active/ns2-runtime" / group).is_dir() and
                    ("headless/ns2/" + group) not in CMAKE,
                    "NS2 research CMake must own engine source in vendor: " + group)
        # Host JIT CMake is also an engine source selector, not just native CMake.
        jit_recipe = (ROOT / "tools/ns2/jit-host/CMakeLists.txt").read_text()
        require("headless/ns2/cpu6" not in jit_recipe and
                jit_recipe.count('vendor/encore-active/ns2-runtime/cpu6') >= 3 and
                "Required vendor CPU6 Dynarmic exclusive monitor is missing" in jit_recipe,
                "Host JIT must use the six-core vendor exclusive monitor, not four-core fallback")
        # All Ampere opcode/address-map tests must use the same canonical table.
        require(not (ROOT / "headless/ns2/gpu").exists(),
                "Obsolete duplicate Ampere/ISA tree must not return")
        ampere_smoke = (ROOT / "tools/check-ns2-ampere-host.py").read_text()
        require('OVERLAY=ROOT/"vendor/encore-active/ns2-runtime/ampere"' in ampere_smoke and
                'PROBE = OVERLAY / "shader_recompiler/frontend/ampere/probe.cpp"' in ampere_smoke and
                'str(PROBE)' in ampere_smoke and
                'headless/ns2/gpu' not in ampere_smoke,
                "Host Ampere ISA tests must use the real renderer-selected source owner")
        # Refuse the regression to duplicated/outdated whole engine owners.
        # One versioned vendor submodule owns every experimental native overlay.
        for legacy in ("overrides", "eglantine", "dynarmic"):
            root = ROOT / "headless" / "ns2" / legacy
            require(not root.exists() or not any(root.rglob("*")),
                    "Stale NSW2 engine clone reappeared: " + str(root))
            require(("headless/ns2/" + legacy) not in CMAKE,
                    "Native CMake selected obsolete NSW2 owner: " + legacy)
        vendor = ROOT / "vendor" / "encore-active"
        # Vendored GPU memory algorithms remain shared Encore source, not an
        # external emulator namespace (upstream attribution stays in docs).
        for path in ("core/ns2_egl_continuity_guard.h",
                     "video_core/ns2_egl_gpu_range_batch.h"):
            header = (vendor / "ns2-helpers/include" / path).read_text()
            require("namespace Eden::NS2::GpuMemory" in header and
                    "namespace Eden::NS2::Eglantine" not in header,
                    "NS2 shared GPU memory helper namespace drift: " + path)
        maintained = [
            "ns2-a64/dynarmic/frontend/A64/decoder/a64.inc",
            "ns2-a64/dynarmic/frontend/A64/translate/impl/a64_branch.cpp",
            "ns2-experimental/src/core/file_sys/program_metadata.cpp",
            "ns2-experimental/src/core/loader/nso.cpp",
            "ns2-helpers/include/core/loader/ns2_nso_preflight.h",
            "ns2-helpers/include/core/ns2_egl_continuity_guard.h",
            "ns2-helpers/include/video_core/ns2_egl_gpu_range_batch.h",
            "eden-core/overrides/core/device_memory_manager.inc",
            "eden-core/src/video_core/memory_manager.cpp",
            "eden-vulkan/vk_texture_cache_cost.cpp",
        ]
        require(all((vendor / path).is_file() for path in maintained),
                "NSW2 vendor source ownership or checkout is incomplete")
        require('option(EDEN_NS2_METADATA_EXPERIMENTAL' in CMAKE,
                "No metadata opt-in")
        require('option(EDEN_NS2_EXEFS_EXPERIMENTAL' in CMAKE,
                "No ExeFS opt-in")
        require('option(EDEN_NS2_CPU6_EXPERIMENTAL' in CMAKE,
                "No CPU6 opt-in")
        require('EDEN_NS2_CPU6_EXPERIMENTAL OR' in
                CMAKE.split("# Release gate: Vulkan/RADV", 1)[1],
                "Final release must reject CPU6 experiment")
        cpu6_condition = CMAKE.split("if(EDEN_NS2_CPU6_EXPERIMENTAL)", 1)[1].split(
            "set(EDEN_NS2_CPU6_ROOT", 1
        )[0]
        require(
            "if(NOT EDEN_NS2_A64_EXPERIMENTAL OR NOT EDEN_NS2_METADATA_EXPERIMENTAL)"
            in cpu6_condition and
            "OR EDEN_NS2_CPU6_EXPERIMENTAL OR" not in cpu6_condition,
            "Six-core research selector must not reject itself"
        )
        cpu6 = ROOT / "vendor/encore-active/ns2-runtime/cpu6"
        require("NUM_CPU_CORES = 6" in (cpu6 / "core/hardware_properties.h").read_text(),
                "Six-core hardware map missing")
        require("MAX_NUM_CPU_CORES = 6" in
                (cpu6 / "dynarmic/interface/exclusive_monitor.h").read_text(),
                "Six-slot Dynarmic exclusive monitor missing")
        bridge_gate = CMAKE[CMAKE.index("# N3m: compile a renderer-callable"):
                           CMAKE.index("# Release gate: Vulkan/RADV")]
        require('option(EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL' in bridge_gate and
                'NOT EDEN_NS2_AMPERE_PROBE_EXPERIMENTAL' in bridge_gate and
                'NOT EDEN_NS2_METADATA_EXPERIMENTAL' in bridge_gate and
                'NOT EDEN_NS2_GPU_SESSION_EXPERIMENTAL' in bridge_gate and
                'NOT EDEN_NS2_NVDRV_EXPERIMENTAL' in bridge_gate and
                'NOT PS5_NATIVE OR NOT EDEN_PS5_VULKAN' in bridge_gate and
                'target_sources(video_core PRIVATE "${EDEN_NS2_VULKAN_SHADER_BRIDGE}")'
                    in bridge_gate and
                'EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL OR'
                    in CMAKE[CMAKE.index("# Release gate: Vulkan/RADV"):],
                "NS2 renderer compilation must be explicitly opt-in and release-forbidden")
        require('target_sources(video_core PRIVATE "${EDEN_NS2_NATIVE_GPU_SPIRV_CAPTURE}")'
                    in bridge_gate and
                'ns2_shader_spirv_compile.cpp' in bridge_gate,
                "Explicit NS2 GMMU shader compile source must only exist in bridge mode")
        registry_header = ROOT / "vendor/encore-active/ns2-runtime/hle/core/hle/service/nvdrv/devices/native_gpu_process_registry.h"
        registry_code = registry_header.read_text()
        require("CaptureTicket(" in registry_code and "IsCurrent(" in registry_code and
                "generation" in registry_code and
                "std::numeric_limits<std::uint64_t>::max()" in registry_code,
                "NS2 shader ownership must use nonreusable session tickets")
        # Native graphics must be selected by the exact 0xC797 channel bind,
        # not merely by the title ID; raw Ampere must never enter Maxwell CFG.
        engine_registry = (ROOT / "vendor/encore-active/ns2-runtime/nvdrv_gpu/core/hle/service/nvdrv/devices/native_gpu_channel_registry.h").read_text()
        puller = (ROOT / "vendor/encore-active/ns2-runtime/gpu_dispatch/video_core/engines/puller.cpp").read_text()
        active_vk = (ROOT / "vendor/encore-active/eden-vulkan/vk_pipeline_cache_cost.cpp").read_text()
        # Boot-stall triage is PS5-only and bounded. Future captured logs
        # must distinguish missing GPU-session IPC, GPFIFO admission,
        # Ampere class binding and VI2 commands instead of just guest_frame_handoff=0.
        service_dir = ROOT / "vendor/encore-active/ns2-runtime/gpu_session/core/hle/service/am/service"
        supervisor_source = (ROOT / "vendor/encore-active/ns2-runtime/graphics_supervisor/core/hle/service/am/service/graphics_supervisor.cpp").read_text()
        gpu_session_source = (service_dir / "gpu_session.cpp").read_text()
        gpu_worker_source = (service_dir / "gpu_worker.cpp").read_text()
        gpu_worker_header = (service_dir / "gpu_worker.h").read_text()
        # Sparse 215 may release the VA before physical retirement succeeds.
        # Do not call destructive GMMU release again on retry or teardown.
        require("bool gmmu_released{};" in gpu_worker_header and
                "bool nvmap_released{};" in gpu_worker_header and
                "std::weak_ptr<void> nvmap_lifetime;" in gpu_worker_header and
                "region.nvmap_released = true;" in gpu_worker_source and
                "region.nvmap_lifetime.expired()" in gpu_worker_source and
                "dense->second.gmmu_released = true;" in gpu_worker_source and
                "const bool released = (physical && dense->second.gmmu_released) ||"
                    in gpu_worker_source and
                "if (mapping.sparse && dense != m_dense_regions.end() &&"
                    in gpu_worker_source,
                "Native sparse 215 release must be retry-safe through teardown")
        nvdrv_source = (ROOT / "vendor/encore-active/ns2-runtime/nvdrv_gpu/core/hle/service/nvdrv/devices/nvhost_gpu.cpp").read_text()
        for owner, source in (("gpu_session", gpu_session_source),
                              ("gpu_worker", gpu_worker_source),
                              ("vi2", supervisor_source),
                              ("graphics_supervisor", supervisor_source)):
            require(f"EDEN_NS2_IPC owner={owner}" in source and
                    "#ifdef PS5_NATIVE" in source and
                    "requests.fetch_add(" in source or
                    (owner in ("vi2", "graphics_supervisor") and
                     f"EDEN_NS2_IPC owner={owner}" in source and
                     "calls.fetch_add(" in source),
                    f"Missing bounded NS2 boot trace for {owner}")
        require("{31,&IVi2Session::VsyncEvent" in supervisor_source and
                "{32,&IVi2Session::VsyncEvent" in supervisor_source and
                "ScheduleLoopingEvent(" in supervisor_source and
                "EDEN_NS2_VI2_VSYNC" in supervisor_source,
                "Eglantine upstream boot gate: VI2 31/32 must signal 60Hz even before first Present")
        require("EDEN_NS2_GPU_WORKER_RESULT cmd=" in gpu_worker_source and
                "TraceNs2WorkerResult(" in gpu_worker_source and
                "EDEN_NS2_IPC owner=vi2" in supervisor_source,
                "NS2 boot trace must record guest-visible GPU worker IPC results")
        # P2.3 must select a complete maintained SPIR-V emitter only in
        # the native NS2 bridge. The original fourteen-bank source is kept.
        qmd_spirv = (ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/backend/spirv/spirv_emit_context.cpp").read_text()
        native_direct_cbuf = (ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/backend/spirv/emit_spirv_context_get_set.cpp").read_text()
        native_graphics_cache = (ROOT / "vendor/encore-active/eden-vulkan/vk_pipeline_cache_cost.cpp").read_text()
        pristine_direct_cbuf = (ROOT / "vendor/sources/eden/src/shader_recompiler/backend/spirv/emit_spirv_context_get_set.cpp").read_text()
        qmd_indirect = (ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/native_indirect_cbuf.h").read_text()
        qmd_bridge = (ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/renderer_spirv_bridge.cpp").read_text()
        qmd_env = (ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/native_qmd_compute_environment.h").read_text()
        host_native_spirv = (ROOT / "tools/check-ns2-spirv-host.py").read_text()
        ir_native_fixture = (ROOT / "tools/ns2/test_ampere_real_spirv.cpp").read_text()
        qmd_launch_capture = (ROOT / "vendor/encore-active/ns2-runtime/ampere/video_core/ns2_shader_spirv_compile.cpp").read_text()
        qmd_spirv_header = (ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/renderer_spirv_bridge.h").read_text()
        pristine_spirv = (ROOT / "vendor/sources/eden/src/shader_recompiler/backend/spirv/spirv_emit_context.cpp").read_text()
        require('set(EDEN_NS2_QMD_CBUF_SPIRV' in CMAKE and
                'list(REMOVE_ITEM eden_ns2_shader_sources "backend/spirv/spirv_emit_context.cpp")' in CMAKE and
                'list(APPEND eden_ns2_shader_sources "${EDEN_NS2_QMD_CBUF_SPIRV}")' in CMAKE and
                'set(EDEN_NS2_QMD_CBUF_DIRECT_SPIRV' in CMAKE and
                'list(REMOVE_ITEM eden_ns2_shader_sources "backend/spirv/emit_spirv_context_get_set.cpp")' in CMAKE and
                'list(APPEND eden_ns2_shader_sources "${EDEN_NS2_QMD_CBUF_DIRECT_SPIRV}")' in CMAKE and
                'const Id safe_offset{ctx.OpSelect' in native_direct_cbuf and
                'ctx.Const(0x10000U / element_size)' in native_direct_cbuf and
                'if (offset.U32() >= 0x10000U)' in native_direct_cbuf and
                'return ctx.ConstantNull(result_type);' in native_direct_cbuf and
                'if (!Shader::Ampere::NativeSpirvCbufBoundsActive())' in native_direct_cbuf and
                'const Id cond = ctx.OpULessThanEqual(ctx.TypeBool(), buffer_offset, ctx.Const(0xFFFFu));' in native_direct_cbuf and
                'NativeSpirvCbufBoundsScope native_bounds;' in qmd_bridge and
                'Shader::Ampere::NativeSpirvCbufBoundsScope native_bounds;' in native_graphics_cache and
                'NativeGraphicsStageMaskSupported(configured_stages)' in native_graphics_cache and
                'NativeGraphicsStageMaskSupported(keyed_stages)' in native_graphics_cache and
                'const auto native_session_current = [&]()' in native_graphics_cache and
                native_graphics_cache.count('if (!native_session_current())') == 3 and
                'GraphicsPipeline* selected = CurrentGraphicsPipelineSlowPath();' in native_graphics_cache and
                'return selected;' in native_graphics_cache and
                'IsGraphicsCurrent(&graphics_engine,*active_engine)' in
                    (ROOT / "tools/ns2/test_native_ampere_channel.cpp").read_text() and
                'catch (const std::exception& exception) {' in native_graphics_cache and
                'if (!Shader::Ampere::NativeSpirvCbufBoundsActive())' in native_graphics_cache and
                'LOG_WARNING(Render_Vulkan, "NS2 native graphics shader rejected:' in native_graphics_cache and
                'NativeSpirvCbufBoundsActive(), "native CBUF mode not enabled"' in ir_native_fixture and
                'ctx.OpAccessChain(uniform_type, cbuf, ctx.u32_zero_value,' in native_direct_cbuf and
                'if (offset.IsImmediate() || !ctx.profile.has_broken_robust)' in pristine_direct_cbuf and
                'std::span{buf_labels}.first(bank_count)' in qmd_spirv and
                'OpReturnValue(ConstantNull(buffer_type))' in qmd_spirv and
                'NormalizeNativeQmdIndirectCbufIR(ir, qmd_enabled_cbuf_mask)' in qmd_bridge and
                'kNativeQmdIndirectCbufBanks = 8' in qmd_indirect and
                'info.constant_buffer_mask = enabled_mask;' in qmd_indirect and
                'return declared_mask == program.info.constant_buffer_mask;' in qmd_indirect and
                '!(enabled_mask & bit)' in qmd_indirect and
                'NativeQmdStaticCbufReadExtent(offset.U32())' in qmd_indirect and
                'all_offsets_static' in qmd_indirect and
                'info.uses_global_memory || info.stores_global_memory' in qmd_indirect and
                'bank_indices[bank_count] = bank;' in qmd_spirv and
                'OpULessThan(' in qmd_spirv and
                '0x10000U / bytes_per_element' in qmd_spirv and
                'OpSelect(U32[1], valid_offset, binding, Const(~u32{0}))' in qmd_spirv and
                'make_accessor(U32[4], &UniformDefinitions::U32x4, 16)' in qmd_spirv and
                'CheckNativeQmdIndirectCbufIR();' in ir_native_fixture and
                'run(sparse, true, true, 0, 0, true, 0x10000);' in ir_native_fixture and
                'verify_native_ldc(0, 0x01U, true);' in ir_native_fixture and
                'verify_native_ldc(7, 0x80U, true);' in ir_native_fixture and
                'verify_native_ldc(7, 0x01U, false);' in ir_native_fixture and
                'verify_native_ldc(8, 0xffU, false);' in ir_native_fixture and
                'const Id cbuf{cbufs[bank_indices[i]].*member_ptr};' in qmd_spirv and
                'enabled_cbuf_mask |= u32{1} << bank;' in qmd_launch_capture and
                'qmd_enabled_cbuf_mask = 0xffU' in qmd_spirv_header and
                'shader_info.constant_buffer_mask != declared_banks' in qmd_env and
                'OpSwitch(binding, buf_labels[0], buf_literals, buf_labels);' in pristine_spirv and
                'native_cbuf_emitters.get(name, SHADER / name)' in host_native_spirv and
                '"backend/spirv/emit_spirv_context_get_set.cpp":' in host_native_spirv,
                "Sparse QMD3 CBUF source, native test selection, and Vulkan layout must agree")
        qmd_header = (ROOT / "vendor/encore-active/ns2-runtime/gpu_dispatch/video_core/native_qmd.h").read_text()
        require("AcquireNativeQmdSession(" in engine_registry and
                "qmd_sessions.erase(process)" in engine_registry and
                "NativeGpuChannelRegistry::AcquireNativeQmdSession(" in puller and
                "ProcessNativeComputeQmd(" in puller and
                "session->scheduler.Signal(" in puller and
                "rasterizer->SignalFence(" in puller and
                "IsFullyMappedRange(addr, sizeof(data))" in puller and
                "IsCurrent(channel, ticket)" in puller,
                "Ampere QMD3 must run on authenticated process session with real mapped fence handling")
        require(
            '#include "video_core/native_shader_capture.h"' in puller and
            'Shader::Ampere::CaptureNativeComputeShader(' in puller and
            'VideoCommon::ReadNs2GpuShader' in puller and
            'registry.AcquireComputeTranslationCache(' in puller and
            'registry.IsComputeCurrent(' in puller and
            'EDEN_NS2_COMPUTE_SHADER_CAPTURE' in puller and
            'backend=missing' in puller and
            'return false;\n            });' in puller,
            "Native QMD3 must capture real mapped Ampere shader under GPU epoch without forging Vulkan execution")
        require(
            "constexpr bool NativeComputePlainRegister(" in qmd_header and
            "Tegra::NativeComputePlainRegister(reg)" in puller and
            "Tegra::NativeComputePlainRegister(method)" in puller and
            "engine.regs.reg_array[reg] = value;" in puller and
            "engine.regs.reg_array[method] = values.back();" in puller and
            "case 0x6cU: case 0x6dU:" in qmd_header and
            "case 0xaeU: case 0xafU: case 0xb0U:" in qmd_header and
            "case 0x107U:" in qmd_header and
            "case 0x6c3U:" in qmd_header,
            "Ampere Compute plain-register fast path must retain QMD/upload/semaphore side effects")
        # The EglantinePS5 shader audit found dropped last-lane vertex
        # varyings and truncated NVN2 compute storage binding arrays. These
        # independently produce missing geometry/black or jumping textures.
        attribute_owner = (ROOT / "vendor/encore-active/ns2-runtime/shader_resource/include/shader_recompiler/frontend/ir/attribute.h").read_text()
        buffers_owner = (ROOT / "vendor/encore-active/ns2-runtime/shader_resource/include/video_core/buffer_cache/buffer_cache_base.h").read_text()
        pinned_attribute = (ROOT / "vendor/sources/eden/src/shader_recompiler/frontend/ir/attribute.h").read_text()
        pinned_buffers = (ROOT / "vendor/sources/eden/src/video_core/buffer_cache/buffer_cache_base.h").read_text()
        require("attribute <= Attribute::Generic31X" in pinned_attribute and
                "NUM_STORAGE_BUFFERS = 16" in pinned_buffers and
                "target_include_directories(shader_recompiler BEFORE PRIVATE \"${EDEN_NS2_SHADER_RESOURCE_ROOT}\")" in CMAKE and
                "target_include_directories(video_core BEFORE PRIVATE \"${EDEN_NS2_SHADER_RESOURCE_ROOT}\")" in CMAKE,
                "Pristine Eden baseline and opt-in research-only graphics headers are mandatory")
        lower_owner = (ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/lower_to_maxwell.h").read_text()
        require("attribute <= Attribute::Generic31W" in attribute_owner and
                "NUM_STORAGE_BUFFERS = 32" in buffers_owner and
                "NUM_STORAGE_BUFFERS <= 32" in buffers_owner and
                "case 0x234: { // HSETP2" in lower_owner and
                "case 0xb82: { // LDC U8/S8/U16/S16/U32/U64" in lower_owner and
                "if (width > 5 ||" in lower_owner,
                "NX2 shader/texture ABI requires full attribute vector, 32 storage slots, and reviewed half/narrow constant lowering")
        native_negative = (ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/translation_cache.cpp").read_text()
        native_negative_header = (ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/translation_cache.h").read_text()
        require("if (!copy.Ready()) ++stats.negative_hits" in native_negative and
                "if (!image.Ready()) ++stats.rejected;" in native_negative and
                "std::equal(e.native.begin(), e.native.end(), native.begin())" in native_negative and
                "u64 negative_hits{};" in native_negative_header,
                "NS2 negative shader cache must verify full bytes, bound entries and retain rejected status")
        # A QMD may be produced by the guest GPU immediately before
        # PCAS. A raw CPU-side ReadBlockUnsafe would miss Vulkan buffer/
        # query-cache dirty data even when all 4 KiB GMMU pages are mapped.
        qmd_reader = puller.split(
            "void Puller::ProcessNativeComputeQmdAt(", 1)[1].split(
            "auto release = ", 1)[0]
        require("IsFullyMappedRange(addr, sizeof(data))" in qmd_reader and
                "pusher.memory_manager.ReadBlock(addr, data.data(), sizeof(data));" in qmd_reader and
                "ReadBlockUnsafe" not in qmd_reader and
                qmd_reader.index("IsFullyMappedRange") < qmd_reader.index("ReadBlock(") and
                "memory->ReadBlock(address, dest, size)" in
                    (ROOT / "vendor/encore-active/ns2-runtime/ampere/video_core/native_shader_capture.cpp").read_text(),
                "P2.7 QMD3 must see GPU-dirty descriptor bytes via coherent GMMU read")
        qmd_dispatch = puller.split(
            "void Puller::ProcessNativeComputeQmdAt(", 1)[1].split(
            "/// Calls a GPU engine method.", 1)[0]
        require("NativeQmdReleaseTargetsMapped(" in qmd_header and
                "for (const std::uint32_t base : {24U, 28U, 52U})" in qmd_header and
                "!is_mapped(addr, sizeof(std::uint32_t))" in qmd_header and
                "Tegra::NativeQmdReleaseTargetsMapped(" in qmd_dispatch and
                "if (mapped && release_targets_mapped)" in qmd_dispatch and
                qmd_dispatch.index("NativeQmdReleaseTargetsMapped(") <
                    qmd_dispatch.index("pusher.rasterizer->DispatchNativeCompute(*launch)") and
                'if (!addr || (addr & 3U)' in qmd_dispatch,
                "Native QMD3 completion targets must all be mapped before shader submission")
        require("class NativeQmdScheduler" in qmd_header and
                "std::array<Word, 3> ReleaseSlots{24, 28, 52}" in qmd_header and
                "std::unordered_map<Address, State> states;" in qmd_header and
                "static inline std::unordered_map<Address, State>" not in qmd_header and
                "native shader dispatch required" in qmd_header and
                "QMD dependency underflow" in qmd_header,
                "Upstream-derived QMD3 scheduler must isolate title state, reject unsafe dispatch and retain third release slot")
        require("ProcessNativeComputeInlineQmd(" in puller and
                "if (reg == 0x107)" in puller and
                "if (method == 0x107)" in puller and
                "AccelerateInlineToMemory(" in puller and
                "std::copy_n(regs.begin() + 0xc8" in puller and
                "ProcessNativeComputeQmdAt(pusher, address, 3, subchannel, 0x107)" in puller and
                "ProcessNativeComputeQmdAt(DmaPusher& pusher, GPUVAddr address" in puller and
                "qmd_units >= (u64{1} << 41)" in puller and
                "qmd_pointer = static_cast<u32>(qmd_units)" not in puller,
                "Native inline Compute QMD must upload coherent 256-byte descriptor before PCAS")
        require("ProcessNativeComputeReportSemaphore(" in puller and
                "if (reg == 0x6c3)" in puller and
                "if (method == 0x6c3)" in puller and
                "NativeComputeSemaphoreReduction(" in puller and
                "QueryType::Payload" in puller,
                "Ampere report semaphores must work for direct and TU104 MME emits")
        require("EDEN_NS2_GPFIFO submit=" in nvdrv_source and
                "EDEN_NS2_GPU_BIND count=" in puller and
                "engine == 0xc7c0" in puller and
                "std::atomic<unsigned>" in puller,
                "NS2 boot trace requires concrete GPFIFO and Ampere bind witnesses")
        # Native compute macros must use the TU104 96-bit interpreter and
        # authenticated PCAS/QMD3, never reinterpret a Maxwell launch.
        require("engine_id == static_cast<EngineID>(0xc7c0)" in puller and
                "engine == static_cast<EngineID>(0xc7c0)" in puller and
                "EDEN_NS2_COMPUTE_QMD_UNSUPPORTED" in puller and
                "CallNativeCompute(" in puller and
                "native_compute->ExecuteStaged(" in puller and
                "native_compute_macro_method" in puller and
                "native_compute_parameters" in puller and
                "if (method == 0xae || method == 0xaf || method == 0xb0)" in puller and
                "ProcessNativeComputeQmd(pusher, reg, value, subchannel)" in puller,
                "NS2 compute MME must emit native PCAS into QMD3 without Maxwell launch")
        require("bool invalid_compute_register_read = false;" in puller and
                "if (index >= Tegra::Engines::KeplerCompute::Regs::NUM_REGS)" in puller and
                "const auto allowed = [&](u32 reg, u32)" in puller and
                "return !invalid_compute_register_read;" in puller and
                'fail("compute MME interpreter or register access rejected");' in puller,
                "Untrusted Ampere MME register reads must fail closed before QMD publication")
        mme_state = (ROOT / "vendor/encore-active/ns2-runtime/gpu_dispatch/video_core/native_ampere_macro_state.h").read_text()
        require("Result ExecuteStaged(" in mme_state and
                "const auto old_dram = dram;" in mme_state and
                "dram = old_dram;" in mme_state and
                "shadow[address] = value;" in mme_state and
                "pending.emplace_back(address, value);" in mme_state and
                "for (const auto& [address, value] : pending)" in mme_state and
                "commit(address, value);" in mme_state and
                "MaxPendingMethods = 65536" in mme_state and
                "native_3d->ExecuteStaged(" in puller and
                "native_compute->ExecuteStaged(" in puller and
                "return !bad_read;" in puller and
                "return !invalid_compute_register_read;" in puller,
                "P2.4 native TU104 macros must stage all emissions and restore DRAM on failure")
        require("BindGraphicsEngine(" in puller and
                "UnbindGraphicsSubchannel(" in puller and
                "CaptureGraphicsTicket(" in engine_registry and
                "IsGraphicsCurrent(" in engine_registry and
                "channel_generation" in engine_registry,
                "Native 3D rendering requires per-channel authenticated class identity")
        native_capture = (ROOT / "vendor/encore-active/ns2-runtime/ampere/video_core/native_shader_capture.cpp").read_text()
        native_capture_core = (ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/capture.cpp").read_text()
        native_capture_fixture = (ROOT / "tools/ns2/test_ampere_gpu_capture.cpp").read_text()
        native_branch_tables = (ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/program_capture.h").read_text()
        require("opcode == 0x949 || opcode == 0x958" in native_capture_core and
                "if (bank >= 18 || (offset & 3U) ||" in native_branch_tables and
                "offset > 0x10000U - entries * sizeof(u32)" in native_branch_tables and
                "indirect_uniform.status==NativeCaptureStatus::UnresolvedIndirectBranch" in native_capture_fixture and
                "table[0].cbuf_offset==0xffc0U" in native_capture_fixture and
                "TrackCaptureIndirectBranches(motif).empty()" in native_capture_fixture and
                "TranslateCaptureIndirectTargets" in native_branch_tables and
                "prior.native_code_offset != native_offset" in native_branch_tables and
                "mapped_header_table->front().entries" in native_capture_fixture and
                "aliased_image.ValidForCompiler()" in native_capture_fixture and
                "native BRX emits branch-to-restoration stubs" in (
                    ROOT / "tools/ns2/test_ampere_lower_bridge.cpp").read_text() and
                "native indirect branch through barrier scope" in (
                    ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/lower_to_maxwell.h").read_text() and
                "native indirect control flow requires checked CBUF plan" in (
                    ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/lower_to_maxwell.h").read_text() and
                "raw native BRX cannot enter Maxwell CFG" in (
                    ROOT / "tools/ns2/test_ampere_lower_bridge.cpp").read_text() and
                "native indirect target PC mismatch" in (
                    ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/lower_to_maxwell.h").read_text() and
                "BRX expected native PC must agree" in (
                    ROOT / "tools/ns2/test_ampere_lower_bridge.cpp").read_text() and
                "MakeNativeIndirectBranchPlans" in native_branch_tables and
                "compiled_brx.Ready()" in native_capture_fixture and
                "stable_cbuf.mutate_between_reads" in native_capture_fixture and
                "CaptureNativeGraphicsShaderChecked" in native_capture_core and
                "ReadNs2GraphicsCbuf" in native_capture and
                "IsFullyMappedRange(address, sizeof(u32))" in native_capture and
                "dispatch_plans=MakeNativeIndirectBranchPlans" in native_capture_fixture and
                "ResolveCaptureIndirectBranchesChecked" in native_branch_tables and
                "snapshot_reads>16" in native_capture_fixture and
                "unexpected_brx" in native_capture_fixture,
                "Native BRX/BRXU must never publish unresolved targets or probe CBUF past 64 KiB")
        native_pipeline_source = (ROOT / "vendor/encore-active/eden-vulkan/vk_pipeline_cache_cost.cpp").read_text()
        require(native_pipeline_source.count(
                    "const VideoCommon::Ns2GraphicsCbufContext cbuf_context{") == 2 and
                "i == 5 ? 4U : 0U" in native_pipeline_source and
                "native_translation_cache.get(), &cbuf_context" in native_pipeline_source and
                "native_translation_cache.get(),\n                &cbuf_context" in native_pipeline_source and
                "const auto& buffers = owner->engine->state" in native_capture and
                "if (!cbuf.enabled || !cbuf.address" in native_capture,
                "NS2 graphics BRX requires real per-stage mapped CBUF admission at both pipeline paths")
        require("const auto checked_read = " in native_capture_core and
                "checked_read(gpu_base, header.data(), header.size())" in native_capture_core and
                "checked_read(addr, page.data(), aligned_batch)" in native_capture_core and
                "checked_read(addr, bytes.data(), bytes.size())" in native_capture_core and
                "catch (const std::exception&)" in native_capture_core and
                "result.status = NativeCaptureStatus::TranslationFailed;" in native_capture_core and
                "throwing_header.status==NativeCaptureStatus::Unmapped" in native_capture_fixture and
                "throwing_compute.first_error_offset==16" in native_capture_fixture and
                "throwing_batch.Ready()" in native_capture_fixture and
                "failed.status = Shader::Ampere::NativeCaptureStatus::TranslationFailed;" in native_capture and
                "return Shader::Ampere::NativeMaxwellEnvironment::CreateOwned(" in native_capture and
                "catch (const std::exception&)" in native_capture,
                "Native Ampere guest GMMU reads, lowering, capture must fail closed on exceptions")
        require("if (!memory->IsFullyMappedRange(address, size))" in native_capture and
                "memory->ReadBlock(address, dest, size);" in native_capture and
                "catch (const std::exception&)" in native_capture and
                "return false;" in native_capture,
                "NS2 GMMU native shader capture must fail closed on changed mappings")
        require("AcquireGraphicsTranslationCache(" in engine_registry and
                "std::shared_ptr<Shader::Ampere::NativeTranslationCache>" in engine_registry and
                "translation_cache{}" in engine_registry and
                "AcquireGraphicsTranslationCache(" in native_capture and
                "#ifdef EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL" in native_capture and
                "4 * 1024 * 1024, 32" in native_capture and
                "NativeTranslationCache::GetOrTranslate" in
                    (ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/translation_cache.cpp").read_text(),
                "N3m shader cache must be bounded and bound to authenticated engine epoch")
        require("native_translation_cache.get()" in active_vk and
                "AcquireGraphicsTranslationCache(maxwell3d, *native_ticket)" in active_vk and
                "AcquireGraphicsTranslationCache(maxwell3d, *ticket)" in active_vk,
                "N3m active Vulkan translation must reuse exact GPU session cache")
        require('#ifdef EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL' in active_vk and
                "CaptureGraphicsTicket(maxwell3d)" in active_vk and
                "CaptureNs2GraphicsShaderFromGpu(" in active_vk and
                "CreateNs2GraphicsShaderEnvironment(" in active_vk and
                "IsGraphicsCurrent(maxwell3d, *ticket)" in active_vk and
                "native_env->Image().diagnostic_cache_key" in active_vk and
                "RefreshStages(graphics_key.unique_hashes)" in active_vk,
                "NS2 shader capture must feed maintained Vulkan pipeline only when authenticated")
        require('target_include_directories(video_core BEFORE PRIVATE "${PORT_ROOT}/vendor/encore-active/ns2-runtime/hle")'
                    in bridge_gate,
                "NS2 video_core must compile with the session registry overlay")
        pipeline_source = ROOT / "vendor/encore-active/ns2-runtime/ampere/video_core/ns2_shader_spirv_compile.cpp"
        require(pipeline_source.is_file() and
                "CaptureNativeGraphicsShader(" in pipeline_source.read_text() and
                "CompileCapturedNs2VertexSpirvFromReader(" in pipeline_source.read_text() and
                "ReadNs2GpuShader, &memory" in pipeline_source.read_text() and
                "CompileReviewedNativeGraphicsSpirv(" in pipeline_source.read_text() and
                "registry.CaptureTicket(process)" in pipeline_source.read_text() and
                pipeline_source.read_text().count("registry.IsCurrent(*session)") == 10 and
                "CompileCapturedNs2ComputeSpirvFromReader(" in pipeline_source.read_text() and
                "CaptureNativeComputeShader(" in pipeline_source.read_text() and
                "CreateComputeOwned(" in pipeline_source.read_text() and
                "CompileReviewedNativeComputeSpirv(" in pipeline_source.read_text() and
                "NativeSpirvStatus::InactiveSession" in pipeline_source.read_text(),
                "Real GMMU-to-SPIR-V owner is missing")
        # Native QMD3 metadata must reach the authenticated SPIR-V compiler
        # without going through Switch 1's 40-bit Kepler launch format.
        qmd_environment = ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/native_qmd_compute_environment.h"
        qmd_api = ROOT / "vendor/encore-active/ns2-runtime/ampere/video_core/ns2_shader_spirv_compile.h"
        require(qmd_environment.is_file() and
                "class NativeQmdComputeEnvironment final" in qmd_environment.read_text() and
                "cbuf.gpu_address + offset" in qmd_environment.read_text() and
                "launch.block" in qmd_environment.read_text() and
                "launch.local_pos_bytes + launch.local_crs_bytes" in qmd_environment.read_text() and
                "BuildResourcePlan(" in qmd_environment.read_text() and
                "shader_info.storage_buffers_descriptors" in qmd_environment.read_text() and
                "ReadStorageDescriptor(" in qmd_environment.read_text() and
                "std::array<u32, 4> descriptor{};" in qmd_environment.read_text() and
                "descriptor.data(), sizeof(descriptor)" in qmd_environment.read_text() and
                "const auto record = ReadStorageDescriptor(desc.cbuf_index, offset);" in qmd_environment.read_text() and
                "A sparse GMMU unmap or failed CPU-backed span lookup" in qmd_environment.read_text() and
                "const bool known_size = tag == 0 && bytes != 0" in qmd_environment.read_text() and
                "NativeQmdGlobalMemoryLayoutMatches(" in qmd_environment.read_text() and
                "result.global_layout_resolved = result.uses_global_memory;" in qmd_environment.read_text() and
                "info.nvn_buffer_used.test(i)" in qmd_environment.read_text() and
                "i < info.nvn_buffer_used.size(); ++i" in qmd_environment.read_text() and
                "if (info.nvn_buffer_used.test(i))" in qmd_environment.read_text() and
                "info.stores_global_memory && !storage.is_written" in qmd_environment.read_text() and
                "host_ssbo_alignment" in qmd_environment.read_text() and
                "CompileCapturedNs2QmdComputeSpirv(" in qmd_api.read_text() and
                "CompileCapturedNs2QmdComputeSpirv(" in pipeline_source.read_text() and
                "CompileCapturedNs2QmdComputeSpirvWithResources(" in qmd_api.read_text() and
                "CompileCapturedNs2QmdComputeSpirvWithResources(" in pipeline_source.read_text() and
                "resource_owner->BuildResourcePlan(*compiled.info)" in pipeline_source.read_text() and
                "CompileCapturedNs2ComputeSpirv(" in pipeline_source.read_text() and
                (ROOT / "tools/ns2/test_native_qmd_compute_environment.cpp").is_file(),
                "QMD3 49-bit Compute metadata must reach authenticated SPIR-V compilation")
        # P2.3 bounded global memory reuses the real shared SPIR-V
        # U64 address -> NVN SSBO dispatch. The QMD3 adapter authenticates
        # the descriptor count and all referenced backing before Vulkan.
        global_emit = (ROOT / "vendor/sources/eden/src/shader_recompiler/backend/spirv/spirv_emit_context.cpp").read_text()
        require("void EmitContext::DefineGlobalMemoryFunctions(const Info& info)" in global_emit and
                "if (!info.uses_global_memory || !profile.support_int64)" in global_emit and
                "if (!info.nvn_buffer_used[index])" in global_emit and
                "ssbo_addr_cbuf_offset" in global_emit and
                "ssbo_size_cbuf_offset" in global_emit and
                "min_ssbo_alignment" in global_emit and
                "global_layout_resolved" in qmd_environment.read_text(),
                "Native global memory requires genuine SPIR-V SSBO lookup and authenticated QMD backing")
        native_spirv_bridge = (ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/renderer_spirv_bridge.cpp").read_text()
        native_compute_spirv = native_spirv_bridge.split(
            "NativeSpirvResult CompileReviewedNativeComputeSpirv(", 1)[1].split(
            "NativeSpirvResult CompileReviewedNativeVertexSpirv(", 1)[0]
        require("if (ir.info.uses_global_memory)" in native_compute_spirv and
                "!profile.support_int64 || !profile.support_descriptor_aliasing" in native_compute_spirv and
                "storage.cbuf_index - cbuf.index < cbuf.count" in native_compute_spirv and
                "ir.info.used_constant_buffer_types |=" in native_compute_spirv and
                "Shader::IR::Type::U32 | Shader::IR::Type::U32x2" in native_compute_spirv and
                native_compute_spirv.index("ir.info.used_constant_buffer_types |=") <
                    native_compute_spirv.index("Shader::Backend::SPIRV::EmitSPIRV("),
                "P2.3 native global memory must declare real U32/U32x2 CBUF aliases before SPIR-V emission")
        # Native Vulkan must use the authenticated Ampere SPIR-V shader and
        # QMD buffer resources, never the legacy Maxwell launch descriptor.
        native_vk_rasterizer = (ROOT / "vendor/encore-active/eden-vulkan/vulkan_rasterizer.cpp").read_text()
        native_vk_pipeline = (ROOT / "vendor/encore-active/eden-vulkan/vk_compute_pipeline_cost.cpp").read_text()
        native_vk_pipeline_h = (ROOT / "vendor/encore-active/eden-vulkan/include/video_core/renderer_vulkan/vk_compute_pipeline.h").read_text()
        native_vk_cache = (ROOT / "vendor/encore-active/eden-vulkan/vk_pipeline_cache_cost.cpp").read_text()
        native_vk_cache_h = (ROOT / "vendor/encore-active/eden-vulkan/include/video_core/renderer_vulkan/vk_pipeline_cache.h").read_text()
        native_vk_port = (ROOT / "tools/prepare-vulkan-port.py").read_text()
        require(
            "bool ComputePipeline::ConfigureNative(" in native_vk_pipeline and
            "resources.StageVulkanBufferBindings(" in native_vk_pipeline and
            "resources.ValidateGpuBufferMappings(mapped)" in native_vk_pipeline and
            "Shader::Ampere::NativeQmdGlobalMemoryLayoutMatches(" in native_vk_pipeline and
            "device.IsShaderInt64Supported()" in native_vk_pipeline and
            "device.GetStorageBufferAlignment()" in native_vk_pipeline and
            "NativeQmdGlobalMemoryLayoutMatches(" in native_vk_port and
            "buffer_cache.ObtainBuffer(" in native_vk_pipeline and
            "WriteDescriptorBuffer(device, descriptor_buffer_layout," in native_vk_pipeline and
            "bool ConfigureNative(" in native_vk_pipeline_h and
            "CreateNativeComputePipeline(" in native_vk_cache_h and
            "PipelineCache::CreateNativeComputePipeline(" in native_vk_cache and
            "std::shared_ptr<ComputePipeline> PipelineCache::CreateNativeComputePipeline(" in native_vk_cache and
            "std::vector<NativeComputeReuse> native_compute_reuse;" in native_vk_cache_h and
            "it->channel_generation != ticket->channel_generation" in native_vk_cache and
            "it->words.size() != shader.words.size()" in native_vk_cache and
            "std::equal(it->words.begin(), it->words.end(), shader.words.begin())" in native_vk_cache and
            "std::rotate(it, it + 1, native_compute_reuse.end());" in native_vk_cache and
            "if (native_compute_reuse.size() == 12)" in native_vk_cache and
            "RetainNativeComputeUntilGpuTick(" in native_vk_rasterizer and
            "shader.ComputeMetadataReady()" in native_vk_cache and
            "registry.IsComputeCurrent(kepler_compute, *ticket)" in native_vk_cache and
            "vk::ShaderModule spv_module = BuildShader(device, shader.words)" in native_vk_cache and
            "U92 native QMD3 direct ComputePipeline buffer binding" in native_vk_port and
            "U93 authenticated native ComputePipeline SPIR-V to driver handoff" in native_vk_port and
            "CaptureComputeTicket(kepler_compute)" in native_vk_cache and
            "CurrentComputePipeline() {" in native_vk_cache,
            "NS2 native Vulkan QMD3 typed buffer/image handoff must remain session-verified")
        # U96: native buffer-only Compute inherits NS1's no-worker-wait
        # inside cache-lock ordering. Keep native-only staging fail-closed.
        require(
            "guest_descriptor_queue.AcquireKnownEmpty(uses_descriptor_buffer);" in native_vk_pipeline and
            "U97 native typed descriptor buffer binding index" in native_vk_port and
            "const u32 buffer_index{};\n            cmdbuf.SetDescriptorBufferOffsetsEXT(" in native_vk_pipeline and
            "0, buffer_index, descriptor_buffer_offset);" in native_vk_pipeline and
            "const auto preflight_guest = [&]" in native_vk_rasterizer and
            "guest_descriptor_queue.PreflightExactGuestDraw(" in native_vk_rasterizer and
            "descriptor_buffer_ring.PreflightFrameReuse(scheduler)" in native_vk_rasterizer and
            "pipeline->PreflightDescriptorScratch();" in native_vk_rasterizer and
            native_vk_rasterizer.index("const auto preflight_guest = [&]") <
                native_vk_rasterizer.index("if (!pipeline->ConfigureNative(") and
            "U96 native compute preflights GPU worker waits before BufferCache lock" in native_vk_port,
            "NS2 Vulkan Compute preflight must occur before locked native descriptor binding")
        bridge_source = ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/renderer_spirv_bridge.cpp"
        stage_policy = ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/native_graphics_stage_policy.h"
        require(stage_policy.is_file() and
                'stage == Shader::Stage::VertexB || stage == Shader::Stage::Fragment' in stage_policy.read_text() and
                'static_assert(!IsStandaloneNativeGraphicsStage(Shader::Stage::VertexA))' in stage_policy.read_text() and
                'static_assert(!IsStandaloneNativeGraphicsStage(Shader::Stage::Compute))' in stage_policy.read_text() and
                'NativeGraphicsStageMaskSupported(u32 mask)' in stage_policy.read_text() and
                'static_assert(!NativeGraphicsStageMaskSupported(0x01))' in stage_policy.read_text() and
                'static_assert(NativeGraphicsStageMaskSupported(0x23))' in stage_policy.read_text() and
                'assert(NativeGraphicsStageMaskSupported(mask))' in
                    (ROOT / "tools/ns2/test_ampere_isa.cpp").read_text(),
                "NS2 standalone shader admission must exclude VertexA merge and compute")
        require(bridge_source.is_file() and
                "CompileReviewedNativeGraphicsSpirv(" in bridge_source.read_text() and
                "IsStandaloneNativeGraphicsStage(env.ShaderStage())" in bridge_source.read_text() and
                "CompileReviewedNativeVertexSpirv(" in bridge_source.read_text() and
                "env.ShaderStage() != Shader::Stage::VertexB" in bridge_source.read_text() and
                "ir.stage != env.ShaderStage()" in bridge_source.read_text(),
                "Native SPIR-V must preserve real Fragment/VertexB stage and strict vertex-only ABI")
        require("CompileCapturedNs2GraphicsSpirvFromReader(" in pipeline_source.read_text() and
                "CompileCapturedNs2GraphicsSpirv(" in pipeline_source.read_text() and
                "IsStandaloneNativeGraphicsStage(original->ShaderStage())" in pipeline_source.read_text() and
                "CompileReviewedNativeGraphicsSpirv(" in pipeline_source.read_text() and
                "original->ShaderStage() != Shader::Stage::VertexB" in pipeline_source.read_text(),
                "Native renderer capture must keep standalone Fragment stage and original VertexB-only contract")
        require("CompileReviewedNativeMergedVertexSpirv(" in bridge_source.read_text() and
                "Shader::Maxwell::MergeDualVertexPrograms(ir_a,ir_b,vertex_b)" in bridge_source.read_text() and
                "ir_a.stage!=Shader::Stage::VertexA" in bridge_source.read_text() and
                "ir_b.stage!=Shader::Stage::VertexB" in bridge_source.read_text() and
                "CompileCapturedNs2MergedVertexSpirvFromReader(" in pipeline_source.read_text() and
                "CompileCapturedNs2MergedVertexSpirv(" in pipeline_source.read_text() and
                "gpu_address_a==gpu_address_b" in pipeline_source.read_text() and
                pipeline_source.read_text().count("registry.IsCurrent(*session)") >= 5,
                "NS2 dual native vertex shader compilation must use real merged IR and session ticket")
        require(
            'if(EDEN_NS2_EXEFS_EXPERIMENTAL OR EDEN_SHARED_NS2_EXEFS)' in CMAKE and
            'set(EDEN_SHARED_NS2_EXEFS ON)' in CMAKE and
            'if(NOT EDEN_REVIEWED_DUAL_NPDM)' in CMAKE and
            'if(PS5_NATIVE AND EDEN_FINAL_RELEASE_PROFILE AND EDEN_REVIEWED_DUAL_NPDM)'
                in CMAKE,
            "ExeFS must require reviewed dual NPDM for research or shared release")
        require('EDEN_NS2_METADATA_EXPERIMENTAL OR EDEN_NS2_EXEFS_EXPERIMENTAL' in CMAKE,
                "Final release must reject experimental selectors")
        selection = CMAKE.index("# Experimental ExeFS bridge must be selected AFTER")
        am_selection = CMAKE.index("# Research-only Switch 2 AM command 320.")
        release_gate = CMAKE.index("# Release gate: Vulkan/RADV")
        require(selection < am_selection < release_gate,
                "NS2 AM and ExeFS owners must be selected after maintained Encore owners")
        preflight_header = ROOT / "vendor/encore-active/ns2-helpers/include/core/loader/ns2_nso_preflight.h"
        romdir_source = ROOT / "vendor/encore-active/ns2-experimental/src/core/loader/deconstructed_rom_directory.cpp"
        require(preflight_header.is_file() and "PreflightNso(" in preflight_header.read_text() and
                "MaxImageBytes" in preflight_header.read_text() and
                '"core/loader/ns2_nso_preflight.h"' in romdir_source.read_text() and
                "if (metadata.IsSwitch2())" in romdir_source.read_text() and
                "PreflightNso(header, module_file->GetSize())" in romdir_source.read_text(),
                "NS2 ExeFS must validate actual NSO0 file length before legacy loader allocations")
        handoff_header = ROOT / "vendor/encore-active/ns2-helpers/include/core/loader/ns2_process_handoff.h"
        require(handoff_header.is_file() and
                "VerifyUncompressedTextHandoff(" in handoff_header.read_text() and
                '"core/loader/ns2_process_handoff.h"' in romdir_source.read_text() and
                "process.GetMemory().ReadBlock(" in romdir_source.read_text() and
                "metadata.IsSwitch2()" in romdir_source.read_text(),
                "NS2 KProcess text handoff must use bounded process readback")
        thread_guard = ROOT / "vendor/encore-active/ns2-helpers/include/core/loader/ns2_main_thread_admission.h"
        require(thread_guard.is_file() and
                "MainThreadPermitted(" in thread_guard.read_text() and
                "MainThreadPermitted(allowed_cores, allowed_priorities" in romdir_source.read_text() and
                "process.GetCoreMask()" in romdir_source.read_text() and
                "process.GetPriorityMask()" in romdir_source.read_text(),
                "NS2 guest process must check real kernel scheduling permissions")
        public_svc = ROOT / "vendor/encore-active/ns2-helpers/include/core/loader/ns2_public_homebrew_svc.h"
        require(public_svc.is_file() and
                "MissingPublicHelloSvcs(" in public_svc.read_text() and
                "MissingPublicHelloSvcs(" in
                    (ROOT / "tools/ns2/test_real_kcapabilities.py").read_text() and
                "MissingPublicHelloSvcs(" in
                    (ROOT / "tools/ns2/test_nso_process_handoff.cpp").read_text() and
                "IsPublicHelloFixture(" not in romdir_source.read_text() and
                "MissingPublicHelloSvcs(" not in romdir_source.read_text() and
                'ns2_public_homebrew_svc.h' not in romdir_source.read_text(),
                "Fixture-only SVC checks must stay in host tests, not the generic NSW2 runtime")
        svc_trace = ROOT / "vendor/encore-active/ns2-helpers/include/core/loader/ns2_svc_trace.h"
        svc_owner = ROOT / "vendor/encore-active/ns2-runtime/kernel/core/hle/kernel/svc.cpp"
        svc_contracts = {
            "vendor_trace_header": svc_trace.is_file(),
            "vendor_real_dispatcher": svc_owner.is_file(),
            "real_process_registration": "SvcTrace::Register(process.GetProcessId())" in romdir_source.read_text(),
            "real_kernel_trace_call": svc_owner.is_file() and "Eden::NS2::SvcTrace::Next(process.GetProcessId())" in svc_owner.read_text(),
            "single_dispatcher_macro": svc_owner.is_file() and "#ifdef EDEN_NS2_SVC_TRACE" in svc_owner.read_text(),
            "research_compiler_gate": "target_compile_definitions(core PRIVATE EDEN_NS2_SVC_TRACE=1)" in CMAKE,
            "native_core_selection": 'list(APPEND eden_ns2_svc_sources "${EDEN_NS2_NATIVE_SVC_SOURCE}")' in CMAKE and
                'list(REMOVE_ITEM eden_ns2_svc_sources "hle/kernel/svc.cpp")' in CMAKE,
            "generator_removed": "prepare_svc_trace_owner.cmake" not in CMAKE,
            "generated_tu_removed": "ns2_svc.cpp" not in CMAKE,
        }
        require(all(svc_contracts.values()),
                "NS2 SVC owner drift: " + ",".join(k for k, good in svc_contracts.items() if not good))
        # Source ownership includes both review-gated shared NS1/NS2 owners
        # and opt-in native GPU research. Match the exact selected source
        # variables (including the two NVDRV overlay stages) instead of a
        # stale count from before kernel/audio/GPU-access integration.
        selected_owners = re.findall(
            r'set_property\(TARGET core PROPERTY SOURCES "\$\{([^}]+)\}"\)',
            CMAKE[selection:])
        expected_owners = [
            "eden_ns2_exefs_sources", "eden_ns2_svc_sources",
            "eden_ns2_gpu_access_sources", "eden_ns2_process_sources",
            "eden_ns2_kernel_sources", "eden_ns2_audio_sources",
            "eden_ns2_am_sources", "eden_ns2_scale_sources",
            "eden_ns2_nvdrv_sources", "eden_ns2_nvdrv_sources",
            "eden_ns2_research_kernel_sources", "eden_ns2_supervisor_sources",
        ]
        require(sorted(selected_owners) == sorted(expected_owners) and
                'target_compile_definitions(core PRIVATE EDEN_NS2_PROCESS_RUN_GUARD=1)' in CMAKE and
                'list(APPEND eden_ns2_process_sources "${EDEN_NS2_NATIVE_PROCESS_SOURCE}")' in CMAKE and
                'list(REMOVE_ITEM eden_ns2_process_sources "hle/service/os/process.cpp")' in CMAKE and
                'EDEN_NS2_PROCESS_RUN_GUARD_EXPERIMENTAL OR' in CMAKE,
                "Unexpected NS2 core source owner: ExeFS, SVC, process-run, AM, NVDRV and supervisor must stay isolated")
        require('EDEN_NS2_A64_EXPERIMENTAL OR EDEN_NS2_AM_EXPERIMENTAL OR' in CMAKE,
                "Final release must reject NS2 application-manager experiment")
        require('option(EDEN_NS2_AM_EXPERIMENTAL' in CMAKE and
                'if(NOT EDEN_NS2_METADATA_EXPERIMENTAL)' in CMAKE[am_selection:release_gate] and
                'list(FIND eden_ns2_am_sources "${EDEN_APP_FUNCTION_SOURCE}"' in CMAKE,
                "NS2 application manager must require metadata and maintained source owner")
        scale_selection = CMAKE.index("# Research-only AM proxy command 60 and graphics scaling service.")
        require(am_selection < scale_selection < release_gate,
                "Graphics scaling source owner must precede final release gate")
        require("option(EDEN_NS2_GRAPHICS_SCALE_EXPERIMENTAL" in CMAKE and
                "if(NOT EDEN_NS2_AM_EXPERIMENTAL)" in CMAKE[scale_selection:release_gate] and
                "EDEN_NS2_GRAPHICS_SCALE_EXPERIMENTAL OR" in CMAKE,
                "Graphics scaling option must depend on AM and remain release-forbidden")
        scale_root = ROOT / "vendor/encore-active/ns2-runtime/am/core/hle/service/am/service"
        proxy = (scale_root / "application_proxy.cpp").read_text()
        scale = (scale_root / "graphics_scaling_parameters_functions.cpp").read_text()
        require("{60, D<&IApplicationProxy::GetGraphicsScalingParametersFunctions>" in proxy and
                "GetGraphicsScalingParametersFunctions(" in proxy,
                "NS2 proxy command 60 must instantiate real graphics scaling service")
        require("{1050, nullptr, \"SetGraphicsScaleChangedNotificationEnabled\"}" in scale and
                "*out_parameters = {10, 1, 1}" in scale,
                "Research graphics scale must not pretend to implement notifications")
        session_selection = CMAKE.index("# Switch 2 GPU TIPC service and bounded worker transport.")
        require(session_selection < release_gate and
                'option(EDEN_NS2_GPU_SESSION_EXPERIMENTAL' in CMAKE and
                'EDEN_NS2_GPU_SESSION_EXPERIMENTAL OR' in CMAKE,
                "NS2 GPU service must remain opt-in and forbidden in release")
        require("if(NOT EDEN_NS2_NVDRV_EXPERIMENTAL)" in
                CMAKE[session_selection:release_gate] and
                'target_sources(core PRIVATE "${EDEN_NS2_GPU_SESSION_SOURCE}"' in CMAKE,
                "NS2 GPU service must require NVDRV and compile real source")
        session_root = ROOT / "vendor/encore-active/ns2-runtime/gpu_session/core/hle/service/am/service"
        require('std::shared_ptr<Nvidia::Module> m_module;' in
                (session_root / "gpu_session.h").read_text() and
                (session_root / "gpu_session.h").read_text().index(
                    "std::shared_ptr<Nvidia::Module> m_module") <
                (session_root / "gpu_session.h").read_text().index(
                    "std::shared_ptr<GpuWorkerSharedState> m_shared"),
                "NVDRV module must initialize before shared GPU FD owner")
        service_cpp = (session_root / "gpu_session.cpp").read_text()
        service_h = (session_root / "gpu_session.h").read_text()
        require("RegisterHandlersTipc(functions)" in service_cpp and
                "GpuSessionProtocol::DeviceSlots devices" in (session_root / "gpu_worker_shared.h").read_text() and
                "GpuSessionProtocol::AddressSpaceSlots address_spaces" in (session_root / "gpu_worker_shared.h").read_text() and
                "rb.Push(Kernel::ResultNotImplemented.raw)" in service_cpp and
                "{11, &IGpuSession::GetNotificationRange" in service_cpp and
                "{12, &IGpuSession::GetNotificationEvent" in service_cpp and
                "m_shared->event_context.CreateEvent" in service_cpp and
                "event_context.CloseEvent" in (session_root / "gpu_worker_shared.cpp").read_text() and
                "rb.PushCopyObjects(ctx, *readable)" in service_cpp and
                "IPC::ResponseBuilder rb{ctx, 2, 1, 0};" in service_cpp and
                "{21, &IGpuSession::RequestWorker" in service_cpp and
                "{22, &IGpuSession::AcquireWorker" in service_cpp and
                "CreateWorkerKernelSession(system, ctx" in service_cpp and
                "m_worker->Close(kernel)" in service_cpp and
                "client->Open(kernel)" in service_cpp and
                "{33, &IGpuSession::CreateAddressSpace" in service_cpp and
                "{41, &IGpuSession::CreateGraphicsDevice" in service_cpp and
                "{42, &IGpuSession::DestroyGraphicsDevice" in service_cpp and
                "{202, &IGpuSession::GetAddressSpacePartition" in service_cpp and
                "{203, &IGpuSession::GetAddressSpacePartition" in service_cpp and
                'm_module->Open("/dev/nvhost-as-gpu"' in service_cpp and
                "ioctl.raw = 0x40284109" in service_cpp and
                "ioctl.raw = 0xc0404108" in service_cpp and
                "m_shared->address_spaces.HasCapacity()" in service_cpp and
                "m_shared->address_spaces.Register(id)" in service_cpp,
                "NS2 GPU service must own real NVDRV descriptors and safely close them")
        worker_header = ROOT / "vendor/encore-active/ns2-runtime/hle/core/hle/service/am/service/gpu_worker_protocol.h"
        worker_cpp = worker_header.read_text()
        require("class MappingLedger" in worker_cpp and
                "LedgerStatus RecordMapped" in worker_cpp and
                "LedgerStatus RecordUnmapped" in worker_cpp and
                "DecodeMap(" in worker_cpp and "DecodeUnmap(" in worker_cpp and
                "DecodeModify(" in worker_cpp and
                "DecodeReleaseSparse(" in worker_cpp and
                "RecordSparse(" in worker_cpp and
                "RecordReleasedSparse(" in worker_cpp and
                "CanReserveSparse(" in worker_cpp and
                "CanReleaseSparse(" in worker_cpp and
                "DecodeSparseBatch(" in worker_cpp and
                "ContainsSparse(" in worker_cpp and
                "MaxMappings = 4096" in worker_cpp,
                "NS2 4K worker preflight / bounded ledger missing")
        shared_cpp = (session_root / "gpu_worker_shared.cpp").read_text()
        require("GpuWorkerSharedState::~GpuWorkerSharedState()" in shared_cpp and
                "address_spaces.OwnedIds()" in shared_cpp and
                "event_context.CloseEvent(event)" in shared_cpp and
                "module->GetContainer().CloseSession(" in shared_cpp and
                "module->Close(static_cast<Nvidia::DeviceFD>(*fd))" in shared_cpp and
                "NativeGpuProcessRegistry::Instance().Register(process)" in shared_cpp and
                "NativeGpuProcessRegistry::Instance().Unregister(native_process)" in shared_cpp,
                "Live worker handles must retain NVDRV FD and event ownership")
        worker_hle_cpp = (session_root / "gpu_worker.cpp").read_text()
        require("IGpuWorker::HandleSyncRequest" in worker_hle_cpp and
                "Kernel::ResultNotImplemented.raw" in worker_hle_cpp and
                "IGpuWorker::~IGpuWorker()" in worker_hle_cpp and
                "m_process->Close(kernel)" in worker_hle_cpp and
                "RegisterHandlersTipc(functions)" in worker_hle_cpp and
                "{101, &IGpuWorker::CreateGpuAccessibleMemory" in worker_hle_cpp and
                "{102, &IGpuWorker::DestroyGpuAccessibleMemory" in worker_hle_cpp and
                "LockForMapDeviceAddressSpace" in worker_hle_cpp and
                "Kernel::KMemoryState::FlagCanAlignedDeviceMap" in worker_hle_cpp and
                "Kernel::KMemoryState::FlagReferenceCounted" in worker_hle_cpp and
                "KMemoryAttribute::GpuAccessible" in worker_hle_cpp and
                "EDEN_SHARED_NS2_GPU_ACCESS_SVC" in CMAKE and
                "UnlockForDeviceAddressSpace" in worker_hle_cpp and
                "CreateHandle(size, handle)" in worker_hle_cpp and
                "handle->dupes == 1" in worker_hle_cpp and
                "Kernel::ResultBusy" in worker_hle_cpp and
                "m_shared->events[notification]->Signal(kernel)" in worker_hle_cpp and
                "DecodeGpuMemoryRelease(command)" in worker_hle_cpp and
                '{211, &IGpuWorker::NormalMapGpuMemory4K' in worker_hle_cpp and
                '{212, &IGpuWorker::NormalModifyGpuMemory4K' in worker_hle_cpp and
                '{213, &IGpuWorker::NormalUnmapGpuMemory4K' in worker_hle_cpp and
                'm_mappings.RecordMapped(*request)' in worker_hle_cpp and
                'm_mappings.RecordUnmapped(*request)' in worker_hle_cpp and
                'as->MapNative4K(' in worker_hle_cpp and
                'as->UnmapNative4K(' in worker_hle_cpp and
                'as->ModifyNativeKind(' in worker_hle_cpp and
                '{214, &IGpuWorker::CreateSparseRegion' in worker_hle_cpp and
                '{215, &IGpuWorker::DestroySparseRegion' in worker_hle_cpp and
                '{216, &IGpuWorker::ExecuteSparseMapRequests' in worker_hle_cpp and
                'as->RemapNativeSparse(staged)' in worker_hle_cpp and
                'ctx.GetReadBufferSize() == bytes' in worker_hle_cpp and
                'm_mappings.ContainsSparse(' in worker_hle_cpp and
                'm_shared->events[request->notification]->Signal(kernel)' in worker_hle_cpp and
                'as->ReserveNativeSparse4K(' in worker_hle_cpp and
                'as->ReleaseNativeSparse4K(' in worker_hle_cpp and
                'm_mappings.RecordSparse(' in worker_hle_cpp and
                'm_mappings.RecordReleasedSparse(' in worker_hle_cpp,
                "Native GPU worker IPC must reject unsupported mappings")
        # GSV must be able to resolve a registered, live guest AS FD to the
        # exact current KProcess GMMU; no cross-title address-space reuse.
        session_owner = (session_root / "gpu_session.cpp").read_text()
        session_header = (session_root / "gpu_session.h").read_text()
        native_as_owner = (ROOT / "vendor/encore-active/ns2-runtime/nvdrv_as/core/hle/service/nvdrv/devices/nvhost_as_gpu.cpp").read_text()
        require("GetRegisteredAddressSpace(u32 id)" in session_header and
                "IGpuSession::GetRegisteredAddressSpace(u32 id)" in session_owner and
                "m_shared->address_spaces.Registered(id)" in session_owner and
                "m_module->VerifyFD(" in session_owner and
                "as->OwnsNativeProcess(m_process)" in session_owner and
                "m_opened_gpu_as[id] = as;" in session_owner and
                "GetDevice<Nvidia::Devices::nvdevice>" in session_owner and
                "as.get() == live.get()" in session_owner and
                "m_opened_gpu_as" in session_header and
                "bool nvhost_as_gpu::OwnsNativeProcess(Kernel::KProcess* process)" in native_as_owner and
                "m_native_process == process && vm.initialised && gmmu" in native_as_owner,
                "Native GSV address-space resolver must enforce live FD and process-scoped GMMU")
        require('target_sources(core PRIVATE "${EDEN_NS2_GPU_SESSION_SOURCE}"' in CMAKE and
                '"${EDEN_NS2_GPU_WORKER_SOURCE}"' in CMAKE and
                '"${EDEN_NS2_GPU_SHARED_SOURCE}")' in CMAKE and
                "EDEN_NS2_GPU_WORKER_SOURCE" in CMAKE[session_selection:release_gate],
                "Native worker source must be gated with GPU session research owner")
        supervisor_selection = CMAKE.index("# Research-only SelfController -> GraphicsSupervisor")
        require(session_selection < supervisor_selection < release_gate and
                "EDEN_NS2_GRAPHICS_SUPERVISOR_EXPERIMENTAL OR" in CMAKE and
                "if(NOT EDEN_NS2_GPU_SESSION_EXPERIMENTAL OR NOT EDEN_NS2_AM_EXPERIMENTAL)" in CMAKE,
                "NS2 supervisor must require AM/GPU and be release-forbidden")
        require('list(FIND eden_ns2_supervisor_sources' in CMAKE and
                '"hle/service/am/service/self_controller.cpp" eden_ns2_self_idx' in CMAKE and
                'set_property(TARGET core PROPERTY SOURCES "${eden_ns2_supervisor_sources}")' in CMAKE,
                "NS2 supervisor must replace only pinned CMIF SelfController owner")
        sup_cpp = (ROOT / "vendor/encore-active/ns2-runtime/graphics_supervisor/core/hle/service/am/service/graphics_supervisor.cpp").read_text()
        self_cpp = (ROOT / "vendor/encore-active/ns2-runtime/self_controller/core/hle/service/am/service/self_controller.cpp").read_text()
        require("m_bootstrap.CanOpenGpuSession(packet, module != nullptr)" in sup_cpp and
                'GetService<Nvidia::NVDRV>("nvdrv:s", true)' in sup_cpp and
                "CreateMetadataSession(system, ctx," in sup_cpp and
                "handler->RegisterAddressSpace(*id)" in sup_cpp and
                "m_bootstrap.GpuContextReady()" in sup_cpp and
                "Kernel::ResultNotImplemented.raw" in sup_cpp and
                "{434, &IGraphicsSupervisor::RegisterGpuAddressSpace" in sup_cpp and
                "{497, &IGraphicsSupervisor::OpenGpuSession" in sup_cpp,
                "Supervisor must require real NVDRV module and register only owned GPU VA")
        require('{2000, &ISelfController::GetGraphicsSupervisor' in self_cpp and
                "server.RegisterSession(&session->GetServerSession()" in self_cpp and
                "rb.PushCopyObjects(ctx, m_graphics_supervisor_session)" in self_cpp,
                "CMIF SelfController must create a real supervisor copy-handle session")
        nvdrv_selection = CMAKE.index("# Native Switch 2 GPU capabilities IOCTLs, experimental only;")
        require(am_selection < nvdrv_selection < release_gate,
                "NVDRV research must select after maintained Encore owners and before release gate")
        require('option(EDEN_NS2_NVDRV_EXPERIMENTAL' in CMAKE and
                'EDEN_NS2_NVDRV_EXPERIMENTAL OR' in CMAKE and
                'list(FIND eden_ns2_nvdrv_sources' in CMAKE and
                '"hle/service/nvdrv/devices/nvhost_ctrl_gpu.cpp" eden_ns2_nvdrv_idx' in CMAKE,
                "NVDRV opt-in, original source owner or final release protection missing")
        native_as_root = ROOT / "vendor/encore-active/ns2-runtime/nvdrv_as/core/hle/service/nvdrv/devices"
        native_as_cpp = (native_as_root / "nvhost_as_gpu.cpp").read_text()
        native_as_h = (native_as_root / "nvhost_as_gpu.h").read_text()
        require('set(EDEN_NS2_NVDRV_AS_SOURCE' in CMAKE and
                '"hle/service/nvdrv/devices/nvhost_as_gpu.cpp" eden_ns2_as_idx' in CMAKE and
                'list(REMOVE_ITEM eden_ns2_nvdrv_sources' in CMAKE and
                'list(APPEND eden_ns2_nvdrv_sources "${EDEN_NS2_NVDRV_AS_SOURCE}")' in CMAKE and
                'target_include_directories(core BEFORE PRIVATE "${EDEN_NS2_NVDRV_GPU_ROOT}" "${EDEN_NS2_NVDRV_ROOT}" "${EDEN_NS2_NVDRV_AS_ROOT}")' in CMAKE and
                "MapNative4K(" in native_as_h and
                "UnmapNative4K(" in native_as_h and
                "ReserveNativeSparse4K(" in native_as_h and
                "ReleaseNativeSparse4K(" in native_as_h and
                "ModifyNativeKind(" in native_as_h and
                "allocation_map.lower_bound(address)" in native_as_cpp and
                "mapping_map.lower_bound(address)" in native_as_cpp and
                "nvmap.PinHandle(handle_id, false)" in native_as_cpp and
                "UnmapNative4K(u64 address, u64 size)" in native_as_cpp and
                "gmmu->MapSparse(address, size, false)" in native_as_cpp and
                "native_sparse_regions.emplace(address, size)" in native_as_cpp and
                "native_sparse_regions.erase(owned)" in native_as_cpp and
                "NativeSparseMappingTable native_sparse_mappings" in native_as_h and
                "std::map<u32, DAddr> native_sparse_pins" in native_as_h and
                "RemapNativeSparse(std::span<const NativeSparseRemapEntry>" in native_as_h and
                "native_sparse_mappings = std::move(updated)" in native_as_cpp and
                "native_sparse_pins.merge(newly_pinned)" in native_as_cpp and
                "nvmap.UnpinHandle(it->first)" in native_as_cpp and
                "needed.insert(range.handle)" in native_as_cpp,
                "Native 4KiB NVDRV address-space owner must be isolated and bounded")
        # The 426/427/428 video mapping owner needs an actual bounded,
        # process-owned NVMap-to-GMMU mapper; no legacy MapBufferEx shortcut.
        require("NvResult MapNativeImage(u32 handle_id, u64 source, u64 size, u64& address)" in native_as_h and
                "NvResult nvhost_as_gpu::MapNativeImage(" in native_as_cpp and
                "container.GetSession(handle->session_id)" in native_as_cpp and
                "vm.small_page_allocator->Allocate(pages)" in native_as_cpp and
                "vm.small_page_allocator->Free(allocated, pages)" in native_as_cpp and
                "gmmu->Map(gpu_address, pinned + source, size" in native_as_cpp and
                "mapping_map.emplace(gpu_address, Mapping(" in native_as_cpp and
                "NvResult nvhost_as_gpu::UnmapNative4K(" in native_as_cpp,
                "NS2 native GPU images must own real 4K VA, NVMap pins and GMMU mapping")
        require("EDEN_NS2_NVDRV_AS_SOURCE" in CMAKE[nvdrv_selection:release_gate],
                "Native AS owner is not gated under research-only NVDRV switch")
        channel_root = ROOT / "vendor/encore-active/ns2-runtime/nvdrv_gpu/core/hle/service/nvdrv/devices"
        native_channel_cpp = (channel_root / "nvhost_gpu.cpp").read_text()
        native_channel_h = (channel_root / "nvhost_gpu.h").read_text()
        process_registry = (
            ROOT / "vendor/encore-active/ns2-runtime/hle/core/hle/service/nvdrv/devices/native_gpu_process_registry.h"
        ).read_text()
        fence_plan = (
            ROOT / "vendor/encore-active/ns2-runtime/hle/core/hle/service/nvdrv/devices/native_gpu_submission.h"
        ).read_text()
        require('set(EDEN_NS2_NVDRV_GPU_SOURCE' in CMAKE and
                '"hle/service/nvdrv/devices/nvhost_gpu.cpp" eden_ns2_gpu_idx' in CMAKE and
                'list(APPEND eden_ns2_nvdrv_sources "${EDEN_NS2_NVDRV_GPU_SOURCE}")' in CMAKE and
                "EDEN_NS2_NVDRV_GPU_SOURCE" in CMAKE[nvdrv_selection:release_gate] and
                "UsesNativeAbi(DeviceFD fd) const;" in native_channel_h and
                "const auto it = sessions.find(fd);" in native_channel_cpp and
                "UsesNativeAbi(fd)" in native_channel_cpp and
                "UsesNativeAbi()" not in native_channel_cpp and
                "NativeGpuProcessRegistry::Instance().Contains(session->process)" in native_channel_cpp and
                "if (native && !native_plan)" in native_channel_cpp and
                "BuildIncrementCommandList(params.fence, native_completion)" in native_channel_cpp and
                "GetNativeGpuContextSlot(params.class_num)" in native_channel_cpp and
                "case 7:" in native_channel_cpp and
                "class NativeGpuProcessRegistry" in process_registry and
                "PlanNativeSubmission(" in fence_plan,
                "Native NS2 GPU channel must be process-scoped and release gated")
        ampere_root = ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere"
        isa_table = (ampere_root / "ampere_isa_table.h").read_text()
        isa_probe = (ampere_root / "probe.cpp").read_text()
        isa_header = (ampere_root / "probe.h").read_text()
        isa_classifier = (ampere_root / "classify.h").read_text()
        # A valid shader image must enter the same CFG byte-address
        # convention as the shipping Vulkan graphics compiler, but only
        # through the explicit NS2 research selector.
        ir_bridge = (ampere_root / "ir_bridge.cpp").read_text()
        maxwell_env = (ampere_root / "maxwell_environment.cpp").read_text()
        require('EDEN_NS2_MAXWELL_IR_BRIDGE' in CMAKE and
                '"${EDEN_NS2_MAXWELL_IR_BRIDGE}"' in CMAKE and
                'ir_bridge.h' in CMAKE and
                (ampere_root / "ir_bridge.h").is_file() and
                'Shader::Maxwell::Flow::CFG cfg{env, flow_pool, address, exits_to_dispatcher}' in ir_bridge and
                'Shader::Maxwell::TranslateProgram(inst_pool, block_pool, env, cfg, host_info)' in ir_bridge and
                'start_address = stage == Shader::Stage::Compute' in maxwell_env and
                '? image.first_instruction_address' in maxwell_env and
                ': image.first_instruction_address - sizeof(Shader::ProgramHeader)' in maxwell_env and
                'TranslateReviewedComputeIR(' in ir_bridge and
                'Shader::Maxwell::Flow::CFG cfg{env, flow_pool, env.StartAddress()}' in ir_bridge and
                'EDEN_NS2_AMPERE_PROBE_EXPERIMENTAL OR' in CMAKE[release_gate:],
                "Native Maxwell graphics IR bridge must remain explicit, offset-correct and release-gated")
        require('option(EDEN_NS2_AMPERE_PROBE_EXPERIMENTAL' in CMAKE and
                'target_sources(shader_recompiler PRIVATE' in CMAKE and
                '"${EDEN_NS2_MAXWELL_IMAGE_BRIDGE}"' in CMAKE and
                'EDEN_NS2_MAXWELL_IMAGE_BRIDGE' in CMAKE and
                'program_address_map.h' in CMAKE and
                'maxwell_image.h' in CMAKE and
                'EDEN_NS2_AMPERE_LOWER_BRIDGE' in CMAKE and
                'target_include_directories(shader_recompiler BEFORE PRIVATE "${EDEN_NS2_AMPERE_ROOT}")' in CMAKE and
                'EDEN_NS2_AMPERE_PROBE_EXPERIMENTAL OR' in CMAKE[release_gate:] and
                'ISA_ROW_COUNT = 629' in isa_table and
                'ProbeProgram(std::span<const u8> code)' in isa_probe and
                'FirstUnreviewedBit(' in isa_probe and
                'MaxInstructions = 65536' in isa_probe and
                'ProbeStatus::UnknownOpcode' in isa_probe and
                'Classify(op12).kind' in isa_probe and
                'enum class ProbeStatus' in isa_header and
                'enum class OpKind' in isa_classifier and
                (ROOT / "tools/ns2/test_ampere_isa_probe.cpp").is_file() and
                (ROOT / "tools/ns2/test_ampere_lower_bridge.cpp").is_file() and
                (ampere_root / "lower_to_maxwell.h").is_file() and
                (ampere_root / "register_pressure.h").is_file() and
                (ampere_root / "lower_bridge.h").is_file() and
                "LowerReviewedToMaxwell(\n    std::span<const u8> native_code" in
                    (ampere_root / "lower_bridge.cpp").read_text() and
                "ProbeProgram(native_code)" in
                    (ampere_root / "lower_bridge.cpp").read_text() and
                "LowerToMaxwell(input, {}, false, indirect_dispatch)" in
                    (ampere_root / "lower_bridge.cpp").read_text() and
                "BridgeMaxInstructions = 4096" in
                    (ampere_root / "lower_bridge.cpp").read_text() and
                "LowerBridgeStatus::UnsupportedSemantics" in
                    (ampere_root / "lower_bridge.cpp").read_text() and
                "BuildMaxwellShaderImage(" in (ampere_root / "maxwell_image.cpp").read_text() and
                "AppendNativeAddressMap(" in (ampere_root / "maxwell_image.cpp").read_text() and
                "NativeProgramAddress(code, address)" in (ampere_root / "maxwell_image.cpp").read_text() and
                "ImageSalt =" in (ampere_root / "maxwell_image.cpp").read_text() and
                "MaxwellSchedulingPeriod = 0x20" in (ampere_root / "maxwell_image.cpp").read_text() and
                "LowerReviewedToMaxwell(native_code, indirect_dispatch)" in (ampere_root / "maxwell_image.cpp").read_text() and
                "MaxwellImageStatus::InvalidLayout" in (ampere_root / "maxwell_image.cpp").read_text() and
                (ROOT / "tools/ns2/test_ampere_maxwell_image.cpp").is_file() and
                (ROOT / "tools/ns2/test_ampere_gpu_capture.cpp").is_file() and
                'EDEN_NS2_NATIVE_SHADER_CAPTURE' in CMAKE and
                'EDEN_NS2_NATIVE_GMMU_CAPTURE' in CMAKE and
                'target_sources(video_core PRIVATE "${EDEN_NS2_NATIVE_GMMU_CAPTURE}")' in CMAKE and
                'target_include_directories(video_core BEFORE PRIVATE "${EDEN_NS2_AMPERE_ROOT}")' in CMAKE and
                (ampere_root / "capture.h").is_file() and
                (ampere_root / "program_capture.h").is_file() and
                'ProgramCaptureState capture' in (ampere_root / "capture.cpp").read_text() and
                'BuildMaxwellShaderImage(' in (ampere_root / "capture.cpp").read_text() and
                'MaxCapturedInstructions = 4096' in (ampere_root / "capture.cpp").read_text() and
                'NativeCaptureStatus::NoTerminator' in (ampere_root / "capture.cpp").read_text() and
                'memory->IsFullyMappedRange(address, size)' in
                    (ROOT / "vendor/encore-active/ns2-runtime/ampere/video_core/native_shader_capture.cpp").read_text() and
                'memory->ReadBlock(address, dest, size)' in
                    (ROOT / "vendor/encore-active/ns2-runtime/ampere/video_core/native_shader_capture.cpp").read_text() and
                'EDEN_NS2_NATIVE_TRANSLATION_CACHE' in CMAKE and
                'EDEN_NS2_MAXWELL_ENVIRONMENT_ADAPTER' in CMAKE and
                'maxwell_environment.h' in CMAKE and
                (ampere_root / "maxwell_environment.h").is_file() and
                (ampere_root / "maxwell_environment.cpp").is_file() and
                'Shader::Environment' in
                    (ampere_root / "maxwell_environment.h").read_text() and
                'ReadInstruction(u32 address)' in
                    (ampere_root / "maxwell_environment.cpp").read_text() and
                'original.ReadCbufValue(index, offset)' in
                    (ampere_root / "maxwell_environment.cpp").read_text() and
                'image.ReadMaxwellInstruction(address)' in
                    (ampere_root / "maxwell_environment.cpp").read_text() and
                (ROOT / "tools/ns2/test_ampere_maxwell_environment.cpp").is_file() and
                'CreateNs2GraphicsShaderEnvironment(' in
                    (ROOT / "vendor/encore-active/ns2-runtime/ampere/video_core/native_shader_capture.cpp").read_text() and
                'CreateOwned(' in (ampere_root / "maxwell_environment.cpp").read_text() and
                'std::unique_ptr<Shader::Environment> owned;' in
                    (ampere_root / "maxwell_environment.h").read_text() and
                'NativeMaxwellEnvironment::CreateOwned(' in
                    (ROOT / "vendor/encore-active/ns2-runtime/ampere/video_core/native_shader_capture.cpp").read_text() and
                'std::unique_ptr<Shader::Environment> original' in
                    (ROOT / "vendor/encore-active/ns2-runtime/ampere/video_core/native_shader_capture.h").read_text() and
                'destroyed==1' in
                    (ROOT / "tools/ns2/test_ampere_maxwell_environment.cpp").read_text() and
                'translation_cache.cpp' in CMAKE and
                'translation_cache.h' in CMAKE and
                (ROOT / "tools/ns2/test_ampere_translation_cache.cpp").is_file() and
                'class NativeTranslationCache' in (ampere_root / "translation_cache.h").read_text() and
                'std::equal(e.native.begin(), e.native.end(), native.begin())' in
                    (ampere_root / "translation_cache.cpp").read_text() and
                'lru.splice(lru.begin(), lru, it)' in
                    (ampere_root / "translation_cache.cpp").read_text() and
                '!image.Ready()' in (ampere_root / "translation_cache.cpp").read_text() and
                'cache->GetOrTranslate(maxwell_header, source, stage)' in
                    (ampere_root / "capture.cpp").read_text() and
                'NativeTranslationCache* cache' in
                    (ROOT / "vendor/encore-active/ns2-runtime/ampere/video_core/native_shader_capture.cpp").read_text(),
                "Ampere shader ISA probe must remain bounded, opt-in and release gated")
        nvdrv_root = ROOT / "vendor/encore-active/ns2-runtime/nvdrv/core/hle/service/nvdrv/devices"
        ctrl = (nvdrv_root / "nvhost_ctrl_gpu.cpp").read_text()
        ioctl = (nvdrv_root / "native_characteristics_ioctl.h").read_text()
        require('WriteNativeCharacteristicsIoctlReply(' in ctrl and
                'return WrapFixedInlOut(this, &nvhost_ctrl_gpu::GetCharacteristics3' in ctrl and
                'native_characteristics_ioctl.h' in ctrl,
                "Research native response must preserve original ioctl fallback")
        require('raw != 0xc0e04705U && raw != 0xc0e84705U' in ioctl,
                "Native ioctl handler must match only exact native commands")
        am_root = ROOT / "vendor/encore-active/ns2-runtime/am/core/hle/service/am/service"
        am_impl = (am_root / "application_functions.cpp").read_text()
        am_header = (am_root / "application_functions.h").read_text()
        require("GetScreenShotAndContinuousRecordingInitiallyEnabled" in am_impl and
                "GetScreenShotAndContinuousRecordingInitiallyEnabled" in am_header,
                "AM 320 declaration/handler missing")
        require("last_reported_title.exchange(title_id" in am_impl,
                "Maintained Encore application metadata diagnostic behavior lost")
        require('foreach(eden_ncz_relative IN ITEMS' in CMAKE and
                '"file_sys/submission_package.cpp"' in CMAKE and
                '"file_sys/card_image.cpp"' in CMAKE and
                '"loader/nsp.cpp"' in CMAKE and
                '"file_sys/registered_cache.cpp"' in CMAKE and
                'list(APPEND core_sources "${EDEN_PORT_DIR}/ncz.cpp")' in CMAKE and
                'vendor/encore-active/eden-core/src/core/' in CMAKE and
                'list(APPEND core_sources "${eden_ncz_maintained}")' in CMAKE,
                "Existing PS5 NCZ/NSZ/XCZ source owners must be retained")
        require('eden_ns2_loader_origin' in CMAKE and
                'eden_ns2_romdir_origin' in CMAKE and
                'list(FIND eden_ns2_exefs_sources "${eden_ns2_original}"' in CMAKE,
                "No version-aware source ownership check")
        loader = (NS2 / "loader/loader.cpp").read_text(encoding="utf-8")
        romdir = (NS2 / "loader/deconstructed_rom_directory.cpp").read_text(encoding="utf-8")
        header = (ROOT / "vendor/encore-active/ns2-helpers/include/core/loader/deconstructed_rom_directory.h").read_text(encoding="utf-8")
        format_header = (ROOT / "vendor/encore-active/ns2-helpers/include/core/loader/ns2_content_formats.h").read_text(
            encoding="utf-8")
        format_tests = (ROOT / "tools/ns2/test_content_formats.cpp").read_text(
            encoding="utf-8")
        require('core/loader/ns2_content_formats.h' in loader and
                'Eden::NS2::Content::IdentifyName(name)' in loader and
                'Kind::XCZ' in loader and 'Kind::NSZ' in loader and
                'Kind::NPDMMetadata' in loader and
                'Kind::RomFSData' in loader and
                'return FileType::Unknown;' in loader and
                'constexpr Kind IdentifyName(' in format_header and
                'constexpr bool HasExistingLoaderRoute(' in format_header and
                'RequiresRecognizedContent(' in format_header and
                'MayFallbackByName(' in format_header and
                '!Eden::NS2::Content::MayFallbackByName(filename_kind)' in loader and
                'type == FileType::Unknown' in loader and
                'compressed alias must not enter loader through extension alone' in format_tests and
                'mkw.xci2' in format_tests and
                'game-card-key' in format_tests,
                "NS2 content route audit or unsupported-format guard lost")
        require('<< 14) & 0xffc000' in romdir,
                "16-KiB-aligned Encore ASLR offset lost")
        require('!metadata.UsesExtendedAcid()' in romdir,
                "Extended ACID Dynarmic path guard lost")
        require('bool standalone{true}' in header,
                "Standalone ExeFS state missing")
        require(loader.index('IdentifyFileLoader<AppLoader_DeconstructedRomDirectory>')
                < loader.index('IdentifyFileLoader<AppLoader_NSO>'),
                "ExeFS identification is after generic NSO")
        print("NS2 research source owner / ExeFS safety guards: PASS")
    except (AssertionError, ValueError, OSError) as exc:
        print(f"NS2 source selection check FAILED: {exc}", file=sys.stderr)
        return 1
    print("NOTE: static selection proof only; no complete PS5 CMake configure/compile")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
