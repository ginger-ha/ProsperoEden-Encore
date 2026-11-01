# Nintendo Switch 2 — NS2JB extracted firmware code dump

**Status (2026-11-01): detection/import supported; native system-service execution NOT supported.** This is not a switch from the established NS1 NCA firmware layout.

## Actual input inspected

The supplied `firmware.zip` is a `ns2jb-system-code-dump`, with
`firmware-dump-named.json`, `ncm-system-programs.bin`, and
`040.../main` (`NSO0`), `040.../main.npdm` (`META`/`ACI0`),
`040.../code-info.bin` per system-program ID.

The `inventory.keys` array has 90 records with `id`, `version`, `type`
and `installType`. These **NCM index keys are not cryptographic keys**.
Every record's ID/version matches one manifest program; every extracted
`main.npdm` ACI0 title ID matches its program ID (90/90). The import and
metadata inventory are usable without `prod.keys`; no titlekey, AES header
key or NCA decryption key is available in this JSON. Existing NCA
decrypt/boot paths still use legitimate `keys/prod.keys`.

The JSON says `complete: true` and `captured: 90`, but those describe the
*dump process*, not an installable or entirely executable firmware:
87/90 have both `main` and `main.npdm`; 3 have `main.npdm`
only, with `main` explicitly absent (result 514):

- `0400000000000837`
- `0400000000000843`
- `040000000000085D`

No NCA archives, NCA Control RomFS, system-version content, or any proof
that all guest services are present can be inferred from this archive.
The importer deliberately does **not** synthesize those missing parts.

## Automatic recognition and import on PS5 (current main source)

**No user-side script or ZIP repackaging is required.** Leave an ordinary
firmware ZIP in a supported family folder. On next launcher initialization,
Encore scans the selected storage root and known family directories, validates
bounded ZIP32 entries, deflates them using the native zlib runtime, checks
per-file CRC and stages the files in a new \`encore-imported-*\` directory.
An invalid archive is rejected and the original ZIP is never modified.
The content folders are resolved again after import.

The console family and the firmware *format* are independent:

| Family | NCA files | extracted NSO/NPDM system code | ZIP |
| --- | --- | --- | --- |
| Switch 1 | recognized | recognized | automatically staged |
| Switch 2 | recognized | recognized | automatically staged |

Supported folder layouts under the selected root include:

\`\`\`text
firmware/*.nca                      # legacy flat NS1
firmware/ns1/  firmware/ns2/
firmware/switch1/  firmware/switch2/
switch1/firmware/  switch2/firmware/
ns1/firmware/  ns2/firmware/
firmware/ns1.zip  firmware/ns2.zip
keys/prod.keys
keys/ns1/prod.keys  keys/ns2/prod.keys
keys/switch1/prod.keys  keys/switch2/prod.keys
switch1/keys/prod.keys  switch2/keys/prod.keys
\`\`\`

An explicitly named family folder can contain NCAs, an extracted dump or a
ZIP. A legacy flat NCA without other family evidence remains NS1 for backward
compatibility; an unlabelled ZIP whose contents do not indicate the family
is not guessed as NS2. Two indistinguishable NCA sets mixed at the same
directory level cannot be separated safely by filename alone; put those into
family-labelled folders. ZIP extraction is a storage operation, **not**
proof of either generation's guest services executing.

For debugging or offline checksum inspection only, the optional host tool
\`tools/ns2/prepare_firmware_dump.py\` still exists. Users should not need it
for an ordinary PS5 installation. ZIP import validates archive CRC/path
integrity; the separate host tool additionally validates the NS2JB manifest's
SHA-256 records.

Keep previously installed firmware, original archives, user keys and game
data unchanged. NCM \`inventory.keys\` describe content indexing, not NCA
decryption keys.

## Runtime boundary

Encore now reports an NS2 system-code dump if the usual firmware NCA
check finds zero NCAs. It **never** substitutes that code dump for
cryptographic NCA validation or reports the native guest runtime ready.
Full extracted-system-module loading needs a verified backend for
module registration, FS data partitions, IPC/service versions and
guest-kernel compatibility; these are not provided by the archive itself.
A green import does not imply either NS2 commercial title boots or a
working Switch 2 HOS.

## ExeFS game art and metadata

For games placed under `roms/<game>/base/exefs/main` with an adjacent
`main.npdm`, the library first uses the existing complete NPDM parser,
then a strictly bounded, symlink-resistant `META`/`ACI0` title-ID
fallback if the parser rejects unfamiliar NS2 metadata. It uses this ID
for cached title data and cover lookup; it does **not** bypass native
loader validation. A game with no usable title ID or an absent catalogue
match still needs a real metadata/artwork source, and `Core load failed`
must be diagnosed separately.
