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
    // A native channel is not automatically a native 3D renderer:
    // the actual 0xC797 puller bind must opt in explicitly.
    int graphics_engine{};
    int separate_engine{};
    assert(!channel_registry.CaptureGraphicsTicket(&graphics_engine));
    assert(!channel_registry.BindGraphicsEngine(&legacy,&graphics_engine,0));
    assert(!channel_registry.BindGraphicsEngine(&native,nullptr,0));
    assert(!channel_registry.BindGraphicsEngine(&native,&graphics_engine,8));
    assert(channel_registry.BindGraphicsEngine(&native,&graphics_engine,2));
    assert(channel_registry.BindGraphicsEngine(&native,&graphics_engine,5));
    assert(!channel_registry.BindGraphicsEngine(&legacy,&graphics_engine,1));
    assert(!channel_registry.BindGraphicsEngine(&another,&graphics_engine,1));
    assert(!channel_registry.CaptureGraphicsTicket(&separate_engine));
    const auto active_engine = channel_registry.CaptureGraphicsTicket(&graphics_engine);
    assert(active_engine && active_engine->channel_generation == first_ticket->channel_generation);
    assert(channel_registry.IsGraphicsCurrent(&graphics_engine,*active_engine));
    channel_registry.UnbindGraphicsSubchannel(&native,&graphics_engine,2);
    assert(channel_registry.CaptureGraphicsTicket(&graphics_engine));
    channel_registry.UnbindGraphicsSubchannel(&native,&graphics_engine,5);
    assert(!channel_registry.CaptureGraphicsTicket(&graphics_engine));
    assert(!channel_registry.IsGraphicsCurrent(&graphics_engine,*active_engine));
    assert(channel_registry.BindGraphicsEngine(&native,&graphics_engine,2));
    // Class 0xC7C0 is independently authenticated; a native process alone
    // or graphics class 0xC797 must not impersonate the Compute engine.
    int compute_engine{};
    int alternate_compute_engine{};
    assert(!channel_registry.CaptureComputeTicket(&compute_engine));
    assert(!channel_registry.BindComputeEngine(&legacy,&compute_engine,0));
    assert(!channel_registry.BindComputeEngine(&native,nullptr,0));
    assert(!channel_registry.BindComputeEngine(&native,&compute_engine,8));
    assert(channel_registry.BindComputeEngine(&native,&compute_engine,1));
    assert(channel_registry.BindComputeEngine(&native,&compute_engine,4));
    assert(!channel_registry.BindComputeEngine(&another,&compute_engine,1));
    assert(!channel_registry.CaptureComputeTicket(&alternate_compute_engine));
    const auto native_compute=channel_registry.CaptureComputeTicket(&compute_engine);
    assert(native_compute &&
           native_compute->channel_generation==first_ticket->channel_generation);
    assert(channel_registry.IsComputeCurrent(&compute_engine,*native_compute));
    channel_registry.UnbindComputeSubchannel(&native,&compute_engine,1);
    assert(channel_registry.CaptureComputeTicket(&compute_engine));
    channel_registry.UnbindComputeSubchannel(&native,&compute_engine,4);
    assert(!channel_registry.CaptureComputeTicket(&compute_engine));
    assert(!channel_registry.IsComputeCurrent(&compute_engine,*native_compute));
    assert(channel_registry.BindComputeEngine(&native,&compute_engine,1));
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
    assert(!channel_registry.IsComputeCurrent(&compute_engine,*native_compute));
    assert(!channel_registry.CaptureComputeTicket(&compute_engine));
    assert(!channel_registry.IsGraphicsCurrent(&graphics_engine,*active_engine));
    assert(!channel_registry.CaptureGraphicsTicket(&graphics_engine));
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
    assert(!channel_registry.CaptureGraphicsTicket(&graphics_engine));
    assert(!channel_registry.CaptureComputeTicket(&compute_engine));
    assert(channel_registry.BindComputeEngine(&native,&compute_engine,3));
    const auto reopened_compute=channel_registry.CaptureComputeTicket(&compute_engine);
    assert(reopened_compute &&
           reopened_compute->channel_generation==reopened->channel_generation &&
           !channel_registry.IsComputeCurrent(&compute_engine,*native_compute));
    assert(channel_registry.BindGraphicsEngine(&native,&graphics_engine,3));
    assert(channel_registry.CaptureGraphicsTicket(&graphics_engine));
    assert(!channel_registry.IsGraphicsCurrent(&graphics_engine,*active_engine));
    assert(!channel_registry.IsCurrent(&native,*first_ticket));
    channel_registry.Unbind(&native);
    assert(!channel_registry.CaptureTicket(&native));
    assert(!channel_registry.IsCurrent(&native,*reopened));
    assert(!channel_registry.CaptureGraphicsTicket(&graphics_engine));
    assert(!channel_registry.CaptureComputeTicket(&compute_engine));
    assert(!channel_registry.IsComputeCurrent(&compute_engine,*reopened_compute));
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
