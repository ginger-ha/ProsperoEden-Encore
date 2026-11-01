# FC27 — 2026-11-01 stable-playback jitter and HUD audit

## Grounded console capture (do not commit private logs)

- Build: `6271928eb7b5d50687fccc730ae706986f3d6108`.
- Source: three successive launches within `heap(20261101-071933).log`; FC27 is the third.
- FC27 window count: 89 reports, approximately 447 seconds of displayed callbacks.
- The first minutes include 359 cold shader misses across the session; the worst early first-use stalls must be studied separately from steady playback.
- The report after the **first 180 seconds** covers 54 five-second windows, 18 intervals >50ms and one >100ms.
- **50/54** steady windows contain no >50ms intervals.
- Two concentrated windows account for **15/18** remaining >50ms intervals:

| Approximate elapsed time | Renderer frame | 5s FPS | late50 | worst frame | cache blocked acquisitions | cumulative cache wait |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 316s | 9,167 | 26.709 | 7 | 166.014ms | 2,882 | 45.382ms |
| 422s | 12,309 | 26.314 | 8 | 88.060ms | 4,953 | 78.987ms |

## Interpretation — observations vs hypotheses

The residual 5-second drops are **bursts**, not a constant 10% FPS deficit. Both spikes correlate with increased cache-lock contention, but thread-summed waits do **not** equal presentation wall time. 45.382ms of aggregated waiting cannot by itself explain every lost 30Hz display slot in a five-second period.

HUD lag is user-observed but **not directly measured**: `EDEN_VULKAN_FRAME` counts presented callbacks, not image-content revisions or the age of guest HUD glyphs. A late/missing HUD texture cannot currently be attributed to a particular invalidation, descriptor update, draw omission or stale guest scene using these logs.

The 60.0Hz `clock_hz` field is the **game clock setting**. The PS5 display negotiation reports 59.94Hz. These values alone are insufficient to attribute the two irregular 5-second bursts to HDMI drift.

The `jit_ms=0`, `guest_ipc_ms=0` and `gpu_dispatch_ms=0` values from incomplete release instrumentation must not be treated as proven absence of workload.

## Added regression / no-new-console-test gate

`tools/analyze-fc27-release-sessions.py` now emits a per-launch `steady_state` section, with:
- explicit exclusion of the first 180 seconds, based on logged presentation time (not a game-scene clock)
- ranked clusters with frame key, late50/100, worst, cache contention and summed waits
- explicit counts for missing/unpaired pressure windows
- no invented HUD content freshness, frame-causality or CPU/GPU owner identification
- host self-test for mixed sessions, burst accounting, and incomplete profiling

## Next actual runtime candidate (not implemented by this forensic PR)

Only after confirming an exact lock *owner*, reduce the **measured** buffer/texture mutex-held section, keeping CPU-written texture invalidation, guest remap, GPU fence and draw order intact. For HUD, specifically verify the guest texture revision/descriptor generation across the draw-to-present boundary, and compare image-content freshness to the presented callback. Removing fences or reusing descriptors without ownership proof is not an acceptable fix.

No engine hot path is changed in this PR; do not claim an FPS/HUD improvement from an offline analyzer. A future source-level runtime correction should be proved by native-source O0/O2 tests and one consolidated PS5 validation, not repeated manual trials.
