#!/usr/bin/env python3
"""Bounded Vulkan loading diagnostics source witness (not a guest-frame proof).

The loader is allowed to display its own frames while an NS2 title is stuck
before its first guest SwapBuffers. Check the shipping callback owns exactly
two quiet diagnostics per title and resets the stage on window creation.
"""
from pathlib import Path
import re

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
print("ENCORE_VULKAN_LOADING_DIAGNOSTIC_PASS first_guest_frame_not_claimed=1 max_reports=2 reset_per_title=1")
