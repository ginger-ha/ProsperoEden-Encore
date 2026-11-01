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
    return 0;
}
