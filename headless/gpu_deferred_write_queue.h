// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
// Source-only, session-owned FIFO for deferred guest cache writes.
// Completion watermarks are a host contract, NOT a GPU fence or runtime enable.
#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <exception>
#include <limits>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <type_traits>
#include <utility>
#include <vector>

namespace Eden::GpuDeferredWrite {
struct Range {
    std::uint64_t begin{}, end{}; // half-open
};
struct Write {
    unsigned core{};
    Range range{};
    // A merged FIFO entry acknowledges all consecutive enqueues through this id.
    std::uint64_t last_sequence{};
    bool published{true}; // False until producer finishes the guest RAM store.
    bool cancelled{false}; // Failed conditional store: advances FIFO without cache invalidation.
};

class Queue {
public:
    using Sequence = std::uint64_t;
    struct Ticket {
        Sequence sequence{};
        std::uint64_t generation{};
    };
    static constexpr unsigned Cores = 4;
    static constexpr std::uint64_t PageBytes = 4096;
    static constexpr std::uint64_t DirtyRegionBytes = PageBytes / 2;
    // Upper bound on accepted-but-not-acknowledged guest stores, including
    // entries in an active GPU replay snapshot. Saturation must be handled by
    // the producer with a synchronous/cache-safe fallback BEFORE its store.
    // Never silently drop a write while pretending the ticket was accepted.
    static constexpr Sequence MaxOutstandingWrites = 8192;

    // Legacy host-only immediate publication. The inactive native bridge
    // still calls this BEFORE its backing RAM store; that path is unsafe to
    // activate until it is replaced by Reserve + post-store Publish.
    std::optional<Ticket> EnqueueTracked(unsigned core, std::uint64_t address,
                                         std::uint64_t size) {
        return EnqueueImpl(core, address, size, true);
    }

    // Reserve an order position before touching guest RAM. The GPU consumer
    // cannot replay this entry until the producer has finished the actual
    // write and explicitly called Publish(ticket).
    std::optional<Ticket> Reserve(unsigned core, std::uint64_t address,
                                  std::uint64_t size) {
        return EnqueueImpl(core, address, size, false);
    }

    // Backpressure for a prospective post-store producer. A rejected Reserve
    // MUST NOT fall back to a synchronous write ahead of older FIFO entries.
    // Request GPU-owner replay outside queue locks, wait through the exact
    // older watermark, then try reserving again. Never call from the GPU
    // consumer or while holding a GPU-cache mutex. Producers must be joined
    // before title destruction; the native integration remains disabled.
    template<class RequestGpu>
    std::optional<Ticket> ReserveOrdered(unsigned core, std::uint64_t address,
                                         std::uint64_t size, RequestGpu&& request_gpu) {
        if (core >= Cores || size == 0 ||
            size > std::numeric_limits<std::uint64_t>::max() - address)
            return std::nullopt;
        for (;;) {
            if (auto ticket = Reserve(core, address, size)) return ticket;
            Ticket barrier;
            {
                std::lock_guard lock(mutex_);
                if (closed_ || failed_ ||
                    accepted_ == std::numeric_limits<Sequence>::max())
                    return std::nullopt;
                // The queue drained after Reserve failed; retry, not fallback.
                if (accepted_ - completed_ < MaxOutstandingWrites) continue;
                barrier = {accepted_, generation_};
                // Join scheduling callbacks at Close, just as PublishAndWake.
                ++pending_wake_callbacks_;
            }
            if (active_consumer_ == this || active_wake_callback_ == this)
                std::terminate();
            struct RestoreWake {
                const Queue*& slot;
                const Queue* previous;
                ~RestoreWake() { slot = previous; }
            } restore{active_wake_callback_, active_wake_callback_};
            active_wake_callback_ = this;
            try {
                RequestGpuOrThrow(request_gpu);
            } catch (...) {
                {
                    std::lock_guard lock(mutex_);
                    failed_ = true;
                    --pending_wake_callbacks_;
                }
                wake_cv_.notify_all();
                completed_cv_.notify_all();
                throw;
            }
            {
                std::lock_guard lock(mutex_);
                --pending_wake_callbacks_;
            }
            wake_cv_.notify_all();
            // The callback may be asynchronous. WaitUntil also wakes on
            // title close/failure; no younger guest write may overtake barrier.
            if (!WaitUntil(barrier)) return std::nullopt;
        }
    }

    // Host-only legacy publication without GPU wakeup. This is NOT sufficient
    // for a native CPU reader to await the replayed write.
    bool Publish(Ticket ticket) {
        return PublishImpl(ticket).has_value();
    }

    // Resolve a failed conditional write. No-op only at the memory level:
    // the FIFO ticket stays ordered with all earlier cache invalidations.
    // Native callers must use CancelAndWake to preserve worker liveness.
    bool Cancel(Ticket ticket) {
        return PublishImpl(ticket, false, true).has_value();
    }

    // A native-ready producer needs TWO actions after its actual guest store:
    // publish the payload, then request a GPU-owner wake when the oldest FIFO
    // reservation first becomes replayable. Run the caller's scheduling
    // callback OUTSIDE mutex_ to avoid a scheduler/cache-lock inversion.
    //
    // This is a host-only scheduling contract. The disabled native bridge
    // does not invoke it or guarantee GPU-thread lifetime/fence ordering.
    template<class RequestGpu>
    bool PublishAndWake(Ticket ticket, RequestGpu&& request_gpu) {
        return ResolveAndWake(ticket, false, std::forward<RequestGpu>(request_gpu));
    }

    // A failed conditional write did not change backing RAM. Resolve its
    // reserved FIFO position without replaying an unnecessary invalidation.
    // Still request a GPU wake when it unblocks the next published writer.
    template<class RequestGpu>
    bool CancelAndWake(Ticket ticket, RequestGpu&& request_gpu) {
        return ResolveAndWake(ticket, true, std::forward<RequestGpu>(request_gpu));
    }

    // Existing opt-in native bridge uses this signature. There is deliberately
    // no automatic fallback for a rejected write: caller must not reorder work.
    bool Enqueue(unsigned core, std::uint64_t address, std::uint64_t size) {
        return EnqueueTracked(core, address, size).has_value();
    }

    Sequence AcceptedSequence() const {
        std::lock_guard lock(mutex_);
        return accepted_;
    }
    Sequence CompletedSequence() const {
        std::lock_guard lock(mutex_);
        return completed_;
    }

    // True includes entries being replayed but not yet acknowledged.
    bool Pending() const {
        std::lock_guard lock(mutex_);
        return completed_ != accepted_;
    }

    // A callback exception permanently poisons this title's queue. Replaying
    // it again is unsafe because the callback may have made partial cache
    // changes before throwing. Only quiescent teardown can clear the poison.
    bool Failed() const {
        std::lock_guard lock(mutex_);
        return failed_;
    }

    // A failed GPU->CPU download compromises guest memory coherence. Unlike
    // a failed CAS comparison, do not acknowledge or replay its reservation:
    // poison the whole session and release blocked producer/reader threads.
    void FailClosed() {
        {
            std::lock_guard lock(mutex_);
            failed_ = true;
        }
        completed_cv_.notify_all();
        wake_cv_.notify_all();
    }

    // Generation-tagged wait for either queued or reserved writes.
    // Caller MUST schedule a GPU-owner drain, without holding any GPU cache
    // lock, before waiting. The result is replay-callback completion only,
    // NOT GPU/device-fence completion or safe native CPU-read synchronization.
    // A stale ticket cannot become valid again after an idle session reset.
    bool WaitUntil(Ticket ticket) {
        std::unique_lock lock(mutex_);
        if (ticket.generation != generation_ || ticket.sequence == 0 ||
            ticket.sequence > accepted_) return false;
        completed_cv_.wait(lock, [&] {
            return completed_ >= ticket.sequence || closed_ || failed_ ||
                   generation_ != ticket.generation;
        });
        // A callback may complete while Close() is joining the GPU owner.
        // Never report a successful CPU read for a closed/poisoned title,
        // even if the sequence watermark was acknowledged before shutdown.
        return !closed_ && !failed_ && generation_ == ticket.generation &&
               completed_ >= ticket.sequence;
    }

    // A conditional RAM read must wait ONLY for the FIFO work preceding its
    // own still-unpublished ticket. Sequence zero represents no predecessors.
    // It is valid only for a live reservation in the correct session and must
    // not bypass poison or title shutdown. GPU-owner scheduling is external.
    bool WaitForPredecessors(Ticket predecessor) {
        {
            std::lock_guard lock(mutex_);
            if (closed_ || failed_ || predecessor.generation != generation_ ||
                accepted_ == 0 || predecessor.sequence >= accepted_)
                return false;
            if (predecessor.sequence == 0) return true;
        }
        return WaitUntil(predecessor);
    }

    // Deliberately NO WaitUntil(Sequence) overload. Sequence numbers reset
    // after quiescence; only generation-tagged tickets can be waited upon.
    // A stale read ticket must never succeed against another title session.

    // GPU owner only. Capture ONE finite FIFO batch while holding the queue
    // mutex, then replay it without that mutex. New enqueues remain pending
    // until a later GPU boundary, even if they arrive during replay.
    //
    // The requested generation-tagged ticket is a MINIMUM completion target,
    // not an upper cutoff: entries accepted before the snapshot may be
    // included. A stale session's ticket cannot drain another session.
    // Only published guest payloads are eligible for replay.
    template<class Replay>
    std::uint64_t DrainThrough(Ticket target, Replay&& replay) {
        // Only one GPU owner can replay a session at a time. A second owner
        // waits for the first before it rechecks its requested watermark.
        // Recursive replay on the same thread is a caller contract violation:
        // fail fast rather than deadlock or silently skip an invalidation.
        if (active_consumer_ == this) std::terminate();
        std::unique_lock owner(consumer_mutex_);
        struct RestoreOwner {
            const Queue*& slot;
            const Queue* prior;
            ~RestoreOwner() { slot = prior; }
        } restore{active_consumer_, active_consumer_};
        active_consumer_ = this;
        std::vector<Write> work;
        {
            std::lock_guard lock(mutex_);
            if (closed_ || failed_ || target.generation != generation_ || target.sequence == 0 ||
                target.sequence > accepted_ || completed_ >= target.sequence) return 0;
            // Reserve + Publish is ordered, but publishers can finish out of
            // order. Drain only the contiguous PUBLISHED prefix. Never
            // overtake an earlier uncommitted guest RAM write.
            std::size_t ready = 0;
            while (ready != queue_.size() && queue_[ready].published) ++ready;
            if (ready == 0) return 0;
            if (ready == queue_.size()) {
                work.swap(queue_);
            } else {
                work.assign(queue_.begin(), queue_.begin() + ready);
                queue_.erase(queue_.begin(), queue_.begin() + ready);
            }
        }
        // Under the consumer mutex no other replay can be in flight.
        // The snapshot includes ONLY the published FIFO prefix.
        std::uint64_t replayed = 0;
        try {
            for (const auto& item : work) {
                if (item.cancelled) continue;
                replay(item.core, item.range.begin, item.range.end - item.range.begin);
                ++replayed;
            }
        } catch (...) {
            // The callback may have partially modified GPU caches. Never
            // acknowledge this batch, retry it, or permit later work to
            // overtake it. Report failure to readers and propagate the error.
            {
                std::lock_guard lock(mutex_);
                failed_ = true;
            }
            completed_cv_.notify_all();
            throw;
        }
        {
            std::lock_guard lock(mutex_);
            completed_ = work.back().last_sequence;
            // A complete drain traditionally swapped the entire FIFO into
            // `work`, leaving queue_ with zero capacity. Repeated short
            // bursts then reallocated the FIFO on almost every GPU boundary.
            // Recycle the emptied snapshot's backing storage only when no
            // producer enqueued a new tail while replay ran. Never disturb
            // a newer unpublished reservation or its sequence ordering.
            if (queue_.empty()) {
                work.clear();
                queue_.swap(work);
            }
        }
        completed_cv_.notify_all();
        return replayed;
    }

    template<class Replay>
    std::uint64_t Drain(Replay&& replay) {
        Ticket target{};
        {
            std::lock_guard lock(mutex_);
            target = {accepted_, generation_};
        }
        return DrainThrough(target, std::forward<Replay>(replay));
    }

    // Shutdown barrier: reject future work, release CPU waiters, then wait
    // until any in-flight GPU replay callback has returned. No GPU cache lock
    // may be held while calling Close(). Never call it recursively from replay.
    // Producers and waiters still must be joined before destroying the Queue.
    void Close() {
        if (active_consumer_ == this || active_wake_callback_ == this)
            std::terminate();
        {
            std::lock_guard lock(mutex_);
            closed_ = true;
            close_completed_ = false;
        }
        completed_cv_.notify_all();
        // A publish may have released mutex_ and be about to invoke the GPU
        // scheduling callback. Join all such callbacks before returning:
        // otherwise the caller could free the scheduler underneath them.
        {
            std::unique_lock lock(mutex_);
            wake_cv_.wait(lock, [&] { return pending_wake_callbacks_ == 0; });
        }
        // DrainThrough holds consumer_mutex_ for the complete replay batch.
        // Lock order is consumer_mutex_ -> mutex_ on a drain; never hold
        // mutex_ while waiting for this lock.
        std::lock_guard owner(consumer_mutex_);
        {
            std::lock_guard lock(mutex_);
            close_completed_ = true;
        }
    }

    // Reset only AFTER Close(), joining producers/readers and releasing all
    // GPU cache locks. Serialize with the consumer as an extra safety barrier.
    // Reject open-session resets instead of silently recycling live tickets.
    // A caller must still enforce full thread quiescence before destruction.
    bool ResetAfterQuiescence() {
        if (active_consumer_ == this) return false;
        std::lock_guard owner(consumer_mutex_);
        std::lock_guard lock(mutex_);
        if (!closed_ || !close_completed_ || pending_wake_callbacks_ != 0)
            return false;
        queue_.clear();
        accepted_ = completed_ = 0;
        generation_ = FreshGeneration(); // Unique across ALL queue instances.
        failed_ = false;
        closed_ = false;
        close_completed_ = false;
        return true;
    }

private:
    // The scheduler may expose either a void callback (throw on failure) or
    // an explicit bool acceptance result. Treat false as failure: otherwise
    // a published FIFO head can strand readers or a saturated producer.
    template<class RequestGpu>
    static void RequestGpuOrThrow(RequestGpu&& request_gpu) {
        if constexpr (std::is_same_v<std::invoke_result_t<RequestGpu>, bool>) {
            if (!std::forward<RequestGpu>(request_gpu)())
                throw std::runtime_error("deferred GPU wake rejected");
        } else {
            std::forward<RequestGpu>(request_gpu)();
        }
    }

    template<class RequestGpu>
    bool ResolveAndWake(Ticket ticket, bool cancel, RequestGpu&& request_gpu) {
        const auto became_ready = PublishImpl(ticket, true, cancel);
        if (!became_ready) return false;
        if (*became_ready) {
            // A synchronous scheduling callback must never recursively close
            // this very queue: Close() waits for the callback's own counter.
            // Keep the owner marker scoped, including exception unwinding.
            struct RestoreWake {
                const Queue*& slot;
                const Queue* prior;
                ~RestoreWake() { slot = prior; }
            } restore{active_wake_callback_, active_wake_callback_};
            active_wake_callback_ = this;
            try {
                RequestGpuOrThrow(std::forward<RequestGpu>(request_gpu));
            } catch (...) {
                // A publication without a successful GPU wake cannot safely
                // satisfy its reader. Fail closed, never assume another GPU
                // command will eventually rescue this title.
                {
                    std::lock_guard lock(mutex_);
                    failed_ = true;
                    --pending_wake_callbacks_;
                }
                wake_cv_.notify_all();
                completed_cv_.notify_all();
                throw;
            }
            {
                std::lock_guard lock(mutex_);
                --pending_wake_callbacks_;
            }
            wake_cv_.notify_all();
        }
        return true;
    }

    // Returning true means a blocked/unready FIFO head became published.
    // A later ready tail does NOT schedule an unnecessary second GPU tick.
    // The wake callback itself runs after this queue lock is released.
    std::optional<bool> PublishImpl(Ticket ticket, bool arm_wake = false, bool cancel = false) {
        std::lock_guard lock(mutex_);
        if (closed_ || failed_ || ticket.generation != generation_ || ticket.sequence == 0 ||
            ticket.sequence > accepted_) return std::nullopt;
        // Strictly monotone upper sequence IDs survive tail merges and
        // published-prefix drains: binary search remains exact.
        const auto entry = std::lower_bound(
            queue_.begin(), queue_.end(), ticket.sequence,
            [](const Write& write, Sequence sequence) {
                return write.last_sequence < sequence;
            });
        if (entry == queue_.end() || entry->last_sequence != ticket.sequence ||
            entry->published) return std::nullopt;
        const bool was_ready = !queue_.empty() && queue_.front().published;
        entry->published = true;
        entry->cancelled = cancel;
        const bool became_ready = !was_ready && !queue_.empty() &&
                                  queue_.front().published;
        // Account for the notifier WHILE holding mutex_, before Close() can
        // set closed_. Close() waits for this callback before returning.
        if (arm_wake && became_ready) ++pending_wake_callbacks_;
        return became_ready;
    }

    // Tickets must identify the owning queue as well as the title session.
    // An epoch starting at 1 for every Queue would permit cross-address-space
    // confusion whenever two independent queues reached the same sequence.
    static std::uint64_t FreshGeneration() {
        auto prior = next_generation_.load(std::memory_order_relaxed);
        do {
            if (prior == std::numeric_limits<std::uint64_t>::max())
                std::terminate(); // Never issue a duplicate epoch on wrap.
        } while (!next_generation_.compare_exchange_weak(
            prior, prior + 1, std::memory_order_relaxed));
        return prior + 1;
    }
    static inline std::atomic<std::uint64_t> next_generation_{0};

    std::optional<Ticket> EnqueueImpl(unsigned core, std::uint64_t address,
                                      std::uint64_t size, bool published) {
        if (core >= Cores || size == 0 ||
            size > std::numeric_limits<std::uint64_t>::max() - address)
            return std::nullopt;
        const auto end = address + size;
        std::lock_guard lock(mutex_);
        if (closed_ || failed_ || accepted_ == std::numeric_limits<Sequence>::max() ||
            accepted_ - completed_ >= MaxOutstandingWrites)
            return std::nullopt;
        const Sequence sequence = accepted_ + 1;
        if (published && !queue_.empty()) {
            auto& tail = queue_.back();
            const auto& last = tail.range;
            // A cancelled conditional write is a no-op. Never fuse a later
            // real memory write into it or the replay would skip that write.
            if (tail.published && !tail.cancelled && tail.core == core &&
                (address / DirtyRegionBytes) == ((end - 1) / DirtyRegionBytes) &&
                (last.begin / DirtyRegionBytes) == ((last.end - 1) / DirtyRegionBytes) &&
                (address / DirtyRegionBytes) == (last.begin / DirtyRegionBytes) &&
                address <= last.end && last.begin <= end) {
                tail.range.begin = std::min(last.begin, address);
                tail.range.end = std::max(last.end, end);
                tail.last_sequence = sequence;
                accepted_ = sequence;
                return Ticket{sequence, generation_};
            }
        }
        queue_.push_back({core, {address, end}, sequence, published});
        accepted_ = sequence;
        return Ticket{sequence, generation_};
    }

    std::mutex consumer_mutex_; // Never held by producer or CPU waiter.
    static inline thread_local const Queue* active_consumer_{nullptr};
    static inline thread_local const Queue* active_wake_callback_{nullptr};
    mutable std::mutex mutex_;
    std::condition_variable completed_cv_;
    std::condition_variable wake_cv_;
    std::size_t pending_wake_callbacks_{};
    std::vector<Write> queue_;
    Sequence accepted_{};
    Sequence completed_{};
    std::uint64_t generation_{FreshGeneration()};
    bool closed_{};
    bool failed_{};
    bool close_completed_{};
};
} // namespace Eden::GpuDeferredWrite
