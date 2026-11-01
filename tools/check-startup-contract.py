#!/usr/bin/env python3
"""Fast release gate for Encore's 13.60 startup/elevation/storage contract."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
main = (root / "headless/main.cpp").read_text()
elevation = (root / "headless/elevation/elevation.cpp").read_text()
helper = (root / "headless/elevation/helper/main.cpp").read_text()
packager = (root / "tools/package-headless-native.sh").read_text()
lifecycle = (root / "src/lifecycle.c").read_text()

body = main[main.index("int main("):]
boot = body.index("BootTrace::Begin")
request = body.index("elevation::request")
migrate_sandbox = body.index("MigrateSandboxData")
migrate_legacy = body.index("MigrateLegacyInstallAssets")
assert boot < request < migrate_sandbox < migrate_legacy
for forbidden in ("std::thread", "std::jthread", "pthread_create"):
    assert forbidden not in body[:request], f"{forbidden} starts before the one-shot helper"

assert "ProbeWritableRoot(Eden::kDataDir)" in body
assert body.index("MigrateLegacyInstallAssets") < body.index("PrepareStorageLayout();") < body.index("BootTrace::Ready")
assert "invalid_success_identity" not in body, "uid/gid inference must not kill a valid filesystem grant"
assert 'target_title_id[] = "PPSA99008"' in helper
assert 'sandbox-elevator.elf' in packager
assert 'PPSA99121' not in lifecycle, "stale lifecycle title ID"
assert 'PPSA99008' in lifecycle

# The rotating 3D jacket is the only authored startup animation. Both
# render backends retain their warm-up presentations but show a plain
# dark handoff, NOT the obsolete violet loading shader.
graphics = (root / "headless/graphics.cpp").read_text()
vulkan_backend = (root / "vendor/encore-active/eden-vulkan/vulkan_renderer.cpp").read_text()
native_presenter = (root / "vendor/encore-active/eden-vulkan/vulkan_window_adapt_pass.cpp").read_text()
assert 'const bool quiet_loading_handoff = hud.loading != 0;' in native_presenter
assert 'if (hud.width && !quiet_loading_handoff && !hud_pipeline)' in native_presenter
assert 'if (hud.width && !quiet_loading_handoff &&' in native_presenter
assert 'const f32 bg_red = quiet_loading_handoff ? 0.024f :' in native_presenter
assert 'const f32 bg_green = quiet_loading_handoff ? 0.035f :' in native_presenter
assert 'const f32 bg_blue = quiet_loading_handoff ? 0.039f :' in native_presenter
assert 'const VkRect2D scissor{' in native_presenter
assert 'const VkRect2D scissor = hud.loading' not in native_presenter
assert 'PresentVulkanLoading(renderer);' in graphics
# A black picture with a live stderr is not proof of a dead game process.
# Emit only bounded milestone signals: Core load, GPU start, guest run and
# two time thresholds while Vulkan still has no first guest frame.
for stage in ('stage=core_loaded', 'stage=gpu_started', 'stage=guest_run_begin'):
    assert stage in main, stage
assert 'EDEN_VULKAN_LOADING_WAIT stage=10s' in graphics
assert 'EDEN_VULKAN_LOADING_WAIT stage=30s' in graphics
assert 'vulkan_loading_diagnostic_stage = 0;' in graphics
assert 'guest_frame_handoff=0' in graphics
assert 'PresentLoading();' in vulkan_backend
assert '"void main(){ color = vec4(0.024, 0.035, 0.039, 1.0); }\\n";' in graphics

for stage in (
    "elevation: request begin",
    "elevation: connect 127.0.0.1:9021",
    "elevation: helper stream complete",
    "elevation: prepare received",
    "elevation: final response",
):
    assert stage in elevation, f"missing startup trace stage: {stage}"

print("Startup contract: trace, single-threaded elevation, real filesystem proof and title identity PASS")
