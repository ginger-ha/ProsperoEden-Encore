# Eden Encore — roadmap suivable pour un moteur PS5 commun NS1 / NS2

**Mise à jour : 2026-11-02 · branche unique : `main`**

> **Suivi vivant à cases cochables : [GitHub Issue #15 — ROADMAP](https://github.com/niakw/ProsperoEden-Encore/issues/15)**
> **Audit technique et preuves de boot : [GitHub Issue #14](https://github.com/niakw/ProsperoEden-Encore/issues/14)**
> Le document présent explique les dépendances et critères de sortie; c'est l'issue #15 qu'il faut mettre à jour après chaque lot.

## Objectif et règles

Une seule application PS5 et un seul socle de moteur Vulkan, CPU/JIT, HLE, cache shaders, cache textures, buffer cache, ordonnanceur, services communs et UI. Les détails intrinsèquement différents (instructions Maxwell/Ampere, descripteurs QMD, capacités GPU, fréquences, services et formats firmware) sont sélectionnés automatiquement et vérifiés; **aucun réglage « expérimental » dans le profil final**. Cela ne signifie pas supprimer les contrôles de sécurité ni prétendre qu'une instruction Ampere est du Maxwell.

Le mode sans build PS5 reste en vigueur. Les deux workflows de build complet et recherche sont désactivés, la CI hôte continue. Il faudra finalement un **build de qualification PS5 explicitement autorisé**, une fois les barrières hôte levées, car on ne peut pas prouver la compatibilité console sans exécuter le programme.

## État technique vérifié au départ

| Domaine | État au 02/11/2026 | Limite de la preuve |
| --- | --- | --- |
| Moteur NS1 | Base fonctionnelle historiquement sur BOTW; FC27 a encore crashs/saccades et HUD à contrôler | Pas de succès FC27 vérifié pour le nouveau code |
| Boot NS2 | Parsing, TitleID, chemins extraits, capacités, partie HLE en place | MKW/Bananza restent sans première image invitée confirmée |
| GPU buffers communs | SSBO array walker unique NS1/NS2 avec 32 slots, générateur et vendor cohérents | CI hôte du dernier SHA à confirmer; textures Ampere non terminées |
| Compute NS2 | Capture QMD3 → SPIR-V → VkComputePipeline pour les cas admissibles | Images TIC/TSC, global memory, CBUF indirect, pipeline-cache natif manquants |
| GPU 3D NS2 | Sous-composants Ampere / MME présents | Rendu réel, task/mesh, stages et synchronisation non prouvés |
| Mémoire et VRAM | GMMU, NVMap, sparse/ASTC et contrôles hôte partiels | Résidence physique 12 GiB et premières images sur PS5 non prouvées |
| HLE / synchronisation | Nombreux services et correctifs IPC, VI2, scheduler | Pas de chemin complet invités → VI2 → frame certifié |
| UI et jaquettes | Index LaunchBox Switch 2, cache fronts/backs/spines, opacité et conservation d'inventaire corrigés; preview hôte verte | Jaquettes réellement récupérées sur console et transition GL→Vulkan sans flash à valider |
| Release | Builds natifs verrouillés | Pas de qualification console de cette révision |

## Séquence des jalons

| Ordre | Jalon | Livrable observable | Déblocage |
| --- | --- | --- | --- |
| **P0** | CI, propriété des sources et dé-expérimentalisation | Tous tests obligatoires verts au même SHA, inventaire des `EDEN_NS2_*_EXPERIMENTAL` + plan de promotion/suppression | Précondition à tout nouveau port moteur |
| **P1** | Boot / mémoire / HLE communs | Progression du PC invité traçable, 49-bit GMMU, NVMap/rollback, IPC exact, addons/keys/firmwares flexibles | Entrée GPU authentifiée et stable |
| **P2** | GPU Vulkan complet partagé | TIC/TSC, images/UBO/SSBO, caches, graphics/compute Ampere, ASTC/sparse/VRAM, synchronisations, premier framebuffer invité | Première image réelle de MKW/Bananza |
| **P3** | UI / rendu / NS1 sans régression | Jaquettes NS1/NS2 correctes, aucun rescan visible, chargement unique continu, FC27/BOTW non dégradés | Candidat d'installation |
| **P4** | Préqualification sans console | Tests Clang/GCC, CI complets, mémoire/fences, source parity et négatifs, code de release sans chemins factices | Autorisation manuelle d'un build PS5 |
| **P5** | Qualification PS5 et stabilisation | MKW + Bananza première image invitée, FC27 match sans crash, BOTW, gestion des ressources, comparaison performances | Release seulement si critères remplis |

Ces jalons ne sont **pas** des estimations de délais; chacun se ferme uniquement sur preuve. Un test de traduction shader, une preview OpenGL ou une compilation native réussie ne remplace pas une image issue du GPU invité.

## Points à suivre à chaque livraison

1. Commit **main** complet et commit **vendor** épinglé.
2. CI : `encore-core-fast-gate`, `encore-core-preflight`, `ns2-research-host`, `check-vendored-vulkan-fork`, `launcher render preview`. Lister tous les échecs restant et les skips explicites.
3. Preuves : **source intégrée**, **hôte validé**, **PS5 validé**, séparément.
4. Corrections génériques transférables aux deux générations, tests NS1/NS2 avant fermeture du jalon.
5. Prochain verrou en cause et actions exactes sans introduire de hack par TitleID.

## Références du premier point de contrôle

- Dernière révision stable de l'architecture SSBO partagée : [main `8df7bff`](https://github.com/niakw/ProsperoEden-Encore/commit/8df7bff70a7d23a3394544f9377e02836cd9c30a), [vendor `5612c96`](https://github.com/niakw/Prospero.Eden-Encore-vendor/commit/5612c96a6ce181186987e3fcb7ca291bfc6fd7c9).
- [Tests hôte NS2 #41433008853](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41433008853) et [preview #41433008821](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41433008821) : réussis pour cette révision; [core fast gate #41433008785](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41433008785) : échec d'inventaire F07, **pas** un PASS moteur.
- Correctif de classement du composant loader hors inventaire historique : [`2963bea`](https://github.com/niakw/ProsperoEden-Encore/commit/2963bea8ad537cb56d92b9a876f9054684055d9f), [nouveau core gate #41434852822](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41434852822) en cours lors de la création de ce document.

**Priorité immédiate :** fermer P0.1, établir la cartographie des responsabilités communes (P0.2/P0.3), puis terminer TIC/TSC + mémoire/VI2 pour atteindre une frame GPU NS2 réellement présentable.

## P2.3 — Optimisation native Compute revue (2026-11-02)

Le fournisseur Vulkan conserve désormais au plus **12 pipelines Compute Ampere** compilés sous leur propriétaire `PipelineCache`, avec clef comprenant **processus + génération du processus + époque du canal + hash et comparaison complète du SPIR-V**. Les dispatchs ont des `shared_ptr` indépendants retenus jusqu'au retrait GPU ; l'éviction LRU ne libère jamais une ressource encore retenue par une commande. Les shaders dépassant 65 536 mots SPIR-V restent sans cache. Les échecs de création ne sont jamais mémorisés, et une saturation mémoire du cache ne doit pas faire échouer un dispatch valide. Ce changement ne touche pas le cache Maxwell/NS1. Le générateur Vulkan est synchronisé avec les sources du vendor, sans supprimer la comparaison intégrale. **Qualification PS5 encore manquante.**
