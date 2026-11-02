#!/usr/bin/env python3
"""Bounded Vulkan loading diagnostics source witness (not a guest-frame proof).

The loader is allowed to display its own frames while an NS2 title is stuck
before its first guest SwapBuffers. Check the shipping callback owns exactly
two quiet diagnostics per title and resets the stage on window creation.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / "headless/graphics.cpp").read_text()
assert source.count("unsigned vulkan_loading_diagnostic_stage{};") == 1
assert source.count("vulkan_loading_diagnostic_stage = 0;") == 1
loading = source.split("bool LoadingTick(", 1)[1].split("GraphicsWindow::GraphicsWindow(", 1)[0]
assert loading.count("EDEN_VULKAN_LOADING_WAIT stage=10s") == 1
assert loading.count("EDEN_VULKAN_LOADING_WAIT stage=30s") == 1
assert 'vulkan_loading_diagnostic_stage == 0 && elapsed >= 10.0' in loading
assert 'vulkan_loading_diagnostic_stage == 1 && elapsed >= 30.0' in loading
assert 'vulkan_loading_diagnostic_stage = 1;' in loading
assert 'vulkan_loading_diagnostic_stage = 2;' in loading
assert 'guest_frame_handoff=0' in loading
assert 'const double elapsed = now - vulkan_loading_start;' in loading
assert 'if (first) sceSystemServiceHideSplashScreen();' in loading
assert 'return true;' in loading
constructor = source.split("GraphicsWindow::GraphicsWindow(", 1)[1]
assert constructor.index("vulkan_loading_diagnostic_stage = 0;") < constructor.index("vulkan_loading_pace = {};")
# Validate stage boundary behavior under monotonic time (not the real GPU).
def stages(elapsed_values):
    stage = 0
    events = []
    for elapsed in elapsed_values:
        if stage == 0 and elapsed >= 10:
            stage = 1
            events.append(10)
        elif stage == 1 and elapsed >= 30:
            stage = 2
            events.append(30)
    return events, stage
assert stages([0, 1, 9.999, 10, 10, 20, 29.999, 30, 30, 100]) == ([10, 30], 2)
assert stages([0, 31, 32]) == ([10, 30], 2)
assert stages([0, 1, 9.9]) == ([], 0)
# Continuous jacket-to-Vulkan loading must use the launcher frame itself,
# not the old purple scene, a black second interstitial, or fake guest frames.
root = Path(__file__).resolve().parents[1]
frontend = (root / "headless/prosperoeden/frontend.cpp").read_text()
handoff = (root / "headless/launch_handoff.hpp").read_text()
renderer = (root / "vendor/encore-active/eden-vulkan/vulkan_renderer.cpp").read_text()
oracle = (root / "vendor/encore-active/eden-vulkan-oracles/vulkan_loading.inc").read_text()
renderer_header = (root / "vendor/encore-active/eden-vulkan/include/video_core/renderer_vulkan/renderer_vulkan.h").read_text()
generator = (root / "tools/prepare-vulkan-port.py").read_text()
assert frontend.count("glReadPixels(") == 2  # dev BMP capture + one production handoff
assert "glReadPixels(0, 0, width, height, GL_RGBA,\n                                         GL_UNSIGNED_BYTE, snapshot.rgba.data());" in frontend
assert frontend.count("LaunchHandoff::Publish(") == 1
handoff_read = frontend.index("snapshot.rgba.data());")
# The first swap is the legitimate startup splash. Verify the swap AFTER
# the completed launcher readback, not the first swap in this source file.
assert frontend.index("display.swap()") < frontend.index("batch.draw(list, viewport,")
assert frontend.index("batch.draw(list, viewport,") < handoff_read < frontend.index("display.swap()", handoff_read)
assert "handoff_captured = true;" in frontend
assert "handoff_captured && launcher.done()" not in frontend  # capture is single-use
assert "if (!handoff_captured && launcher.done() &&" in frontend
launcher_scene = (root / "headless/prosperoeden/pe/ui/launcher.cpp").read_text()
assert "const float leave = 1.0f;" in launcher_scene
assert "if (fade > 0.0f)" not in launcher_scene
assert "LaunchHandoff::Clear()" in frontend
assert "inline bool Valid(const Frame& frame)" in handoff
assert "frame.width <= max_width && frame.height <= max_height" in handoff
assert "std::exchange(pending_frame, {})" in handoff
assert "inline std::shared_ptr<const Frame> Peek()" in handoff
for evidence in (
    '#include "launch_handoff.hpp"',
    "Eden::LaunchHandoff::Peek()",
    "Eden::LaunchHandoff::Clear();",
    "loading_jacket_attempts >= 3",
    "loading_jacket_attempted = true;",
    "loading_jacket_buffer = std::move(buffer);",
    "buffer.Flush();",
    "VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL",
    "cmdbuf.CopyBufferToImage(upload, target,",
    "loading_jacket_width == frame->width",
):
    assert evidence in renderer, evidence
assert "vk::Buffer loading_jacket_buffer{};" in renderer_header
assert "u32 loading_jacket_attempts{};" in renderer_header
assert "loading_jacket_attempts{}" in generator
assert renderer.index("Eden::LaunchHandoff::Peek()") < renderer.index("loading_jacket_buffer = std::move(buffer);") < renderer.index("Eden::LaunchHandoff::Clear();")
assert "loading_jacket_buffer{}" in generator
assert "launch_handoff.hpp" in generator
assert "loading_jacket_buffer = std::move(buffer);" in oracle
assert "cmdbuf.CopyBufferToImage(upload, target," in oracle
assert renderer.count("EDEN_LOADER_JACKET_HANDOFF_VULKAN") == 4  # success + fallback + retries + unsupported format
# A native build has been deliberately blocked until full NS2 / NS1
# compatibility and console validation; host-only tests remain enabled.
research = (root / ".github/workflows/ns2-native-ps5-research.yml").read_text()
release = (root / ".github/workflows/build-040-zbic.yml").read_text()
assert "  workflow_dispatch:" in research
assert "  push:" not in research
assert "    if: ${{ false }}" in research
assert "    if: ${{ false }}" in release
# Compile and execute the tiny mailbox owner in host mode: one transfer,
# bounded dimensions, no stale snapshot and no copied pixels on subsequent
# Vulkan warm-up ticks. Does not build the PS5 app or GPU runtime.
compiler = shutil.which("clang++") or shutil.which("g++")
assert compiler, "host C++20 compiler required for single-loader mailbox test"
with tempfile.TemporaryDirectory(prefix="encore-single-loader-") as directory:
    exe = Path(directory) / "test_launch_handoff"
    subprocess.run(
        [compiler, "-std=c++20", "-Wall", "-Wextra", "-Werror",
         "-pthread", "-O2", "-I", str(root / "headless"),
         str(root / "tools/loader/test_launch_handoff.cpp"), "-o", str(exe)],
        check=True,
    )
    subprocess.run([str(exe)], check=True)
print("ENCORE_LOADER_MAILBOX_HOST_PASS single_use=1 bounded=1")
print("ENCORE_SINGLE_LOADER_HANDOFF_SOURCE_PASS build_ps5_blocked=1")

print("ENCORE_VULKAN_LOADING_DIAGNOSTIC_PASS first_guest_frame_not_claimed=1 max_reports=2 reset_per_title=1")
