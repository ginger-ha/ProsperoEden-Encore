#!/usr/bin/env python3
"""Build actual pinned Eden Maxwell/IR/SPIR-V and validate synthetic graphics modules.

Uses the upstream CMake source inventories, with real Sirit and SPIRV-Headers.
Does not attach this compiler to production Vulkan or Switch 1 shader caches.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "vendor/sources/eden/src"
SHADER = SRC / "shader_recompiler"
SIRIT = ROOT / "build-ns2-deps/sirit"
HEADERS = ROOT / "build-ns2-deps/spirv-headers"
FMT = ROOT / "build-ns2-a64/fmt/include"
OUT = ROOT / "build-ns2-real-spirv"

def run(cmd):
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        print("FAILED:", " ".join(map(str, cmd)), file=sys.stderr)
        print(result.stdout[-6000:], result.stderr[-18000:], file=sys.stderr)
        raise RuntimeError("real SPIR-V build or validation failed")
    return result

def cmake_sources(file, prefix, pattern, minimum, required):
    cmake = file.read_text().split("add_library(" + prefix, 1)[1].split("\n)", 1)[0]
    names = re.findall(r"^\s*(" + pattern + r")\s*$", cmake, re.M)
    if len(names) < minimum or any(name not in names for name in required):
        raise RuntimeError("unexpected pinned CMake source inventory: " + str(file))
    return names

def main():
    cxx = shutil.which(os.environ.get("CXX", "g++"))
    validator = shutil.which("spirv-val")
    if not cxx or not validator:
        raise RuntimeError("requires C++20 compiler and spirv-val")
    if not (FMT / "fmt/format.h").is_file() or not (SIRIT / "include/sirit/sirit.h").is_file() or not (HEADERS / "include/spirv/unified1/spirv.hpp11").is_file():
        raise RuntimeError("pinned fmt/Sirit/SPIRV-Headers are missing")
    shaders = cmake_sources(
        SHADER / "CMakeLists.txt", "shader_recompiler STATIC",
        r"(?:frontend|ir_opt|backend/spirv)/[^\s()]+\.cpp", 135,
        ["frontend/maxwell/translate_program.cpp",
         "backend/spirv/emit_spirv.cpp",
         "backend/spirv/spirv_emit_context.cpp"])
    sirit_sources = cmake_sources(
        SIRIT / "src/CMakeLists.txt", "siritobj OBJECT",
        r"(?:instructions/)?[^\s()/]+\.cpp", 18,
        ["sirit.cpp", "instructions/type.cpp"])
    overlay = ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere"
    # P2.3: validate BOTH maintained QMD3 source variants, not Eden's
    # fourteen-bank indirect switch or its unchecked direct-bank accessor.
    native_cbuf_emitters = {
        "backend/spirv/spirv_emit_context.cpp":
            ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/backend/spirv/spirv_emit_context.cpp",
        "backend/spirv/emit_spirv_context_get_set.cpp":
            ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/backend/spirv/emit_spirv_context_get_set.cpp",
    }
    if any(shaders.count(owner) != 1 for owner in native_cbuf_emitters):
        raise RuntimeError("pinned SPIR-V CBUF source owner changed")
    sources = [native_cbuf_emitters.get(name, SHADER / name)
               for name in shaders] + [
        overlay / (name + ".cpp") for name in
        ("ir_bridge", "renderer_spirv_bridge", "maxwell_environment", "maxwell_image", "lower_bridge", "probe")
    ] + [overlay / "capture.cpp",
         overlay / "translation_cache.cpp",
         ROOT / "vendor/encore-active/ns2-runtime/ampere/video_core/ns2_shader_spirv_compile.cpp",
         SRC / "common/settings_common.cpp",
         ROOT / "tools/ns2/jit-host/common_shim.cpp",
         ROOT / "tools/ns2/test_ampere_real_spirv.cpp"]
    sources += [SIRIT / "src" / name for name in sirit_sources]
    missing = [str(p) for p in sources if not p.is_file()]
    if missing:
        raise RuntimeError("missing pinned shader sources: " + ", ".join(missing))
    OUT.mkdir(parents=True, exist_ok=True)
    flags = [cxx, "-std=c++20", "-O0", "-g0", "-DFMT_HEADER_ONLY",
             "-ffunction-sections", "-fdata-sections", "-Wno-unused-parameter",
             "-pthread", "-I" + str(FMT),
             "-I" + str(ROOT / "vendor/encore-active/ns2-runtime/ampere"),
             "-I" + str(ROOT / "vendor/encore-active/ns2-runtime/gpu_dispatch"),
             "-I" + str(ROOT / "vendor/encore-active/ns2-runtime/hle"), "-I" + str(SRC),
             "-I" + str(SRC / "dynarmic/src"),
             "-I" + str(SIRIT / "include"), "-I" + str(SIRIT / "src"),
             "-I" + str(HEADERS / "include")]
    jobs = [(p, OUT / f"{i:03d}.o") for i, p in enumerate(sources)]
    print("Compiling true Maxwell, IR, SPIR-V and Sirit C++ units:", len(jobs), flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(run, flags + ["-c", str(src), "-o", str(obj)]): src
                   for src, obj in jobs}
        for item in as_completed(futures):
            try:
                item.result()
            except Exception:
                print("Failing source:", futures[item], file=sys.stderr)
                for other in futures:
                    other.cancel()
                raise
    binary = OUT / "ns2-real-spirv"
    run([cxx, "-pthread", "-Wl,--gc-sections", "-o", str(binary)] +
        [str(obj) for _, obj in jobs] + ["-latomic"])
    print(run([str(binary), str(OUT / "synthetic")]).stdout, end="")
    # Real live native LDC 0xb82 reaches QMD3 CBUF banks 0 and 7; BRX
    # reaches the actual Maxwell CFG/IR/Sirit loop+conditional dispatch.
    # Validate the executable-structure SPIR-V modules, not only headers or
    # reflected descriptor plans. No PS5 GPU work is submitted here.
    for mode in ("direct", "dispatcher", "fragment", "merged", "compute", "cbuf0", "cbuf7", "brx"):
        path = OUT / f"synthetic-{mode}.spv"
        print(run([validator, "--target-env", "spv1.5", str(path)]).stdout, end="")
        print(f"spirv-val SPIR-V 1.5 {mode}: PASS")
        print(run([validator, "--target-env", "vulkan1.2", str(path)]).stdout, end="")
        print(f"spirv-val Vulkan 1.2 {mode}: PASS")
    module_test = OUT / "ns2-vulkan-modules"
    run([cxx, "-std=c++20", "-O2",
         str(ROOT / "tools/ns2/test_ampere_vulkan_module.cpp"),
         "-o", str(module_test), "-lvulkan"])
    print(run([str(module_test),
               str(OUT / "synthetic-direct.spv"),
               str(OUT / "synthetic-dispatcher.spv"),
               str(OUT / "synthetic-fragment.spv"),
               str(OUT / "synthetic-merged.spv"),
               str(OUT / "synthetic-compute.spv")]).stdout, end="")
    print("SPIR-V validation and Vulkan shader-module creation passed; "
          "real PS5 Vulkan renderer not exercised.")

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(error, file=sys.stderr)
        sys.exit(1)
