# Eden Encore — source de vérité unique des overrides

**Règle impérative :** tout correctif ou variante de source d'une
dépendance doit vivre dans **`vendor/encore-active/`**, sous forme
de source complète, d'en-tête complet ou de donnée maintenue. Le compilateur
ne doit sélectionner qu'un propriétaire de code. Les sources originales
sous `vendor/sources/` restent immuables.

Le rôle de `headless/CMakeLists.txt`, `headless/*.cmake`, `tools/`,
`Makefile` et `.github/workflows/` est d'assembler, sélectionner,
installer et **vérifier** — pas de conserver la correction C++ concurrente.
Les scripts de replay de patches sont des oracles historiques, pas
une autre source de vérité. Les scripts d'installation peuvent copier les
fichiers maintenus et refuser toute dérive SHA, mais pas inventer de
nouveaux corps C++ destinés à la console.

## État concret au 27 octobre 2026

- `vendor/encore-active` : **337 sources et en-têtes suivis** (hors 107 unités NS2 expérimentales), dont 335 avec IDs de graphe et 2 en-têtes d'hygiène partagés possédant un garde de provenance et un installateur dédié. Le snapshot Eden original reste immuable. Couverture documentaire, **pas** validation console.
- `headless/CMakeLists.txt` : **1 générateur** `write_derived`.
- Le module CMake expérimental de pont différé contient **0 générateurs**
  `write_derived`, soit **1 site** au total.
- Aucun module actif ne procède encore aux substitutions **indirectes**
  de C++ recensées. X06 est conservé comme oracle sous `tools/fixtures/`.
- `headless/` contient **2 fragments `.inc`**, tous deux diagnostics GPU
  de l'application (l'un inclus transitivement). L'ancien diagnostic
  OpenGL DEV a été déplacé sans réécriture dans `encore-active` et est
  inclus exclusivement par le rasterizer DEV maintenu.
- Les fichiers `src/`, `third_party/`, `assets/`, `data/`,
  `fixtures/` et `sce_sys/` sont distincts : code natif original,
  contrats ABI, ressources ou tests. Ils ne sont pas automatiquement
  des corrections aux dépendances. Toute future transformation de source
  découverte dans ces répertoires doit rejoindre `encore-active`.
- `tools/build-headless-host.sh` (FFmpeg hôte),
  `tools/materialize-openssl-cert.py` (certificats),
  `tools/build-radv-dependencies.sh` (ccache Meson temporaire) et
  `tools/build-opengl-sdk.sh` (test hôte provisoire) restent des
  transformations de **build/ressource**, à qualifier séparément des
  overrides C++ ; elles sont documentées dans
  `EDEN_OVERRIDE_MIGRATION_INVENTORY.md`.

Le contrôle `tools/check-active-cmake-source-boundary.py`, intégré à la
prévalidation hôte, explore récursivement les modules CMake actifs de
`headless/` et `vendor/encore-active/` : aucun ne peut désormais
réintroduire `file(WRITE)`, `string(REPLACE)`, `execute_process` ou
`write_derived` pour fabriquer du code. Le seul appel autorisé du
CMake racine demeure G23 (en-tête de ressource GLSL).
Le script vérifie aussi que `prepare-vulkan-port.py` reste un ancien
outil de reconstruction pour les tests, jamais invoqué dans les chemins
de compilation native. Cette preuve couvre les frontières de build
énumérées, pas l'exécution effective sur console.

## Recensement des modules CMake hors CMake principal

<!-- SINGLE_SOURCE_CMAKE_START -->
| Fichier | Nature | Position |
| --- | --- | --- |
| `headless/dynarmic/reg_alloc.cmake` | Sélection/copie de deux sources Encore maintenues | Sélecteur conforme |
| `headless/dynarmic/shared-jit.cmake` | Sélection/copie de trois fichiers Encore complets | Sélecteur conforme ; M01–M03 retirés |
| `headless/gpu_native_observability.cmake` | Sélection de sources Encore maintenues | Sélecteur conforme |
| `headless/guest_write_deferred_bridge.cmake` | Sélection de six variantes expérimentales maintenues | Sélecteur conforme ; M12 retiré |
| `headless/inject.cmake` | Orchestration ou toolchain | Sélecteur / configuration |
| `headless/jit-alias.cmake` | Sélection/copie de l'en-tête Xbyak et de ConstantPool complets | Sélecteur conforme ; X09 retiré |
| `headless/nup_v1_runtime.cmake` | Sélection des sources NUP v1 et des propriétaires AoC/RomFS existants | P5 uniquement, OFF par défaut, interdit en release finale ; aucune génération C++ |
| `headless/ps5.cmake` | Orchestration ou toolchain | Sélecteur / configuration |
| `headless/scalar-memory.cmake` | Sélection des émetteurs vectoriel et data processing maintenus | Sélecteur conforme ; X08 retiré |
| `headless/vulkan.cmake` | Sélection/copie de sources Encore maintenues | Sélecteur / configuration |
<!-- SINGLE_SOURCE_CMAKE_END -->

## G13/X05/M12 : unité native complète

Les deux sources `memory_native_{standard,a32}.cpp` sont versionnées et
choisies directement depuis `eden-core/src/core`, sans génération ni
substitution de C++ dans CMake. La cible `core` retire explicitement la
source préexistante et conserve `PS5_NATIVE=1` sur l'unité compilée.
M12 choisit les variantes DEV complètes `guest-bridge/memory_ps5_*.cpp`
uniquement si le pont expérimental est activé ; aucune fonctionnalité
n'autorise son activation en production. X05 n'est plus inclus au build.
Les anciennes recettes CMake sont des oracles confinés à `tools/fixtures`.
Parité historique hôte et sélection sont distinctes de la validation PS5.

## Core::System G14 maintenu

Les variantes normale et native du cœur de système sont suivies comme
fichiers entiers sous `eden-core/src/core/core_{standard,native}.cpp`.
CMake ne garde que les deux sélections et la copie, et n'injecte plus
les corps de shutdown/loader/IPC ; le témoin hôte rejoue exactement les
transformations historiques dans les deux modes, sans prétendre à une
qualification matérielle.

## Chargeur NSO G15 maintenu

Le chargeur natif de segments (LZ4/ZBIC, contrôles de bornes, BSS en mémoire
guest, arguments et patches) vit désormais sous
`vendor/encore-active/eden-core/src/core/loader/nso.cpp`.
CMake sélectionne une copie exacte en `PORT_BUILD_DIR/nso.cpp`, sans mutation
de code ; le profil non natif conserve le fichier épinglé. L'ancien
`write_derived` est archivé uniquement comme oracle testable en répertoire
temporaire, sans participation au build. La parité octet par octet ne
remplace pas une vérification native sur console.

## Allocateur natif maintenu

L'ancien générateur G22 de `app_heap.c` a été supprimé. Le compilateur
sélectionne la source complète `eden-build/tooling/native/app_heap_arenas.c`
(normale) ou `app_heap_flat.c` (sans arènes) directement dans
`vendor/encore-active/`. Le diagnostic optionnel `heap_guard.h` est
maintenu au même endroit ; `third_party/app_heap.c` demeure épinglé et
immuable. Parité et compilation syntaxique des quatre combinaisons sont
contrôlées sur hôte, pas sur console.

## Cache GPU R437 maintenu

Le header natif `video_core/buffer_cache/buffer_cache.h`, initialement créé
par substitutions dans CMake, est maintenant la version complète suivie dans
`vendor/encore-active/eden-core/src/video_core/buffer_cache/`. La compilation
PS5 sélectionne une copie identique de ce header ; la comparaison avec
`eden-backports` et le témoin R437 empêchent le retour de l'ancien générateur.
Le helper applicatif `headless/buffer_pages.h` reste un composant distinct.

## Runtime RADV maintenu

Le fichier de démarrage natif `app_crt_radv.cpp` est maintenu
dans `vendor/encore-active/eden-build/tooling/native/` et choisi
explicitement par le profil RADV ; la branche CMake ne transforme plus
le boilerplate en C++.

## Fragments inclus ou injectés : vérifier leur propriétaire réel

Les entrées techniques qui fabriquent un correctif pour une dépendance
doivent finir dans `encore-active`. Ne pas transférer à l'aveugle les
fragments de l'application native qui ne remplacent aucune source upstream.

<!-- SINGLE_SOURCE_FRAGMENTS_START -->
| Chemin | Hypothèse de rôle | Qualification |
| --- | --- | --- |
| `headless/gpu_native_probe.inc` | Diagnostic GPU natif local | Inclus transitivement par `gpu_probe.inc` ; pas un override de dépendance |
| `headless/gpu_probe.inc` | Diagnostic graphique local | Inclus par `graphics.cpp` sous `EDEN_GPU_PROBE` ; reste dans le runtime de l'application |
<!-- SINGLE_SOURCE_FRAGMENTS_END -->

### Frontières des deux fragments résiduels

L'injection G09 est intégrée à `a64_interface_standard.cpp` sous un garde
C++ explicite. L'unité `a64_interface_shared.cpp` conserve la variante
partagée déjà distincte dans l'ancien CMake. Les deux fragments `gpu_probe.inc` / `gpu_native_probe.inc` sont des diagnostics
applicatifs inclus par `graphics.cpp` sous `EDEN_GPU_PROBE`.
Le contrôle de compilation a révélé que `gl_rasterizer_dev.cpp` incluait
`headless/dev_render_passes.inc` : c'était donc un **override DEV réel**,
non un fichier orphelin. Ce fragment complet vit désormais sous
`vendor/encore-active/eden-core/src/video_core/renderer_opengl/`, près du
rasterizer DEV qui l'inclut. `tools/check-headless-fragment-ownership.py`
verrouille cette provenance et rejette d'autres consommateurs actifs.
Le déplacement est à contenu identique, sans qualification console.

## Interface A32 native : génération G10 supprimée

La variante hôte conserve la source Dynarmic épinglée. Le profil natif
sélectionne une unité complète maintenue sous
`vendor/encore-active/eden-core/src/dynarmic/backend/x64/a32_interface_native.cpp`.
Elle conserve le diagnostic de pression JIT, la seconde tentative de
commit après épuisement mémoire et la notification des blocs compilés.
CMake copie cette unité sans réécriture et le test
`tools/check-maintained-a32-native-interface.py` vérifie l'identité
des transformations historiques. Aucune qualification PS5 n'est revendiquée.

## PhysicalCore : deux sources maintenues (G12/X07)

Le générateur G12 et la réécriture indirecte X07 sont retirés.
`physical_core_standard.cpp` et `physical_core_dev.cpp` résident
sous `vendor/encore-active/eden-core/src/core/hle/kernel/`.
Les deux conservent le drapeau ABI `bool`, mais chaque accès utilise
`std::atomic_ref`; les traces guest fault ne sont émises que dans le
chemin de faute. Le profil DEV ajoute le chronométrage de l'attente CPU.
CMake ne fait qu'une sélection et une copie, sans transformer de C++.
Les tests hôte vérifient le comportement atomique et les deux variantes,
mais ne certifient pas l'exécution console.

## Interface A64 : unité complète par mode

Le générateur G09 et `headless/jit-compile-batch.inc` sont retirés.
`vendor/encore-active/eden-core/src/dynarmic/backend/x64/` possède
`a64_interface_standard.cpp` et `a64_interface_shared.cpp`.
CMake copie uniquement la variante choisie ; le batch et les mesures DEV
sont conditionnés au niveau C++ sans réécriture CMake. L'identité du
bloc historique et la sélection des profils sont vérifiées sur hôte ;
la compilation native et l'exécution console ne sont pas certifiées.

### Émetteurs A32/A64 — G03/G04 transférés

Les générateurs historiques G03/G04 ont été retirés du CMake principal.
Les sources complètes `a32_emit_x64.cpp`,
`a64_emit_x64_standard.cpp`, `a64_emit_x64_shared.cpp`,
`a64_emit_x64_standard.h` et `a64_emit_x64_shared.h`
résident dans `vendor/encore-active/eden-core/src/dynarmic/backend/x64/`.
CMake sélectionne uniquement la variante normale ou partagée et copie
l'en-tête correspondant, avec le même chemin de build qu'avant.
Le booléen de publication `Emit(..., bool publish)` n'est exposé en
mode standard que lorsque batch ou shared sont activés. A32 ne dépend
pas de cette signature. Les transitions de fast-dispatch, liens,
RSB et propriétés de protection RW/RX sont conservées.

Les unités du JIT partagé liées à l'état et aux callbacks
(M01–M03) restent à consolider ; les unités mémoire G06–G08
sont désormais maintenues dans `encore-active`. Les tests de parité et de sélection sont des preuves
hôte, **pas** une preuve de compilation ou d'exécution console.

## Unités de mémoire A32/A64 — G08 centralisé

L'ancien générateur G08 et le préfixage CMake des macros du JIT partagé
sont retirés. Les unités C++ complètes
`a32_emit_x64_memory.cpp` et `a64_emit_x64_memory.cpp` sont maintenues
sous `vendor/encore-active/eden-core/src/dynarmic/backend/x64/`.
Les trois macros de monitor/conf du JIT partagé sont définies
uniquement sous `EDEN_SHARED_JIT_LAYOUT` ; la sélection CMake copie
exactement les unités maintenues pour A32/A64 sans réécriture.
La parité de chaque corps épinglé et la sélection ont un contrôle hôte ;
l'exécution native/guest reste non qualifiée.

La migration G06/G07 a été effectuée ensemble avec la cartographie
des fallbacks, accès exclusifs et du registre A32 ; elle n'a pas été
validée par un build natif.

## Mémoire x64 complète : G06 et G07 centralisés

L'en-tête `emit_x64_memory.h` est une source complète maintenue sous
`vendor/encore-active/eden-core/src/dynarmic/backend/x64/`. Il contient
les chemins page-table A32/A64, le pointeur packed, les registres scratch,
le fallback exclusif et les helpers checked-fastmem conditionnés en C++.

Les deux variantes complètes du corps inclus sont
`emit_x64_memory_standard.cpp.inc` et
`emit_x64_memory_checked.cpp.inc`. CMake ne fait que sélectionner selon
`EDEN_A32_FASTMEM` puis copier vers le chemin d'inclusion attendu.
Les chemins normal/JIT partagé sont distingués dans le C++ sous
`EDEN_SHARED_JIT_LAYOUT`. Les fragments scalaires historiques ne sont
plus assemblés dans CMake et servent uniquement à la parité.

`checked-fastmem.cmake` est supprimé, `scalar-memory.cmake` conserve
seulement la sélection des deux sources indépendantes vectorielles, et
`shared-jit.cmake` n'injecte plus d'édition dans les sources mémoire.
G06/G07 et les dettes indirectes X03/X08 sont retirés des registres.
`tools/check-maintained-memory-g06-g07.py` vérifie les corps et les
huit combinaisons de sélection CMake ; **la compilation native et les
preuves de fonctionnement sur console restent à obtenir**.

## Émetteur x64 commun : source complète par profil (G05)

L'ancien générateur G05 de `emit_x64.cpp` est retiré. La correction
`patch_information.find(target_desc)` est identique dans les deux unités
maintenues `emit_x64_host.cpp` et `emit_x64_native.cpp`; seul le profil
natif retire le coût de formatage associé à `PerfMapRegister`.
Le sélecteur CMake copie l'unité choisie vers le chemin de compilation
existant. Le test hôte compare les deux variantes à la source épinglée
et vérifie leur sélection sans annoncer de qualification console.

## G17/G18 — gestionnaire de services

Les variantes normales et diagnostiques de `ServerManager` ont chacune leur C++ et leur en-tête complets sous `vendor/encore-active/eden-core/src/core/hle/service/`. CMake choisit simplement la paire et copie son en-tête dans l'overlay d'inclusion historique. Un test de parité reconstruit les sept anciennes injections DEV depuis l'original épinglé ; ni re-génération ni compilation double du gestionnaire n'est permise. G19 (`kernel.cpp`) sélectionne désormais les deux sources maintenues `kernel_standard.cpp` et `kernel_dev.cpp`, sans génération C++ dans le CMake actif.

## G16 — finalisation des pages mémoire kernel

La garde de `KPageTableBase::Finalize` est maintenant une source C++ complète
dans `vendor/encore-active/eden-core/src/core/hle/kernel/k_page_table_base.cpp`.
Le processus ordinaire continue de libérer ses pages physiques ; la
finalisation d'un kernel en arrêt ne les libère plus, car le gestionnaire
mémoire sera recréé. L'ancienne réécriture G16 est supprimée de CMake.
La parité exacte avec la source épinglée et le chemin compilé font l'objet du
test `tools/check-maintained-page-table-finalize.py`. Le résultat sur
console reste non qualifié.

## BlockOfCode : W^X, alias mémoire et permissions JIT

Les générateurs G01/G02 et la mutation indirecte X09 sont retirés ensemble.
`vendor/encore-active/eden-core/src/dynarmic/backend/x64/` possède
`block_of_code.h`, `block_of_code_host.cpp` et
`block_of_code_native.cpp`. CMake choisit la variante, puis la copie
sans réécriture dans `${PORT_BUILD_DIR}` pour préserver les tests de
protection JIT et l'arbre de compilation. L'ancien fragment
`headless/jit-permissions.inc` est intégré aux unités complètes et supprimé.
Un contrôle hôte exerce les sélections CMake Linux/native et vérifie les
invariants W^X ; aucun progrès guest/console n'est revendiqué.

## Assertion JIT centralisée

`headless/jit_assert.inc` a été retiré : son contenu était déjà intégré
mot pour mot dans l'en-tête complet
`vendor/encore-active/eden-core/src/common/assert.h`, sélectionné par
la priorité d'inclusion du JIT. Le test de parité compare le préfixe Eden
épinglé et verrouille le bloc de diagnostic intégré par son empreinte Git,
sans conserver un fragment C++ concurrent hors `encore-active`.

## Groupe JIT partagé centralisé

Les cinq fragments `jit_*.inc` et `jit_group.h` ont été déplacés à
blobs Git identiques dans `vendor/encore-active/eden-core/dynarmic/shared-jit/`.
Le module `headless/dynarmic/shared-jit.cmake` sélectionne désormais les
sources complètes `a64_jitstate.h`, `jit_group.h` et `callback.cpp` maintenues
dans Encore. Les anciennes transformations M01 et M03 sont reproduites
exactement par des tests de parité ; CMake ne fait que copier ces fichiers.
Ce module ne possède plus aucun site `write_derived` ; les **0 générateurs
secondaire** restant appartiennent au pont différé expérimental.
Shared JIT reste OFF par défaut, sans qualification matérielle.

## Fragments scalaires centralisés

Le traducteur scalaire, son implémentation de lecture/écriture des
registres et l'optimiseur IR sont désormais trois fichiers complets
maintenus sous `vendor/encore-active/eden-core/src/dynarmic/`.
CMake choisit directement les unités `a64_translate.cpp` et
`opt_passes.cpp`, avec `impl/impl.cpp` inclus exclusivement par le
traducteur. `scalar-fold.inc` est un témoin historique de parité, non
une entrée de compilation. Les deux émetteurs scalaires `emit_x64_vector.cpp` et
`emit_x64_data_processing.cpp` sont des sources complètes maintenues.
Les fragments `scalar-memory-read.inc` et `scalar-memory-write.inc`
sont désormais des témoins de parité sous `encore-active` ; leurs
corps sont inclus dans les deux variantes de
`emit_x64_memory_*.cpp.inc`. Le sélecteur
`scalar-memory.cmake` n'assemble plus de code C++ (X08 retiré).

## Oracles Vulkan historiques

Les cinq anciens fragments Vulkan ont été déplacés **sans modifier leurs blobs
Git** vers `vendor/encore-active/eden-vulkan-oracles/`. Ils ne constituent
pas une seconde version compilée de Vulkan : `tools/prepare-vulkan-port.py`
ne les charge que pour reconstituer les sorties historiques, tandis que
le binaire choisit exclusivement `vendor/encore-active/eden-vulkan/`.
`headless/vulkan.cmake` ne les surveille plus inutilement comme dépendances
de configuration. Leur conservation sert la preuve de parité, pas la
construction du moteur.

## G21 : processeur GPU maintenu en cinq variantes

Les cinq sources GPU (OpenGL hôte et natif normal/DEV, Vulkan) sont
complètes dans `eden-core/src/video_core/`. Le CMake actif choisit
une seule unité par profil ; il ne lit plus ni ne réécrit le code
`gpu.cpp` épinglé. L'ancienne recette CMake n'existe que comme
oracle sous `tools/fixtures/legacy-g21-gpu.cmake`. Les contrats de
parité sont hôte uniquement ; aucun comportement console n'est
déclaré qualifié.

## Correction GPU réellement centralisée

`video_core/memory_manager.cpp` est désormais maintenu dans
`vendor/encore-active/eden-core/src/video_core/`, avec les huit sites
de correction de plages, débordements et pages GPU. `PS5_NATIVE` sélectionne
directement cette source. Le module `native_gpu_granular_bounds.cmake`
et la génération `memory-manager-native.cpp` sont supprimés.
Les vérifications hôtes contrôlent les fonctions maintenues et leur parité
avec les anciennes transformations ; aucun gain FPS ni résultat console
n'est inféré.

## Variantes HID exclusives

Le témoin R435 ne génère plus `npad_pause_diag.cpp` dans CMake.
`hid_core` compile une seule variante : le `npad.cpp` maintenu
ordinaire, ou `npad_pause_diag.cpp` lorsque `PS5_NATIVE` et
`EDEN_DEV_PROFILE` sont tous deux activés. La variante de diagnostic
conserve les deux gardes de pointeurs de la version normale et ne modifie
ni le mapping ni les commandes. Le contrôle hôte compare le code
extérieur au témoin Fullkey et vérifie la sélection exclusive.

## Diagnostic conditionnel GPU versionné

Le profil `EDEN_DEV_PROFILE` utilise une unité `Maxwell3D` complète
sous `encore-active/eden-core/src/video_core/engines/`, au lieu de
reconstruire un correctif dans CMake. Le profil normal demeure sur
l'unité Eden épinglée. Parité de contenu vérifiable hors console.

## Injections GPU centralisées

Le fragment historique `headless/native_gpu_thread.inc` a été supprimé :
son implémentation de `ThreadManager::StartThread` et `ThreadManager::Stop`
était déjà présente à l'identique dans les deux sources complètes
`vendor/encore-active/eden-gpu/gpu_thread_quiet.cpp` et
`gpu_thread_dev.cpp`. Le test de sélection native vérifie désormais
l'identité du cycle de vie dans ces deux variantes et l'absence de
la copie historique. Il ne s'agit pas d'une nouvelle modification GPU.

La file GPU utilise exclusivement
`vendor/encore-active/eden-gpu/include/common/bounded_threadsafe_queue.h`
et les deux variantes du worker, directement sélectionnées dans CMake.
L'ancien fragment `gpu_queue_stop_wait.inc`, redondant et non compilé,
a été supprimé. Le seul fragment encore injecté dans cette famille est
`gpu_sync_failure_wait.inc`, en attendant la migration du `gpu.cpp`
complet vers `encore-active`.

## Table mémoire sparse maintenue

Le header `sparse_large_vector.h` ne doit plus être généré depuis des
substitutions CMake. L'implémentation complète est maintenue sous
`vendor/encore-active/eden-core/src/common/`; l'ancienne priorité d'include
demeure, avec comparaison textuelle complète dans un oracle hôte.

## Diagnostic KProcess maintenu

Le fichier `eden-core/src/core/hle/kernel/k_process.cpp` contient
les cinq marqueurs chronométrés de finalisation du processus, selon
le profil `EDEN_DEV_PROFILE`. La sélection CMake ne génère plus
cette unité. Le profil normal et ses méthodes ne changent pas ;
les seules preuves disponibles sont des contrôles de source hôte.

## Xbyak maintenu en source complète

Le header épinglé `xbyak.h` est maintenu sous
`vendor/encore-active/eden-build/third_party/xbyak/` avec la licence
BSD d'origine et les huit adaptations d'alias mémoire. CMake ne fait plus
que le copier. Le module `jit-alias.cmake` conserve une modification
indirecte de `code_source` (X09) retirée : les deux variantes complètes de `BlockOfCode` sont maintenues dans `encore-active`.

## Dynarmic : suivi des blocs centralisé

Les unités `block_range_information.cpp` et `.h` ne sont plus
dupliquées dans `headless/dynarmic/`. Elles résident sous
`vendor/encore-active/eden-core/src/dynarmic/backend/` ;
CMake sélectionne le .cpp et copie le header pour préserver le
chemin d'inclusion prioritaire. La logique et le profil JIT ne changent pas.

## Pool de constantes JIT maintenu

`constant_pool.cpp` est une unité C++ versionnée dans
`encore-active/eden-core/src/dynarmic/backend/x64/`.
Le sélecteur `jit-alias.cmake` ne modifie plus cette unité à la configuration.
La variante `xbyak.h` reste une migration différente, non masquée ici.

## Verrou natif Dynarmic centralisé

Le fragment historique `headless/spin-lock.inc` est supprimé. Les fonctions
`SpinLock::Lock()` et `SpinLock::Unlock()` résident dans l'unique source
`vendor/encore-active/eden-core/src/dynarmic/common/spin_lock_x64.cpp`.
Le build natif sélectionne cette source directement et n'assemble plus
le corps C++ dans CMake. La vérification de provenance protège son
identité Git ; le comportement console reste à confirmer.

## Blitter logiciel GPU maintenu

La variante native complète de `sw_blitter/blitter.cpp` est dans
`vendor/encore-active/eden-core/src/video_core/engines/`.
Elle conserve le backport de production et élargit trois calculs de taille ;
le module natif ne fait plus d'injection C++. Le test de parité vérifie
les deux héritages, sans prouver les performances sur console.

## Shader PRMT natif maintenu

`shader_recompiler/frontend/maxwell/translate/impl/not_implemented.cpp`
contient désormais directement la traduction PRMT mode 0 de l'ancien
générateur CMake. L'oracle hôte compare les corps PRMT, les diagnostics
bornés et les assertions de référence. Les cas non pris en charge
continuent de déclencher le même chemin d'échec.

## Rasterizer OpenGL : variantes compilées depuis Encore

Le rasterizer normal et le rasterizer DEV sont deux unités complètes
sous `vendor/encore-active/eden-core/src/video_core/renderer_opengl/`,
avec sélection exclusive dans `headless/CMakeLists.txt`.
La journalisation limitée à trois tirages et les fonctions de diagnostic
DEV restent exactement équivalentes aux anciennes sources générées.

## Module GPU d'observabilité sans code dérivé

`gpu_native_observability.cmake` choisit désormais des unités complètes
pour PRMT, blitter et Fermi2D. Le mode Fermi2D expérimental reste OFF
par défaut, et la source `fermi_2d_observed.cpp` préserve le
comportement de compatibilité normal. Les deux variantes sont comparées
au résultat historique de génération par l'oracle hôte.

## Correction de cache de shaders centralisée

Le chargement d'un cache tronqué ou corrompu est compilé depuis
`eden-core/src/video_core/shader_environment.cpp` qui inclut
`shader_cache_reader.inc` depuis son propre dossier Encore.
Le générateur CMake et le doublon `headless/` sont supprimés.
Le contrôle de parité reconstruit l'ancien résultat du CMake épinglé ;
cela ne constitue pas une preuve de comportement sur console.

## Conditions de sortie de la dette

1. Aucun générateur CMake ne reconstruit du C++ corrigé à partir d'une
   source épinglée. Les ressources GLSL et sorties de configuration ne
   sont pas automatiquement du C++ : les classer par usage.
2. Aucun module indirect ne transforme un corps ou un en-tête upstream ;
   toute modification est une source suivie dans `encore-active`.
3. Les scripts `tools/` encore autorisés pour la production se limitent
   à sélectionner, copier, configurer ou contrôler. Les différences hôtes,
   certificats et packaging ont chacune une origine versionnée explicite.
4. Les `.inc` qui injectent une modification upstream sont migrés dans
   `encore-active`, avec mise à jour des include paths ou du sélecteur.
5. Chaque transfert possède un test de **parité exacte** avec la source
   anciennement générée, un rattachement de fonctions, et une prévalidation
   CI. La validation du comportement console est distincte.
6. `headless/prosperoeden/` reste le code du launcher dans son chantier
   indépendant ; la centralisation des overrides ne justifie pas de toucher
   au thème ni aux mappings de commandes.

Ce registre est un **périmètre de migration**, pas un certificat
d'achèvement. L'énumération de modules et fragments est vérifiée par CI :
un nouveau fichier doit être explicitement qualifié plutôt que devenir
un override invisible.
