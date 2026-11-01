# PS5 Vulkan — bounded inactive presentation-layer retention (2026-11-01)

## Source finding

In `BlitScreen::DrawToFrame` (PS5), an ordinary change in the number of Nvnflinger presentation layers already grows the `std::list<Layer>` without an idle. A **decrease** previously triggered `WaitIdle(device)`, deleted all layers and rebuilt exactly the smaller count. A subsequent increase then had to create new layer resources. This is a plausible source of intermittent stalls when a title adds/removes transient UI layers, but the FC27 November 1 logs do **not** identify a layer-count transition in either residual stutter window. **No measured FC27 FPS or HUD gain is claimed.**

`WindowAdaptPass::Draw` uses `configs.size()` as the draw count, advances `layer_it` only across those active configs and records only their descriptor sets. Therefore extra inactive `Layer` objects can remain in the list without being rendered or referenced by that frame.

## Change

- PS5 only: keep a high-water reserve of at most **8 inactive/reusable layer identities** without an idle when the active guest layer count decreases.
- The limit is on **retained owner count during a shrink**, not the number of active guest layers. If a title needs 9+ simultaneous layers, all are created and drawn. When it later shrinks, owners above 8 are retired via the original `WaitIdle` and rebuilt to the exact active count.
- Rebuild with original device/queue synchronization when swapchain image count, descriptor/layout contract or format changes, or FSR/SGSR output-sensitive window dimensions change.
- No draw skipping; no change to guest textures, CPU memory invalidation, Vulkan fences, wait ordering or NS2 GPU logic. Desktop path unchanged.
- Tradeoff: up to 8 layers and their per-swapchain resources may remain allocated while fewer are active. Capacity is reclaimed on layout rebuild/teardown, or on over-budget shrink.

## Host qualification

`tools/check-ps5-f07-present-layer-growth-host.py` extracts the **actual** native/desktop conditional decision and compiles it at O0/O2 under UBSan. The fixture covers grow → shrink → re-grow without idle, unchanged layer identity, forced contract rebuild, FSR/SGSR rectangle changes and a 9 → 8 → 2 → 8 bounded sequence. The test also checks the source of `WindowAdaptPass::Draw` consumes only the active `configs.size()` entries.

The native source generator emits the same changed decision. CI parity and full build remain necessary; **PS5 hardware verification is not inferred** from a host test. Please combine any PS5 comparison with the main release/NS2 functional testing rather than requesting another standalone FC27 install.
