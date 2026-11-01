#!/usr/bin/env python3
"""Prevent exploratory kernel/JIT backports from silently entering shipping builds."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
script = (root / "tools/apply-eden-backports.sh").read_text()
# The active source materializer, not test-only environment variables, owns
# the previously optional I-cache and service-manager patches.
import json
active = (root / "tools/install-active-core-backports.py").read_text()
prepare = (root / "tools/prepare-build.sh").read_text()
manifest = json.loads((root / "vendor/encore-active/eden-backports/manifest.json").read_text())
assert manifest["excluded_experimental"] == ["EDEN_EXPERIMENTAL_DUMMY_THREAD_WAITS"]
assert 'python3 -B tools/install-active-core-backports.py "$eden" --repair-owned-cache' in prepare
assert 'KNOWN_STALE_A64_SHA256 = "08ae577aa069b589faaa8cc6659baa66c80661d78abc15381907d63b343c17b0"' in active
assert "preserve_known_owned_cache_source(destination, target, sha(current))" in active
assert 'python3 -B tools/install-active-core-backports.py "$eden" --check' in prepare
for patch in ("eden-dynarmic-icache-coherence.patch", "eden-sm-host-wait.patch"):
    assert patch in active
    assert 'apply_one "$root/headless/backports/' + patch + '"' not in script
for flag in ("EDEN_EXPERIMENTAL_ICACHE_COHERENCE", "EDEN_EXPERIMENTAL_SM_HOST_WAIT"):
    assert flag not in prepare
    assert flag not in script
# Known dangling wait-queue pointers remain unsafe: the dummy-thread patch
# must not silently enter the active core. Preserve the sole quarantine.
flag = "EDEN_EXPERIMENTAL_DUMMY_THREAD_WAITS"
condition = "if [[ ${" + flag + ":-OFF} == ON ]]; then"
start = script.index(condition)
stop = script.index("\nfi", start)
assert "eden-dummy-thread-waits.patch" in script[start:stop]
assert script.count('apply_one "$root/headless/backports/eden-dummy-thread-waits.patch"') == 1

# R307: the #4473/#4477 cache/fence fixes are already in the pinned
# backport replay. Do not stage a second derived buffer-cache header or
# duplicate Kepler/DMA implementation in the native Vulkan build.
native_cmake = (root / "headless/CMakeLists.txt").read_text()
gpu_patch = root / "headless/backports/eden-4473-4477.patch"
assert gpu_patch.is_file() and "gpu_modified_ranges.ForEachInRange" in gpu_patch.read_text()
assert script.count('apply_one "$root/headless/backports/eden-4473-4477.patch"') == 1
assert (root / "headless/eden-buffer-4473.cmake").exists() is False
assert "eden-buffer-4473.cmake" not in native_cmake
assert "eden4473/dma_pusher.cpp" not in native_cmake
assert "gpu-memory-4473" not in native_cmake
assert "apply-upstream-4473.py" not in native_cmake
assert "Prepared Eden source lacks #4473/#4477" in native_cmake
assert "Eden #4473/#4477 are already applied once" in native_cmake
print("PASS R307: one authoritative audited Eden #4473/#4477 patch, no double Vulkan overlay")
print("PASS active I-cache and SM backports, quarantined dummy wait remains excluded")
