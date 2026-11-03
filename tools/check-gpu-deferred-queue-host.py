#!/usr/bin/env python3
"""Host-only compiler/sanitizer qualification of deferred guest write queue.

Does NOT prove renderer cache/fence/texture correctness; native activation forbidden
until cache replay, GPU-dirty handling and title lifecycle are audited together.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
header = root / "headless/gpu_deferred_write_queue.h"
assert header.is_file()
source = r'''
#include "gpu_deferred_write_queue.h"
#include <array>
#include <atomic>
#include <cassert>
#include <mutex>
#include <condition_variable>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <thread>
#include <vector>
using Eden::GpuDeferredWrite::Queue;
template<typename T>
concept AcceptsBareWait = requires(T& queue) {
    queue.WaitUntil(std::uint64_t{1});
};
template<typename T>
concept AcceptsBareDrain = requires(T& queue) {
    queue.DrainThrough(std::uint64_t{1},
        [](unsigned, std::uint64_t, std::uint64_t) {});
};
static_assert(!AcceptsBareWait<Queue>);
static_assert(!AcceptsBareDrain<Queue>);
int main() {
    Queue q;
    assert(!q.Pending());
    assert(!q.Enqueue(4, 1, 1));
    assert(!q.Enqueue(0, 1, 0));
    assert(!q.Enqueue(0, UINT64_MAX, 2));
    assert(!q.Pending());

    assert(q.Enqueue(0, 100, 8));
    assert(q.Enqueue(0, 105, 10));
    assert(q.Enqueue(0, 4093, 8)); // crosses 4K boundary => independent
    assert(q.Enqueue(0, 4100, 10));
    std::vector<std::array<std::uint64_t,3>> written;
    const auto replay = [&](unsigned core, std::uint64_t addr, std::uint64_t size) {
        written.push_back({core,addr,size});
    };
    assert(q.Drain(replay) == 3);
    assert(!q.Pending());
    assert((written[0] == std::array<std::uint64_t,3>{0,100,15}));
    assert((written[1] == std::array<std::uint64_t,3>{0,4093,8}));
    assert((written[2] == std::array<std::uint64_t,3>{0,4100,10}));
    assert(q.Drain(replay) == 0);

    // Boundary-adjacent and gap-separated writes must not coalesce into
    // one GPU dirty area, even when inside the same guest 4-KiB page.
    Queue regions;
    assert(regions.Enqueue(0,2040,8));
    assert(regions.Enqueue(0,2048,8));
    assert(regions.Enqueue(0,3072,8));
    assert(regions.Enqueue(0,3090,8));
    assert(regions.Enqueue(0,3095,8)); // overlaps last: safe to merge
    std::vector<std::array<std::uint64_t,3>> precise;
    assert(regions.Drain([&](unsigned core,std::uint64_t addr,std::uint64_t sz) {
        precise.push_back({core,addr,sz});
    })==4);
    assert((precise[0]==std::array<std::uint64_t,3>{0,2040,8}));
    assert((precise[1]==std::array<std::uint64_t,3>{0,2048,8}));
    assert((precise[2]==std::array<std::uint64_t,3>{0,3072,8}));
    assert((precise[3]==std::array<std::uint64_t,3>{0,3090,13}));

    // GPU-owned writes must collect dirty ranges for the next fence and must
    // not overwrite GPU memory immediately. This is a caller contract.
    unsigned immediate = 0, held_for_fence = 0;
    assert(q.Enqueue(1, 4096, 8));
    assert(q.Enqueue(2, 8192, 8));
    q.Drain([&](unsigned, std::uint64_t addr, std::uint64_t) {
        if (addr == 4096) ++held_for_fence;
        else ++immediate;
    });
    assert(held_for_fence == 1 && immediate == 1);

    // Cross-core enqueue order is part of the memory coherency contract.
    // Previously a per-core sweep moved core 0 ahead of earlier core 2.
    Queue ordered;
    assert(ordered.Enqueue(2,12288,8));
    assert(ordered.Enqueue(0,4096,8));
    assert(ordered.Enqueue(3,16384,8));
    assert(ordered.Enqueue(1,8192,8));
    std::vector<unsigned> observed_order;
    assert(ordered.Drain([&](unsigned core, std::uint64_t, std::uint64_t) {
        observed_order.push_back(core);
    })==4);
    assert((observed_order == std::vector<unsigned>{2,0,3,1}));
    assert(!ordered.Pending());

    // Adjacent writes by the same core cannot merge when another core's
    // write sits between them in the global FIFO.
    Queue interleaved;
    assert(interleaved.Enqueue(0,64,8));
    assert(interleaved.Enqueue(1,4096,8));
    assert(interleaved.Enqueue(0,72,8));
    unsigned entries=0;
    assert(interleaved.Drain([&](unsigned,std::uint64_t,std::uint64_t) {
        ++entries;
    })==3);
    assert(entries==3);


    // Independent producer cores race with the GPU drain: every unique
    // page written must be replayed, including pushes during a drain.
    Queue concurrent;
    constexpr unsigned N = 320;
    std::array<std::atomic<unsigned>,4> seen{};
    std::array<std::atomic<bool>,4> done{};
    std::vector<std::thread> workers;
    for(unsigned c=0;c<4;++c) workers.emplace_back([&,c] {
        for(unsigned i=0;i<N;++i) {
            const std::uint64_t address = (std::uint64_t(c)*N+i+1)*4096;
            assert(concurrent.Enqueue(c,address,8));
            if ((i&7u)==0) std::this_thread::yield();
        }
        done[c].store(true,std::memory_order_release);
    });
    unsigned long long replay_count = 0;
    auto drain = [&](unsigned c, std::uint64_t addr, std::uint64_t size) {
        assert(size==8 && addr%4096==0);
        assert(addr/4096>std::uint64_t(c)*N &&
               addr/4096<=std::uint64_t(c+1)*N);
        seen[c].fetch_add(1,std::memory_order_relaxed);
        ++replay_count;
    };
    while(!done[0].load(std::memory_order_acquire) ||
          !done[1].load(std::memory_order_acquire) ||
          !done[2].load(std::memory_order_acquire) ||
          !done[3].load(std::memory_order_acquire) ||
          concurrent.Pending()) {
        concurrent.Drain(drain);
        std::this_thread::yield();
    }
    for(auto& t:workers)t.join();
    concurrent.Drain(drain);
    assert(replay_count==4*N);
    for(const auto& s:seen)assert(s.load()==N);
    // An open session must never silently recycle live ticket identities.
    assert(!concurrent.ResetAfterQuiescence());
    concurrent.Close();
    assert(concurrent.ResetAfterQuiescence());
    assert(!concurrent.Pending());
    assert(concurrent.Drain(drain)==0);

    // Sequence watermarks acknowledge merged writes, not just FIFO entries.
    Queue tracked;
    const auto a = tracked.EnqueueTracked(2, 100, 8);
    const auto b = tracked.EnqueueTracked(2, 104, 8);
    assert(a && b && a->sequence == 1 && b->sequence == 2);
    assert(a->generation == b->generation);
    assert(tracked.AcceptedSequence() == 2);
    assert(tracked.CompletedSequence() == 0 && tracked.Pending());
    std::optional<Queue::Ticket> late_ticket;
    std::atomic<bool> wait_done{false};
    std::atomic<bool> wait_ok{false};
    std::thread waiting_reader([&] {
        wait_ok.store(tracked.WaitUntil(*b), std::memory_order_release);
        wait_done.store(true, std::memory_order_release);
    });
    std::atomic<unsigned> batch_count{0};
    assert(tracked.DrainThrough(*b, [&](unsigned core, std::uint64_t addr, std::uint64_t sz) {
        assert(core == 2 && addr == 100 && sz == 12);
        assert(tracked.Pending()); // In-flight replay is not a completed ticket.
        batch_count.fetch_add(1);
        // A new producer during replay must not extend this drain indefinitely.
        late_ticket = tracked.EnqueueTracked(0, 4096, 8);
        assert(late_ticket && late_ticket->sequence == 3);
    }) == 1);
    waiting_reader.join();
    assert(wait_done.load() && wait_ok.load());
    assert(batch_count.load() == 1);
    assert(tracked.CompletedSequence() == 2);
    assert(tracked.AcceptedSequence() == 3 && tracked.Pending());
    assert(tracked.Drain([&](unsigned, std::uint64_t, std::uint64_t) {}) == 1);
    assert(tracked.CompletedSequence() == 3 && !tracked.Pending());
    assert(tracked.WaitUntil(*late_ticket));
    assert(!tracked.WaitUntil(Queue::Ticket{4, late_ticket->generation}));

    // A blocked read must escape on title shutdown rather than wait forever.
    Queue stopping;
    const auto ticket = stopping.EnqueueTracked(1, 8192, 8);
    assert(ticket && ticket->sequence == 1);
    std::atomic<bool> cancelled{false};
    std::thread blocked([&] { cancelled.store(!stopping.WaitUntil(*ticket)); });
    stopping.Close();
    blocked.join();
    assert(cancelled.load());
    assert(!stopping.EnqueueTracked(1, 12288, 8).has_value());
    assert(stopping.ResetAfterQuiescence());
    assert(!stopping.Pending() && stopping.Enqueue(1, 12288, 8));
    assert(stopping.Drain([](unsigned, std::uint64_t, std::uint64_t) {}) == 1);

    // Two GPU-owner attempts are serialized. The second must not replay a
    // newer write before the first callback completes, nor skip its own work.
    Queue single_owner;
    assert(single_owner.Enqueue(0, 16384, 8));
    std::atomic<bool> replay_entered{false};
    std::atomic<bool> release_replay{false};
    std::atomic<bool> first_callback_done{false};
    std::atomic<bool> second_started{false};
    std::atomic<bool> second_callback_done{false};
    std::thread first_owner([&] {
        assert(single_owner.Drain([&](unsigned, std::uint64_t, std::uint64_t) {
            replay_entered.store(true, std::memory_order_release);
            while (!release_replay.load(std::memory_order_acquire)) std::this_thread::yield();
            first_callback_done.store(true, std::memory_order_release);
        }) == 1);
    });
    while (!replay_entered.load(std::memory_order_acquire)) std::this_thread::yield();
    assert(single_owner.Enqueue(1, 20480, 8));
    std::thread second_owner([&] {
        second_started.store(true, std::memory_order_release);
        assert(single_owner.Drain([&](unsigned core, std::uint64_t, std::uint64_t) {
            assert(core == 1 && first_callback_done.load(std::memory_order_acquire));
            second_callback_done.store(true, std::memory_order_release);
        }) == 1);
    });
    while (!second_started.load(std::memory_order_acquire)) std::this_thread::yield();
    assert(single_owner.CompletedSequence() == 0);
    release_replay.store(true, std::memory_order_release);
    first_owner.join();
    second_owner.join();
    assert(first_callback_done.load() && second_callback_done.load());
    assert(single_owner.CompletedSequence() == 2 && !single_owner.Pending());

    // Regression: the replay callback continuously appends more writes.
    // DrainThrough must take ONE fixed queue snapshot, not keep draining
    // new work until producers finally stop. The old implementation did.
    Queue burst;
    const auto initial = burst.EnqueueTracked(0, 32768, 8);
    assert(initial && initial->sequence == 1);
    assert(burst.DrainThrough(*initial, [&](unsigned core, std::uint64_t, std::uint64_t) {
        assert(core == 0);
        for (unsigned i = 0; i < 400; ++i) {
            const auto added = burst.EnqueueTracked(1, (std::uint64_t(i) + 20) * 4096, 8);
            assert(added && added->sequence == i + 2);
        }
    }) == 1);
    assert(burst.CompletedSequence() == 1);
    assert(burst.AcceptedSequence() == 401 && burst.Pending());
    unsigned later_count = 0;
    assert(burst.Drain([&](unsigned core, std::uint64_t, std::uint64_t) {
        assert(core == 1);
        ++later_count;
    }) == 400);
    assert(later_count == 400 && !burst.Pending());
    assert(burst.CompletedSequence() == burst.AcceptedSequence());

    // A requested read ticket is a minimum completion target, not an
    // exact cutoff. The captured snapshot can acknowledge newer writes
    // accepted before the GPU consumer takes its snapshot.
    Queue snapshot;
    const auto early = snapshot.EnqueueTracked(0, 4096, 8);
    const auto later = snapshot.EnqueueTracked(1, 8192, 8);
    assert(early && later && early->sequence == 1 && later->sequence == 2);
    assert(snapshot.DrainThrough(*early, [](unsigned, std::uint64_t, std::uint64_t) {}) == 2);
    assert(snapshot.CompletedSequence() == later->sequence);
    assert(!snapshot.Pending());
    assert(snapshot.DrainThrough(*early, [](unsigned, std::uint64_t, std::uint64_t) {
        assert(false);
    }) == 0);

    // Two-phase publication: an out-of-order published write must not
    // leapfrog a prior reservation from another guest core.
    Queue two_phase;
    const auto first = two_phase.Reserve(1, 4096, 8);
    const auto second = two_phase.Reserve(3, 8192, 8);
    assert(first && second && first->sequence == 1 && second->sequence == 2);
    assert(first->generation == second->generation);
    assert(two_phase.Publish(*second));
    assert(!two_phase.Publish(*second));
    assert(two_phase.Pending() && two_phase.CompletedSequence() == 0);
    unsigned premature = 0;
    assert(two_phase.Drain([&](unsigned,std::uint64_t,std::uint64_t){++premature;}) == 0);
    assert(premature == 0);
    assert(two_phase.Publish(*first));
    std::vector<unsigned> published_order;
    assert(two_phase.Drain([&](unsigned core,std::uint64_t,std::uint64_t) {
        published_order.push_back(core);
    }) == 2);
    assert((published_order == std::vector<unsigned>{1,3}));
    assert(two_phase.WaitUntil(*first) && two_phase.WaitUntil(*second));
    assert(!two_phase.Publish(*first) && !two_phase.Pending());

    // Failed conditional/atomic store: cancel its reservation without
    // triggering an invalidation, but never overtake earlier published work.
    Queue cancelled_cas;
    const auto cas_before = cancelled_cas.Reserve(0, 4096, 8);
    const auto cas_failed = cancelled_cas.Reserve(1, 8192, 8);
    const auto cas_after = cancelled_cas.Reserve(2, 12288, 8);
    assert(cas_before && cas_failed && cas_after);
    assert(cancelled_cas.Publish(*cas_after));
    assert(cancelled_cas.Cancel(*cas_failed));
    assert(cancelled_cas.Drain([](unsigned,std::uint64_t,std::uint64_t) {
        assert(false);
    }) == 0);
    assert(cancelled_cas.Publish(*cas_before));
    std::vector<unsigned> cas_replayed;
    assert(cancelled_cas.Drain([&](unsigned core, std::uint64_t, std::uint64_t) {
        cas_replayed.push_back(core);
    }) == 2);
    assert((cas_replayed == std::vector<unsigned>{0,2}));
    assert(cancelled_cas.CompletedSequence() == cas_after->sequence);
    assert(cancelled_cas.WaitUntil(*cas_failed) && !cancelled_cas.Pending());
    assert(!cancelled_cas.Publish(*cas_failed));
    assert(!cancelled_cas.Cancel(*cas_failed));
    assert(!cancelled_cas.Cancel(*cas_after));
    // When the FIRST unpublished ticket is cancelled, it must wake the GPU
    // to replay a published tail. A cancellation is not a dropped sequence.
    Queue cancelled_head;
    const auto cancelled_head_ticket = cancelled_head.Reserve(0, 16384, 8);
    const auto real_tail_ticket = cancelled_head.Reserve(1, 20480, 8);
    assert(cancelled_head_ticket && real_tail_ticket);
    unsigned cancellation_wakes = 0;
    std::vector<unsigned> cancellation_replayed;
    auto cancellation_tick = [&] {
        ++cancellation_wakes;
        cancelled_head.Drain([&](unsigned core,std::uint64_t,std::uint64_t) {
            cancellation_replayed.push_back(core);
        });
    };
    assert(cancelled_head.PublishAndWake(*real_tail_ticket, cancellation_tick));
    assert(cancellation_wakes == 0);
    assert(cancelled_head.CancelAndWake(*cancelled_head_ticket, cancellation_tick));
    assert(cancellation_wakes == 1);
    assert((cancellation_replayed == std::vector<unsigned>{1}));
    assert(cancelled_head.CompletedSequence() == real_tail_ticket->sequence);
    assert(cancelled_head.WaitUntil(*cancelled_head_ticket));
    assert(!cancelled_head.Pending());
    assert(!cancelled_head.CancelAndWake(*cancelled_head_ticket, cancellation_tick));

    // Regression: a canceled conditional store may still be the FIFO tail.
    // An overlapping same-core real write MUST get a separate replayable
    // entry, not inherit the canceled flag through eager coalescing.
    Queue cancelled_tail;
    const auto failed_compare = cancelled_tail.Reserve(0, 0x1200, 16);
    assert(failed_compare && cancelled_tail.Cancel(*failed_compare));
    const auto actual_write = cancelled_tail.EnqueueTracked(0, 0x1200, 16);
    assert(actual_write && actual_write->sequence == failed_compare->sequence + 1);
    unsigned real_invalidations = 0;
    assert(cancelled_tail.Drain([&](unsigned core, std::uint64_t addr,
                                    std::uint64_t size) {
        assert(core == 0 && addr == 0x1200 && size == 16);
        ++real_invalidations;
    }) == 1);
    assert(real_invalidations == 1);
    assert(cancelled_tail.CompletedSequence() == actual_write->sequence);
    assert(cancelled_tail.WaitUntil(*actual_write));
    assert(!cancelled_tail.Pending());

    // A finished ordinary (non-atomic) CPU store is visible to replay
    // because Publish releases the queue mutex and the consumer acquires it.
    // No callback may execute before publication of this exact ticket.
    Queue publication;
    int guest_payload = 0;
    const auto delayed = publication.Reserve(0, 12288, sizeof(guest_payload));
    assert(delayed);
    assert(publication.Drain([](unsigned,std::uint64_t,std::uint64_t){assert(false);}) == 0);
    std::atomic<bool> started{false};
    std::thread producer([&] {
        started.store(true, std::memory_order_release);
        guest_payload = 0x12345;
        assert(publication.Publish(*delayed));
    });
    while (!started.load(std::memory_order_acquire)) std::this_thread::yield();
    unsigned observed = 0;
    while (publication.CompletedSequence() < delayed->sequence) {
        publication.Drain([&](unsigned core,std::uint64_t addr,std::uint64_t sz) {
            assert(core == 0 && addr == 12288 && sz == sizeof(guest_payload));
            assert(guest_payload == 0x12345);
            ++observed;
        });
        std::this_thread::yield();
    }
    producer.join();
    assert(observed == 1 && publication.WaitUntil(*delayed));

    // Published entries before an uncommitted reservation can drain.
    // Published entries after that reservation must wait.
    Queue partial;
    assert(partial.Enqueue(0, 4096, 8));
    const auto hole = partial.Reserve(1, 8192, 8);
    assert(hole);
    assert(partial.Enqueue(2, 16384, 8));
    std::vector<unsigned> prefix;
    assert(partial.Drain([&](unsigned c,std::uint64_t,std::uint64_t) {
        prefix.push_back(c);
    }) == 1);
    assert((prefix == std::vector<unsigned>{0}));
    assert(partial.CompletedSequence() == 1 && partial.Pending());
    assert(partial.Drain([](unsigned,std::uint64_t,std::uint64_t){assert(false);}) == 0);
    assert(partial.Publish(*hole));
    assert(partial.Drain([&](unsigned c,std::uint64_t,std::uint64_t) {
        prefix.push_back(c);
    }) == 2);
    assert((prefix == std::vector<unsigned>{0,1,2}));
    assert(!partial.Pending());

    // Stale sessions, invalid tickets, and teardown cancellation.
    Queue lifetime;
    const auto old = lifetime.Reserve(2, 24576, 8);
    assert(old);
    assert(!lifetime.Publish(Queue::Ticket{0, old->generation}));
    assert(!lifetime.Publish(Queue::Ticket{old->sequence + 1, old->generation}));
    lifetime.Close();
    assert(!lifetime.Publish(*old));
    assert(!lifetime.WaitUntil(*old));
    assert(lifetime.ResetAfterQuiescence());
    const auto fresh = lifetime.Reserve(2, 24576, 8);
    assert(fresh && fresh->sequence == old->sequence &&
           fresh->generation != old->generation);
    assert(!lifetime.Publish(*old));
    assert(!lifetime.WaitUntil(*old));
    // Different address spaces can carry sequence 1 at the same time, but
    // their ticket epochs must never be interchangeable.
    Queue foreign_space;
    const auto foreign = foreign_space.Reserve(2, 24576, 8);
    assert(foreign && foreign->sequence == fresh->sequence);
    assert(foreign->generation != fresh->generation);
    assert(!lifetime.Publish(*foreign));
    assert(!lifetime.WaitUntil(*foreign));
    assert(lifetime.DrainThrough(*foreign,
        [](unsigned,std::uint64_t,std::uint64_t){assert(false);}) == 0);
    assert(!foreign_space.Publish(*fresh));
    assert(lifetime.Publish(*fresh));
    // The sequence number is identical, but the previous title session
    // must be rejected even at a GPU drain boundary.
    assert(lifetime.DrainThrough(*old, [](unsigned,std::uint64_t,std::uint64_t){
        assert(false);
    }) == 0);
    assert(lifetime.Pending() && lifetime.CompletedSequence() == 0);
    assert(lifetime.DrainThrough(*fresh,
        [](unsigned,std::uint64_t,std::uint64_t){}) == 1);
    assert(lifetime.WaitUntil(*fresh));

    // Multiple CPU producers publish DIFFERENT RAM payloads out of order.
    // Replay must stay FIFO and must never observe a pre-publication value.
    // Entries are spaced apart so ordinary coalescing cannot hide a hole.
    Queue concurrent_publication;
    constexpr unsigned PublishedWrites = 128;
    std::array<Queue::Ticket, PublishedWrites> reserved_tickets{};
    std::array<unsigned, PublishedWrites> guest_values{};
    std::array<std::atomic<bool>, 4> finished_publishers{};
    for (unsigned i = 0; i < PublishedWrites; ++i) {
        auto ticket = concurrent_publication.Reserve(i % 4,
                                                     (std::uint64_t(i) + 1) * 4096, 8);
        assert(ticket && ticket->sequence == i + 1);
        reserved_tickets[i] = *ticket;
    }
    std::vector<std::thread> publishers;
    for (unsigned core = 0; core < 4; ++core) {
        publishers.emplace_back([&, core] {
            for (int index = int(PublishedWrites) - 4 + int(core);
                 index >= 0; index -= 4) {
                guest_values[unsigned(index)] = unsigned(index) + 1;
                assert(concurrent_publication.Publish(reserved_tickets[unsigned(index)]));
                if ((index & 15) == 0) std::this_thread::yield();
            }
            finished_publishers[core].store(true, std::memory_order_release);
        });
    }
    unsigned next_replay_index = 0;
    const auto verify_publication = [&](unsigned core, std::uint64_t addr,
                                        std::uint64_t size) {
        const auto index = unsigned(addr / 4096 - 1);
        assert(size == 8 && index == next_replay_index);
        assert(core == index % 4);
        // Plain CPU backing-RAM values, synchronized only by Publish and the
        // replay snapshot's mutex acquisition.
        assert(guest_values[index] == index + 1);
        ++next_replay_index;
    };
    while (true) {
        concurrent_publication.Drain(verify_publication);
        bool producers_done = true;
        for (const auto& done : finished_publishers)
            producers_done &= done.load(std::memory_order_acquire);
        if (producers_done && !concurrent_publication.Pending()) break;
        std::this_thread::yield();
    }
    for (auto& publisher : publishers) publisher.join();
    assert(next_replay_index == PublishedWrites);
    assert(concurrent_publication.CompletedSequence() == PublishedWrites);
    assert(!concurrent_publication.Pending());

    // Backlog regression: reverse publication across thousands of tickets.
    // A linear Publish() search performs quadratic work in this case; binary
    // lookup must preserve the exact sequence and FIFO replay semantics.
    Queue reverse_publish;
    constexpr unsigned BacklogWrites = 4096;
    std::vector<Queue::Ticket> backlog;
    backlog.reserve(BacklogWrites);
    for (unsigned i = 0; i < BacklogWrites; ++i) {
        const auto t = reverse_publish.Reserve(i % Queue::Cores,
                                               (std::uint64_t(i) + 512) * 4096, 8);
        assert(t && t->sequence == i + 1);
        backlog.push_back(*t);
    }
    for (unsigned i = BacklogWrites - 1; i != 0; --i) {
        assert(reverse_publish.Publish(backlog[i]));
        assert(!reverse_publish.Publish(backlog[i]));
        if (i == BacklogWrites - 1 || i == 1) {
            assert(reverse_publish.Drain(
                [](unsigned,std::uint64_t,std::uint64_t){assert(false);}) == 0);
        }
    }
    assert(reverse_publish.CompletedSequence() == 0);
    assert(reverse_publish.Pending());
    assert(reverse_publish.Publish(backlog.front()));
    unsigned replayed_backlog = 0;
    assert(reverse_publish.Drain([&](unsigned core, std::uint64_t addr,
                                     std::uint64_t size) {
        assert(size == 8);
        assert(addr == (std::uint64_t(replayed_backlog) + 512) * 4096);
        assert(core == replayed_backlog % Queue::Cores);
        ++replayed_backlog;
    }) == BacklogWrites);
    assert(replayed_backlog == BacklogWrites);
    assert(reverse_publish.CompletedSequence() == BacklogWrites);
    assert(reverse_publish.WaitUntil(backlog.back()) && !reverse_publish.Pending());
    assert(!reverse_publish.Publish(backlog.back()));

    // Draining a prefix shifts the queue. New lower-bound lookups must still
    // resolve surviving out-of-order reservations, not removed sequence IDs.
    Queue sliced_backlog;
    const auto consumed = sliced_backlog.EnqueueTracked(0, 2048, 8);
    const auto hold = sliced_backlog.Reserve(1, 8192, 8);
    const auto after_hold = sliced_backlog.Reserve(2, 12288, 8);
    assert(consumed && hold && after_hold);
    assert(sliced_backlog.Drain([](unsigned,std::uint64_t,std::uint64_t){}) == 1);
    assert(!sliced_backlog.Publish(*consumed));
    assert(sliced_backlog.Publish(*after_hold));
    assert(sliced_backlog.Drain(
        [](unsigned,std::uint64_t,std::uint64_t){assert(false);}) == 0);
    assert(sliced_backlog.Publish(*hold));
    std::vector<unsigned> sliced_order;
    assert(sliced_backlog.Drain([&](unsigned core,std::uint64_t,std::uint64_t) {
        sliced_order.push_back(core);
    }) == 2);
    assert((sliced_order == std::vector<unsigned>{1,2}));
    assert(!sliced_backlog.Pending());

    // Shutdown must not race the renderer's replay callback lifetime.
    // An unpublished second write also gives a reliable wait-to-close signal.
    Queue teardown;
    const auto active = teardown.EnqueueTracked(0, 32768, 8);
    const auto waiting = teardown.Reserve(1, 65536, 8);
    assert(active && waiting);
    std::atomic<bool> replay_active{false};
    std::atomic<bool> release_gpu{false};
    std::atomic<bool> close_returned{false};
    std::atomic<bool> waiting_cancelled{false};
    std::thread gpu_owner([&] {
        assert(teardown.Drain([&](unsigned c,std::uint64_t,std::uint64_t) {
            assert(c == 0);
            replay_active.store(true, std::memory_order_release);
            while (!release_gpu.load(std::memory_order_acquire))
                std::this_thread::yield();
        }) == 1);
    });
    while (!replay_active.load(std::memory_order_acquire))
        std::this_thread::yield();
    std::thread cpu_reader([&] {
        waiting_cancelled.store(!teardown.WaitUntil(*waiting),
                                std::memory_order_release);
    });
    std::thread title_close([&] {
        teardown.Close();
        close_returned.store(true, std::memory_order_release);
    });
    // A cancelled CPU waiter proves Close() has set the close flag and sent
    // its notification while the GPU callback is still blocked.
    while (!waiting_cancelled.load(std::memory_order_acquire))
        std::this_thread::yield();
    assert(!close_returned.load(std::memory_order_acquire));
    assert(!teardown.Publish(*waiting));
    assert(!teardown.EnqueueTracked(1, 98304, 8));
    release_gpu.store(true, std::memory_order_release);
    gpu_owner.join();
    cpu_reader.join();
    title_close.join();
    assert(close_returned.load(std::memory_order_acquire));
    assert(teardown.CompletedSequence() == active->sequence);
    // This callback completed while shutdown was joining GPU ownership.
    // Its CPU wait ticket MUST still fail after Close().
    assert(!teardown.WaitUntil(*active));
    assert(teardown.Drain([](unsigned,std::uint64_t,std::uint64_t) {
        assert(false); // Never replay remaining queued work after Close().
    }) == 0);
    assert(teardown.Pending()); // Unpublished reservation awaits teardown.
    assert(teardown.ResetAfterQuiescence());
    assert(!teardown.Pending());

    // Closing with a queued but not yet replayed write also forbids late
    // rasterizer invocation, even if a stale GPU tick arrives afterwards.
    Queue closed_before_replay;
    const auto never_replay = closed_before_replay.EnqueueTracked(3, 131072, 8);
    assert(never_replay);
    closed_before_replay.Close();
    assert(closed_before_replay.DrainThrough(*never_replay,
        [](unsigned,std::uint64_t,std::uint64_t) {assert(false);}) == 0);
    assert(!closed_before_replay.WaitUntil(*never_replay));

    // A cache replay callback can fail after partially applying invalidation.
    // The queue must NEVER report that snapshot as completed or retry it:
    // retrying may duplicate partially applied GPU/texture side effects.
    Queue poisoned;
    const auto first_write = poisoned.EnqueueTracked(0, 262144, 8);
    const auto second_write = poisoned.EnqueueTracked(1, 266240, 8);
    const auto not_yet_published = poisoned.Reserve(2, 270336, 8);
    assert(first_write && second_write && not_yet_published);
    std::atomic<bool> failed_reader{false};
    std::thread poison_reader([&] {
        failed_reader.store(!poisoned.WaitUntil(*second_write),
                            std::memory_order_release);
    });
    unsigned replay_attempts = 0;
    bool saw_error = false;
    try {
        poisoned.Drain([&](unsigned, std::uint64_t, std::uint64_t) {
            ++replay_attempts;
            if (replay_attempts == 2)
                throw std::runtime_error("partial rasterizer replay failed");
        });
    } catch (const std::runtime_error&) {
        saw_error = true;
    }
    poison_reader.join();
    assert(saw_error && replay_attempts == 2);
    assert(failed_reader.load(std::memory_order_acquire));
    assert(poisoned.Failed() && poisoned.Pending());
    assert(poisoned.CompletedSequence() == 0);
    assert(poisoned.AcceptedSequence() == not_yet_published->sequence);
    assert(!poisoned.Publish(*not_yet_published));
    assert(!poisoned.EnqueueTracked(3, 274432, 8));
    assert(!poisoned.WaitUntil(*first_write));
    assert(!poisoned.WaitUntil(*second_write));
    assert(poisoned.Drain([&](unsigned, std::uint64_t, std::uint64_t) {
        assert(false); // A poisoned session may not silently resume.
    }) == 0);
    poisoned.Close();
    assert(poisoned.ResetAfterQuiescence()); // Strictly after all threads have joined.
    assert(!poisoned.Failed() && !poisoned.Pending());
    const auto recovered = poisoned.EnqueueTracked(0, 278528, 8);
    assert(recovered && recovered->generation != first_write->generation);
    assert(poisoned.Drain([](unsigned,std::uint64_t,std::uint64_t){}) == 1);
    assert(poisoned.WaitUntil(*recovered));

    // A replay callback cannot reset the queue while it owns its GPU
    // consumer mutex, irrespective of the external session state.
    Queue nested_reset;
    const auto nested_ticket = nested_reset.EnqueueTracked(2, 282624, 8);
    assert(nested_ticket);
    assert(nested_reset.Drain([&](unsigned,std::uint64_t,std::uint64_t) {
        assert(!nested_reset.ResetAfterQuiescence());
    }) == 1);
    assert(nested_reset.WaitUntil(*nested_ticket));

    // Lost-wakeup regression: GPU sees an unpublished FIFO head and exits
    // Drain(), while later writes can be published in arbitrary order.
    // Publishing the blocked HEAD must schedule another tick; publishing
    // a ready tail must NOT fire redundant notifications.
    Queue wake;
    const auto stalled = wake.Reserve(0, 4096, 8);
    const auto middle = wake.Reserve(1, 8192, 8);
    const auto tail = wake.Reserve(2, 12288, 8);
    assert(stalled && middle && tail);
    unsigned wakes = 0;
    unsigned replayed = 0;
    auto gpu_tick = [&] {
        ++wakes;
        // Synchronous GPU work from the callback verifies the queue mutex
        // was released before the wake was invoked.
        wake.Drain([&](unsigned core, std::uint64_t addr, std::uint64_t sz) {
            assert(sz == 8 && core == replayed);
            assert(addr == (std::uint64_t(replayed) + 1) * 4096);
            ++replayed;
        });
    };
    assert(wake.Drain([](unsigned,std::uint64_t,std::uint64_t) {
        assert(false);
    }) == 0);
    assert(wake.PublishAndWake(*tail, gpu_tick));
    assert(wake.PublishAndWake(*middle, gpu_tick));
    assert(wakes == 0 && replayed == 0);
    assert(wake.PublishAndWake(*stalled, gpu_tick));
    assert(wakes == 1 && replayed == 3 && !wake.Pending());
    assert(!wake.PublishAndWake(*middle, gpu_tick) && wakes == 1);

    // A published prefix can drain before an unpublished hole. Publishing
    // the hole later MUST reschedule the owner; the first tick is insufficient.
    Queue gap_wake;
    const auto head0 = gap_wake.Reserve(0, 16384, 8);
    const auto hole1 = gap_wake.Reserve(1, 20480, 8);
    const auto after2 = gap_wake.Reserve(2, 24576, 8);
    assert(head0 && hole1 && after2);
    unsigned gap_ticks = 0;
    unsigned gap_replayed = 0;
    auto tick_gap = [&] {
        ++gap_ticks;
        gap_wake.Drain([&](unsigned core,std::uint64_t,std::uint64_t) {
            assert(core == gap_replayed);
            ++gap_replayed;
        });
    };
    assert(gap_wake.PublishAndWake(*head0, tick_gap));
    assert(gap_ticks == 1 && gap_replayed == 1);
    assert(gap_wake.PublishAndWake(*after2, tick_gap));
    assert(gap_ticks == 1);
    assert(gap_wake.PublishAndWake(*hole1, tick_gap));
    assert(gap_ticks == 2 && gap_replayed == 3);
    assert(!gap_wake.Pending());

    // Multiple published tails are not a storm of redundant GPU ticks.
    // Publish the head last after 256 others; one wake replays all 257.
    Queue coalesce_wake;
    constexpr unsigned WakeBacklog = 256;
    std::vector<Queue::Ticket> wake_tickets;
    for (unsigned i = 0; i < WakeBacklog; ++i) {
        const auto t = coalesce_wake.Reserve(i % 4, 32768 + std::uint64_t(i) * 4096, 8);
        assert(t);
        wake_tickets.push_back(*t);
    }
    unsigned scheduled_ticks = 0, wake_replayed = 0;
    auto tick_coalesced = [&] {
        ++scheduled_ticks;
        coalesce_wake.Drain([&](unsigned core,std::uint64_t,std::uint64_t) {
            assert(core == wake_replayed % 4);
            ++wake_replayed;
        });
    };
    for (unsigned i = WakeBacklog - 1; i > 0; --i)
        assert(coalesce_wake.PublishAndWake(wake_tickets[i], tick_coalesced));
    assert(scheduled_ticks == 0 && wake_replayed == 0);
    assert(coalesce_wake.PublishAndWake(wake_tickets[0], tick_coalesced));
    assert(scheduled_ticks == 1 && wake_replayed == WakeBacklog);
    assert(!coalesce_wake.Pending());

    // Explicit bool-returning scheduling callbacks must be accepted, not
    // merely invoked. A false return leaves an already published FIFO head
    // without a GPU tick; fail closed instead of stranding a reader.
    Queue bool_wake_ok;
    const auto bool_ok_ticket = bool_wake_ok.Reserve(0, 0xC000, 8);
    assert(bool_ok_ticket);
    assert(bool_wake_ok.PublishAndWake(*bool_ok_ticket, [&]() -> bool {
        return bool_wake_ok.Drain([](unsigned,std::uint64_t,std::uint64_t) {}) == 1;
    }));
    assert(bool_wake_ok.WaitUntil(*bool_ok_ticket) && !bool_wake_ok.Failed());

    Queue bool_wake_rejected;
    const auto bool_bad_ticket = bool_wake_rejected.Reserve(0, 0xD000, 8);
    assert(bool_bad_ticket);
    bool bool_wake_threw = false;
    try {
        (void)bool_wake_rejected.PublishAndWake(*bool_bad_ticket, []() -> bool {
            return false;
        });
    } catch (const std::runtime_error&) {
        bool_wake_threw = true;
    }
    assert(bool_wake_threw && bool_wake_rejected.Failed());
    assert(!bool_wake_rejected.WaitUntil(*bool_bad_ticket));
    assert(!bool_wake_rejected.Reserve(1, 0xE000, 8));

    Queue bool_cancel_rejected;
    const auto bool_cancel_ticket = bool_cancel_rejected.Reserve(0, 0xF000, 8);
    assert(bool_cancel_ticket);
    bool bool_cancel_threw = false;
    try {
        (void)bool_cancel_rejected.CancelAndWake(*bool_cancel_ticket, []() -> bool {
            return false;
        });
    } catch (const std::runtime_error&) {
        bool_cancel_threw = true;
    }
    assert(bool_cancel_threw && bool_cancel_rejected.Failed());
    assert(!bool_cancel_rejected.WaitUntil(*bool_cancel_ticket));

    // A failed GPU wake must poison this title rather than strand a reader.
    Queue wake_failure;
    const auto pending_wake = wake_failure.Reserve(0, 65536, 8);
    assert(pending_wake);
    bool failed_to_schedule = false;
    try {
        wake_failure.PublishAndWake(*pending_wake, [] {
            throw std::runtime_error("GPU scheduling failed");
        });
    } catch (const std::runtime_error&) {
        failed_to_schedule = true;
    }
    assert(failed_to_schedule && wake_failure.Failed());
    assert(!wake_failure.WaitUntil(*pending_wake));
    assert(wake_failure.Drain([](unsigned,std::uint64_t,std::uint64_t) {
        assert(false);
    }) == 0);
    assert(!wake_failure.Enqueue(1, 69632, 8));
    wake_failure.Close();
    assert(wake_failure.ResetAfterQuiescence());
    assert(!wake_failure.Failed());

    // Closing a title while a producer is still inside the post-store wake
    // callback must wait for that callback, not just for GPU replay. This
    // prevents an in-flight request from touching a freed GPU scheduler.
    Queue wake_lifetime;
    const auto lifetime_wake = wake_lifetime.Reserve(0, 98304, 8);
    assert(lifetime_wake);
    std::atomic<bool> notify_entered{false};
    std::atomic<bool> release_notify{false};
    std::atomic<bool> woke_close_returned{false};
    std::atomic<bool> woke_reader_cancelled{false};
    std::thread waking_producer([&] {
        assert(wake_lifetime.PublishAndWake(*lifetime_wake, [&] {
            notify_entered.store(true, std::memory_order_release);
            while (!release_notify.load(std::memory_order_acquire))
                std::this_thread::yield();
        }));
    });
    while (!notify_entered.load(std::memory_order_acquire))
        std::this_thread::yield();
    std::thread woke_reader([&] {
        woke_reader_cancelled.store(!wake_lifetime.WaitUntil(*lifetime_wake),
                                    std::memory_order_release);
    });
    std::thread closing_wake([&] {
        wake_lifetime.Close();
        woke_close_returned.store(true, std::memory_order_release);
    });
    while (!woke_reader_cancelled.load(std::memory_order_acquire))
        std::this_thread::yield();
    assert(!woke_close_returned.load(std::memory_order_acquire));
    release_notify.store(true, std::memory_order_release);
    waking_producer.join();
    woke_reader.join();
    closing_wake.join();
    assert(woke_close_returned.load(std::memory_order_acquire));
    assert(!wake_lifetime.Publish(*lifetime_wake));
    assert(wake_lifetime.ResetAfterQuiescence());
    assert(!wake_lifetime.Pending());

    // Actual asynchronous host GPU scheduling: the first GPU tick can still
    // be executing after its ready snapshot was removed. When another
    // reservation becomes ready behind it, a second wake must survive until
    // the GPU worker returns from the first replay callback.
    Queue asynchronous;
    const auto async_a = asynchronous.Reserve(0, 4096, 8);
    const auto async_b = asynchronous.Reserve(1, 8192, 8);
    const auto async_c = asynchronous.Reserve(2, 12288, 8);
    assert(async_a && async_b && async_c);
    std::mutex scheduler_mutex;
    std::condition_variable scheduler_cv;
    unsigned tick_requests = 0;
    bool stop_scheduler = false;
    std::atomic<bool> first_callback_entered{false};
    std::atomic<bool> release_first_callback{false};
    std::atomic<unsigned> callback_count{0};
    auto schedule_gpu = [&] {
        {
            std::lock_guard lock(scheduler_mutex);
            ++tick_requests;
        }
        scheduler_cv.notify_one();
    };
    std::thread gpu_worker([&] {
        while (true) {
            {
                std::unique_lock lock(scheduler_mutex);
                scheduler_cv.wait(lock, [&] { return tick_requests != 0 || stop_scheduler; });
                if (tick_requests == 0 && stop_scheduler) break;
                --tick_requests;
            }
            asynchronous.Drain([&](unsigned core,std::uint64_t addr,std::uint64_t sz) {
                const auto index = callback_count.fetch_add(1);
                assert(core == index && sz == 8 &&
                       addr == (std::uint64_t(index) + 1) * 4096);
                if (index == 0) {
                    first_callback_entered.store(true, std::memory_order_release);
                    while (!release_first_callback.load(std::memory_order_acquire))
                        std::this_thread::yield();
                }
            });
        }
    });
    assert(asynchronous.PublishAndWake(*async_a, schedule_gpu));
    while (!first_callback_entered.load(std::memory_order_acquire))
        std::this_thread::yield();
    // The GPU is busy with the first snapshot. C cannot pass B; B becoming
    // ready requests a new GPU tick even while the first one is in flight.
    assert(asynchronous.PublishAndWake(*async_c, schedule_gpu));
    assert(asynchronous.PublishAndWake(*async_b, schedule_gpu));
    release_first_callback.store(true, std::memory_order_release);
    assert(asynchronous.WaitUntil(*async_c));
    {
        std::lock_guard lock(scheduler_mutex);
        stop_scheduler = true;
    }
    scheduler_cv.notify_one();
    gpu_worker.join();
    assert(callback_count.load() == 3 && !asynchronous.Pending());
    asynchronous.Close();
    assert(asynchronous.ResetAfterQuiescence());

    // A completed write is NOT a valid read ticket once its title has
    // closed. The previous implementation returned true based only on the
    // completion watermark, even after Close() finished.
    Queue completed_then_closed;
    const auto done_before_close = completed_then_closed.EnqueueTracked(0, 131072, 8);
    assert(done_before_close);
    assert(completed_then_closed.Drain(
        [](unsigned,std::uint64_t,std::uint64_t){}) == 1);
    assert(completed_then_closed.WaitUntil(*done_before_close));
    completed_then_closed.Close();
    assert(!completed_then_closed.WaitUntil(*done_before_close));

    // Same failure contract after a previously completed write followed by
    // a partial replay exception: completed tickets from a poisoned session
    // cannot authorize further guest reads.
    Queue poisoned_after_success;
    const auto prior = poisoned_after_success.EnqueueTracked(0, 135168, 8);
    assert(prior);
    assert(poisoned_after_success.Drain(
        [](unsigned,std::uint64_t,std::uint64_t){}) == 1);
    assert(poisoned_after_success.WaitUntil(*prior));
    const auto causes_failure = poisoned_after_success.EnqueueTracked(1, 139264, 8);
    assert(causes_failure);
    bool callback_failed = false;
    try {
        poisoned_after_success.Drain([](unsigned,std::uint64_t,std::uint64_t) {
            throw std::runtime_error("GPU cache replay failed");
        });
    } catch (const std::runtime_error&) {
        callback_failed = true;
    }
    assert(callback_failed && poisoned_after_success.Failed());
    assert(!poisoned_after_success.WaitUntil(*prior));
    assert(!poisoned_after_success.WaitUntil(*causes_failure));
    poisoned_after_success.Close();
    assert(poisoned_after_success.ResetAfterQuiescence());

    // A stalled/unpublished FIFO head must not allow unlimited memory
    // accumulation. Saturation rejects reservations BEFORE their guest RAM
    // store; the caller must execute its original synchronous fallback.
    Queue bounded;
    std::vector<Queue::Ticket> accepted;
    accepted.reserve(Queue::MaxOutstandingWrites);
    for (Queue::Sequence i = 0; i < Queue::MaxOutstandingWrites; ++i) {
        auto ticket = bounded.Reserve(unsigned(i % Queue::Cores),
                                      (i + 1) * 4096, 8);
        assert(ticket && ticket->sequence == i + 1);
        accepted.push_back(*ticket);
    }
    assert(bounded.AcceptedSequence() == Queue::MaxOutstandingWrites);
    assert(bounded.Pending());
    assert(!bounded.Reserve(0, 0x20000000, 8));
    assert(!bounded.EnqueueTracked(1, 0x20001000, 8));
    assert(bounded.AcceptedSequence() == Queue::MaxOutstandingWrites);

    // Saturation must not suppress Publish for already accepted writes.
    // Reverse-order publication cannot bypass the pending first write.
    for (std::size_t i = accepted.size(); i-- > 1;)
        assert(bounded.Publish(accepted[i]));
    assert(bounded.Drain([](unsigned,std::uint64_t,std::uint64_t) {
        assert(false);
    }) == 0);
    assert(bounded.Publish(accepted.front()));
    unsigned replayed_bounded = 0;
    assert(bounded.Drain([&](unsigned c,std::uint64_t a,std::uint64_t n) {
        assert(n == 8 && c == replayed_bounded % Queue::Cores);
        assert(a == (std::uint64_t(replayed_bounded) + 1) * 4096);
        if (replayed_bounded == 0) {
            // Snapshot has left queue_, but its guest writes are NOT yet
            // acknowledged. The pending budget must include in-flight work.
            assert(!bounded.Reserve(0, 0x20002000, 8));
        }
        ++replayed_bounded;
    }) == Queue::MaxOutstandingWrites);
    assert(replayed_bounded == Queue::MaxOutstandingWrites);
    assert(!bounded.Pending());
    assert(bounded.WaitUntil(accepted.back()));
    auto post_drain = bounded.Reserve(3, 0x20003000, 8);
    assert(post_drain);
    assert(bounded.Publish(*post_drain));
    assert(bounded.Drain([](unsigned,std::uint64_t,std::uint64_t) {}) == 1);

    // Ordered producer saturation: all older writes must reach replay
    // before the newly reserved write can proceed to its guest RAM store.
    Queue ordered_pressure;
    for (Queue::Sequence i = 0; i < Queue::MaxOutstandingWrites; ++i)
        assert(ordered_pressure.EnqueueTracked(unsigned(i % 4),
               0x100000 + i * 4096, 8));
    unsigned older_replayed = 0, pressure_wakes = 0;
    const auto resumed = ordered_pressure.ReserveOrdered(3, 0x9000000, 8, [&]() -> bool {
        ++pressure_wakes;
        return ordered_pressure.Drain([&](unsigned core, std::uint64_t addr,
                                           std::uint64_t size) {
            assert(core == older_replayed % 4 &&
                   addr == 0x100000 + std::uint64_t(older_replayed) * 4096 &&
                   size == 8);
            ++older_replayed;
        }) == Queue::MaxOutstandingWrites;
    });
    assert(resumed && pressure_wakes == 1 &&
           older_replayed == Queue::MaxOutstandingWrites &&
           resumed->sequence == Queue::MaxOutstandingWrites + 1);
    assert(ordered_pressure.Publish(*resumed));
    assert(ordered_pressure.Drain([&](unsigned core, std::uint64_t addr,
                                      std::uint64_t size) {
        assert(core == 3 && addr == 0x9000000 && size == 8);
    }) == 1);

    // Saturation while a previous store is still unpublished. The first
    // wake cannot replay that head; a later PublishAndWake must unblock the
    // waiting ordered producer without an unsafe synchronous fallback.
    Queue blocked_pressure;
    const auto held = blocked_pressure.Reserve(0, 0x500000, 8);
    assert(held);
    for (Queue::Sequence i = 1; i < Queue::MaxOutstandingWrites; ++i)
        assert(blocked_pressure.EnqueueTracked(unsigned(i % 4),
               0x600000 + i * 4096, 8));
    std::atomic<bool> pressure_started{false};
    std::atomic<bool> pressure_initial_drain{false};
    std::atomic<bool> pressure_finished{false};
    std::thread blocked_producer([&] {
        pressure_started.store(true, std::memory_order_release);
        const auto ticket = blocked_pressure.ReserveOrdered(1, 0xA000000, 8, [&] {
            // A synchronous GPU owner sees no published prefix yet.
            assert(blocked_pressure.Drain([](unsigned,std::uint64_t,std::uint64_t) {
                assert(false);
            }) == 0);
            pressure_initial_drain.store(true, std::memory_order_release);
        });
        assert(ticket);
        assert(ticket->sequence == Queue::MaxOutstandingWrites + 1);
        pressure_finished.store(true, std::memory_order_release);
        assert(blocked_pressure.Publish(*ticket));
    });
    while (!pressure_started.load(std::memory_order_acquire) ||
           !pressure_initial_drain.load(std::memory_order_acquire))
        std::this_thread::yield();
    assert(!pressure_finished.load(std::memory_order_acquire));
    assert(blocked_pressure.PublishAndWake(*held, [&] {
        assert(blocked_pressure.Drain([&](unsigned,std::uint64_t,std::uint64_t) {}) ==
               Queue::MaxOutstandingWrites);
    }));
    blocked_producer.join();
    assert(pressure_finished.load(std::memory_order_acquire));
    assert(blocked_pressure.Drain([](unsigned,std::uint64_t,std::uint64_t) {}) == 1);

    // A scheduler failure must poison and wake blocked producers, not
    // silently let them perform an out-of-order cache invalidation.
    Queue pressure_failure;
    for (Queue::Sequence i = 0; i < Queue::MaxOutstandingWrites; ++i)
        assert(pressure_failure.EnqueueTracked(unsigned(i % 4),
               0x100000 + i * 4096, 8));
    bool pressure_threw = false;
    try {
        (void)pressure_failure.ReserveOrdered(0, 0xA100000, 8, [] {
            throw std::runtime_error("GPU wake rejected");
        });
    } catch (const std::runtime_error&) {
        pressure_threw = true;
    }
    assert(pressure_threw && pressure_failure.Failed());
    assert(!pressure_failure.Reserve(0, 0xA200000, 8));

    // Bool-returning scheduling rejection must also release a producer
    // whose Queue is saturated. The helper must never enter WaitUntil on
    // an explicit failure or permit an out-of-order cache invalidation.
    Queue pressure_bool_rejected;
    for (Queue::Sequence i = 0; i < Queue::MaxOutstandingWrites; ++i)
        assert(pressure_bool_rejected.EnqueueTracked(unsigned(i % Queue::Cores),
               0x100000 + i * 4096, 8));
    bool pressure_bool_threw = false;
    try {
        (void)pressure_bool_rejected.ReserveOrdered(0, 0xB100000, 8, []() -> bool {
            return false;
        });
    } catch (const std::runtime_error&) {
        pressure_bool_threw = true;
    }
    assert(pressure_bool_threw && pressure_bool_rejected.Failed());
    assert(!pressure_bool_rejected.Reserve(0, 0xB200000, 8));

    // The queue can recycle an emptied GPU snapshot without losing its
    // capacity on every frame. If a producer enqueues DURING replay, its
    // newer tail must remain intact; subsequent empty-burst drains still
    // preserve sequence watermarks and exact callback counts.
    Queue recycled;
    unsigned recycled_callbacks = 0;
    for (unsigned round = 0; round < 64; ++round) {
        for (unsigned i = 0; i < 32; ++i)
            assert(recycled.EnqueueTracked(i % Queue::Cores,
                    0xC000000 + (std::uint64_t(round) * 32 + i) * 4096, 8));
        unsigned seen = 0;
        const auto before = recycled.CompletedSequence();
        assert(recycled.Drain([&](unsigned, std::uint64_t, std::uint64_t size) {
            assert(size == 8);
            if (round == 0 && seen == 0)
                assert(recycled.EnqueueTracked(1, 0xE000000, 8));
            ++seen;
            ++recycled_callbacks;
        }) == 32);
        assert(seen == 32);
        assert(recycled.CompletedSequence() == before + 32);
        if (round == 0) {
            assert(recycled.Pending());
            assert(recycled.Drain([&](unsigned core, std::uint64_t address,
                                       std::uint64_t size) {
                assert(core == 1 && address == 0xE000000 && size == 8);
                ++recycled_callbacks;
            }) == 1);
        }
        assert(!recycled.Pending());
    }
    assert(recycled_callbacks == 64 * 32 + 1);

    // Coalescing does not create an unbounded accepted-sequence backlog
    // disguised as one vector entry: throttle the outstanding watermark.
    Queue coalesced_budget;
    for (Queue::Sequence i = 0; i < Queue::MaxOutstandingWrites; ++i)
        assert(coalesced_budget.Enqueue(0, 100, 8));
    assert(!coalesced_budget.Enqueue(0, 101, 8));
    assert(coalesced_budget.AcceptedSequence() == Queue::MaxOutstandingWrites);
    assert(coalesced_budget.Drain([](unsigned c,std::uint64_t a,std::uint64_t n) {
        assert(c == 0 && a == 100 && n == 8);
    }) == 1);
    assert(coalesced_budget.Enqueue(0, 101, 8));
}
'''
with tempfile.TemporaryDirectory(prefix="encore-deferred-host-") as folder:
    cpp = Path(folder) / "test.cpp"
    exe = Path(folder) / "test"
    cpp.write_text(source)
    subprocess.run([
        "clang++", "-std=c++20", "-O1", "-g", "-pthread", "-Wall", "-Wextra",
        "-Werror", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-I", str(header.parent), str(cpp), "-o", str(exe)
    ], check=True, timeout=45)
    subprocess.run([str(exe)], check=True, timeout=45)
print("GPU_DEFERRED_QUEUE_HOST_PASS concurrency=4 no_lost_ranges=1280 crosspage_split=1 quiescence=1")
