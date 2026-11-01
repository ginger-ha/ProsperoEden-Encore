# NS2 GPU access attribute syscall — reviewed integration

**Status:** ABI/memory validation, not a native GPU rendering path.

The unified PS5 release selects an exact maintained kernel dispatcher owner that preserves normal NS1 SVC dispatch. Only `imm == 0x80`, a **registered NS2 ExeFS process PID**, a 64-bit process, and its 12 GiB guest layout can enter the adapter. Its 0x20 attribute mask can be enabled or cleared; all other attributes are explicitly rejected. Address, size, 4 KiB alignment, overflow and current guest page-table ownership are validated. On a valid request the bit is now **persisted in the real KPageTableBase memory block attributes** via SetMemoryAttribute, so QueryMemory and downstream users can read it. Invalid requests return ordinary kernel results. The source includes two reviewed complete header overlays (Svc::MemoryAttribute and KMemoryAttribute) with the 0x20 bit, keeping the pinned NS1 layout and state semantics. A previous version returned success without storing the attribute; this correction eliminates that false success.

The adapter is intentionally not a GMMU mapping, shader translator, GPU command execution, frame submission, kernel memory pinning service or device-memory coherence proof. It cannot by itself resolve the reported black screen. NVIDIA worker and graphics supervisor research paths stay excluded from the release.

Upstream idea: Djihads80/Eglantine nx2 (SVC 0x80), adapted by tightening process identity and range/flag validation rather than unconditional `args[0] = 0`.

`tools/check-ns2-gpu-access-svc-host.py` compiles and runs constexpr alignment/mask/overflow/PID fixtures and checks the exact shipping source/CMake wiring. First native PS5 compile and console evidence still required.
