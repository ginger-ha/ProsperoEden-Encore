#!/usr/bin/env python3
"""Audit the active CMake module boundary; prohibit C++ source fabrication.

Pinned upstream vendor/sources CMake and historical tools/fixtures are not
build-time Encore mutation owners. Resource generation G23 is explicitly
allowed in the root; staging maintained full sources is permitted.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
root_cmake = (ROOT/"headless/CMakeLists.txt").read_text(encoding="utf-8")
generator_sites = re.findall(
    r'^\s*write_derived\(\s*"([^"]+)"', root_cmake, re.M)
assert generator_sites == ["${PORT_BUILD_DIR}/include/loading_scene_glsl.h"], generator_sites
assert root_cmake.count("function(write_derived path content)") == 1
assert root_cmake.count('file(WRITE "${path}.in" "${content}")') == 1
assert len(re.findall(r"^\s*string\(REPLACE", root_cmake, re.M)) == 2
assert 'write_derived("${derived}"' not in root_cmake
assert 'write_derived("${PORT_BUILD_DIR}/kernel.cpp"' not in root_cmake
assert 'write_derived("${PORT_BUILD_DIR}/gpu.cpp"' not in root_cmake

# Discover modules recursively so a newly introduced indirect CMake owner
# cannot hide outside today's documented top-level module list.
module_paths = {
    ROOT/"tools/ps5.cmake",
    *(ROOT/"headless").rglob("*.cmake"),
    *(ROOT/"vendor/encore-active").rglob("*.cmake"),
    *(ROOT/"vendor/encore-active").rglob("CMakeLists.txt"),
}
module_paths.discard(ROOT/"headless/CMakeLists.txt")
# Exclude source-pin SDK manifests: the checked Encore CMake layer above
# is the only location allowed to mutate included dependency sources.
active_mutation = re.compile(
    r'^\s*(?:file\s*\(\s*(?:WRITE|APPEND|GENERATE)\b'
    r'|string\s*\(\s*REPLACE\b'
    r'|write_derived\s*\('
    r'|execute_process\s*\()', re.I | re.M)
# The P5-only NUP gate tokenizes two audited source-owner names, not C++
# source text. Permit that ONE exact list-parsing invocation only. Do not
# exempt the module, a generic string(REPLACE), or future source transforms.
nup_gate_path = ROOT/"headless/nup_v1_runtime.cmake"
nup_pair_split = 'string(REPLACE "|" ";" eden_nup_parts "${eden_nup_pair}")'
assert nup_gate_path.read_text(encoding="utf-8").count(nup_pair_split) == 1

def permitted_source_owner_split(path: Path, source: str, match: re.Match) -> bool:
    return (path == nup_gate_path and
            source[match.start():].splitlines()[0].strip() == nup_pair_split)

# A newly introduced CMake string replacement in this very module must still
# fail, including one that creates a .cpp output or changes the selected list.
assert permitted_source_owner_split(
    nup_gate_path, nup_pair_split, active_mutation.search(nup_pair_split))
assert not permitted_source_owner_split(
    ROOT/"headless/other.cmake", nup_pair_split,
    active_mutation.search(nup_pair_split))
for negative in (
    'string(REPLACE "old" "new" cpp_text "${source}")',
    'string(REPLACE "|" ";" eden_nup_parts "${other}")',
):
    assert not permitted_source_owner_split(
        nup_gate_path, negative, active_mutation.search(negative))

checked = 0
approved_splits = 0
for path in sorted(module_paths):
    assert path.is_file(), path
    text = path.read_text(encoding="utf-8")
    violations = []
    for match in active_mutation.finditer(text):
        if permitted_source_owner_split(path, text, match):
            approved_splits += 1
            continue
        violations.append((text.count("\n", 0, match.start()) + 1,
                           match.group(0).strip()))
    assert not violations, (
        f"Active CMake module must not generate or rewrite C++: "
        f"{path.relative_to(ROOT)} {violations}")
    checked += 1
assert approved_splits == 1, approved_splits

native_build = (ROOT/"tools/build-headless-native.sh").read_text()
vulkan = (ROOT/"headless/vulkan.cmake").read_text()
assert 'file(COPY "${EDEN_ACTIVE_VULKAN}/"' in vulkan
assert 'vendor/encore-active' in vulkan or 'EDEN_ACTIVE_VULKAN' in vulkan
for path, code in (("native build", native_build),
                   ("CMake root", root_cmake), ("Vulkan selector", vulkan)):
    assert "prepare-vulkan-port.py" not in code, (
        f"Historical Vulkan source transformation invoked by {path}")
assert 'shutil.copyfile(maintained, tmp)' in (
    ROOT/"tools/install-active-core-backports.py").read_text()
print(f"ENCORE_ACTIVE_CMAKE_SOURCE_BOUNDARY_PASS modules={checked} "
      "cpp_generators=0 resource_generators=1 nup_source_pair_split=1")
