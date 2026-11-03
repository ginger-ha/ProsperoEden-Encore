#!/usr/bin/env python3
"""Reject process-wide GPU ABI promotion in the real NS2 research NVDRV channel."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "vendor/encore-active/ns2-runtime/nvdrv_gpu/core/hle/service/nvdrv/devices"
source = (BASE / "nvhost_gpu.cpp").read_text()
header = (BASE / "nvhost_gpu.h").read_text()
native_puller = (ROOT / "vendor/encore-active/ns2-runtime/gpu_dispatch/video_core/engines/puller.cpp").read_text()
# BindObject must not change the active subchannel before native class
# authentication, or a rejected Ampere bind can hijack subsequent methods.
bind_source = native_puller.split("void Puller::ProcessBindMethod(", 1)[1].split(
    "void Puller::ProcessFenceActionMethod(", 1)[0]
ampere_3d_bind = bind_source.split(
    "if (engine_id == static_cast<EngineID>(0xc797)) {", 1)[1].split(
    "if (engine_id == static_cast<EngineID>(0xc7c0)) {", 1)[0]
ampere_compute_bind = bind_source.split(
    "if (engine_id == static_cast<EngineID>(0xc7c0)) {", 1)[1].split(
    "if (engine_id == static_cast<EngineID>(0xc7b5)) {", 1)[0]
ampere_dma_bind = bind_source.split(
    "if (engine_id == static_cast<EngineID>(0xc7b5)) {", 1)[1].split(
    "\n        return;\n    }\n", 1)[0]
binding_write = "bound_engines[method_call.subchannel] = engine_id;"

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
# Native H:0x1b kickoff pointer lists must be mapped in their exact FD
# process before any command reads or GPU queue submission.
kickoff = source.split("NvResult nvhost_gpu::SubmitGPFIFOBase1(", 1)[1].split(
    "NvResult nvhost_gpu::SubmitGPFIFOBase2(", 1)[0]
kickoff_preflight = "NativeGpfifoGuestHeadersReadable("
kickoff_read = "this->GetSessionMemory(fd).ReadBlock("
guard = (ROOT / "vendor/encore-active/ns2-runtime/hle/core/hle/service/nvdrv/devices/native_gpu_submission.h").read_text()
checks = [
    (kickoff_preflight in kickoff and kickoff_read in kickoff and
     kickoff.index(kickoff_preflight) < kickoff.index(kickoff_read) and
     "if (UsesNativeAbi(fd) &&" in kickoff and
     "session->process->GetMemory().IsValidVirtualAddressRange(" in kickoff and
     "return NvResult::InvalidSize;" in kickoff and
     "if (count == 0) return true;" in guard and
     "if (address == 0 || entry_size == 0 ||" in guard and
     "count > std::numeric_limits<std::size_t>::max() / entry_size" in guard and
     "address > std::numeric_limits<std::uint64_t>::max() - bytes" in guard,
     "native kickoff maps every guest header with overflow-safe bounded helper, leaving NS1 unchanged"),
    (all(s in source for s in required_cpp), "native source uses exact caller FD"),
    (all(s in header for s in required_header), "native header exposes caller FD"),
    (all(s in native_puller for s in required_puller),
     "actual research Puller owns authenticated native 3D/Turing macro dispatch"),
    (binding_write not in bind_source.split(
        "if (engine_id == static_cast<EngineID>(0xc797)) {", 1)[0],
     "native classes do not commit binding before authentication"),
    (ampere_3d_bind.count(binding_write) == 1 and
     ampere_3d_bind.index(binding_write) > ampere_3d_bind.index("if (native_3d_failed || native_macro_method)"),
     "native 3D bind commits only after channel authorization and valid MME state"),
    (ampere_compute_bind.count(binding_write) == 1 and
     ampere_compute_bind.index(binding_write) > ampere_compute_bind.index("IsNative(") and
     "EngineTypes::KeplerCompute" in ampere_compute_bind and
     "retire_native_3d();" in ampere_compute_bind,
     "native compute class binds only after channel authorization and revokes previous 3D owner"),
    (ampere_dma_bind.count(binding_write) == 1 and
     ampere_dma_bind.index(binding_write) > ampere_dma_bind.index("IsNative("),
     "native DMA bind commits only after channel authorization"),
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
