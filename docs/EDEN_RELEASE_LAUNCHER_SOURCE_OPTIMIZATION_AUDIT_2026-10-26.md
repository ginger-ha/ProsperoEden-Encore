# Eden Encore — fin de la première passe d’optimisation du lanceur RELEASE

**26 octobre 2026.** Sur l'unique branche `dev/ps5-sparse-jit`, l'application destinée à l'utilisateur est construite par `tools/build-package.sh release-stage`, avec `EDEN_FINAL_RELEASE_PROFILE=ON`. Les variantes DEV ne sont pas des livrables utilisateur et **ne font pas partie de ce chantier**.

## Portée vérifiée

Inventaire à partir des `git ls-files` actuellement suivis : **507 fichiers sources maintenus**, **448** déjà traités, **59** nouveaux fichiers du lanceur classés ci-dessous. Aucun propriétaire CPU/JIT/GPU/HLE nouveau parmi les 59. Quatre fonctions RELEASE ont nécessité un changement de code (`LocaleCaseCandidates`, `Font::fit`, `Font::wrap`, `distances`); les autres ont une décision de première revue. La revue couvre le périmètre et les principaux chemins; elle **ne démontre ni absence universelle de bugs, ni benchmark FPS, ni revue exhaustive de toutes les branches de chaque fonction**.

Tests source-extraits : `tools/check-release-case-index-dedup-host.py`, `tools/check-release-font-fit-alloc-host.py`, `tools/check-release-font-sdf-scratch-host.py` (`-O0`/`-O2`). Tous doivent passer sur les octets de cette source avant qualification du ZIP release. Les chemins non modifiés sont épinglés à leur blob Git exact : leur modification invalide automatiquement cette première revue lors du contrôle `tools/check-eden-optimization-coverage.py`.

| Source | Blob Git | Décision | Fonction/coût examiné |
| --- | --- | --- | --- |
| `headless/prosperoeden/eden_services.cpp` | `14db2ee513fe6` | Optimisation intégrée + revue Avatar | LocaleCaseCandidates inchangée ; PR #1 ajoute une lecture avatar PS5 optionnelle liée à l'utilisateur, hors boucle de rendu. |
| `headless/prosperoeden/eden_services.h` | `b47c4b8a09e5` | Revue statique | EdenServices API and async media cancellation boundary; interface only. |
| `headless/prosperoeden/fr_fr_embedded.h` | `7ebe8df590bf` | Données/constantes | Embedded French catalog data, not a per-frame algorithm. |
| `headless/prosperoeden/frontend.cpp` | `6b0e980fb727` | Revue statique | RunApp input/render loop, language and capture entry; no further proven hotpath defect. |
| `headless/prosperoeden/frontend.h` | `a2a7f8fffa99` | Revue statique | SelectProsperoEdenGame launcher interface only. |
| `headless/prosperoeden/frontend_stub.cpp` | `386e9893835d` | Revue statique | Headless alternative frontend stub; not the shipping graphical path. |
| `headless/prosperoeden/host/fake_services.cpp` | `f8f44ed15e49` | Test hôte | Fixture README : suppression du héros synthétique uniquement sous PE_PREVIEW_BRANDED_HOME ; hors moteur PS5. |
| `headless/prosperoeden/host/fake_services.hpp` | `414360bf0fb1` | Test hôte | FakeServices host contract declarations; not PS5 runtime. |
| `headless/prosperoeden/host/preview_main.cpp` | `84ef0e1466b1` | Test hôte | Preview Stage render/press/screenshot scripting, including timed waits, host-only. |
| `headless/prosperoeden/pe/audio/mixer.cpp` | `6b814bbd5e3e` | Revue statique | Mixer::render/command bus, bounded live voice and command processing; no proven redundant native work. |
| `headless/prosperoeden/pe/audio/mixer.hpp` | `73bac058eccd` | Revue statique | Mixer command/voice fields and audio callback interface. |
| `headless/prosperoeden/pe/audio/sounds.cpp` | `3fec935a1a77` | Revue statique | SoundBank::load occurs during startup; play posts cue through mixer. |
| `headless/prosperoeden/pe/audio/sounds.hpp` | `8818b3923e5f` | Revue statique | Static sound cue and sample ownership declarations. |
| `headless/prosperoeden/pe/audio/stream_ring.hpp` | `85a3d6e4209b` | Optimisation intégrée, CI à qualifier | Deux copies `memcpy` contiguës au plus par accès ; suppression du modulo par échantillon, publication SPSC préservée. Témoin `tools/check-ps5-launcher-audio-stream-ring-host.py` O0/O2 ASan/UBSan ; gain console non mesuré. |
| `headless/prosperoeden/pe/audio/wav.cpp` | `9f04abce17f6` | Revue statique | decode_wav PCM parser called on sound load, not each audio callback. |
| `headless/prosperoeden/pe/audio/wav.hpp` | `ecc8a878f7c2` | Revue statique | DecodedWav representation and decode signature. |
| `headless/prosperoeden/pe/core/file.hpp` | `63e01611dfc5` | Revue statique | read_file bounded to configured max size and only called by loaders. |
| `headless/prosperoeden/pe/core/log.hpp` | `de37255b2a8c` | Revue statique | printf-style diagnostic helper; no steady-state processing logic. |
| `headless/prosperoeden/pe/core/strings.cpp` | `2a1578e80c09` | Revue statique | Catalog::load and translation lookup; key normalization and UTF-8 fallback only. |
| `headless/prosperoeden/pe/core/strings.hpp` | `3916b4a8366d` | Revue statique | Catalog dictionary and translation API; non-renderer declarations. |
| `headless/prosperoeden/pe/core/tween.hpp` | `a1aa75b026eb` | Revue statique | Inline cubic/expo easing and scalar interpolation only. |
| `headless/prosperoeden/pe/gfx/bidi.cpp` | `bfe3552274b5` | Revue statique | Bidi::resolve/visual_order Unicode grapheme and bracket ordering; preserve correctness. |
| `headless/prosperoeden/pe/gfx/bidi.hpp` | `2f938e9fb0ee` | Revue statique | Bidirectional text shaping interfaces only. |
| `headless/prosperoeden/pe/gfx/draw_list.cpp` | `5bcba9105df3` | Revue statique | DrawList grouping/rounded-rectangle primitives produce batched instance runs. |
| `headless/prosperoeden/pe/gfx/draw_list.hpp` | `864b70c350a9` | Revue statique | DrawList reusable vectors and clip/transform stack declarations. |
| `headless/prosperoeden/pe/gfx/font.cpp` | `1d7c2e186ac4` | Optimisation intégrée | Font::fit reuses one UTF-8 prefix; Font::wrap removes copied word/glyph candidates using bounded append/rollback (O0/O2 equivalence). |
| `headless/prosperoeden/pe/gfx/font.hpp` | `0a129cd37e16` | Revue statique | Font atlas/dynamic layout declarations and shaping cache ownership. |
| `headless/prosperoeden/pe/gfx/font_format.hpp` | `cc807dc31fbf` | Revue statique | Packed immutable font/glyph format definitions. |
| `headless/prosperoeden/pe/gfx/gl_batch.hpp` | `e881358bb08a` | Revue statique | GL stream slot/capacity and one batch submission API; renderer cpp already reviewed. |
| `headless/prosperoeden/pe/gfx/gl_program.cpp` | `6aa10a3f064b` | Revue statique | GL shader compile/link startup helper; not frame-loop compilation. |
| `headless/prosperoeden/pe/gfx/gl_program.hpp` | `102dbe5c0739` | Revue statique | GL shader program creation API. |
| `headless/prosperoeden/pe/gfx/harfbuzz.cpp` | `b65200e2af41` | Revue statique | External text shaping implementation shim; no app-owned hot loop. |
| `headless/prosperoeden/pe/gfx/image.cpp` | `296809efb6b1` | Revue statique | TGA and DDS decode plus halve; image decoding moved to async cover worker. |
| `headless/prosperoeden/pe/gfx/image.hpp` | `95e1d43c2690` | Revue statique | Image pixel buffer and decode functions. |
| `headless/prosperoeden/pe/gfx/stream_ring_policy.hpp` | `91cd2ead70c1` | Revue statique | StreamCapacity growth policy; amortized buffer sizing. |
| `headless/prosperoeden/pe/gfx/system_fonts.cpp` | `a721c95a81c9` | Optimisation intégrée | distances() SDF scratch now TLS reused across glyphs/inside/outside; O0/O2 reference witness. |
| `headless/prosperoeden/pe/gfx/system_fonts.hpp` | `4a4baaa602f6` | Revue statique | SystemFonts glyph fallback and face selection declarations. |
| `headless/prosperoeden/pe/platform/audio_out.cpp` | `2b8a12c86119` | Revue statique | AudioOut::run uses fixed hardware grain and Mixer::render output. |
| `headless/prosperoeden/pe/platform/audio_out.hpp` | `060842253e01` | Revue statique | AudioOut worker lifecycle counters and channel declarations. |
| `headless/prosperoeden/pe/platform/display_egl.cpp` | `a31fb6db8799` | Revue statique | Display::swap/open/close EGL surface boundary; native GL batch owns drawing. |
| `headless/prosperoeden/pe/platform/display_egl.hpp` | `7438f8f6fa10` | Revue statique | EGL display lifecycle surface and error signatures. |
| `headless/prosperoeden/pe/ui/browse.cpp` | `96afbbbae783` | Revue statique | browse_to/press_files/draw_files path browser; disk navigation not guest GPU hotpath. |
| `headless/prosperoeden/pe/ui/case_media_selection.hpp` | `34fd91455575` | Re-revue + témoin hôte | `FrontPaperAvailable` ne saute que les images confirmées absentes ; priorité des décodages en attente et références sans copie conservées. |
| `headless/prosperoeden/pe/ui/dualsense_mask_asset.hpp` | `ba9a3d15e7cf` | Données/constantes | Immutable inline controller-mask artwork; no runtime decode/search. |
| `headless/prosperoeden/pe/ui/hero_text_layout.hpp` | `9e76a77e987b` | Revue statique | wrap_description word-boundary layout, weak endings; bounded by hero text. |
| `headless/prosperoeden/pe/ui/home.cpp` | `a40fd7f010aa` | Revue statique | refresh_home_hero/press_home and home draw, reused current game media. |
| `headless/prosperoeden/pe/ui/launcher.cpp` | `f7e26bfc8131` | Revue statique | Avatar : sonde stat/fingerprint dans le worker async ; refresh 5 s, aucune lecture de fichier dans la boucle de rendu. |
| `headless/prosperoeden/pe/ui/launcher.hpp` | `821992032a8c` | Revue statique | Future typée ProfileAvatarProbe et état d'invalidation ; worker et teardown conservés. |
| `headless/prosperoeden/pe/ui/mapping.cpp` | `2ce53b13a38b` | Revue statique | Button mapping UI, profile names and input binding page. |
| `headless/prosperoeden/pe/ui/services.hpp` | `3d26738cbf0f` | Revue statique | Services abstract media and title interface; no implementation allocation. |
| `headless/prosperoeden/pe/ui/settings.cpp` | `be3b42b9740e` | Revue statique | Settings press/render/dialog and preference labels; no frame-blocking I/O identified. |
| `headless/prosperoeden/pe/ui/switch_theme.cpp` | `f852926a48bc` | Revue statique | Switch-theme tile/advanced panel drawing via reused DrawList painter. |
| `headless/prosperoeden/pe/ui/theme.hpp` | `fc7b378ab519` | Revue statique | Inline color/text sizing and visual easing policy. |
| `headless/prosperoeden/pe/ui/video_presets.hpp` | `05a735ec7b05` | Revue statique | Inline profile lookup/compare with no disk or GPU work. |
| `headless/prosperoeden/pe/ui/widgets.cpp` | `7b50467e172a` | Revue statique | Canvas text/box/case-face drawing functions; batched GL and cover queries. |
| `headless/prosperoeden/pe/ui/widgets.hpp` | `1b31fd1a9e39` | Revue statique | Widget layout/color/cover interfaces only. |
| `headless/prosperoeden/ps5_profile_avatar_staging.hpp` | `bb125e8b2331` | Revue statique + témoin hôte | Nouveau lecteur de marqueur propriétaire : utilisateur/format exacts, O_NOFOLLOW, taille bornée ; aucune écriture ; test check-ps5-avatar-dds-host.py, console non qualifiée. |
| `headless/prosperoeden/radio_input.c` | `e42b0ba4c27f` | Revue statique | Pad polling and bounded edge-event translation; no network/disk dependency. |
| `headless/prosperoeden/radio_input.h` | `e994a36c5a1d` | Revue statique | Pad polling/event API declarations. |
| `headless/prosperoeden/version.h` | `6b0dd31b2266` | Données/constantes | Canonical package/app version constants only. |

## Ce qui n'est pas clos

Cette première passe est un **audit de couverture du code**. Les saccades du jeu, la fraîcheur du HUD, les verrous GPU, la qualité d'antialiasing et le comportement PS5 restent des critères indépendants, non certifiés par ces 60 décisions. Ne pas compter les fichiers inactifs ou hôte comme des FPS optimisés.
## 2026-10-30 — standalone repository URL-only revalidation

The new official repository is `niakw/ProsperoEden-Encore`. The single change to `headless/prosperoeden/pe/ui/browse.cpp` replaces the old GitHub URL shown in the launcher About screen. Verification compared complete file contents against the previously reviewed Git blob `96afbbbae783279625e88c18e39ec1115f2b4730` and proved that replacing exactly `github.com/niakw/Prospero.Eden-Encore` with `github.com/niakw/ProsperoEden-Encore` reproduces the current source byte-for-byte (Git blob `1f48fc883e2930704275b16e9333e33b1793d517`). **No other C++ logic, performance path or graphics/PS5 runtime change occurred.** The coverage ledger has been repinned to the new blob, retaining the exact-source invariant.


## Nouvelle vérification du preview OpenGL (2026-11-01)

- Source : `headless/prosperoeden/host/preview_main.cpp`, blob Git `e1576cbf8a41a34fdd58e387062316fb95a40350` (précédent `e62c5d2b656016b6dfc0675b88c8379c039f7c72`).
- Changement revu : le scénario hôte `PE_PREVIEW_LIBRARY_FALLBACK` sélectionne la onzième jaquette par dix appuis directionnels `Right` au lieu de deux `R1`, qui changent maintenant l'onglet principal.
- Portée : **test de prévisualisation hôte uniquement**. Aucun chemin PS5 native, shader, GPU, threading ou JIT modifié ; aucune baisse des exigences de vérification pixel, cadrage, zoom ou texture.
- Qualification attendue : contrôler les tests de preview et la couverture d'optimisation F07 ; cette revue de source ne prétend pas mesurer ni améliorer les performances FC27 ou NS2 sur console.

## Revue additionnelle du 2 novembre 2026 — recherche du scan NS2

- `headless/prosperoeden/eden_services.cpp`, blob Git `8a25564b3588720d4e9e78c699f495d137272f09` (précédemment `b8aeeafb7c8ce6d9993a34498e9701d851d7df12`). Pour un TitleID déjà répertorié par `Ns2Catalog`, l'enrichissement cherche les véritables scans LaunchBox avec le nom canonique en premier ; exemple : `DonkeyKongBananza` contre `Donkey Kong Bananza`. Ce choix intervient hors du rendu et avant les appels Nlib.
- Le fallback des jeux NS1 et des titres inconnus est inchangé. Le fichier de référence F07 conserve exactement 518 sources, dont cette unique empreinte revue, les 517 autres restant intactes.
- `tools/check-launch-case-artwork.py` vérifie le branchement, `tools/check-release-case-index-dedup-host.py` garde la preuve de déduplication. **Aucun FPS, téléchargement console ni image NS2 prouvés**.

## Revue preview hôte — zoom réel 130 % (2 novembre 2026)

- `headless/prosperoeden/host/preview_main.cpp` : `e87eb1f64bcbc24e8d6263df493064d79dcbbd3f` (précédemment `e1576cbf8a41a34fdd58e387062316fb95a40350`). Le scénario de reconstruction sans scans appelle désormais `Cross` puis `R2` pour vérifier le passage du viewer de 100 % à 130 %. Si le viewer n'ouvre pas, `R2` n'a aucun effet et le contrôle d'écart entre pixels doit encore échouer.
- **Aucun seuil relâché** : variabilité des trois régions au-dessus de 17 et différence des images zoomées/non zoomées au-dessus de 4 restent exigées dans `.github/workflows/launcher-production-preview.yml`.
- Changement strictement dans le scénario de prévisualisation hôte ; aucune modification du code d'entrée PS5. La CI du nouveau SHA reste la preuve requise.

## Revue preview asynchrone — 2 novembre 2026

- **Source de la prévisualisation hôte** : `headless/prosperoeden/host/preview_main.cpp`, blob Git `76ad9a17f9f57c23012e8199914132fcf8bf93cb` (précédemment `e87eb1f64bcbc24e8d6263df493064d79dcbbd3f`).
- **Défaut ciblé** : les appels `wait(2.0f)` simulent 120 frames sans attendre 2 secondes réelles ; un runner peut donc acheminer dix touches Right avant la publication de la liste de ROM.
- **Correction de test** : le premier Right doit produire un `Cue::focus` réel, avec un plafond de 120 tentatives et 25 ms de délai de travail entre les tentatives. Les neuf Right restants atteignent toujours l'index 10. Échec explicite si la liste n'est pas navigable. La navigation console et les contrôles des pixels de la preview sont inchangés.
- **Statut** : revue de source et empreinte F07 mise à jour ; qualification sur le nouveau SHA encore requise.

## Re-revue du sélecteur de jaquettes après fallback média (2 novembre 2026)

- **Source exacte :** `headless/prosperoeden/pe/ui/case_media_selection.hpp`, Git blob `34fd91455575949f539eeb0dd884c13add5992e4` (ancien `3a3ddb5916701487537e6670f4ebc56b4d4d9716`), introduit par `cfce4b32c9689c531f9d720f65881806684ef571`. La nouvelle fonction `FrontPaperAvailable` sélectionne par références des sources réellement déjà en cache : elle ne remplace le héros que lorsque son chargement est confirmé manquant. Les décodages encore en attente restent éligibles. Les chemins NS1 et NS2 partagent ce fallback ; pas de fetch réseau, copie de chaînes ni modification du parcours normal `FrontPaper` / `BackScenes`.
- **Témoin réel :** `tools/check-encore-case-media-selection-host.py` exerce les cas héros absent, capture alternative, icône et héros encore disponible, avec les sources C++ sélectionnées ; le job `source-ux` **réussi** `125474453091` de la [prévalidation #41502592263](https://github.com/niakw/ProsperoEden-Encore/actions/runs/41502592263) a produit `ENCORE_CASE_MEDIA_DEDUP_PASS` en `clang++`, `g++` et `c++`, `-O0/-O2` sur `90be0df2baa5824ec86740b9a6481fd122b51c90`. Le rendu OpenGL de prévisualisation est également vert sur ce SHA.
- **Portée :** re-revue stricte de provenance après changement de code ; aucune optimisation F07 P0/P1, performance console, fraîcheur HUD ni validation FW13.60 revendiquée. Le garde `check-eden-optimization-coverage.py` conserve la comparaison du blob Git courant et les 518 propriétaires historiques.

## Revue du scénario OpenGL asynchrone — 2 novembre 2026

- **Échec confirmé** : preview #41517911320 produit ses trois PNG sans erreur GL mais ne déclenche pas le viewer (690 instances après Cross/R2, contre 779 pour la preview réussie #41502142950). Le signal `Cue::focus` peut provenir de l'accueil et ne prouve pas la présence dans la bibliothèque.
- **Correctif** : `Launcher::preview_home_ready()` et `preview_library_ready(11)` sont deux requêtes d'état constantes sans effet de bord. Le test attend une véritable Home chargée, navigue vers Library, attend une liste publiée contenant au moins onze jeux, puis utilise dix touches Right. Attente bornée de 160 × 25 ms par étape avec échec explicite ; la capture et les trois seuils OpenGL stricts sont conservés.
- **Empreintes exactes** : `headless/prosperoeden/pe/ui/launcher.hpp` `b2c81fda94c172cee2b7edbe69bc128a0f09a061` ; `headless/prosperoeden/host/preview_main.cpp` `899058e87797cb17416f676e05547cd5bb825e9b`. Deux entrées de source F07 revues ; aucun build PS5 et aucune amélioration FPS revendiqués.

## P3.4 — revue de l'inventaire ROM natif après disparition temporaire du stockage (2 novembre 2026)

- **Source exacte :** `headless/prosperoeden/eden_services.cpp` blob `25ca7e5b026598461aa07a5db8bda0b1860cf7b3` (ancien `8a25564b3588720d4e9e78c699f495d137272f09`). Le correctif [`f31a1bc`](https://github.com/niakw/ProsperoEden-Encore/commit/f31a1bc21c37977e977d34073c4de1509e5e71aa) conserve la capture précédente lorsque `stat(path)` échoue pour une raison qui ne prouve pas l'absence du titre : `EIO`, `EACCES`, `ENODEV`, etc. Seuls `ENOENT` et `ENOTDIR` sont ignorés pour un fichier disparu ; la cause `errno` est capturée avant toute opération de journalisation et l'exception est traitée par `Launcher::finish_scan` sans remplacer `games_`. Un dossier ROM absent en fin de scan est déjà intercepté dans le worker après [`664b7f0`](https://github.com/niakw/ProsperoEden-Encore/commit/664b7f0a18e3134efb444cd5d2562a5cfe02a368), y compris au tout premier inventaire.
- **Témoins :** [`329b2b8`](https://github.com/niakw/ProsperoEden-Encore/commit/329b2b80d9b99bdb855f96b894fed32cfe092f06) exécute dans le source-preflight le C++ extrait de la condition d'échec `stat` (`-O0/-O2`) et du contrôle de disponibilité du volume. `check-nlib-ui-recovery.py` vérifie également le contrat, sans être utilisé comme seul oracle.
- **Périmètre :** aucune suppression du scanner de titres, de la sélection locale des jaquettes, des langues ou des ajustements régionaux. Pas d'I/O ajouté au rendu OpenGL ni au thread UI, aucune modification de la mémoire guest ou du renderer. La validation console et le dernier run complet source/hôte restent nécessaires ; ce re-stamp signifie **provenance source inspectée**, pas « P3.4 terminé » ni gain FPS.


## P3.2 — revue ciblée du catalogue de secours de jaquettes NS2 (3 novembre 2026)

- **Source examinée :** `headless/prosperoeden/eden_services.cpp` blob Git `37725334676fa201a1caea099544331df6001e76` (précédent `25ca7e5b026598461aa07a5db8bda0b1860cf7b3`), changement publié dans [`55dd40e`](https://github.com/niakw/ProsperoEden-Encore/commit/55dd40e97ba24aeb2a0d90993ccb3d60f50558d0). La fonction `RetailCaseIndex()` est initialisée une seule fois (statique) ; la lecture des métadonnées TSV de secours intervient après l'index complet. Un jeu déjà indexé garde chaque face existante, seules les faces vides sont complétées. Aucun accès réseau, parcours de ROM ni décodage OpenGL pendant la construction de la table ; aucun code GPU, mémoire invité ou répertoire utilisateur modifié. `LocaleCaseCandidates` et les garde-fous `SafeCaseCandidate` sont inchangés.
- **Périmètre de performance :** deux entrées de secours mises en paquet, parsing/copie de vecteurs sur initialisation du cache seulement. Pas d'impact par frame identifié ; allocation ponctuelle de métadonnées, pas d'optimisation FPS revendiquée. Une image de jaquette reste téléchargée par le worker existant, non dans le thread de rendu. Si les ressources distantes échouent, le fallback d'image procédural reste actif.
- **Témoin :** `tools/check-launch-case-artwork.py` vérifie les signatures du TSV additionnel, sa lecture après le catalogue principal et l'absence d'images embarquées. Les échecs du `source-early` sur `55dd40e` et `37eb5c7` provenaient de l'empreinte F07 historique non révisée ; cette revue met à jour la provenance, **sans transformer les essais console ou les images de CDN en succès prouvés**.

## Revue P3.2 du 3 novembre 2026 — recto de secours et dos sans doublon

Objet actuel `headless/prosperoeden/pe/ui/case_media_selection.hpp` : `59f1f95c6eb497c94ddc9640145f98f25c808190`. Dans `BackScenes(featured, cover, screenshots, usable)`, la catégorie arrière exclut désormais l'image renvoyée par **`FrontPaperAvailable`** avec le même prédicat de décodage, plutôt que `FrontPaper` qui pouvait retenir un Hero existant mais inutilisable. Un appel direct avec l'ancienne image de Hero et une première capture défectueuse n'insère donc plus la vraie capture de secours parmi les scènes arrière. La sélection reste sans copie, sans I/O réseau, avec trois emplacements fixes et le même comportement pour le prédicat 3-arguments toujours disponible. Le témoin `tools/check-encore-case-media-selection-host.py` teste les deux cas : Hero refusé, ou absence de Hero avec première capture refusée. C'est une correction du composant commun NS1/NS2, **pas** une preuve du rendu du boîtier sur PS5 (P5).
