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
