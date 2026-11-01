#!/usr/bin/env python3
"""Validate one shipping PS5 ExeFS owner for NS1 and NS2."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
cmake = (ROOT / "headless/CMakeLists.txt").read_text()
release = cmake.split("# Experimental ExeFS bridge", 1)[1].split(
    "# N52: process-run admission", 1
)[0]
assert 'option(EDEN_NS2_EXEFS_EXPERIMENTAL' in release
assert 'set(EDEN_SHARED_NS2_EXEFS OFF)' in release
assert 'if(PS5_NATIVE AND EDEN_FINAL_RELEASE_PROFILE AND EDEN_REVIEWED_DUAL_NPDM)' in release
assert 'set(EDEN_SHARED_NS2_EXEFS ON)' in release
assert 'if(EDEN_NS2_EXEFS_EXPERIMENTAL OR EDEN_SHARED_NS2_EXEFS)' in release
assert 'if(NOT EDEN_REVIEWED_DUAL_NPDM)' in release
assert 'set_property(TARGET core PROPERTY SOURCES' in release
for name in ("loader.cpp", "deconstructed_rom_directory.cpp"):
    assert (ROOT / "vendor/encore-active/ns2-experimental/src/core/loader" / name).is_file()
positions = [i for i in range(len(release))
             if release.startswith('if(PS5_NATIVE AND EDEN_NS2_EXEFS_EXPERIMENTAL)', i)]
assert len(positions) == 2
assert 'eden_ns2_native_nso_idx' in release[positions[0]:positions[1]]
assert 'EDEN_NS2_NATIVE_SVC_SOURCE' in release[positions[1]:]
assert 'EDEN_SHARED_NS2_EXEFS' in release
rom = (ROOT / "vendor/encore-active/ns2-experimental/src/core/loader/deconstructed_rom_directory.cpp").read_text()
loader = (ROOT / "vendor/encore-active/ns2-experimental/src/core/loader/loader.cpp").read_text()
for required in (
    "metadata.IsSwitch2()", "metadata.UsesExtendedAcid()",
    "Eden::NS2::ExeFS::PreflightNso",
    "Eden::NS2::ExeFS::AdmitKProcessCode",
    "Eden::NS2::ExeFS::MainThreadPermitted",
    "Eden::NS2::ExeFS::VerifyUncompressedTextHandoff",
):
    assert required in rom, required
assert "Eden::NS2::SvcTrace::Register" in rom
assert 'IdentifyFileLoader<AppLoader_DeconstructedRomDirectory>(file)' in loader
assert "Eden::NS2::Content::IdentifyName" in loader
assert "AppLoader_NSP" in loader and "AppLoader_XCI" in loader
assert 'set(EDEN_SHARED_NS2_AM ON)' in cmake
assert 'if(EDEN_NS2_AM_EXPERIMENTAL OR EDEN_SHARED_NS2_AM)' in cmake
am_file = (ROOT / "vendor/encore-active/ns2-runtime/am/core/hle/service/am/service/application_functions.cpp").read_text()
assert '{320, D<&IApplicationFunctions::GetScreenShotAndContinuousRecordingInitiallyEnabled>' in am_file
assert "m_applet->screenshot_permission" in am_file
assert "m_applet->game_play_recording_supported" in am_file
assert 'if(EDEN_NS2_NVDRV_EXPERIMENTAL OR EDEN_SHARED_NS2_NVDRV_CAPS)' in cmake
assert 'set(EDEN_SHARED_NS2_NVDRV_CAPS ON)' in cmake
nv = (ROOT / "vendor/encore-active/ns2-runtime/nvdrv/core/hle/service/nvdrv/devices/nvhost_ctrl_gpu.cpp").read_text()
assert "command.raw == 0xc0e04705U || command.raw == 0xc0e84705U" in nv
assert "WriteNativeCharacteristicsIoctlReply(" in nv
assert 'if(EDEN_NS2_NVDRV_EXPERIMENTAL)' in cmake
# Shared shipping branch must not select the AS/GPU research replacements.
nv_selector = cmake.split('option(EDEN_NS2_NVDRV_EXPERIMENTAL', 1)[1].split(
    '# Switch 2 GPU TIPC service', 1)[0]
assert 'if(EDEN_NS2_NVDRV_EXPERIMENTAL)' in nv_selector
assert 'eden_ns2_as_idx' in nv_selector and 'eden_ns2_gpu_idx' in nv_selector
assert 'Settings::SetNceEnabled(is_39bit && !metadata.UsesExtendedAcid())' in rom
# The shipping kernel must accept an NS2 12 GiB guest heap without changing
# the Switch 1 layout-specific cap or replacing the complete SVC dispatcher.
heap = cmake.split('# Shared kernel heap admission for Switch 2:', 1)[1].split(
    '# Research-only Switch 2 AM command 320.', 1)[0]
assert 'set(EDEN_SHARED_NS2_KERNEL_HEAP ON)' in heap
assert 'EDEN_FINAL_RELEASE_PROFILE AND EDEN_REVIEWED_DUAL_NPDM' in heap
assert 'set_property(TARGET core PROPERTY SOURCES' in heap
kernel_root = ROOT / 'vendor/encore-active/ns2-runtime/kernel/core/hle/kernel'
addr = (kernel_root / 'k_address_space_info.cpp').read_text()
svc = (kernel_root / 'svc/svc_physical_memory.cpp').read_text()
assert '.size = 16_GiB' in addr and 'KAddressSpaceInfo::Type::Heap' in addr
assert '.size = 8_GiB' in addr and 'Ns2HeapInfo' in addr
assert 'Settings::MemoryLayout::Memory_12Gb' in addr and 'return Ns2HeapInfo;' in addr
assert 'if (width == 39 && type == KAddressSpaceInfo::Type::Heap' in addr
assert 'KSystemControl::Init::GetIntendedMemorySize()' in svc
assert '(std::max)(MainMemorySizeMax,' in svc
for owner in ('hle/kernel/k_address_space_info.cpp', 'hle/kernel/svc/svc_physical_memory.cpp'):
    assert owner in heap
assert 'EDEN_NS2_KERNEL_ROOT' in heap
# A 12 GiB guest kernel cannot work if the memory layout is selected only
# later by the ExeFS loader (after InitializeKernel). Use the maintained
# native Core::System as the source ancestor, preserving NS1 optimizations.
native_core = (ROOT / 'vendor/encore-active/eden-core/src/core/core_native.cpp').read_text()
shared_core = (ROOT / 'vendor/encore-active/ns2-runtime/process/core/core.cpp').read_text()
selector = cmake.split('# The Core::System overlay is a fully maintained', 1)[1].split(
    '# RomFS builder parents', 1)[0]
assert 'EDEN_FINAL_RELEASE_PROFILE AND EDEN_REVIEWED_DUAL_NPDM' in selector
assert 'ns2-runtime/process/core/core.cpp' in selector
assert '#include "diagnostics.h"' in native_core and shared_core.startswith('#include "diagnostics.h"')
assert 'IsSwitch2ExtractedProgram(' in shared_core
assert 'metadata.Load(npdm) == Loader::ResultStatus::Success' in shared_core
assert 'metadata.IsSwitch2()' in shared_core
load = shared_core.split('SystemResultStatus Load(', 1)[1].split(
    'if (params.applet_type == Service::AM::AppletType::Application)', 1)[0]
assert load.index('IsSwitch2ExtractedProgram(') < load.index('InitializeKernel(system);')
assert 'Settings::MemoryLayout::Memory_12Gb' in load
assert 'SetGlobal(false)' in load and 'SetValue(Settings::MemoryLayout::Memory_12Gb)' in load
assert 'initialized_memory_layout != Settings::values.memory_layout_mode.GetValue()' in shared_core
assert 'bool extended_memory_layout' not in shared_core
# Real aud:u manager bridge is additive and shares maintained NS1 audio HLE.
audio_root = ROOT / 'vendor/encore-active/ns2-runtime/audio/core/hle/service/audio'
audio = (audio_root / 'audio.cpp').read_text()
client = (audio_root / 'nx2_audio_user_client.h').read_text()
audio_select = cmake.split('# Shared Switch 2 audio user service:', 1)[1].split(
    '# Research-only Switch 2 AM command 320.', 1)[0]
assert 'EDEN_FINAL_RELEASE_PROFILE AND EDEN_REVIEWED_DUAL_NPDM' in audio_select
assert 'set(EDEN_SHARED_NS2_AUDIO ON)' in audio_select
assert 'list(REMOVE_ITEM eden_ns2_audio_sources "hle/service/audio/audio.cpp")' in audio_select
assert 'set_property(TARGET core PROPERTY SOURCES' in audio_select
assert 'target_include_directories(core BEFORE PRIVATE' in audio_select
assert audio.count('RegisterNamedService("aud:u"') == 1
for name in ('audout:u', 'audren:u', 'audin:u', 'audctl', 'hwopus'):
    assert audio.count('RegisterNamedService("' + name + '"') == 1, name
for command, method, manager in (
    (1, 'GetAudioOutManager', 'IAudioOutManager'),
    (2, 'GetAudioRendererManager', 'IAudioRendererManager')):
    assert '{' + str(command) + ', &INx2AudioUserClient::' + method in client
    assert 'rb.PushIpcInterface<' + manager + '>(ctx, system)' in client
assert 'auto stub fallback' not in client.lower()
streamplay = (audio_root.parent / 'nx2_streamplay.h').read_text()
assert audio.count('RegisterNamedService("stpl:u"') == 1
assert '{0, &INx2StreamPlayService::GetUserService' in streamplay
assert '{300, &INx2StreamPlayUserService::GetEvent' in streamplay
assert 'service_context.CreateEvent(' in streamplay
assert 'service_context.CloseEvent(event)' in streamplay
assert 'rb.PushCopyObjects(ctx, event->GetReadableEvent())' in streamplay
assert 'rb.PushIpcInterface<INx2StreamPlayUserService>(ctx, system)' in streamplay

# Shared NS2 GPU-access SVC 0x80 is restricted to an actual NS2
# ExeFS process and the 12 GiB profile; no blanket success of unknown calls.
gpu_svc = (ROOT / 'vendor/encore-active/ns2-runtime/gpu_access_svc/core/hle/kernel/svc.cpp').read_text()
assert 'Eden::NS2::SvcTrace::IsActive(process.GetProcessId())' in gpu_svc
assert 'Settings::MemoryLayout::Memory_12Gb' in gpu_svc
assert 'process.GetPageTable().Contains(address, size)' in gpu_svc
assert 'else if (process.Is64Bit())' in gpu_svc
print("ENCORE_NS2_SHARED_EXEFS_SHIPPING_OWNER_PASS release=one ns1_nso_preserved=1 ns2_am_320=1 nvdrv_caps=1 kernel_heap=1 prekernel_layout=1 audio_u=1 streamplay=1")
