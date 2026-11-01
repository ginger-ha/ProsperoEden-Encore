#!/usr/bin/env python3
"""Test the exact scoped GPU HLE headers from pinned Eden-NS2 plus uploaded patch."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent
HEADERS=ROOT/"vendor/encore-active/ns2-runtime/hle"
NVDRV=ROOT/"vendor/encore-active/ns2-runtime/nvdrv"
EDEN=ROOT/"vendor/sources/eden/src"
SOURCE=ROOT/"tools/ns2/test_graphics_hle.cpp"
EXPECTED=[
    HEADERS/"core/hle/service/am/service/graphics_supervisor_protocol.h",
    HEADERS/"core/hle/service/am/service/native_image_layout.h",
    HEADERS/"core/hle/service/am/service/gpu_memory_registration.h",
    HEADERS/"core/hle/service/nvdrv/devices/native_gpu_kind.h",
    HEADERS/"core/hle/service/nvdrv/devices/native_sparse_remap.h",
    HEADERS/"core/hle/service/nvdrv/devices/native_gpu_context.h",
    HEADERS/"core/hle/service/am/service/graphics_syncpoint_cache.h",
    HEADERS/"core/hle/service/am/service/gpu_session_protocol.h",
    HEADERS/"core/hle/service/am/service/graphics_supervisor_bootstrap.h",
    HEADERS/"core/hle/service/am/service/gpu_worker_protocol.h",
]
def main()->int:
    if not all(f.is_file() for f in EXPECTED):
        print("NS2 graphics HLE overlay incomplete",file=sys.stderr)
        return 2
    # The real research-only supervisor, not just the standalone protocol,
    # handles creation/bind/destruction; no synthetic GPU work is advertised.
    supervisor=ROOT/"vendor/encore-active/ns2-runtime/graphics_supervisor/core/hle/service/am/service/graphics_supervisor.cpp"
    text=supervisor.read_text()
    for command, method in ((111,"CreateNativeMemory"),(112,"DestroyNativeMemory"),(114,"BindNativeMemory")):
        assert '{'+str(command)+', &IGraphicsSupervisor::'+method in text
    assert 'm_native_memory.ValidateBind(' in text
    assert 'table.QueryInfo(&info, &page, cursor)' in text
    assert 'NativeMemoryError(m_native_memory.Bind(' in text
    assert 'm_native_memory.Destroy(' in text
    assert 'GpuContextReady()' in text
    assert 'ResultNotImplemented.raw' in text
    assert 'ResultInvalidCurrentMemory' in text
    for command, method in ((435,"CalculateNativeImageSize"),(1510,"CalculateNativeImageRequirements")):
        assert '{'+str(command)+', &IGraphicsSupervisor::'+method in text
    assert 'CalculateNativeImageRequirements(std::span<const u32>{data + 2, 16}, data[18])' in text
    assert 'if (data[1] != 17) return {};' in text
    assert 'rb.Push(request ? static_cast<u32>(request->alignment)' in text
    assert 'Kernel::KMemoryState::FlagMapped' in text
    compiler=shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        print("C++20 compiler missing",file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="encore-ns2-graphics-hle-") as tmp:
        for opt in ("-O0","-O2"):
            exe=Path(tmp)/("test"+opt)
            command=[compiler,"-std=c++20","-Wall","-Wextra","-Werror",
                     "-pedantic","-fsanitize=undefined","-fno-sanitize-recover=all",
                     opt,"-I",str(HEADERS),"-I",str(NVDRV),"-I",str(EDEN),str(SOURCE),
                     "-o",str(exe)]
            subprocess.run(command,check=True)
            subprocess.run([str(exe)],check=True,env={
                **os.environ,"UBSAN_OPTIONS":"halt_on_error=1"})
    print("No real NVDRV GPU session, PS5 rendering or game compatibility inferred.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
