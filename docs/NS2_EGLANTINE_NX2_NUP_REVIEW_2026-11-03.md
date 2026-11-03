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
- `tools/check-nup-v1-payload-host.py` : vérification hôte du hash des **membres** raw/zstd, lecture par blocs de 1 Mio, fenêtre zstd bornée (64 Mio), refus des frames surnuméraires, extents chevauchants, incohérences de déduplication et TLV hors limites. Les extents parfaitement partagés sont vérifiés une seule fois.
- Contrôles structurels additionnels : refus des cycles de répertoires et des flags incohérents pour les mises à jour autonomes. Les arbres mal formés ne peuvent pas être considérés comme valides pour un futur montage VFS.
- CI hôte avec structure **et** intégrité des payloads validée le 3 novembre : https://github.com/niakw/ProsperoEden-Encore/actions/runs/41557420412 (une CI plus récente couvre les cas de déduplication).
- `.github/workflows/nup-v1-host.yml` : vérifie structure, payload et compilation/exécution du VFS C++ hôte. CI validée pour multi-update/AoC et standalone : https://github.com/niakw/ProsperoEden-Encore/actions/runs/41559489576
- Commits : https://github.com/niakw/ProsperoEden-Encore/commit/4cab01fa96f9cd960d3ba6bde1c22e9ce4c399f6 et https://github.com/niakw/ProsperoEden-Encore/commit/a07225c4ce3e7b0caaeab059916e000022699e7e

Conditions d'intégration NUP dans le binaire commun, **sans** activer un chemin incomplet :

1. Un VFS NUP v1 avec validation intégrale TOC/régions/noeuds/chemins/TLV, lecture raw et zstd paresseuse et bornée, hash par fichier et protections contre décompression excessive.
   - Un **module VFS C++ read-only autonome** est désormais présent dans `headless/nup_v1_vfs.{h,cpp}` : montage vérifiant superbloc/TOC/UUID/arbres/extents/TLV, recherche de chemins, raw et zstd paresseux par blocs, SHA-256 intégral avant succès de lecture, protections anti-cycle, superposition de la mise à jour NCM la plus récente et vue des DLC séparée.
   - `tools/nup-v1-vfs-host.cpp` et `tools/check-nup-v1-vfs-host.py` exercent ces invariants sans exécuter le système invité. Les tests couvrent base, multi-updates désordonnées, update autonome, addon isolé, fichier vide, partage d'extent, SHA/fichiers corrompus, frames supplémentaires, noms imbriqués et slots malformés.
   - **Limite structurante : le module C++ est seulement validé sur hôte**. Il n'est pas raccordé à `FileSys::VirtualFile`/`VirtualDir`, au `AppLoader` natif, aux providers AoC, ni au catalogue PS5. Les dépendances crypto/zstd doivent être résolues pour le build natif avant tout raccordement.
2. Un chargeur commun NS1/NS2 qui expose ExeFS + RomFS et overlays base/mise à jour de manière déterministe; gestion de plusieurs updates et des index de DLC via le mécanisme AoC déjà maintenu, sans double application des patches.
3. Détection par **signature** avant tout fallback d'extension, reconnaissance catalogue uniquement lorsque le chargeur accepte réellement le format; ne pas annoncer NUP jouable sur le frontend prématurément.
4. Wiring dans le CMake réel, dans tous les sélecteurs de source NS1/NS2 et la table `FileType`/erreurs, en conservant NSP/XCI/NSZ/XCZ/extracted et le loader NSO PS5 16 KiB.
5. Fixtures synthétiques avec base seule, base+plusieurs updates, update autonome, plusieurs DLC, réutilisation d'extent, noms non sûrs, TOC/payload hash altérés, overflow taille, codecs inconnus, plus test d'intégrité zstd.
6. CI host, tests NS1/NS2, comparaison du contenu exposé avec un dump extrait équivalent; ensuite autorisation séparée d'un build PS5 pour qualification console.
7. Réutiliser le design GPL-compatible d'Eglantine seulement après audit des différences et de la licence; ne pas importer le code de `a55uka/nup` sans confirmation de licence (aucun LICENSE visible dans son arborescence).

## Adaptateur natif — contrats vérifiés, non activés

- Le moteur maintenu expose `FileSys::VfsFile::Read(u8*, size_t, size_t)`, `GetSize()` et `GetName()` dans `vendor/sources/eden/src/core/file_sys/vfs/vfs.h`, et les dossiers en lecture seule via `ReadOnlyVfsDirectory` / `VectorVfsDirectory`. Le futur adaptateur devra conserver la durée de vie du `NupV1::Source` et le propriétaire du fichier; ne pas exposer de pointeur vers un conteneur détruit.
- L'API hôte expose désormais `FindPackageMember`, `FindEffectiveMember`, `ListPackageDirectory` et `ListEffectiveDirectory`. Les deux chemins utilisent l'ordre des versions NCM, sans liste de jeux ni contournement par TitleID; les packages addon restent accessibles individuellement et ne sont pas injectés à tort dans la RomFS principale.
- Les deux fichiers `vendor/encore-active/eden-core/src/core/loader/loader.cpp` et `vendor/encore-active/ns2-experimental/src/core/loader/loader.cpp` ont des sélecteurs qui diffèrent sur le chemin ExeFS, et `vendor/sources/eden/src/core/loader/loader.h` ne déclare pas encore `FileType::NUP`. Le branchement devra pointer sur **un seul** VFS/chargeur NUP commun sans échanger ces sélecteurs en bloc.
- L'adaptateur devra vérifier la disponibilité et la liaison des bibliothèques crypto/zstd dans le profil PS5 avant tout ajout aux cibles CMake. Rien n'a été ajouté au sélecteur `IsGameFile` ni au frontend.
- **Optimisation intégrée sur hôte** : la première `ReadMember` vérifie SHA-256 et taille complète; les appels suivants réutilisent le résultat pour une `Source` contractuellement immuable. Les plages raw sont alors directement accessibles et les plages zstd ne sont décodées que jusqu'à l'offset utile (le décodage repart toujours du début de trame).
- **Performance restante** : ajouter avant tout raccordement PS5 une preuve de source immuable pendant la session (ou une invalidation sur changement), un éventuel cache zstd borné, des tests de contention et des benchmarks sur données volumineuses. La CI hôte de l'optimisation est verte : https://github.com/niakw/ProsperoEden-Encore/actions/runs/41560577238.
- CI hôte des vues et des listes de répertoires : https://github.com/niakw/ProsperoEden-Encore/actions/runs/41560322257 (réussie, C++ compilé et exécuté). **Aucun titre NUP lancé ni test PS5 effectué.**

### Adaptateur FileSys natif inactif — jalon hôte du 3 novembre

- Nouveaux fichiers `headless/nup_v1_native_vfs.{h,cpp}`, non enregistrés dans le loader, sans CMake PS5 ni changement vendor. Ils exposent des `FileSys::VirtualFile` et `VirtualDir` en lecture seule pour ExeFS/RomFS, la vue effective et chaque package (notamment DLC).
- La source `VirtualFile` et l'archive sont retenues dans un état partagé par les fichiers/dossiers enfants; les handles restent lisibles après destruction du `Mount`. Les chemins et index restent ceux déjà validés par le noyau VFS.
- Le moteur NUP offre `AllowsVerifiedMemberCache()`. Pour les sources natives `VfsFile`, il retourne **false** : une propriété `IsWritable() == false` ne garantit pas qu'un fichier externe reste immuable. Donc **SHA-256 complet à chaque lecture**, coûteux mais correct tant qu'aucune politique d'immuabilité n'a été démontrée.
- Tests avec interface native VFS simulée : overlays, update autonome, addon distinct, entrée inexistante, lecture seule, corruption entre deux lectures, durée de vie de la source. CI verte : [#41562364228](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41562364228). Les lectures concurrentes ont ensuite passé la CI [#41562602314](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41562602314). La compilation `-fsyntax-only` contre les cinq vrais en-têtes VFS du vendor épinglé a passé la CI [#41562807128](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41562807128), sans linker le core. Les handles de fichier retiennent désormais fortement leur répertoire parent (`aa75670`), avec test de régression `f8a12d2` en cours.
- **Non prouvé** : link natif du core/bibliothèques PS5, coût des SHA répétés sur de grands jeux, synchronisation avec les chargements NS1/NS2, montage ExeFS ou AoC réel, lancement NUP. Aucun indicateur de jouabilité ne doit être exposé.

- Point chargeur confirmé dans le vendor épinglé : `AppLoader_DeconstructedRomDirectory::ReadRomFS()` utilise un membre `romfs` qui n'est affecté nulle part dans sa source; fournir uniquement un `main` NUP et son dossier ExeFS ne suffit donc **pas** à exposer la RomFS au jeu. Le chemin NUP devra construire/transmettre la RomFS via `FileSys::CreateRomFS` et raccorder le service AoC sans double application de patches.

### Pont natif ExeFS/RomFS — complément du 3 novembre

- `headless/nup_v1_native_content.{h,cpp}` assemble, **sans activation**, les vues VFS communes NS1/NS2 : ExeFS effectif (`main` et `main.npdm` seulement comme présence), RomFS convertissable via l'API **existante** `FileSys::CreateRomFS`, DLC énumérés et convertibles séparément par `package_index`. Les DLC ne sont jamais inclus dans la RomFS effective; il n'y a encore aucun enregistrement AoC.
- `tools/nup-v1-content-fixture.py` produit une archive brute déterministe (pas de contenu commercial), avec base, deux mises à jour d'ordre distinct, ExeFS `main`/`main.npdm`, fusion RomFS imbriquée et deux addons autonomes. `tools/nup-v1-native-host.cpp` vérifie la priorité de la version la plus récente, l'héritage des fichiers de base, les noms, la conservation des parents et deux RomFS de DLC indépendantes.
- Le test **d'exécution hôte** emploie un substitut de sérialiseur RomFS qui rend visibles les noms et contenus transmis. Il ne valide donc **pas** les octets d'une vraie RomFS de Switch. Le contrôle `-fsyntax-only` compile ce code contre les vrais en-têtes `romfs.h` et VFS du vendor épinglé, mais ne lie pas la conversion native. CI [#41576285540](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41576285540), réussie.
- Le chemin `AppLoader_DeconstructedRomDirectory::ReadRomFS` ne fournit toujours pas une RomFS par simple construction du répertoire ExeFS : il faut un raccordement explicite au chargeur NUP (et aux services AoC), éviter la double application de `PatchManager`, puis démontrer le lien crypto/zstd en sélection PS5. La présence de fichiers synthétiques n'est **pas** une preuve de boot NS1 ou NS2.

### Audit AoC natif — restriction réelle du service commun

- Dans le vendor épinglé (`sources/eden/src/core/hle/service/aoc/addon_content_manager.cpp`), `aoc:u` construit sa liste en interrogeant `ContentProvider::ListEntriesFilter(TitleType::AOC, ContentRecordType::Data)`, puis réclame `GetEntry(...)->GetStatus() == Success`. Cette voie suppose actuellement une entrée NCA reconnue. Une RomFS NUP **déjà déchiffrée** ne doit ni être annoncée comme un NCA valide, ni être injectée artificiellement dans le provider NCA.
- `CountAddOnContent` et `ListAddOnContent` filtrent par `FileSys::GetBaseTitleID` et exposent le numéro `GetAOCID` (11 bits). Le pont NUP filtre donc les titres hors base, ne retient que les IDs dans la plage AoC et sélectionne la version NCM maximale de chaque ID pour éviter les doublons. Ce n'est **pas** un service AoC connecté.
- Le raccordement manquant consiste à exposer proprement les RomFS de NUP dans les services fichier/AoC communs, avec leur identité programme et leur durée de vie, sans modifier le fonctionnement des DLC NCA. Les commandes `PrepareAddOnContent`/`NotifyMountAddOnContent` du service existant sont elles-mêmes des stubs : ne pas leur attribuer une preuve de montage effectif.
- Scénarios hôte NUP ajoutés : deux IDs AoC d'une même base, une ancienne/nouvelle version d'un même DLC, et un addon d'un autre titre à exclure. Leur CI propre doit être verte avant fermeture de ce sous-jalon.

### Garde-fou identité des mises à jour

- Au niveau du noyau VFS NUP, `Archive::Parse` refuse désormais qu'un package `update` ait une identité de base différente de celle du package `base` (ou des autres updates autonomes). La comparaison reprend le masque canonique du moteur `FileSys::GetBaseTitleID` et ne porte sur aucun titre de jeu en particulier.
- Cette vérification précède tout montage d'overlay ExeFS/RomFS : une version NCM plus élevée issue d'un autre titre ne peut donc plus masquer `main`, `main.npdm` ou les données du jeu. Les DLC étrangers sont filtrés séparément au niveau du pont AoC.
- CI existante du correctif [#41577121610](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41577121610) réussie. Le nouveau scénario négatif à SHA-256/UUID **valides** mais update d'un autre titre est en attente de sa propre CI [#41577179861](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41577179861). Ne pas le marquer validé avant résultat.

**Limite actuelle : NUP n'est PAS lancé par Encore.** Les contrôles ajoutés sont un prérequis sûr, pas un port complet. P2.2/Vulkan continue indépendamment. Ne fermer aucun jalon GPU ou loader sur une simple réussite du préflight.
