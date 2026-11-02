// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// One temporary, title-scoped frame linking the native OpenGL jacket
// animation to the PS5 Vulkan warm-up. No disk I/O and no guest GPU state.
#include <cstdint>
#include <limits>
#include <memory>
#include <mutex>
#include <utility>
#include <vector>

namespace Eden::LaunchHandoff {

struct Frame {
    std::uint32_t width{};
    std::uint32_t height{};
    // Top-to-bottom, tightly packed RGBA8; Vulkan converts to output format.
    std::vector<std::uint8_t> rgba;
};

inline std::mutex frame_mutex;
inline std::shared_ptr<const Frame> pending_frame;

// Bounded by the largest normal 4K console output. Reject anything that
// could overflow the byte count or require an unbounded image allocation.
inline bool Valid(const Frame& frame) {
    constexpr std::uint32_t max_width = 4096;
    constexpr std::uint32_t max_height = 2160;
    return frame.width > 0 && frame.height > 0 &&
           frame.width <= max_width && frame.height <= max_height &&
           frame.rgba.size() == static_cast<std::size_t>(frame.width) *
                                    static_cast<std::size_t>(frame.height) * 4;
}
inline void Publish(Frame&& frame) {
    if (!Valid(frame)) return;
    auto stored = std::make_shared<Frame>(std::move(frame));
    const std::lock_guard lock{frame_mutex};
    pending_frame = std::move(stored);
}
inline std::shared_ptr<const Frame> Take() {
    const std::lock_guard lock{frame_mutex};
    return std::exchange(pending_frame, {});
}
inline void Clear() {
    const std::lock_guard lock{frame_mutex};
    pending_frame.reset();
}
} // namespace Eden::LaunchHandoff
