# PS5 consolidated NS1/NS2 source build — 2026-11-01

This [full-build] marker validates the current *single native release* binary
after the memory/GSV integration and the exact source-overlay correction.

## Native shipping source under test

- NS2 ExeFS program identity and per-title 12 GiB guest layout; restore user
  NS1 profile after kernel shutdown or direct title transition.
- Kernel GPU memory SVC 0x80 uses real per-process page-table attribute
  persistence. The 0x20 GPU-accessible bit is exposed consistently by the
  maintained kernel memory types and is guarded by exact NS2 PID identity.
  That identity is cleared before every new title and after shutdown.
- Audio service aud:u and stream-play stpl:u are additive to NS1 services.
- The corrected SVC type header is derived from the **installed**
  `vendor/encore-active/eden-backports/src/core/hle/kernel/svc_types.h`,
  retaining `InfoType::Unknown37` and `Unknown38` needed by
  `svc_info.cpp`. The previous native run 41274607620 failed to compile
  because the original NS2 overlay copied an older header without those
  members. This candidate checks the actual native compiler result.
- F07 exact-source owner checks remain mandatory.

## Research-only sources (not shipped or proven)

The native 4 KiB GMMU worker now requires an actual GPU-accessible kernel
memory attribute. The isolated GraphicsSupervisor has bounded native-memory
object commands 111, 112 and 114 and reviewed image sizing commands 435 and
1510. Its pure C++ protocols are checked by source-linked host CI under
O0/O2 UBSan. The research GSV / native 4 KiB NVDRV / Ampere GPU service /
VI2 presentation remain disabled for this single public release.

A successful native compilation is **not** a proof of DK Bananza first frame,
Mario Kart World rendering or NS2 gameplay. No PS5 console re-test should be
requested until there is a new coherent native GPU runtime candidate.
