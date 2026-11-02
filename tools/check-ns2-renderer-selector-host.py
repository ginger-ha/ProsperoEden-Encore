#!/usr/bin/env python3
"""Exercise the actual research CMake switch without building PS5."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
source = (ROOT / "headless/CMakeLists.txt").read_text()
start = "# N3m: compile a renderer-callable"
end = "# Release gate: Vulkan/RADV"
assert start in source and end in source
selector = start + source.split(start,1)[1].split(end,1)[0]
target = ROOT / "vendor/encore-active/ns2-runtime/ampere/shader_recompiler/frontend/ampere/renderer_spirv_bridge.cpp"
assert target.is_file() and "target_sources(video_core PRIVATE" in selector
# P2.2: production-selected native renderer obtains TIC metadata exclusively
# from the authenticated QMD channel tables, not from fake defaults or a
# second Switch 2 texture cache. This source witness is not PS5 runtime proof.
rasterizer = (ROOT / "vendor/encore-active/eden-vulkan/vulkan_rasterizer.cpp").read_text()
native = rasterizer.split("bool RasterizerVulkan::DispatchNativeCompute(", 1)[1].split(
    "void RasterizerVulkan::DispatchCompute(", 1)[0]
assert "class NativeQmdTextureMetadata final : public Shader::Environment" in rasterizer
assert "NativeBufferOnlyMetadata" not in rasterizer
assert "VideoCommon::PixelFormatFromTextureInfo(" in rasterizer
assert "VideoCommon::ReadNs2GpuShader(" in rasterizer
assert "NativeQmdTextureTables" in native
assert "kepler_compute.regs" in native
assert "launch.linked_tsc" in native
assert "return false; // no unbacked image/sampler descriptor publication" in native
assert "resources->HasResolvedBufferBindings()" in native
print("NS2_NATIVE_TIC_METADATA_SOURCE_PASS real_tables=1 no_false_vk_images=1")

def test(root, title, values, succeed):
    args = ["cmake","-S",str(root),"-B",str(root/title)]
    args += [f"-D{k}={'ON' if v else 'OFF'}" for k,v in values.items()]
    p = subprocess.run(args,capture_output=True,text=True)
    assert (p.returncode==0)==succeed,(title,p.stderr[-3000:])
    return (root/title/"owner.txt").read_text() if succeed else ""

def main():
    if not shutil.which("cmake"): raise RuntimeError("cmake required")
    dollar = chr(36)
    with tempfile.TemporaryDirectory(prefix="ns2-cmake-") as tmp:
        path = Path(tmp)
        cmake = (
            "cmake_minimum_required(VERSION 3.22)\n"
            "project(NS2ShaderSelector LANGUAGES CXX)\n"
            f'file(WRITE "{dollar}{{CMAKE_CURRENT_BINARY_DIR}}/stub.cpp" "int n() {{return 1;}}\\n")\n'
            f'add_library(video_core STATIC "{dollar}{{CMAKE_CURRENT_BINARY_DIR}}/stub.cpp")\n'
            f'add_library(core STATIC "{dollar}{{CMAKE_CURRENT_BINARY_DIR}}/stub.cpp")\n'
            f'set(PORT_BUILD_DIR "{dollar}{{CMAKE_CURRENT_BINARY_DIR}}")\n'
            f'set(PORT_ROOT "{ROOT.as_posix()}")\n'
        )
        for name in ("NATIVE","VULKAN","AMPERE","METADATA","GPU_SESSION","NVDRV"):
            key = {"NATIVE":"PS5_NATIVE","VULKAN":"EDEN_PS5_VULKAN",
                   "AMPERE":"EDEN_NS2_AMPERE_PROBE_EXPERIMENTAL",
                   "METADATA":"EDEN_NS2_METADATA_EXPERIMENTAL",
                   "GPU_SESSION":"EDEN_NS2_GPU_SESSION_EXPERIMENTAL",
                   "NVDRV":"EDEN_NS2_NVDRV_EXPERIMENTAL"}[name]
            cmake += f"set({key} {dollar}{{NS2_TEST_{name}}})\n"
        cmake += selector
        cmake += f'get_target_property(owner video_core SOURCES)\nfile(WRITE "{dollar}{{CMAKE_CURRENT_BINARY_DIR}}/owner.txt" "{dollar}{{owner}}")\n'
        (path/"CMakeLists.txt").write_text(cmake)
        baseline = {f"NS2_TEST_{n}":True for n in ("NATIVE","VULKAN","AMPERE","METADATA","GPU_SESSION","NVDRV")}
        off = test(path,"off",baseline,True)
        assert "renderer_spirv_bridge" not in off,off
        enabled = {**baseline,"EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL":True}
        on = test(path,"on",enabled,True)
        assert str(target) in on,on
        assert "ns2_shader_spirv_compile.cpp" in on,on
        for name in baseline:
            test(path,"missing-"+name,{**enabled,name:False},False)
    print("NS2 renderer selector: PASS (OFF, ON, six missing prerequisite cases)")

if __name__=="__main__":
    main()
