# PS5 Vulkan alias copy — publish freshness after successful submission

## Verified source-level failure mode

`TextureCache::SynchronizeAliases`, in the maintained Vulkan `texture_cache.h`, gathers newer GPU image aliases, sorts them by `modification_tick`, and calls `CopyImage` to bring an older destination up to date. Before this change, it wrote the newest source revision to `image.modification_tick` and marked `GpuModified` **before** the copies had been recorded. `CopyImage` enters Vulkan runtime copy/emulation/reinterpret/convert paths that may throw or reject a copy.

On a failure after one earlier source copy, the destination could retain an incorrectly up-to-date revision and suppress later alias synchronization. This is a concrete stale-image retry failure mode, although the November 1 FC27 logs do not prove that this exact failure was responsible for its HUD lag.

## Corrective behavior

- **PS5 only:** keep the destination's previous revision and `GpuModified` publication until all selected alias-copy calls complete.
- The original monotonic sort and copy order are unchanged. If any copy throws, the caller still observes the same exception; a subsequent guest draw sees an older destination revision and can retry.
- **Desktop unchanged** (original eager publication retained within `#ifndef PS5_NATIVE`).
- No discarded Vulkan work, GPU wait removal, framebuffer backpressure changes, image ID reuse or NS2 runtime changes. This is not a generic way to recover from device loss and does not guarantee completion of a driver-side GPU execution after successful queueing.

## Executed-source regression

`tools/check-fc27-f04-native-dma-alias-bytes-host.py` already extracts and compiles the production `SynchronizeAliases` method alongside an actual DMA source fragment and CPU invalidation. The extension injects an exception **after the first source copy** of two sorted aliases, asserts that neither the destination tick nor its GPU-dirty flag is published prematurely, then retries successfully and compares the destination pixel bytes. It runs PS5 source at `-O0` and `-O2` under UBSan.

The generator `tools/prepare-vulkan-port.py` reproduces the exact edited vendor source via two reviewed deltas. Host validation proves a reproducible failure-before/success-after property only; console HUD content/freshness, performance and real Vulkan driver behavior still require the consolidated PS5 test.
