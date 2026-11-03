# Metadata bridge firmware source review — 2026-11-01

Review target: `headless/metadata_bridge.cpp` Git blob `83b2b12f48be609520f28c23e0722a55b57597f4`.
Previous F07 reviewed blob: `9c3ca3d1378eb901726652a1bbc5e28f74601851`.

## Actual changes since the old source audit

- Adds `extracted_npdm_identity.h` and `firmware_zip_import.h` to the launcher-facing metadata bridge.
- Automatic ZIP import searches 19 bounded NS1/NS2 firmware roots, including top-level firmware ZIPs. A candidate archive must be a regular non-symlink ZIP; selection is bounded to eight archives per root.
- Explicit NS1/NS2 labels or extracted metadata determine archive family. Ambiguous mixed/unknown archives are rejected rather than silently labelled NS2. Flat NCA-only legacy ZIPs retain the NS1 fallback.
- The importer avoids overwriting an existing destination and checks untrusted parent paths against `Eden::StorageDirectory`. The real importer enforces ZIP entry safety/CRC/size limits and must complete atomically.
- Startup separately identifies NS1 and NS2 firmware and keys. Extracted NS2 NCM discovery is read-only and **not** evidence that the NS2 guest OS services can boot. Encrypted NCAs still require real key validation; NS1 NCA SystemVersion validation remains in place.
- The implementation does not touch Vulkan, command submission, shader compilation, NS1 performance policy, or guest SVC handling.

## Source-linked host evidence

- `tools/check-firmware-auto-import-host.py`: source-extracted import scanner exercised with NS1/NS2 ZIPs, preservation of inputs, and repeat import.
- `tools/check-firmware-zip-native-host.py`: real native ZIP importer CRC, extraction, directory, symlink/no-overwrite and traversal cases.
- `tools/check-firmware-matrix-host.py`: source-linked independent NS1/NS2 firmware/keys resolver, format and root symlink boundaries.

This review **updates only the source blob identity** in the historical F07 ledger: contract U13 remains reviewed without a new optimization. No PS5 FPS, NS2 frame, or decrypted NS2 runtime claim is made. Re-review any subsequent source edit.

## Registered source-owner audit row

| Source owner | Disposition | Evidence limit |
|---|---|---|
| `headless/metadata_bridge.cpp` | Source-reviewed 2026-11-01 | No FPS or console first-frame claim |

## Réévaluation du 3 novembre 2026 : métadonnées NUP strictement sous P5

La révision `headless/metadata_bridge.cpp` `83b2b12f48be609520f28c23e0722a55b57597f4` ajoute `PreferredNupLocale`, la lecture d'identité, de titres localisés, d'icônes bornées à 4 Mio et de langues NACP pour des conteneurs NUP. **Toutes** les nouvelles branches exécutables sont encapsulées dans `#ifdef EDEN_NUP_V1_RUNTIME`; un simple include `<string_view>` est ajouté hors garde. Les chemins de métadonnées habituels NSP/XCI et les recherches de firmware/keys NS1 et NS2 restent inchangés dans cette révision. Le CMake `nup_v1_runtime.cmake` garde la sélection OFF par défaut et la refuse au profil final ; `eden-metadata` n'obtient la définition que sous ce sélecteur P5. Ce contrôle de diff ne vaut ni compilation intégrale PS5, ni validation du NUP en jeu, ni qualification du décodage d'images sur console.
