#!/usr/bin/env python3
"""Static release selection proof: refuse dev and experimental native paths."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
pkg = (root / "tools/build-package.sh").read_text()
build = (root / "tools/build-headless-native.sh").read_text()
cm = (root / "headless/CMakeLists.txt").read_text()
validator = (root / "tools/ci/check-release-experiments.py").read_text()
main = (root / "headless/main.cpp").read_text()
release = pkg.split("release|release-stage)\n", 1)[1].split("\n    ;;", 1)[0]
assert "EDEN_FINAL_RELEASE_PROFILE=ON" in release
for opt in ("EDEN_SHARED_JIT", "EDEN_JIT_COMPILE_BATCH",
            "EDEN_INLINE_EXCLUSIVES", "EDEN_HEAP_GUARD", "EDEN_DEVICE_FRONTEND",
            "EDEN_GUEST_WRITE_BRIDGE_DEV", "EDEN_UNQUALIFIED_FERMI2D_COPY"):
    assert opt+"=OFF" in release, opt
assert 'export EDEN_PS5_VULKAN=ON EDEN_VULKAN_DRIVER=RADV' in pkg
assert 'bash tools/build-headless-native.sh --graphics' in pkg
assert '-DEDEN_FINAL_RELEASE_PROFILE="${EDEN_FINAL_RELEASE_PROFILE:-OFF}"' in build
# The final release contract has exactly one canonical top-level gate.
# Do not accidentally start validating an unrelated nested experimental gate.
final_gate = "if(EDEN_FINAL_RELEASE_PROFILE)\n"
assert cm.count(final_gate) == 1
section = cm.split(final_gate, 1)[1].split("\nendif()", 1)[0]
nup_selector = (root / "headless/nup_v1_runtime.cmake").read_text()
assert cm.count('include("${CMAKE_CURRENT_LIST_DIR}/nup_v1_runtime.cmake")') == 1
assert nup_selector.count("option(EDEN_NUP_V1_RUNTIME") == 1
assert 'route verified NUP containers to shared loader" OFF)' in nup_selector
assert nup_selector.count("if(EDEN_NUP_V1_RUNTIME)") == 1
assert "if(EDEN_FINAL_RELEASE_PROFILE)" in nup_selector
assert "NUP v1 P5 qualification is not yet allowed in a final release" in nup_selector
for token in ("NOT PS5_NATIVE", "NOT EDEN_PS5_VULKAN", "NOT EDEN_PS5_OPENGL",
              'NOT EDEN_VULKAN_DRIVER STREQUAL "RADV"', "EDEN_SHARED_JIT",
              "EDEN_JIT_COMPILE_BATCH", "EDEN_DEV_PROFILE",
              "EDEN_DEV_VULKAN", "EDEN_DEV_WAIT_CALLERS", "EDEN_GPU_PROBE",
              "EDEN_DEVICE_FRONTEND", "EDEN_GUEST_WRITE_BRIDGE_DEV",
              "EDEN_UNQUALIFIED_FERMI2D_COPY", "NOT EDEN_BLOCKING_GUEST_CONTEXT_LOCKS",
              "NOT EDEN_A32_FASTMEM"):
    assert token in section, token
assert "EDEN_SPARSE_JIT_DEV" not in pkg and "EDEN_SPARSE_JIT_DEV" not in cm
assert "EDEN_SPARSE_JIT_DEV" not in build
assert "EDEN_JIT_SPARSE_TRIM" in validator
assert '"EDEN_FINAL_RELEASE_PROFILE:BOOL": "ON"' in validator
assert '"EDEN_NUP_V1_RUNTIME:BOOL": "OFF"' in validator
assert 'EDEN_NS2_.*_EXPERIMENTAL:BOOL' in validator
assert "target_compile_definitions(eden-headless PRIVATE EDEN_FINAL_RELEASE_PROFILE=1)" in cm
assert 'experimental_sparse_jit = true;' in main
assert 'if (!Common::ProbeSparseJitAlias())' in main
assert 'throw std::runtime_error("PS5 sparse JIT alias preflight failed")' in main
assert 'experimental_logical_cpu = true;\n            experimental_frame_probe = true;\n#endif' in main
for flag in ("EDEN_GUEST_WRITE_BRIDGE_DEV", "EDEN_UNQUALIFIED_FERMI2D_COPY"):
    assert f'"{flag}:BOOL": "OFF"' in validator
    assert f'-D{flag}="' in build
subprocess.run([sys.executable, "-B", str(root / "tools/ci/check-release-experiments.py"),
                "--self-test"], check=True, timeout=15)
print("ENCORE_SINGLE_FINAL_RELEASE_PROFILE_PASS RADV+launcher_GL per_core_JIT sparse=ON fail_closed_alias=1")
