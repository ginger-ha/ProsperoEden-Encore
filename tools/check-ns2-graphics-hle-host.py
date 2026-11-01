#!/usr/bin/env python3
"""Test the exact scoped GPU HLE headers from pinned Eden-NS2 plus uploaded patch."""
from pathlib import Path
import os
import re
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
    # Accept only formatting whitespace; the same native-memory guard is required.
    assert re.search(r'NativeMemoryError\s*\(\s*m_native_memory\.Bind\s*\(', text)
    assert 'm_native_memory.Destroy(' in text
    # GSV 111/112/114 must use real NVMap handle identity and kernel page locks,
    # not acknowledge metadata-only resources that cannot become GPU images.
    for source in (
        'nvmap.CreateHandle(size, handle)',
        'm_native_memory.Adopt(id, size)',
        'auto handle = nvmap.GetHandle(packet[2])',
        'handle.reset(); // FreeHandle',
        'nvmap.FreeHandle(packet[2], false)',
        'table.LockForMapDeviceAddressSpace(',
        'handle->Alloc(',
        'm_native_memory.Bind(id, address, size)',
        'UnlockForDeviceAddressSpace(',
        'm_native_module->GetContainer().CloseSession(',
    ):
        assert source in text, "Missing real GSV NVMap lifetime owner: " + source
    assert 'm_native_memory.Create(size)' not in text, "Synthetic GSV native memory ID in runtime"
    # VI2 must connect real process-owned 429 image window aliases to the
    # existing display compositor, not return synthetic present success.
    for command, method in ((301,"InitializeDisplayContext"),
                            (303,"FinalizeDisplayContext"),
                            (305,"OpenDisplaySession")):
        assert '{'+str(command)+', &IGraphicsSupervisor::'+method in text
    for evidence in (
        'class IVi2Session final : public ServiceFramework<IVi2Session>',
        '{229,&IVi2Session::Present,"PresentClientBuffer"}',
        'GetService<VI::IManagerRootService>("vi:m",true)',
        'CreateManagedLayer(&layer,*c->display,m_aruid)',
        'GetPresentImage(p[5])',
        'GetLayerProducerHandle(',
        'std::make_shared<android::GraphicBuffer>(',
        'c->producer->AttachBuffer(&idx,buffer)',
        'c->producer->QueueBuffer(idx,input,&output)',
        'c.producer->DetachNextBuffer(',
        'c.release_fences[slot]=release_fence',
        'if(!image||!image->window_pool||!m_native_module)return {}',
        'GetSyncpointManager().IsSyncpointAllocated(fence)',
        'c->retained[slot]=buffer',
        'backing_handle->Duplicate(true)',
        'image->size>backing_handle->orig_size-offset',
        'backing_session->process!=m_process',
        'FreeHandle(*id,true)',
        'syncpoints.HasSyncpointExpired(point.id,point.value)',
        '{111,&IVi2Session::OpenEndpoint,"OpenEndpoint"}',
        '{112,&IVi2Session::CloseEndpoint,"CloseEndpoint"}',
        '{352,&IVi2Session::OutputLevels,"SetClientOutputLevels"}',
        '{106,&IVi2Session::MaxResolution,"GetBufferMaxResolution"}',
        'c->queued_modules[slot]=img->module',
        'it->available_bit=p[5]',
        'Signal(c.available_bit)',
        'Signal(c->release_bit)',
        'client->output_levels=values;',
        'std::isfinite(v)',
        'native->format=android::PixelFormat::Rgba8888;',
        'pref[6]==1&&outw<=width&&outh<=height',
    ):
        assert evidence in text, "VI2 compositor must preserve real queue/fence owner: " + evidence

    for command, method in (
        (911, "CreateVideoImagePool"), (912, "DestroyVideoImagePool"),
        (426, "MapVideoGpuImage"), (427, "UnmapVideoGpuImage"),
        (428, "QueryVideoGpuImage"),
    ):
        assert '{'+str(command)+', &IGraphicsSupervisor::'+method in text
    for snippet in (
        'CalculateNativeVideoImageLayout(preference, count)',
        'm_video_pools.Add(static_cast<u32>(m_next_image_id),',
        'm_native_memory.Get(backing)',
        'session && session->process == m_process',
        'handle->Duplicate(true)',
        'nvmap.PinHandle(backing, false)',
        'm_video_pools.Lookup(packet[2])',
        'FindRegisteredGpuAddressSpace(packet[4])',
        'as->MapNativeImage(image->backing, image->offset,',
        'it->second.address_space->UnmapNative4K(',
        'm_video_mappings.erase(it)',
        'it->second.address_space == as',
        'const auto as = FindRegisteredGpuAddressSpace(packet[3]);',
        'nvmap.UnpinHandle(pool->backing)',
        'm_video_pools.Remove(pool->first_id)',
        'for (const auto& [key, mapping] : m_video_mappings)',
    ):
        assert snippet in text, "Missing real NS2 video pool/GMMU ownership: " + snippet

    assert '{423, &IGraphicsSupervisor::BindNativeGpuMemory' in text
    for snippet in (
        'GraphicsSupervisorProtocol::DecodeNativeParentBind(packet)',
        'session && session->process == m_process',
        'parent->Duplicate(true)',
        'nvmap.PinHandle(request->parent, false)',
        'nvmap.UnpinHandle(request->parent)',
        'nvmap.FreeHandle(request->parent, true)',
        'm_native_parents.emplace(request->child, request->parent)',
        'm_native_parents.find(packet[2])',
        'BindNativeMemoryBacking(request->child,',
        'for (const auto& [child, parent] : m_native_parents)',
    ):
        assert snippet in text, "Missing real parent GSV 423 lifecycle: " + snippet

    for command in (314,315):
        assert '{'+str(command)+', &IGraphicsSupervisor::ConfigureNativeWindowImagePool' in text
    assert 'm_native_images.ConfigureWindowPool(packet[2], create)' in text
    assert '!image->window_pool' in text
    for command, method in ((429,"CreateNativeImage"), (430,"DestroyNativeImage")):
        assert '{'+str(command)+', &IGraphicsSupervisor::'+method in text
    for snippet in (
        'm_native_images.Create(',
        'm_native_images.Destroy(packet[2])',
        'static_cast<u32>(m_next_image_id)',
        'handle->Duplicate(true)',
        'FreeHandle(\n                image->backing, true)',
        'for (const auto& [image_id, image] : m_native_images.Records())',
    ):
        assert snippet in text, "Missing native image NVMap ownership: " + snippet
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
