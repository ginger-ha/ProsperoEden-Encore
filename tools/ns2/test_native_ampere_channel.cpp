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
    assert(process_registry.IsCurrent(*first_ticket));
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
    assert(!process_registry.IsCurrent(*first_ticket));
    assert(process_registry.Register(&first));
    assert(!channel_registry.IsNative(&native));
    assert(!channel_registry.Bind(&native,&first)); // stale generation cannot acquire
    channel_registry.Unbind(&native);
    assert(channel_registry.Bind(&native,&first));
    assert(channel_registry.IsNative(&native));
    const auto reopened=channel_registry.CaptureTicket(&native);
    assert(reopened && reopened->process==&first &&
           reopened->generation!=first_ticket->generation);
    assert(!process_registry.IsCurrent(*first_ticket));
    channel_registry.Unbind(&native);
    assert(!channel_registry.CaptureTicket(&native));
    channel_registry.Unbind(&another);
    process_registry.Unregister(&first);
    process_registry.Unregister(&other);
}
