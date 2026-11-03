# Eden Encore — roadmap suivable pour un moteur PS5 commun NS1 / NS2

**Mise à jour : 2026-11-03 · branche unique : `main`**

> **Suivi vivant à cases cochables : [GitHub Issue #15 — ROADMAP](https://github.com/niakw/ProsperoEden-Encore/issues/15)**
> **Audit technique et preuves de boot : [GitHub Issue #14](https://github.com/niakw/ProsperoEden-Encore/issues/14)**
> Le document présent explique les dépendances et critères de sortie; c'est l'issue #15 qu'il faut mettre à jour après chaque lot.

## Objectif et règles

Une seule application PS5 et un seul socle de moteur Vulkan, CPU/JIT, HLE, cache shaders, cache textures, buffer cache, ordonnanceur, services communs et UI. Les détails intrinsèquement différents (instructions Maxwell/Ampere, descripteurs QMD, capacités GPU, fréquences, services et formats firmware) sont sélectionnés automatiquement et vérifiés; **aucun réglage « expérimental » dans le profil final**. Cela ne signifie pas supprimer les contrôles de sécurité ni prétendre qu'une instruction Ampere est du Maxwell.

**Verrou P5 imposé par le propriétaire : aucun build PS5 et aucun test console avant l'entrée formelle en P5, après traitement des jalons P0 à P4.** Jusqu'à cette frontière, seuls les changements source, contrôles Clang/GCC, tests host, analyses de parité et previews hors console sont permis. Les workflows natifs restent désactivés; leur réactivation et la qualification de vrais jeux requièrent une autorisation explicite en P5. Aucun jalon P0-P4 ne doit être maintenu artificiellement ouvert parce qu'il manque un essai console réservé à P5.

## État technique vérifié au départ

| Domaine | État au 02/11/2026 | Limite de la preuve |
| --- | --- | --- |
| Moteur NS1 | Base fonctionnelle historiquement sur BOTW; FC27 a encore crashs/saccades et HUD à contrôler | Pas de succès FC27 vérifié pour le nouveau code |
| Boot NS2 | Parsing, TitleID, chemins extraits, capacités, partie HLE en place | MKW/Bananza restent sans première image invitée confirmée |
| GPU buffers communs | SSBO array walker unique NS1/NS2 avec 32 slots, générateur et vendor cohérents | CI hôte du dernier SHA à confirmer; textures Ampere non terminées |
| Compute NS2 | Capture QMD3 → SPIR-V → VkComputePipeline buffer-only; LRU natif borné à 12 avec vie GPU protégée (source/hôte) | Images TIC/TSC Vulkan, global memory, CBUF indirect et qualification PS5 manquants |
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
| **P4** | Préqualification strictement hôte | Tests Clang/GCC, CI complets, mémoire/fences simulées, source parity et négatifs, chemin de release sans faux succès | Dossier de décision d'entrée en P5; pas de build exécuté |
| **P5** | Build PS5 contrôlé, qualification console et stabilisation | Autorisation explicite du build, puis MKW + Bananza première image invitée, FC27 match sans crash, BOTW, ressources et performances | Release seulement si critères console remplis |

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

## P2.6a — Réutilisation native Compute revue (2026-11-02)

Le fournisseur Vulkan conserve désormais au plus **12 pipelines Compute Ampere** compilés sous leur propriétaire `PipelineCache`, avec clef comprenant **processus + génération du processus + époque du canal + hash et comparaison complète du SPIR-V**. Les dispatchs ont des `shared_ptr` indépendants retenus jusqu'au retrait GPU ; l'éviction LRU ne libère jamais une ressource encore retenue par une commande. Les shaders dépassant 65 536 mots SPIR-V restent sans cache. Les échecs de création ne sont jamais mémorisés, et une saturation mémoire du cache ne doit pas faire échouer un dispatch valide. Ce changement ne touche pas le cache Maxwell/NS1. Le générateur Vulkan est synchronisé avec les sources du vendor, sans supprimer la comparaison intégrale. **Qualification PS5 encore manquante.**

## Micro-jalons vérifiés sans build PS5 (2026-11-02)

- **P2.6a — hôte validé :** l'implémentation LRU Compute et le garde de provenance N56/U92 sont validés sur [`43f595b`](https://github.com/niakw/ProsperoEden-Encore/commit/43f595bd51f665f240e4cf17f29b56e34715ee63) / vendor [`32a0ac1`](https://github.com/niakw/Prospero.Eden-Encore-vendor/commit/32a0ac1bbdea56c5daa19c077c0bd6792844f935) par [NS2 host #41521143542](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41521143542). La mesure NS1/NS2 et les essais GPU réels restent ouverts.
- **P3.4a/b — preview/source validées :** la navigation entre onglets conserve les derniers jeux et l'illustration. Les protections de volumes absents au premier scan sont intégrées ; [preview #41524761665](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41524761665) verte sur `664b7f0`. L'indisponibilité d'un **fichier** (EIO, EACCES, ENODEV) ne doit plus cacher les autres titres : source [`f31a1bc`](https://github.com/niakw/ProsperoEden-Encore/commit/f31a1bc21c37977e977d34073c4de1509e5e71aa). Le témoin de refus exact en O0/O2 a été activé dans le preflight [`329b2b8`](https://github.com/niakw/ProsperoEden-Encore/commit/329b2b80d9b99bdb855f96b894fed32cfe092f06) ; résultats CI encore à qualifier sur ce SHA. P3.4 global attend toujours la console.
- **P4.2a — hôte validé :** nouveaux cas négatifs GMMU 49 bits, pages 4 KiB et translation physique disjointe [`155f633`](https://github.com/niakw/ProsperoEden-Encore/commit/155f633cb5b4ecce0115e3b5ad127dac48444bdf), [NS2 host #41525695461](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41525695461) réussi en Clang/GCC. OOM GPU, fences et consoles restent ouverts.

**Dernier code observé lors de ce relevé :** parent `329b2b80d9b99bdb855f96b894fed32cfe092f06`, gitlink vendor `32a0ac1bbdea56c5daa19c077c0bd6792844f935`. Aucun build PS5 activé. Pour les statuts de CI et la checklist opposable, conserver l'[issue #15](https://github.com/niakw/ProsperoEden-Encore/issues/15) comme source vivante.


## Frontière P2.2b/P2.2c et verrou P5 — 2026-11-03

- **P2.2b (intégration source)** : l'acquisition réelle des vues TIC/TSC, des samplers et la rétention des ressources Vulkan doivent être cohérentes dans les deux variantes maintenues du cache commun. Les chemins NS1 et NUP ne doivent pas être modifiés pour déclarer le jalon terminé.
- **P2.2c (qualification avant P5)** : finir les cas positifs/négatifs Clang/GCC, les vérifications de provenance et d'ABI C++ avec ASTC/Vulkan, et obtenir les CI hôte pertinentes vertes au même couple SHA main/vendor. Une CI en file d'attente n'est pas une preuve.
- **P5 (qualification console uniquement après P0–P4)** : compilation native PS5 autorisée explicitement, installation, tests FC27/BOTW/MKW/Bananza, métriques GPU/CPU, première vraie image invitée et régressions console. Ces éléments ne sont **pas** des conditions de fermeture de P2.2c avant P5.
- **État de source à ce jalon** : l'interface native ASTC/Vulkan a été alignée au [vendor `d213ec7`](https://github.com/niakw/Prospero.Eden-Encore-vendor/commit/d213ec7630d7fb4f3e4795f711da4c8359ec544c), épinglé depuis [main `b7a7ebe`](https://github.com/niakw/ProsperoEden-Encore/commit/b7a7ebe88ed144081587a9336db6cf01d080a5a5), et les contrôles Clang/GCC ASTC-prioritaires sont ajoutés au [`34007d5`](https://github.com/niakw/ProsperoEden-Encore/commit/34007d5a8e92b92d349f34a338e613d08b4577cf). La [CI #41579773499](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41579773499) était en attente lors du dernier contrôle; **P2.2b/P2.2c non encore fermés**.
