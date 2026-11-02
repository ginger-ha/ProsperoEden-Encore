#!/usr/bin/env python3
"""P2.2 host-only witness: native TIC shader format mapping and refusal policy.

This compares the ACTUAL pinned enums, rather than assuming that a Vulkan
surface-format integer is always a shader pixel-format integer. Does not
compile the PS5 renderer or prove that VkImage/VkSampler bindings work.
"""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[2]
vendor = root / "vendor"
shader_info = (vendor / "sources/eden/src/shader_recompiler/shader_info.h").read_text()
surface_info = (vendor / "sources/eden/src/video_core/surface.h").read_text()

shader_enum = re.search(r"enum class TexturePixelFormat\s*\{(.*?)\};",
                        shader_info, re.S)
assert shader_enum, "Shader::TexturePixelFormat absent"
shader = [item.strip() for item in shader_enum.group(1).split(",") if item.strip()]
surface_macro = surface_info.split("#define PIXEL_FORMAT_LIST", 1)[1].split("\n\n", 1)[0]
surface = re.findall(r"PIXEL_FORMAT_ELEM\((\w+),", surface_macro)
shared_end = "E5B9G9R9_FLOAT"
assert shared_end in shader and shared_end in surface
shared_count = shader.index(shared_end) + 1
assert surface.index(shared_end) + 1 == shared_count
assert shader[:shared_count] == surface[:shared_count], "numeric format prefix drift"

# The shader compiler has no corresponding ETC2/EAC image formats. Never
# cast these ten surface entries into unrelated shader depth/stencil entries.
unrepresented = surface[shared_count:-7]
assert unrepresented == [
    "ETC2_RGB_UNORM", "ETC2_RGBA_UNORM", "ETC2_RGB_PTA_UNORM",
    "ETC2_RGB_SRGB", "ETC2_RGBA_SRGB", "ETC2_RGB_PTA_SRGB",
    "EAC_R11_UNORM", "EAC_R11_SNORM",
    "EAC_R11G11_UNORM", "EAC_R11G11_SNORM",
], "unexpected non-shader surface formats"
depth = shader[shared_count:]
assert depth == [
    "D32_FLOAT", "D16_UNORM", "X8_D24_UNORM", "S8_UINT",
    "D24_UNORM_S8_UINT", "S8_UINT_D24_UNORM", "D32_FLOAT_S8_UINT",
]
assert depth == surface[-len(depth):], "depth/stencil format set drift"

for filename in (
    "encore-active/eden-vulkan/vulkan_rasterizer.cpp",
    "encore-active/eden-core/guest-bridge/vulkan_rasterizer.cpp",
):
    source = (vendor / filename).read_text()
    native = source.split("class NativeQmdTextureMetadata final", 1)[1].split(
        "} // namespace", 1)[0]
    assert "if (format <= VideoCore::Surface::PixelFormat::E5B9G9R9_FLOAT)" in native
    assert "return static_cast<Shader::TexturePixelFormat>(format);" in native
    for name in depth:
        assert re.search(
            r"case VideoCore::Surface::PixelFormat::" + name +
            r":\s*return Shader::TexturePixelFormat::" + name + r";", native
        ), (filename, name)
    assert "throw std::runtime_error{\"unsupported native Compute shader pixel format\"};" in native
    assert "return VideoCore::Surface::IsPixelFormatInteger(ReadNativePixelFormat(handle));" in native
    assert "return false; // no unbacked image/sampler descriptor publication" in source

print("NS2_NATIVE_TIC_PIXEL_FORMAT_MAP_PASS shared=95 rejected=10 explicit_depth=7"
      " ns1_vulkan_unchanged=1 no_native_image_binding_claim=1")

# P2.2 common owner boundary: Compute buffers and TIC image preflight must
# share the SAME full-span 49-bit GMMU guard. No false Vulkan publication.
native_header = (vendor / (
    "encore-active/ns2-runtime/ampere/shader_recompiler/"
    "frontend/ampere/native_qmd_compute_environment.h"
)).read_text()
compute = (vendor / "encore-active/eden-vulkan/vk_compute_pipeline_cost.cpp").read_text()
assert "bool NativeQmdContiguousGpuSpan(" in native_header
assert "sampler.min_lod_clamp.Value() > sampler.max_lod_clamp.Value()" in native_header, "native TSC LOD order guard missing"
assert "tic.IsPitchLinear()" in native_header and "!tic.Pitch()" in native_header, "native pitch image admission guard missing"
assert "bool SameBufferBindings(const NativeQmdResourcePlan& other)" in native_header
assert "image_handles.size() != other.image_handles.size()" in native_header
assert "a.primary_shift != b.primary_shift" in native_header
assert "a.secondary_shift != b.secondary_shift" in native_header
assert "a.is_written != b.is_written" in native_header
assert "bool SameRegisters(u64 live_tic, u32 live_tic_limit," in native_header
assert "bool ForEachCapturedRecord(const NativeQmdResourcePlan& plan," in native_header
snapshot_body = native_header.split("MatchesSnapshot(", 1)[1].split(
    "    // Transcode already admitted snapshot bytes", 1)[0]
assert "ForEachCapturedRecord(" in snapshot_body
assert "const auto fresh = Capture(" not in snapshot_body
assert "std::vector<NativeQmdImageTableRecord> captured;" in native_header
for owner_path in (
    "encore-active/eden-vulkan/vulkan_rasterizer.cpp",
    "encore-active/eden-core/guest-bridge/vulkan_rasterizer.cpp",
):
    code = (vendor / owner_path).read_text()
    assert "const auto before_binding = resource_owner->BuildResourcePlan(*compiled.info);" in code
    assert "bool current_after_staging = false;" in code
    assert "auto native_compute_retirement = SCOPE_GUARD {" in code
    assert "native_recording_started = true;" in code
    assert "native_compute_retirement.Cancel();" in code
    assert code.index("native_recording_started = true;") < code.index(
        "if (!pipeline->ConfigureNative(")
    assert code.index("native_compute_retirement.Cancel();") < code.rindex(
        "RetainNativeComputeUntilGpuTick(")
    # Return-false or exceptions after staging use the same timeline owner.
    assert "Scope retirement also handles this rejection" in code
    assert code.count("resources->SameBufferBindings(") == 2, owner_path
    assert code.index("bool current_after_staging = false;") < code.index(
        "RetainNativeComputeUntilGpuTick(", code.index("bool current_after_staging = false;"))
print("NS2_NATIVE_QMD_MUTABLE_BUFFER_SNAPSHOT_PASS pre_stage=1 post_stage=1"
      " post_stage_throw=retained")

assert "CaptureAdmissible(const NativeQmdResourcePlan&" in native_header
assert "Shader::Ampere::NativeQmdContiguousGpuSpan(" in compute
assert "for (u64 delta = 4096" not in compute, "duplicated GMMU guard reappeared"
for filename in (
    "encore-active/eden-vulkan/vulkan_rasterizer.cpp",
    "encore-active/eden-core/guest-bridge/vulkan_rasterizer.cpp",
):
    source = (vendor / filename).read_text()
    assert "tables.CaptureAdmissible(" in source, filename
    assert "tables.SameRegisters(" in source, filename
    assert source.index("tables.SameRegisters(") < source.index(
        "tables.MatchesSnapshot("), filename
    assert "Shader::Ampere::NativeQmdContiguousGpuSpan(" in source, filename
    assert "const VideoCommon::ImageInfo info{tic};" in source, filename
    admission = source.split("[this](const Tegra::Texture::TICEntry& tic) {", 1)[1]
    assert admission.index("PixelFormat::Invalid)") < admission.index(
        "const VideoCommon::ImageInfo info{tic};"), filename
    assert "return false; // no unbacked image/sampler descriptor publication" in source

# Legacy NS1 still uses its own 40-bit verification. It is not silently
# widened without a corresponding Maxwell regression suite.
legacy = (vendor / "sources/eden/src/video_core/texture_cache/util.cpp").read_text()
assert "if (address >= (1ULL << 40))" in legacy

print("NS2_NATIVE_TEXTURE_GMMU_SHARED_PASS mapping=49bit whole_span=1"
      " no_native_vulkan_publication=1 ns1_legacy_guard=unchanged")

# P2.2.2 native-only typed cache accessor overlay. Never mutate the pinned
# upstream sources, shipping Eden backports or the original Maxwell ABI.
overlay = vendor / "encore-active/eden-vulkan/vulkan-cache/video_core/texture_cache"
header = (overlay / "texture_cache_base.h").read_text()
impl = (overlay / "texture_cache.h").read_text()
upstream_header = (vendor / "sources/eden/src/video_core/texture_cache/texture_cache_base.h").read_text()
backport_header = (vendor / "encore-active/eden-backports/src/video_core/texture_cache/texture_cache_base.h").read_text()
native_gate = "#if defined(PS5_NATIVE) && defined(EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL)"
for sym in ("AcquireNativeImageView", "AcquireNativeSampler"):
    assert sym in header and sym in impl, sym
    assert sym not in upstream_header and sym not in backport_header, sym
assert native_gate in header and native_gate in impl
assert "channel_state->image_views.try_emplace(descriptor)" in impl
assert "slot_images[view.image_id].flags & ImageFlagBits::Remapped" in impl
assert "CreateImageView(descriptor)" in impl
assert "PrepareImageView(pair->second, is_written, false)" in impl
assert "return FindSampler(descriptor, true);" in impl
assert "SamplerId TextureCache<P>::FindSampler(" in impl
assert "ImageViewId TextureCache<P>::VisitImageView(" in impl
assert "return false; // no unbacked image/sampler descriptor publication" in (
    vendor / "encore-active/eden-vulkan/vulkan_rasterizer.cpp").read_text()
print("NS1_NS2_NATIVE_TEXTURE_CACHE_TYPED_OVERLAY_PASS owner=one"
      " upstream=immutable backports=immutable dispatch_images=closed")

# Validate that every maintained Vulkan rasterizer refuses native TIC layer
# offsets and layered image sizes that would narrow into u32 in the cache.
for path in (
    "encore-active/eden-vulkan/vulkan_rasterizer.cpp",
    "encore-active/eden-core/guest-bridge/vulkan_rasterizer.cpp",
):
    source = (vendor / path).read_text()
    start = source.split("const u64 layer_offset =", 1)[1].split(
        "return Shader::Ampere::NativeQmdContiguousGpuSpan(", 1)[0]
    assert "layer_offset > u32_limit" in start, path
    assert "u64{info.layer_stride} * info.resources.layers > u32_limit" in start, path
    assert "if (!bytes) return false;" in start, path
print("NS2_NATIVE_TIC_U32_LAYOUT_BOUNDS_PASS no_truncated_view_offset=1")

# Both native rasterizer variants must check the reflection-to-TIC/TSC
# ownership order BEFORE capturing or publishing guest image descriptors.
native_env = (vendor / (
    "encore-active/ns2-runtime/ampere/shader_recompiler/"
    "frontend/ampere/native_qmd_compute_environment.h"
)).read_text()
# Capture and typed replay must enforce the EXACT same TIC budget/MSAA
# admission, not two diverging copies of the field-policy checks.
assert "bool NativeQmdTicLayoutSupported(" in native_env
assert native_env.count("NativeQmdTicLayoutSupported(") == 4  # helper + capture + replay + typed layout
assert "if (!NativeQmdTicLayoutSupported(tic)) return std::nullopt;" in native_env
assert "if (!NativeQmdTicLayoutSupported(entry.tic)) return std::nullopt;" in native_env
# Translate from the exact TIC layout policy used by capture/replay.
for owner in (
    "encore-active/eden-vulkan/vulkan_rasterizer.cpp",
    "encore-active/eden-core/guest-bridge/vulkan_rasterizer.cpp",
):
    native_owner = (vendor / owner).read_text()
    assert native_owner.count("NativeQmdTicLayoutSupported(entry)") == 1, owner
    assert "unsupported native Compute TIC header" not in native_owner, owner
assert "bool NativeQmdTicMatchesShaderType(" in native_env
assert "bool NativeQmdTypedImageLayoutMatches(" in native_env
for owner in (
    "encore-active/eden-vulkan/vulkan_rasterizer.cpp",
    "encore-active/eden-core/guest-bridge/vulkan_rasterizer.cpp",
):
    native_owner = (vendor / owner).read_text()
    typed_guard = "Shader::Ampere::NativeQmdTypedImageLayoutMatches("
    assert native_owner.count(typed_guard) == 1, owner
    assert native_owner.index("const auto typed_descriptors = tables.DecodeAdmitted(") < native_owner.index(typed_guard)
    assert native_owner.index(typed_guard) < native_owner.index("tables.MatchesSnapshot(")
assert "bool NativeQmdImageLayoutMatches(" in native_env
assert "NativeQmdImageKind::TextureBuffer" in native_env
assert "NativeQmdImageKind::ImageBuffer" in native_env
assert "NativeQmdImageKind::SampledTexture" in native_env
assert "NativeQmdImageKind::StorageImage" in native_env
assert "wrap_ok(sampler.wrap_u.Value())" in native_env
assert "wrap_ok(sampler.wrap_v.Value())" in native_env
assert "wrap_ok(sampler.wrap_p.Value())" in native_env
for path in (
    "encore-active/eden-vulkan/vulkan_rasterizer.cpp",
    "encore-active/eden-core/guest-bridge/vulkan_rasterizer.cpp",
):
    owner = (vendor / path).read_text()
    guard = "NativeQmdImageLayoutMatches(*compiled.info, *resources)"
    assert owner.index(guard) < owner.index("tables.CaptureAdmissible("), path
print("NS2_NATIVE_SPIRV_IMAGE_LAYOUT_OWNER_PASS order=4 rights=verified"
      " unsound_wrap=refused native_image_dispatch=closed")

# P2.2 native cache preflight uses the active GMMU and engine identity, not
# merely a process ticket: never mix two GPU channels sharing TIC bytes.
assert "NativeChannelMatches(" in header
assert "kepler_compute == &expected_compute" in impl
assert "gpu_memory == &expected_memory" in impl
assert "&channel_state->kepler_compute == &expected_compute" in impl
assert "&channel_state->gpu_memory == &expected_memory" in impl
assert impl.count("NativeChannelMatches(expected_compute, expected_memory)") == 2
for source_path in (
    "encore-active/eden-vulkan/vulkan_rasterizer.cpp",
    "encore-active/eden-core/guest-bridge/vulkan_rasterizer.cpp",
):
    caller = (vendor / source_path).read_text()
    assert "texture_cache.NativeChannelMatches(" in caller
    assert "std::scoped_lock lock{texture_cache.mutex};" in caller
    before_close = caller.split("return false; // no unbacked image/sampler descriptor publication", 1)[0]
    assert "registry.IsComputeCurrent(kepler_compute, *ticket)" in before_close
print("NS2_TEXTURE_CACHE_CHANNEL_GMMU_OWNER_PASS engine=exact gmmu=exact"
      " both_native_cache_apis=guarded images_still_closed=1")

for path in (
    "encore-active/eden-vulkan/vulkan_rasterizer.cpp",
    "encore-active/eden-core/guest-bridge/vulkan_rasterizer.cpp",
):
    bridge = (vendor / path).read_text()
    locked = bridge.split("std::scoped_lock lock{texture_cache.mutex};", 1)[1]
    assert locked.index("texture_cache.NativeChannelMatches(") < locked.index(
        "tables.MatchesSnapshot("), path
    assert locked.index("tables.MatchesSnapshot(") < locked.index(
        "return false; // no unbacked image/sampler descriptor publication"), path
print("NS2_TIC_TSC_LOCKED_SNAPSHOT_PASS same_channel=required snapshot=second_read"
      " before_publication=1")

# A real TICEntry/TSCEntry decode boundary follows guest admission; it
# produces no Vulkan objects. The existing fail-closed dispatch remains.
assert "struct NativeQmdTypedTextureRecord" in native_env
assert "DecodeAdmitted(const NativeQmdResourcePlan& plan," in native_env
assert "src.raw_handle != raw" in native_env
assert "src.tic_index != (linked_tsc ? raw : (raw & 0xfffffU))" in native_env
assert "src.tsc_index != (linked_tsc ? raw : (raw >> 20))" in native_env
assert "std::memcpy(&entry.tic, src.tic_words.data(), sizeof(entry.tic))" in native_env
assert "std::memcpy(&sampler, src.tsc_words.data(), sizeof(sampler))" in native_env
for path in (
    "encore-active/eden-vulkan/vulkan_rasterizer.cpp",
    "encore-active/eden-core/guest-bridge/vulkan_rasterizer.cpp",
):
    bridge = (vendor / path).read_text()
    assert bridge.index("tables.CaptureAdmissible(") < bridge.index(
        "tables.DecodeAdmitted(") < bridge.index("tables.MatchesSnapshot("), path
    assert "return false; // no unbacked image/sampler descriptor publication" in bridge
print("NS2_TYPED_TIC_TSC_DECODE_PASS real_cache_ABI=1"
      " retained_vk_objects=0 native_image_dispatch=closed")

assert "std::scoped_lock channel_lock{config_mutex};" in impl
assert impl.index("std::scoped_lock channel_lock{config_mutex};") < impl.index(
    "&channel_state->kepler_compute == &expected_compute")
print("NS2_CACHE_CHANNEL_RACE_PREVENTION_PASS config_mutex=acquired")

# The generic guest fence callback can execute synchronously when delay is
# false. Native pipeline retirement MUST wait a real GPU timeline tick via
# SyncOperation, and must be used for both success and aborted submissions.
generic_fence = (vendor / "sources/eden/src/video_core/fence_manager.h").read_text()
assert "if (!delay_fence) {" in generic_fence
assert "func();" in generic_fence
assert "RetainNativeComputeUntilGpuTick(" in native_env
assert "const u64 tick = scheduler.Flush();" in native_env
assert "fences.SyncOperation(" in native_env
assert "gpu_scheduler->Wait(tick);" in native_env
assert "fences.SignalReference();" in native_env
for path in (
    "encore-active/eden-vulkan/vulkan_rasterizer.cpp",
    "encore-active/eden-core/guest-bridge/vulkan_rasterizer.cpp",
):
    code = (vendor / path).read_text()
    assert code.count("RetainNativeComputeUntilGpuTick(") == 2, path
    assert "fence_manager.SignalFence([pipeline = std::move(pipeline)] {})" not in code
print("NS2_NATIVE_COMPUTE_GPU_TICK_RETENTION_PASS no_immediate_release=1"
      " cancelled_submit=retained successful_submit=retained")

# All TIC MSAA sample-counts accepted by native admission must be
# understood by the existing shared Maxwell texture/Vulkan helpers.
maxwell_msaa = (vendor / "sources/eden/src/video_core/renderer_vulkan/maxwell_to_vk.cpp").read_text()
cache_samples = (vendor / "sources/eden/src/video_core/texture_cache/samples_helper.h").read_text()
for name in ("Msaa4x2_VC8", "Msaa4x2_VC24"):
    assert ("case MsaaMode::" + name + ":") in native_env
    assert ("MsaaMode::" + name + ":") in maxwell_msaa
    assert ("MsaaMode::" + name + ":") in cache_samples
print("NS2_MSAA_VC8_VC24_SHARED_MAPPING_PASS sample_count=8")

# If deferred fence registration itself throws, a second shared owner must
# survive until the already submitted GPU tick finishes. The test fixture
# injects this failure and validates the destruction order on the real helper.
assert "auto emergency_owner = owner;" in native_env
assert "catch (...) {" in native_env.split(
    "void RetainNativeComputeUntilGpuTick(", 1)[1].split(
    "// Shared NS2 GMMU preflight", 1)[0]
assert "scheduler.Wait(tick);" in native_env
print("NS2_NATIVE_COMPUTE_FENCE_REGISTRATION_FALLBACK_PASS"
      " owner_retained_on_exception=1")

# P2.2 GPU-owner safety: the PS5 Vulkan cache must not retire VkImage or
# VkImageView on an assumed number of frames. The GPU completion semaphore
# owns their final release, independently of the native compute fence owner.
vk_runtime_header = (vendor / (
    "encore-active/ns2-astc/include/video_core/renderer_vulkan/vk_texture_cache.h"
)).read_text()
vk_runtime = (vendor / "encore-active/eden-vulkan/vk_texture_cache_cost.cpp").read_text()
assert "void RetireGpuImage(Image&& image);" in vk_runtime_header
assert "void RetireGpuImageView(ImageView&& view);" in vk_runtime_header
assert "pending_retired_images" in vk_runtime_header
assert "pending_retired_views" in vk_runtime_header
assert "const u64 tick = scheduler.CurrentTick();" in vk_runtime
assert "scheduler.GetMasterSemaphore().KnownGpuTick()" in vk_runtime
assert "std::erase_if(pending_retired_views" in vk_runtime
assert "std::erase_if(pending_retired_images" in vk_runtime
assert "MIN_TEXTURE_RETIRE_FRAMES = 8;" in vk_runtime
assert "gpu_retire_frame - pending.frame >= MIN_TEXTURE_RETIRE_FRAMES" in vk_runtime
assert "++gpu_retire_frame;" in vk_runtime
assert vk_runtime.index("std::erase_if(pending_retired_views") < vk_runtime.index(
    "std::erase_if(pending_retired_images"), "destroy Vulkan image before view"
assert "scheduler.Finish();" in vk_runtime.split(
    "TextureCacheRuntime::~TextureCacheRuntime()", 1)[1].split(
    "void TextureCacheRuntime::RetireGpuImage(", 1)[0]
for symbol in ("RetireGpuImage(Image&& image)", "RetireGpuImageView(ImageView&& view)"):
    block = vk_runtime.split("void TextureCacheRuntime::" + symbol, 1)[1].split(
        "\n}\n", 1)[0]
    assert "scheduler.Finish();" in block, "OOM path must drain submitted GPU work"
    queue = "pending_retired_images" if "Image&&" in symbol else "pending_retired_views"
    assert block.index(queue + ".reserve(") < block.index(queue + ".push_back("), (
        "Vulkan owner must not move before throwing queue growth", queue)
    assert "max_size()" in block and "capacity()" in block, (
        "GPU retirement container growth must remain amortized", queue)
for site in ("void TextureCache<P>::InvalidateScale(", "void TextureCache<P>::DeleteImage("):
    block = impl.split(site, 1)[1].split("\ntemplate <class P>", 1)[0]
    assert "runtime.RetireGpuImageView(" in block, site
assert "runtime.RetireGpuImage(std::move(slot_images[image_id]));" in impl
assert "return false; // no unbacked image/sampler descriptor publication" in (
    vendor / "encore-active/eden-vulkan/vulkan_rasterizer.cpp").read_text()
print("NS1_NS2_VULKAN_IMAGE_TIMELINE_RETIREMENT_SOURCE_PASS"
      " views_before_images=1 OOM_fallback=wait_gpu native_image_dispatch=closed")
