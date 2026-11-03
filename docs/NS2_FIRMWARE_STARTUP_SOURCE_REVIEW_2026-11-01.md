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

## Re-revue fonctionnelle P3.4/P1.1 — 3 novembre 2026

**Propriétaire actuel :** `headless/metadata_bridge.cpp` blob Git `4ad21dc591071f8d59097d8a4268a64d9e132138` (commits `c3ef9b5`, `a930437`). Les composants firmware/keys, NUP optionnel, FSP et le chargeur n'ont pas été changés ; seuls les chemins de collecte d'updates et DLC ont été modifiés.

La limite historique de 2 048 dossiers ne publie plus silencieusement les 2 048 premiers résultats lorsque 2 049 titres ou plus sont présents. La lecture racine ne saute plus les erreurs de permission. Un scan local interrompu transmet `complete=false` à l'appelant, qui s'arrête sans appeler `publish(true)`. Un répertoire d'updates/DLC **optionnel et absent** reste permis ; un répertoire **présent mais inaccessible** ou un provider qui ne peut pas l'ouvrir bloque la publication globale. Les liens symboliques ne sont pas suivis. En lancement direct (`main.cpp` blob `62a518af2610297cbd92a5cc5717c76ea8c9c274`), une ROM empaquetée placée directement dans `roms/` ne doit pas émettre d'avertissement de scan de dossier. Les dossiers de jeu valides échangent uniquement des racines additives entières ; leur refus est diagnostiqué explicitement. `tools/check-extracted-aoc-layout-host.py` garde les frontières source du scan et `tools/check-nup-v1-game-discovery.py` vérifie le contrat C++ de complétude.

**Preuves :** modifications source relues et tests ajoutés ; tests d'intégration et compilation hôte de ce SHA non encore qualifiés. Aucune affirmation d'application des DLC en jeu ou de premier framebuffer PS5.

## Transaction de rafraîchissement P3.4 — 3 novembre 2026

Blob source revu : `headless/metadata_bridge.cpp` `e461e758dcd633b58d3e13385eb8fd35c80d336a`, commit `cded90f`. Les metadonnées update/DLC ne sont plus effacées au démarrage de chaque scan. `AddOnScanTransaction` conserve la dernière carte complète pendant la construction privée du nouveau relevé, remplace la carte et le drapeau de validation sous le même mutex uniquement sur `Commit`, puis invalide le drapeau en cas d'échec, y compris sortie anticipée et exception. Leurs trois lecteurs natifs consultent maintenant ce drapeau sous le même mutex, afin qu'un relevé invalidé ne serve jamais de version mise à jour, de langue ou de compteur DLC. La destruction de l'ancienne carte intervient après le verrou. Le scanner de titres conserve son verrou de sérialisation.

Témoins hôte ajoutés : `tools/check-extracted-aoc-layout-host.py` compile la véritable classe transactionnelle extraite du propriétaire sous Clang/GCC O0/O2; `tools/check-addon-snapshot-host.py` teste trois lecteurs concurrents contre 3 000 publications et refus simulés. Le contrat `tools/check-glyph-overrides-runtime.py` et la recherche ExeFS suivent l'API courante plutôt que l'effacement historique. Le harnais local isolé équivalent (Clang/GCC O0/O2) est vert ; la suite complète du dépôt avec dépendances de vendor et PS5 demeure à qualifier. Aucun changement du chemin graphique ou des commutateurs P5.
