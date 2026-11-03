// SPDX-License-Identifier: GPL-3.0-or-later
// Synthetic request fixtures: no SDK, firmware, content, PS5 execution or GPU submission.
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <span>
#include "core/hle/service/am/service/gpu_memory_registration.h"
#include "core/hle/service/am/service/graphics_supervisor_protocol.h"
#include "core/hle/service/am/service/native_image_layout.h"
#include "core/hle/service/nvdrv/devices/native_gpu_kind.h"
#include "core/hle/service/nvdrv/devices/native_gpu_context.h"
#include "core/hle/service/am/service/graphics_syncpoint_cache.h"
#include "core/hle/service/am/service/gpu_session_protocol.h"
#include "core/hle/service/am/service/graphics_supervisor_bootstrap.h"
#include "core/hle/service/am/service/gpu_worker_protocol.h"

static int assertions=0;
static void require(bool condition,const char* desc){
    ++assertions;
    if(!condition){std::fprintf(stderr,"NS2 HLE fixture FAILED: %s\n",desc);std::exit(1);}
}
int main(){
    using namespace Service::AM;
    namespace P=Service::AM::GraphicsSupervisorProtocol;
    namespace N=Service::Nvidia::Devices;
    const std::array<u32,8> reg{0x75,6,0x1000,0,0x2fff,0,0xaabbcc05,0xff000006};
    const auto r=DecodeGpuMemoryRegistration(reg);
    require(r && r->begin==0x1000 && r->end==0x2fff,"GPU registration bounds");
    require(r && r->flags==5 && r->device==6,"GPU registration padding ignored");
    require(!DecodeGpuMemoryRegistration(std::span<const u32>(reg.data(),7)),
            "GPU registration rejects short request");
    const std::array<u32,8> gpuMemoryValid{0x75,6,0x1000,0,0x2fff,0,0,0x12340001};
    const auto validMemory=DecodeGpuMemoryRegistration(gpuMemoryValid);
    require(validMemory && IsValidGpuMemoryRegistrationRange(*validMemory) &&
            validMemory->device==1 && validMemory->flags==0,
            "GPU memory registration preflight accepts 4K aligned live device");
    auto malformedMemory=gpuMemoryValid;
    malformedMemory[2]=0x1001;
    require(!IsValidGpuMemoryRegistrationRange(*DecodeGpuMemoryRegistration(malformedMemory)),
            "reject GPU memory page misalignment before NVMap locking");
    malformedMemory=gpuMemoryValid;malformedMemory[4]=0x2000;
    require(!IsValidGpuMemoryRegistrationRange(*DecodeGpuMemoryRegistration(malformedMemory)),
            "reject GPU memory fractional final page");
    malformedMemory=gpuMemoryValid;malformedMemory[4]=0;malformedMemory[5]=0;
    require(!IsValidGpuMemoryRegistrationRange(*DecodeGpuMemoryRegistration(malformedMemory)),
            "reject negative GPU memory inclusive size");
    malformedMemory=gpuMemoryValid;malformedMemory[4]=0xffffffff;malformedMemory[5]=0xffffffff;
    require(!IsValidGpuMemoryRegistrationRange(*DecodeGpuMemoryRegistration(malformedMemory)),
            "reject 64-bit max inclusive GPU memory end");
    malformedMemory=gpuMemoryValid;malformedMemory[7]=0;
    require(!IsValidGpuMemoryRegistrationRange(*DecodeGpuMemoryRegistration(malformedMemory)),
            "reject reserved zero device ID");
    const std::array<u32,4> gpuMemoryRelease{0x76,2,4,63};
    const auto release=DecodeGpuMemoryRelease(gpuMemoryRelease);
    require(release && release->id==4 && release->notification==63,
            "GPU memory release validates actual NVMap handle and notification");
    auto invalidRelease=gpuMemoryRelease;invalidRelease[2]=0;
    require(!DecodeGpuMemoryRelease(invalidRelease),"release refuses reserved NVMap handle");
    invalidRelease=gpuMemoryRelease;invalidRelease[3]=64;
    require(!DecodeGpuMemoryRelease(invalidRelease),"release refuses out-of-range notification");
    invalidRelease=gpuMemoryRelease;invalidRelease[1]=3;
    require(!DecodeGpuMemoryRelease(invalidRelease),"release rejects incorrect word count");
    require(!DecodeGpuMemoryRelease(std::span<const u32>{gpuMemoryRelease.data(),3}),
            "release refuses truncated TIPC packet");
    auto badreg=reg;badreg[1]=5;
    require(!DecodeGpuMemoryRegistration(badreg),"GPU registration rejects wrong size");
    badreg=reg;badreg[0]=0x76;
    require(!DecodeGpuMemoryRegistration(badreg),"GPU registration rejects wrong command");

    std::array<u32,16> bootstrap{};
    bootstrap[0]=0x14; bootstrap[1]=0x8000000c;bootstrap[2]=2;
    bootstrap[3]=0x1234;bootstrap[4]=0xabc;bootstrap[6]=5;bootstrap[7]=0x80000000;
    auto br=P::DecodeBootstrap(bootstrap);
    require(br && br->process_handle==0x1234 && br->applet_resource_user_id==0xabc,
            "bootstrap handle and application resource ID");
    require(br && br->flags==0x8000000000000005ULL && P::IsLocalBootstrap(*br),
            "bootstrap native profile 0x807");
    require(P::NativeGpuProfileForBootstrap(br->flags)==0x807,"GPU profile 0x807");
    bootstrap[6]=6;
    br=P::DecodeBootstrap(bootstrap);
    require(br && P::NativeGpuProfileForBootstrap(br->flags)==0x808,
            "GPU profile 0x808");
    bootstrap[8]=1;
    br=P::DecodeBootstrap(bootstrap);
    require(br && !P::IsLocalBootstrap(*br),"nonzero remote memory rejected");
    bootstrap[8]=0;bootstrap[2]=1;
    require(!P::DecodeBootstrap(bootstrap),"bootstrap handle mode rejected");
    bootstrap[2]=2;bootstrap[1]=0;
    require(!P::DecodeBootstrap(bootstrap),"bootstrap malformed header rejected");

    const std::array<u32,5> duplicate{0x30,0x80000001,2,0x99,3};
    auto dup=P::DecodeRequestGroupEventDuplicate(duplicate);
    require(dup && dup->group==3 && dup->copied_handle==0x99,"request group duplicate");
    require(P::ClassifyRequestGroupEventDuplicate(3,true,true,true)==
            P::RequestGroupDuplicateStatus::Ready,"valid request group");
    require(P::ClassifyRequestGroupEventDuplicate(8,true,true,true)==
            P::RequestGroupDuplicateStatus::OutOfRange,"request group out of range");
    require(P::ClassifyRequestGroupEventDuplicate(3,false,true,true)==
            P::RequestGroupDuplicateStatus::NotConfigured,"unconfigured request group");
    require(P::ClassifyRequestGroupEventDuplicate(3,true,false,true)==
            P::RequestGroupDuplicateStatus::MissingEvent,"missing request event");
    require(P::ClassifyRequestGroupEventDuplicate(3,true,true,false)==
            P::RequestGroupDuplicateStatus::IdentityMismatch,"request event identity mismatch");
    const std::array<u32,7> sync{0xd9,5,3,~u32{9},123,0,0};
    auto wait=P::DecodeSyncpointWait(sync);
    require(wait && wait->slot==3 && wait->id==9 && wait->threshold==123 && !wait->wide,
            "syncpoint packet decoding");
    require(P::IsSyncpointWaitSatisfied(124,123,false),"modular syncpoint satisfied");
    require(!P::IsSyncpointWaitSatisfied(122,123,false),"modular syncpoint pending");
    require(!P::IsSyncpointWaitSatisfied(1,0x100000001ULL,true),
            "wide syncpoint checks full threshold");
    require(P::DecodeBufferSlot(0x1234)==0x34,"packed buffer slot");
    // Guest VI2 timing, not a title-specific performance override.
    require(P::DecodePresentSwapInterval(0)==1,"zero-timing legacy 60 Hz default");
    require(P::DecodePresentSwapInterval(60)==1,"single-vblank 60 Hz default");
    require(P::DecodePresentSwapInterval((1U<<16)|60)==1,"guest one vblank");
    require(P::DecodePresentSwapInterval((2U<<16)|60)==2,"guest two vblanks at 30 FPS");
    require(P::DecodePresentSwapInterval((3U<<16)|120)==3,"guest three vblanks");
    require(P::DecodePresentSwapInterval((4U<<16)|60)==4,"guest four vblanks");
    require(P::DecodePresentSwapInterval((5U<<16)|60)==4,"unsupported interval bounded");
    require(P::DecodePresentSwapInterval(0xffffffff)==4,"malformed interval bounded");

    std::array<u32,16> preferences{};
    preferences[0]=0;preferences[1]=1;preferences[2]=(63<<16)|127; // 128x64
    preferences[3]=0;preferences[4]=4;preferences[5]=8;preferences[6]=1;
    preferences[7]=1;
    const auto req=CalculateNativeImageRequirements(preferences,2);
    require(req && req->size==65536 && req->alignment==4096,
            "RGBA image block height/stride and count");
    require(!CalculateNativeImageRequirements(preferences,0),"reject zero image count");
    preferences[5]=7;
    require(!CalculateNativeImageRequirements(preferences,1),"reject short pitch");
    preferences[5]=8;preferences[8]=1;
    require(!CalculateNativeImageRequirements(preferences,1),"reject extra format flags");
    preferences[8]=0;preferences[4]=9;
    require(!CalculateNativeImageRequirements(preferences,1),"reject unsupported block height");
    preferences[4]=4;preferences[6]=0;
    require(!CalculateNativeImageRequirements(preferences,1),"reject unknown color layout");

    // Sparse NVGPU MMU ABI and mapping lifetime, sourced from latest pinned NS2.
    N::NativeSparseRemapEntry entry{};
    entry.flags=0x1000;entry.kind=6;entry.fallback_kind=6;
    entry.handle=7;entry.source_pages=2;entry.destination_pages=0x10;entry.pages=4;
    auto decoded=N::DecodeNativeSparseRemap(entry);
    require(decoded && decoded->address==0x10000 && decoded->size==0x4000 &&
            decoded->source_offset==0x2000 && decoded->handle==7,
            "native sparse 4-KiB mapping");
    entry.flags=0x2000;entry.pages=1;
    decoded=N::DecodeNativeSparseRemap(entry);
    require(decoded && decoded->size==0x10000,"native sparse 64-KiB page size");
    entry.flags=0x3000;
    require(!N::DecodeNativeSparseRemap(entry),"reject multiple page-size flags");
    entry.flags=0x1000;entry.pages=0;
    require(!N::DecodeNativeSparseRemap(entry),"reject empty sparse mapping");
    entry.pages=4;entry.source_pages=~u64{0};
    require(!N::DecodeNativeSparseRemap(entry),"reject sparse source overflow");
    entry.source_pages=2;entry.handle=0;
    require(!N::DecodeNativeSparseRemap(entry),"reject source on unmapped handle");
    entry.handle=7;entry.reserved=1;
    require(!N::DecodeNativeSparseRemap(entry),"reject sparse reserved field");
    entry.reserved=0;entry.flags=0x1000;
    require(N::DecodeNativeSparseRemap(entry).has_value(),"accept restored mapping");

    N::NativeSparseMappingTable table;
    table.Replace({0x1000,0x4000,0x10000,7});
    table.Replace({0x2000,0x1000,0x20000,9});
    const auto& ranges=table.Ranges();
    require(ranges.size()==3,"split overlapping sparse mapping into three regions");
    require(ranges.at(0x1000).size==0x1000 && ranges.at(0x1000).handle==7,
            "preserve left sparse fragment");
    require(ranges.at(0x2000).size==0x1000 && ranges.at(0x2000).handle==9,
            "insert overlapping sparse owner");
    require(ranges.at(0x3000).size==0x2000 &&
            ranges.at(0x3000).source_offset==0x12000,
            "advance right fragment physical offset");
    require(table.ReferencedHandles().size()==2,"both sparse backing handles pinned");
    table.Replace({std::numeric_limits<u64>::max()-0xff,0x200,0,44});
    table.Replace({0x6000,0,0,44});
    table.Replace({0x6000,0x200,std::numeric_limits<u64>::max()-0xff,44});
    require(table.Ranges().size()==3 && table.ReferencedHandles().size()==2,
            "reject overflowing and empty sparse mapping without dropping handles");
    table.Replace({0x2000,0x1000,0,0});
    require(table.Ranges().size()==2 && table.ReferencedHandles().size()==1 &&
            table.ReferencedHandles().contains(7),
            "unmap sparse middle range and release old handle");

    GpuSparseMapRequest gm{};
    gm.address=0x10000;gm.size=0x2000;gm.kind=6;
    gm.fallback_kind=6;gm.cache=1;gm.memory=7;gm.source_offset=0x4000;
    const auto gpuMap=DecodeGpuSparseMap(gm);
    require(gpuMap && gpuMap->flags==0x1004 &&
            gpuMap->destination_pages==0x10 && gpuMap->source_pages==4,
            "GPU request maps to 4-KiB sparse ioctl entry");
    gm.address=0x10001;
    require(!DecodeGpuSparseMap(gm),"reject unaligned sparse destination");
    gm.address=0x10000;gm.read_only=1;
    require(!DecodeGpuSparseMap(gm),"reject unsupported sparse read-only flag");
    gm.read_only=0;gm.comptag_mode=1;
    require(!DecodeGpuSparseMap(gm),"reject unsupported sparse compression tag");
    gm.comptag_mode=0;gm.cache=2;
    require(!DecodeGpuSparseMap(gm),"reject unsupported sparse caching mode");
    gm.cache=1;gm.reserved2=1;
    require(!DecodeGpuSparseMap(gm),"reject unknown sparse extension");

    std::array<u32,12> region{0xe6,10,8,0x10000,0,0x1ffff,0,12,0,1,0,0};
    auto regionReq=DecodeGpuSparseRegion(region);
    require(regionReq && regionReq->address_space==8 &&
            IsValidGpuSparseRegionRange(*regionReq),"valid sparse region boundary");
    region[5]=0x1ffe0;
    regionReq=DecodeGpuSparseRegion(region);
    require(regionReq && !IsValidGpuSparseRegionRange(*regionReq),
            "reject unaligned sparse end");
    region[5]=0x1ffff;region[7]=15;
    regionReq=DecodeGpuSparseRegion(region);
    require(regionReq && !IsValidGpuSparseRegionRange(*regionReq),
            "reject unsupported sparse page shift");
    region[7]=12;region[5]=0xffffffff;region[6]=0xffffffff;
    regionReq=DecodeGpuSparseRegion(region);
    require(regionReq && !IsValidGpuSparseRegionRange(*regionReq),
            "reject inclusive maximum end overflow");
    require(!DecodeGpuSparseRegion(std::span<const u32>(region.data(),11)),
            "reject truncated sparse region request");
    // Dense GPU-only render backing uses actual kernel pages + NVMap, not
    // an unbacked sparse VA or an optimistic success on allocation failure.
    require(CanBackNativeDenseGpuOnly(0, 300ULL << 20, 0,
                                     3ULL << 30),
            "bounded 300 MiB GPU-only backing can be admitted");
    require(CanBackNativeDenseGpuOnly(0, 300ULL << 20, 1500ULL << 20,
                                     512ULL << 20),
            "six 300 MiB render targets stay inside 2 GiB budget");
    require(!CanBackNativeDenseGpuOnly(1, 300ULL << 20, 0, 3ULL << 30),
            "sparse allocation mode must not be marked dense resident");
    require(!CanBackNativeDenseGpuOnly(0, 513ULL << 20, 0, 3ULL << 30),
            "huge virtual textures cannot exhaust dense allocation pool");
    require(!CanBackNativeDenseGpuOnly(0, 300ULL << 20, 1800ULL << 20,
                                      3ULL << 30),
            "reject dense backing above combined per-session budget");
    require(!CanBackNativeDenseGpuOnly(0, 300ULL << 20, 0, 350ULL << 20),
            "preserve minimum free memory reserve");
    require(!CanBackNativeDenseGpuOnly(0, 0x1001, 0, 3ULL << 30),
            "reject unaligned native dense backing");
    require(!CanBackNativeDenseGpuOnly(0, 300ULL << 20, ~u64{0}, 3ULL << 30),
            "reject counter overflow / stale allocation accounting");

    std::array<u8,4> legacyTsg{21,0,0,0};
    auto tsg=N::DecodeNativeTsgBinding(legacyTsg,false);
    require(tsg && tsg->channel_fd==21 && tsg->subcontext_id==0,
            "legacy native GPU binding");
    require(!N::DecodeNativeTsgBinding(legacyTsg,true),
            "reject short extended native GPU binding");
    legacyTsg.fill(0xff);
    require(!N::DecodeNativeTsgBinding(legacyTsg,false),
            "reject negative GPU file descriptor");
    std::array<u8,24> extendedTsg{};
    extendedTsg[0]=21;extendedTsg[4]=63;
    tsg=N::DecodeNativeTsgBinding(extendedTsg,true);
    require(tsg && tsg->channel_fd==21 && tsg->subcontext_id==63,
            "largest native GPU subcontext id");
    extendedTsg[4]=64;
    require(!N::DecodeNativeTsgBinding(extendedTsg,true),
            "reject out of range native GPU subcontext");
    extendedTsg[4]=63;extendedTsg[23]=1;
    require(!N::DecodeNativeTsgBinding(extendedTsg,true),
            "reject nonzero native GPU extension bytes");
    extendedTsg[23]=0;
    require(!N::DecodeNativeTsgBinding(
        std::span<const u8>(extendedTsg.data(),23),true),
        "reject truncated GPU binding");
    require(N::GetNativeGpuContextSlot(0xc797)==std::optional<u32>{1} &&
            N::GetNativeGpuContextSlot(0xc7c0)==std::optional<u32>{2} &&
            N::GetNativeGpuContextSlot(0xc7b5)==std::optional<u32>{4} &&
            N::GetNativeGpuContextSlot(0xc56f)==std::optional<u32>{5},
            "native context identities");
    require(!N::GetNativeGpuContextSlot(0xb197),
            "legacy Maxwell context is not native");
    namespace Cache=Service::AM::GraphicsSyncpointCache;
    static_assert(Cache::CounterCount==192 && Cache::GroupCount==3);
    require(Cache::Header[0]==1 && Cache::Header[2]==191,
            "graphics syncpoint memory layout");
    require(Cache::ExtendCounter(Cache::Unallocated,12)==12,
            "first syncpoint sample");
    require(Cache::ExtendCounter(0x1fffffffeULL,1)==0x200000001ULL,
            "extend 32-bit syncpoint across counter wrap");
    Cache::CounterValue syncCounter{};
    require(syncCounter.Observe(std::nullopt)==Cache::Unallocated,
            "empty syncpoint observation");
    require(syncCounter.Observe(0xfffffffe)==0xfffffffeULL,
            "initial near-wrap counter");
    require(syncCounter.Observe(1)==0x100000001ULL,
            "syncpoint counter wrap");
    require(syncCounter.Observe(std::nullopt)==Cache::Unallocated &&
            syncCounter.previous==0x100000001ULL,
            "missing counter should not clear last observed value");

    namespace GP=Service::AM::GpuSessionProtocol;
    namespace GS=Service::AM::GraphicsSupervisorBootstrap;
    GS::State state{0xabc};
    std::array<GP::U32,16> gsBootstrap{};
    gsBootstrap[0]=0x14;gsBootstrap[1]=0x8000000c;gsBootstrap[2]=2;
    gsBootstrap[3]=0x1234;gsBootstrap[4]=0xabc;gsBootstrap[6]=5;
    gsBootstrap[7]=0x80000000;
    const std::array<GP::U32,3> bindProcess{0x1b,0x80000000,2};
    const std::array<GP::U32,2> completeBootstrap{0x75,0};
    const std::array<GP::U32,2> initGpu{417,0};
    const std::array<GP::U32,2> activateGpu{418,0};
    const std::array<GP::U32,4> openGpu{0x201,2,4,0};
    require(state.Complete(completeBootstrap)==GS::Status::InvalidState &&
            state.InitializeGpuContext(initGpu,401)==GS::Status::InvalidState &&
            state.CanOpenGpuSession(openGpu,true)==GS::Status::InvalidState,
            "graphics supervisor must reject calls before process bootstrap");
    require(state.Initialize(gsBootstrap,false)==GS::Status::InvalidHandle &&
            state.CurrentPhase()==GS::Phase::Created,
            "invalid process handle must not advance bootstrap");
    gsBootstrap[4]=0xdef;
    require(state.Initialize(gsBootstrap,true)==GS::Status::InvalidArgument &&
            state.CurrentPhase()==GS::Phase::Created,
            "mismatched applet ARUID does not mutate state");
    gsBootstrap[4]=0xabc;
    require(state.Initialize(gsBootstrap,true)==GS::Status::Success &&
            state.CurrentPhase()==GS::Phase::Initialized &&
            state.NativeProfile()==0x807,
            "valid graphics supervisor bootstrap negotiates sm87 profile");
    require(state.Initialize(gsBootstrap,true)==GS::Status::InvalidState,
            "duplicate bootstrap must not reinitialize GPU profile");
    require(state.BindProcess(bindProcess,false)==GS::Status::InvalidHandle &&
            state.CurrentPhase()==GS::Phase::Initialized,
            "reject invalid process bind identity");
    require(state.BindProcess(bindProcess,true)==GS::Status::Success &&
            state.CurrentPhase()==GS::Phase::ProcessBound &&
            state.Complete(completeBootstrap)==GS::Status::Success &&
            state.CurrentPhase()==GS::Phase::Ready,
            "graphics supervisor requires ordered bootstrap phases");
    require(state.Complete(completeBootstrap)==GS::Status::InvalidState,
            "duplicate graphics supervisor completion rejected");
    require(state.InitializeGpuContext(activateGpu,402)==GS::Status::InvalidState &&
            !state.GpuContextReady(),
            "activate GPU context cannot precede initialization");
    require(state.InitializeGpuContext(initGpu,401)==GS::Status::Success &&
            state.InitializeGpuContext(activateGpu,402)==GS::Status::Success &&
            state.GpuContextReady(),
            "GPU context initialization followed by activation");
    require(state.CanOpenGpuSession(openGpu,false)==GS::Status::InvalidState &&
            state.CanOpenGpuSession(openGpu,true)==GS::Status::Success,
            "GPU session requires completed bootstrap and real NVDRV module");
    auto badOpen=openGpu;
    badOpen[2]=8;
    require(state.CanOpenGpuSession(badOpen,true)==GS::Status::InvalidPacket,
            "GPU session opening rejects unsupported flags");
    badOpen=openGpu;badOpen[0]=0x202;
    require(state.CanOpenGpuSession(badOpen,true)==GS::Status::InvalidPacket,
            "GPU session opening rejects wrong TIPC command");
    GS::State unsupported{0xabc};
    auto remoteBootstrap=gsBootstrap;
    remoteBootstrap[8]=1;
    require(unsupported.Initialize(remoteBootstrap,true)==GS::Status::Unsupported &&
            unsupported.CurrentPhase()==GS::Phase::Created,
            "remote graphics bootstrap cannot falsely report success");
    GS::State newer{0xabc};
    auto sm88Bootstrap=gsBootstrap;
    sm88Bootstrap[6]=6;
    require(newer.Initialize(sm88Bootstrap,true)==GS::Status::Success &&
            newer.NativeProfile()==0x808,
            "sm88 GPU profile negotiated without publishing GPU capabilities");

    static_assert(GP::MaxDevices==256 && GP::MaxNotificationEvents==64 &&
                  GP::MaxAddressSpaces==8);
    constexpr std::array<GP::U32,8> createPacket{
        0x39,6,0x12345678,0xabcdef01,0,0,0x55667788,0x99aabbcc};
    const auto deviceRequest=GP::DecodeCreateDevice(createPacket);
    require(deviceRequest && deviceRequest->name==0xabcdef0112345678ULL &&
            deviceRequest->debug_label==0x99aabbcc55667788ULL,
            "native GPU session device identity pairs");
    GP::DeviceSlots devices;
    const auto first=devices.Create(createPacket);
    require(first.status==GP::Status::Success && first.id==1 &&
            devices.Get(1) && devices.Get(1)->name==deviceRequest->name,
            "GPU device slot starts at 1");
    auto unsupportedDevice=createPacket;
    unsupportedDevice[4]=1;
    require(devices.Create(unsupportedDevice).status==GP::Status::Unsupported &&
            devices.Count()==1,
            "unsupported GPU creation flags do not allocate slots");
    auto malformedDevice=createPacket;
    malformedDevice[0]=0x38;
    require(devices.Create(malformedDevice).status==GP::Status::InvalidPacket &&
            devices.Count()==1,
            "invalid GPU creation command does not allocate slots");
    GP::DeviceSlots full;
    for (GP::U32 id=1;id<GP::MaxDevices;++id) {
        const auto result=full.Create(createPacket);
        require(result.status==GP::Status::Success && result.id==id,
                "GPU device slot ordering");
    }
    require(full.Count()==255 &&
            full.Create(createPacket).status==GP::Status::OutOfResource,
            "GPU device limit fails without overwriting slot zero");
    const std::array<GP::U32,3> destroyDevice{0x3a,1,255};
    require(full.Destroy(destroyDevice)==GP::Status::Success &&
            full.Count()==254 && !full.Get(255),
            "highest GPU device id can be destroyed");
    require(full.Destroy(destroyDevice)==GP::Status::NotFound,
            "duplicate GPU device destroy is reported");
    require(full.Create(createPacket).id==255,
            "freed GPU device ID reused");
    const std::array<GP::U32,3> outOfRangeDevice{0x3a,1,256};
    const std::array<GP::U32,3> truncatedDevice{0x3a,1,0x101};
    const std::array<GP::U32,3> zeroDevice{0x3a,1,0};
    require(full.Destroy(outOfRangeDevice)==GP::Status::InvalidPacket &&
            full.Destroy(truncatedDevice)==GP::Status::InvalidPacket &&
            full.Destroy(zeroDevice)==GP::Status::InvalidPacket &&
            full.Count()==255,
            "destroy must not truncate 32-bit ID to 8-bit alias");
    // Real fd lifecycle is owned by the NVDRV module, not this pure bounded
    // registry. Failed opens/IOCTLs must not call Add().
    GP::AddressSpaceSlots addressSpaces;
    require(addressSpaces.HasCapacity() && addressSpaces.Count()==0 &&
            !addressSpaces.Owns(1) && !addressSpaces.Registered(1) &&
            addressSpaces.Register(1)==GP::Status::NotFound,
            "unallocated GPU VA must not be advertised or registered");
    const std::array<GP::U32,3> makeAs{0x31,1,0};
    const std::array<GP::U32,3> registerAs{0x1c2,1,42};
    const std::array<GP::U32,3> invalidMakeAs{0x31,1,1};
    const std::array<GP::U32,3> badRegisterAs{0x1c2,1,0};
    const std::array<GP::U32,3> wrappedRegister{0x1c2,1,0xffffffff};
    require(GP::IsCreateAddressSpace(makeAs) &&
            !GP::IsCreateAddressSpace(invalidMakeAs) &&
            GP::DecodeRegisterAddressSpace(registerAs)==std::optional<GP::U32>{42} &&
            !GP::DecodeRegisterAddressSpace(badRegisterAs) &&
            !GP::DecodeRegisterAddressSpace(wrappedRegister),
            "GPU VA commands reject invalid command words and full-width IDs");
    require(addressSpaces.Add(0)==GP::Status::InvalidPacket &&
            addressSpaces.Add(0xffffffff)==GP::Status::InvalidPacket &&
            addressSpaces.Count()==0,
            "GPU VA refuses reserved and overflowing fd");
    require(addressSpaces.Add(42)==GP::Status::Success &&
            addressSpaces.Add(42)==GP::Status::InvalidState &&
            addressSpaces.Count()==1 && !addressSpaces.Registered(42),
            "GPU VA fd ownership must be unique and initially unregistered");
    require(addressSpaces.Register(42)==GP::Status::Success &&
            addressSpaces.Registered(42) && addressSpaces.Count()==1,
            "supervisor registers only owned successful NVDRV fds");
    for(GP::U32 id=43;id<50;++id)
        require(addressSpaces.Add(id)==GP::Status::Success,
                "NVDRV fd allocation fills bounded GPU VA slots");
    require(addressSpaces.Count()==8 && !addressSpaces.HasCapacity() &&
            addressSpaces.Add(50)==GP::Status::OutOfResource &&
            addressSpaces.Count()==8 &&
            addressSpaces.Register(50)==GP::Status::NotFound,
            "GPU VA capacity is eight and overflow cannot mutate ownership");
    const auto owned=addressSpaces.OwnedIds();
    require(owned[0]==std::optional<GP::U32>{42} &&
            owned[7]==std::optional<GP::U32>{49} &&
            !addressSpaces.Registered(49),
            "GPU VA destructor can enumerate all owned fds for cleanup");
    require(GP::AddressSpaceRegionEnd(0x1000,1,0x1000)==
            std::optional<GP::U64>{0x1fff} &&
            GP::AddressSpaceRegionEnd(0x1000,0,0x1000)==std::nullopt &&
            GP::AddressSpaceRegionEnd(0x1000,1,0)==std::nullopt &&
            GP::AddressSpaceRegionEnd(0x1000,std::numeric_limits<GP::U64>::max(),2)==std::nullopt &&
            GP::AddressSpaceRegionEnd(std::numeric_limits<GP::U64>::max(),1,2)==std::nullopt,
            "NVDRV VA region query must reject zero sizes and uint64 overflow");
    const std::array<GP::U32,3> partition{219,1,17};
    const auto part=GP::DecodeAddressSpacePartition(partition,203);
    require(part && part->address_space==17 && part->user,
            "TIPC user GPU address-space partition");
    require(!GP::DecodeAddressSpacePartition(partition,202),
            "GPU partition header must match command");
    GP::NotificationSlots notifications;
    const std::array<GP::U32,2> notifyRange{0x1b,0};
    const std::array<GP::U32,3> requestWorker{0x25,1,63};
    const std::array<GP::U32,3> badWorker{0x25,1,64};
    const std::array<GP::U32,3> eventPacket{0x1c,1,63};
    require(GP::IsGetNotificationRange(notifyRange) &&
            GP::DecodeEventIndex(eventPacket,0x1c)==std::optional<GP::U32>{63},
            "GPU notification range and maximum event index");
    require(notifications.RequestWorker(requestWorker)==GP::Status::InvalidState &&
            notifications.MarkEvent(63)==GP::Status::Success &&
            notifications.RequestWorker(requestWorker)==GP::Status::Success,
            "GPU worker requires a real allocated notification slot");
    require(notifications.RequestWorker(badWorker)==GP::Status::InvalidPacket &&
            notifications.MarkEvent(64)==GP::Status::InvalidPacket,
            "out of range event index rejected");
    const std::array<GP::U32,2> acquireWorker{0x26,0};
    require(GP::IsAcquireWorker(acquireWorker),
            "worker acquisition TIPC envelope validated");
    const std::array<GP::U32,2> badAcquireWorker{0x26,1};
    const std::array<GP::U32,3> badWorkerCommand{0x24,1,63};
    require(!GP::IsAcquireWorker(badAcquireWorker) &&
            !GP::DecodeEventIndex(badWorkerCommand,0x25) &&
            !GP::DecodeEventIndex(std::span<const GP::U32>{requestWorker.data(),2},0x25),
            "worker requests must reject malformed TIPC envelopes");
    require(notifications.RequestWorker(requestWorker)==GP::Status::Success &&
            notifications.HasEvent(63) && !notifications.HasEvent(64),
            "worker request can repeat only for a real notification event");


    // Native 4-KiB mapping ABI is tested independently; no live handler yet.
    namespace WP=Service::AM::GpuWorkerProtocol;
    static_assert(WP::PageSize==4096 && WP::MaxNotifications==64 &&
                  WP::MaxMappings==4096);
    std::array<WP::U32,18> rawMap{
        0xe3,16,9,0x4000,0,0x5fff,0,17,0x1000,0,0,1,6,6,0,1,1,63};
    const auto map=WP::DecodeMap(rawMap);
    require(map && map->address_space==9 && map->memory==17 &&
            map->address==0x4000 && map->size==0x2000 &&
            map->memory_offset==0x1000 && map->selected_kind==6 &&
            map->notification==63 && map->device==1,
            "NS2 4K mapping packet decodes full-width VA, resource and native kind");
    auto mutated=rawMap;
    mutated[11]=0xdeadbe01;mutated[12]=0xcafe0006;mutated[13]=0xbeef0006;
    mutated[15]=0x10001;mutated[16]=0xffffff01;
    require(WP::DecodeMap(mutated).has_value(),
            "TIPC byte fields ignore undefined upper padding bits");
    mutated=rawMap;mutated[0]=0xe2;
    require(!WP::DecodeMap(mutated), "wrong command header rejected");
    mutated=rawMap;mutated[10]=1;
    require(!WP::DecodeMap(mutated), "unsupported permission rejected");
    mutated=rawMap;mutated[11]=2;
    require(!WP::DecodeMap(mutated), "invalid cache mode rejected");
    mutated=rawMap;mutated[14]=1;
    require(!WP::DecodeMap(mutated), "unknown map mode rejected");
    mutated=rawMap;mutated[16]=2;
    require(!WP::DecodeMap(mutated), "invalid sync mode rejected");
    mutated=rawMap;mutated[17]=64;
    require(!WP::DecodeMap(mutated), "event index 64 rejected");
    mutated=rawMap;mutated[15]=0;
    require(!WP::DecodeMap(mutated), "device zero reserved");
    mutated=rawMap;mutated[7]=0;
    require(!WP::DecodeMap(mutated), "unallocated memory ID rejected");
    mutated=rawMap;mutated[3]=0x4001;
    require(!WP::DecodeMap(mutated), "unaligned VA rejected");
    mutated=rawMap;mutated[5]=0x5000;
    require(!WP::DecodeMap(mutated), "unaligned inclusive end rejected");
    mutated=rawMap;mutated[8]=0x1001;
    require(!WP::DecodeMap(mutated), "unaligned memory offset rejected");
    mutated=rawMap;mutated[5]=0xffffffff;mutated[6]=0xffffffff;
    require(!WP::DecodeMap(mutated), "uint64 inclusive end cannot wrap");
    mutated=rawMap;mutated[8]=0xfffff000;mutated[9]=0xffffffff;
    require(!WP::DecodeMap(mutated), "physical source offset overflow rejected");
    mutated=rawMap;mutated[12]=8;mutated[13]=7;
    require(!WP::DecodeMap(mutated), "unknown native kind rejected");
    mutated=rawMap;mutated[12]=8;mutated[13]=6;
    require(WP::DecodeMap(mutated) && WP::DecodeMap(mutated)->selected_kind==6,
            "compressed kind explicitly falls back to supported one");
    require(!WP::DecodeMap(std::span<const WP::U32>{rawMap.data(),17}),
            "truncated raw worker message rejected");
    const std::array<WP::U32,9> rawUnmap{
        0xe5,7,9,0x4000,0,0x5fff,0,1,63};
    const auto unmap=WP::DecodeUnmap(rawUnmap);
    require(unmap && unmap->size==0x2000 && unmap->sync==1,
            "unmap uses matching inclusive 4K range");
    auto badUnmap=rawUnmap;badUnmap[8]=64;
    require(!WP::DecodeUnmap(badUnmap), "unmap event index bounded");
    badUnmap=rawUnmap;badUnmap[5]=0x6000;
    require(!WP::DecodeUnmap(badUnmap), "unmap rejects fractional page");
    const std::array<WP::U32,11> rawModify{
        0xe4,9,9,0x5000,0,0x5fff,0,8,6,1,63};
    const auto modify=WP::DecodeModify(rawModify);
    require(modify && modify->size==4096 && modify->selected_kind==6,
            "modify kind uses valid fallback and page size");
    auto badModify=rawModify;badModify[10]=64;
    require(!WP::DecodeModify(badModify), "modify event index bounded");
    badModify=rawModify;badModify[8]=7;
    require(!WP::DecodeModify(badModify), "unsupported modify kind rejected");

    WP::MappingLedger ledger;
    require(ledger.CanMap(*map)==WP::LedgerStatus::Success &&
            ledger.RecordMapped(*map)==WP::LedgerStatus::Success &&
            ledger.Count()==1, "ledger records only committed GPU mapping");
    require(ledger.RecordMapped(*map)==WP::LedgerStatus::Overlap &&
            ledger.Count()==1, "duplicate mapping cannot overwrite owner");
    auto overlap=*map;overlap.address=0x5000;overlap.size=0x1000;
    require(ledger.CanMap(overlap)==WP::LedgerStatus::Overlap,
            "successor overlapping mapping denied");
    overlap.address=0x3000;overlap.size=0x2000;
    require(ledger.CanMap(overlap)==WP::LedgerStatus::Overlap,
            "predecessor overlapping mapping denied");
    overlap.address=0x6000;overlap.size=0x1000;
    require(ledger.RecordMapped(overlap)==WP::LedgerStatus::Success &&
            ledger.Count()==2, "adjacent mapping permitted");
    overlap.address=0x4000;overlap.address_space=10;
    require(ledger.RecordMapped(overlap)==WP::LedgerStatus::Success &&
            ledger.Count()==3, "separate GPU address space independent");
    require(ledger.CanModify(*modify)==WP::LedgerStatus::Success,
            "valid contained kind update");
    auto escaped=*modify;escaped.size=0x2000;
    require(ledger.CanModify(escaped)==WP::LedgerStatus::NotFound,
            "kind update cannot escape owned range");
    auto partial=*unmap;partial.size=0x1000;
    require(ledger.CanUnmap(partial)==WP::LedgerStatus::NotFound &&
            ledger.RecordUnmapped(partial)==WP::LedgerStatus::NotFound &&
            ledger.Count()==3, "partial unmap does not discard ownership");
    require(ledger.RecordUnmapped(*unmap)==WP::LedgerStatus::Success &&
            ledger.RecordUnmapped(*unmap)==WP::LedgerStatus::NotFound &&
            ledger.Count()==2, "exact unmap commits once");
    // 214/215: sparse VA reservations and normal GPU mappings share one
    // bounded address-space ledger; sparse pages must never be modified or
    // torn down through normal 212/213 commands.
    const std::array<WP::U32, 9> sparseRelease{
        0xe7, 7, 9, 0x8000, 0, 0xafff, 0, 1, 63};
    const auto sparseUnmap = WP::DecodeReleaseSparse(sparseRelease);
    require(sparseUnmap && sparseUnmap->address == 0x8000 &&
            sparseUnmap->size == 0x3000 && sparseUnmap->notification == 63,
            "sparse release has its own TIPC command identity");
    auto badSparseRelease = sparseRelease;
    badSparseRelease[0] = 0xe5;
    require(!WP::DecodeReleaseSparse(badSparseRelease),
            "normal unmap command cannot release a sparse region");
    badSparseRelease = sparseRelease;
    badSparseRelease[5] = 0xb000;
    require(!WP::DecodeReleaseSparse(badSparseRelease),
            "sparse inclusive end must be 4K aligned");
    badSparseRelease = sparseRelease;
    badSparseRelease[8] = 64;
    require(!WP::DecodeReleaseSparse(badSparseRelease),
            "sparse release requires an allocated notification slot");
    require(!WP::DecodeReleaseSparse(
                std::span<const WP::U32>{sparseRelease.data(), 8}),
            "reject truncated sparse release without out-of-bounds reads");

    WP::MappingLedger sparse;
    require(sparse.CanReserveSparse(9, 1, 0x8000, 0x3000) ==
                WP::LedgerStatus::Success && sparse.Count() == 0 &&
            sparse.RecordSparse(9, 1, 0x8000, 0x3000) ==
                WP::LedgerStatus::Success && sparse.Count() == 1,
            "reserve and record an actual backend-committed sparse region");
    require(sparse.RecordSparse(9, 1, 0x8000, 0x3000) ==
                WP::LedgerStatus::Overlap && sparse.Count() == 1,
            "duplicate sparse reservation does not overwrite ownership");
    auto normalVsSparse = *map;
    normalVsSparse.address = 0x9000;
    normalVsSparse.size = 0x1000;
    require(sparse.CanMap(normalVsSparse) == WP::LedgerStatus::Overlap,
            "normal 4K mapping cannot overwrite sparse reservation");
    auto sparseModify = *modify;
    sparseModify.address = 0x9000;
    sparseModify.size = 0x1000;
    require(sparse.CanModify(sparseModify) == WP::LedgerStatus::NotFound,
            "sparse VA cannot be modified by normal kind command");
    auto normalReleaseSparse = *unmap;
    normalReleaseSparse.address = 0x8000;
    normalReleaseSparse.size = 0x3000;
    require(sparse.CanUnmap(normalReleaseSparse) == WP::LedgerStatus::NotFound,
            "sparse VA cannot be released by normal 4K unmap");
    require(sparse.CanReleaseSparse(9, 0x8000, 0x1000) ==
                WP::LedgerStatus::NotFound &&
            sparse.CanReleaseSparse(10, 0x8000, 0x3000) ==
                WP::LedgerStatus::NotFound &&
            sparse.Count() == 1,
            "sparse teardown requires exact size and address-space owner");
    require(sparse.RecordReleasedSparse(9, 0x8000, 0x3000) ==
                WP::LedgerStatus::Success &&
            sparse.RecordReleasedSparse(9, 0x8000, 0x3000) ==
                WP::LedgerStatus::NotFound && sparse.Count() == 0,
            "sparse release commits only once after native unmap");
    require(sparse.CanReserveSparse(9, 1, 0x1001, 0x1000) ==
                WP::LedgerStatus::Invalid &&
            sparse.CanReserveSparse(9, 1, 0x1000, 0x1001) ==
                WP::LedgerStatus::Invalid &&
            sparse.CanReserveSparse(9, 1, 0xfffffffffffff000ULL, 0x2000) ==
                WP::LedgerStatus::Invalid,
            "sparse preflight rejects fractional pages and 64-bit overflow");
    require(sparse.RecordMapped(*map) == WP::LedgerStatus::Success &&
            sparse.CanReserveSparse(9, 1, 0x5000, 0x2000) ==
                WP::LedgerStatus::Overlap,
            "sparse reservation cannot overwrite normal 4K mapping");

    // 216 TIPC preflight is bounded before touching the guest buffer.
    const std::array<WP::U32, 15> sparseBatchRaw{
        0x011000e8, 7, 0, 0, 0, 0, 0, 0,
        2, 0, 9, 40, 0, 1, 63};
    const auto sparseBatch = WP::DecodeSparseBatch(sparseBatchRaw);
    require(sparseBatch && sparseBatch->count == 2 &&
            sparseBatch->address_space == 9 &&
            sparseBatch->notification == 63 && sparseBatch->sync == 1,
            "worker 216 batch count/stride/owner/notification decoded");
    auto brokenBatch = sparseBatchRaw;
    brokenBatch[8] = 257;
    require(!WP::DecodeSparseBatch(brokenBatch),
            "sparse batch count strictly limited to 256");
    brokenBatch = sparseBatchRaw;
    brokenBatch[8] = 0;
    require(!WP::DecodeSparseBatch(brokenBatch),
            "zero sparse map requests rejected");
    brokenBatch = sparseBatchRaw;
    brokenBatch[11] = 39;
    require(!WP::DecodeSparseBatch(brokenBatch),
            "wrong sparse entry stride rejected");
    brokenBatch = sparseBatchRaw;
    brokenBatch[13] = 2;
    require(!WP::DecodeSparseBatch(brokenBatch),
            "unsupported sparse sync mode rejected");
    brokenBatch = sparseBatchRaw;
    brokenBatch[14] = 64;
    require(!WP::DecodeSparseBatch(brokenBatch),
            "out-of-range sparse completion event rejected");
    brokenBatch = sparseBatchRaw;
    brokenBatch[9] = 1;
    require(!WP::DecodeSparseBatch(brokenBatch),
            "64-bit sparse count high-word overflow rejected");
    brokenBatch = sparseBatchRaw;
    brokenBatch[12] = 1;
    require(!WP::DecodeSparseBatch(brokenBatch),
            "64-bit sparse stride high-word overflow rejected");
    require(!WP::DecodeSparseBatch(std::span<const WP::U32>{
                sparseBatchRaw.data(), 14}),
            "truncated sparse batch request rejected");
    WP::MappingLedger containedSparse;
    require(containedSparse.RecordSparse(9, 1, 0x8000, 0x4000) ==
                WP::LedgerStatus::Success &&
            containedSparse.ContainsSparse(9, 0x8000, 0x4000) &&
            containedSparse.ContainsSparse(9, 0x9000, 0x1000),
            "sparse remap must lie within an allocated 4K sparse VA region");
    require(!containedSparse.ContainsSparse(9, 0x7000, 0x1000) &&
            !containedSparse.ContainsSparse(9, 0xb000, 0x2000) &&
            !containedSparse.ContainsSparse(10, 0x8000, 0x1000) &&
            !containedSparse.ContainsSparse(9, 0x8001, 0x1000) &&
            !containedSparse.ContainsSparse(9, 0x8000, 0) &&
            !containedSparse.ContainsSparse(9, 0xfffffffffffff000ULL, 0x2000),
            "sparse batch rejects cross-owner, overflow and out-of-region changes");
    require(containedSparse.RecordReleasedSparse(9, 0x8000, 0x4000) ==
                WP::LedgerStatus::Success &&
            !containedSparse.ContainsSparse(9, 0x8000, 0x1000),
            "released sparse reservation cannot be remapped");

    WP::MappingLedger bounded;
    auto fill=*map;fill.size=0x1000;
    for (std::size_t i=0;i<WP::MaxMappings;++i) {
        fill.address=0x100000+(i*0x1000);
        require(bounded.RecordMapped(fill)==WP::LedgerStatus::Success,
                "bounded mapping table must accept all allowed slots");
    }
    fill.address=0x100000+(WP::MaxMappings*0x1000);
    require(bounded.Count()==WP::MaxMappings &&
            bounded.RecordMapped(fill)==WP::LedgerStatus::OutOfResource &&
            bounded.Count()==WP::MaxMappings,
            "4K mapping table exhaustion is deterministic");

    // Native-memory objects are bounded descriptors. They do not allocate
    // Vulkan images and must not fabricate a completed GPU operation.
    P::NativeMemoryLedger native_memory;
    auto [created, first_memory] = native_memory.Create(0x4000);
    require(created == P::NativeMemoryStatus::Success && first_memory == 1 &&
            native_memory.Count() == 1, "GSV 111 allocates first owned descriptor");
    auto [created_two, second_memory] = native_memory.Create(0x2000);
    require(created_two == P::NativeMemoryStatus::Success && second_memory == 2,
            "GSV 111 IDs are distinct and monotonic");
    require(native_memory.Create(0).first == P::NativeMemoryStatus::InvalidSize &&
            native_memory.Create(0x1001).first == P::NativeMemoryStatus::InvalidSize &&
            native_memory.Create((12ULL << 30) + 0x1000).first == P::NativeMemoryStatus::InvalidSize,
            "GSV 111 refuses empty, unaligned and oversized host requests");
    require(native_memory.ValidateBind(first_memory, 0x8000, 0x3000) ==
                P::NativeMemoryStatus::Success,
            "GSV 114 validates owned descriptor and in-bounds guest range");
    require(native_memory.ValidateBind(first_memory, 0x8001, 0x3000) ==
                P::NativeMemoryStatus::InvalidAddress &&
            native_memory.ValidateBind(first_memory, 0x8000, 0x5000) ==
                P::NativeMemoryStatus::InvalidSize &&
            native_memory.ValidateBind(first_memory, 0xfffffffffffff000ULL, 0x2000) ==
                P::NativeMemoryStatus::InvalidAddress,
            "GSV 114 prevents misaligned, oversized or wrapped binding");
    require(native_memory.Bind(first_memory, 0x8000, 0x3000) ==
                P::NativeMemoryStatus::Success &&
            native_memory.Get(first_memory)->bound &&
            native_memory.Get(first_memory)->guest_address == 0x8000,
            "GSV 114 commits a validated ownership binding");
    require(native_memory.Bind(first_memory, 0x9000, 0x1000) ==
                P::NativeMemoryStatus::AlreadyBound,
            "GSV 114 cannot silently rebind an existing native-memory object");
    require(native_memory.Destroy(first_memory) == P::NativeMemoryStatus::Success &&
            !native_memory.Get(first_memory).has_value() &&
            native_memory.ValidateBind(first_memory, 0x8000, 0x1000) ==
                P::NativeMemoryStatus::InvalidHandle &&
            native_memory.Destroy(first_memory) == P::NativeMemoryStatus::InvalidHandle,
            "GSV 112 releases exact resource and rejects stale handles");
    require(native_memory.Destroy(second_memory) == P::NativeMemoryStatus::Success &&
            native_memory.Count() == 0,
            "GSV native-memory resources survive independent destroy order");
    // Production 111 returns a GLOBAL NVMap handle (nonsequential, often a
    // multiple of four), not the local synthetic ledger ID.
    require(native_memory.Adopt(16, 0x6000) == P::NativeMemoryStatus::Success &&
            native_memory.Get(16)->size == 0x6000 &&
            native_memory.OwnedIds().size() == 1 &&
            native_memory.OwnedIds()[0] == 16,
            "GSV 111 adopts actual externally allocated NVMap ID");
    require(native_memory.Adopt(16, 0x6000) == P::NativeMemoryStatus::AlreadyBound &&
            native_memory.Adopt(0, 0x6000) == P::NativeMemoryStatus::InvalidHandle &&
            native_memory.Adopt(20, 0x1001) == P::NativeMemoryStatus::InvalidSize &&
            native_memory.Count() == 1,
            "GSV 111 rejects aliasing and invalid native NVMap handles");
    require(native_memory.ValidateBind(16, 0x100000, 0x6000) ==
                P::NativeMemoryStatus::Success &&
            native_memory.Bind(16, 0x100000, 0x6000) ==
                P::NativeMemoryStatus::Success &&
            native_memory.Destroy(16) == P::NativeMemoryStatus::Success &&
            native_memory.OwnedIds().empty(),
            "GSV 114/112 track externally owned physical GPU backing");

    // Native parent binding command 423 has 12 words after its TIPC header.
    std::array<u32,14> parent_packet{
        0x1b7, 12, 16, 0x8000, 0, 0x4000, 0, 20, 0x2000, 0, 0, 0, 0, 0};
    const auto parent_bind = P::DecodeNativeParentBind(parent_packet);
    require(parent_bind && parent_bind->child == 16 && parent_bind->parent == 20 &&
            parent_bind->address == 0x8000 && parent_bind->size == 0x4000 &&
            parent_bind->parent_offset == 0x2000,
            "GSV 423 decodes valid child and parent NVMap fields");
    parent_packet[11] = 1;
    require(!P::DecodeNativeParentBind(parent_packet),
            "GSV 423 rejects nonzero reserved packet words");
    parent_packet[11] = 0;
    parent_packet[7] = 16;
    require(!P::DecodeNativeParentBind(parent_packet),
            "GSV 423 rejects self-backed native memory");
    parent_packet[7] = 20;
    parent_packet[8] = 1;
    require(!P::DecodeNativeParentBind(parent_packet),
            "GSV 423 rejects unaligned parent offsets");
    parent_packet[8] = 0x2000;
    parent_packet[6] = 0xffffffff;
    parent_packet[5] = 0xfffff000;
    require(!P::DecodeNativeParentBind(parent_packet),
            "GSV 423 rejects address/size overflow before backing is pinned");
    parent_packet[6] = 0;
    parent_packet[5] = 0x4000;
    require(!P::DecodeNativeParentBind(
                std::span<const u32>{parent_packet.data(), parent_packet.size() - 1}),
            "GSV 423 rejects truncated native GPU parent packets");

    // Native 429/430 image IDs retain a separately owned NVMap backing
    // reference; creation is not a claim of Vulkan rendering or presentation.
    preferences[6] = 1;
    const auto image_requirements = CalculateNativeImageRequirements(preferences, 2);
    require(image_requirements && image_requirements->size == 65536,
            "native image requirements available for backing registry");
    NativeImageLedger images;
    require(!images.Create(0, 0x10000, *image_requirements, preferences) &&
            !images.Create(16, 0x8000, *image_requirements, preferences) &&
            images.Count() == 0,
            "GSV 429 rejects absent or undersized backing memory");
    const auto first_image = images.Create(16, 0x10000, *image_requirements, preferences);
    const auto second_image = images.Create(16, 0x10000, *image_requirements, preferences);
    require(first_image && *first_image == 1 &&
            second_image && *second_image == 2 &&
            images.Get(*first_image)->backing == 16 &&
            images.Get(*first_image)->size == 0x10000 &&
            images.Get(*first_image)->preference[1] == 1 &&
            images.Count() == 2,
            "GSV 429 owns distinct image IDs linked to genuine NVMap backing");
    require(images.ConfigureWindowPool(*first_image, true) &&
            images.Get(*first_image)->window_pool &&
            !images.ConfigureWindowPool(*first_image, true) &&
            !images.Destroy(*first_image) &&
            images.ConfigureWindowPool(*first_image, false) &&
            !images.Get(*first_image)->window_pool,
            "GSV 314/315 require explicit window alias retirement");
    require(!images.ConfigureWindowPool(0xffffffffU, true),
            "GSV native window alias rejects unowned image IDs");
    require(!images.Destroy(0) && !images.Destroy(0xffffffffU) &&
            images.Destroy(*first_image) &&
            !images.Get(*first_image).has_value() &&
            !images.Destroy(*first_image) && images.Count() == 1 &&
            images.Destroy(*second_image) && images.Records().empty(),
            "GSV 430 rejects stale images and retires independent references");

    // Native video pools (911) are distinct from 429 native image handles.
    // Both kinds must reject foreign backing before any GPU VA allocation.
    std::array<u32,16> video{};
    video[0] = 0;
    video[1] = 5;
    video[2] = (63u << 16) | 127u; // 128 x 64, RGBA
    const auto video_layout = CalculateNativeVideoImageLayout(video, 2);
    require(video_layout && video_layout->image_bytes == 65536 &&
            video_layout->image_stride == 65536 &&
            video_layout->total_bytes == 131072,
            "GSV video pool 911 computes upstream RGBA image byte and stride");
    NativeVideoPoolLedger pools;
    require(!pools.Add(0x80000000u, 2, 0, 131072, video[2], *video_layout) &&
            !pools.Add(0x80000000u, 2, 20, 65536, video[2], *video_layout) &&
            pools.ImageCount() == 0,
            "GSV 911 rejects nonexistent or undersized NVMap backing");
    require(pools.Add(0x80000000u, 2, 20, 131072, video[2], *video_layout) &&
            pools.ImageCount() == 2,
            "GSV 911 allocates a bounded image ID range");
    const auto second_video = pools.Lookup(0x80000001u);
    require(second_video && second_video->backing == 20 &&
            second_video->offset == 65536 &&
            second_video->size == 65536 &&
            second_video->packed_dimensions == video[2],
            "GSV 426/428 resolve image backing, offset, size and dimensions");
    require(!pools.Add(0x80000001u, 2, 20, 131072, video[2], *video_layout) &&
            !pools.Lookup(0x80000002u) &&
            pools.Remove(0x80000000u) && pools.ImageCount() == 0 &&
            !pools.Remove(0x80000000u),
            "GSV 911/912 reject overlapping and stale image pools");
    const NativeVideoImageLayout unaddressable{
        0x1fffff000ULL, 0x1000U, 0xfffff000U, 0x100U, false, 0};
    require(!pools.Add(0x80000010u, 3, 20, 0x200000000ULL,
                       video[2], unaddressable),
            "GSV 428 refuses pool images with unrepresentable 32-bit offsets");
    video[1] = 1; // NV12 4:2:0, even dimensions
    const auto nv12 = CalculateNativeVideoImageLayout(video, 2);
    require(nv12 && nv12->nv12 && nv12->image_bytes == 24576 &&
            nv12->total_bytes == 49152 && nv12->chroma_offset == 16384,
            "GSV native NV12 two-plane pitch/chroma layout");
    video[2] = (63u << 16) | 126u; // odd width
    require(!CalculateNativeVideoImageLayout(video, 2),
            "GSV native NV12 rejects odd pixel dimensions");
    video[2] = (63u << 16) | 127u;
    video[3] = 1;
    require(!CalculateNativeVideoImageLayout(video, 2),
            "GSV video image pools reject unreviewed format flags");

    NativeImageLedger coordinated;
    const auto requested = coordinated.Create(16, 0x10000,
                                             *image_requirements, preferences, 42);
    const auto automatic = coordinated.Create(16, 0x10000,
                                              *image_requirements, preferences);
    require(requested && *requested == 42 && automatic && *automatic == 43 &&
            !coordinated.Create(16, 0x10000, *image_requirements, preferences, 42) &&
            !coordinated.Create(16, 0x10000, *image_requirements, preferences, 41),
            "GSV native and video pool IDs never reuse or alias guest handles");

    const auto generic=N::SelectNativeMemoryKind(6,6);
    require(generic && generic->selected==6 &&
            generic->backend==static_cast<u8>(Tegra::PTEKind::GENERIC_16BX2),
            "generic uncompressed native MMU kind");
    require(N::SelectNativeMemoryKind(8,6).has_value(),
            "compressed kind explicitly negotiates generic fallback");
    require(!N::SelectNativeMemoryKind(8,7).has_value(),
            "no silent fallback for unknown MMU kind");
    require(!N::SelectNativeMemoryKind(0xfe,0xfe).has_value(),
            "do not confuse legacy generic kind with native GPU kind");
    require(!N::SelectNativeMemoryKind(2,2).has_value(),
            "do not advertise unsupported native kind");
    std::printf("NS2 graphics HLE protocol, image layout, MMU kind: %d assertions PASS\n",
                assertions);
}
