#!/usr/bin/env python3
"""N51 vendor-native GPU PTE range batching, exact source baseline parity."""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[2]
OWNER = ROOT / "vendor/encore-active/eden-core/src/video_core/memory_manager.cpp"
HELPER = ROOT / "vendor/encore-active/ns2-helpers/include/video_core/ns2_egl_gpu_range_batch.h"
CMAKE = (ROOT / "headless/CMakeLists.txt").read_text()

def blob(t: str) -> str:
    b = t.encode()
    return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()

def once(t: str, old: str, new: str) -> str:
    assert t.count(old) == 1, ("N51 native PS5 source-owner drift", old[:72])
    return t.replace(old, new)

t = OWNER.read_text()
# N51 shares the canonical GPU memory owner with P1.2 (cross-page scalar
# accesses and physical-backing continuity). Keep an *exact* allowlist of
# independently reviewed owner blobs: the original N51 integration and its
# P1.2-protected successor. Never fall back to a substring-only audit.
source_blob = blob(t)
n51_original = "c7923dbbef27a9088dbfcb33c162e3c7069679c1"
p12_protected = "7dba34b3e300515cd5b0a8579fe893072cb70b24"
# Source-level diff reviewed 2026-11-03: this complete owner additionally
# bounds GPU unmap, sparse walkers and 40/49-bit VA probes. The paging tests
# compile real owner-derived C++ in O0/O2 under UBSan; keep exact blob pinning.
p12_bounded = "b5caf9fa5b0477b005249d4b87bac89934bf4c50"
assert source_blob in (n51_original, p12_protected, p12_bounded), (
    "N51 GPU owner source drift (review before changing baseline)", source_blob)
if source_blob in (p12_protected, p12_bounded):
    assert '#include "native_paged_scalar.h"' in t
    assert "Eden::GpuScalar::Read(addr, value" in t
    assert "Eden::GpuScalar::Write(addr, data" in t
    assert t.count("memory.GetSpan(dev_addr_base, copy_amount)") == 4
    assert "memory.ReadBlockUnsafe(dev_addr_base, dest_buffer, copy_amount)" in t
    assert "memory.WriteBlockUnsafe(dev_addr_base, src_buffer, copy_amount)" in t
assert HELPER.is_file() and "class ChangedPageRuns" in HELPER.read_text()
# P1.2 introduced a scalar safety include between the canonical header
# and the N51 opt-in block. Remove only N51, never the P1.2 include.
owner_header = '#include "video_core/memory_manager.h"\n'
if source_blob in (p12_protected, p12_bounded):
    owner_header += '#include "native_paged_scalar.h"\n'
t = once(t,
    owner_header + '#ifdef EDEN_NS2_GPU_RANGE_BATCH\n'
    '#include "video_core/ns2_egl_gpu_range_batch.h"\n#endif',
    owner_header.rstrip("\n"))
for page in ("page_size", "big_page_size"):
    init = (
        "#ifdef EDEN_NS2_GPU_RANGE_BATCH\n"
        "    // Coalesce only adjacent changed PTE pages; preserve unchanged holes.\n"
        f"    Eden::NS2::GpuMemory::ChangedPageRuns changed_runs({page});\n"
        "    const auto notify_changed = [this](GPUVAddr address, u64 length) {\n"
        "        rasterizer->ModifyGPUMemory(unique_identifier, address, length);\n"
        "    };\n"
        "#endif\n")
    t = once(t, init, "")
    old = (
        "        if (current_entry_type != entry_type) {\n"
        f"            rasterizer->ModifyGPUMemory(unique_identifier, current_gpu_addr, {page});\n"
        "        }")
    altered = (
        "#ifdef EDEN_NS2_GPU_RANGE_BATCH\n"
        "        changed_runs.Record(current_gpu_addr, current_entry_type != entry_type,\n"
        "                            notify_changed);\n"
        "#else\n"+old+"\n#endif")
    t = once(t, altered, old)
flush = "#ifdef EDEN_NS2_GPU_RANGE_BATCH\n    changed_runs.Flush(notify_changed);\n#endif\n"
assert t.count(flush) == 2
t = t.replace(flush, "")
# The legacy baseline after removing N51 stays byte-for-byte unchanged.
# For the protected successor the exact pre-removal owner blob above, plus
# single-occurrence N51 rewrites, prevents unrelated edits from being hidden.
if source_blob == n51_original:
    assert blob(t) == "f30099dfb5df01d9cd787d199e3e61f28205669a", "N51 changed unrelated PS5 GPU logic"
else:
    assert "EDEN_NS2_GPU_RANGE_BATCH" not in t

if source_blob == p12_bounded:
    # Unlike an allowlist update alone, prove that each new range guard is
    # present before the corresponding guest GPU page-table walk.
    assert "size == 0 || addr >= address_space_size ||" in OWNER.read_text()
    assert "size == 0 || gpu_addr >= address_space_size ||" in OWNER.read_text()
    assert "size == 0 || src_addr >= address_space_size ||" in OWNER.read_text()
    assert "size > address_space_size -" in OWNER.read_text()
    assert "const size_t page_last{((addr + size - 1) >> page_bits) + 1};" in OWNER.read_text()

assert "EDEN_NS2_GPU_RANGE_BATCH_EXPERIMENTAL OR" in CMAKE
assert "EDEN_NS2_GPU_RANGE_BATCH=1" in CMAKE
assert "EDEN_FINAL_RELEASE_PROFILE" in CMAKE
assert "headless/ns2/eglantine/video_core/memory_manager.cpp" not in CMAKE
print("N51_NATIVE_GPU_SINGLE_VENDOR_OWNER_AND_F07_BASELINE_PASS")
