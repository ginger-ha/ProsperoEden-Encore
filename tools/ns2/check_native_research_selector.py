#!/usr/bin/env python3
"""Exercise the real native PS5 NS2 selector gate without compiling the SDK."""
from pathlib import Path
import os
import re
import subprocess

root = Path(__file__).resolve().parents[2]
cmake = (root / "headless/CMakeLists.txt").read_text()
native_script = root / "tools/build-headless-native.sh"
script = native_script.read_text()

declared = re.findall(r"option\((EDEN_NS2_[A-Z0-9_]+)\s", cmake)
assert declared and len(declared) == len(set(declared)), "missing/duplicate NS2 CMake options"
start = script.index("# The shipping PS5 package must never silently acquire")
end = script.index('cmake -S "$scratch/source"', start)
gate = script[start:end]
forwarded = re.findall(r"^    (EDEN_NS2_[A-Z0-9_]+)$", gate, re.MULTILINE)
assert set(forwarded) == set(declared), (
    "Native CMake options drifted", sorted(set(declared) - set(forwarded)),
    sorted(set(forwarded) - set(declared))
)
assert '"${ns2_cmake_args[@]}"' in script, "native CMake does not receive selector array"
# Native RasterizerVulkan::DispatchNativeCompute must override the SAME
# RasterizerInterface ABI seen by core and all Vulkan consumers.
rasterizer_header = (root / "vendor/sources/eden/src/video_core/rasterizer_interface.h").read_text()
assert 'virtual bool DispatchNativeCompute(const Tegra::NativeComputeLaunch&)' in rasterizer_header
assert 'file(STRINGS "${EDEN_NS2_RASTERIZER_INTERFACE}"' in cmake
assert 'configure_file("${EDEN_NS2_RASTERIZER_INTERFACE}"' in cmake
assert 'target_compile_definitions(video_core PUBLIC EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL=1)' in cmake
assert 'target_compile_definitions(core PUBLIC EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL=1)' in cmake
assert 'EDEN_FINAL_RELEASE_PROFILE=ON' in gate
assert 'EDEN_NS2_NATIVE_EXPERIMENTAL=ON' in gate

subprocess.run(["bash", "-n", str(native_script)], check=True)
test_code = "set -euo pipefail\n" + gate + '\nprintf "%s\n" "${ns2_cmake_args[@]}"\n'

def verify(overrides, expected_exit):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    env.update(overrides)
    run = subprocess.run(["bash", "-c", test_code], env=env, text=True,
                         capture_output=True, timeout=10)
    assert (run.returncode == 0) == (expected_exit == 0), (
        overrides, run.returncode, run.stderr
    )
    return run

normal = verify({}, 0)
assert len(normal.stdout.splitlines()) == len(declared)
assert set(normal.stdout.splitlines()) == {f"-D{name}=OFF" for name in declared}
research = verify({"EDEN_NS2_NATIVE_EXPERIMENTAL": "ON",
                   "EDEN_NS2_METADATA_EXPERIMENTAL": "ON"}, 0)
assert "-DEDEN_NS2_METADATA_EXPERIMENTAL=ON" in research.stdout.splitlines()
verify({"EDEN_NS2_METADATA_EXPERIMENTAL": "ON"}, 2)
verify({"EDEN_NS2_NATIVE_EXPERIMENTAL": "ON",
        "EDEN_FINAL_RELEASE_PROFILE": "ON"}, 2)
verify({"EDEN_NS2_NATIVE_EXPERIMENTAL": "maybe"}, 2)
verify({"EDEN_NS2_NATIVE_EXPERIMENTAL": "ON",
        "EDEN_NS2_A64_EXPERIMENTAL": "maybe"}, 2)
# N76 must compose with the already-optimized G11 PS5 A64 backend.
# Replacing the G11 translation unit would silently drop NS1 performance work.
n76 = cmake.split("# N76 -- NS2 guest CNTPCT calibration", 1)[1].split(
    "option(EDEN_HOST_ASAN", 1
)[0]
assert "n76_selected_g11_owner_idx" in n76
assert 'set(EDEN_N76_G11_PROFILE normal)' in n76
assert 'set(EDEN_N76_G11_PROFILE dev)' in n76
assert 'list(REMOVE_ITEM n76_core_sources' not in n76
assert 'list(APPEND n76_core_sources' not in n76
assert 'set_property(TARGET core PROPERTY SOURCES "${n76_core_sources}")' not in n76
g11_root = root / "vendor/encore-active/eden-core/src/core/arm/dynarmic/g11"
for profile in ("normal", "dev"):
    owner = (g11_root / f"arm_dynarmic_64_native_{profile}.cpp").read_text()
    assert owner.count("#ifdef EDEN_NS2_GUEST_COUNTER") == 2, profile
    assert owner.count('#include "encore/guest_counter_policy.h"') == 1, profile
    assert owner.count("config.cntfrq_el0 = static_cast<u32>(Eden::GuestCounter::Rate());") == 1
    assert owner.count("config.cntfrq_el0 = Hardware::CNTFREQ;") == 1

# Exercise the *actual* final-release CMake cache-variable gate with
# cmake -P. Individual flags must all fail closed even if someone bypasses the
# build-headless-native.sh environment selector and invokes CMake directly.
import tempfile
release_start = cmake.index("    # Fail closed for *all* opt-in NS2 engines")
release_end = cmake.index(
    "    target_compile_definitions(eden-headless PRIVATE EDEN_FINAL_RELEASE_PROFILE=1)",
    release_start
)
release_fragment = cmake[release_start:release_end]
assert 'get_cmake_property(eden_release_cache_vars CACHE_VARIABLES)' in release_fragment
assert 'MATCHES "^EDEN_NS2_.*_EXPERIMENTAL$"' in release_fragment

with tempfile.TemporaryDirectory(prefix="encore-ns2-release-gate-") as temporary:
    scenario = Path(temporary) / "release-gate.cmake"
    def run_release_cache(enabled):
        lines = ["set(EDEN_FINAL_RELEASE_PROFILE ON)"]
        for flag in declared:
            state = "ON" if flag == enabled else "OFF"
            lines.append(f'set({flag} {state} CACHE BOOL "" FORCE)')
        if enabled and enabled not in declared:
            lines.append(f'set({enabled} ON CACHE BOOL "" FORCE)')
        lines.extend(["if(EDEN_FINAL_RELEASE_PROFILE)", release_fragment, "endif()"])
        scenario.write_text("\n".join(lines) + "\n")
        result = subprocess.run(["cmake", "-P", str(scenario)], capture_output=True, text=True)
        if enabled:
            assert result.returncode != 0 and enabled in result.stderr, (
                enabled, result.returncode, result.stderr
            )
        else:
            assert result.returncode == 0, result.stderr
    run_release_cache(None)
    for flag in declared:
        run_release_cache(flag)
    run_release_cache("EDEN_NS2_FUTURE_UNREVIEWED_EXPERIMENTAL")
print("NS2_RELEASE_CMAKE_FAIL_CLOSED_PASS", len(declared), "plus future flag")

print(f"PASS: {len(declared)} native NS2 CMake selectors; opt-in research; release fail-closed")
