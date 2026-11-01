# Extracted NS1/NS2 library metadata and media — source re-review

Source: `headless/prosperoeden/eden_services.cpp` @ `df7d8af3f674d43f8c6596a62263a3234ca6dab8`.
Prior reviewed F07 source blob: `ea91caf2d586d4be5550214912c08abab7429c5e`.

The recent source changes do **not** change the proven `LocaleCaseCandidates` dedup implementation. These are launcher discovery and media changes, not GPU or JIT optimizations:

- Extracted base game identity and offline NS2 retail metadata are keyed by the title ID, not the user's folder name. A fixed allowlist of product hosts/paths is used only by the existing image worker, with size/dimension, cancellation, retry, TGA conversion and atomic filename constraints. A successful cover download does not imply that NS2 gameplay boots.
- Extracted `control.nacp` sidecars read only the historical 16-slot, uncompressed format, bounded to 0x3000–0x20000 bytes; parent traversal and symlinks are refused. Name and developer strings are checked as UTF-8 and prefer the user's launcher language with an English and remaining-language fallback; no encrypted NCA parsing or guest authority is inferred.
- ExeFS `icon_<language>.dat` JPEG/PNG sidecars are selected from a bounded language-name list at safe locations. Intermediate directory safety, file type, file size and JPEG/PNG magic bytes are checked; unrelated binary `.dat` blobs are never treated as covers.
- Late real front-cover completion updates the game tile only when its cover is missing. Existing cover priorities and the NS1 path remain intact.
- The PS5 staged avatar fallback and case-index dedup previously reviewed in F07 are not removed or reclassified.

**Independent source-linked host checks:**
`tools/check-exefs-directory-host.py` (real NACP/icon path extraction, English/French, symlink/corrupt-file coverage);
`tools/check-ns2-title-catalog-host.py` (allowlisted cover and title fallback);
`tools/check-release-case-index-dedup-host.py` (historical F07 optimization witness).

This refreshes the historical source fingerprint while retaining the existing `new_source_issue_corrected` disposition and original proof. No PS5 frame-time, local avatar appearance, playable NS2 game, or first rendered Switch 2 image is proven.

## Registered source-owner audit row

| Source owner | Disposition | Evidence limit |
|---|---|---|
| `headless/prosperoeden/eden_services.cpp` | Source-reviewed 2026-11-01 | No FPS or console first-frame claim |
