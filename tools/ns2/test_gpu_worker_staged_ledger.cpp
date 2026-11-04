// SPDX-License-Identifier: GPL-3.0-or-later
// Real native 211/214 mapping ledger: allocations BEFORE a guest GMMU commit.
#include <cassert>
#include <cstdlib>
#include <new>
#include "core/hle/service/am/service/gpu_worker_protocol.h"

static int fail_new{};
void* operator new(std::size_t n) {
    if (fail_new && --fail_new == 0) throw std::bad_alloc{};
    if (void* p = std::malloc(n)) return p;
    throw std::bad_alloc{};
}
void operator delete(void* ptr) noexcept { std::free(ptr); }
void operator delete(void* ptr,std::size_t) noexcept { std::free(ptr); }

namespace GW = Service::AM::GpuWorkerProtocol;
int main() {
    GW::MappingLedger ledger;
    const GW::Map4K map{9, 7, 2, 0, 0x4000, 0x2000, 0, 1, 1, 0, 0};
    using Status = GW::LedgerStatus;
    using Pending = GW::MappingLedger::Pending;
    assert(ledger.CanMap(map) == Status::Success);
    {
        Pending stage;
        fail_new=1;
        assert(ledger.PrepareMapped(map,stage)==Status::OutOfResource);
        assert(stage.empty() && ledger.Count()==0);
        fail_new=0;
    }
    // Failure of GMMU driver after preflight should simply destroy the
    // staged node, with no GPU memory mapped and no committed ownership.
    {
        Pending stage;
        assert(ledger.PrepareMapped(map,stage)==Status::Success);
        assert(stage.size()==1 && ledger.Count()==0);
    }
    assert(ledger.Count()==0);
    {
        Pending stage;
        assert(ledger.PrepareMapped(map,stage)==Status::Success);
        // No allocations are permitted after a successful guest GMMU map.
        fail_new=1;
        assert(ledger.CommitPrepared(stage)==Status::Success);
        assert(fail_new==1 && stage.empty() && ledger.Count()==1);
    }
    fail_new=0;
    { Pending ignored; assert(ledger.PrepareMapped(map,ignored)==Status::Overlap); }
    GW::Unmap4K unmap{9,0,0x4000,0x2000,0};
    assert(ledger.RecordUnmapped(unmap)==Status::Success && ledger.Count()==0);
    // A committed overlapping entry between preflight and commit is detected
    // without publishing the staged node (simulated caller misuse).
    {
        Pending stage;
        assert(ledger.PrepareMapped(map,stage)==Status::Success);
        assert(ledger.RecordMapped(map)==Status::Success);
        assert(ledger.CommitPrepared(stage)==Status::Overlap);
        assert(stage.size()==1 && ledger.Count()==1);
    }
    assert(ledger.RecordUnmapped(unmap)==Status::Success);
    // Legacy ledger callers still fail closed on allocator OOM.
    fail_new=1;
    assert(ledger.RecordMapped(map)==Status::OutOfResource);
    assert(ledger.Count()==0);
    fail_new=0;
    {
        Pending stage;
        fail_new=1;
        assert(ledger.PrepareSparse(9,2,0x8000,0x3000,stage)==Status::OutOfResource);
        assert(stage.empty() && ledger.Count()==0);
        fail_new=0;
    }
    {
        Pending stage;
        assert(ledger.PrepareSparse(9,2,0x8000,0x3000,stage)==Status::Success);
        fail_new=1;
        assert(ledger.CommitPrepared(stage)==Status::Success);
        assert(fail_new==1 && stage.empty() && ledger.Count()==1);
    }
    fail_new=0;
    assert(ledger.ContainsSparse(9,0x9000,0x1000));
    assert(ledger.RecordReleasedSparse(9,0x8000,0x3000)==Status::Success);
    fail_new=1;
    assert(ledger.RecordSparse(9,2,0x8000,0x3000)==Status::OutOfResource);
    assert(ledger.Count()==0);
    fail_new=0;
}
