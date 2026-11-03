# Audit de reprise — Eglantine `nx2`, Fire Emblem et NUP v1 (2026-11-03)

## Périmètre et protection du travail concurrent

- Dépôt cible unique : `niakw/ProsperoEden-Encore`, branche `main`, vendor épinglé `niakw/Prospero.Eden-Encore-vendor`. Aucun branchement de fonctionnalité ni build PS5 automatique.
- L'autre conversation poursuit P2.2 sur le GPU Vulkan/Ampere : ne pas remplacer le chargeur natif, les sources de textures, le buffer cache, le shader recompiler, les sélecteurs CMake ni le gitlink pendant ces évolutions sans relecture des nouveaux HEAD.
- Les titres cités en amont sont des scénarios de reproduction. Aucun contournement par TitleID, nom de jeu, empreinte de programme, scène, profil caché ou extension trompeuse n'est acceptable.

## Références examinées

- Eglantine `nx2` HEAD `3bdd53d08adfd96b7e3e3f09344c514540ef1ce6` (2026-11-02) : https://github.com/zortos293/Eglantine/commits/nx2/
- PR #20, dont `62bc7538b119b3b5a8105ce9195b04ef626ec4ae` : https://github.com/zortos293/Eglantine/pull/20
- Upscale / jitter `b9d6b4a71ee0ff4fb6bf89699746ccaf3086c030` : https://github.com/zortos293/Eglantine/commit/b9d6b4a71ee0ff4fb6bf89699746ccaf3086c030
- Ordonnancement GPU `fae3bc64a90940a809993c3ceef4eb1f5d98b93e` : https://github.com/zortos293/Eglantine/commit/fae3bc64a90940a809993c3ceef4eb1f5d98b93e
- Readback / pacing `5bef7354b464a38527864756814cc6e0f0fc6567` : https://github.com/zortos293/Eglantine/commit/5bef7354b464a38527864756814cc6e0f0fc6567
- Implémentations NUP amont : `src/core/file_sys/nup_container.{h,cpp}`, `src/core/loader/nup.{h,cpp}`, `src/core/file_sys/nup_writer.{h,cpp}`, et tests `src/tests/core/nup_writer.cpp`.
- Spécification NUP v1 du projet `a55uka/nup` (branche `meow`) : https://github.com/a55uka/nup/blob/meow/SPEC.md

## Verdict de reprise — générique uniquement

| Amont | Décision | Contrôle avant intégration |
| --- | --- | --- |
| IDP.2A.LO, IADD3.X, LDGSTS.E.BYPASS.128, FSET/HSET2/TXD/TXQ et surfaces / matrices HMMA | À comparer aux chemins Ampere existants, ports ciblés seulement | Tests décodage/opérandes, IR/SPIR-V, `spirv-val`, compilation hôte, Maxwell inchangé |
| Provenance des handles bindless, SSA et couples sampler/image | Fort candidat pour P2.2, mais source propriétaire déjà maintenue dans le vendor | Validation canal/process/génération + TIC/TSC/CBUF, tests remap/unmap |
| Tables de constantes natives 24–31, null buffer sur CBUF désactivé | Fort candidat GPU correctness | Conservation des ressources par dispatch, rejet explicite si adresse invalide |
| Command snapshot après synchronisation (`fae3bc64`) | Candidat prioritaire à auditer | Drain du producteur avant inspection dirty, ordre DMA/fence, absence de stale snapshot |
| Readback page/fence/queue (`5bef7354`) | Candidat conditionnel, **pas de copie globale** | Comparaison avec protections PS5 existantes, tests aliasing/générations, preuve de performance |
| Réutilisation uploads uniformes, vues tables, VRAM | Optimisations secondaires | Aucune invalidation ignorée, durée de vie GPU et budget bornés, essais NS1/NS2 |
| VI2 display queries 104–107/354 | À comparer aux HLE native NS2 et réponses existantes | Contrat IPC exact, requêtes mal formées, aucun stub de réussite générique |
| Upscaler spatial/jitter `b9d6b4a` et `FE_UPSCALE_STANDIN.md` | **Rejet du patch tel quel** : filtrage par TitleID + fingerprint, correction ad hoc | N'accepter qu'un mécanisme général prouvé sur les mêmes entrées et les autres titres |
| Lichii rebranding/packaging et fixes CI desktop | Non pertinent pour PS5 et sans rapport avec le moteur | Ne pas récupérer |
| NUP v1 | Préflight générique déjà introduit; lecteur VFS/loader et DLC à développer séparément | Voir section suivante |

L'amont rapporte qu'un écran est rendu localement, **pas** une validation de gameplay. Le document `FE_UPSCALE_STANDIN.md` décrit un contournement lié au TitleID `04007EF01F8AE000` et à l'empreinte `14b4222bbe23abee` ; le candidat de dé-jitter n'a pas été validé en partie sur une scène identique. Le journal `MKW_UPSTREAM_AUDIT_2026-11-02.md` note des saccades avec un correctif de readback ; une optimisation de synchronisation ne doit pas être fusionnée sur foi d'un nom de commit.

## NUP v1 — intégration réelle nécessaire

La spec décrit une archive de dumps **déjà déchiffrés**, indifférente à la génération de console : signature `NUP\\x01`, superbloc `0x80`, TOC hachée SHA-256, enregistrements de package `0x40`, de dossier `0x18`, de fichier `0x50`, extents par fichier raw/zstd, métadonnées TLV et packages base/updates/addon. NUP n'est ni NCA ni une nouvelle méthode de déchiffrement.

État Encore constaté à l'audit :
- `headless/game_files.h` indexe les conteneurs NSP/NSZ/XCI/XCZ et les dumps extraits, **pas NUP**.
- `encore-active/eden-core/src/core/loader/loader.cpp` sélectionné pour les wrappers compressés ne reconnaît pas NUP ; le header du moteur `sources/eden/src/core/loader/loader.h` et le CMake du moteur ne le déclarent pas non plus.
- Le chemin NS2 ExeFS peut choisir une autre source maintenue `encore-active/ns2-experimental/src/core/loader/loader.cpp` sous sélecteur CMake. Les deux chemins doivent utiliser une **même** implémentation testée, sans double lecteur.
- L'implémentation Eglantine `AppLoader_NUP` utilise son loader ExeFS de branche et **n'installe pas encore les DLC**. Porter quatre fichiers ne suffirait pas.
- L'amont signalait une assertion de hash du **writer NUP** non résolue (ligne 391 de son test) dans sa suite complète, donc ne pas importer le writer ou déclarer une conversion fiable sans la réparer.

Déjà livré sans risque d'interférence :
- `tools/check-nup-v1-host.py` : vérification de structure/TOC, chemins/offsets, packages, UUID. Les tests injectent cinq corruptions. Ne vérifie **pas** les hash SHA-256 des fichiers décompressés et ne lance aucun logiciel invité.
- `.github/workflows/nup-v1-host.yml` : exécute `--self-test` sur hôte. Run **réussi** : https://github.com/niakw/ProsperoEden-Encore/actions/runs/41555437627
- Commits : https://github.com/niakw/ProsperoEden-Encore/commit/4cab01fa96f9cd960d3ba6bde1c22e9ce4c399f6 et https://github.com/niakw/ProsperoEden-Encore/commit/a07225c4ce3e7b0caaeab059916e000022699e7e

Conditions d'intégration NUP dans le binaire commun, **sans** activer un chemin incomplet :

1. Un VFS NUP v1 avec validation intégrale TOC/régions/noeuds/chemins/TLV, lecture raw et zstd paresseuse et bornée, hash par fichier et protections contre décompression excessive.
2. Un chargeur commun NS1/NS2 qui expose ExeFS + RomFS et overlays base/mise à jour de manière déterministe; gestion de plusieurs updates et des index de DLC via le mécanisme AoC déjà maintenu, sans double application des patches.
3. Détection par **signature** avant tout fallback d'extension, reconnaissance catalogue uniquement lorsque le chargeur accepte réellement le format; ne pas annoncer NUP jouable sur le frontend prématurément.
4. Wiring dans le CMake réel, dans tous les sélecteurs de source NS1/NS2 et la table `FileType`/erreurs, en conservant NSP/XCI/NSZ/XCZ/extracted et le loader NSO PS5 16 KiB.
5. Fixtures synthétiques avec base seule, base+plusieurs updates, update autonome, plusieurs DLC, réutilisation d'extent, noms non sûrs, TOC/payload hash altérés, overflow taille, codecs inconnus, plus test d'intégrité zstd.
6. CI host, tests NS1/NS2, comparaison du contenu exposé avec un dump extrait équivalent; ensuite autorisation séparée d'un build PS5 pour qualification console.
7. Réutiliser le design GPL-compatible d'Eglantine seulement après audit des différences et de la licence; ne pas importer le code de `a55uka/nup` sans confirmation de licence (aucun LICENSE visible dans son arborescence).

**Limite actuelle : NUP n'est PAS lancé par Encore.** Les contrôles ajoutés sont un prérequis sûr, pas un port complet. P2.2/Vulkan continue indépendamment. Ne fermer aucun jalon GPU ou loader sur une simple réussite du préflight.
