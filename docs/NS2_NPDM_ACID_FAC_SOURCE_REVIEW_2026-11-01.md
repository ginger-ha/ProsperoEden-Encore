# Extracted NPDM ACID/FAC diagnostic — source re-review

Current source: `headless/extracted_npdm_identity.h`, blob `d740d94e1423600c1782e91792f1cbd803945dc0`.
Prior reviewed blob: `116e1d4bb7181c0f44e1910f5f8f1eb53ca14a61`.

The only new component is `Eden::ExtractedNpdm::ProbeAccess`:
- Reads a regular, symlink-free NPDM file bounded to 1 MiB; verifies META header.
- Detects both Switch 1 0x200-byte and Switch 2 0x300-byte signature/key prefixes and checks the ACID header at their distinct offsets, without assuming the game generation from its title ID.
- Reports bounded FAC offset and length, rejects out-of-region FAC requests and distinguishes the header and format states.
- Returns a diagnostic record only. **It does not grant filesystem capabilities, override kernel ACID validation or make NS2 guest services executable.**
- The previously reviewed `TitleId` read-only ACI0 parser is unchanged.

`tools/check-ns2-extracted-inputs-host.py` extracts this actual production header and compiles/runs NS1 ACID, NS2 extended ACID, invalid FAC and ACI0 identity fixtures. Its CI registration remains the historical U87 source proof.

This is an audit receipt for a source change, not a speed improvement, PS5 native success, or an NS2 first-frame claim.

## Registered source-owner audit row

| Source owner | Disposition | Evidence limit |
|---|---|---|
| `headless/extracted_npdm_identity.h` | Source-reviewed 2026-11-01 | No FPS or console first-frame claim |
