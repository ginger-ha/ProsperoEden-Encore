#!/usr/bin/env python3
"""P2.7: source-owner audit of live guest GPFIFO fetch against NX2 snapshots.

Eglantine fae3bc6 changes selection of *submitted GPU command words* after
GPU writes. Encore's maintained DmaPusher has a different interface: ioctl
copies guest command HEADERS only; the pusher reads the actual command words
at execution time. This oracle rejects accidental reintroduction of unsafe
snapshot reuse. It is NOT proof that GPU writes are fully synchronized.
"""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
vendor = root / "vendor"
cmake = (root / "headless/CMakeLists.txt").read_text()
assert '"${EDEN_MAINTAINED_GUEST_GPU_ROOT}/dma_pusher.cpp"' in cmake
assert '"${EDEN_MAINTAINED_GUEST_GPU_ROOT}/dma_pusher_dev.cpp"' in cmake
assert '"${EDEN_MAINTAINED_GPU_DMA}"' in cmake
owner = vendor / "encore-active/eden-core/src/video_core"
for file in ("dma_pusher.cpp", "dma_pusher_dev.cpp"):
    source = (owner / file).read_text()
    step = source.split("bool DmaPusher::Step() {", 1)[1].split(
        "void DmaPusher::ProcessCommands(", 1
    )[0]
    assert "CommandList& command_list = dma_pushbuffer.front();" in step
    assert "ProcessCommands(command_list.prefetch_command_list);" in step
    assert "command_list.command_lists[dma_pushbuffer_subindex]" in step
    # Eglantine's submission-time user-GPU-word cache is NOT in this
    # maintained owner; do not port its snapshot-selection patch blindly.
    assert "submitted_words" not in step and "submitted_offsets" not in step
    assert "GpuGuestMemory<Tegra::CommandHeader," in step
    assert "GuestMemoryFlags::SafeRead" in step
    assert "GuestMemoryFlags::UnsafeRead" in step
    assert step.index("dma_state.dma_get = header.addr;") < step.index(
        "GpuGuestMemory<Tegra::CommandHeader,"
    ) < step.index("ProcessCommands(headers);")
nvdrv = (vendor / (
    "encore-active/ns2-runtime/nvdrv_gpu/core/hle/service/nvdrv/"
    "devices/nvhost_gpu.cpp"
)).read_text()
assert nvdrv.count("Tegra::CommandList entries(params.num_entries);") == 2
assert nvdrv.count("entries.command_lists.data()") >= 3
assert "gpu.PushGPUEntries(bind_id, std::move(entries));" in nvdrv
for helper in (
    "BuildWaitCommandList(params.fence)",
    "BuildIncrementCommandList(params.fence)",
    "BuildIncrementWithWfiCommandList(params.fence)",
):
    assert helper in nvdrv
assert "submitted_words" not in nvdrv
assert "submitted_offsets" not in nvdrv
print("P2_7_NATIVE_GPU_COMMAND_FETCH_OWNER_PASS real_dma=2"
      " guest_words=live_fetch synthetic_prefetch=fences_only"
      " upstream_submitted_snapshot=inapplicable"
      " gpu_write_sync=NOT_PROVEN")
