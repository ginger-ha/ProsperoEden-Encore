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
| `headless/game_files.h` | `fe8bc387c8d539ea8c909c6e0ae9a1c6c497844e` | Neuf extensions historiques + `.nup` uniquement derrière le garde P5; ExeFS inchangé, aucune validation GPU |
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

### Revue complémentaire du 3 novembre 2026 — ExeFS mixte

Le nouvel objet `headless/game_files.h` (`dd89d9f9c5c0cde824f41889918f665275c05bdc`) ne modifie que trois sélections d'`exefs`/`base` : reconnaissance insensible à la casse des noms de répertoires exacts (`ExeFS`, `BASE`), sans accepter des préfixes ou les répertoires de mise à jour/DLC comme titres de base. Les contrôles des segments, erreurs de système de fichiers et liens symboliques restent inchangés; `tools/check-exefs-directory-host.py` est le témoin hôte. Cet inventaire reste distinct d'une preuve de lancement PS5.

### Revue complémentaire du 3 novembre 2026 — sélection NUP strictement P5

L'objet source `headless/game_files.h` (`0432c4c2651b2af22343f1401751b3222e30cdc4`) ajoute seulement `IsNupFile()` et ses appels dans `IsGameFile`, `IsNestedGameFileSelection` et `FindNestedGamePackage`. Sans définition de compilation `EDEN_NUP_V1_RUNTIME`, `IsNupFile` renvoie **toujours false** : les neuf extensions historiques conservent leur comportement. En P5 uniquement, les chemins `.nup` deviennent candidats, mais la validation de signature, du VFS et du chargeur reste distincte. Le gate CMake est OFF par défaut et interdit en `EDEN_FINAL_RELEASE_PROFILE`; voir `tools/check-nup-v1-runtime-cmake.py` et `tools/check-nup-v1-game-discovery.py`. Les chemins updates/DLC, symlinks, ExeFS, classement et contrôles de niveaux n'ont pas été modifiés par cette révision. La qualification du sélecteur n'est **pas** une preuve d'exécution d'un jeu NUP sur PS5.

### Revue du 3 novembre — sélections enregistrées d'updates/DLC

Le blob `headless/game_files.h` `d292275239472a9df01205ceabbcd96a2e6a2877` applique désormais **la même exclusion** de noms réservés aux packages rencontrés lors de la découverte et aux chemins de titre déjà enregistrés. Les stems exacts update/patch/DLC/AOC/addon et leurs variantes avec suffixe `_` ou `-` sont refusés comme *base*; les noms de conteneurs AOC/patch sont aussi écartés des racines extraites. Les packages réels sont toujours classés via leurs métadonnées par le provider AoC; aucun routage de DLC n'est supprimé. Un fichier caché `.nsp` ou `.xci` ne peut pas être sélectionné depuis un ancien cache. Les tests hôte `tools/check-exefs-directory-host.py` couvrent la découverte et une sélection persistée, sans changement du chemin NS1 normal, du lecteur NUP P5 ou de la console.

### Revue supplémentaire du 3 novembre 2026 — parcours ExeFS borné

Nouvel objet `headless/game_files.h` : `fe8bc387c8d539ea8c909c6e0ae9a1c6c497844e`. La recherche de l'ExeFS extrait accepte les chemins canoniques `base/Base/BASE` × `exefs/ExeFS/EXEFS` seulement après vérification de chaque composant sans symlink et des fichiers `main`/`main.npdm`. Les dossiers non canoniques restent pris en charge par la recherche récursive existante, désormais bornée à **512 entrées examinées par dossier et 128 sous-dossiers**, refusant un résultat partiel plutôt que d'exposer un candidat dépendant de l'ordre des entrées. Le test hôte `tools/check-exefs-directory-host.py` crée de véritables dossiers contenant plus de 512 fichiers pour vérifier le maintien du chemin standard et le refus du parcours partiel. Aucun changement au moteur Vulkan/JIT, aux formats NUP P5, ni aux workflows PS5.
