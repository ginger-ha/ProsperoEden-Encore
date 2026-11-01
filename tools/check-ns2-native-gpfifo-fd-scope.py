#!/usr/bin/env python3
"""Reject process-wide GPU ABI promotion in the real NS2 research NVDRV channel."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "vendor/encore-active/ns2-runtime/nvdrv_gpu/core/hle/service/nvdrv/devices"
source = (BASE / "nvhost_gpu.cpp").read_text()
header = (BASE / "nvhost_gpu.h").read_text()

required_cpp = (
    "bool nvhost_gpu::UsesNativeAbi(DeviceFD fd) const {",
    "const auto it = sessions.find(fd);",
    "if (it == sessions.end()) return false;",
    "const auto* session = core.GetSession(it->second);",
    "NativeGpuProcessRegistry::Instance().Contains(session->process);",
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
    ("UsesNativeAbi()" not in source + header, "no unscoped native ABI call"),
    (source.count("return SubmitGPFIFOImpl(params, std::move(entries), fd);") == 2,
     "both GPFIFO submit paths propagate FD"),
    ("output, fd);" in source, "inline submit passes FD"),
    ("for (const auto& [fd, session_id] : sessions)" not in source,
     "no cross-process session scan"),
]
errors = [message for passed, message in checks if not passed]
if errors:
    print("NS2 NVDRV per-FD ABI isolation: FAILED: " + "; ".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("NS2 NVDRV per-FD ABI isolation source gate: PASS")
print("No NS2 GPU hardware or PS5 gameplay inference.")
