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
    # Protocol 11 (VI2) and 12 (GPU session) must expose an event as
    # a TIPC COPY handle. Explicit errors carry no phantom null handle.
    vi_notify=text.split('void Event(HLERequestContext& ctx) {',1)[1].split('void VsyncEvent(',1)[0]
    assert 'IPC::ResponseBuilder rb{ctx,2,1,0};' in vi_notify
    assert 'rb.PushCopyObjects(ctx,m_event->GetReadableEvent());' in vi_notify
    assert 'AddMoveObject' not in vi_notify
    assert 'readable->Open(kernel)' not in vi_notify
    gpu_session=(ROOT/"vendor/encore-active/ns2-runtime/gpu_session/core/hle/service/am/service/gpu_session.cpp").read_text()
    gpu_notify=gpu_session.split('void IGpuSession::GetNotificationEvent(HLERequestContext& ctx) {',1)[1].split('IGpuSession::ResolveOpenedAddressSpace',1)[0]
    assert 'IPC::ResponseBuilder rb{ctx, 2, 1, 0};' in gpu_notify
    assert 'rb.PushCopyObjects(ctx, *readable);' in gpu_notify
    assert 'AddMoveObject' not in gpu_notify
    assert 'readable->Open(kernel)' not in gpu_notify
    # NX2 VI2 has an empty request-group acknowledgement only for 51.
    # Queries 103/104/105 must fill their full SDK payload, not return
    # success with stale input buffer words (HDR 104 can black out graphics).
    for number, method in (
        (51, "AcknowledgeDisplayPoll"),
        (103, "QueryRefreshRate"),
        (104, "QueryHdrStatus"),
        (105, "QueryPaperWhite"),
    ):
        assert '{'+str(number)+',&IVi2Session::'+method in text
    for evidence in (
        'void AcknowledgeDisplayPoll(HLERequestContext& ctx)',
        'void QueryRefreshRate(HLERequestContext& ctx)',
        'void QueryHdrStatus(HLERequestContext& ctx)',
        'void QueryPaperWhite(HLERequestContext& ctx)',
        'ValidateDisplayStatus(ctx, 103)',
        'ValidateDisplayStatus(ctx, 104)',
        'ValidateDisplayStatus(ctx, 105)',
        'GraphicsSupervisorProtocol::Vi2NominalRefreshRateHz',
        'GraphicsSupervisorProtocol::Vi2SdrOutputFormat',
        'GraphicsSupervisorProtocol::Vi2SdrPeakNits',
        'GraphicsSupervisorProtocol::Vi2SdrPaperWhiteNits',
        'GraphicsSupervisorProtocol::Vi2MaxResolutionMode(',
        'Settings::IsDockedMode()',
        'GetDisplayResolution(&width, &height, *m_display)',
        'return Kernel::ResultInvalidCombination;',
        'return m_display && m_vi ? ResultSuccess : Kernel::ResultInvalidState;',
    ):
        assert evidence in text, "Missing fail-closed VI2 payload owner: " + evidence
    assert 'width==1280&&height==720' not in text
    hdr=text.split('void QueryHdrStatus(HLERequestContext& ctx) {',1)[1].split(
        'void QueryPaperWhite(HLERequestContext& ctx) {',1)[0]
    assert 'IPC::ResponseBuilder rb{ctx, 5};' in hdr
    assert 'rb.Push<u64>(result.IsSuccess()' in hdr
    assert 'rb.Push<u32>(result.IsSuccess()' in hdr
    assert 'rb.Push(Kernel::ResultNotImplemented.raw)' in text
    # The guest's VI2 swap interval is forwarded to the real compositor.
    # A fixed 1-vblank default here can double 30 FPS game/audio pacing.
    assert 'DecodePresentSwapInterval(p[12])' in text
    assert 'input.swap_interval=1;' not in text
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
        'if (fence.num_fences > fence.fences.size()) continue;',
        'if(!image||!image->window_pool||!m_native_module)return {}',
        'GetSyncpointManager().IsSyncpointAllocated(fence)',
        'c->retained[slot]=buffer',
        'backing_handle->Duplicate(true)',
        'image->size>backing_handle->orig_size-offset',
        'backing_session->process != m_process',
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
    # Native present can fail allocations before or after its NVMap dupe.
    # A later shared_ptr control-block OOM must release the duplicate and
    # the service must return a refused image instead of throwing into IPC.
    vi2_lease = text.split('IGraphicsSupervisor::GetPresentImage(u32 id) {', 1)[1].split(
        'void IGraphicsSupervisor::InitializeDisplayContext(', 1)[0]
    assert vi2_lease.index('std::make_unique<u32>(backing)') < vi2_lease.index(
        'backing_handle->Duplicate(true)') < vi2_lease.index('lease_token.release()')
    assert vi2_lease.count('catch (const std::bad_alloc&)') == 2
    image_create = text.split('void IGraphicsSupervisor::CreateNativeImage(', 1)[1].split(
        'void IGraphicsSupervisor::ConfigureNativeWindowImagePool(', 1)[0]
    assert 'catch (const std::bad_alloc&)' in image_create
    assert image_create.index('m_native_images.Create(') < image_create.index(
        'catch (const std::bad_alloc&)') < image_create.index(
        'result = Kernel::ResultOutOfResource;',
        image_create.index('catch (const std::bad_alloc&)'))
    assert (ROOT / 'tools/ns2/check_native_vi2_oom_host.py').is_file()
    for snippet in (
        'm_native_images.Create(',
        'm_native_images.Destroy(packet[2])',
        'static_cast<u32>(m_next_image_id)',
        'handle->Duplicate(true)',
        'FreeHandle(\n                image->backing, true)',
        'for (const auto& [image_id, image] : m_native_images.Records())',
    ):
        assert snippet in text, "Missing native image NVMap ownership: " + snippet
    worker = (ROOT / 'vendor/encore-active/ns2-runtime/gpu_session/core/hle/service/am/service/gpu_worker.cpp').read_text()
    dense = worker.split('Result IGpuWorker::BackGpuOnlyRegion(',1)[1].split(
        'bool IGpuWorker::RetireGpuOnlyRegion(',1)[0]
    assert dense.index('pending_region.try_emplace(') < dense.index(
        'memory.AllocateAndOpen(') < dense.index('RemapNativeSparse(') < dense.index(
        'm_dense_regions.merge(pending_region);')
    assert 'm_dense_regions.emplace(' not in dense
    assert (ROOT / 'tools/ns2/check_native_dense_ledger_oom_host.py').is_file()
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
