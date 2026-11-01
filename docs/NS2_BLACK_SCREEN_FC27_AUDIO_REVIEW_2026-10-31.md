# Hardware incident / source review — PS5 NS1 audio crash and NS2 extracted titles (2026-10-31)

Source-review scope: `headless/metadata_bridge.cpp` (blob `9c3ca3d1378eb901726652a1bbc5e28f74601851`),
`headless/prosperoeden/eden_services.cpp` (blob `85a20128ec98c7c039538dd8f5671a8448aadb83`). No GPU/JIT optimization
or FPS claim is made, and this document does **not** close the native hardware regression.

## Confirmed observations from owner-provided Oct 31 PS5 logs (build 46aaa92e)

- FC27 base 0100C49025D3E000 loads, Vulkan RADV initialises, then two crashes with
  **identical** SIGSEGV PC eboot+0x321b83, fault address 0x10 on the thread named
  `audio`, after 273s and 35s. Both logs have GPU hang counter 0. The exact
  function cannot be established without the matching unstripped ELF / link map.
- Two extracted NS2 selections launch with `title_id=0`; native NSO files load,
  rendering surface initialises and submits, but the screen remains black. The
  previous metadata reader tried the bare `main` file instead of `main.npdm`.
  This explains **missing metadata/cover lookup** and game profile identity,
  but does not prove why guest frames are absent.
- `EDEN_PROFILE_AVATAR format=png status=found` appears repeatedly in the
  observed logs. Path discovery succeeded. A missing on-screen avatar must be
  diagnosed at the **image decode/texture/UI rendering** stage, not blamed on
  a missing foreground cache. User ID 0 acceptance is still a valid boundary fix.

## Revised source contracts

1. Extracted title lookup: `ReadExtractedProgramMetadata` reuses the engine's
   `FileSys::ProgramMetadata` parser and enforces `IsSafeDeconstructedGamePath`.
   It reads the nearby `main.npdm`, refuses path escapes/symlinks and does
   not synthesize a Title ID from directory names. NSP/XCI handling remains
   on its existing loader path. The short NPDM name is not treated as localized
   NACP metadata; Nlib enrichment is keyed only by an actual Title ID.
2. Extracted title footprint: `ExtractedBaseBytes` counts base-owned files
   with symlink rejection, bounded depth/entries and cancellation. It skips
   `updates` and `dlc` subtrees, and reports unknown size rather than claiming
   the NSO `main` file represents a complete game. Ordinary packaged file
   size logic remains unchanged. `ExtractedLocalCover` is an optional local
   image fallback with the same no-symlink and 16MiB bound.
3. Avatar: foreground-user ID 0 is permitted (the NiakPS5 broker accepts
   nonnegative IDs); a failed lookup still never enumerates other users.
4. Host test: `tools/check-exefs-directory-host.py` extracts the real base
   scanner and local cover helper. GCC and Clang O0/O2 + UBSan passed in
   GitHub source-early run 41212890935 before the stale optimization-inventory
   blob assertions stopped the job. This review updates only those source
   hashes, not historical F07 conclusions.

## Remaining work / explicit non-qualification

- Reproduce and symbolize eboot+0x321b83 with a **matching** PS5 native
  `llvm-pie.elf` and `link.map`; do not assert audio root cause or change
  shared engine code based only on the thread name.
- Keep NS2 experimental flags out of shipping NS1 defaults; all-on research
  compilation is not proof of NS1 gameplay regression-free behavior.
- Verify extracted Title ID on actual console, and trace NS2 first guest
  frame, CPU scheduler, NVDRV channels and GPU submit for black screens.
- Verify profile PNG decoded/uploaded into the avatar texture on PS5.

## Addendum 2026-11-01 — owner-bound avatar decode fallback

The 2026-10-31 reviewed `eden_services.cpp` blob `85a20128ec98c7c039538dd8f5671a8448aadb83` was modified **only** in commit `7136f8af02cd` (36 changed lines), producing blob `ea91caf2d586d4be5550214912c08abab7429c5e`. The change makes `IsDecodableAvatarFile` reject a readable but invalid PNG, checks bounded image dimensions through stb_image, and attempts the **same foreground user's** matching DDS when the PNG cannot decode. The PNG and DDS staging owner-marker checks remain required, and no cross-profile enumeration was added. This is a source-only re-review based on the exact patch; successful appearance of an avatar on a PS5 remains **unverified**. The historical 26 October launcher performance disposition is unchanged.
