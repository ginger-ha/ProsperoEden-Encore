#!/usr/bin/env python3
"""Count Encore-owned files not yet handled in the optimization work pass.

Fast-skip previously maintained sources with a specific historical proof, but
never confuse code triage with host or console performance validation.
"""
import json
import hashlib
import subprocess
from collections import Counter
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/"docs/EDEN_OPTIMIZATION_COVERAGE_2026-10-20.json"
STATE=json.loads(P.read_text())
assert STATE["schema_version"]==1
tracked=set(subprocess.check_output(["git","ls-files","-z"],cwd=ROOT).decode().split("\0"))-{""}
# When vendor is moved to an immutable gitlink, the parent index lists only
# "vendor". Preserve the original vendor/… owner namespace by merging the
# pinned submodule index; never infer source ownership from arbitrary disk files.
if "vendor" in tracked:
    vendor_paths = subprocess.check_output(
        ["git", "-C", "vendor", "ls-files", "-z"], cwd=ROOT
    ).decode().split("\0")
    tracked.update("vendor/" + p for p in vendor_paths if p)

suffixes={".c",".cpp",".cxx",".cc",".h",".hpp",".inc"}
all_owners={p for p in tracked
        if p.startswith(("headless/","src/","vendor/encore-active/"))
        and Path(p).suffix in suffixes}
# NS2 is an explicitly unqualified research layer, not historical F07 review.
# Do not silently count new research source code as already optimized.
research = json.loads((ROOT/"docs/NS2_RESEARCH_ADDED_SOURCE_OWNERS.json").read_text())
research_owners={"vendor/encore-active/"+p for p in research["paths"]}
assert research["schema_version"] == 1 and len(research_owners) == 120
assert research_owners <= all_owners, sorted(research_owners-all_owners)
# The two new shared warning-hygiene headers have a separate exact-source
# verifier and installer. They are not retroactive F07 optimization reviews.
hygiene_owners = {
    "vendor/encore-active/eden-header-hygiene/include/common/page_table.h",
    "vendor/encore-active/eden-header-hygiene/include/video_core/macro.h",
}
assert hygiene_owners <= all_owners, sorted(hygiene_owners - all_owners)
assert "tools/install-eden-header-hygiene.py" in tracked
# The four mainline extracted AOC owners are explicitly reviewed in the
# post-snapshot F07 source ledger. Do not silently drop their proof entries
# or misclassify them as opt-in NS2 experiments.
extracted_aoc_owners = {
    "vendor/encore-active/eden-core/src/core/file_sys/extracted_aoc.h",
    "vendor/encore-active/eden-core/src/core/file_sys/extracted_aoc_paths.h",
    "vendor/encore-active/eden-core/src/core/file_sys/romfs_factory.cpp",
    "vendor/encore-active/eden-core/src/core/hle/service/aoc/addon_content_manager.cpp",
}
assert extracted_aoc_owners <= all_owners, sorted(extracted_aoc_owners - all_owners)
assert not extracted_aoc_owners & (research_owners | hygiene_owners)
# New NS2 kernel/process owners are selected only by the one reviewed PS5
# release profile. They postdate the frozen F07 518-source optimization audit
# and must remain independently visible, not mislabeled as F07-complete.
ns2_shared_release_owners = {
    "vendor/encore-active/ns2-runtime/kernel/core/hle/kernel/k_address_space_info.cpp",
    "vendor/encore-active/ns2-runtime/kernel/core/hle/kernel/svc/svc_physical_memory.cpp",
    "vendor/encore-active/ns2-runtime/process/core/core.cpp",
}
assert ns2_shared_release_owners <= all_owners, sorted(ns2_shared_release_owners-all_owners)
assert not ns2_shared_release_owners & (research_owners | hygiene_owners | extracted_aoc_owners)
release_cmake = (ROOT / "headless/CMakeLists.txt").read_text()
assert 'set(EDEN_SHARED_NS2_KERNEL_HEAP ON)' in release_cmake
assert 'ns2-runtime/process/core/core.cpp' in release_cmake
print("NS2_SHARED_RELEASE_F07_ISOLATION_PASS", f"new_release_sources={len(ns2_shared_release_owners)}")
ns2_shared_audio_owners = {
    "vendor/encore-active/ns2-runtime/audio/core/hle/service/audio/audio.cpp",
    "vendor/encore-active/ns2-runtime/audio/core/hle/service/audio/nx2_audio_user_client.h",
    "vendor/encore-active/ns2-runtime/audio/core/hle/service/nx2_streamplay.h",
}
assert ns2_shared_audio_owners <= all_owners, sorted(ns2_shared_audio_owners-all_owners)
assert not ns2_shared_audio_owners & (research_owners | hygiene_owners | ns2_shared_release_owners)
assert 'set(EDEN_SHARED_NS2_AUDIO ON)' in release_cmake
print("NS2_SHARED_AUDIO_F07_ISOLATION_PASS", f"new_release_sources={len(ns2_shared_audio_owners)}")
ns2_shared_gpu_access_owners = {
    "vendor/encore-active/ns2-runtime/gpu_access_svc/core/hle/kernel/svc.cpp",
    "vendor/encore-active/ns2-runtime/gpu_access_svc/core/hle/kernel/ns2_gpu_memory_attribute.h",
    "vendor/encore-active/ns2-runtime/gpu_access_svc/core/hle/kernel/svc_types.h",
    "vendor/encore-active/ns2-runtime/gpu_access_svc/core/hle/kernel/k_memory_block.h",
}
assert ns2_shared_gpu_access_owners <= all_owners, sorted(ns2_shared_gpu_access_owners - all_owners)
assert not ns2_shared_gpu_access_owners & (research_owners | hygiene_owners | ns2_shared_release_owners | ns2_shared_audio_owners)
assert 'set(EDEN_SHARED_NS2_GPU_ACCESS_SVC ON)' in release_cmake
print("NS2_GPU_ACCESS_F07_ISOLATION_PASS", f"new_release_sources={len(ns2_shared_gpu_access_owners)}")
# The newly selected rasterizer header is a post-F07 NS2 Compute ABI owner.
# Assert its source and native-only guard rather than silently raising the
# frozen 518-source F07 optimization proof count.
post_f07_native_vulkan_owners = {
    "vendor/encore-active/eden-vulkan/include/video_core/renderer_vulkan/vk_rasterizer.h",
}
assert post_f07_native_vulkan_owners <= all_owners, sorted(post_f07_native_vulkan_owners-all_owners)
assert not post_f07_native_vulkan_owners & (
    research_owners | hygiene_owners | ns2_shared_release_owners |
    ns2_shared_audio_owners | ns2_shared_gpu_access_owners
)
native_rasterizer_header = (ROOT / next(iter(post_f07_native_vulkan_owners))).read_text()
assert native_rasterizer_header.count("DispatchNativeCompute(") == 1
assert "#if defined(PS5_NATIVE) && defined(EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL)" in native_rasterizer_header
assert "[[nodiscard]] bool DispatchNativeCompute(const Tegra::NativeComputeLaunch& launch) override;" in native_rasterizer_header
assert 'file(COPY "${EDEN_ACTIVE_VULKAN}/" DESTINATION "${PORT_BUILD_DIR}")' in (
    ROOT / "headless/vulkan.cmake"
).read_text()
print("NS2_POST_F07_VULKAN_ABI_ISOLATION_PASS", f"new_native_headers={len(post_f07_native_vulkan_owners)}")
# The shared Maxwell/Ampere Compute storage walker was added after F07.
# Preserve the immutable 518-owner audit and independently prove its owner.
post_f07_shared_compute_owners = {
    "vendor/encore-active/eden-vulkan/include/video_core/renderer_vulkan/vk_compute_storage_layout.h",
}
assert post_f07_shared_compute_owners <= all_owners, sorted(post_f07_shared_compute_owners-all_owners)
assert not post_f07_shared_compute_owners & (
    research_owners | hygiene_owners | ns2_shared_release_owners |
    ns2_shared_audio_owners | ns2_shared_gpu_access_owners |
    post_f07_native_vulkan_owners
)
shared_compute_header = (ROOT / next(iter(post_f07_shared_compute_owners))).read_text()
assert "namespace Vulkan::ComputeStorageLayout {" in shared_compute_header
assert "count > max_bindings - flattened" in shared_compute_header
assert "std::numeric_limits<std::uint32_t>::max()" in shared_compute_header
shared_compute_cpp = (ROOT / "vendor/encore-active/eden-vulkan/vk_compute_pipeline_cost.cpp").read_text()
assert '#include "video_core/renderer_vulkan/vk_compute_storage_layout.h"' in shared_compute_cpp
assert shared_compute_cpp.count("ComputeStorageLayout::ForEach(") == 3
assert "python3 -B tools/check-shared-compute-storage-descriptors-host.py" in (
    ROOT / ".github/workflows/encore-core-fast-gate.yml"
).read_text()
print("NS1_NS2_SHARED_COMPUTE_F07_ISOLATION_PASS", f"new_shared_headers={len(post_f07_shared_compute_owners)}")
# The launcher -> Vulkan RGBA mailbox is a new ordinary production header,
# not part of the immutable F07 518-owner optimization snapshot. Validate
# the real handoff and its independent host gate instead of inflating F07.
post_f07_launcher_handoff_owners = {"headless/launch_handoff.hpp"}
assert post_f07_launcher_handoff_owners <= all_owners
handoff_header = (ROOT / "headless/launch_handoff.hpp").read_text()
assert "namespace Eden::LaunchHandoff {" in handoff_header
assert "inline std::shared_ptr<const Frame> Peek()" in handoff_header
assert "std::exchange(pending_frame, {})" in handoff_header
assert "tools/check-ps5-vulkan-loading-stages-host.py" in tracked
assert not post_f07_launcher_handoff_owners & (
    research_owners | hygiene_owners | ns2_shared_release_owners |
    ns2_shared_audio_owners | ns2_shared_gpu_access_owners |
    post_f07_native_vulkan_owners | post_f07_shared_compute_owners
)
print("ENCORE_SHARED_LOADER_F07_ISOLATION_PASS",
      f"new_shipping_headers={len(post_f07_launcher_handoff_owners)}")
# This generated PS5/NS2-only typed cache ABI postdates the frozen F07
# 518-source optimization audit. Keep it visible and independently guarded,
# never reclassify it as previously optimized Switch 1 source code.
post_f07_ns2_typed_cache_owners = {
    "vendor/encore-active/eden-vulkan/vulkan-cache/video_core/texture_cache/texture_cache_base.h",
}
assert post_f07_ns2_typed_cache_owners <= all_owners, sorted(
    post_f07_ns2_typed_cache_owners-all_owners)
assert not post_f07_ns2_typed_cache_owners & (
    research_owners | hygiene_owners | ns2_shared_release_owners |
    ns2_shared_audio_owners | ns2_shared_gpu_access_owners |
    post_f07_native_vulkan_owners | post_f07_shared_compute_owners |
    post_f07_launcher_handoff_owners
)
cache_header = (ROOT / next(iter(post_f07_ns2_typed_cache_owners))).read_text()
assert "AcquireNativeImageView(" in cache_header
assert "NativeChannelMatches(" in cache_header
assert "AcquireNativeSampler(" in cache_header
assert "#if defined(PS5_NATIVE) && defined(EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL)" in cache_header
print("NS2_POST_F07_TYPED_CACHE_ABI_ISOLATION_PASS",
      f"new_native_headers={len(post_f07_ns2_typed_cache_owners)}")
# P1.2 shared GPU scalar fix is newer than the immutable F07 518 owners.
# Its exact native owner and Clang/GCC witness are tracked separately, not
# misclassified as a completed historical optimization or opt-in NS2 path.
post_f07_shared_gpu_scalar_owners = {
    "vendor/encore-active/eden-core/src/video_core/native_paged_scalar.h",
}
assert post_f07_shared_gpu_scalar_owners <= all_owners, sorted(
    post_f07_shared_gpu_scalar_owners - all_owners)
assert not post_f07_shared_gpu_scalar_owners & (
    research_owners | hygiene_owners | ns2_shared_release_owners |
    ns2_shared_audio_owners | ns2_shared_gpu_access_owners |
    post_f07_native_vulkan_owners | post_f07_shared_compute_owners |
    post_f07_launcher_handoff_owners | post_f07_ns2_typed_cache_owners
)
native_scalar_owner = (
    ROOT / "vendor/encore-active/eden-core/src/video_core/memory_manager.cpp"
).read_text()
assert '#include "native_paged_scalar.h"' in native_scalar_owner
assert "Eden::GpuScalar::Read(addr, value," in native_scalar_owner
assert "Eden::GpuScalar::Write(addr, data," in native_scalar_owner
assert "tools/ns2/check_paged_gpu_scalar_host.py" in tracked
assert "python3 -B tools/ns2/check_paged_gpu_scalar_host.py" in (
    ROOT / ".github/workflows/encore-core-preflight.yml").read_text()
print("NS1_NS2_SHARED_GPU_SCALAR_F07_ISOLATION_PASS",
      f"post_snapshot_reviewed={len(post_f07_shared_gpu_scalar_owners)}")
# NUP v1 parser/adapter/loader/router additions came after the frozen
# 518-path F07 optimization audit. Their native CMake gate is OFF by default,
# forbidden in the final profile, and has no PS5 runtime proof. Keep this
# exact staged-source inventory separate from historical optimized owners.
post_f07_nup_vfs_owners = {
    "headless/nup_v1_vfs.h",
    "headless/nup_v1_vfs.cpp",
    "headless/nup_v1_native_vfs.h",
    "headless/nup_v1_native_vfs.cpp",
    "headless/nup_v1_native_content.h",
    "headless/nup_v1_native_content.cpp",
    "headless/nup_v1_native_loader.h",
    "headless/nup_v1_native_loader.cpp",
    "headless/nup_v1_native_aoc.h",
    "headless/nup_v1_native_aoc.cpp",
    "headless/nup_v1_loader_route.cpp",
    "headless/nup_v1_romfs_factory.cpp",
    "headless/nup_v1_aoc_service.cpp",
}
assert post_f07_nup_vfs_owners <= all_owners, sorted(
    post_f07_nup_vfs_owners - all_owners)
assert not post_f07_nup_vfs_owners & (
    research_owners | hygiene_owners | ns2_shared_release_owners |
    ns2_shared_audio_owners | ns2_shared_gpu_access_owners |
    post_f07_native_vulkan_owners | post_f07_shared_compute_owners |
    post_f07_launcher_handoff_owners | post_f07_ns2_typed_cache_owners
)
# The native router is prepared but must remain *conditional*, never a
# default shipping source. The old "not in CMake at all" rule became stale
# when the explicit P5 gate was introduced.
# The active headless CMake entrypoint explicitly includes the isolated
# P5 NUP selector; test the actual included file, not stale inline CMake.
nup_include = 'include("${CMAKE_CURRENT_LIST_DIR}/nup_v1_runtime.cmake")'
assert release_cmake.count(nup_include) == 1
nup_select = (ROOT / "headless/nup_v1_runtime.cmake").read_text()
assert nup_select.count("option(EDEN_NUP_V1_RUNTIME") == 1
assert 'route verified NUP containers to shared loader" OFF)' in nup_select
assert nup_select.count("if(EDEN_NUP_V1_RUNTIME)") == 1
nup_gate = nup_select.split("if(EDEN_NUP_V1_RUNTIME)", 1)[1].split("\nendif()", 1)[0]
assert 'if(EDEN_FINAL_RELEASE_PROFILE)' in nup_gate
assert "NUP v1 P5 qualification is not yet allowed in a final release" in nup_gate
assert "target_sources(core PRIVATE" in nup_gate
for selected in (
    "nup_v1_vfs.cpp", "nup_v1_native_vfs.cpp",
    "nup_v1_native_content.cpp", "nup_v1_native_aoc.cpp",
    "nup_v1_native_loader.cpp", "nup_v1_loader_route.cpp",
):
    source_ref = '"${EDEN_PORT_DIR}/' + selected + '"'
    assert nup_gate.count(source_ref) == 1
    assert release_cmake.count(source_ref) == 0
# P5's two maintained-owner replacements are also post-F07, and must stay
# inside the same explicit gate. Replacing original source without a unique
# match fails at configure time; never treat the replacements as shipped.
for original, replacement in (
    ("file_sys/romfs_factory.cpp", "nup_v1_romfs_factory.cpp"),
    ("hle/service/aoc/addon_content_manager.cpp", "nup_v1_aoc_service.cpp"),
):
    pair = '"' + original + "|" + replacement + '"'
    assert nup_gate.count(pair) == 1
    assert replacement not in release_cmake
assert 'list(LENGTH eden_nup_matches eden_nup_match_count)' in nup_gate
assert 'if(NOT eden_nup_match_count EQUAL 1)' in nup_gate
assert 'set_property(TARGET core PROPERTY SOURCES "${eden_nup_runtime_sources}")' in nup_gate
assert (ROOT / "tools/check-nup-v1-runtime-cmake.py").is_file()
nup_core = (ROOT / "headless/nup_v1_vfs.h").read_text()
nup_adapter = (ROOT / "headless/nup_v1_native_vfs.h").read_text()
assert "Not wired into the PS5 loader or game catalogue." in nup_core
assert "Deliberately NOT registered" in nup_adapter
assert "AllowsVerifiedMemberCache() const override { return false; }" in (
    ROOT / "headless/nup_v1_native_vfs.cpp").read_text()
assert "Inactive native NUP content bridge" in (
    ROOT / "headless/nup_v1_native_content.h").read_text()
assert "INACTIVE NUP v1 application-loader adapter." in (
    ROOT / "headless/nup_v1_native_loader.h").read_text()
assert "NupAppLoader::Open(" in (
    ROOT / "headless/nup_v1_native_loader.cpp").read_text()
print("NUP_V1_POST_F07_OWNER_ISOLATION_PASS",
      f"not_retroactive_F07={len(post_f07_nup_vfs_owners)}",
      "shipping_selection=absent")

owners=all_owners-research_owners-hygiene_owners-ns2_shared_release_owners-ns2_shared_audio_owners-ns2_shared_gpu_access_owners-post_f07_native_vulkan_owners-post_f07_shared_compute_owners-post_f07_launcher_handoff_owners-post_f07_ns2_typed_cache_owners-post_f07_shared_gpu_scalar_owners-post_f07_nup_vfs_owners
print("ENCORE_EXTRACTED_AOC_F07_OWNER_PASS", f"post_snapshot_reviewed={len(extracted_aoc_owners)}")
assert len(owners)==518, ("F07 reviewed shipping source owner drift",len(owners))
assert "headless/ns2_title_catalog.h" in owners, "new NS2 title owner unaccounted for"
print("NS2_F07_TRIAGE_ISOLATION_PASS", f"unreviewed_research_sources={len(research_owners)}",
      "separate_shared_warning_headers=2")
entries=STATE["handled_paths"]
handled={e["path"] for e in entries}
assert len(entries)==len(handled),"duplicate optimization owner"
assert extracted_aoc_owners<=handled, ("AOC source review missing", sorted(extracted_aoc_owners-handled))
assert handled<=owners,sorted(handled-owners)
allowed={"code_changed_in_batch","reviewed_without_new_code_edit",
         "historical_host_contract_reviewed","previously_integrated_source_change",
         "shipping_backport_integrated_previously","historical_maintained_unit_parity","new_source_issue_corrected","historical_native_selected_unit",
         "preexisting_generated_or_inactive_unit","format_feature_source_integrated"}
assert all(e["disposition"] in allowed and e["evidence"] for e in entries)
audit=(ROOT/"docs/EDEN_CORE_AUDIT_DEPENDENCIES.md").read_text()
rows=audit.split("<!-- AUDIT_ROWS_START -->",1)[1].split("<!-- AUDIT_ROWS_END -->",1)[0]
by_id={}
for line in rows.splitlines():
    if not re.match(r"^\|\s*[A-Z]\d{2,3}\s*\|",line):
        continue
    cells=[v.strip() for v in line.strip().strip("|").split("|")]
    assert len(cells)==9
    assert cells[0] not in by_id
    by_id[cells[0]]=dict(path=cells[3],status=cells[5],evidence=cells[6])
for e in entries:
    if e["disposition"] not in {"historical_host_contract_reviewed",
                               "previously_integrated_source_change",
                               "shipping_backport_integrated_previously",
                               "historical_maintained_unit_parity","historical_native_selected_unit"}:
        continue
    cid=e["contract_id"]
    assert cid in by_id,("historical contract missing",cid)
    row=by_id[cid]
    assert row["path"]==e["path"]
    assert row["status"]==e["prior_status"]
    # Registry evidence can reference a source installer while the separate
    # host CI witness checks parity. Both references are kept when different.
    assert row["evidence"]==e.get("contract_evidence",e["proof_ref"])
    assert row["status"]==("HOST" if e["disposition"]=="historical_host_contract_reviewed"
                          else "SOURCE")
    assert e["path"].startswith("vendor/encore-active/")
    # A skipped *first code review* still leaves independent test/console debt.
    assert "PS5" not in e.get("claimed_performance","")
# Shipping backports are a code-modification fact, not a HOST label.
# Lock every fast-triaged source to its installed bytes, its immutable
# previous source digest, and the exact register owner (verified above).
shipping=json.loads((ROOT/"vendor/encore-active/eden-backports/manifest.json").read_text())
upstream=json.loads((ROOT/"UPSTREAM.json").read_text())
assert shipping["pinned_eden_commit"]==upstream["eden_commit"]
assert len(shipping["entries"])==83
for e in entries:
    if e["disposition"]!="shipping_backport_integrated_previously":
        continue
    assert e["path"]=="vendor/encore-active/eden-backports/"+e["shipping_relpath"]
    assert e["prior_status"]=="SOURCE"
    record=shipping["entries"][e["shipping_relpath"]]
    active=ROOT/e["path"]
    assert active.is_file()
    assert hashlib.sha256(active.read_bytes()).hexdigest()==record["active"]
    assert active.stat().st_size==record["bytes"]
    assert e["shipping_active_sha256"]==record["active"]
    assert e["shipping_upstream_sha256"]==record["upstream"]
    assert e["shipping_bytes"]==record["bytes"]
    assert record["active"]!=record["upstream"],("not a changed backport",e["path"])
assert sum(e["disposition"]=="shipping_backport_integrated_previously"
           for e in entries)==78
# A fast-skipped profile source must keep an exact original CI witness.
# Off/DEV/staged paths are NOT declared active runtime optimizations.
preflight=(ROOT/".github/workflows/encore-core-preflight.yml").read_text()
for e in entries:
    if e["disposition"]!="historical_maintained_unit_parity":
        continue
    assert e["prior_status"]=="SOURCE"
    assert e["profile_visibility"] in {"optional_or_staged","profile_dependent_or_selected"}
    assert e["proof_ref"].endswith(".py") and (ROOT/e["proof_ref"]).is_file()
    assert "python3 -B "+e["proof_ref"] in preflight,("not in CI",e["path"])
# Source fixes added after the first baseline are counted only with
# a current checked-in source and a CI-invoked, source-aware host witness.
for e in entries:
    if e["disposition"]!="new_source_issue_corrected":
        continue
    assert e["proof_ref"].endswith(".py") and (ROOT/e["proof_ref"]).is_file()
    assert "python3 -B "+e["proof_ref"] in preflight
    assert (ROOT/e["path"]).is_file()
# The NCZ/multi-format source owners added after the 493-source snapshot are
# maintained or test-only code, not proven F01-F06 performance optimizations.
# Pin their real blobs, reviewed source roles and native selection/witness.
format_roots = {
    "headless/game_files.h",
    "headless/ncz.cpp",
    "headless/ncz.h",
    "headless/ncz_check.cpp",
    "headless/ncz_vfs.h",
}
format_native = {
    "file_sys/card_image.cpp", "file_sys/registered_cache.cpp",
    "file_sys/submission_package.cpp", "loader/loader.cpp", "loader/nsp.cpp",
}
native_prefix = "vendor/encore-active/eden-core/src/core/"
format_paths = format_roots | {native_prefix + p for p in format_native}
format_entries = [e for e in entries if e["disposition"] == "format_feature_source_integrated"]
assert len(format_entries) == len(format_paths) == 10
assert {e["path"] for e in format_entries} == format_paths
format_review = ROOT / "docs/EDEN_FORMAT_SOURCE_REVIEW_2026-10-23.md"
review_text = format_review.read_text()
cmake_formats = (ROOT / "headless/CMakeLists.txt").read_text()
for e in format_entries:
    path = e["path"]
    assert e["proof_ref"] in {
        "tools/check-encore-ncz-sources.py",
        "tools/check-ncz.py",
        "tools/check-exefs-directory-host.py",
    }
    assert "python3 -B " + e["proof_ref"] in preflight
    assert e["feature_review_document"] == str(format_review.relative_to(ROOT))
    assert "| `" + path + "` | `" + e["reviewed_source_git_blob"] + "` |" in review_text, path
    if path.startswith(native_prefix):
        assert e["source_scope"] == "native_maintained"
        assert '"' + path.removeprefix(native_prefix) + '"' in cmake_formats, path
    elif path == "headless/ncz.cpp":
        assert e["source_scope"] == "native_adapter"
        assert 'list(APPEND core_sources "${EDEN_PORT_DIR}/ncz.cpp")' in cmake_formats
    elif path == "headless/ncz_check.cpp":
        assert e["source_scope"] == "host_test_only"
        assert e["proof_ref"] == "tools/check-ncz.py"
    else:
        assert e["source_scope"] == "header_only"
# New features can carry independent runtime/performance debt; this registry
# only records a reviewed integration, not performance measured on PS5.

# Verify every historical selected native unit against its actual selector.
# Optional/device support and console performance are not certified here.
radv_sel=(ROOT/"tools/install-vendored-radv.py").read_text()
vulkan_sel=(ROOT/"headless/vulkan.cmake").read_text()
surface_sel=(ROOT/"tools/install-vendored-surface-lifecycle.py").read_text()
for e in entries:
    if e["disposition"]!="historical_native_selected_unit": continue
    assert e["prior_status"]=="SOURCE"
    assert "python3 -B "+e["proof_ref"] in preflight
    assert (ROOT/e["proof_ref"]).is_file() and (ROOT/e["path"]).is_file()
    kind=e["source_selector"]
    if kind=="radv":
        assert e["path"].startswith("vendor/encore-active/ps5-mesa/")
        relative=e["path"].removeprefix("vendor/encore-active/ps5-mesa/")
        assert "'"+relative+"'" in radv_sel
    elif kind=="vulkan":
        assert e["path"].startswith("vendor/encore-active/eden-vulkan/")
        assert "file(COPY " in vulkan_sel and "EDEN_ACTIVE_VULKAN" in vulkan_sel
    elif kind=="surface":
        assert e["path"].endswith("src/core/hle/service/nvnflinger/surface_flinger.cpp")
        assert 'PATH = Path("src/core/hle/service/nvnflinger/surface_flinger.cpp")' in surface_sel
    else: raise AssertionError(("unknown source selector",kind))
assert sum(e["disposition"]=="historical_native_selected_unit" for e in entries)==20
# The native emulator optimization queue excludes the separately owned UI
# launcher. This is a presentation/scheduling filter, NEVER a claim that
# those source files are optimized or absent from the full inventory.
launcher_prefix=STATE.get("active_emulation_priority_excludes_launcher_prefix")
assert launcher_prefix=="headless/prosperoeden/"
pending_code=owners-handled
# One source in the launcher directory is linked into EVERY native app build:
# it defines global pthread_once/libc shims. Never dismiss it as UI-only.
shared=set(STATE.get("launcher_global_runtime_exceptions",[]))
assert shared=={"headless/prosperoeden/runtime_shims.cpp"}
# The shared runtime shim remains in the engine *classification* even after
# its code review is complete; it must not be forced to remain outstanding.
assert shared<=owners
cmake=(ROOT/"headless/CMakeLists.txt").read_text()
assert '"${launcher_dir}/runtime_shims.cpp"' in cmake
launcher_pending={p for p in pending_code if p.startswith(launcher_prefix) and p not in shared}
# Assert the runtime/launcher boundary against actual versioned paths.
assert len(pending_code)==len(launcher_pending)+len(pending_code-launcher_pending)
# New per-source review decisions must remain traceable to the exact
# current contract path and a real file entry in the written source review.
# A source reviewed as not needing a patch remains valid only for the
# identical Git blob. A changed header must trigger a fresh optimization triage.
for e in entries:
    if not e.get("reviewed_source_git_blob"):
        continue
    actual=subprocess.check_output(["git","hash-object",e["path"]],cwd=ROOT,text=True).strip()
    assert actual==e["reviewed_source_git_blob"],("source changed: repeat optimization review",e["path"])
for e in entries:
    if not e.get("source_review_document"):
        continue
    assert e["disposition"]=="reviewed_without_new_code_edit"
    # Some native startup shims, generated headers and standalone host test
    # executables are code owners without an ID in the *core* audit graph.
    # Keep their explicit review and unchanged Git blob rather than invent an ID.
    ident=e.get("contract_id")
    if ident is not None:
        assert ident in by_id and by_id[ident]["path"]==e["path"]
    else:
        assert e.get("review_scope") in {
            "host-only-test","startup-shim","shutdown-only",
            "generated-configuration","startup-interface","inactive-experimental",
            "runtime-abi-interface", "launcher-release-hotpath",
            "launcher-release-support",
        }
        assert e["path"] not in {r["path"] for r in by_id.values()}
        if e.get("review_scope") in {"launcher-release-hotpath","launcher-release-support"}:
            assert e["path"].startswith("headless/prosperoeden/")
            assert e.get("reviewed_source_git_blob") and e["source_review_document"].startswith(
                "docs/EDEN_RELEASE_LAUNCHER_SOURCE_OPTIMIZATION_AUDIT_")

    source_review=ROOT/e["source_review_document"]
    assert source_review.is_file()
    assert "| `"+e["path"]+"` |" in source_review.read_text(),e["path"]
    if e.get("proof_ref") and e.get("prior_status"):
        row=by_id[e["contract_id"]]
        assert row["status"]==e["prior_status"]
        assert row["evidence"]==e["proof_ref"]
        assert "python3 -B "+e["proof_ref"] in preflight
# Generated fragments and opt-in sources are not production runtime hot paths.
# They count as source-triaged, but never as FPS-optimized. Verify their
# original ownership and that every asserted witness still runs in CI.
vulkan_generator=(ROOT/"tools/prepare-vulkan-port.py").read_text()
for e in entries:
    if e["disposition"]!="preexisting_generated_or_inactive_unit": continue
    ident=e["contract_id"]
    assert ident in by_id and by_id[ident]["path"]==e["path"]
    assert by_id[ident]["status"]==e["prior_status"]=="SOURCE"
    assert by_id[ident]["evidence"]==e["proof_ref"]
    assert "python3 -B "+e["proof_ref"] in preflight
    assert (ROOT/e["path"]).is_file()
    kind=e["profile_visibility"]
    if kind=="vulkan_oracle_not_compiled":
        assert e["path"].startswith("vendor/encore-active/eden-vulkan-oracles/")
        basename=Path(e["path"]).name
        assert "(vulkan_oracle / '"+basename+"').read_text()" in vulkan_generator
    elif kind=="dynarmic_scalar_generator_fragment":
        assert e["contract_id"] in {"J28","J29"}
    elif kind=="maintained_standard_memory":
        assert e["contract_id"] in {"V97","V98"}
    elif kind=="opengl_dev_capture_fragment":
        assert e["contract_id"]=="V107"
    elif kind=="deferred_guest_bridge_off":
        assert e["contract_id"] in {"V89","V90","V91","V92","V93",
                                   "V94","V95","V96","V99"}
        bridge=(ROOT/"headless/guest_write_deferred_bridge.cmake").read_text()
        assert 'option(EDEN_GUEST_WRITE_BRIDGE_DEV "Compile inactive native deferred-write bridge" OFF)' in bridge
    else: raise AssertionError(("unexpected profile",kind))
assert sum(e["disposition"]=="preexisting_generated_or_inactive_unit"
           for e in entries)==19
status=Counter(e["disposition"] for e in entries)
# The baseline remains a dated historical inventory. New source owners must
# be explicit, traceable, present in the current tree and handled in the
# source-review ledger, rather than silently rewriting the snapshot count.
post_snapshot=set(STATE.get("post_snapshot_owned_additions", []))
assert len(post_snapshot)==len(STATE.get("post_snapshot_owned_additions", []))
assert post_snapshot<=owners, ("untracked post-snapshot source", sorted(post_snapshot-owners))
assert post_snapshot<=handled, ("post-snapshot source lacks review", sorted(post_snapshot-handled))
assert len(owners)==STATE["owned_code_count_at_snapshot"]+len(post_snapshot), (
    "source inventory changed", len(owners),
    STATE["owned_code_count_at_snapshot"],len(post_snapshot))
assert len(owners)==len(handled)+len(owners-handled)
print("EDEN_OPTIMIZATION_REVIEW_BACKLOG_PASS",
      "owned_code="+str(len(owners)),
      "handled="+str(len(handled)),
      "code_touched="+str(status["code_changed_in_batch"]),
      "source_reviewed="+str(status["reviewed_without_new_code_edit"]),
      "prior_host="+str(status["historical_host_contract_reviewed"]),
      "prior_source="+str(status["previously_integrated_source_change"]),
      "shipping_integrated="+str(status["shipping_backport_integrated_previously"]),
      "historical_maintained="+str(status["historical_maintained_unit_parity"]),
      "new_code_fixes="+str(status["new_source_issue_corrected"]),
      "format_feature_integrated_not_optimized="+str(status["format_feature_source_integrated"]),
      "native_selected="+str(status["historical_native_selected_unit"]),
      "preexisting_inactive_oracle="+str(status["preexisting_generated_or_inactive_unit"]),
      "remaining_emulator_to_optimize_review="+str(len(pending_code-launcher_pending)),
      "launcher_ui_pending_separate="+str(len(launcher_pending)),
      "all_component_triage_remaining="+str(len(owners-handled)),
      "new_code_fixes_required=UNKNOWN native_console_validation=SEPARATE")
