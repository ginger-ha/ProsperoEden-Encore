# Installing Prospero.Eden Encore

**First time here?** [Four-step start](README.md#start-here--install-in-four-steps) · [18 language/region options](LANGUAGES.md) · [Français](docs/i18n/INSTALL.fr-FR.md) · [Español](docs/i18n/INSTALL.es-ES.md) · [Troubleshooting](TROUBLESHOOTING.md).

This is the **full English installation reference** for ZIP/FTP, FFPFSC/ShadowMountPlus and safe migration from the original native ProsperoEden.

Prospero.Eden Encore targets **PS5 firmware 13.60** and keeps one simple storage contract.

The application title is:

```text
PPSA99008
```

The default storage root is:

```text
/data/prosperoeden
```

## Storage layout

Encore keeps one selected storage root, but **firmware and keys can be arranged flexibly inside it**. The legacy flat layout remains supported:

```text
<root>/
├── keys/
│   └── prod.keys
├── firmware/
├── roms/
├── updates/
├── mods/
├── save-import/
├── save-export/
└── ryujinx/
```

With the default internal root, that means for example:

```text
/data/prosperoeden/keys/prod.keys
/data/prosperoeden/firmware/
/data/prosperoeden/roms/
/data/prosperoeden/updates/
/data/prosperoeden/mods/
```

You can also keep the two console generations separate without a fixed layout:

```text
<root>/firmware/ns1/                # NCA, extracted system dump, or ZIP
<root>/firmware/ns2/                # NCA, extracted system dump, or ZIP
<root>/keys/ns1/prod.keys
<root>/keys/ns2/prod.keys
```

Aliases include `firmware/switch1`, `firmware/switch2`,
`switch1/firmware`, `switch2/firmware`, `keys/switch1`,
`keys/switch2`, `switch1/keys` and `switch2/keys`. Flat
`firmware/*.nca` is treated as NS1 for compatibility. NS2 NCA packages
need an NS2-labelled location rather than guessing by extension. Both
families can have NCA, extracted or ZIP firmware: neither generation is
inferred solely from the file format.

**On-console ZIP firmware import:** copy the original ZIP into a
family-labelled firmware folder (or use a clearly named
`firmware/ns1.zip` or `firmware/ns2.zip`). Encore recognizes and
stages the contents automatically, preserves the original ZIP and does
not require running a Mac/PC helper. Imported system-code inventories
are not a guarantee of compatible NS2 guest services. NCM `keys`
inside JSON are indexing records and cannot replace cryptographic
`prod.keys` for encrypted NCAs.

Application-managed data also stays under `/data/prosperoeden`:

```text
/data/prosperoeden/config/
/data/prosperoeden/logs/
/data/prosperoeden/covers/
/data/prosperoeden/user/
/data/prosperoeden/cache/
/data/prosperoeden/backup/
```

### External storage

You may choose another **root** in **Settings → Storage**.

Only the selected storage **root** changes. The usual standard folders are
created when needed, but the NS1/NS2 firmware and keys layouts above remain
flexible beneath that root.

For example, an external root must still contain:

```text
<external root>/keys/
<external root>/firmware/
<external root>/roms/
<external root>/updates/
<external root>/mods/
<external root>/save-import/
<external root>/save-export/
<external root>/ryujinx/
```

Encore creates the standard subfolders when a valid writable external root is selected.

This is a **single storage root**, not arbitrary paths outside it. Within
that root, firmware and key discovery accepts the NS1/NS2 variants above.

---

## Compressed NSZ and XCZ games

Encore's development branch recognizes four **game container** extensions in the Library:
`.nsp`, `.xci`, `.nsz` and `.xcz`. It also exposes five
**direct native loader** extensions: `.nro`, `.nso`, `.nca`,
`.nax`, `.kip`. Direct files may not be complete bootable games;
the core validates them and reports a loader error when content is missing. You may place them under the same
`<root>/roms/` folder. A game's compressed updates and DLC can be placed
under `<root>/updates/`. This feature is **under native-build and PS5
qualification**, and is not a claim about the current published release.

| | Block compression (often XCZ) | Solid compression (often NSZ) |
| --- | --- | --- |
| Read pattern | Random access directly from the compressed file | A continuous zstd stream; reaching a later offset can require decoding earlier data |
| Space while playing | No full decompressed copy required | May need space for the game's uncompressed contents |
| Cache | Small decompressed block cache | Only the currently used game's unpacked copy plus bounded metadata pieces |
| Cancellation | Ordinary title cancellation | Touchpad + L1 cancels unpack during title loading |

**Extracted ExeFS games:** a deconstructed title may instead be stored as:

```text
<storage-root>/roms/<title>/main
<storage-root>/roms/<title>/main.npdm
<storage-root>/roms/<title>/rtld           (when required)
<storage-root>/roms/<title>/subsdk0        (when present)
```

Encore lists the directory as an **EXEFS** game, validates the two
required files and launches `main` using the native extracted-directory
loader. Do not create symlinks in this layout; incomplete modules or
missing metadata will still prevent a game from booting. Folders outside
`roms/` and nested game directories are not auto-discovered.

The app manages solid decompression under:
`/data/prosperoeden/user/cache/nsz/`. When a game is not running, these
regenerable files may be removed to recover space. Do **not** remove
`user/` itself, the saved games, the installed files, keys or firmware.
If there is insufficient room to unpack, the fallback seeks through the
compressed stream and can be too slow for real-time play. Block compression
is preferable for large games on space-constrained consoles.

**Format distinction:** NSP/XCI/NSZ/XCZ are game containers.
NRO/NSO/NCA/NAX/KIP are direct executable or archive inputs whose ability
to boot depends on their contents. **LZ4**, **ZBIC** and **zstd** are
compression methods used inside executables or NCZ files, not standalone
game file extensions. A `.ncz` is an internal member of an NSZ/XCZ, not
a ROM to launch by itself. The Library picker also accepts NRO, NCA, NSO, NAX and KIP
files through Eden's direct loaders, but they are not guaranteed to be
complete bootable games. Deconstructed-directory input remains a separate
internal loader type.

The program does not provide games, proprietary keys or firmware.

---

<a id="upgrade-from-native"></a>
## Upgrading from the original native ProsperoEden to Encore

**This is an in-place application upgrade, not a second installation.** The original native
[ProsperoEden](https://github.com/blackbearreloaded/ProsperoEden) and Encore use the **same
PS5 title ID, `PPSA99008`**, and therefore normally the same application directory:

```text
/data/homebrew/PPSA99008/
```

The app's **executable files are different from your persistent data**:

| What | Native PS5 path | What to do |
| --- | --- | --- |
| **Application executable / UI** | `/data/homebrew/PPSA99008/` | Replace with the **complete Encore** `PPSA99008/` tree from the chosen release (after backing up). |
| **Keys, firmware, games, settings, saves, caches** | `/data/prosperoeden/` | **Keep; do not delete or overwrite as part of the app update.** Back up before migration. |
| **External storage root** | Your existing selected root | Leave connected and keep its contents; confirm it is selected on first launch. |
| **Legacy native assets** | `/data/homebrew/PPSA99008/assets/` (some older builds) | **Back up first.** Encore may migrate supported user data from this old location *after* startup. |
| **Optional FFPFSC image** | ShadowMountPlus-selected location | Update the image using the FFPFSC workflow below, **not** by unpacking it into the normal folder. |

**Because the title ID is shared, the native project and Encore are not independent side-by-side
apps under the same title ID.** Installing an original native ProsperoEden release over Encore
is not an Encore upgrade and can restore incompatible executable files. For Encore updates, use
[Encore Releases](https://github.com/niakw/ProsperoEden-Encore/releases), not releases from the original port.

### Recommended migration: native folder → Encore folder

1. **Check your source installation.** This procedure applies when the original app is the
   normal folder `/data/homebrew/PPSA99008/`. If it is mounted as an FFPFSC image, see
   [the FFPFSC section](#method-2--ffpfsc-with-shadowmountplus) instead.
2. **Close the original emulator completely** and stop using its files. Confirm that its
   application directory is no longer in use.
3. **Create an offline backup before copying anything.** Save the **whole**
   `/data/homebrew/PPSA99008/` folder **including any old `assets/` directory**, the
   `/data/prosperoeden/` data root, and your external storage root (when used). A backup on
   your PC or another separate drive is preferable. Keys and saves are private: keep them
   under your own control, never share them with a support request.
4. Download the intended **Encore** release from
   [our Releases page](https://github.com/niakw/ProsperoEden-Encore/releases) and verify
   its checksum and device-qualification notes. A green CI artifact is **not automatically**
   a console-tested release.
5. **Inspect the extracted package.** It must contain **one** `PPSA99008/` directory
   holding `eboot.bin`, `sce_sys/param.json`, the complete `ui/` tree and any other
   files from that release. Do not copy only `eboot.bin`; do not create
   `PPSA99008/PPSA99008/`; do not copy the Actions distribution-wrapper directory.
6. Copy the **complete Encore `PPSA99008/` application tree** to
   `/data/homebrew/PPSA99008/`, replacing the original **application files**. **Do not
   remove or wipe the old application directory first** when it may still contain legacy
   `assets/` awaiting migration. An overlay copy can leave obsolete app files: remove
   such leftovers **only after** a successful first launch and after checking the release's
   cleanup notes; never remove persistent data on a guess.
7. Launch **Encore**. Its one-shot filesystem-access request must succeed before it can use
   the selected storage root or attempt a guarded legacy migration. Old user content in
   `/data/prosperoeden/` is reused; supported older `assets/` layouts are considered
   for migration only if they are still present and the preflight checks pass.
8. Verify the Library, storage-root choice, game files, keys, firmware and any relevant
   saves/settings **before deleting any backup or obsolete file**. Keep a working backup
   until you are satisfied with the install.

### What happens to existing data?

- **Already in `/data/prosperoeden/`:** reused in place. This is a persistent data root,
  **not** a disposable cache folder.
- **Old `PPSA99008/assets/` layout:** a guarded migration can move supported legacy
  data toward `/data/prosperoeden/` **only when the old source still exists** and the
  application has sufficient filesystem access.
- **External drive:** Encore preserves a valid existing external root instead of forcing a
  move to the internal drive; folder names remain identical below the chosen root.
- **Migration safety:** unexpected or symlinked entries are rejected, destination conflicts
  do not silently overwrite existing files, moves are preflighted, and failed migration
  attempts try to restore already moved directories.
- **If you deleted the old app folder first:** data stored *only* inside its old
  `assets/` subfolder cannot be reconstructed by Encore. Restore it from your backup,
  **do not** overwrite the current persistent root in the process.

### Updating an existing Encore installation

For an **Encore → newer Encore** upgrade, the procedure is similar: back up your current
`PPSA99008/` app tree and `/data/prosperoeden/` data (and any external root), verify
the new official release, replace the **complete** application tree under the same title
ID, then check games, saves, language files and settings after launch.

**An in-app Encore update checker/installer is not shipped today.** It is specified as
**R21** in the [separate full feature roadmap](https://github.com/niakw/ProsperoEden-Encore/blob/feat/graphics-network-achievements/docs/ROADMAP_ENCORE_COLLAB_2026-10-25.md).
Likewise, newer changes in the original ProsperoEden/Eden repositories are
**not automatically synced** into Encore; they are reviewed and selectively adapted.
Do not use a newer original-native package as if it were an Encore release.

If a problem occurs, first check the correct package/layout and your logs. To roll back,
restore your **saved application folder or image**, not an unrelated upstream build. If
data migration has already changed your saved files, restore only the necessary data
from the **matching pre-upgrade backup** after comparing the paths; a manual rollback
must not overwrite newer saves without your consent.

**Firmware:** **13.60** is the only firmware tested with Encore on a real PS5 and is
therefore the recommended *tested* target. Earlier firmware **may work** with a compatible
homebrew/graphics/filesystem environment, but no minimum firmware is established or
qualified for Encore. This does **not** recommend updating your console just to match
our test firmware. See [the firmware FAQ](README.md#faq) and [technical fork notes](docs/FORK_NOTES.md).
---

## Method 1 — ZIP installation

This is the recommended installation method.

### 1. Download

Download:

```text
Prospero.Eden-Encore-R1.zip
```

The Release also includes `SHA256SUMS`.

### 2. Extract the title

The archive contains:

```text
PPSA99008/
```

Copy the complete folder to:

```text
/data/homebrew/PPSA99008
```

The installation should include at least:

```text
/data/homebrew/PPSA99008/eboot.bin
/data/homebrew/PPSA99008/sce_sys/param.json
/data/homebrew/PPSA99008/ui/
```

Do not copy only `eboot.bin`.

The GitHub Actions **native build and package** run additionally provides an
`Eden-Encore-PS5-FTP-PPSA99008` artifact: extract it once and copy its
`PPSA99008/` folder to `/data/homebrew/`. The `Prospero.Eden-Encore-release`
Actions artifact is instead a **distribution bundle** containing `dist/`
archives and debug symbols; do not copy that wrapper folder to the console.
The in-progress native build checkpoint is now stored in an internal GitHub
Actions cache, not a duplicate downloadable `staged-app` artifact. Historical
runs may still display `Prospero.Eden-Encore-staged-app`; these are not
separate emulator versions and should never be installed.

For a **manual FTP install**, the release also provides:

```text
Prospero.Eden-Encore-R1-FTP.zip
```

This contains only the runtime `PPSA99008/` tree. The complete legal bundle remains in the
normal release ZIP/FFPFSC, while ShadowMount-only `ui/lang/*.txt` companions are omitted from
the FTP variant because the canonical `.po` catalogs are sufficient for an ordinary folder install.

**FileZilla:** force **Transfer > Transfer type > Binary** before copying to a PS5 FTP server.
Some PS5 FTP servers reject ASCII `STOR`, while FileZilla's Auto mode may classify text-like
extensions as ASCII.

The repository's `tools/install-ftp.py` / `make install` path always uses binary `STOR`
and verifies the copied language catalogs.

### 3. Prepare storage

For the default internal layout, place your own files under:

```text
/data/prosperoeden/keys/
/data/prosperoeden/firmware/
/data/prosperoeden/roms/
```

Encore creates the normal folder structure automatically once filesystem access is available.

### 4. Launch Encore

Encore performs its one-shot filesystem-access request during startup, then proves the selected
storage root is actually writable before any migration is allowed to run.

On a clean internal installation, a successful first launch creates:

```text
/data/prosperoeden
/data/prosperoeden/keys
/data/prosperoeden/firmware
/data/prosperoeden/roms
/data/prosperoeden/updates
/data/prosperoeden/mods
/data/prosperoeden/save-import
/data/prosperoeden/save-export
/data/prosperoeden/ryujinx
```

Migration is therefore **not an installation-time operation**. It happens only after Encore itself
has launched and full filesystem access has been proved. If `/data/prosperoeden` never appears,
the startup/access stage did not complete and no legacy migration could have run.

If filesystem access cannot be obtained, Encore remains in its normal PS5 sandbox rather than
pretending access succeeded. External and `/data/prosperoeden` storage will not be treated as
available in that state.

---

## Method 2 — FFPFSC with ShadowMountPlus

The optional `.ffpfsc` contains the same Encore application as the ZIP, packed as a compressed PFS
image for compatible ShadowMountPlus / etaHEN setups.

Download:

```text
Prospero.Eden-Encore-R1.ffpfsc
```

It can be placed in a location supported by your ShadowMountPlus setup, for example a compatible
homebrew/game scan directory on internal or USB storage.

### What FFPFSC changes

FFPFSC changes **how the application itself is mounted**.

It does not change Encore's storage layout:

```text
/data/prosperoeden
```

remains the default storage root unless you select an external root.

FFPFSC does not:

- repair FPKG entitlement/PPR;
- replace kstuff;
- bypass Encore's filesystem-access request;
- change firmware compatibility.

### `TitleDir bridge unavailable`

If ShadowMountPlus reports:

```text
TitleDir bridge unavailable
```

the failure occurs in the ShadowMountPlus/title-registration path **before Encore runs**.

It is not an Encore storage-migration or elevation error.

Use the ZIP/folder installation to validate Encore itself, then troubleshoot the ShadowMountPlus
environment separately.

When migrating an existing ProsperoEden installation, it is safest to complete the first Encore
launch with the ordinary folder installation before switching to FFPFSC.

---

## Verifying the download

Compare the downloaded files with `SHA256SUMS`.

On macOS or Linux:

```bash
shasum -a 256 Prospero.Eden-Encore-R1.zip
shasum -a 256 Prospero.Eden-Encore-R1.ffpfsc
```

---

## Updating Encore

**For both a native ProsperoEden → Encore migration and a later Encore → Encore
upgrade, follow the [backed-up in-place upgrade procedure above](#upgrade-from-native).**
Both use the same application title ID, so do not mix original-native and Encore
executable files. Only the complete Encore application tree should replace the
installed application; the persistent data directory must be preserved.

### Application folder / ZIP

For an official new Encore release, verify its SHA-256 and full
`PPSA99008/` contents, make an offline backup, then replace the complete
`/data/homebrew/PPSA99008/` application files. **Do not delete
`/data/prosperoeden/` or an existing legacy `assets/` directory before
checking the migration.** A copied folder does not itself mean the
migration succeeded: verify library, storage and saves after first launch.

### External storage

Keep the selected external root and its standard subdirectories in place.
Backup and verify it alongside the internal data root when upgrading.

### FFPFSC

Replace the existing Encore `.ffpfsc` image with the official new image,
then remount/rescan using your ShadowMountPlus workflow. Do not mix it with
an ordinary-folder application install for the same title ID without
confirming which one your launcher will execute.

**There is currently no shipped automatic updater.** The proposed R21
feature is described in the [separate collaborative roadmap](https://github.com/niakw/ProsperoEden-Encore/blob/feat/graphics-network-achievements/docs/ROADMAP_ENCORE_COLLAB_2026-10-25.md).

---

## If Encore is set to French but the launcher stays in English

A complete R1 install contains **29** catalog files under `PPSA99008/ui/lang/`, including `fr-FR.po`. On a PS5 set to French, the first setup selects French automatically; changing **Settings → Language** later now rebuilds the launcher immediately so its catalog, fonts and cached labels switch together.

Release builds also ignore the old development-only `language.txt` override. That prevents a stale test file from forcing `en-US` after an update.

For an older/manual FTP installation that stays English:

1. reinstall the **complete** `PPSA99008` folder, including nested `ui/lang/`;
2. remove any old test-only `language.txt` from the application folder if one was left by a development build;
3. prefer `make install PS5_HOST=<address>` — the installer checks all 29 language catalogues by SHA-256 after copying;
4. inspect `/data/prosperoeden/logs/stderr.log`: a healthy French launcher reports a line containing `EDEN_LANGUAGE ... tag=fr-FR catalog=fr-FR texts=...`.

---

## If Encore reports setup incomplete

Check the selected storage root.

For the default internal root:

```text
/data/prosperoeden/keys/prod.keys
/data/prosperoeden/firmware/*.nca
/data/prosperoeden/roms/
```

The launcher validates that:

- `prod.keys` exists and supplies the required keys;
- the firmware folder contains readable NCA files;
- firmware SystemVersion data is present.

If you selected external storage, check the same folders under that external root.

---

## If Encore does not start

1. Verify the release checksum.
2. Confirm the complete `PPSA99008` folder/image is present.
3. Confirm the PS5 homebrew/jailbreak runtime is active.
4. Check Encore's Diagnostics/logs.
5. Use **Safe Launch** for a title that stopped booting after settings changes.
6. Remember that FPKG/PPR and general kstuff problems are outside Encore.

For support, see [SUPPORT.md](SUPPORT.md).

For security-sensitive reports, see [SECURITY.md](SECURITY.md).
