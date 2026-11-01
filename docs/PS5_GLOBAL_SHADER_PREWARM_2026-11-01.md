# PS5 Vulkan — global bounded persisted shader prewarm (2026-11-01)

## Runtime observation and goal

The FC 27 console trace on 2026-11-01 shows a strong cluster of first-use shader compilation and
long presentation intervals near match startup. The tester also reports residual micro-stutter
and occasional delayed HUD content during otherwise largely smooth gameplay. These are two
possibly distinct problems: widening startup cache restoration cannot alone prove a fix for
late-match frame pacing, texture freshness, or guest rendering progress.

## Scope of this candidate change

- Every title (NS1 and NS2) uses **the same** persisted-pipeline reader quota: up to **32**
  entries instead of 8. There are **no title-ID special cases**.
- If a title's cache has fewer than 32 valid serialized entries, the reader naturally loads
  only the available entries. This does not manufacture pipelines for unseen shaders.
- Quota cancellation affects **only the cache file reader**. Accepted shader-builder jobs
  finish before the local load state is destroyed; the worker pool stays alive for gameplay.
- Valid native handles are the only ones admitted into the prewarm maps, as before.
- The startup summary includes `limit=32` and the real queued/completed/valid/rejected counts.
- The active Vulkan vendor source and its reproducible `prepare-vulkan-port.py` generator
  must remain byte-for-byte equivalent for the quota and summary changes.
- No buffer/texture cache ownership, GPU scheduler wait, draw ordering, fence handling,
  JIT path, framebuffer lifetime, guest controls, or NS2 loader code changes.

## Trade-off and limitations

More persisted pipelines may move some cold first-use IR / SPIR-V translation **before**
the first guest frame, potentially reducing initial visible hitches. It may also extend
startup and increase temporary compilation memory/CPU use for titles with many saved entries.
No claim of improved FPS, reduced HUD latency, or guaranteed benefit on a cleared cache:
without persisted pipeline entries there is nothing to prewarm.

The current reader takes the first serialized cache entries, not a proven usage-ranked
list. Further quota increases or priority scheduling should use matching console
measurements rather than treating all stutter as shader-first-use latency.

## Validation before merge

1. Run the bounded-prewarm host tests, admission tests, persistence tests, and
   generator parity/build preflight with the pinned vendor submodule commit.
2. Keep the PR separate from ongoing NS2 GMMU/GPFIFO changes; do not merge or build
   on the other conversation's behalf.
3. On a later combined PS5 build, compare warm-cache startup duration,
   `EDEN_PS5_SHADER_PREWARM` valid/queued metrics, FC27 first-match late50/100,
   and in-match residual frame pacing. Check HUD correctness and title switching.
4. Also compare cold-cache launch (0 persisted entries) and one non-FC27 game.
5. Treat per-frame HUD freshness and buffer/texture lock attribution as **OPEN**.
   Do not remove GPU waits/fences or disable texture invalidation to hide artifacts.
