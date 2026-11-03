# Lichii nx2 — audit transposable à Eden Encore (2026-11-03)

Référence examinée : [`zortos293/Lichii` branche `nx2`, `29571ea9d74b0999ac900255220a40f90a865cec`](https://github.com/zortos293/Lichii/commits/nx2/). L'objectif est la compatibilité générique NS2 sans régressions NS1 ; **aucun correctif par titre** et **aucune reprise globale du fork**.

## Comparaison et décision

| Amont Lichii | Sujet technique réel | Décision Encore |
| --- | --- | --- |
| [`46b2577`](https://github.com/zortos293/Lichii/commit/46b2577bf78870ed85cbb790a9dc3c82cc77f4a7) | `BufferCache::FindBuffer` indexe `page_table` sans vérifier le numéro de page ; les CBUF GPU non mappés doivent retirer leur binding | **Port ciblé publié** : le CBUF non mappé était déjà traité dans le propriétaire maintenu ; ajout du contrôle de page ET de l'étendue en octets, uniquement dans `eden-core` maintenu (`vendor 5c7b925`, `main 5f9fefd`). L'amont `eden-backports` reste épinglé et inchangé |
| [`fae3bc6`](https://github.com/zortos293/Lichii/commit/fae3bc64a90940a809993c3ceef4eb1f5d98b93e) | Revalidation des commandes écrites par le GPU après drain, avant réutilisation d'un snapshot à la soumission | **Ne pas copier** : notre `DmaPusher` lit les mots invités au moment de l'exécution et n'utilise pas le cache `submitted_words`. `tools/ns2/check_native_gpu_command_fetch_owner.py` vérifie cette différence ; l'ordonnancement de véritables écritures GPU avant le fetch reste **non prouvé** (P2.7) |
| [`10e7063`](https://github.com/zortos293/Lichii/commit/10e70639058b9adc4f7fc77e11982bb834fce86b) | Capturer et abaisser une fois les shaders natifs, puis réutiliser le résultat | **Déjà partiellement couvert** par `NativeTranslationCache` (capture et traduction vérifiées par session/processus) dans `CaptureNativeComputeShader` et la GMMU d'Encore ; ne pas injecter le cache shader desktop de Lichii dans notre ABI PS5. Mesurer les recompilations restantes séparément |
| [`d7ce3d8`](https://github.com/zortos293/Lichii/commit/d7ce3d8c0881fc605974d4747573e8a1fcadb37f) | Accès scalaires multipages, synchronisation des sémaphores, readback GPU | Les scalaires multipages ont déjà `native_paged_scalar.h` dans le propriétaire maintenu ; **pas de port massif** de la file GPU. L'audit global de provenance P1.2 doit encore expliquer l'empreinte courante `b5caf9fa5b0477b005249d4b87bac89934bf4c50`, non reconnue par l'oracle historique |
| [`e37b4b9`](https://github.com/zortos293/Lichii/commit/e37b4b9fa60f02fa77a4795cdd1bed0b8c71b933) | Priorité d'éviction aux blocs de mémoire Vulkan les moins occupés | **À mesurer après la qualification fonctionnelle** : dépend du propriétaire GPU, des images épinglées et des seuils VRAM ; pas de transplantation sans preuve de libération par bloc, fence et stabilité |
| [`3b1d6eb`](https://github.com/zortos293/Lichii/commit/3b1d6eb9cde08f35d14c6f2f7b3aa8f87c272644) | Apple Silicon/MoltenVK/arm64, corrections et réglages de build desktop | **Hors chemin de rendu PS5**. Peut renseigner les outils hôte, mais n'est pas une optimisation PS5 démontrée |
| [`b9d6b4a`](https://github.com/zortos293/Lichii/commit/b9d6b4a71ee0ff4fb6bf89699746ccaf3086c030), [`62bc753`](https://github.com/zortos293/Lichii/commit/62bc7538b119b3b5a8105ce9195b04ef626ec4ae) | Workarounds associés à des titres et upscale de substitution | **Exclus**. Aucun test, flag ou code conditionnel propre à un jeu ne doit être porté |

### BRX — aucune fausse accélération

Le fork possède `shader_recompiler/frontend/ampere/program_address_map.h`, utilisé pour convertir les cibles des branches natives Ampere en positions Maxwell. Encore possède **déjà** `program_address_map.h`, son adaptateur `maxwell_image.cpp`, et `NativeIndirectBranchPlan`. Le point non clos reste **l'authentification des tables/cibles indirectes** avant compilation et exécution, pas l'absence de traduction d'adresse. Conserver le refus lorsque la preuve de table est insuffisante.

## Contrôles effectivement exécutés

- `tools/check-ns2-buffer-find-bounds-host.py` : C++ extrait du vrai `FindBuffer`, UBSan `-O0` et `-O2`, pages 0/valides/hors table, étendue exacte et débordement de 16 Gio, adressage maximal. **PASS**.
- `tools/check-ps5-buffer-pages-r437.py` : reconstruction stricte depuis le backport historique, avec ajout audité du guard de page/étendue ; **PASS**.
- `tools/check-ps5-buffer-region-multipage-host.py` : régression des recherches sur plusieurs pages, O0/O2 ; **PASS**.
- `tools/check-ns2-source-selection.py` : garde de sélection des propriétaires ; **PASS**.
- `tools/check-vendor-consolidation-debt.py` : **NON PASSANT** à un oracle GPU P1.2 distinct (empreinte `memory_manager.cpp` inchangée par ce lot). Ne pas modifier le hash autorisé à l'aveugle.

## Prochaines preuves manquantes

1. **P2.7** : synchroniser le producteur de commandes GPU et la lecture CPU effective sans snapshots périmés, sans ajouter de stall systématique ni toucher au chemin NS1.
2. **P2.4** : calculer et authentifier les destinations BRX/BRXU indirectes ; l'existence du tableau d'adresses ne démontre pas la validité des cibles dynamiques.
3. **P2.2/P4.2** : valider les propriétés de publication TIC/TSC, l'acquisition et la conservation des images Vulkan, et les fences sur les propriétaires réellement actifs.
4. **P5 seulement** : compilation PS5 et qualification console une fois les gates P0–P4 fermés, sans prétendre que des tests hôte constituent des FPS observés en jeu.
