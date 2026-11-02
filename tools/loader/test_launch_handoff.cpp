// SPDX-License-Identifier: GPL-3.0-or-later
// Host-only mailbox contract: no PS5 SDK, Vulkan device, or game launch.
#include "launch_handoff.hpp"
#include <cassert>
#include <cstdint>
#include <utility>

int main() {
    using namespace Eden::LaunchHandoff;
    Clear();
    assert(!Take());
    Frame invalid{};
    invalid.width = 4097;
    invalid.height = 1;
    invalid.rgba.resize(4097 * 4);
    Publish(std::move(invalid));
    assert(!Take());

    Frame mismatched{};
    mismatched.width = 2;
    mismatched.height = 1;
    mismatched.rgba = {1, 2, 3, 4}; // Missing a whole pixel.
    Publish(std::move(mismatched));
    assert(!Take());

    Frame valid{};
    valid.width = 2;
    valid.height = 1;
    valid.rgba = {12, 32, 51, 255, 80, 90, 100, 200};
    assert(Valid(valid));
    Publish(std::move(valid));
    // Zero-extent swapchain and the first two failed upload attempts must
    // never consume the only launcher screenshot.
    for (int retry = 0; retry < 3; ++retry) {
        const auto pending = Peek();
        assert(pending && pending->width == 2 && pending->height == 1);
        assert(pending->rgba[0] == 12);
    }
    const auto shared = Take();
    assert(shared && shared->width == 2 && shared->height == 1);
    assert(shared->rgba.size() == 8);
    assert(shared->rgba[0] == 12 && shared->rgba[7] == 200);
    assert(!Peek()); // Cleared only when Vulkan owns a finished upload.
    assert(!Take()); // Single-use handoff.
    Frame next{1, 1, {255, 0, 0, 255}};
    Publish(std::move(next));
    Clear();
    assert(!Take()); // Launcher retry must not reuse old artwork.
}
