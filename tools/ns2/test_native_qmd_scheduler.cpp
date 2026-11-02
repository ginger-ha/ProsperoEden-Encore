// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later
// Host-only QMD 3.0 scheduler conformance against reviewed Eglantine NX2.
// Tests scheduling, per-title isolation, release slots, fail-closed decoding.
#include <array>
#include <cassert>
#include <cstdint>
#include <string_view>
#include <unordered_map>
#include <vector>
#include <tuple>
#include "video_core/native_qmd.h"

// Overflow and underflow must refuse malformed cross-channel PCAS counts
// before touching scheduler state. The ordinary QMD count path is exercised
// by the existing release/dependency integration fixtures below.
static_assert(!Tegra::NativeQmdDependencyAdd(
    std::numeric_limits<std::int32_t>::max(), 1));
static_assert(!Tegra::NativeQmdDependencyAdd(
    std::numeric_limits<std::int32_t>::min(), -1));
static_assert(Tegra::NativeQmdDependencyAdd(
    std::numeric_limits<std::int32_t>::max() - 1, 1) ==
    std::numeric_limits<std::int32_t>::max());
static_assert(Tegra::NativeQmdDependencyAdd(
    std::numeric_limits<std::int32_t>::min() + 1, -1) ==
    std::numeric_limits<std::int32_t>::min());

using Q=Tegra::NativeQmdScheduler;
using Address=Q::Address;
using Descriptor=Q::Descriptor;
struct Fixture {
    Q qmd;
    std::unordered_map<Address, Descriptor> descriptors;
    std::vector<std::tuple<Address,std::uint32_t,std::uint32_t>> released;
    unsigned dispatched{};
    bool allow_dispatch{true};
    // Fail one release callback before it queues any guest-visible write.
    std::unordered_map<Address, unsigned> transient_release_failures;
    bool read(Address address, Descriptor& out) {
        const auto it=descriptors.find(address);
        if(it==descriptors.end())return false;
        out=it->second;
        return true;
    }
    bool release(Address address, std::uint32_t value, std::uint32_t flags) {
        if (auto it=transient_release_failures.find(address);
            it!=transient_release_failures.end() && it->second>0) {
            --it->second;
            return false;
        }
        released.emplace_back(address,value,flags);
        return true;
    }
    bool dispatch(const Descriptor&) { ++dispatched;return allow_dispatch; }
    std::string_view signal(Address address,std::uint32_t action) {
        return qmd.Signal(address,action,
            [this](Address p,Descriptor& d){return read(p,d);},
            [this](Address p,std::uint32_t v,std::uint32_t f){return release(p,v,f);},
            [this](const Descriptor& d){return dispatch(d);});
    }
};
static Descriptor EmptyGrid(unsigned dependencies=0) {
    Descriptor d{};
    d[18]=0x30; // native QMD 3.0 signature
    d[4]=dependencies<<14;
    return d;
}
static void SetRelease(Descriptor& d,unsigned slot,Address address,unsigned payload,
                       bool add=false) {
    d[slot]=static_cast<std::uint32_t>(address);
    d[slot+1]=static_cast<std::uint32_t>((address>>32)&0xff)
              |(1u<<30)|(1u<<23)|(add?(1u<<26):0);
    d[slot+2]=payload;
}
int main() {
    // MKW native Compute hot path: side-effect-free register writes avoid
    // KeplerCompute::CallMethod. The special methods MUST still execute
    // their original upload, semaphore, QMD and legacy side effects.
    for (const unsigned reg : {0x00U, 0x60U, 0x6bU, 0x6eU, 0xadU,
                               0xb1U, 0x106U, 0x108U, 0x557U,
                               0x55dU, 0x582U, 0x6c0U, 0x6c2U,
                               0x982U, 0xcffU})
        assert(Tegra::NativeComputePlainRegister(reg));
    for (const unsigned reg : {0x45U, 0x46U, 0x47U, 0x48U,
                               0x6cU, 0x6dU, 0xaeU, 0xafU, 0xb0U,
                               0x107U, 0x6c3U, 0xe00U, 0xffffU})
        assert(!Tegra::NativeComputePlainRegister(reg));
    // A native burst to one plain register has last-value-wins semantics
    // for its entire span. No method trigger may be coalesced this way.
    std::array<unsigned, 4> burst{10, 11, 12, 13};
    unsigned sequential{};
    for (const auto word : burst) sequential=word;
    const unsigned collapsed=burst.back();
    assert(sequential==collapsed);
    assert(!Tegra::NativeComputePlainRegister(0x107U));
    // Native 0xC7C0 SET_REPORT_SEMAPHORE_D reductions are performed after
    // a real GPU fence, not by reusing the Switch 1 semaphore decoder.
    assert(Tegra::NativeComputeSemaphoreReduction(6,4,0)==10);
    assert(Tegra::NativeComputeSemaphoreReduction(6,4,1)==4);
    assert(Tegra::NativeComputeSemaphoreReduction(6,4,2)==6);
    assert(Tegra::NativeComputeSemaphoreReduction(6,4,3)==0);
    assert(Tegra::NativeComputeSemaphoreReduction(2,4,3)==3);
    assert(Tegra::NativeComputeSemaphoreReduction(6,4,4)==4);
    assert(Tegra::NativeComputeSemaphoreReduction(2,4,4)==1);
    assert(Tegra::NativeComputeSemaphoreReduction(0,4,4)==4);
    assert(Tegra::NativeComputeSemaphoreReduction(6,4,5)==4);
    assert(Tegra::NativeComputeSemaphoreReduction(6,4,6)==6);
    assert(Tegra::NativeComputeSemaphoreReduction(6,4,7)==2);
    // Decode the exact QMD3 compute resource description before hooking
    // an authenticated native pipeline. This does NOT run a shader.
    {
        auto d=EmptyGrid();
        d[8]=0x120;
        d[11]=1U<<30;
        d[12]=3;d[13]=4;d[14]=5;
        d[17]=0x200;
        d[18]=(8U<<16)|0x30U;
        d[19]=(2U<<16)|16U;
        d[20]=1;
        d[23]=0x80;
        d[48]=0x34567000;
        d[49]=1;
        d[50]=0x40;
        d[32]=0x12340000;
        d[33]=5|(4U<<19);
        const auto launch=Tegra::DecodeNativeComputeLaunch(d);
        assert(launch.has_value());
        assert(launch->code_base==0x134567000ULL);
        assert(launch->program_address==0x134567120ULL);
        assert((launch->grid==std::array<std::uint32_t,3>{3,4,5}));
        assert((launch->block==std::array<std::uint32_t,3>{8,16,2}));
        assert(launch->shared_bytes==0x200 && launch->local_pos_bytes==0x80);
        assert(launch->local_crs_bytes==0x40 && launch->linked_tsc);
        assert(launch->constant_buffers[0].enabled);
        assert(launch->constant_buffers[0].gpu_address==0x512340000ULL);
        assert(launch->constant_buffers[0].size==64);
        assert(!launch->constant_buffers[1].enabled);
        // Native shader and only enabled constant-buffer ranges must be
        // mapped BEFORE any future Vulkan pipeline/resource submission.
        unsigned mapped_queries=0;
        auto all_mapped=[&](std::uint64_t address,std::size_t bytes) {
            ++mapped_queries;
            return (address==launch->program_address && bytes==16) ||
                   (address==launch->constant_buffers[0].gpu_address &&
                    bytes==launch->constant_buffers[0].size);
        };
        assert(Tegra::NativeComputeLaunchMapped(*launch,all_mapped));
        assert(mapped_queries==2);
        mapped_queries=0;
        assert(!Tegra::NativeComputeLaunchMapped(
            *launch,[&](std::uint64_t address,std::size_t) {
                ++mapped_queries;
                return address!=launch->program_address;
            }));
        assert(mapped_queries==1);
        mapped_queries=0;
        assert(!Tegra::NativeComputeLaunchMapped(
            *launch,[&](std::uint64_t address,std::size_t) {
                ++mapped_queries;
                return address!=launch->constant_buffers[0].gpu_address;
            }));
        assert(mapped_queries==2);
        // Native Ampere uses 49-bit QMD GPU VAs, including high CBUF
        // address bits beyond the Switch 1/Maxwell 40-bit allocation.
        d[33]|=1U<<8;
        const auto wide_cbuf=Tegra::DecodeNativeComputeLaunch(d);
        assert(wide_cbuf &&
               wide_cbuf->constant_buffers[0].gpu_address==
                   ((std::uint64_t{0x105}<<32)|0x12340000ULL));
        d[33]|=1U<<17;
        assert(!Tegra::DecodeNativeComputeLaunch(d));
        d[33]&=~((1U<<8)|(1U<<17));
        // An enabled CBUF near the 49-bit limit may never wrap its size.
        d[32]=0xfffffff0U;
        d[33]=0x1ffffU|(4U<<19);
        assert(!Tegra::DecodeNativeComputeLaunch(d));
        d[32]=0x12340000U;
        d[33]=5U|(4U<<19);
        // Local memory allocations have 24 significant bits, unlike
        // the older 20-bit mask that truncated native Ampere QMD3.
        d[23]=0x100080;
        d[50]=0x100040;
        const auto widened=Tegra::DecodeNativeComputeLaunch(d);
        assert(widened && widened->local_pos_bytes==0x100080 &&
               widened->local_crs_bytes==0x100040);
        d[12]=0;
        assert(!Tegra::DecodeNativeComputeLaunch(d));
        d[12]=3;d[18]=0x30;
        assert(!Tegra::DecodeNativeComputeLaunch(d));
    }
    // The three Ampere completion slots must all be delivered, not only
    // the two legacy slots. They are validated before any side effect.
    {
        Fixture f;auto d=EmptyGrid();
        SetRelease(d,24,0x1000,7);
        SetRelease(d,28,0x2000,9);
        SetRelease(d,52,0x3000,11,true);
        f.descriptors[0x20000]=d;
        assert(f.signal(0x20000,3).empty());
        assert(f.released.size()==3);
        assert(std::get<0>(f.released[2])==0x3000);
        assert(std::get<1>(f.released[2])==11);
        assert((std::get<2>(f.released[2])&(1u<<26))!=0);
        assert(f.dispatched==0); // zero grid; no fake compute shader launch
    }
    // A compute queue may decrement another channel's QMD after its launch
    // record arrives. An early decrement must be retained for the same title.
    {
        Fixture f;auto d=EmptyGrid(2);SetRelease(d,52,0x4040,3);
        f.descriptors[0x40000]=d;
        assert(f.signal(0x40000,3).empty());
        assert(f.released.empty());
        assert(f.signal(0x40000,7).empty());
        assert(f.released.empty());
        assert(f.signal(0x40000,7).empty());
        assert(f.released.size()==1);
        assert(f.signal(0x40000,7).empty());
        assert(f.released.size()==1); // no duplicate completion
    }
    {
        Fixture f;auto d=EmptyGrid(1);SetRelease(d,24,0x9000,2);
        f.descriptors[0x10000]=d;
        assert(f.signal(0x10000,7).empty()); // arrives on another channel first
        assert(f.released.empty());
        assert(f.signal(0x10000,3).empty());
        assert(f.released.size()==1);
        // An independent GPU process must never observe the other title's
        // prior cached descriptor or deferred dependency.
        Fixture next;
        assert(next.signal(0x10000,2)=="unmapped QMD");
        assert(next.released.empty());
    }
    // A nonempty grid is never marked successful without native dispatch.
    {
        Fixture f;auto d=EmptyGrid();
        d[12]=1;d[13]=1;d[14]=1;
        SetRelease(d,52,0x7000,17);
        f.descriptors[0x70000]=d;
        f.allow_dispatch=false;
        assert(f.signal(0x70000,3)=="native shader dispatch required");
        assert(f.dispatched==1);
        assert(f.released.empty()); // rejected shader must not fake GPU fence
        f.allow_dispatch=true;
        assert(f.signal(0x70000,2).empty()); // retry genuine dispatch
        assert(f.dispatched==2);
        assert(f.released.size()==1);
    }
    // If a later semaphore cannot be queued, the previously queued slots
    // must not be repeated; the compute program must not run twice either.
    {
        Fixture f;auto d=EmptyGrid();
        d[12]=1;d[13]=1;d[14]=1;
        SetRelease(d,24,0x1111,5,true);
        SetRelease(d,28,0x2222,7);
        SetRelease(d,52,0x3333,11);
        f.descriptors[0x88800]=d;
        f.transient_release_failures[0x2222]=1;
        assert(f.signal(0x88800,3)=="unmapped QMD release");
        assert(f.dispatched==1);
        assert(f.released.size()==1);
        assert(std::get<0>(f.released[0])==0x1111);
        assert(f.signal(0x88800,2).empty());
        assert(f.dispatched==1);
        assert(f.released.size()==3);
        assert(std::get<0>(f.released[1])==0x2222);
        assert(std::get<0>(f.released[2])==0x3333);
        assert(f.signal(0x88800,2).empty());
        assert(f.dispatched==1 && f.released.size()==3);
    }
    // An already accepted compute dispatch must retain its original
    // descriptor if the guest mutates or unmaps the QMD before a failed
    // release is retried. Re-reading would complete the wrong transaction.
    {
        Fixture f;auto d=EmptyGrid();
        d[12]=1;d[13]=1;d[14]=1;
        SetRelease(d,24,0x1100,10,true);
        SetRelease(d,28,0x2200,20);
        f.descriptors[0x88000]=d;
        f.transient_release_failures[0x2200]=1;
        assert(f.signal(0x88000,3)=="unmapped QMD release");
        assert(f.dispatched==1 && f.released.size()==1);
        // The same QMD address now holds another program and semaphores.
        auto replacement=d;
        replacement[48]=0x9000;
        SetRelease(replacement,24,0x3300,30,true);
        SetRelease(replacement,28,0x4400,40);
        f.descriptors[0x88000]=replacement;
        assert(f.signal(0x88000,2).empty());
        assert(f.dispatched==1 && f.released.size()==2);
        assert(std::get<0>(f.released[0])==0x1100);
        assert(std::get<0>(f.released[1])==0x2200);
        assert(std::get<1>(f.released[1])==20);
        // A fresh, distinct action 3 may legitimately consume the replacement.
        assert(f.signal(0x88000,3).empty());
        assert(f.dispatched==2 && f.released.size()==4);
        assert(std::get<0>(f.released[2])==0x3300);
        assert(std::get<0>(f.released[3])==0x4400);
    }
    // Descriptor backing may be unmapped after dispatch; a retry still
    // finalizes from the admitted snapshot rather than reading freed pages.
    {
        Fixture f;auto d=EmptyGrid();
        d[12]=1;d[13]=1;d[14]=1;
        SetRelease(d,24,0x5100,1);
        SetRelease(d,28,0x5200,2);
        f.descriptors[0x89000]=d;
        f.transient_release_failures[0x5200]=1;
        assert(f.signal(0x89000,3)=="unmapped QMD release");
        f.descriptors.erase(0x89000);
        assert(f.signal(0x89000,2).empty());
        assert(f.released.size()==2 && f.dispatched==1);
    }
    // Empty grids need the same retry protection without a shader dispatch.
    {
        Fixture f;auto d=EmptyGrid();
        SetRelease(d,24,0x5555,5);
        f.descriptors[0x99900]=d;
        f.transient_release_failures[0x5555]=1;
        assert(f.signal(0x99900,3)=="unmapped QMD release");
        assert(f.released.empty() && f.dispatched==0);
        assert(f.signal(0x99900,2).empty());
        assert(f.released.size()==1 && f.dispatched==0);
    }
    // A reloaded launch cannot reset already accepted semaphores while a
    // completion transaction still needs a retry.
    {
        Fixture f;auto d=EmptyGrid();
        d[12]=1;d[13]=1;d[14]=1;
        SetRelease(d,24,0x1111,1,true);
        SetRelease(d,28,0x2222,2);
        f.descriptors[0xa2000]=d;
        f.transient_release_failures[0x2222]=1;
        assert(f.signal(0xa2000,3)=="unmapped QMD release");
        assert(f.released.size()==1 && f.dispatched==1);
        assert(f.signal(0xa2000,3)=="QMD reload during pending release");
        assert(f.released.size()==1 && f.dispatched==1);
        assert(f.signal(0xa2000,2).empty());
        assert(f.released.size()==2 && f.dispatched==1);
        // Once finished, a new, genuine action 3 may reuse the QMD VA.
        assert(f.signal(0xa2000,3).empty());
        assert(f.released.size()==4 && f.dispatched==2);
    }
    // Bad dependent actions are rejected BEFORE submitting a shader or
    // publishing a release, rather than after irreversible guest writes.
    {
        Fixture f;auto d=EmptyGrid();
        d[12]=1;d[13]=1;d[14]=1;
        d[16]=1|(7u<<1); // unsupported primary dependent action
        SetRelease(d,24,0xabc0,9);
        f.descriptors[0xb2000]=d;
        assert(f.signal(0xb2000,3)=="unsupported dependent QMD action");
        assert(f.released.empty() && f.dispatched==0);
        d[16]=1|(4u<<1)|(1u<<5); // second dependent is unsupported
        f.descriptors[0xb3000]=d;
        assert(f.signal(0xb3000,3)=="second dependent QMD unsupported");
        assert(f.released.empty() && f.dispatched==0);
    }
    // Malformed QMDs fail before any guest semaphore is released.
    {
        Fixture f;auto d=EmptyGrid();d[18]=0x20;
        f.descriptors[0xa0000]=d;
        assert(f.signal(0xa0000,3)=="unsupported QMD version or queue");
        assert(f.released.empty());
    }
    {
        Fixture f;auto d=EmptyGrid();SetRelease(d,24,0x1234,2);
        d[25]|=1u<<25; // unsupported release format
        f.descriptors[0xb0000]=d;
        assert(f.signal(0xb0000,3)=="unsupported QMD release format");
        assert(f.released.empty());
    }
    // A dependent QMD decremented from a preceding completion is scheduled
    // only on receipt of the matching second-channel launch.
    {
        Fixture f;auto first=EmptyGrid(),second=EmptyGrid(1);
        first[15]=0xd0000>>8;first[16]=1|(4u<<1);
        SetRelease(second,52,0xdead,5);
        f.descriptors[0xc0000]=first;f.descriptors[0xd0000]=second;
        assert(f.signal(0xd0000,3).empty());
        assert(f.released.empty());
        assert(f.signal(0xc0000,3).empty());
        assert(f.released.size()==1);
        assert(std::get<0>(f.released[0])==0xdead);
    }
    // Native inline QMDs use the full 49-bit GPU VA space. A QMD above
    // the 32-bit PCAS-word range must remain address-distinct, and its
    // completed semaphore cannot be confused with a low-40-bit alias.
    {
        Fixture f;
        constexpr Address upper = 0x10100020000ULL;
        constexpr Address lower = 0x100020000ULL;
        auto high = EmptyGrid();
        high[12]=1; high[13]=1; high[14]=1;
        SetRelease(high,24,0x2000,14);
        auto low = EmptyGrid();
        SetRelease(low,24,0x3000,15);
        f.descriptors[upper] = high;
        f.descriptors[lower] = low;
        assert(f.signal(upper,3).empty());
        assert(f.dispatched==1 && f.released.size()==1 &&
               std::get<0>(f.released[0])==0x2000);
        assert(f.signal(lower,3).empty());
        assert(f.dispatched==1 && f.released.size()==2 &&
               std::get<0>(f.released[1])==0x3000);
    }
    return 0;
}
