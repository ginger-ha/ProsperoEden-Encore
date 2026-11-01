#!/usr/bin/env python3
"""Reject process-wide GPU ABI promotion in the real NS2 research NVDRV channel."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "vendor/encore-active/ns2-runtime/nvdrv_gpu/core/hle/service/nvdrv/devices"
source = (BASE / "nvhost_gpu.cpp").read_text()
header = (BASE / "nvhost_gpu.h").read_text()
native_puller = (ROOT / "vendor/encore-active/ns2-runtime/gpu_dispatch/video_core/engines/puller.cpp").read_text()
required_puller = (
    "engine_id == static_cast<EngineID>(0xc797)",
    "CallNative3D(dma_pusher,method_call.method,",
    "CallNative3D(dma_pusher,method,",
    "native_3d->Execute(",
    "native_macro_method=method",
    "engine.draw_manager.DrawDeferred(engine)",
    "if (!native_3d) native_3d = std::make_unique<Tegra::NativeAmpereMacroState>()",
    "if (native_3d_failed || native_macro_method)",
)

required_cpp = (
    "bool nvhost_gpu::UsesNativeAbi(DeviceFD fd) const {",
    "const auto it = sessions.find(fd);",
    "if (it == sessions.end()) return false;",
    "const auto* session = core.GetSession(it->second);",
    "NativeGpuProcessRegistry::Instance().Contains(session->process);",
    "NativeGpuChannelRegistry::Instance().Bind(channel_state.get(), owner->process)",
    "if (!opened || opened->process != owner->process)",
    "NativeGpuChannelRegistry::Instance().Unbind(channel_state.get());",
    "NvResult nvhost_gpu::AllocateObjectContext(IoctlAllocObjCtx& params, DeviceFD fd)",
    "NvResult nvhost_gpu::SubmitGPFIFOImpl(IoctlSubmitGpfifo& params, Tegra::CommandList&& entries, DeviceFD fd)",
    "const bool native = UsesNativeAbi(fd);",
    "if (UsesNativeAbi(fd)) {",
    "return WrapFixed(this, &nvhost_gpu::AllocateObjectContext, input, output, fd);",
    "return SubmitGPFIFOImpl(params, std::move(entries), fd);",
    "return sessions.size() == 1 && UsesNativeAbi(sessions.begin()->first)",
)
required_header = (
    "NvResult AllocateObjectContext(IoctlAllocObjCtx& params, DeviceFD fd);",
    "NvResult SubmitGPFIFOImpl(IoctlSubmitGpfifo& params, Tegra::CommandList&& entries, DeviceFD fd);",
    "bool UsesNativeAbi(DeviceFD fd) const;",
)
checks = [
    (all(s in source for s in required_cpp), "native source uses exact caller FD"),
    (all(s in header for s in required_header), "native header exposes caller FD"),
    (all(s in native_puller for s in required_puller),
     "actual research Puller owns authenticated native 3D/Turing macro dispatch"),
    ("UsesNativeAbi()" not in source + header, "no unscoped native ABI call"),
    (source.count("return SubmitGPFIFOImpl(params, std::move(entries), fd);") == 2,
     "both GPFIFO submit paths propagate FD"),
    ("output, fd);" in source, "inline submit passes FD"),
    ("for (const auto& [other_fd, session_id] : sessions)" in source,
     "native channel rejects mixed-process FDs before GPU queue work"),
]
errors = [message for passed, message in checks if not passed]
if errors:
    print("NS2 NVDRV per-FD ABI isolation: FAILED: " + "; ".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("NS2 NVDRV per-FD ABI isolation source gate: PASS")
print("No NS2 GPU hardware or PS5 gameplay inference.")
