#!/usr/bin/env python3
"""Configure-only test of the P5 NUP source selector; never compiles a console."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = r"""
cmake_minimum_required(VERSION 3.24)
project(EncoreNupGate LANGUAGES CXX)
set(EDEN_PORT_DIR "@NUP_ROOT@/headless")
set(PORT_ROOT "@WORK_ROOT@")
add_library(core STATIC
    "@WORK_ROOT@/core/loader/loader.cpp"
    "@WORK_ROOT@/core/file_sys/romfs_factory.cpp"
    "@WORK_ROOT@/core/hle/service/aoc/addon_content_manager.cpp")
add_library(libzstd_static INTERFACE)
add_library(ZLIB::ZLIB INTERFACE IMPORTED)
add_executable(eden-headless "@WORK_ROOT@/mock-headless.cpp")
add_library(eden-metadata STATIC "@WORK_ROOT@/mock-metadata.cpp")
include("@NUP_ROOT@/headless/nup_v1_runtime.cmake")
get_target_property(source_list core SOURCES)
if(EDEN_NUP_V1_RUNTIME)
    if(NOT source_list MATCHES "nup_v1_loader_route[.]cpp")
        message(FATAL_ERROR "NUP factory source not attached")
    endif()
    if(NOT source_list MATCHES "nup_v1_native_aoc[.]cpp")
        message(FATAL_ERROR "NUP AoC source not attached")
    endif()
    if(NOT source_list MATCHES "nup_v1_aoc_service[.]cpp")
        message(FATAL_ERROR "NUP AoC service source not attached")
    endif()
    if(NOT source_list MATCHES "nup_v1_romfs_factory[.]cpp")
        message(FATAL_ERROR "NUP RomFS factory source not attached")
    endif()
    if(source_list MATCHES "/core/hle/service/aoc/addon_content_manager[.]cpp" OR
       source_list MATCHES "/core/file_sys/romfs_factory[.]cpp")
        message(FATAL_ERROR "Duplicate original AoC/ROMFS source owners")
    endif()
    get_source_file_property(defs "@WORK_ROOT@/core/loader/loader.cpp"
        COMPILE_DEFINITIONS TARGET_DIRECTORY core)
    if(NOT defs MATCHES "GetLoader=EdenOriginalGetLoader")
        message(FATAL_ERROR "Original vendor GetLoader not aliased")
    endif()
else()
    if(source_list MATCHES "nup_v1_")
        message(FATAL_ERROR "NUP leaked into default build")
    endif()
endif()
"""

def configure(root: Path, label: str, *options: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["cmake", "-S", str(root), "-B", str(root/label), *options],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        check=False,
    )

def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        owner = root / "core/loader/loader.cpp"
        owner.parent.mkdir(parents=True)
        owner.write_text("int noop() { return 0; }\n", encoding="utf-8")
        for relative in (
            "core/file_sys/romfs_factory.cpp",
            "core/hle/service/aoc/addon_content_manager.cpp",
        ):
            synthetic = root / relative
            synthetic.parent.mkdir(parents=True, exist_ok=True)
            synthetic.write_text("int temporary_" + str(len(relative)) +
                                 "() { return 0; }\n", encoding="utf-8")
        (root / "mock-headless.cpp").write_text(
            "int main() { return 0; }\n", encoding="utf-8")
        (root / "mock-metadata.cpp").write_text(
            "int metadata() { return 0; }\n", encoding="utf-8")
        maintained = root / "vendor/encore-active/eden-core/src/core/file_sys"
        maintained.mkdir(parents=True)
        (maintained / "extracted_aoc.h").write_text("#pragma once\n", encoding="utf-8")
        content = TEMPLATE.replace("@NUP_ROOT@", ROOT.as_posix()).replace(
            "@WORK_ROOT@", root.as_posix())
        project = root / "CMakeLists.txt"
        project.write_text(content, encoding="utf-8")
        off = configure(root, "off")
        assert off.returncode == 0, f"default OFF failed:\n{off.stdout}"
        on = configure(root, "on", "-DEDEN_NUP_V1_RUNTIME=ON")
        assert on.returncode == 0, f"P5 ON source configure failed:\n{on.stdout}"
        denied = configure(root, "final", "-DEDEN_NUP_V1_RUNTIME=ON",
                           "-DEDEN_FINAL_RELEASE_PROFILE=ON")
        assert denied.returncode != 0 and (
            "not yet allowed in a final release" in denied.stdout), denied.stdout
        # A missing or renamed vendor factory cannot silently route through NUP.
        owner.rename(owner.with_name("renamed.cpp"))
        project.write_text(content.replace(
            "core/loader/loader.cpp", "core/loader/renamed.cpp"),
            encoding="utf-8")
        drift = configure(root, "drift", "-DEDEN_NUP_V1_RUNTIME=ON")
        assert drift.returncode != 0 and (
            "exactly one pinned loader.cpp owner" in drift.stdout), drift.stdout
    print("P5 NUP source routing: default OFF, ON, final refusal, source drift OK")

if __name__ == "__main__":
    main()
