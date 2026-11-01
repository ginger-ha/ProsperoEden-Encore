#!/usr/bin/env python3
"""Fail if the active C/C++ source catalogue drifts from tracked files.

This verifies file-level coverage and exact graph cross-links only.
It is not a function audit, compiler check or console-test certificate.
"""
from pathlib import Path
import json
import re
import runpy

root = Path(__file__).resolve().parents[1]
active = root / "vendor/encore-active"
document = (root / "docs/EDEN_ACTIVE_SOURCE_CATALOG.md").read_text()
audit = (root / "docs/EDEN_CORE_AUDIT_DEPENDENCIES.md").read_text()
begin, end = "<!-- ACTIVE_SOURCE_CATALOG_START -->", "<!-- ACTIVE_SOURCE_CATALOG_END -->"
assert document.count(begin) == document.count(end) == 1
section = document.split(begin, 1)[1].split(end, 1)[0]
suffixes = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".inc", ".inl", ".s", ".S", ".asm", ".cl"}
physical_all = sorted(
    p.relative_to(active).as_posix()
    for p in active.rglob("*")
    if p.is_file() and p.suffix in suffixes
)
# Preserve the audited production source catalogue. The NS2 research sources
# are tracked separately and explicitly; they are not F07 shipping proofs.
research_manifest = json.loads(
    (root / "docs/NS2_RESEARCH_ADDED_SOURCE_OWNERS.json").read_text()
)
research_paths = research_manifest["paths"]
assert research_manifest["schema_version"] == 1
assert len(research_paths) == len(set(research_paths)) == 111
assert research_paths == sorted(research_paths)
assert set(research_paths) <= set(physical_all), (
    "Missing pinned NS2 research source owners", sorted(set(research_paths) - set(physical_all))
)
assert all(p.startswith(("ns2-", "eden-core/include/", "eden-vulkan/include/"))
           for p in research_paths), "Unreviewed NS2 source category"
# Four extracted AOC translation/header owners arrived with the mainline
# installation integration. They are shipping additions, not historical F07
# owners and not opt-in NS2 research files. Keep the historical F07 review
# immutable for optimization triage while cataloguing AOC in shipping ownership.
extracted_aoc_owners = {
    "eden-core/src/core/file_sys/extracted_aoc.h",
    "eden-core/src/core/file_sys/extracted_aoc_paths.h",
    "eden-core/src/core/file_sys/romfs_factory.cpp",
    "eden-core/src/core/hle/service/aoc/addon_content_manager.cpp",
}
assert extracted_aoc_owners <= set(physical_all), (
    "Missing maintained extracted AOC owners", sorted(extracted_aoc_owners - set(physical_all))
)
assert not extracted_aoc_owners.intersection(research_paths), (
    "Extracted AOC production owners misclassified as NS2 research"
)
aoc_recipe = (root / "headless/CMakeLists.txt").read_text()
assert "foreach(eden_aoc_relative IN ITEMS" in aoc_recipe
assert '"file_sys/romfs_factory.cpp"' in aoc_recipe
assert '"hle/service/aoc/addon_content_manager.cpp"' in aoc_recipe
assert 'list(REMOVE_ITEM core_sources "${eden_aoc_relative}")' in aoc_recipe
assert 'list(APPEND core_sources "${eden_aoc_maintained}")' in aoc_recipe
print("ENCORE_EXTRACTED_AOC_OWNER_PASS", f"new_shipping={len(extracted_aoc_owners)}")
# Shared NS2 heap overlays are newly reviewed, release-selected kernel owners.
# They are neither experimental research nor part of the frozen F07 historical
# optimization catalogue. Track them separately and retain the existing
# 337-owner F07 graph (and its original audit receipts) byte-for-byte.
shared_ns2_kernel_owners = {
    "ns2-runtime/kernel/core/hle/kernel/k_address_space_info.cpp",
    "ns2-runtime/kernel/core/hle/kernel/svc/svc_physical_memory.cpp",
    "ns2-runtime/process/core/core.cpp",
}
assert shared_ns2_kernel_owners <= set(physical_all), (
    "Missing shipping NS2 kernel overlays", sorted(shared_ns2_kernel_owners - set(physical_all))
)
assert not shared_ns2_kernel_owners.intersection(research_paths)
kernel_select = (root / "headless/CMakeLists.txt").read_text()
assert 'set(EDEN_SHARED_NS2_KERNEL_HEAP ON)' in kernel_select
assert 'EDEN_FINAL_RELEASE_PROFILE AND EDEN_REVIEWED_DUAL_NPDM' in kernel_select
for relative in shared_ns2_kernel_owners:
    if relative.startswith("ns2-runtime/kernel/core/"):
        assert relative.removeprefix("ns2-runtime/kernel/core/") in kernel_select
assert 'ns2-runtime/process/core/core.cpp' in kernel_select
print("ENCORE_SHARED_NS2_KERNEL_SOURCE_PASS", f"new_shipping={len(shared_ns2_kernel_owners)}")
shared_ns2_audio_owners = {
    "ns2-runtime/audio/core/hle/service/audio/audio.cpp",
    "ns2-runtime/audio/core/hle/service/audio/nx2_audio_user_client.h",
    "ns2-runtime/audio/core/hle/service/nx2_streamplay.h",
}
assert shared_ns2_audio_owners <= set(physical_all), (
    "Missing NS2 audio service owners", sorted(shared_ns2_audio_owners - set(physical_all))
)
assert not shared_ns2_audio_owners.intersection(set(research_paths) | shared_ns2_kernel_owners)
assert 'set(EDEN_SHARED_NS2_AUDIO ON)' in kernel_select
print("ENCORE_SHARED_NS2_AUDIO_SOURCE_PASS", f"owners={len(shared_ns2_audio_owners)}")
shared_ns2_gpu_access_owners = {
    "ns2-runtime/gpu_access_svc/core/hle/kernel/svc.cpp",
    "ns2-runtime/gpu_access_svc/core/hle/kernel/ns2_gpu_memory_attribute.h",
    "ns2-runtime/gpu_access_svc/core/hle/kernel/svc_types.h",
    "ns2-runtime/gpu_access_svc/core/hle/kernel/k_memory_block.h",
}
assert shared_ns2_gpu_access_owners <= set(physical_all), sorted(shared_ns2_gpu_access_owners - set(physical_all))
assert not shared_ns2_gpu_access_owners.intersection(set(research_paths) | shared_ns2_kernel_owners | shared_ns2_audio_owners)
assert 'set(EDEN_SHARED_NS2_GPU_ACCESS_SVC ON)' in kernel_select
print("ENCORE_SHARED_NS2_GPU_ACCESS_SOURCE_PASS", f"owners={len(shared_ns2_gpu_access_owners)}")
physical = [p for p in physical_all
            if p not in set(research_paths) | shared_ns2_kernel_owners | shared_ns2_audio_owners | shared_ns2_gpu_access_owners]
# These two versioned headers preserve the immutable upstream Eden snapshot.
# They must be present in the real source catalogue, not excluded as NS2 fixtures.
warning_hygiene = {
    "eden-header-hygiene/include/common/page_table.h",
    "eden-header-hygiene/include/video_core/macro.h",
}
assert {p for p in physical if p.startswith("eden-header-hygiene/")} == warning_hygiene, (
    "Warning-hygiene active owner drift")
assert len(physical) == 337, ("Shipping source catalogue changed", len(physical))
print("NS2_RESEARCH_SOURCE_LEDGER_PASS",
      f"unqualified={len(research_paths)}", f"historical={len(physical)}")
graph = {}
for line in audit.splitlines():
    if not re.match(r"^\| [A-Z][0-9]{2,3} \|", line):
        continue
    fields = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(fields) < 4 or not fields[3].startswith("vendor/encore-active/"):
        continue
    relative = fields[3].removeprefix("vendor/encore-active/")
    graph.setdefault(relative, []).append(fields[0])
def role(path):
    if path.startswith("eden-backports/"):
        return "shipping-backport"
    if path.startswith("ps5-mesa/"):
        return "driver-fork"
    # Test-only historical generator snippets are NOT shipping overrides.
    if path.startswith("eden-vulkan-oracles/"):
        return "oracle-only"
    return "maintained-override"
expected = [
    f"| `{path}` | `{role(path)}` | {','.join(graph[path]) if path in graph else '—'} |"
    for path in physical
]
present = [line for line in section.splitlines() if line.startswith("| `")]
assert present == expected, (
    "Active source catalogue stale or exact graph linkage changed",
    len(present), len(expected),
    next(((a, b) for a, b in zip(present, expected) if a != b), None),
)
# The shipping backport manifest also carries two build recipes that are not
# C/C++ source files; track them explicitly rather than silently omitting them.
manifest = json.loads((active / "eden-backports/manifest.json").read_text())
shipping = set(manifest["entries"])
shipping_cpp = {"src/" + p.removeprefix("eden-backports/src/")
                for p in physical if p.startswith("eden-backports/src/")}
build_recipes = {"src/common/CMakeLists.txt", "src/core/CMakeLists.txt"}
assert shipping == shipping_cpp | build_recipes, (
    "Shipping backport source/build manifest coverage drift",
    sorted(shipping ^ (shipping_cpp | build_recipes)),
)
# Keep the expected count tied to the reviewed manifest revision: every
# additional shipping patch requires an explicit inventory review.
assert len(shipping) == 83 and len(manifest["shipping_receipts"]) == 50
assert all(re.fullmatch(r"[0-9a-f]{64}", digest)
           for digest in manifest["shipping_receipts"].values()), (
    "invalid shipping patch SHA256 receipt",
)
assert manifest["excluded_experimental"] == ["EDEN_EXPERIMENTAL_DUMMY_THREAD_WAITS"]
# All nine selected Vulkan cost translation units have exact graph owners.
# This is source-ownership coverage, not evidence of GPU progress.
vulkan_recipe = (root/"headless/vulkan.cmake").read_text()
cost_modules = ("vk_fence_manager", "vk_buffer_cache", "vk_texture_cache",
                "vk_descriptor_buffer", "vk_multi_range_buffer", "vk_compute_pass",
                "vk_graphics_pipeline", "vk_compute_pipeline", "vk_pipeline_cache")
assert "foreach(name " + " ".join(cost_modules) + ")" in vulkan_recipe
assert 'list(APPEND video_sources "${PORT_BUILD_DIR}/${name}_cost.cpp")' in vulkan_recipe
for module in cost_modules:
    relative = "eden-vulkan/" + module + "_cost.cpp"
    assert (active/relative).is_file(), ("missing selected Vulkan cost source", relative)
    assert relative in graph, ("missing indexed Vulkan cost source", relative)
print("ENCORE_VULKAN_COST_OWNER_PASS", f"selected={len(cost_modules)}")

# Keep the native GPU/guest memory header overrides distinguishable from
# the pinned and materialized backport copies. Selection is native-only.
native_cmake = (root/"headless/CMakeLists.txt").read_text()
assert 'set(EDEN_NATIVE_DIRTY_HEADER_ROOT' in native_cmake
assert 'target_include_directories(core BEFORE PUBLIC "${EDEN_NATIVE_DIRTY_HEADER_ROOT}")' in native_cmake
assert 'target_include_directories(video_core BEFORE PRIVATE "${EDEN_NATIVE_DIRTY_HEADER_ROOT}")' in native_cmake
native_mem = ("device_memory_manager.inc", "gpu_dirty_memory_manager.h", "guest_memory.h")
for name in native_mem:
    rel = "eden-core/overrides/core/" + name
    assert (active/rel).is_file(), ("missing native memory override", rel)
    assert rel in graph, ("native memory override lacks active function owner", rel)
    assert '${EDEN_NATIVE_DIRTY_HEADER_ROOT}/core/' + name in native_cmake
print("ENCORE_NATIVE_MEMORY_OWNER_PASS", f"headers={len(native_mem)}")

# Maintained core code and headers must never be silently omitted from the
# function-owner register. Do not confuse an indexed path with a HOST proof.
maintained_core_paths = [path for path in physical if path.startswith("eden-core/")]
assert len(maintained_core_paths) == 167, ("maintained core source set changed", len(maintained_core_paths))
assert all(path in graph for path in maintained_core_paths), (
    "uncatalogued maintained core source paths",
    [path for path in maintained_core_paths if path not in graph],
)
print("ENCORE_MAINTAINED_CORE_OWNER_PASS", f"files={len(maintained_core_paths)}")

# A maintained native draw manager must replace (not join) the pinned
# engine source. Tracking its file and V108 graph row alone is insufficient
# if CMake silently compiles the old function body instead.
draw_owner = "eden-core/src/video_core/engines/draw_manager.cpp"
draw_sel = native_cmake.split("set(EDEN_MAINTAINED_DRAW_MANAGER", 1)
assert len(draw_sel) == 2, "native selected draw owner missing"
draw_block = draw_sel[1].split("# A guest span must be rejected BEFORE", 1)[0]
assert 'list(REMOVE_ITEM video_sources engines/draw_manager.cpp)' in draw_block
assert 'list(APPEND video_sources "${EDEN_MAINTAINED_DRAW_MANAGER}")' in draw_block
assert '"${PORT_ROOT}/vendor/encore-active/"' not in draw_block
assert '"${PORT_ROOT}/vendor/encore-active/eden-core/src/video_core/engines/draw_manager.cpp"' in draw_block
assert draw_owner in graph and graph[draw_owner] == ["V108"]
assert (active / draw_owner).is_file()
print("ENCORE_INDEXED_DRAW_OWNER_PASS", "source=maintained", "single_CMake_target=video_core")

# GPU variants and the coordinated HLE header overlays are not optional
# catalogue blind spots, even if selected only by a native build flag.
for family, size in (("eden-gpu/", 4), ("eden-threading/", 12)):
    members = [path for path in physical if path.startswith(family)]
    assert len(members) == size, ("maintained family footprint changed", family, len(members))
    assert all(path in graph for path in members), (
        "uncatalogued maintained family file", family,
        [path for path in members if path not in graph],
    )
print("ENCORE_GPU_THREADING_OWNER_PASS", "gpu=4", "threading=12")

# The surface lifecycle and bounded local-memory shader are already
# maintained sources; require their REAL source selection, not a second copy.
shader_rel = "eden-shader/src/shader_recompiler/frontend/maxwell/translate/impl/load_store_local_shared.cpp"
surface_rel = "eden-surface-lifecycle/src/core/hle/service/nvnflinger/surface_flinger.cpp"
composer_rel = "eden-surface-lifecycle/src/core/hle/service/nvnflinger/hardware_composer.cpp"
for rel in (shader_rel, surface_rel, composer_rel):
    assert rel in graph and (active / rel).is_file(), ("missing active owner", rel)
shader_recipe = (root / "headless/CMakeLists.txt").read_text()
assert 'list(APPEND eden_shader_sources "${EDEN_MAINTAINED_SHADER_LOCAL}")' in shader_recipe
assert 'set_property(TARGET shader_recompiler PROPERTY SOURCES "${eden_shader_sources}")' in shader_recipe
surface_installer = (root / "tools/install-vendored-surface-lifecycle.py").read_text()
surface_prepare = (root / "tools/prepare-build.sh").read_text()
assert 'ORIGINAL_GIT_BLOB = "a6136c111d96d2660c28b27c6881e3b671e7eed8"' in surface_installer
assert 'WaitForComposite();' in surface_installer and 'm_composer.RemoveLayerLocked(' in surface_installer
assert 'tools/install-vendored-surface-lifecycle.py "$eden"' in surface_prepare
# Installer verifies BOTH pinned originals and rejects unknown staged
# translations before replacing either one. This avoids mixing mismatched
# SurfaceFlinger/HardwareComposer lifetimes in a single native app.
assert 'COMPOSER_ORIGINAL_GIT_BLOB = "5decb791e1bb1ab2420f386e3fdbdd2b8628a324"' in surface_installer
assert 'if existing not in (original, maintained)' in surface_installer
assert 'check_composer()' in surface_installer
assert 'for rel, source, original, maintained, previous, label in sources:' in surface_installer
assert 'COMPOSER_PATH, COMPOSER_ACTIVE' in surface_installer
print("ENCORE_SHADER_SURFACE_SOURCE_OWNER_PASS sources=3")

# Core native Vulkan device, query and presentation implementation units
# are versioned sources selected into the disposable build tree by the Vulkan
# recipe. Exact source ownership is not a successful native GPU execution.
native_vk_sources = (
    "vulkan_device.cpp", "vulkan_memory_allocator.cpp", "vulkan_query_cache.cpp", "vulkan_blit_screen.cpp",
    "vulkan_window_adapt_pass.cpp", "vulkan_wrapper.cpp",
)
for unit in native_vk_sources:
    rel = "eden-vulkan/" + unit
    assert rel in graph and (active / rel).is_file(), ("uncatalogued Vulkan unit", rel)
    assert '"${PORT_BUILD_DIR}/' + unit + '"' in vulkan_recipe, ("source selection lost", unit)
print("ENCORE_VULKAN_DEVICE_PRESENT_OWNER_PASS", f"sources={len(native_vk_sources)}")

# Vulkan headers are shipped as an ABI-consistent set with the selected
# maintained translation units; do not let include-root owners disappear.
assert 'file(COPY "${EDEN_ACTIVE_VULKAN}/" DESTINATION "${PORT_BUILD_DIR}")' in vulkan_recipe
assert 'target_include_directories(video_core BEFORE PUBLIC "${PORT_BUILD_DIR}/include")' in vulkan_recipe
abi_headers = ("vk_scheduler.h", "vk_present_manager.h", "vk_descriptor_buffer.h",
               "vk_blit_screen.h", "vk_buffer_cache.h", "renderer_vulkan.h")
for header in abi_headers:
    rel = "eden-vulkan/include/video_core/renderer_vulkan/" + header
    assert (active/rel).is_file() and rel in graph, ("missing selected Vulkan ABI owner", rel)
print("ENCORE_VULKAN_SHARED_ABI_OWNER_PASS", f"headers={len(abi_headers)}")

# Summary prose is itself an audit contract, not a manually stale count.
linked_count = sum(path in graph for path in physical)
assert f"**{len(physical)} fichiers** de code" in document
source_truth = (root / "docs/EDEN_OVERRIDE_SOURCE_OF_TRUTH.md").read_text()
assert f"**{len(physical)} sources et en-têtes suivis**" in source_truth, (
    "stale single-source summary", len(physical)
)
assert f"**{linked_count} fichiers** possèdent" in document
if linked_count == len(physical):
    assert "**0 fichier** reste sans correspondance" in document
else:
    assert f"**{len(physical)-linked_count} fichiers** n'ont" in document
root_cmake = (root / "headless/CMakeLists.txt").read_text()
root_generator_count = len(re.findall(r'write_derived\(\s*"', root_cmake))
if root_generator_count == 1:
    assert "L'inventaire du générateur CMake principal G23" in document
else:
    assert f"L'inventaire des {root_generator_count} générateurs CMake" in document
# The CMake debt summary must count actual call sites, not an obsolete snapshot.
override_inventory = (root / "docs/EDEN_OVERRIDE_MIGRATION_INVENTORY.md").read_text()
root_call = "appel générateur" if root_generator_count == 1 else "appels générateurs"
assert f"**{root_generator_count} {root_call}**" in override_inventory
# Source comments describing retired rewrites must not be counted as CMake calls.
active_reads = len(re.findall(r'^\s*file\(READ', root_cmake, re.M))
active_replacements = len(re.findall(r'^\s*string\(REPLACE', root_cmake, re.M))
assert f"**{active_reads} lectures `file(READ`**" in override_inventory
assert f"**{active_replacements} remplacements" in override_inventory

# Separate headless C/C++ footprint: active Encore sources are not the only
# potential implementation units. Track ALL paths without inventing
# native compile coverage or marking launcher work as validated.
headless_doc = (root / "docs/EDEN_HEADLESS_SOURCE_CATALOG.md").read_text()
headless_start = "<!-- HEADLESS_SOURCE_CATALOG_START -->"
headless_end = "<!-- HEADLESS_SOURCE_CATALOG_END -->"
assert headless_doc.count(headless_start) == headless_doc.count(headless_end) == 1
headless_exts = {".c", ".cc", ".cpp", ".h", ".hpp", ".inc", ".cl"}
headless_actual = sorted(
    p.relative_to(root).as_posix()
    for p in (root / "headless").rglob("*")
    if p.is_file() and p.suffix in headless_exts
)
headless_rows = []
for entry in headless_doc.split(headless_start, 1)[1].split(headless_end, 1)[0].splitlines():
    if not entry.startswith("| `headless/"):
        continue
    cells = [cell.strip() for cell in entry.strip().strip("|").split("|")]
    assert len(cells) == 4 and cells[0].startswith("`headless/"), ("malformed headless row", entry)
    headless_rows.append((cells[0].strip("`"), cells[1], cells[2], cells[3]))
assert [r[0] for r in headless_rows] == headless_actual, (
    "headless source path catalog drift", len(headless_rows), len(headless_actual))
# The vendor-active graph above intentionally stores vendor-relative keys.
# Headless paths use repository-relative keys and need an independent map.
headless_graph = {}
for entry in audit.splitlines():
    if not entry.startswith("| "):
        continue
    cells = [cell.strip() for cell in entry.strip().strip("|").split("|")]
    if len(cells) == 9 and re.fullmatch("[A-Z][0-9]{2,3}", cells[0]) and cells[3].startswith("headless/"):
        headless_graph.setdefault(cells[3], []).append(cells[0])
# These three headless runtime translation units are application-owned,
# not third-party dependency overrides. They must remain indexed and selected
# by their actual CMake targets; moving them into vendor would be misleading.
runtime_headless = {
    "headless/metadata_bridge.cpp":
        'add_library(eden-metadata STATIC "${EDEN_PORT_DIR}/metadata_bridge.cpp")',
    "headless/stop_limit.cpp":
        '"${EDEN_PORT_DIR}/crash_report.cpp" "${EDEN_PORT_DIR}/stop_limit.cpp"',
    "headless/zbic_compression.cpp":
        'target_sources(common PRIVATE "${EDEN_PORT_DIR}/zbic_compression.cpp")',
}
for path, selection in runtime_headless.items():
    assert path in headless_graph, ("runtime source lacks functional audit entry", path)
    assert selection in native_cmake, ("tracked runtime unit lost compile selection", path)
for path in ("headless/metadata_bridge.h", "headless/stop_limit.h",
             "headless/zbic_compression.h", "headless/graphics.h",
             "headless/gpu_failure.h", "headless/gpu_deferred_write_queue.h"):
    assert path in headless_graph, ("runtime interface lacks graph owner", path)
print("ENCORE_HEADLESS_RUNTIME_OWNERS_PASS",
      f"compiled={len(runtime_headless)}", "headers=6")

headless_linked = sum(p in headless_graph for p in headless_actual)
for p, family, owner, state in headless_rows:
    if p in headless_graph:
        assert owner == ",".join(headless_graph[p]) and state.strip().startswith("Chemin indexé"), (
            "headless graph owner stale", p)
    else:
        assert owner == "—" and state.strip() == "À qualifier", ("headless owner stale", p)
# Separate intentionally unlinked application/UI and test roles from
# vendor-source overrides. Count from actual catalog/graph, not a guessed
# TODO total or a second manually maintained ownership register.
from collections import Counter
unlinked_by_role = Counter(role for path, role, _, _ in headless_rows
                           if path not in headless_graph)
assert sum(unlinked_by_role.values()) == len(headless_actual)-headless_linked
assert set(unlinked_by_role) == {
    "launcher/UI", "harness/test", "outil auxiliaire",
    "données générées"}
assert unlinked_by_role.get("en-tête/fragment", 0) == 0, (
    "new unowned headless header or fragment", unlinked_by_role)
assert all(path.startswith("headless/prosperoeden/")
           for path, role, _, _ in headless_rows if role == "launcher/UI")
assert all(path in headless_graph for path, role, _, _ in headless_rows
           if role == "runtime/bridge")
for role, count in unlinked_by_role.items():
    assert f"| `{role}` | **{count}** |" in headless_doc, (
        "unlinked headless role summary stale", role, count)
assert f"| **Total non indexé** | **{sum(unlinked_by_role.values())}** |" in headless_doc

assert "**179** chemins" in headless_doc
assert f"**{headless_linked}** chemins déjà présents" in headless_doc
assert f"**{len(headless_actual)-headless_linked}** chemins sans propriétaire exact" in headless_doc
print("ENCORE_HEADLESS_SOURCE_CATALOG_PASS",
      f"paths={len(headless_actual)}", f"graph_exact={headless_linked}",
      f"unlinked={len(headless_actual)-headless_linked}")

print("ENCORE_ACTIVE_CATALOG_SUMMARY_PASS",
      f"files={len(physical)}", f"covered={linked_count}",
      f"cmake_primary_generators={root_generator_count}")

# Every versioned Vulkan source and ABI header selected through the fork's
# configure-time copy has an exact source ownership record. This guards
# coverage, not GPU forward progress or successful native device tests.
vulkan_family = [p for p in physical if p.startswith("eden-vulkan/")]
assert len(vulkan_family) == 43, ("Vulkan maintained footprint changed", len(vulkan_family))
assert all(p in graph for p in vulkan_family), (
    "Vulkan maintained source lacks owner", [p for p in vulkan_family if p not in graph],
)
assert 'file(COPY "${EDEN_ACTIVE_VULKAN}/" DESTINATION "${PORT_BUILD_DIR}")' in vulkan_recipe
print("ENCORE_VULKAN_WHOLE_FAMILY_OWNER_PASS", f"files={len(vulkan_family)}")

# The immutable guest-network shipping header is disabled by a native-only
# include-root override. Guest BSD, DNS and NIFM must all consult this policy.
native_offline = "eden-core/overrides/core/hle/service/sockets/encore_guest_network_policy.h"
shipping_online = "eden-backports/src/core/hle/service/sockets/encore_guest_network_policy.h"
assert native_offline in graph and shipping_online in graph
assert (active / shipping_online).read_text().count(
    "inline constexpr bool kGuestNetworkOffline = false;") == 1
assert (active / native_offline).read_text().count(
    "inline constexpr bool kGuestNetworkOffline = true;") == 1
assert '${EDEN_NATIVE_DIRTY_HEADER_ROOT}/core/hle/service/sockets/encore_guest_network_policy.h' in native_cmake
assert 'target_include_directories(core BEFORE PUBLIC "${EDEN_NATIVE_DIRTY_HEADER_ROOT}")' in native_cmake
for consumer in ("sockets/bsd.cpp", "sockets/sfdnsres.cpp", "nifm/nifm.cpp"):
    body = (active / "eden-backports/src/core/hle/service" / consumer).read_text()
    assert 'Eden::Encore::kGuestNetworkOffline' in body, ("guest network policy not used", consumer)
print("ENCORE_NATIVE_GUEST_NETWORK_POLICY_PASS consumers=3")

# Native RADV is installed from exactly twelve versioned inputs,
# including an OpenCL geometry shader that the C/C++ scanner once omitted.
installer_inputs = runpy.run_path(str(root / "tools/install-vendored-radv.py"))["PATHS"]
mesa_inputs = {"ps5-mesa/" + path for path in installer_inputs}
mesa_physical = {path for path in physical if path.startswith("ps5-mesa/")}
assert len(mesa_inputs) == 12 and mesa_inputs == mesa_physical
assert all(path in graph for path in mesa_inputs), (
    "missing RADV source owner", sorted(path for path in mesa_inputs if path not in graph))
assert "ps5-mesa/src/amd/vulkan/cl/radv_gs_compute.cl" in mesa_inputs
print("ENCORE_DRIVER_INPUT_COVERAGE_PASS", f"inputs={len(mesa_inputs)}", "opencl=1")

# Patch-hunk owners in the versioned production backports; this checks
# known modified code sites, not the final runtime branch or GPU correctness.
modified_shipping = (
    ("eden-backports/src/core/device_memory_manager.h", ["std::shared_lock registry_lk(process_registry_guard);","AtomicLoadPhysical"]),
    ("eden-backports/src/core/device_memory_manager.inc", ["std::unique_lock lk(mapping_guard);","AtomicStoreReverse"]),
    ("eden-backports/src/core/memory.cpp", ["IsDirectBackingAlias","AddressSpaceContains"]),
    ("eden-backports/src/core/hle/kernel/k_scheduler.cpp", ["m_context_guard.try_lock()"]),
    ("eden-backports/src/core/hle/kernel/k_thread.h", ["std::mutex m_context_guard{};"]),
    ("eden-backports/src/core/hle/service/nvdrv/devices/nvmap.cpp", ["EDEN_NVMAP_REJECT_ZERO_ADDRESS","LockForMapDeviceAddressSpace"]),
    ("eden-backports/src/core/hle/service/nvnflinger/buffer_queue_core.cpp", ["dequeue_epoch.fetch_add","dequeue_epoch.load"]),
    ("eden-backports/src/core/hle/service/nvnflinger/buffer_queue_core.h", ["dequeue_epoch"]),
    ("eden-backports/src/core/hle/service/sockets/sfdnsres.cpp", ["kGuestNetworkOffline"]),
    ("eden-backports/src/video_core/renderer_vulkan/vk_buffer_cache.cpp", ["return scheduler.CurrentTick();"]),
    ("eden-backports/src/video_core/buffer_cache/buffer_cache.h", ["SynchronizeBufferWrites","gpu_modified_ranges"]),
    ("eden-backports/src/video_core/texture_cache/texture_cache.h", ["NULL_IMAGE_VIEW_ID","modification_tick == modification_tick"]),
)
for relative, anchors in modified_shipping:
    assert relative in graph and (active / relative).is_file(), (
        "missing function owner in production backport", relative)
    body = (active / relative).read_text()
    for anchor in anchors:
        assert anchor in body, ("shipping patch hunk moved", relative, anchor)
print("ENCORE_SHIPPING_BACKPORT_HOTPATH_OWNER_PASS", f"paths={len(modified_shipping)}")

# Source-owner proofs for eight additional production cache/fence/compute
# backports: changed marker appears once in shipping and not in pinned Eden.
gpu_shipping_diffs = (
    ("src/video_core/buffer_cache/buffer_cache_base.h", "void SynchronizeBufferWrites(Buffer& buffer);"),
    ("src/video_core/texture_cache/texture_cache_base.h", "std::vector<ImageViewId> last_feedback_view_ids;"),
    ("src/video_core/query_cache/query_cache.h", "!Settings::IsGPUFenceBehaviorBalanced() && !Settings::IsGPUFenceBehaviorAccurate()) && is_fence;"),
    ("src/video_core/fence_manager.h", "Settings::IsGPUFenceBehaviorBalanced() || Settings::IsGPUFenceBehaviorAccurate();"),
    ("src/video_core/control/channel_state_cache.h", "P* channel_state = nullptr;"),
    ("src/video_core/engines/kepler_compute.cpp", "if (data.was_dirty || source_dirty) {"),
    ("src/video_core/engines/kepler_compute.h", "bool upload_dirty{};"),
    ("src/video_core/dma_pusher.cpp", "const bool kepler_payload = engine == Engines::EngineTypes::KeplerCompute"),
)
for rel, marker in gpu_shipping_diffs:
    shipping = "eden-backports/" + rel
    assert shipping in graph, ("missing backport graph row", shipping)
    patched = (active / shipping).read_text()
    pinned = (root / "vendor/sources/eden" / rel).read_text()
    assert patched.count(marker) == 1 and marker not in pinned, (
        "production GPU backport drift", shipping, marker)
print("ENCORE_GPU_SHIPPING_PATCH_OWNER_PASS", f"sources={len(gpu_shipping_diffs)}")

# Indexed shipping sources have stable code anchors from their real
# patches, not simply a filename in the compiled-source inventory.
shipping_followups = (
    ("eden-backports/src/audio_core/audio_render_manager.cpp", ["ASSERT(session_count <= session_ids.size());","s32 Manager::GetSessionId()"]),
    ("eden-backports/src/core/hle/service/sockets/bsd.cpp", ["void BSD_USA::Ioctl(","Eden::Encore::kGuestNetworkOffline","write_buffer.size() < guest_addrin.len"]),
    ("eden-backports/src/core/hle/service/sockets/bsd.h", ["void Ioctl(HLERequestContext& ctx);"]),
    ("eden-backports/src/core/hle/service/nifm/nifm.cpp", ["Eden::Encore::kGuestNetworkOffline","void IGeneralService::SetWirelessCommunicationEnabled(","void IGeneralService::IsAnyInternetRequestAccepted("]),
    ("eden-backports/src/hid_core/resources/npad/npad.cpp", ["fullkey_lifo.ReadCurrentEntry().state.sampling_number","eden_watchdog_updates","EDEN_HID_NPAD"]),
    ("eden-backports/src/video_core/texture_cache/util.cpp", ["config.format == static_cast<Tegra::Texture::TextureFormat>(0)","if (config.is_sparse == 0)"]),
)
for relative, anchors in shipping_followups:
    assert relative in graph and (active / relative).is_file(), ("unindexed shipping source", relative)
    body = (active / relative).read_text()
    for anchor in anchors:
        assert anchor in body, ("shipping implementation changed", relative, anchor)
print("ENCORE_SHIPPING_NET_AUDIO_HID_TEXTURE_OWNER_PASS", f"files={len(shipping_followups)}")

# Modified shipping firmware, filesystem, applet and display contracts.
# Passing here asserts exact owner/hunk presence, not device runtime behavior.
shipping_hle_followups = (
    ("eden-backports/src/core/file_sys/system_archive/system_version.cpp", ["VirtualDir SystemVersion()","HLE::ApiVersion::VERSION_DIGEST[0]"]),
    ("eden-backports/src/core/hle/service/filesystem/filesystem.cpp", ["RegisterNamedService(\"fsp-srv\", std::move(FileSystemProxyFactory), 61);"]),
    ("eden-backports/src/core/hle/service/filesystem/fsp/fsp_srv.cpp", ["Result FSP_SRV::OpenDataFileSystemByCurrentProcess(","FileSys::ExtractRomFS(romfs)"]),
    ("eden-backports/src/core/hle/service/am/service/application_creator.cpp", ["IApplicationCreator::CreateSystemApplication(","HLE::ApiVersion::HOS_VERSION_MAJOR"]),
    ("eden-backports/src/core/hle/service/ns/application_manager_interface.cpp", ["IApplicationManagerInterface::Unknown936(","IApplicationManagerInterface::Unknown4042(","IApplicationManagerInterface::Unknown4105("]),
    ("eden-backports/src/core/hle/service/set/settings.cpp", ["RegisterNamedService(\"set:sys\", std::make_shared<ISystemSettingsServer>(system), 60);"]),
    ("eden-backports/src/core/frontend/applets/controller.cpp", ["DefaultControllerApplet::ReconfigureControllers(","keep_connected","max_supported_players"]),
    ("eden-backports/src/core/hle/service/am/display_layer_manager.cpp", ["DisplayLayerManager::CreateManagedDisplayLayer(","SetLayerStackMask(","SetLayerZIndex(Overlay"]),
)
for rel, anchors in shipping_hle_followups:
    assert rel in graph and (active / rel).is_file(), ("uncatalogued HLE source", rel)
    text = (active / rel).read_text()
    for anchor in anchors:
        assert anchor in text, ("firmware/HLE backport source drift", rel, anchor)
print("ENCORE_SHIPPING_FIRMWARE_HLE_OWNER_PASS", f"files={len(shipping_hle_followups)}")


# Strict ownership of shipping firmware, account, kernel, filesystem and
# Vulkan hunks. Pinned comparisons show a real shipped delta, not a new
# override to copy into CMake; this is not native hardware validation.
shipping_structural_diffs = (
    ("src/core/hle/api_version.h", "constexpr u8 HOS_VERSION_MAJOR = 23;"),
    ("src/core/hle/kernel/k_slab_heap.h", "std::mutex m_lock;"),
    ("src/core/hle/kernel/svc/svc_info.cpp", "case InfoType::Unknown37:"),
    ("src/core/hle/kernel/svc_types.h", "TransferMemoryHint = 34,"),
    ("src/core/hle/service/acc/acc.cpp", "void Module::Interface::LoadOpenContext(HLERequestContext& ctx) {"),
    ("src/core/hle/service/acc/acc.h", "void LoadOpenContext(HLERequestContext& ctx);"),
    ("src/core/hle/service/am/lifecycle_manager.h", "void RequestFocusStateChangedNotification(Kernel::KernelCore& kernel) {"),
    ("src/core/hle/service/filesystem/fsp/fsp_srv.h", "Result OpenDataFileSystemByCurrentProcess(OutInterface<IFileSystem> out_interface);"),
    ("src/core/hle/service/ns/application_manager_interface.h", "Result Unknown4042(OutInterface<IAsyncResult> out_interface,"),
    ("src/video_core/renderer_vulkan/vk_buffer_cache.h", "bool IsFree(u64 tick);"),
)
for rel, marker in shipping_structural_diffs:
    shipping_path = active / "eden-backports" / rel
    pinned_path = root / "vendor/sources/eden" / rel
    assert ("eden-backports/" + rel) in graph
    assert shipping_path.is_file() and pinned_path.is_file(), ("missing pinned comparison", rel)
    assert shipping_path.read_text().count(marker) == 1, ("shipping hunk drift", rel, marker)
    assert marker not in pinned_path.read_text(), ("hunk not distinct from pinned source", rel, marker)
print("ENCORE_SHIPPING_STRUCTURAL_OWNER_PASS", f"paths={len(shipping_structural_diffs)}")

shipping_new_ns = (
    ("src/core/hle/service/ns/i_async_result.cpp", "Result IAsyncResult::Cancel() {"),
    ("src/core/hle/service/ns/i_async_result.h", "class IAsyncResult final : public ServiceFramework<IAsyncResult> {"),
)
for rel, marker in shipping_new_ns:
    assert ("eden-backports/" + rel) in graph
    assert (active / "eden-backports" / rel).read_text().count(marker) == 1
    assert not (root / "vendor/sources/eden" / rel).exists(), ("new NS source exists upstream", rel)
print("ENCORE_SHIPPING_NEW_NS_OWNER_PASS", f"paths={len(shipping_new_ns)}")


# Previously unowned shipping backports: confirm a real delta against the
# pinned core, not merely an exact filename in a catalogue. Runtime behavior
# and selected build targets still require independent validation.
shipping_remaining_diffs = (
    ("src/common/logging.cpp", "extern \"C\" bool eden_native_detailed_logging() noexcept;", True),
    ("src/common/net/net.cpp", "const std::size_t timeout_seconds = url == \"https://api.nlib.cc\" ? 3 : 5;", True),
    ("src/common/settings.cpp", "bool IsGPUFenceBehaviorStrict() {", False),
    ("src/common/settings.h", "GpuFenceBehavior::Accurate,", True),
    ("src/common/settings_enums.h", "ENUM(GpuFenceBehavior, Default, Immediate, Balanced, Accurate);", True),
    ("src/core/hle/service/audio/audio.cpp", "server_manager->RegisterNamedService(\"aud:a\", std::make_shared<IAudioSystemManagerForApplet>(system), 30);", True),
    ("src/video_core/engines/sw_blitter/blitter.cpp", "(static_cast<size_t>(in_y) * src_width + static_cast<size_t>(in_x)) *", True),
    ("src/core/hle/service/am/frontend/applets.cpp", "std::erase(caller_applet->child_applets, applet_);", True),
    ("src/core/hle/service/am/service/library_applet_accessor.cpp", "else if (is_front_app) caller_applet->lifecycle_manager.RequestFocusStateChangedNotification(system.Kernel());", True),
    ("src/core/hle/service/am/service/library_applet_creator.cpp", "auto process = CreateProcess(system, program_id, 1, HLE::ApiVersion::HOS_VERSION_MAJOR);", True),
    ("src/core/hle/service/am/service/self_controller.cpp", "Result ISelfController::Unknown240(u32 in_val) {", True),
    ("src/core/hle/service/am/service/self_controller.h", "Result Unknown240(u32 in_val);", True),
    ("src/core/hle/service/bcat/bcat.cpp", "server_manager->RegisterNamedService(\"bcat:a\", std::make_shared<IServiceCreator>(system, \"bcat:a\"), 32);", True),
    ("src/core/hle/service/bpc/bpc.cpp", "server_manager->RegisterNamedService(\"bpc:ams\", std::make_shared<BPC_AMS>(system), 4);", True),
    ("src/core/hle/service/glue/arp.cpp", "LOG_ERROR(Service_ARP, \"Attempted to issue registrar, but registrar is already issued!\");", True),
    ("src/core/hle/service/glue/glue.cpp", "server_manager->RegisterNamedService(\"arp:r\", std::make_shared<ARP_R>(system, system.GetARPManager()), 16);", True),
    ("src/core/hle/service/grc/grc.cpp", "server_manager->RegisterNamedService(\"grc:c\", std::make_shared<GRC>(system), 4);", True),
    ("src/core/hle/service/hid/hid_system_server.cpp", '{551, &IHidSystemServer::GetRegisteredDevices, "GetRegisteredDevicesForControllerSupport"}', True),
    ("src/core/hle/service/ldr/ldr.cpp", "server_manager->RegisterNamedService(\"ldr:dmnt\", std::make_shared<DebugMonitor>(system), 3);", True),
    ("src/core/hle/service/nfp/nfp.cpp", "{25, &IUser::StartDetection, \"StartDetectionWithFilter\"},", True),
    ("src/core/hle/service/ngc/ngc.cpp", "server_manager->RegisterNamedService(\"ngct:u\", std::make_shared<IService>(system), 4);", True),
    ("src/core/hle/service/ns/ns.cpp", "server_manager->RegisterNamedService(\"ns:am2\", std::make_shared<IServiceGetterInterface>(system, \"ns:am2\"), 5);", True),
    ("src/core/hle/service/ns/read_only_application_control_data_interface.cpp", '{23, D<&IReadOnlyApplicationControlDataInterface::GetApplicationControlData3>, "GetApplicationControlData"}', True),
    ("src/core/hle/service/olsc/transfer_task_list_controller.cpp", "Result ITransferTaskListController::GetTransferTaskProgress() {", True),
    ("src/core/hle/service/olsc/transfer_task_list_controller.h", "Result GetTransferTaskProgress();", True),
    ("src/core/hle/service/pctl/parental_control_service.cpp", "Result IParentalControlService::Unknown1460(u8 in_unk, Out<PlayTimerRemainingTimeDisplayInfo> out_display_info) {", True),
    ("src/core/hle/service/pctl/parental_control_service.h", "Result Unknown1460(u8 in_unk, Out<PlayTimerRemainingTimeDisplayInfo> out_display_info);", True),
    ("src/core/hle/service/pctl/pctl_types.h", "struct PlayTimerRemainingTimeDisplayInfo {", True),
    ("src/core/hle/service/pm/pm.cpp", "server_manager->RegisterNamedService(\"pm:bm\", std::make_shared<BootMode>(system), 4);", True),
    ("src/core/hle/service/ro/ro.cpp", "server_manager->RegisterNamedService(\"ro:1\", std::make_shared<RoInterface>(system, \"ro:1\", ro, NrrKind::JitPlugin), 2);", True),
    ("src/core/hle/service/sm/sm.cpp", "Result ServiceManager::RegisterService(Kernel::KServerPort** out_server_port, std::string name, u32 max_sessions, SessionRequestHandlerFactory handler) {", True),
    ("src/core/hle/service/sockets/sockets.cpp", "server_manager->RegisterNamedService(\"bsd:s\", std::make_shared<BSD_USA>(system, \"bsd:s\", false), 0x7E);", True),
    ("src/core/hle/service/usb/usb.cpp", "server_manager->RegisterNamedService(\"usb:pd\", std::make_shared<IPdManager>(system), 6);", True),
    ("src/core/hle/service/wlan/wlan.cpp", "server_manager->RegisterNamedService(\"wlan:lcl\", std::make_shared<ILocalManager>(system), 10);", True),
)
for relative, marker, positive in shipping_remaining_diffs:
    relative_active = "eden-backports/" + relative
    shipping_path = active / relative_active
    pinned_path = root / "vendor/sources/eden" / relative
    assert relative_active in graph and shipping_path.is_file() and pinned_path.is_file()
    shipping_body, pinned_body = shipping_path.read_text(), pinned_path.read_text()
    if positive:
        assert shipping_body.count(marker) == 1 and marker not in pinned_body, (
            "shipping marker drifted", relative_active, marker)
    else:
        assert marker not in shipping_body and pinned_body.count(marker) == 1, (
            "removed shipping marker drifted", relative_active, marker)
print("ENCORE_SHIPPING_COMPLETE_OWNER_PASS", f"paths={len(shipping_remaining_diffs)}")

assert len(physical) == len(set(physical))
print("ENCORE_ACTIVE_SOURCE_CATALOG_PASS",
      f"files={len(physical)}",
      f"graph_exact={sum(path in graph for path in physical)}",
      f"unlinked={sum(path not in graph for path in physical)}",
      f"shipping_sources={len(shipping_cpp)}",
      f"shipping_build_recipes={len(build_recipes)}")
