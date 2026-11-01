# NS2 graphics and shader upstream gap audit — 2026-11-01

The goals are (1) first **real guest image on PS5**, and (2) correct sky, terrain, textures and rendering without regressing Switch 1. A green native compile does **not** prove either.

## Independent sources examined

1. Original user link: `https://git.eden-emu.dev/gamecorner-033/eden-nx2` — currently not reachable to the audit tools. Accessible related fork: `https://git.eden-emu.dev/Takoroka/eden-nx2` (`eden-nx2` branch and 2026-10-29 release). This is not proof the inaccessible original has identical commits.
2. `https://github.com/heydemoura/EglantinePS5` (`main` e1de9c0, separate `fix/bananza-startup-and-terrain` e0b9f8d6). Its unmerged compatibility patch files 0003–0006 were compared by feature. Do **not** represent unmerged patch functionality as included in the official PS5 main.
3. `https://github.com/zortos293/Eglantine` (`nx2` d8a9528, `NX2_NOTES.md`, build 31 source badc91e). Notes document exact 100+ guest boot/render regressions, including rows 69, 82, 84, 86–99.
4. Additional relevant derived comparison: `https://github.com/Wael3rd/Eglantine-MKW`, release `mkw-2026-10-30-pre` and `NX2_VRAM.md`. Useful for dynamic VRAM budget and ASTC BC3, but neither PC results nor its driver assumptions automatically apply to PS5.
5. EglantinePS5's pinned `Djihads80/Eglantine` submodule is a *different* source snapshot from the zortos293 `nx2` branch; compare both rather than using its latest-branch label interchangeably.

## Current source changes (integrated on the vendor main)

| Component | Actual prior gap | Current change | Confidence / qualification |
|---|---|---|---|
| Vertex / geometry shader varyings | `shader_recompiler/frontend/ir/attribute.h::IsGeneric` excluded `Generic31Y/Z/W`, despite 32 x 4 attribute slots | Entire last vec4 now valid; host fixture checks every component | Exact one-line fix from EglantinePS5 0005; no console validation yet |
| Shader resource slots | `video_core/buffer_cache/buffer_cache_base.h` offered only 16 storage bindings | 32 slots + mask capacity assertion; mirrors EglantinePS5 0003 | Can prevent dropped NVN2 shader descriptors; NS1 must still be regression-tested |
| Native Ampere LDC | `lower_to_maxwell.h` rejected 8/16-bit constant loads (widths 1–3) | Reviewed signed/unsigned 8/16-bit forms accepted; widths 6/7 remain rejected | Exact opcode/format review based on EglantinePS5 0004; two compiler fixture |
| Native Ampere half predicates | 0x234 HSETP2 had no lowering case | Reviewed packed half register predicate mode added, unsupported modes still rejected | Based on EglantinePS5 0004; no real game shader proof yet |
| NS2 Compute/QMD3 | Eglantine NX2 0xC7C0, TU104 MME, 3 QMD release slots | Ampere class/execute path and per-process dependency scheduler added in prior lot | Nonempty Compute shaders remain **not executed**; do not fake fence completion |
| VI2 VSync | NS2 31/32 entirely missing | 60 Hz vblank events now provided in experimental service | PS5 compile success, first guest image still unverified |

The shader host fixtures are `tools/ns2/test_shader_generic31.cpp`, `tools/ns2/test_native_shader_texture_semantics.cpp`, plus the QMD3/CPU isolation fixtures in the host CI.

## Remaining gaps, ranked by first-image / visual impact

| Priority | Upstream evidence | Why it could cause reported symptoms | Next bounded step |
|---|---|---|---|
| P0 boot | Eglantine `NX2_NOTES.md` rows 42–60, 82–85 | Guest GMMU mapping / subchannel synchronization / present fences / event waits can stop all guest frames | Correlate actual PS5 `EDEN_NS2_IPC`, `EDEN_NS2_VI2_VSYNC`, `EDEN_NS2_GPFIFO`, `EDEN_NS2_GPU_BIND`, `EDEN_NS2_COMPUTE_QMD_UNSUPPORTED`, `guest_frame_handoff` |
| P0 visual | Eglantine rows 86, 88–93 | Missing sky / atmosphere can be a failed native pixel/geometry/volume shader, uniform predicate bug or missing task/mesh program | Produce negative-cache reason histogram by stage / opcode and correlate with skipped draws; check 32x32x32 volume textures |
| P0 geometry | EglantinePS5 0004 (LEPC, BMOV ATEXIT, geometry OUT), rows 89/97 | Existing Encore translation still lowers LEPC address to zero and has no complete task/mesh Vulkan pipeline; high-LOD mesh may be omitted or flicker | Port whole verified geometry exit/capture chain with tests; implement task/mesh or a proven alternative, never silent dropping |
| P0 texture | Eglantine rows 57, 68–70, 87, 94, 99; Wael `NX2_VRAM.md` | Black/flickering texture can be **missing physical backing**, stale GPU writes, wrong GOB/ASTC swizzle, or VRAM overcommit rather than shader lowering | Check actual per-frame VRAM budget, resident image extent/layers/mips, sparse unmapped detection, ASTC decode and texture generation. Never expose an unbacked image as a valid texture |
| P1 shader | EglantinePS5 0004 opcode compatibility and Eglantine rows 63, 88–93 | Native opcode omissions lead to skipped draws/shader failures; shader 0x234 and LDC 8/16 were concrete gaps now addressed | Import individually tested missing lowering forms, preserve precise source mapping and stage policy |
| P1 performance | Eglantine row 90 and EglantinePS5 current main | Repeated rejected shader translations/logs and broken driver disk cache cause frame-time spikes | Negative compile cache invalidated on GPU memory writes; atomic persistent shader cache after source-owner verification |
| P1 VRAM | Wael 2026-10-30: driver heap double-count and ASTC uncompressed budget overflow | Flashing garbage then crash, or black substitutes if sparse image is unbacked | Evaluate on PS5's special shared-pool allocator first: it already uses a graphics pool free-memory callback; *do not simply copy PC heap sums or force BC3 everywhere* |
| P2 Bananza | EglantinePS5 0006 Bananza-specific depth/color terrain workaround | Can repair terrain under particular verified passes but masks a generic cross-pass dependency flaw | Analyze generic pass resource / indirect-draw synchronization before game-ID-specific override |

## Source-owner boundaries

- Switch 1 is not a retrofitted Ampere title. Keep native GMMU/class/QMD shader owners opt-in and process-bound; global buffer/attribute bounds fixes must pass host tests and a Switch 1 gameplay regression.
- Native `vk_texture_cache_cost.cpp::ProbeSparseImage` currently exercises a *research probe*, **not** a fully resident live guest texture path. Its presence is not evidence that 8192x8192 layered textures render correctly.
- Experimental shader compile success does not mean the fragment/geometry programs' outputs, GPU image memory, or VI2 frame handoff are correct. Request on-console proof before claiming a fix.

## Validation receipts

- `41313252594`: PS5 experimental native build success for previous GPU/VI2/Compute lot `ea2a5cb`; artifact contains **none** of the new shader/texture fixes here.
- A subsequent host run is required to verify Generic31, 32 storage bindings, and native LDC/HSETP2 changes; mark as *source-integrated, not console-tested* until it finishes.
- No claim that all upstream commits were ported: this audit is about **high-impact structural and visual gaps**, not a full diff of every third-party tree.

