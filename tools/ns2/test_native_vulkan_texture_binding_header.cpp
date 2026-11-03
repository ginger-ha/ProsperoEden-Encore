// SPDX-License-Identifier: GPL-3.0-or-later
// P2.2b: compile the production shared Vulkan cache and Compute interfaces,
// never a mock image descriptor. Host syntax only; no VkDevice is created.
#include <memory>
#include <optional>
#include <type_traits>
#include <utility>

#include "video_core/renderer_vulkan/vk_compute_pipeline.h"
#include "video_core/renderer_vulkan/vk_texture_cache.h"
#include "video_core/texture_cache/texture_cache_base.h"

#if !defined(PS5_NATIVE) || !defined(EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL)
#error "P2.2b native Vulkan cache owner probe requires the exact native gates"
#endif

using Vulkan::Image;
using Vulkan::ImageView;
using Vulkan::Sampler;
using Vulkan::TextureCache;
using Vulkan::NativeComputeImageBinding;

static_assert(std::is_same_v<decltype(std::declval<Image&>().PinNativeGpu()),
                             std::shared_ptr<u8>>);
static_assert(std::is_same_v<decltype(std::declval<ImageView&>().PinNativeGpu()),
                             std::shared_ptr<u8>>);
static_assert(std::is_same_v<decltype(std::declval<Sampler&>().PinNativeGpu()),
                             std::shared_ptr<u8>>);
static_assert(std::is_same_v<decltype(std::declval<Image&>().CanRetireNativeGpu()), bool>);
static_assert(std::is_same_v<decltype(std::declval<ImageView&>().CanRetireNativeGpu()), bool>);
static_assert(std::is_same_v<decltype(std::declval<Sampler&>().CanRetireNativeGpu()), bool>);
static_assert(std::is_same_v<
    decltype(std::declval<TextureCache&>().PinNativeImageView(VideoCommon::ImageViewId{})),
    std::optional<TextureCache::NativePinnedImageView>>);
static_assert(std::is_same_v<
    decltype(std::declval<TextureCache&>().PinNativeSampler(VideoCommon::SamplerId{})),
    std::shared_ptr<u8>>);
static_assert(std::is_same_v<decltype(NativeComputeImageBinding::image_pin),
                             std::shared_ptr<u8>>);
static_assert(std::is_same_v<decltype(NativeComputeImageBinding::view_pin),
                             std::shared_ptr<u8>>);
static_assert(std::is_same_v<decltype(NativeComputeImageBinding::sampler_pin),
                             std::shared_ptr<u8>>);
static_assert(std::is_same_v<decltype(NativeComputeImageBinding::view), VkImageView>);
static_assert(std::is_same_v<decltype(NativeComputeImageBinding::sampler), VkSampler>);
