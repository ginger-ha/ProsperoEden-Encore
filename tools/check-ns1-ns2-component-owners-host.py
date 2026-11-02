#!/usr/bin/env python3
"""P0.3: reviewable NS1/NS2 source ownership; NOT an execution/console pass.

Read the checked-in inventory and verify concrete paths inside this repo and
its pinned vendor submodule. An owner change must update the mapping and the
corresponding host witness in the same change.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/NS1_NS2_COMPONENT_OWNERS.json"
data = json.loads(SOURCE.read_text(encoding="utf-8"))
assert data["schema"] == 1
components = data["components"]
required = {
    "cpu-jit", "loader-content", "hos-ipc", "gmmu-buffer",
    "shader-translation", "vulkan-compute", "texture-cache",
    "frame-present", "launcher-library",
}
names = [entry["name"] for entry in components]
assert len(names) == len(set(names)) and set(names) == required, (
    "Component owner contract drift", names
)
shared_owners = set()
for entry in components:
    assert entry["scope"] in {"shared-with-generation-adapters", "shared-ui"}
    assert entry["remaining"].strip(), entry["name"]
    owner = entry["owner"]
    assert owner not in shared_owners, ("Duplicated canonical owner", owner)
    shared_owners.add(owner)
    paths = [owner, entry["witness"]]
    if entry["scope"] == "shared-with-generation-adapters":
        assert entry["ns2_adapter"] != owner, ("NS2 adapter shadowing common owner", owner)
        paths.append(entry["ns2_adapter"])
    else:
        assert "ns2_adapter" not in entry
    for path in paths:
        assert not path.startswith("/") and ".." not in Path(path).parts, path
        assert (ROOT / path).is_file(), ("Missing pinned component source/witness", path)
    assert entry["witness"].startswith("tools/"), entry["name"]

# The native Compute path must share Vulkan BufferCache and TextureCache;
# do not claim the current native path binds images: unsupported TIC/TSC
# descriptors deliberately fail closed until a real cache handoff exists.
rasterizer = (ROOT / "vendor/encore-active/eden-vulkan/vulkan_rasterizer.cpp").read_text()
compute = (ROOT / "vendor/encore-active/eden-vulkan/vk_compute_pipeline_cost.cpp").read_text()
qmd = (ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/native_qmd_compute_environment.h").read_text()
assert "DispatchNativeCompute" in rasterizer and "ConfigureNative" in rasterizer
assert "ComputePipeline::ConfigureNative" in compute
assert "BufferCache& buffer_cache" in compute
assert "requires_tic_tsc" in qmd and "HasResolvedBufferBindings()" in qmd
assert "std::scoped_lock lock{buffer_cache.mutex}" in rasterizer

print(f"EDEN_NS1_NS2_SOURCE_OWNERS_PASS components={len(components)} "
      "tracked_paths=1 native_texture_handoff_unverified=1")
