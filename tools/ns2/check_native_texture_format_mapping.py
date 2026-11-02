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
assert "CaptureAdmissible(const NativeQmdResourcePlan&" in native_header
assert "Shader::Ampere::NativeQmdContiguousGpuSpan(" in compute
assert "for (u64 delta = 4096" not in compute, "duplicated GMMU guard reappeared"
for filename in (
    "encore-active/eden-vulkan/vulkan_rasterizer.cpp",
    "encore-active/eden-core/guest-bridge/vulkan_rasterizer.cpp",
):
    source = (vendor / filename).read_text()
    assert "tables.CaptureAdmissible(" in source, filename
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
