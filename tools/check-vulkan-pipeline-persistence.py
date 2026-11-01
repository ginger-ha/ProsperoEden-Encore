#!/usr/bin/env python3
"""Source contracts for PS5 foreground Vulkan pipeline caching.

Do not cancel the persistent compiler worker pool while initializing a title's
disk cache. This checks integration only; runtime PS5 result is not proven.
"""
import ast
from pathlib import Path
root=Path(__file__).resolve().parents[1]
main=(root/"headless/main.cpp").read_text()
port=(root/"tools/prepare-vulkan-port.py").read_text()
ast.parse(port)
assert 'Settings::values.use_disk_shader_cache = game;' in main
assert 'Settings::values.use_vulkan_driver_pipeline_cache = game;' in main
assert '#ifdef EDEN_PS5_VULKAN\n                if (game && Settings::values.use_disk_shader_cache.GetValue())' in main
assert 'lazy_cache.request_stop();' not in main
assert 'LoadDiskResources(\n                            title_id, std::stop_token{},' in main
assert 'mode=bounded-prewarm32' in main
assert 'EDEN_VULKAN_SHADER_CACHE title=' in main
assert 'if shader_source.count(lazy_vulkan_cache_anchor) != 1:' in port
assert 'if (stop_loading.stop_requested()) {' in port
assert 'LOG_INFO(Render_Vulkan, "PS5 lazy shader cache ready' in port
assert port.index('if (stop_loading.stop_requested()) {') < port.index('shader_source = shader_source.replace(lazy_vulkan_cache_anchor')
# An early return only after pipeline filenames and driver cache creation,
# before emitting any queue/wait/cancel commands: the worker pool survives.
v=port.split("lazy_vulkan_cache_replacement = '''",1)[1].split("'''",1)[0]
assert v.index('LoadVulkanPipelineCache(') < v.index('if (stop_loading.stop_requested())')
assert v.index('if (stop_loading.stop_requested())') < v.index('    struct {')
assert 'workers.WaitForRequests' not in v
# Quota implementation appears AFTER the lazy initialization branch in the
# pinned generator, so an intentional canceled token stays setup-only.
for i in range(5):
    assert f'f07_warm_before_{i}' in port
    assert f'f07_warm_after_{i}' in port
assert 'kStartupPrewarmPipelines = 32' in port
assert 'startup_reader.request_stop();' in port
assert 'workers.WaitForRequests(stop_loading);' in port
assert 'const std::stop_token reader_token{startup_reader.get_token()};' in port
assert 'VideoCommon::LoadPipelines(reader_token' in port
assert 'workers.WaitForRequests(reader_token)' not in port
assert 'vulkan_cache_create_anchor' in port
assert 'vulkan_cache_create_replacement' in port
assert 'if shader_source.count(vulkan_cache_create_anchor) != 1:' in port
assert 'if (data_size == 0) throw;' in port
assert 'Ignoring incompatible driver pipeline cache' in port
assert 'pipeline_cache_ci.initialDataSize = 0;' in port
assert 'if shader_source.count(vulkan_cache_save_anchor) != 1:' in port
assert 'vulkan_cache_save_replacement' in port
assert 'std::filesystem::rename(staging, filename, rename_error);' in port
assert 'std::lock_guard save_lock{save_mutex};' in port
assert 'file.flush();' in port and 'file.close();' in port
assert 'Retained old driver cache after failed save' in port
# PS5 branch must never remove an existing valid cache after an interrupted save.
# Reproduce the REAL patch order applied during native CMake generation:
# transactional PS5 driver-cache saving is injected BEFORE pipeline timer
# instrumentation. In build #37843116788 this changed the function from
# ") try {" to ") {" and an obsolete later shader_costs anchor aborted CMake.
# This regression must run before make prepare, not only after a failed build.
def literal(name: str):
    tree = ast.parse(port)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"Missing Vulkan patch assignment: {name}")

original_save = literal("vulkan_cache_save_anchor")
rewritten_save = literal("vulkan_cache_save_replacement")
costs = literal("shader_costs")
timer_sites = [(old, new) for old, new in costs if "cache_version" in old]
assert len(timer_sites) == 1
timer_old, timer_new = timer_sites[0]
assert original_save.count("cache_version) try {") == 1
assert rewritten_save.count("cache_version) {") == 1
# This was the exact exception thrown by prepare-vulkan-port.py before any
# native C++ compilation. Match the generated *final* function, not upstream.
assert rewritten_save.count(timer_old) == 1
instrumented = rewritten_save.replace(timer_old, timer_new)
assert instrumented.count("Eden::Performance::VulkanTimer(18)") == 1
assert instrumented.count("std::filesystem::rename(staging, filename, rename_error)") == 1
assert instrumented.index("Eden::Performance::VulkanTimer(18)") < instrumented.index("#ifdef PS5_NATIVE")

saving = port.split("vulkan_cache_save_replacement = '''", 1)[1].split("'''", 1)[0]
native = saving.split("#ifdef PS5_NATIVE", 1)[1].split("#else", 1)[0]
assert 'std::filesystem::remove(filename' not in native
assert 'Common::FS::RemoveFile(filename)' not in native
assert 'std::filesystem::remove(staging, cleanup_error)' in native
print("PASS Vulkan PS5 bounded shader prewarm and non-destructive persistent worker pool")
print("Driver cache / filesystem correctness on real PS5: NOT TESTED")
