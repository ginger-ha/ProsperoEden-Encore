#!/usr/bin/env python3
"""Strict N57 vendor Vulkan parity: reconstruct the precise original F07 owners.

The N57 additions exist only in versioned vendor C++ plus the one small
ASTC assemble include. No executable code generator or replacement TU is used.
"""
from pathlib import Path
import subprocess

OWNER = Path("vendor/encore-active/eden-vulkan")
ASTC = Path("vendor/encore-active/ns2-astc/include/video_core/renderer_vulkan")
BASELINE = {
    "vk_texture_cache_cost.cpp": ("b2b08b577c3a3f9a4aeda10beb208a1b6d0a07e6",
                                  "3e8c9b250fc97d2d8366cacee3d1b089d3945149"),
    "vk_compute_pass_cost.cpp": ("f6de3b8406e0c312a84b677f6a1c4637ec0cc0f2",
                                 "596f86f2d27c1190f5d57ce6a591e32d419c7f08"),
}
AUXILIARY = {
    "vk_texture_cache.h": "80d2f99e44b13b79d1485cdc8c56e96b457a748d",
    "vk_compute_pass.h": "38e94f9e6c40853829172e2feded3b4d68b9089d",
    "ns2_astc_assemble_layers.inc": "528dd4f4ba78a40a894d9f7c86ad125878201156",
}

def git_blob(data: bytes) -> str:
    import hashlib
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

def once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, ("N57 vendor source drift", old[:90])
    return text.replace(old, new)


# P2.2 exact additions are removed only for the frozen N57/N73 SHA witness.
# Every byte of these additions is matched before stripping, and runtime
# ownership semantics are separately verified by the P2.2 host guard.
# P2.2b: reverse ONLY exact native cache-pin additions for N57's frozen
# historical SHA. The PS5 runtime still uses the pinned Vulkan owners.
def strip_p22_native_gpu_pins(text: str) -> str:
    text = once(text, "\n    Image(Image&&) = default;\n    Image& operator=(Image&&) = default;\n#if defined(PS5_NATIVE) && defined(EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL)\n    // A reference is held by the REAL GPU descriptor owner until its fence.\n    // The runtime's retirement queue cannot destroy this Vulkan resource\n    // while a native QMD dispatch still pins it.\n    [[nodiscard]] std::shared_ptr<u8> PinNativeGpu() {\n        if (!native_gpu_pin) native_gpu_pin = std::make_shared<u8>(0);\n        return native_gpu_pin;\n    }\n    [[nodiscard]] bool CanRetireNativeGpu() const noexcept {\n        return !native_gpu_pin || native_gpu_pin.use_count() == 1;\n    }\n#endif\n\n\n    void UploadMemory(VkBuffer buffer, VkDeviceSize offset,\n                      std::span<const VideoCommon::BufferImageCopy> copies);\n",
                "\n    Image(Image&&) = default;\n    Image& operator=(Image&&) = default;\n\n    void UploadMemory(VkBuffer buffer, VkDeviceSize offset,\n                      std::span<const VideoCommon::BufferImageCopy> copies);\n")
    text = once(text, "\n    bool NeedsScaleHelper() const;\n\n#if defined(PS5_NATIVE) && defined(EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL)\n    std::shared_ptr<u8> native_gpu_pin;\n#endif\n    Scheduler* scheduler{};\n    TextureCacheRuntime* runtime{};\n\n",
                "\n    bool NeedsScaleHelper() const;\n\n    Scheduler* scheduler{};\n    TextureCacheRuntime* runtime{};\n\n")
    text = once(text, "\n    ImageView(ImageView&&) = default;\n    ImageView& operator=(ImageView&&) = default;\n#if defined(PS5_NATIVE) && defined(EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL)\n    // A reference is held by the REAL GPU descriptor owner until its fence.\n    // The runtime's retirement queue cannot destroy this Vulkan resource\n    // while a native QMD dispatch still pins it.\n    [[nodiscard]] std::shared_ptr<u8> PinNativeGpu() {\n        if (!native_gpu_pin) native_gpu_pin = std::make_shared<u8>(0);\n        return native_gpu_pin;\n    }\n    [[nodiscard]] bool CanRetireNativeGpu() const noexcept {\n        return !native_gpu_pin || native_gpu_pin.use_count() == 1;\n    }\n#endif\n\n\n    [[nodiscard]] VkImageView DepthView();\n\n",
                "\n    ImageView(ImageView&&) = default;\n    ImageView& operator=(ImageView&&) = default;\n\n    [[nodiscard]] VkImageView DepthView();\n\n")
    text = once(text, "    [[nodiscard]] vk::ImageView MakeView(VkFormat vk_format, VkImageAspectFlags aspect_mask,\n                                         std::optional<Shader::TextureType> texture_type = std::nullopt);\n\n#if defined(PS5_NATIVE) && defined(EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL)\n    std::shared_ptr<u8> native_gpu_pin;\n#endif\n    const Device* device = nullptr;\n    const SlotVector<Image>* slot_images = nullptr;\n\n",
                "    [[nodiscard]] vk::ImageView MakeView(VkFormat vk_format, VkImageAspectFlags aspect_mask,\n                                         std::optional<Shader::TextureType> texture_type = std::nullopt);\n\n    const Device* device = nullptr;\n    const SlotVector<Image>* slot_images = nullptr;\n\n")
    text = once(text, "public:\n    explicit Sampler(TextureCacheRuntime&, const Tegra::Texture::TSCEntry&);\n\n\n#if defined(PS5_NATIVE) && defined(EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL)\n    // A reference is held by the REAL GPU descriptor owner until its fence.\n    // The runtime's retirement queue cannot destroy this Vulkan resource\n    // while a native QMD dispatch still pins it.\n    [[nodiscard]] std::shared_ptr<u8> PinNativeGpu() {\n        if (!native_gpu_pin) native_gpu_pin = std::make_shared<u8>(0);\n        return native_gpu_pin;\n    }\n    [[nodiscard]] bool CanRetireNativeGpu() const noexcept {\n        return !native_gpu_pin || native_gpu_pin.use_count() == 1;\n    }\n#endif\n\n    [[nodiscard]] VkSampler Handle() const noexcept {\n        return *variants.front().sampler;\n    }\n",
                "public:\n    explicit Sampler(TextureCacheRuntime&, const Tegra::Texture::TSCEntry&);\n\n    [[nodiscard]] VkSampler Handle() const noexcept {\n        return *variants.front().sampler;\n    }\n")
    text = once(text, "    [[nodiscard]] VkSampler Find(const VariantKey& key) const noexcept;\n    VkSampler Emplace(VariantKey key);\n\n#if defined(PS5_NATIVE) && defined(EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL)\n    std::shared_ptr<u8> native_gpu_pin;\n#endif\n    CustomBorderColorBudget custom_border_color_budget;\n    std::vector<Variant> variants;\n\n",
                "    [[nodiscard]] VkSampler Find(const VariantKey& key) const noexcept;\n    VkSampler Emplace(VariantKey key);\n\n    CustomBorderColorBudget custom_border_color_budget;\n    std::vector<Variant> variants;\n\n")
    return text

def strip_p22_runtime_header(text: str) -> str:
    text = once(text, "#include <span>\n#ifdef PS5_NATIVE\n#include <memory>\n#include <vector>\n#endif\n", "#include <span>\n")
    text = once(text, "    void Finish();\n#ifdef PS5_NATIVE\n    ~TextureCacheRuntime();\n    // Retire shared Vulkan cache ownership only after actual GPU completion.\n    // Image views must retire before their backing images.\n    void RetireGpuImage(Image&& image);\n    void RetireGpuImageView(ImageView&& view);\n#endif\n", "    void Finish();\n")
    text = once(text, "    std::vector<std::pair<u64, ResolveShadow>> pending_resolve_shadows;\n#ifdef PS5_NATIVE\n    template <typename T>\n    struct GpuRetireEntry {\n        u64 tick;\n        u64 frame;\n        std::unique_ptr<T> resource;\n    };\n    // Preserve the old eight-frame framebuffer/view ordering in addition\n    // to waiting for the actual GPU timeline; neither condition alone suffices.\n    u64 gpu_retire_frame{};\n    std::vector<GpuRetireEntry<ImageView>> pending_retired_views;\n    std::vector<GpuRetireEntry<Image>> pending_retired_images;\n#endif\n", "    std::vector<std::pair<u64, ResolveShadow>> pending_resolve_shadows;\n")
    return text

def strip_p22_runtime_cpp(text: str) -> str:
    # N57's historical source predates both P2.2's timeline retirement and
    # P2.2b's additional native descriptor pin. Revert the small pin guard
    # first, then strip the already-audited P2.2 retirement block below.
    text = once(text, "    const auto ready = [this, is_free](const auto& pending) {\n        const bool gpu_completed = is_free(pending.tick) &&\n            gpu_retire_frame - pending.frame >= MIN_TEXTURE_RETIRE_FRAMES;\n#if defined(EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL)\n        // A guest remap/eviction can race a freshly acquired native image\n        // before that dispatch flushes its timeline. Do not destroy the REAL\n        // VkImage or VkImageView until its final fence-held pin is released.\n        return gpu_completed && pending.resource->CanRetireNativeGpu();\n#else\n        return gpu_completed;\n#endif\n    };",
                "    const auto ready = [this, is_free](const auto& pending) {\n        return is_free(pending.tick) &&\n               gpu_retire_frame - pending.frame >= MIN_TEXTURE_RETIRE_FRAMES;\n    };")
    text = once(text, "\n#ifdef PS5_NATIVE\nTextureCacheRuntime::~TextureCacheRuntime() {\n    // Never destroy Vulkan image/view owners with outstanding GPU commands.\n    // Teardown is the only blocking case; frame reclamation remains async.\n    if (!pending_retired_views.empty() || !pending_retired_images.empty()) {\n        scheduler.Finish();\n        pending_retired_views.clear();\n        pending_retired_images.clear();\n    }\n}\n\nvoid TextureCacheRuntime::RetireGpuImage(Image&& image) {\n    const u64 tick = scheduler.CurrentTick();\n    try {\n        // Reserve BEFORE moving the Vulkan owner: a failed vector growth\n        // must never destroy the temporary image before the GPU drain below.\n        // Geometric growth avoids O(n^2) reallocations under texture churn.\n        if (pending_retired_images.size() == pending_retired_images.capacity()) {\n            const auto capacity = pending_retired_images.capacity();\n            const auto max_size = pending_retired_images.max_size();\n            if (capacity == max_size) throw std::bad_alloc{};\n            pending_retired_images.reserve(\n                capacity + std::min(std::max<std::size_t>(capacity, 8), max_size - capacity));\n        }\n        pending_retired_images.push_back({tick, gpu_retire_frame, std::make_unique<Image>(std::move(image))});\n    } catch (...) {\n        // If queue allocation fails, wait before any moved owner can die.\n        scheduler.Finish();\n        throw;\n    }\n}\n\nvoid TextureCacheRuntime::RetireGpuImageView(ImageView&& view) {\n    const u64 tick = scheduler.CurrentTick();\n    try {\n        // Retain the original view until all throwing container allocation\n        // has completed, then move it into a preallocated retirement slot.\n        // Geometric growth avoids O(n^2) reallocations under texture churn.\n        if (pending_retired_views.size() == pending_retired_views.capacity()) {\n            const auto capacity = pending_retired_views.capacity();\n            const auto max_size = pending_retired_views.max_size();\n            if (capacity == max_size) throw std::bad_alloc{};\n            pending_retired_views.reserve(\n                capacity + std::min(std::max<std::size_t>(capacity, 8), max_size - capacity));\n        }\n        pending_retired_views.push_back({tick, gpu_retire_frame, std::make_unique<ImageView>(std::move(view))});\n    } catch (...) {\n        scheduler.Finish();\n        throw;\n    }\n}\n#endif\n\n", "\n")
    text = once(text, "void TextureCacheRuntime::TickFrame() {\n    static constexpr u32 MAX_UNUSED_SCRATCH_FRAMES = 60;\n#ifdef PS5_NATIVE\n    ++gpu_retire_frame;\n#endif", "void TextureCacheRuntime::TickFrame() {\n    static constexpr u32 MAX_UNUSED_SCRATCH_FRAMES = 60;")
    text = once(text, "if (msaa_scratch_images.empty() && pending_resolve_shadows.empty() &&\n        pending_retired_views.empty() && pending_retired_images.empty()) {", "if (msaa_scratch_images.empty() && pending_resolve_shadows.empty()) {")
    text = once(text, "if (pending_resolve_shadows.empty() && pending_retired_views.empty() &&\n        pending_retired_images.empty() &&\n        std::all_of(msaa_scratch_images.begin(), msaa_scratch_images.end(),", "if (pending_resolve_shadows.empty() &&\n        std::all_of(msaa_scratch_images.begin(), msaa_scratch_images.end(),")
    text = once(text, "\n#ifdef PS5_NATIVE\n    // Erase image views before images: both own real Vulkan resources.\n    // Frame age alone never proves completion of an outstanding GPU tick.\n    // Keep the prior eight-frame framebuffer retirement ordering: the\n    // sentenced framebuffer ring is ticked immediately before this runtime.\n    static constexpr u64 MIN_TEXTURE_RETIRE_FRAMES = 8;\n    const auto ready = [this, is_free](const auto& pending) {\n        return is_free(pending.tick) &&\n               gpu_retire_frame - pending.frame >= MIN_TEXTURE_RETIRE_FRAMES;\n    };\n    std::erase_if(pending_retired_views, ready);\n    std::erase_if(pending_retired_images, ready);\n#endif", "")
    return text

def normalized(root: Path) -> dict[str, str]:
    for name, expected in AUXILIARY.items():
        path = root / ASTC / name
        if name == "vk_texture_cache.h":
            n73 = path.read_text()
            n73 = strip_p22_native_gpu_pins(n73)
            n73 = strip_p22_runtime_header(n73)
            before = "    void Finish();\n"
            extension = (
                "#ifdef EDEN_NS2_SPARSE_CACHE_PROBE\n"
                "    // N73: native cache-side Vulkan sparse admission/bind/retire probe.\n"
                "    // Never replaces the dense guest texture or samples an unbound image.\n"
                "    [[nodiscard]] bool ProbeSparseImage(const VideoCommon::ImageInfo& info);\n"
                "#endif\n"
            )
            assert n73.count(before + extension) == 1, "N73 ASTC header drift"
            stripped = n73.replace(before + extension, before)
            assert stripped.count(before + "\n\n") == 1, "N73 header whitespace drift"
            stripped = stripped.replace(before + "\n\n", before + "\n", 1)
            assert git_blob(stripped.encode()) == expected, ("N73 auxiliary drift", name)
            continue
        assert git_blob(path.read_bytes()) == expected, ("N57 auxiliary source drift", name)

    extra = (root / ASTC / "ns2_astc_assemble_layers.inc").read_text()
    for signature in ("void ASTCDecoderPass::AssembleLayers(", "PreflightAstcLayerDecode(",
                      "image.StorageImageLayerView(", "cmdbuf.Dispatch(dx, dy, 1)",
                      "scheduler.Flush();"):
        assert signature in extra, ("N57 layer decode contract", signature)
    assert "image.host_level_offset" not in extra

    result = {}
    for name, (current_sha, previous_sha) in BASELINE.items():
        text = (root / OWNER / name).read_text()
        if name == "vk_texture_cache_cost.cpp":
            text = strip_p22_runtime_cpp(text)
        if name == "vk_texture_cache_cost.cpp":
            # N73 is an additive native runtime probe. Strip its exact source
            # changes before applying N57's original hardcoded SHA oracle.
            n73_include = (
                "#include \"video_core/renderer_vulkan/vk_texture_cache.h\"\n"
                "#ifdef EDEN_NS2_SPARSE_CACHE_PROBE\n"
                "#include <atomic>\n"
                "#include \"video_core/renderer_vulkan/ns2_sparse_cache_admission.h\"\n"
                "#include \"video_core/renderer_vulkan/ns2_sparse_bind_transaction.h\"\n"
                "#endif"
            )
            assert text.count(n73_include) == 1, "N73 source include drift"
            text = text.replace(n73_include,
                '#include "video_core/renderer_vulkan/vk_texture_cache.h"')
            begin = "// NS2 N73 BEGIN: one real cache-side VkImage sparse admission/bind/retire probe."
            end = "// NS2 N73 END\n\n"
            assert text.count(begin) == text.count(end) == 1, "N73 source body drift"
            i,j=text.index(begin),text.index(end)
            code=text[i:j + len(end)]
            for witness in ("memory_allocator.CreateSparseImage(image_ci)",
                            "AdmitSparseCacheImage(", "owner.Bind(",
                            "RetireSparseCacheProbe(", "logical.CreateImageView(view_info)",
                            "gpu_unsafe.load(std::memory_order_acquire)",
                            "owner.ReadyForSampling()"):
                assert witness in code, ("N73 changed native VkImage ownership", witness)
            text = text[:i] + text[j + len(end):]
        assert git_blob(text.encode()) == current_sha, ("N57 maintained source drift", name)
        if name == "vk_texture_cache_cost.cpp":
            # N49's single vendor-owner addition, reversed without masking F07.
            text = once(text,
                '#include "video_core/renderer_vulkan/vk_texture_cache.h"\n'
                '#ifdef EDEN_NS2_VIEW_DIMENSION_GUARD\n'
                '#include "video_core/renderer_vulkan/ns2_view_type_guard.h"\n#endif',
                '#include "video_core/renderer_vulkan/vk_texture_cache.h"')
            start = '#ifdef EDEN_NS2_VIEW_DIMENSION_GUARD\n    // Keep physical 2D/3D dimensionality'
            end = '#endif\n    if (texture_type) {'
            assert text.count(start) == text.count(end) == 1, "N49 guard differs"
            i = text.index(start)
            j = text.index(end, i)
            text = text[:i] + '    if (texture_type) {' + text[j + len(end):]
            assert git_blob(text.encode()) == "46be65804131d8ffcc4951fc70d2cc6a449c2e85", "N49 touched unrelated PS5 GPU source"
            text = once(text, '#include "performance.h"\n#ifdef EDEN_NS2_ASTC_LAYER_DECODE\n#include <stdexcept>\n#endif',
                        '#include "performance.h"')
            text = once(text,
                "                                            VkFormat format, u32 base_layer = 0,\n"
                "                                            u32 layer_count = VK_REMAINING_ARRAY_LAYERS) {",
                "                                            VkFormat format) {")
            text = once(text,
                "            .baseArrayLayer = base_layer,\n            .layerCount = layer_count,",
                "            .baseArrayLayer = 0,\n            .layerCount = VK_REMAINING_ARRAY_LAYERS,")
            begin = "#ifdef EDEN_NS2_ASTC_LAYER_DECODE\nVkImageView Image::StorageImageLayerView("
            end = "#endif\n\nbool Image::IsRescaled() const noexcept {"
            assert text.count(begin) == text.count(end) == 1
            i, j = text.index(begin), text.index(end)
            text = text[:i] + "bool Image::IsRescaled() const noexcept {" + text[j + len(end):]
            begin = "#ifdef EDEN_NS2_ASTC_LAYER_DECODE\nvoid TextureCacheRuntime::AccelerateImageUploadLayers("
            end = "#endif\n\nvoid TextureCacheRuntime::TransitionImageLayout(Image& image) {"
            assert text.count(begin) == text.count(end) == 1
            i, j = text.index(begin), text.index(end)
            text = text[:i] + "void TextureCacheRuntime::TransitionImageLayout(Image& image) {" + text[j + len(end):]
        else:
            text = once(text,
                '#include "video_core/renderer_vulkan/vk_compute_pass.h"\n'
                '#ifdef EDEN_NS2_ASTC_LAYER_DECODE\n#include <stdexcept>\n'
                '#include "video_core/renderer_vulkan/ns2_astc_decode_preflight.h"\n#endif',
                '#include "video_core/renderer_vulkan/vk_compute_pass.h"')
            text = once(text,
                '#ifdef EDEN_NS2_ASTC_LAYER_DECODE\n'
                '#include "video_core/renderer_vulkan/ns2_astc_assemble_layers.inc"\n'
                '#endif\nconstexpr u32 BL3D_BINDING_INPUT_BUFFER  = 0;',
                'constexpr u32 BL3D_BINDING_INPUT_BUFFER  = 0;')
        assert git_blob(text.encode()) == previous_sha, ("N57 changed unrelated F07 native bytes", name)
        result[name] = text
    return result
