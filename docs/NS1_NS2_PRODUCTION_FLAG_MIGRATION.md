# Eden Encore — migration des 22 sélecteurs de recherche NS2 vers un moteur commun

**Inventaire effectif du 02/11/2026**, dérivé de `headless/CMakeLists.txt`. Voir la [roadmap vivante #15](https://github.com/niakw/ProsperoEden-Encore/issues/15) (P0.2). **Tous les 22 commutateurs ci-dessous ont actuellement `OFF` comme valeur par défaut**. Leur existence ne prouve pas que les fonctionnalités NS2 soient intégrées au produit distribué.

| Domaine et destination de production | Flags `EDEN_NS2_…_EXPERIMENTAL` à résorber | Critère de promotion/suppression |
| --- | --- | --- |
| Boot, CPU, architecture et fréquence | `EDEN_NS2_METADATA_EXPERIMENTAL`, `EDEN_NS2_EXEFS_EXPERIMENTAL`, `EDEN_NS2_PROCESS_RUN_GUARD_EXPERIMENTAL`, `EDEN_NS2_A64_EXPERIMENTAL`, `EDEN_NS2_CPU6_EXPERIMENTAL`, `EDEN_NS2_GUEST_COUNTER_EXPERIMENTAL` | Une sélection automatique vérifiée par NPDM/HOS/CPU, progression invitée réelle, 6 cœurs NS2 et absence de régression NS1 |
| Services HOS, IPC et GPU session | `EDEN_NS2_AM_EXPERIMENTAL`, `EDEN_NS2_GRAPHICS_SCALE_EXPERIMENTAL`, `EDEN_NS2_NVDRV_EXPERIMENTAL`, `EDEN_NS2_GPU_SESSION_EXPERIMENTAL`, `EDEN_NS2_GRAPHICS_SUPERVISOR_EXPERIMENTAL` | Implémentation commune des protocoles + adaptateurs de commandes spécifiques, replies/handles/fences exacts; aucun retour factice de succès |
| Adressage / résidence / scheduler | `EDEN_NS2_GPU_RANGE_BATCH_EXPERIMENTAL`, `EDEN_NS2_CONTINUITY_EXPERIMENTAL`, `EDEN_NS2_SPARSE_QUEUE_EXPERIMENTAL`, `EDEN_NS2_SPARSE_CACHE_PROBE_EXPERIMENTAL` | Adresses natives contrôlées, réservation physique et remise à zéro atomique, un scheduler Vulkan, rollback fiable, budgets et limites de périphérique |
| Shader / GPU | `EDEN_NS2_AMPERE_PROBE_EXPERIMENTAL`, `EDEN_NS2_VULKAN_SHADER_BRIDGE_EXPERIMENTAL` | Une API shader/pipeline canonique, Maxwell/Ampere décodés par leur frontend matériel, vertex/fragment/compute validés, pas de pipeline de « probe » dans le produit |
| Cache texture, ASTC, images | `EDEN_NS2_ASTC_SCRATCH_RELEASE_EXPERIMENTAL`, `EDEN_NS2_ASTC_LAYER_DECODE_EXPERIMENTAL`, `EDEN_NS2_ASTC_TEXTURE_CACHE_BRIDGE_EXPERIMENTAL`, `EDEN_NS2_VIEW_EXPERIMENTAL` | Texture/cache unique, formats ASTC, vues 3D/layers, GOB, synchronisation et contrôles de bornes testés sur NS1 et NS2 |
| Cache Vulkan | `EDEN_NS2_PIPELINE_CACHE_EXPERIMENTAL` | Une implémentation cache driver robuste et versionnée, pas de changement de schéma pendant le jeu, invalidations et durées de vie contrôlées |

**État des jalons :** 22 flags recensés, 22 désactivés par défaut, **0 flag de cette liste déclaré promu**. Certains comportements ont déjà des propriétaires partagés `EDEN_SHARED_NS2_*` — cela ne suffit pas à certifier les chemins verrouillés ici.

## Règles de migration

1. **Conserver une seule responsabilité maintenue** pour JIT, buffers, cache texture, shaders, renderer, services et UI; n'admettre des adaptations qu'aux frontières matérielles (ISA/QMD, formats/ABI/services). Pas de fork parallèle du moteur.
2. Remplacer chaque flag de recherche **après validation** par sélection automatique selon le programme invité/la capacité matérielle, ou supprimer le code devenu redondant. Ne pas remplacer un mode OFF par un « succès » artificiel.
3. Faire passer les tests hôte négatifs, la parité source, la CI commune et la non-régression NS1 **sur le même SHA**, puis qualifier sur la PS5.
4. L'inventaire est contrôlé par `tools/check-ns2-production-flags-host.py`. L'ajout, le renommage ou le retrait d'un flag doit mettre ce document et les tests à jour dans le même commit.
5. Les workflows de build PS5 restent verrouillés avant les critères P4 de la roadmap. La validation console demandera ensuite un build expressément autorisé; aucune preuve console ne peut être obtenue sans exécution.

Ce document est un **inventaire des travaux restants**, pas un engagement selon lequel les 22 chemins sont déjà fonctionnels.
