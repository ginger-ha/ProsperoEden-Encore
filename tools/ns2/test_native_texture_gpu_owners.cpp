// SPDX-License-Identifier: GPL-3.0-or-later
// P2.2b host-only proof for a future native Vulkan image descriptor owner.
// Exercises the ACTUAL QMD3 GPU-timeline retirement template with multiple
// shared resources; it does NOT activate VkImage/VkSampler publication.
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <functional>
#include <memory>
#include <stdexcept>
#include <utility>
#include <vector>
#include "shader_recompiler/frontend/ampere/native_qmd_compute_environment.h"

struct MockScheduler {
    u64 tick{};
    u64 completed{};
    u64 waited{};
    unsigned finishes{};
    bool fail_flush_after_submit{};
    bool fail_wait_once{};

    u64 Flush() {
        ++tick;
        if (fail_flush_after_submit) {
            throw std::runtime_error{"flush failed after enqueue"};
        }
        return tick;
    }
    void Wait(u64 target) {
        if (fail_wait_once) {
            fail_wait_once = false;
            throw std::runtime_error{"GPU timeline Wait transient failure"};
        }
        assert(target != 0 && target <= tick && target <= completed);
        waited = std::max(waited, target);
    }
    void Finish() {
        ++finishes;
        completed = tick;
        Wait(tick);
    }
};

struct MockFences {
    std::vector<std::function<void()>> pending{};
    bool reject_registration{};
    bool reject_signal{};
    unsigned signals{};

    void SyncOperation(std::function<void()>&& callback) {
        if (reject_registration) {
            throw std::runtime_error{"cannot register GPU retirement"};
        }
        pending.push_back(std::move(callback));
    }
    void SignalReference() {
        if (reject_signal) {
            throw std::runtime_error{"guest fence signal failed"};
        }
        ++signals;
    }
};

struct Resource {
    unsigned& destroyed;
    const u64& waited;
    u64 final_tick;

    Resource(unsigned& count, const u64& completed_wait, u64 required)
        : destroyed(count), waited(completed_wait), final_tick(required) {}
    ~Resource() {
        // Releasing even one VkImage, VkImageView, or VkSampler before the
        // last in-flight submission completes would be a use-after-free.
        assert(waited >= final_tick);
        ++destroyed;
    }
};

struct GpuOwnerBundle {
    std::shared_ptr<Resource> pipeline;
    std::shared_ptr<Resource> image_view;
    std::shared_ptr<Resource> sampler;
};

struct Witness {
    MockScheduler scheduler{};
    MockFences fences{};
    unsigned destroyed{};
    u64 required_tick{1};

    std::shared_ptr<GpuOwnerBundle> NewOwners() {
        auto owners = std::make_shared<GpuOwnerBundle>();
        const auto resource = [&] {
            return std::make_shared<Resource>(
                destroyed, scheduler.waited, required_tick);
        };
        owners->pipeline = resource();
        owners->image_view = resource();
        owners->sampler = resource();
        return owners;
    }
};

int main() {
    using Shader::Ampere::RetainNativeComputeUntilGpuTick;
    {
        Witness test;
        auto owners = test.NewOwners();
        std::weak_ptr<Resource> image = owners->image_view;
        std::weak_ptr<Resource> sampler = owners->sampler;
        RetainNativeComputeUntilGpuTick(test.scheduler, test.fences, owners);
        owners.reset(); // Guest channel/cache can drop its ownership now.
        assert(test.fences.signals == 1 && test.scheduler.waited == 0);
        assert(!image.expired() && !sampler.expired());
        test.scheduler.completed = 1;
        auto retire = std::move(test.fences.pending.front());
        test.fences.pending.clear();
        retire();
        assert(test.scheduler.waited == 1 && !image.expired());
        retire = {}; // Last actual GPU owner releases after the wait.
        assert(image.expired() && sampler.expired() &&
               test.destroyed == 3);
    }
    {
        // The same image/sampler can outlive either of two submissions,
        // even when the callbacks are processed in reverse order.
        Witness test;
        test.required_tick = 2;
        MockFences second;
        auto owners = test.NewOwners();
        std::weak_ptr<Resource> image = owners->image_view;
        RetainNativeComputeUntilGpuTick(test.scheduler, test.fences, owners);
        RetainNativeComputeUntilGpuTick(test.scheduler, second, owners);
        owners.reset();
        test.scheduler.completed = 2;
        auto retire_second = std::move(second.pending.front());
        second.pending.clear();
        retire_second();
        retire_second = {};
        assert(!image.expired() && test.destroyed == 0);
        auto retire_first = std::move(test.fences.pending.front());
        test.fences.pending.clear();
        retire_first();
        retire_first = {};
        assert(image.expired() && test.destroyed == 3 &&
               test.scheduler.waited == 2);
    }
    {
        Witness test;
        test.fences.reject_registration = true;
        test.scheduler.completed = 1;
        auto owners = test.NewOwners();
        std::weak_ptr<Resource> image = owners->image_view;
        bool refused{};
        try {
            RetainNativeComputeUntilGpuTick(test.scheduler, test.fences,
                                            std::move(owners));
        } catch (const std::runtime_error&) {
            refused = true;
        }
        assert(refused && test.scheduler.waited == 1 &&
               image.expired() && test.destroyed == 3);
    }
    {
        Witness test;
        test.fences.reject_signal = true;
        test.scheduler.completed = 1;
        auto owners = test.NewOwners();
        std::weak_ptr<Resource> sampler = owners->sampler;
        bool refused{};
        try {
            RetainNativeComputeUntilGpuTick(test.scheduler, test.fences,
                                            std::move(owners));
        } catch (const std::runtime_error&) {
            refused = true;
        }
        assert(refused && test.scheduler.waited == 1 &&
               !sampler.expired() && test.destroyed == 0);
        test.fences.pending.clear();
        assert(sampler.expired() && test.destroyed == 3);
    }
    {
        Witness test;
        test.scheduler.fail_flush_after_submit = true;
        auto owners = test.NewOwners();
        std::weak_ptr<Resource> image = owners->image_view;
        bool refused{};
        try {
            RetainNativeComputeUntilGpuTick(test.scheduler, test.fences,
                                            std::move(owners));
        } catch (const std::runtime_error&) {
            refused = true;
        }
        assert(refused && test.scheduler.finishes == 1 &&
               test.scheduler.waited == 1 && image.expired() &&
               test.destroyed == 3);
    }
    {
        // Deferred retirement differs from registration failure: the
        // callback already belongs to the fence manager and Wait itself can
        // fail. The image/sampler/pipeline must survive until Finish drains.
        Witness test;
        test.scheduler.fail_wait_once = true;
        auto owners = test.NewOwners();
        std::weak_ptr<Resource> view = owners->image_view;
        RetainNativeComputeUntilGpuTick(test.scheduler, test.fences, owners);
        owners.reset();
        assert(!view.expired() && test.destroyed == 0 &&
               test.scheduler.finishes == 0);
        auto retire = std::move(test.fences.pending.front());
        test.fences.pending.clear();
        retire();
        assert(!view.expired() && test.scheduler.finishes == 1 &&
               test.scheduler.waited == 1);
        retire = {};
        assert(view.expired() && test.destroyed == 3);
    }
    std::puts("NS2_NATIVE_TEXTURE_GPU_OWNERS_PASS normal=1 reversed=1 "
              "registration_failure=1 signal_failure=1 flush_failure=1 "
              "deferred_timeline_failure=1");
}
