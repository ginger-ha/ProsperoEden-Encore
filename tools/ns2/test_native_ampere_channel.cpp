// SPDX-License-Identifier: GPL-3.0-or-later
#include <cassert>
#include "core/hle/service/nvdrv/devices/native_gpu_channel_registry.h"
namespace Kernel { class KProcess {}; }
namespace Tegra::Control { struct ChannelState {}; }
int main() {
    using Service::Nvidia::Devices::NativeGpuChannelRegistry;
    using Service::Nvidia::Devices::NativeGpuProcessRegistry;
    auto& process_registry=NativeGpuProcessRegistry::Instance();
    auto& channel_registry=NativeGpuChannelRegistry::Instance();
    Kernel::KProcess first{},other{};
    Tegra::Control::ChannelState native{},legacy{},another{};
    assert(!channel_registry.IsNative(&native));
    assert(!channel_registry.Bind(&native,&first));
    assert(process_registry.Register(&first));
    assert(channel_registry.Bind(&native,&first));
    assert(channel_registry.Bind(&native,&first));
    assert(channel_registry.IsNative(&native));
    const auto first_ticket=channel_registry.CaptureTicket(&native);
    assert(first_ticket && first_ticket->process==&first);
    assert(channel_registry.IsCurrent(&native,*first_ticket));
    assert(!channel_registry.CaptureTicket(&legacy));
    assert(!channel_registry.CaptureTicket(nullptr));
    assert(!channel_registry.IsNative(&legacy));
    assert(process_registry.Register(&other));
    assert(!channel_registry.Bind(&native,&other));
    assert(channel_registry.Bind(&another,&other));
    assert(channel_registry.IsNative(&another));
    const auto other_ticket=channel_registry.CaptureTicket(&another);
    assert(other_ticket && other_ticket->process==&other &&
           other_ticket->generation!=first_ticket->generation);
    process_registry.Unregister(&first);
    assert(!channel_registry.IsNative(&native));
    assert(!channel_registry.CaptureTicket(&native));
    assert(!channel_registry.IsCurrent(&native,*first_ticket));
    assert(process_registry.Register(&first));
    assert(!channel_registry.IsNative(&native));
    assert(!channel_registry.Bind(&native,&first)); // stale generation cannot acquire
    channel_registry.Unbind(&native);
    assert(channel_registry.Bind(&native,&first));
    assert(channel_registry.IsNative(&native));
    const auto reopened=channel_registry.CaptureTicket(&native);
    assert(reopened && reopened->process==&first &&
           reopened->generation!=first_ticket->generation &&
           reopened->channel_generation!=first_ticket->channel_generation);
    assert(channel_registry.IsCurrent(&native,*reopened));
    assert(!channel_registry.IsCurrent(&native,*first_ticket));
    channel_registry.Unbind(&native);
    assert(!channel_registry.CaptureTicket(&native));
    assert(!channel_registry.IsCurrent(&native,*reopened));
    // A channel may be reused by the SAME process generation. In-flight
    // pipelines from the prior bind must still be rejected.
    assert(channel_registry.Bind(&native,&first));
    const auto recycled=channel_registry.CaptureTicket(&native);
    assert(recycled && recycled->process==&first &&
           recycled->generation==reopened->generation &&
           recycled->channel_generation!=reopened->channel_generation);
    assert(!channel_registry.IsCurrent(&native,*reopened));
    assert(channel_registry.IsCurrent(&native,*recycled));
    channel_registry.Unbind(&native);
    channel_registry.Unbind(&another);
    process_registry.Unregister(&first);
    process_registry.Unregister(&other);
}
