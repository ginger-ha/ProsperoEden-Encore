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
    assert source.index("PixelFormat::Invalid)") < source.index(
        "const VideoCommon::ImageInfo info{tic};"), filename
    assert "return false; // no unbacked image/sampler descriptor publication" in source

# Legacy NS1 still uses its own 40-bit verification. It is not silently
# widened without a corresponding Maxwell regression suite.
legacy = (vendor / "sources/eden/src/video_core/texture_cache/util.cpp").read_text()
assert "if (address >= (1ULL << 40))" in legacy

print("NS2_NATIVE_TEXTURE_GMMU_SHARED_PASS mapping=49bit whole_span=1"
      " no_native_vulkan_publication=1 ns1_legacy_guard=unchanged")
