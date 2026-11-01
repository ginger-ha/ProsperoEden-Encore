# NS2 boot gap audit — upstream comparison (2026-11-01)

**Scope:** user's PS5 source `97fb62c`, two zero-guest-frame sessions (Mario Kart World `0400C3F00006E000`, Donkey Kong Bananza `040074A01BF12000`). Both load NSOs, start Vulkan/guest CPU, present loading frames at 60 Hz and never hand off a guest frame. **Do not infer a functioning Ampere GPU pipeline from CI alone.**

## Sources and provenance

- `https://git.eden-emu.dev/gamecorner-033/eden-nx2`: user-provided historical Forgejo location, inaccessible when checked. Cross-referenced the publicly reachable `https://git.eden-emu.dev/Takoroka/eden-nx2` fork and its NX2 branch without claiming byte-exact identity.
- `https://github.com/heydemoura/EglantinePS5`: PS5 port; its `Eglantine` submodule points at **Djihads80/Eglantine**, pinned to `b40ad217ab829226841cb71f6e4c5cb05977a225` on checked `main`. The unmerged `fix/bananza-startup-and-terrain` branch at `e0b9f8d6fbcd35ebcc5cc723f9747e97dcdaec48` contains reviewed compatibility patches; do not treat them as released main changes.
- `https://github.com/zortos293/Eglantine` `nx2` at `d8a9528ba227e3618f8c050706dcf79cabd303f6`; `NX2_NOTES.md` documents specific boot failures and fixes. Release `nx2-build31-20261101` uses source `badc91ebce`; another release on October 31 reported 180 seconds of Bananza GUI execution.
- Additional independent reference: `https://github.com/Mars-Hermetto/monkey` describes Bananza reaching menu and 3D gameplay on Windows; not proof of PS5 parity.

## Actionable gaps (avoid claiming a first frame until PS5 confirms it)

| Priority | Upstream evidence | State in Encore NS2 research | Change / next verification |
|---|---|---|---|
| **P0** | Eglantine NVDRV control: Ampere engine IDs `C797/C7C0/C56F/C7B5`, SM 0x808; NX2_NOTES 24/45 | `native_gpu_characteristics.h` previously copied the Maxwell engine IDs in first 0x70 bytes into the 0xD0/0xD8 native reply; TSG count=64 and bits 8/22 were **already** present | Fixed in vendor `00cd453`, test `test_native_gpu_ioctl.cpp` asserts actual class IDs. Legacy 0xA0 response untouched |
| **P0** | NX2_NOTES row 82: Mario Kart World waits for **two** VI2 cmd-32 vblank signals before GPU submissions | `IVi2Session` previously implemented cmd 11 notification only; 31/32 were absent | Added 31/32 60 Hz timer-backed events under experimental graphics supervisor `0536458`; observe real guest IPC and ticks |
| **P0** | NX2_NOTES rows 30/42/46/57: native GPU VA mappings, GPU-only sparse render targets, syncpoint shim and worker protocol must all be mapped and coherent | Native NS2 TIPC GPU session previously inherited the 37-bit Maxwell VA limit (ending at 128 GiB), which cannot cover upstream GPU-only targets around 0x81_0000_0000 (above 512 GiB). NS2 sessions now request a checked 40-bit GMMU; the original NVDRV default is unchanged. However 214 still reserves **unbacked** sparse VA, not automatically GPU-only physical memory | Host VA fixture checks 0x81_0000_0000 in the 4K partition. Bounded `EDEN_NS2_GPU_214` prints mode/page shift/range/result and `backing=unbound`; `EDEN_NS2_GPU_216` distinguishes processed entries from actual physical handle mappings. Confirm both on PS5 before designing allocation policy |
| **P0** | NX2_NOTES rows 53/60/84: `C7C0` compute/QMD3 scheduler, semaphore releases and per-channel MME data RAM are required | Local GPFIFO puller handles `C797` and `C7B5`; no complete `C7C0` dispatch path; Ampere macro state only partial | Port upstream native compute/QMD and synchronization as a coherent lot, not generic Maxwell aliases |
| **P0** | NX2_NOTES rows 48/55/82: VI2 cmd 229 fences, 31/32 vblank and real NVMap block-linear presentation | Local VI2 229 submits Nvnflinger GraphicBuffers; actual guest image backing, release fences, pacing and first handoff **unverified** | First classify source of `guest_frame_handoff=0` using bounded IPC/GPFIFO/bind traces |
| P1 | EglantinePS5 `0003-switch2-storage-buffer-slots.patch` | Base Eden `NUM_STORAGE_BUFFERS=16`, upstream patch raises to 32 | Review descriptor and shader ABI together; no blanket NS1 changes |
| P1 | EglantinePS5 `0005-generic31-components.patch` | Base `IsGeneric` stops at `Generic31X`, excludes Y/Z/W | Review generic31 range, tests and NS1 impact |
| P1 | EglantinePS5 `0004-bananza-native-shader-modes.patch` | Local lowering includes some forms, but LEPC/exit handler and numerous opcode modes need structured diff | Run semantic opcode/IR diff before copying; no synthetically invented support |
| P2 | NX2_NOTES rows 88–96: mesh/task shaders, huge textures, negative shader cache, 3D ASTC, MUFU | Distinct advanced rendering compatibility gaps | Work after **first real frame**, not before |

## Verified vs not verified

- **Verified from provided logs**: source `97fb62c` loads both game NSOs; Vulkan initializes; guest execution begins; `guest_frame_handoff=0` at 10/30 sec; loading graphics continue to present. No proof of Ampere GPU submissions or first guest image.
- **Not yet validated**: vendor fixes `00cd453` + `0536458` compiled into PS5 research binary, behavior on console, actual native GPU ownership, native compute/VI2.
- **Next candidate test**: one consolidated experimental PS5 build with the above and bounded `EDEN_NS2_IPC`, `EDEN_NS2_GPFIFO`, `EDEN_NS2_GPU_BIND`, `EDEN_NS2_VI2_VSYNC` markers. If 31/32 tick and GPFIFO remains zero, inspect SDK/service waits; if GPFIFO nonzero but no binds, inspect class/context; if binds valid but zero frames, complete native compute/sync/mapping/VI2 pipeline.

Release Switch 1 remains on the original code paths; NS2 fixes are opt-in. Do not merge entire upstream source trees blindly.
