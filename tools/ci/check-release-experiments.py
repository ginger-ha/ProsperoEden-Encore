#!/usr/bin/env python3
"""Verify actual compiled native release experiments (never claim console FPS).

Run after build-package.sh release-stage, before release distribution uploads.
The marker strings in eboot.bin alone do not prove CMake conditionals are ON.
"""
from __future__ import annotations
import sys
import tempfile
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "build/headless-native/CMakeCache.txt"
RELEASE = ROOT / "build/release/PPSA99008"
REQUIRED = {
    "EDEN_PS5_VULKAN:BOOL": "ON",
    "EDEN_VULKAN_DRIVER:STRING": "RADV",
    "EDEN_FINAL_RELEASE_PROFILE:BOOL": "ON",
    "EDEN_GUEST_WRITE_BRIDGE_DEV:BOOL": "OFF",
    "EDEN_UNQUALIFIED_FERMI2D_COPY:BOOL": "OFF",
    "EDEN_PS5_OPENGL:BOOL": "ON",
    "EDEN_DEV_PROFILE:BOOL": "OFF",
    "EDEN_DEV_VULKAN:BOOL": "OFF",
    "EDEN_SHARED_JIT:BOOL": "OFF",
    "EDEN_JIT_COMPILE_BATCH:BOOL": "OFF",
    "EDEN_NUP_V1_RUNTIME:BOOL": "OFF",
}
# Sparse fallback diagnostics may be linked from maintained JIT source even
# when runtime sparse selection is OFF. Strings alone are not activation proof.
# The compiled CMakeCache policy is checked fail-closed below.
MARKERS = (
    b"EDEN_EXPERIMENT_DEFAULTS sparse=%u logical_cpu=%u frame_probe=%u safe=%u",
    b"EDEN_JIT_SPARSE_TRIM released=",
    b"EDEN_PS5_JIT_POLICY scope=all_titles",
    b"EDEN_GPU_REPORT_STALLED age_ms=",
)

def verify(cache: str, eboot: bytes) -> None:
    config = {}
    for line in cache.splitlines():
        if line and not line.startswith(("#", "//")) and "=" in line:
            k, v = line.split("=", 1)
            config[k] = v
    mismatches = [
        f"{k}={config.get(k)!r} (expected {want!r})"
        for k, want in REQUIRED.items() if config.get(k) != want
    ]
    # A new NS2 research switch must never evade release verification just
    # because it was added after this script's fixed REQUIRED list.
    for key, value in config.items():
        if re.fullmatch(r"EDEN_NS2_.*_EXPERIMENTAL:BOOL", key):
            if value not in ("OFF", "FALSE", "0"):
                mismatches.append(f"{key}={value!r} (expected 'OFF')")
    if mismatches:
        raise ValueError("release compile profile mismatch: " + ", ".join(mismatches))
    missing = [value.decode() for value in MARKERS if value not in eboot]
    if missing:
        raise ValueError("release binary lacks runtime markers: " + ", ".join(missing))

def self_test() -> None:
    valid = "\n".join(f"{k}={v}" for k, v in REQUIRED.items())
    eboot = b"".join(MARKERS)
    verify(valid, eboot)
    for key, value in REQUIRED.items():
        incorrect = valid.replace(f"{key}={value}", f"{key}=INVALID")
        try:
            verify(incorrect, eboot)
        except ValueError as exc:
            assert key in str(exc)
        else:
            raise AssertionError(f"unnoticed compiler flag mismatch: {key}")
    for injected in (
        "EDEN_NS2_FUTURE_UNREVIEWED_EXPERIMENTAL:BOOL=ON",
        "EDEN_NS2_METADATA_EXPERIMENTAL:BOOL=ON",
    ):
        try:
            verify(valid + "\n" + injected, eboot)
        except ValueError as exc:
            assert injected.split("=", 1)[0] in str(exc)
        else:
            raise AssertionError(f"unreviewed NS2 release selector accepted: {injected}")
    # A non-NS2 flag must not accidentally match the catch-all checker.
    verify(valid + "\nEDEN_UNRELATED_FEATURE:BOOL=ON", eboot)
    for marker in MARKERS:
        try:
            verify(valid, eboot.replace(marker, b""))
        except ValueError as exc:
            assert marker.decode() in str(exc)
        else:
            raise AssertionError(f"missing binary marker accepted: {marker!r}")
    print("PASS: one native final release profile, fail-closed experimental flags and markers")

def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        self_test()
        return 0
    if len(sys.argv) != 2:
        print("usage: check-release-experiments.py build/release/PPSA99008", file=sys.stderr)
        return 2
    app = Path(sys.argv[1]).resolve()
    if app != RELEASE.resolve():
        print(f"REJECTED: expected native release staging path {RELEASE}", file=sys.stderr)
        return 1
    try:
        if not CACHE.is_file() or not (app / "eboot.bin").is_file():
            raise ValueError("compiled CMake cache or staged native executable missing")
        verify(CACHE.read_text("utf-8"), (app / "eboot.bin").read_bytes())
    except (OSError, ValueError) as exc:
        print(f"EDEN_RELEASE_EXPERIMENTS_REJECTED: {exc}", file=sys.stderr)
        return 1
    print("EDEN_RELEASE_EXPERIMENTS_COMPILED: sparse=on native_profile=release "
          "cross_core_shared_jit=off batch=off alias_runtime_probe=pending hardware=untested")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
