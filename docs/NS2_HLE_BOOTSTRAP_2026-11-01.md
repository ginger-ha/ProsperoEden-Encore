# Switch 2 native bootstrap — HLE/core integration (2026-11-01)

## Consolidated shared PS5 release source

- **Process + kernel:** detect NS2 from parsed ExeFS main.npdm before kernel initialization. Select 12 GiB guest layout per NS2 title, bound SetHeapSize by intended guest RAM and extend only the 12 GiB profile's *virtual* heap range to 16 GiB. These changes do not eagerly allocate 16 GiB of PS5 RAM.
- **Audio:** additive aud:u commands 1 and 2 return actual maintained IAudioOutManager and IAudioRendererManager interfaces. Existing audout:u, audren:u, audin:u, audctl and hwopus registrations are retained for NS1.
- **Stream play:** additive stpl:u command 0 returns an object; its command 300 returns a real kernel event, with balanced event creation and closure. Other GameShare/streaming functionality remains unsupported.
- **GPU characteristics:** exact native NVDRV IOCTL adapters are additive. Full GPU session, worker, GMMU/GPFIFO, Ampere shader, VI2 presentation and GPU budget adaptations remain research only.
- **Loader diagnostics:** bounded 10s/30s Vulkan loading notices are distinct from an actual game frame.

Provenance: Djihads80/Eglantine nx2 and 0x2593/Eden-NS2, selectively adapted to the maintained Encore PS5 vendor source. Do not apply broad upstream patches without source/ABI review.

## Verification limits

Host source tests guard source selection, ABI intent, event lifetime, NS1 service preservation and historical F07 inventory separation. A green native build proves compilation only. The recorded Donkey Kong Bananza console state is guest CPU bootstrap with persistent black screen; **first rendered game frame is still unproven**. No NS2 gameplay compatibility claim follows from these integrations.

This one `[full-build]` candidate tests consolidated source buildability. Do not request separate PS5 installations for each fix.


## Consolidated GPU-memory correctness and NS1 handoff

- NS2 `SVC 0x80` is no longer a success-only admission stub: it validates the exact registered NS2 PID, address/size, GPU attribute mask and real guest page-table range before setting or clearing bit `0x20` with `KPageTableBase::SetMemoryAttribute`.
- The shared maintained kernel headers expose `GpuAccessible` identically to the SVC dispatcher, kernel page table, and memory queries; NS1 SVC IDs and existing user permissions are unchanged.
- The NS2 12 GiB guest profile is temporary: after kernel shutdown or an NS2-to-NS1 title transition, the original memory layout and global/custom setting selection are restored.
- The host source gate checks real mutation, cross-unit header selection, invalid input statuses, and memory profile restoration. Full native compilation must still confirm ABI and linkage.
- This candidate intentionally **does not** enable the experimental 4 KiB NVDRV GMMU path or native Ampere GPU worker, so a black-screen NS2 game remains possible.

The validated initial native HLE/memory bootstrap build was run #41273218088 at revision 32433db9. This follow-up full-build marker requests a single newer native build including the fixed GPU attribute persistence and NS1 restoration, not a PS5 gameplay pass.
