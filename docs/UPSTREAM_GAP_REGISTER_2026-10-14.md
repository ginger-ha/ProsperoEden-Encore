# Upstream coverage register — 14 October 2026

Scope: active development branch `dev/ps5-sparse-jit`. This is a **gap inventory**, not a claim that every independent library's source changes have been reviewed or validated on hardware. Pinned versions are intentional and must not be blindly updated. Exact third-party project identifiers are retained in source URLs, technical manifests and mandatory attribution.

## Current baseline comparison

Comparison counts are relative to the immutable dependency manifest at this date; `+N/−M` indicates divergent ancestry, **not** missing fixes that can simply be cherry-picked. GitHub's comparison endpoint returned at most 300 changed files for the main emulator (file list incomplete).

| Manifest component | Compared to upstream | Commits ahead / behind | Risk and status |
|---|---|---:|---|
| `eden` | Yes; pin `5f142c79` | +84 / 0 | **P0** kernel, timing, guest JIT, rendering; backports require per-commit verification |
| `ffmpeg` | No; source SHA pinned | — | Version locked; codec diff outside present simulation fault analysis |
| `fmt` | No; 12.1.0 tag | — | Version locked; compatibility via compile |
| `zbic` | Yes | 0 / 0 | No upstream drift |
| `compiler-rt` | No; compiler runtime snapshot | — | SDK/toolchain ABI gate, not rolling-head dependency |
| `pacbrew` | No; immutable binary distribution 0.40.2 | — | Build/runtime contract only |
| `opengl-source` | Yes | +18 / 0 | **P1** native GL runtime and launcher; review changed GPU source paths |
| `harfbuzz` | No; 12.3.2 release | — | Text shaping; track explicit regressions |
| `boilerplate` | Yes | +43 / 0 | **P1** loader, native process, storage, packaging |
| `ps5-vulkan-tools` | Yes | +18 / 0 | **P1** native Vulkan runtime tools / WSI; changed broker/client code |
| `ps5-mesa` | Yes | +110 / −103 | **P0** divergent driver ABI and graphics correctness; never wholesale repin |
| `ps5-payload-sdk-fork` | Yes | +100 / −48 | **P0** divergent native ABI, scheduling and direct-memory/runtime APIs |
| `encore-overrides` | Yes | 0 / 0 | No upstream drift |
| `opengl-opengnm-psbc` | Yes | 0 / 0 | No upstream drift |
| `opengl-opengnm` | Yes | 0 / 0 | No upstream drift |
| `opengl-spirv-headers` | Yes | +8 / 0 | P2 interface/grammar updates; shader ABI review |
| `opengl-vulkan-headers` | Yes | +6 / 0 | P2 header/video API updates; build compatibility |
| `opengl-imgui` | Yes | +1498 / 0 | P2 UI dependency; large historic drift, no wholesale bump |
| `opengl-nanovg` | Yes | 0 / 0 | No upstream drift |
| `opengl-sokol` | Yes | +219 / 0 | P2 sample/render utility; targeted review only |
| `opengl-native-boilerplate` | Yes | +52 / 0 | P1 second pin of same loader project, independently versioned |
| `opengl-mesa-26-2` | No; frozen Mesa 26.2.0 release archive | — | P1 software/OpenGL build; validate against ported fork |

Totals: 22/22 manifest entries **inventoried**; 15 entries compared to active Git refs, 7 reference pinned archives/releases/toolchains for which no equivalent current-branch comparison was made. The 300-file API cap and the divergence of two native providers prevent describing this as a complete source-diff review. No title save data was read or changed.

## High-impact kernel/guest corrections and closure

| Upstream correction | Actual Encore disposition | Required proof |
|---|---|---|
| Guest context/slab locks and lazy mutex backing (#4436 + #4447) | Both ported together under `vendor/encore-active/eden-threading` at `8f30384f9`; switchable via `EDEN_BLOCKING_GUEST_CONTEXT_LOCKS` | Native compile, post-match progress and latency test pending |
| Guest A32 page-table x86 addressing (#4415/#4444) | Equivalent indexed addressing derived in `headless/CMakeLists.txt` and `headless/checked-fastmem.cmake` | Host source-anchor validation; no claim of faster gameplay |
| Guest control reconnect fallback (#4420) | ReconfigureControllers logic present in `vendor/encore-active/eden-backports/src/core/frontend/applets/controller.cpp` | **Does not prove the title uses saved custom in-match controls** |
| Guest HID/app lifecycle (#4442) | Covered by earlier backports; see vendor audit from 12 October | Observe actual title-owned action settings |
| Video/texture sync (#4473/#4477) and TFB buffer updates (#4499) | Previously ported, under active backport tests | HUD pixels/alias/descriptor freshness not proved |
| Guest scheduler and event-wait provenance | New IPC active-wait and CPU-thread diagnostics `8bee9e532` | Cross-correlate same title thread around stalled frame |
| GPU driver memory/WSI changes after pinned revision | **Open**; branch diverges significantly | ABI and image-coherency matrix; staged native binary verification |
| Alternative compiler/runtime and thread APIs after SDK pin | **Open**; divergent ABI | Examine source, build and firmware-valid API calls before port |

## End-of-day upstream recheck — functional disposition

- [Original #156 — incremental guest/JIT backing](https://github.com/blackbearreloaded/ProsperoEden/commit/9ce26e650e26112d958f6db4b20d93260de77825): **not ported as an equivalent active runtime mechanism**. It modifies guest pool commitment, JIT Xbyak allocation/commit and kernel pool creation together. Encore already maintains a different sparse JIT/guest map lifetime. Keep a separate audited memory workstream rather than combine it with a gameplay baseline.
- [Main mirror #4499](https://github.com/eden-emulator/mirror/commit/6352612425ae0765802eaa8c5904ff652b97222a): **already implemented in the active native renderer**. `vendor/encore-active/eden-vulkan/vulkan_query_cache.cpp::FlushEndTFB` no longer calls `UpdateBuffers()`, while Begin does. `tools/check-ps5-tfb-counter-stability.py` asserts both positions. The old immutable `vendor/sources` still contains the call; do not infer a missing port by checking that archive alone.
- [Original #164/#171/#172](https://github.com/blackbearreloaded/ProsperoEden/commits/main): updated **emulator overlay information, launcher menu button remapping and translations**. This is not a fix for the guest title's delayed HUD nor proof that its saved in-match control preset applies. **Not declared integrated**, evaluate separately against Encore's launcher UI policy.
- [PS5 OpenGL SDK 1.0.2](https://github.com/blackbearreloaded/ps5-opengl/commit/a519561626933257213d64a4a8bd5e02b55dceb2): program-query/retirement/stats changes; **pin remains intentional** pending source and ABI parity validation. Not proof of a Vulkan match progression fix.
- [Latest maintained native WSI](https://github.com/mihawk-99/PS5_Mesa/commit/47e9eb61ee7e1112194557e1e047178562827bc6): refresh-mode acceptance changed for 119.88 Hz. Prior Encore 120 Hz work is tracked, but latest source parity is **not** established by pinning an older Mesa archive, and FC27 is currently a nominal 30 FPS title.
- [External native Vulkan runtime](https://github.com/mpereiraesaa/PS5_Mesa): disk-cache permission and unpresented-swapchain ownership fixes are adapted in maintained Encore sources. The latest Wine stream-compiler-gate architecture is **not a drop-in patch** for Encore's own Vulkan scheduler. Frame interpolation remains deferred until trustworthy game-progress pacing.

This is a **review of named current high-impact changes**, not a certification that every third-party repository, dependency and commit was imported. The separate [pre-test audit](PRETEST_AUDIT_2026-10-14.md) tracks run-specific log boundaries and native-package qualification.

## Audit controls

1. Every new dependency must be entered in this register; an inventory checker rejects additions without review rows. This is a **coverage alarm**, not an automatic integration decision.
2. Classify each relevant upstream diff as implemented / equivalent / inapplicable / candidate / unresolved, with source and tests. Counts and green CI status do **not** replace per-commit evidence.
3. Preserve native pinned versions, public licenses, legal author attributions, and required artifact names. Public-facing CI step labels use neutral technical descriptions.
4. Focus next on driver divergence, runtime scheduling/handoff, real title save-action selection and frame/HUD freshness. Reserve the console test for one verified package; do not use blind A/B trial loops.
5. Keep branches limited to `dev/ps5-sparse-jit`. During an active native run, defer unrelated workflow-label commits so GitHub's cancel-in-progress concurrency does not invalidate the candidate build.

Reference material: `docs/UPSTREAM_VENDOR_AUDIT_2026-10-12.md`, `docs/EXTERNAL_PS5_EMULATOR_ECOSYSTEM_AUDIT_R438.md`, source pinning in `tools/deps.json`, and the publicly linked upstream commits identified in those audits.



## Native memory package comparison (14 October 2026)

The native build previously inherited a boilerplate `param.json` without the optional `kernel.flexibleMemorySize` key, whereas the current primary source declares **335544320 bytes (320 MiB)**. Encore now explicitly writes this same value when packaging the native app; a host CI gate verifies the field without changing the runtime kernel, guest heap, JIT cache, GPU VRAM accounting, or per-game saves. The size is a package memory declaration, **not** the console's total physical capacity or a promise of additional available memory. Native compilation and firmware 13.60 behavior must still be qualified.

<!-- BEGIN AUTO-UPSTREAM-COMPARISON -->
### Automated comparison (daily + manual)

Checked in UTC: **2026-11-02 13:31 UTC**. Changes are commits relative to pins, not proven missing fixes.
This workflow never imports source patches, modifies dependencies, or reads console data.

| Dependency | Source | Pinned revision | Ahead / behind | Status |
|---|---|---|---:|---|
| eden | [eden-emulator/mirror](https://github.com/eden-emulator/mirror) | 5f142c7926d0 | +129 / -0 | upstream ahead |
| ffmpeg | [FFmpeg/FFmpeg](https://github.com/FFmpeg/FFmpeg) | c7b5f1537d9c | +5353 / -0 | upstream ahead |
| fmt | [fmtlib/fmt](https://github.com/fmtlib/fmt) | 12.1.0 | +379 / -0 | upstream ahead |
| zbic | [kinnay/zbic](https://github.com/kinnay/zbic) | 11b08f271226 | +0 / -0 | identical |
| compiler-rt | frozen archive / binary | — | — | not comparable |
| pacbrew | frozen archive / binary | — | — | not comparable |
| opengl-source | [blackbearreloaded/ps5-opengl](https://github.com/blackbearreloaded/ps5-opengl) | ad2807d41cef | — | repository unavailable |
| harfbuzz | frozen archive / binary | — | — | not comparable |
| boilerplate | [blackbearreloaded/ps5-native-app-boilerplate](https://github.com/blackbearreloaded/ps5-native-app-boilerplate) | dd44bbdc7543 | — | repository unavailable |
| ps5-vulkan-tools | [mihawk-99/PS5_Vulkan](https://github.com/mihawk-99/PS5_Vulkan) | 3f3ee6960701 | +74 / -0 | upstream ahead |
| ps5-mesa | [mihawk-99/PS5_Mesa](https://github.com/mihawk-99/PS5_Mesa) | 0b2d6d1a61d9 | +125 / -103 | diverged |
| ps5-payload-sdk-fork | [mihawk-99/PS5_PayloadSDK](https://github.com/mihawk-99/PS5_PayloadSDK) | 95c08f27386f | +105 / -48 | diverged |
| encore-overrides | [niakw/encore-overrides](https://github.com/niakw/encore-overrides) | 4fdb329e732a | +0 / -0 | identical |
| opengl-opengnm-psbc | [PS4-OpenGNM/opengnm-psbc](https://github.com/PS4-OpenGNM/opengnm-psbc) | a92a1228ea3a | +4 / -0 | upstream ahead |
| opengl-opengnm | [PS4-OpenGNM/opengnm](https://github.com/PS4-OpenGNM/opengnm) | 4b295ca54c82 | +0 / -0 | identical |
| opengl-spirv-headers | [KhronosGroup/SPIRV-Headers](https://github.com/KhronosGroup/SPIRV-Headers) | 0d25db97cb9b | +12 / -0 | upstream ahead |
| opengl-vulkan-headers | [KhronosGroup/Vulkan-Headers](https://github.com/KhronosGroup/Vulkan-Headers) | b51f6b865c18 | +10 / -0 | upstream ahead |
| opengl-imgui | [ocornut/imgui](https://github.com/ocornut/imgui) | f5befd2d29e6 | +1540 / -0 | upstream ahead |
| opengl-nanovg | [memononen/nanovg](https://github.com/memononen/nanovg) | ce3bf745eb2d | +0 / -0 | identical |
| opengl-sokol | [floooh/sokol](https://github.com/floooh/sokol) | 48c85905aeaa | +341 / -0 | upstream ahead |
| opengl-native-boilerplate | [blackbearreloaded/ps5-native-app-boilerplate](https://github.com/blackbearreloaded/ps5-native-app-boilerplate) | 4f531c4b517f | — | repository unavailable |
| opengl-mesa-26-2 | frozen archive / binary | — | — | not comparable |

### Source changes requiring review

These are upstream commit titles, not validated Encore integrations.

**eden** (history excerpt; some commits omitted)
- [c3f1e6562b6c](https://github.com/eden-emulator/mirror/commit/c3f1e6562b6c) — (common/fs) Preserve Windows roots during path sanitization (#4437)
- [4fe5f62c38e7](https://github.com/eden-emulator/mirror/commit/4fe5f62c38e7) — (dynarmic) fix sign extension and optimize vaddr lookups for 64bit on x64 systems (#4446)
- [90aafeedc1d9](https://github.com/eden-emulator/mirror/commit/90aafeedc1d9) — (k_scheduler) fix for libc++ that lazily initializes mutexes (#4447)
- [6374f7f51f02](https://github.com/eden-emulator/mirror/commit/6374f7f51f02) — Partial revert: (dynarmic) fix sign extension and optimize vaddr lookups for 64bit on x64 systems (#4446) (#4448)
- [14235dc0d054](https://github.com/eden-emulator/mirror/commit/14235dc0d054) — (ips) fix .pchtxt with 256 bytes on a single line (#4445)
- [1203082a8f12](https://github.com/eden-emulator/mirror/commit/1203082a8f12) — (msvc) fix build errors (#4451)
- [0ce29be60874](https://github.com/eden-emulator/mirror/commit/0ce29be60874) — (common) Fix RDTSC nanosecond conversion (#4422)
- [3c38afad74c7](https://github.com/eden-emulator/mirror/commit/3c38afad74c7) — (fs) share parent resources with bundled programs (#4319)
- [07f40d5cac63](https://github.com/eden-emulator/mirror/commit/07f40d5cac63) — (npad,hid,am) npad WriteEmptyEntry fix, hid function 551 stub, and applet PopOutData rework (#4442)
- [9a30172e45fc](https://github.com/eden-emulator/mirror/commit/9a30172e45fc) — (dynarmic) Coalesce non-exclusive Write/Read fallback functions (#4158)
- [908b1e9a3701](https://github.com/eden-emulator/mirror/commit/908b1e9a3701) — (dynarmic) fix bad arm codegen on relocations (#4458)
- [a277b62fe432](https://github.com/eden-emulator/mirror/commit/a277b62fe432) — (fs) revert #4319 savedata_factory changes (#4462)
- [74b5e10dc553](https://github.com/eden-emulator/mirror/commit/74b5e10dc553) — (native) doesUpdateMatchProgram update mask fix (#4465)
- [3266c20e3f27](https://github.com/eden-emulator/mirror/commit/3266c20e3f27) — (ips_layer) read magic from IPS file and fix EOF check (#4469)
- [38df54edfe7b](https://github.com/eden-emulator/mirror/commit/38df54edfe7b) — (common/sparse_large_vector) decommit unused pages + fix first page in zeroed region (#4471)
- [a25e32676fd3](https://github.com/eden-emulator/mirror/commit/a25e32676fd3) — (hle) Use correct 'audren:d' service framework (#4472)
- [3d37a816c6ad](https://github.com/eden-emulator/mirror/commit/3d37a816c6ad) — (glsl) fix clang 23 build error for unused function 'SetDefinition' (#4389)
- [cb73a4dcc771](https://github.com/eden-emulator/mirror/commit/cb73a4dcc771) — (renderer_vulkan) Skip post-processing on applet layers (#4474)
- [dbeb73ee0114](https://github.com/eden-emulator/mirror/commit/dbeb73ee0114) — (video_core) cpu buffer fix + kepler uploads / maxwell macro dirty tracking fixes (#4473)
- [99bf8cf51afb](https://github.com/eden-emulator/mirror/commit/99bf8cf51afb) — (am, renderer_vulkan) Fix overlay darkening and SGSR black screen on applets (#4475)
- [bebc19da3253](https://github.com/eden-emulator/mirror/commit/bebc19da3253) — (common) Use 'std::make_unique_for_overwriteT' in ScratchBuffer, remove polyfill (#4432)
- [87d2f03c39bc](https://github.com/eden-emulator/mirror/commit/87d2f03c39bc) — (hid_core) Code cleanup (#4461)
- [f273423b2b83](https://github.com/eden-emulator/mirror/commit/f273423b2b83) — (buffer_cache) Simplify GPU fence synchronization and remove GPU buffer readback (#4477)
- [a82f31a310c5](https://github.com/eden-emulator/mirror/commit/a82f31a310c5) — (settings,qt) merge of "disable controller applet" toggle with "controller applet mode" picker (#4498)
- [8e2d26c27268](https://github.com/eden-emulator/mirror/commit/8e2d26c27268) — (video_core) buffer cache readback for nce invalidations (#4490)
- [2a7e9b53b127](https://github.com/eden-emulator/mirror/commit/2a7e9b53b127) — (android,ui) fixed shader cache clearing when changing drivers (#4496)
- [963119e7cc38](https://github.com/eden-emulator/mirror/commit/963119e7cc38) — (ffmpeg)Gamescope / Gamemode NVDEC Emulation -  GPU Decoding Patches (#4501)
- [3cdd2ce14122](https://github.com/eden-emulator/mirror/commit/3cdd2ce14122) — (android, renderer_vulkan) Сhange default settings (#4509)
- [67bada77f8a4](https://github.com/eden-emulator/mirror/commit/67bada77f8a4) — (video_core) Skip fragment shaders with known issues on non-NVIDIA drivers (#4503)
- [c746982201a6](https://github.com/eden-emulator/mirror/commit/c746982201a6) — (*) fix clangarm64 compilation (#4521)
- [fecc1b4ee32b](https://github.com/eden-emulator/mirror/commit/fecc1b4ee32b) — revert (vulkan) Masquerade VkInfo as PUBGMobile + UE #4320 (#4520)
- [6352612425ae](https://github.com/eden-emulator/mirror/commit/6352612425ae) — (vk) Return the corrections made for buffer update logic #3690 (#4499)
- [4dc69c06f764](https://github.com/eden-emulator/mirror/commit/4dc69c06f764) — (*) Remove Fix{Static,Small}VectorADL workaround for GCC 12 (#4386)
- [a594c8d60ef7](https://github.com/eden-emulator/mirror/commit/a594c8d60ef7) — (shader_recompiler, vulkan, qcom, tu) Provide handling to missing shader subgroups on QCOM (#4508)
- [fb51a1253447](https://github.com/eden-emulator/mirror/commit/fb51a1253447) — (input/sdl) nuke SDL_Vibration thread (#4299)
- [14da4482a466](https://github.com/eden-emulator/mirror/commit/14da4482a466) — (input_common/joycon) Enumerate SDL devices iff SDL signals change (#4486)
- [d8c6c59b6798](https://github.com/eden-emulator/mirror/commit/d8c6c59b6798) — Fix Check Strings after 4523 (#4534)
- [e0d47f2790e3](https://github.com/eden-emulator/mirror/commit/e0d47f2790e3) — (cmake) fix macOS compilation by forcing lz4 to be static (#4540)
- [de7e6e01d43e](https://github.com/eden-emulator/mirror/commit/de7e6e01d43e) — Revert 	(input_common/joycon) Enumerate SDL devices iff SDL signals change (#4486) (#4545)
- [989768aa4672](https://github.com/eden-emulator/mirror/commit/989768aa4672) — Fix (core, gpu, threads) Multithreading refactor (#4254) (#4548)
- [305f40100d76](https://github.com/eden-emulator/mirror/commit/305f40100d76) — Fix aarch and android builds (#4576)
- [eb88a40a8eb0](https://github.com/eden-emulator/mirror/commit/eb88a40a8eb0) — (qt) fix graphics API toggle getting stuck on OpenGL_GLSL (#4577)
- [58968bd1274d](https://github.com/eden-emulator/mirror/commit/58968bd1274d) — (core) Support block-compressed NSZ and XCZ (#4552)
- [a95efaf18f50](https://github.com/eden-emulator/mirror/commit/a95efaf18f50) — (vulkan) Fix TOTK dark squares (#4565)
- [0689f73147eb](https://github.com/eden-emulator/mirror/commit/0689f73147eb) — (ir) resolve conditional Phi inputs when tracking bindless texture handles (#4551)

**ffmpeg** (history excerpt; some commits omitted)
- [9c51aa182488](https://github.com/FFmpeg/FFmpeg/commit/9c51aa182488) — swscale: add SwsCompiledOp.slice_align
- [c911295f096c](https://github.com/FFmpeg/FFmpeg/commit/c911295f096c) — swscale: forward original frame pointers to ops.c backend
- [1d2e616d5f72](https://github.com/FFmpeg/FFmpeg/commit/1d2e616d5f72) — swscale: add a Vulkan backend for ops.c
- [362414afbaaf](https://github.com/FFmpeg/FFmpeg/commit/362414afbaaf) — swscale: add support for processing hardware frames
- [bd24abfb6cb6](https://github.com/FFmpeg/FFmpeg/commit/bd24abfb6cb6) — swscale/vulkan: initialize GLSL compilation and shader execution
- [47e87ed72233](https://github.com/FFmpeg/FFmpeg/commit/47e87ed72233) — Changelog: add entry about swscale Vulkan support
- [86ddc8b4383b](https://github.com/FFmpeg/FFmpeg/commit/86ddc8b4383b) — swscale/output: Fix some integer overflows in yuv2rgba64_full*()
- [f436d885fc10](https://github.com/FFmpeg/FFmpeg/commit/f436d885fc10) — swscale/swscale: fix typos

**fmt** (history excerpt; some commits omitted)
- [a9ea225cadc2](https://github.com/fmtlib/fmt/commit/a9ea225cadc2) — Fix C++20 concept detection (#4653)
- [25df8ccd96ab](https://github.com/fmtlib/fmt/commit/25df8ccd96ab) — Fix usage of memset
- [5cc5072aa68c](https://github.com/fmtlib/fmt/commit/5cc5072aa68c) — Fix range suppresor formatter (#4660)
- [a5cd004883ab](https://github.com/fmtlib/fmt/commit/a5cd004883ab) — Fix badge image link in README.md
- [45ed657df3c8](https://github.com/fmtlib/fmt/commit/45ed657df3c8) — Cleanup locking
- [d04c9801a751](https://github.com/fmtlib/fmt/commit/d04c9801a751) — Dedup compile check enforcement
- [39e15aff74a9](https://github.com/fmtlib/fmt/commit/39e15aff74a9) — Fix template argument ordering
- [2eda43e9be17](https://github.com/fmtlib/fmt/commit/2eda43e9be17) — Add FMT_USE_FLOCKFILE macro to force has_flockfile trait to false (#4666)

**ps5-vulkan-tools**
- [8cc2e4dc9eea](https://github.com/mihawk-99/PS5_Vulkan/commit/8cc2e4dc9eea) — gpu-broker: an application's panel over every frame, the frame passed through outside it
- [6224e4cb925d](https://github.com/mihawk-99/PS5_Vulkan/commit/6224e4cb925d) — gpu-broker: a capture asked for while the panel is shown over a waiting game is of the frame shown again
- [47b3fc84acc6](https://github.com/mihawk-99/PS5_Vulkan/commit/47b3fc84acc6) — gpu-broker: say how long the panel waits for the display and how long its re-show takes
- [98bf667e7743](https://github.com/mihawk-99/PS5_Vulkan/commit/98bf667e7743) — gpu-broker: a panel's re-show streams the frame from a cached shadow, not a read-back of the display
- [8bbd74419ee0](https://github.com/mihawk-99/PS5_Vulkan/commit/8bbd74419ee0) — gpu-broker: a see-through panel blended over the frame blurred under it, with bubbles rising in its margins
- [64e105099d09](https://github.com/mihawk-99/PS5_Vulkan/commit/64e105099d09) — gpu-broker: say what the see-through panel costs, every 120 composes
- [a62b05d9fe7f](https://github.com/mihawk-99/PS5_Vulkan/commit/a62b05d9fe7f) — gpu-broker: a panel change over a waiting game is shown at once, not at the bubbles' next re-show
- [66dad9f1670e](https://github.com/mihawk-99/PS5_Vulkan/commit/66dad9f1670e) — gpu-broker: the panel's blur made every second frame, and a rare glass sweep (1 s after it opens, then at most ever

**ps5-mesa** (history excerpt; some commits omitted)
- [ff437af31b9b](https://github.com/mihawk-99/PS5_Mesa/commit/ff437af31b9b) — radv/ps5: mesh workgroups in parts run once and publish their outputs
- [e81c660bbfbf](https://github.com/mihawk-99/PS5_Mesa/commit/e81c660bbfbf) — radv/ps5: report mesh shaders
- [528835a404e8](https://github.com/mihawk-99/PS5_Mesa/commit/528835a404e8) — Merge ps5-mesh: mesh shaders without per-primitive parameters
- [ddae965f7d4e](https://github.com/mihawk-99/PS5_Mesa/commit/ddae965f7d4e) — radv/ps5: mesh shaders alone stay behind RADV_PS5_MESH
- [07e90fd66665](https://github.com/mihawk-99/PS5_Mesa/commit/07e90fd66665) — Merge ps5-mesh: mesh shaders alone stay behind RADV_PS5_MESH
- [ded225a9396d](https://github.com/mihawk-99/PS5_Mesa/commit/ded225a9396d) — radv/ps5: task shaders on the graphics ring (RADV_PS5_TASK)
- [0be56b9bcec2](https://github.com/mihawk-99/PS5_Mesa/commit/0be56b9bcec2) — radv/ps5: stages run as compute get all their descriptors; task dispatches keep out of statistics
- [cab30ddf59b6](https://github.com/mihawk-99/PS5_Mesa/commit/cab30ddf59b6) — radv/ps5: report task and mesh shaders
- [bc9eedba6b1f](https://github.com/mihawk-99/PS5_Mesa/commit/bc9eedba6b1f) — Merge ps5-task: task shaders on the graphics ring, and with them VK_EXT_mesh_shader
- [e8593120f143](https://github.com/mihawk-99/PS5_Mesa/commit/e8593120f143) — radv/ps5: ray tracing group handles captured and replayed
- [deb172b278ca](https://github.com/mihawk-99/PS5_Mesa/commit/deb172b278ca) — radv/ps5: on-disk shader cache in the title's folder
- [a33b57481443](https://github.com/mihawk-99/PS5_Mesa/commit/a33b57481443) — Merge ps5-shader-cache: on-disk shader cache in the title's folder
- [c551a7ad9338](https://github.com/mihawk-99/PS5_Mesa/commit/c551a7ad9338) — util/disk_cache: a lookup does not make parts; the PS5 changes modes only when needed
- [035a22bc823b](https://github.com/mihawk-99/PS5_Mesa/commit/035a22bc823b) — Merge ps5-shader-cache: a lookup does not make parts; the PS5 changes modes only when needed
- [d4afe0c3f7b5](https://github.com/mihawk-99/PS5_Mesa/commit/d4afe0c3f7b5) — util/mesa_cache_db: an exclusive mode, the default on the PS5
- [2d1a8cf74fda](https://github.com/mihawk-99/PS5_Mesa/commit/2d1a8cf74fda) — Merge ps5-shader-cache: the mesa-db cache's exclusive mode
- [a989e3e9d3f1](https://github.com/mihawk-99/PS5_Mesa/commit/a989e3e9d3f1) — radv/ps5: a line every 10 s on where submissions' time goes
- [1538d3032c96](https://github.com/mihawk-99/PS5_Mesa/commit/1538d3032c96) — radv/ps5: the CPU flush uses CLFLUSHOPT
- [fde48a3b031c](https://github.com/mihawk-99/PS5_Mesa/commit/fde48a3b031c) — radv/ps5: the suspend point is made by a thread of its own
- [d0d7325e447b](https://github.com/mihawk-99/PS5_Mesa/commit/d0d7325e447b) — radv: threaded recording (RADV_THREADED_RECORDING=1)

**ps5-payload-sdk-fork** (history excerpt; some commits omitted)
- [118653bc5d11](https://github.com/mihawk-99/PS5_PayloadSDK/commit/118653bc5d11) — setup-sdk: install the fork's compiler wrappers over the release's
- [5e9abd707a57](https://github.com/mihawk-99/PS5_PayloadSDK/commit/5e9abd707a57) — PROBE: memory streams on a pipe, measured through the CTS title
- [a5cbafeed4b0](https://github.com/mihawk-99/PS5_PayloadSDK/commit/a5cbafeed4b0) — platform: memfd_create, on libkernel's anonymous shared memory objects
- [d4fa6d759657](https://github.com/mihawk-99/PS5_PayloadSDK/commit/d4fa6d759657) — platform: getpwuid_r and posix_fallocate
- [0c374e80d80b](https://github.com/mihawk-99/PS5_PayloadSDK/commit/0c374e80d80b) — platform: the title heap in arenas, one for each allocating thread
- [b83202be73e9](https://github.com/mihawk-99/PS5_PayloadSDK/commit/b83202be73e9) — platform: the title heap usable without its wraps
- [545232e73bdd](https://github.com/mihawk-99/PS5_PayloadSDK/commit/545232e73bdd) — include: clock IDs visible from POSIX 199309, as FreeBSD has them
- [168c13732a85](https://github.com/mihawk-99/PS5_PayloadSDK/commit/168c13732a85) — platform: executable memory by pointer, with no limit on how many
- [f1608d665bdf](https://github.com/mihawk-99/PS5_PayloadSDK/commit/f1608d665bdf) — probe: executable memory by pointer, past the old 128
- [104683613fe8](https://github.com/mihawk-99/PS5_PayloadSDK/commit/104683613fe8) — probe: memory around the pointer step; cached stacks in the final check
- [41dc86f97f41](https://github.com/mihawk-99/PS5_PayloadSDK/commit/41dc86f97f41) — probe: how the console schedules a title's threads
- [3b448ae98729](https://github.com/mihawk-99/PS5_PayloadSDK/commit/3b448ae98729) — platform: committed memory in reserved ranges, exact reservations, and accept4, getpagesizes, in6addr_any and threa
- [8278ca5e9cd0](https://github.com/mihawk-99/PS5_PayloadSDK/commit/8278ca5e9cd0) — platform: zero what is promised fresh; the console hands released direct memory out as it was
- [8a2e5104c9ee](https://github.com/mihawk-99/PS5_PayloadSDK/commit/8a2e5104c9ee) — platform: ps5_sysconf answers the CPUs a title's threads run on
- [5fa43c4d7e19](https://github.com/mihawk-99/PS5_PayloadSDK/commit/5fa43c4d7e19) — platform: thread_local destructors before key destructors; gai_strerror; pthread_exit
- [b9d357168fbb](https://github.com/mihawk-99/PS5_PayloadSDK/commit/b9d357168fbb) — platform: statfs, fstatfs, umask, fork, setsid and wait4
- [43e51c4ac782](https://github.com/mihawk-99/PS5_PayloadSDK/commit/43e51c4ac782) — platform: the offload probe reads the mount with _fstatfs
- [4141c13cf537](https://github.com/mihawk-99/PS5_PayloadSDK/commit/4141c13cf537) — platform: the route probe writes with 1, 4 and 8 threads after the burst
- [7613b71460b8](https://github.com/mihawk-99/PS5_PayloadSDK/commit/7613b71460b8) — platform: each topology pair runs on two fresh threads
- [3752be7e7812](https://github.com/mihawk-99/PS5_PayloadSDK/commit/3752be7e7812) — Block contended heap waits and expose shared memory availability

**opengl-opengnm-psbc**
- [29ae2427dd9b](https://github.com/PS4-OpenGNM/opengnm-psbc/commit/29ae2427dd9b) — psbc: build descriptor set layout, assign VS param exports and FS inputs
- [28697f007862](https://github.com/PS4-OpenGNM/opengnm-psbc/commit/28697f007862) — Merge pull request #2 from sergiopoverony/ps4-fixes

**opengl-spirv-headers**
- [2f88364fbce8](https://github.com/KhronosGroup/SPIRV-Headers/commit/2f88364fbce8) — fix enabling capability for generic pointer instructions (#633)
- [f1fa5178eced](https://github.com/KhronosGroup/SPIRV-Headers/commit/f1fa5178eced) — fix TaskPayloadWorkgroupEXT storage class version (#636)
- [86f980c731e6](https://github.com/KhronosGroup/SPIRV-Headers/commit/86f980c731e6) — clean up SPV_INTEL_memory_access_aliasing (#637)

**opengl-vulkan-headers**
- [31386378257a](https://github.com/KhronosGroup/Vulkan-Headers/commit/31386378257a) — Update for Vulkan-Docs 1.4.361
- [ee2ec5fd83da](https://github.com/KhronosGroup/Vulkan-Headers/commit/ee2ec5fd83da) — Update for Vulkan-Docs 1.4.362
- [6802bb4733b6](https://github.com/KhronosGroup/Vulkan-Headers/commit/6802bb4733b6) — Update for Vulkan-Docs 1.4.363
- [b0c3dd6851e2](https://github.com/KhronosGroup/Vulkan-Headers/commit/b0c3dd6851e2) — Update for Vulkan-Docs 1.4.364
- [3c65a01745e4](https://github.com/KhronosGroup/Vulkan-Headers/commit/3c65a01745e4) — Add vulkan_ubm.h to build.gn
- [c46850864f46](https://github.com/KhronosGroup/Vulkan-Headers/commit/c46850864f46) — Update for Vulkan-Docs 1.4.365
- [73814d006638](https://github.com/KhronosGroup/Vulkan-Headers/commit/73814d006638) — Update for Vulkan-Docs 1.4.366
- [9fbc2a782ee3](https://github.com/KhronosGroup/Vulkan-Headers/commit/9fbc2a782ee3) — Update for Vulkan-Docs 1.4.367

**opengl-imgui** (history excerpt; some commits omitted)
- [1387d356aab8](https://github.com/ocornut/imgui/commit/1387d356aab8) — stb_textedit: subsequent fixes for next/prev word impl (not used by imgui) + PageUp/Home/End (no side effect but mo
- [b5a73033ab54](https://github.com/ocornut/imgui/commit/b5a73033ab54) — Examples: Apple: Amend build scripts and gitignore, fix misc OSX warnings. (#8637)
- [87a6443c5bc6](https://github.com/ocornut/imgui/commit/87a6443c5bc6) — Scroll: fixed contents size, scrollbar visibility and scrolling reet issue with abnormally large contents ranges. (
- [19289d587a3a](https://github.com/ocornut/imgui/commit/19289d587a3a) — Nav: fixed scroll fallback (when there are no interactive widgets to jump to) not being enabled on windows with men
- [c3a3a39e92ad](https://github.com/ocornut/imgui/commit/c3a3a39e92ad) — Nav: fixed abnormal clipping disable over large ranges, could lead to stall. (#3841, #1725)
- [69e1fb50cacb](https://github.com/ocornut/imgui/commit/69e1fb50cacb) — Docs: fixed missing commit credit. (#8656)
- [b7ab2b752374](https://github.com/ocornut/imgui/commit/b7ab2b752374) — TreeNode: fixed an issue where tree lines are not drawn on node opening frame. (#2920)
- [ef503ab0c881](https://github.com/ocornut/imgui/commit/ef503ab0c881) — TreeNode: fixed out of bound access in ImGuiTreeNodeFlags_DrawLinesXXX feature. (#2920)

**opengl-sokol** (history excerpt; some commits omitted)
- [747b20e4c19b](https://github.com/floooh/sokol/commit/747b20e4c19b) — sokol_gfx.h: sg_copy_buffer_to_buffer wip
- [1647500f2d5e](https://github.com/floooh/sokol/commit/1647500f2d5e) — sokol_gfx.h mtl: implement sg_copy_buffer_to_buffer
- [f933ac5ac8c2](https://github.com/floooh/sokol/commit/f933ac5ac8c2) — sokol_gfx_imgui.h: basic support for copy-buffer-to-buffer
- [47d102faa0e2](https://github.com/floooh/sokol/commit/47d102faa0e2) — sokol_gfx.h, sokol_gfx_imgui.h: remove sg_update/append_buffer funcs and related code
- [090a9475b32d](https://github.com/floooh/sokol/commit/090a9475b32d) — sokol_gfx.h: more sg_copy_buffer_to_buffer validation
- [6c731a4f64ff](https://github.com/floooh/sokol/commit/6c731a4f64ff) — sokol_gfx.h: sg_copy_buffer_to_image wip
- [a05979d7955b](https://github.com/floooh/sokol/commit/a05979d7955b) — sokol_gfx.h: validate sg_copy_buffer_to_buffer src/dst offset to be multiple of 4
- [e0ca0b5c297c](https://github.com/floooh/sokol/commit/e0ca0b5c297c) — sokol_gfx.h: sg_copy_buffer_to_image desc-defaults and validation

Unavailable comparisons are not equivalent to zero changes.
The API can truncate changed-file lists beyond 300 files.
<!-- END AUTO-UPSTREAM-COMPARISON -->
