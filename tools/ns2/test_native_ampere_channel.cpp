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
    assert(!channel_registry.IsNative(&legacy));
    assert(process_registry.Register(&other));
    assert(!channel_registry.Bind(&native,&other));
    assert(channel_registry.Bind(&another,&other));
    assert(channel_registry.IsNative(&another));
    process_registry.Unregister(&first);
    assert(!channel_registry.IsNative(&native));
    assert(process_registry.Register(&first));
    assert(!channel_registry.IsNative(&native));
    assert(!channel_registry.Bind(&native,&first)); // stale generation cannot acquire
    channel_registry.Unbind(&native);
    assert(channel_registry.Bind(&native,&first));
    assert(channel_registry.IsNative(&native));
    channel_registry.Unbind(&native);
    channel_registry.Unbind(&another);
    process_registry.Unregister(&first);
    process_registry.Unregister(&other);
}
