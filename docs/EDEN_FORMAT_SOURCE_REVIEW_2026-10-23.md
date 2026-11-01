# Revue source : support des formats, distincte de F01–F06

**23 octobre 2026 — branche unique `dev/ps5-sparse-jit`.**

L'ancien instantané de couverture affichait 493 sources maintenues.
L'arbre Git actuel comporte **504 fichiers C/C++/en-têtes** dans
`headless/`, `src/` et `vendor/encore-active/`. Les onze sources
supplémentaires sont précisément dix unités de sélection/lecture de
conteneurs (ci-dessous) et
`headless/prosperoeden/pe/ui/case_media_selection.hpp` (interface UI
distincte). La revue physique de ces chemins évite d'en faire une
fausse dette d'optimisation JIT/GPU.

## Dix unités nouvelles de lecture/chargement

| Source | Git blob exact | Rôle et portée |
| --- | --- | --- |
| `headless/game_files.h` | `47f2bab4476796c0a54e8e91f7a94faec57b868f` | Sélection et validation des neuf extensions et de l'ExeFS; sélection de titre, pas du frame GPU |
| `headless/ncz.cpp` | `7deff2ea1a82574b9e756ad9c2f0d869aa94612b` | Adaptateur de lecture NCZ et cache, sélectionné par CMake |
| `headless/ncz.h` | `85ced3460d83be2a8011f189c0df406b4dd32b8c` | Décompression NCZ, limites et protection du cache |
| `headless/ncz_check.cpp` | `65c9e5f4eb3625140add52ced2ea82e66bd224ab` | Harnais de vérification hôte; jamais un composant de rendu |
| `headless/ncz_vfs.h` | `176d89e5d385fe140211350ab4c20a38f1f496bd` | Pont VirtualFile utilisé par les sources NCZ maintenues |
| `vendor/encore-active/eden-core/src/core/file_sys/card_image.cpp` | `f843e7f9c977b509368e71eb6356066c1a5e0c50` | Lecteur de partition cartouche NCZ, source maintenue sélectionnée |
| `vendor/encore-active/eden-core/src/core/file_sys/registered_cache.cpp` | `618ff99d2121741c190a9fd3ae8d0fd45f7eb9fe` | Détection NSZ/XCZ des contenus enregistrés |
| `vendor/encore-active/eden-core/src/core/file_sys/submission_package.cpp` | `29a46a6024cad1e867ac450a0bd651bebc1f0b29` | Ouverture NCZ comme archive de contenu d'un package |
| `vendor/encore-active/eden-core/src/core/loader/loader.cpp` | `7943b817dfa8118b150c4970d6513ec179262af0` | Routage des extensions au chargeur natif et NAX |
| `vendor/encore-active/eden-core/src/core/loader/nsp.cpp` | `b56195d24778a849bb768d463fdf4ceef3d5c33f` | Détection des membres NCZ d'un NSP/NSZ |

## Garanties et limites

- Les cinq sources complètes `vendor/encore-active/eden-core/src/core/`
  ont une reproduction octet à octet depuis les sources Eden épinglées,
  vérifiée par `tools/check-encore-ncz-sources.py`, y compris le
  correctif NAX du routeur. `headless/CMakeLists.txt` les sélectionne à
  la place de leur traduction épinglée.
- `headless/ncz.cpp` est sélectionné par CMake. `ncz.h` et
  `ncz_vfs.h` sont des en-têtes de l'adaptateur et des lecteurs NCZ.
  `ncz_check.cpp` est un **test hôte uniquement**. Les preuves sont
  `tools/check-ncz.py`, `tools/check-encore-ncz-sources.py` et
  `tools/check-exefs-directory-host.py`.
- `game_files.h` borne les types de conteneurs et refuse les layouts
  ExeFS traversant des répertoires. Le chargeur natif décide finalement
  si le fichier sélectionné est réellement exécutable.
- La compression/décompression NCZ peut devenir un coût d'I/O pour un
  titre NSZ/XCZ, mais **les anciens essais FC27 en conteneurs classiques
  ne démontrent aucune contribution de ces sources aux saccades**.
  Aucun cache GPU, shader, commande Vulkan, boucle HID ou JIT n'est
  modifié par l'inscription de cette revue.
- L'inscription dans le registre signale `format_feature_source_integrated`,
  **jamais FPS optimisé**. Les empreintes ci-dessus sont contrôlées en CI
  et toute modification forcera un réexamen.
- Le nombre des six objectifs F01–F06 clôturés demeure **0/6** ;
  aucune preuve console n'est créée ici. La source UI supplémentaire
  reste dans le périmètre UI, sans être comptée parmi les dix unités
  moteur revues.

Références : `docs/CONTENT_FORMAT_MATRIX_2026-10-23.md` et
`docs/FC27_EXIT_GATES_2026-10-22.md`.

## Revue complémentaire du 31 octobre 2026

Les deux sources ci-dessus ont été revues et leurs blobs repinnés suite à
l'intégration des layouts extraits/paquetés. `game_files.h` conserve le rôle
de sélection à froid ; `registered_cache.cpp` conserve le support NCZ
avec un second écart strictement audité : ne pas traverser les arbres
`romfs`/`exefs` extraits lors du scan NSP/XCI d'updates/DLC.
Les correspondances source attendues sont vérifiées dans
`tools/check-encore-ncz-sources.py`. Le détail des huit propriétaires
modifiés et leurs risques figure dans
[`FLEXIBLE_LAYOUT_INTEGRATION_SOURCE_REVIEW_2026-10-31.md`](FLEXIBLE_LAYOUT_INTEGRATION_SOURCE_REVIEW_2026-10-31.md).
Aucune validation console ou clôture d'optimisation F01–F07 n'est déduite.

### 31 October — flexible package add-on folders

The selector now discovers NSP/NSZ/XCI/XCZ add-ons in arbitrarily named
nested wrapper directories (e.g. `custom/extensions/bonus.nsp`), not only
under literal `updates/` or `dlc/`. It never regards the selected
base package as add-on content, rejects symlinks and does not recurse
into extracted RomFS/ExeFS payloads. The detected paths are passed to
the metadata-aware native content provider. Host source regression is
tracked by `tools/check-exefs-directory-host.py`; see
`docs/FLEXIBLE_LAYOUT_INTEGRATION_SOURCE_REVIEW_2026-10-31.md`.

A mixed title folder with exactly one XCI/XCZ and other NSP/NSZ content
selects the unique card image as its base. Multiple candidate card images
or anonymous NSP-only mixtures still fail closed rather than guessing.

## Addendum 2026-11-01 — ExeFS-first identification

The loader's reviewed source is now blob `7943b817dfa8118b150c4970d6513ec179262af0`. The exact source-owner gate reconstructs the maintained file from pinned Eden, plus existing NSZ/XCZ and NAX handling, and the explicitly reviewed first-choice `AppLoader_DeconstructedRomDirectory` for a file named `main` that actually belongs to a valid ExeFS directory. Standalone NSO files continue through the generic NSO detector. This avoids treating an extracted program with `main.npdm`, `rtld` and `sdk` as an isolated `main` NSO; no claim is made that Bananza gameplay boots or that Switch 2 emulation is complete.
