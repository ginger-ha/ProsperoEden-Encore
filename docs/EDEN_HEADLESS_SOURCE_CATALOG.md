# Eden Encore — catalogue des fichiers C/C++ hors encore-active : headless

**Branche :** `dev/ps5-sparse-jit`. **Date du relevé :** 30 octobre 2026.

Ce registre complémentaire couvre les **178 chemins** de code, en-têtes et
fragments `.c/.cc/.cpp/.h/.hpp/.inc/.cl` du dossier `headless/`.
Il ne remplace pas `EDEN_ACTIVE_SOURCE_CATALOG.md` : les 326 fichiers
de `vendor/encore-active` sont déjà inventoriés séparément.

**Attention :** une entrée ici ne prouve pas que le fichier est compilé ni
qu'une fonction s'exécute sur console. `launcher/UI` est simplement identifié
pour suivi séparé et n'autorise aucune modification du launcher depuis
l'audit moteur. Un chemin noté « À qualifier » peut avoir été audité sous
une autre forme : il manque seulement la référence de chemin exacte.

- **178** chemins sous `headless/`, dont **60** sources C/C++ et **118** en-têtes/fragments.
- **97** chemins déjà présents dans le graphe moteur.
- **81** chemins sans propriétaire exact dans ce graphe, à trier selon leur rôle réel et leur sélection.
- Les deux générateurs de profils `headless/encore_overrides_generated.h`,
  `headless/glyph_overrides_generated.h` et les autres ressources générées
  sont des entrées de l'inventaire, **pas** de nouveaux patchs CMake.

### Répartition des chemins sans propriétaire de fonction exact

Ce décompte distingue l'incomplétude du **graphe de fonctions** des
déplacements de sources réellement nécessaires. Le registre physique couvre
toujours 176/177 chemins ; il n'y a pas 80 overrides de dépendances oubliés.

| Rôle indicatif | Chemins sans ID exact |
| --- | ---: |
| `launcher/UI` | **65** |
| `harness/test` | **10** |
| `outil auxiliaire` | **4** |
| `données générées` | **2** |
| `en-tête/fragment` | **0** |
| **Total non indexé** | **81** |

Les 65 chemins du launcher sont réservés au périmètre UI séparé.
Les 10 harnais, 4 outils et 2 ressources générées ne sont pas déclarés
comme unités de correction moteur. `ps5_amd_topology_evidence.h` porte désormais l'ID U79 au statut
**PARKED** : ses fonctions sont inventoriées, mais le commit d'origine
`45f9c01` précise « no runtime pinning ». Aucun consommateur natif
n'est revendiqué, aucun test matériel n'est prétendu et ce fichier ne
doit pas être confondu avec un override de dépendance compilé. Les **17 unités `runtime/bridge`** sont toutes rattachées à
un ID exact ; cela reste une preuve documentaire, pas une preuve
d'exécution sur console.

Quarante-cinq en-têtes applicatifs supplémentaires sont désormais rattachés
à leurs consommateurs et à des contrats vérifiables par
`tools/check-headless-runtime-header-owners.py` et
`tools/check-headless-app-policy-owners.py` et
`tools/check-headless-specialized-owners.py` et
`tools/check-headless-final-owners.py`. Ce classement ne les
transforme pas en overrides des dépendances ni en preuves d'exécution PS5.

Le contrôle `tools/check-active-source-inventory.py` confronte les chemins
physiques, la table ci-dessous et les propriétaires du graphe ; il interdit
que des fichiers C/C++ apparaissent dans `headless/` sans être ajoutés
à cette table.

<!-- HEADLESS_SOURCE_CATALOG_START -->
| Chemin | Domaine indicatif | IDs du graphe (chemin exact) | Statut documentaire |
| --- | --- | --- | --- |
| `headless/assets_dir.h` | en-tête/fragment | U46 | Chemin indexé, preuve dépend du graphe |
| `headless/audio.cpp` | runtime/bridge | U04 | Chemin indexé, preuve dépend du graphe |
| `headless/audio_out_init.h` | en-tête/fragment | U47 | Chemin indexé, preuve dépend du graphe |
| `headless/boot_trace.h` | en-tête/fragment | U34 | Chemin indexé, preuve dépend du graphe |
| `headless/buffer_pages.h` | en-tête/fragment | R05 | Chemin indexé, preuve dépend du graphe |
| `headless/buffer_write_ahead.h` | en-tête/fragment | R06 | Chemin indexé, preuve dépend du graphe |
| `headless/button_mapping.h` | en-tête/fragment | U66 | Chemin indexé, preuve dépend du graphe |
| `headless/cache_budget.h` | en-tête/fragment | U28 | Chemin indexé, preuve dépend du graphe |
| `headless/controller_applet.h` | en-tête/fragment | U58 | Chemin indexé, preuve dépend du graphe |
| `headless/crash_report.cpp` | runtime/bridge | U11 | Chemin indexé, preuve dépend du graphe |
| `headless/crash_report.h` | en-tête/fragment | U48 | Chemin indexé, preuve dépend du graphe |
| `headless/crash_site.h` | en-tête/fragment | U27 | Chemin indexé, preuve dépend du graphe |
| `headless/crash_trigger.h` | en-tête/fragment | U49 | Chemin indexé, preuve dépend du graphe |
| `headless/dev_launch_policy.h` | en-tête/fragment | U50 | Chemin indexé, preuve dépend du graphe |
| `headless/dev_replay_policy.h` | en-tête/fragment | U45 | Chemin indexé, preuve dépend du graphe |
| `headless/dev_vulkan.h` | en-tête/fragment | U59 | Chemin indexé, preuve dépend du graphe |
| `headless/development_input.h` | en-tête/fragment | U51 | Chemin indexé, preuve dépend du graphe |
| `headless/devices.h` | en-tête/fragment | U52 | Chemin indexé, preuve dépend du graphe |
| `headless/devices_check.cpp` | harness/test | — | À qualifier |
| `headless/diagnostics.h` | en-tête/fragment | U36 | Chemin indexé, preuve dépend du graphe |
| `headless/direct_pool_accounting.h` | en-tête/fragment | U32 | Chemin indexé, preuve dépend du graphe |
| `headless/direct_pool_probe_policy.h` | en-tête/fragment | U43 | Chemin indexé, preuve dépend du graphe |
| `headless/direct_pool_region_scan.h` | en-tête/fragment | U44 | Chemin indexé, preuve dépend du graphe |
| `headless/display_refresh.h` | en-tête/fragment | U53 | Chemin indexé, preuve dépend du graphe |
| `headless/elevation/elevation.cpp` | outil auxiliaire | — | À qualifier |
| `headless/elevation/elevation.hpp` | outil auxiliaire | — | À qualifier |
| `headless/elevation/helper/main.cpp` | outil auxiliaire | — | À qualifier |
| `headless/elevation/protocol.hpp` | outil auxiliaire | — | À qualifier |
| `headless/encore_overrides_generated.h` | données générées | — | À qualifier |
| `headless/encore_overrides_runtime.h` | en-tête/fragment | U54 | Chemin indexé, preuve dépend du graphe |
| `headless/encore_performance_policy.h` | en-tête/fragment | U55 | Chemin indexé, preuve dépend du graphe |
| `headless/error_applet.h` | en-tête/fragment | U60 | Chemin indexé, preuve dépend du graphe |
| `headless/experimental_performance.h` | en-tête/fragment | U23 | Chemin indexé, preuve dépend du graphe |
| `headless/extracted_npdm_identity.h` | en-tête/fragment | U87 | Chemin indexé, preuve dépend du graphe |
| `headless/fastmem_handler.cpp` | runtime/bridge | J07 | Chemin indexé, preuve dépend du graphe |
| `headless/firmware_zip_import.h` | en-tête/fragment | U88 | Chemin indexé, preuve dépend du graphe |
| `headless/filesystem_probe.h` | en-tête/fragment | U35 | Chemin indexé, preuve dépend du graphe |
| `headless/frame_metrics.h` | en-tête/fragment | U86 | Chemin indexé, preuve dépend du graphe |
| `headless/game_files.h` | en-tête/fragment | U82 | Chemin indexé, preuve dépend du graphe |
| `headless/game_liveness.h` | en-tête/fragment | U67 | Chemin indexé, preuve dépend du graphe |
| `headless/glyph_overrides_generated.h` | données générées | — | À qualifier |
| `headless/glyph_overrides_runtime.h` | en-tête/fragment | U61 | Chemin indexé, preuve dépend du graphe |
| `headless/glyph_sha256.h` | en-tête/fragment | U68 | Chemin indexé, preuve dépend du graphe |
| `headless/glyph_version.h` | en-tête/fragment | U69 | Chemin indexé, preuve dépend du graphe |
| `headless/gpu_deferred_replay.h` | en-tête/fragment | M02 | Chemin indexé, preuve dépend du graphe |
| `headless/gpu_deferred_store_publication.h` | en-tête/fragment | M05 | Chemin indexé, preuve dépend du graphe |
| `headless/gpu_deferred_write_queue.h` | en-tête/fragment | U21 | Chemin indexé, preuve dépend du graphe |
| `headless/gpu_dirty_region_split.h` | en-tête/fragment | R04 | Chemin indexé, preuve dépend du graphe |
| `headless/gpu_failure.h` | en-tête/fragment | U20 | Chemin indexé, preuve dépend du graphe |
| `headless/gpu_fault_rate_limit.h` | en-tête/fragment | U25 | Chemin indexé, preuve dépend du graphe |
| `headless/gpu_native_probe.inc` | en-tête/fragment | U31 | Chemin indexé, preuve dépend du graphe |
| `headless/gpu_probe.inc` | en-tête/fragment | U30 | Chemin indexé, preuve dépend du graphe |
| `headless/graphics.cpp` | runtime/bridge | V11 | Chemin indexé, preuve dépend du graphe |
| `headless/graphics.h` | en-tête/fragment | U19 | Chemin indexé, preuve dépend du graphe |
| `headless/guest_fault.h` | en-tête/fragment | U26 | Chemin indexé, preuve dépend du graphe |
| `headless/heap_pages.cpp` | runtime/bridge | U02 | Chemin indexé, preuve dépend du graphe |
| `headless/hle_counters.h` | en-tête/fragment | U56 | Chemin indexé, preuve dépend du graphe |
| `headless/hud.h` | en-tête/fragment | U57 | Chemin indexé, preuve dépend du graphe |
| `headless/image_pages.h` | en-tête/fragment | U70 | Chemin indexé, preuve dépend du graphe |
| `headless/jit-allocator.h` | en-tête/fragment | J06 | Chemin indexé, preuve dépend du graphe |
| `headless/jit-sparse-commit.h` | en-tête/fragment | J05 | Chemin indexé, preuve dépend du graphe |
| `headless/jit-startup-retry.h` | en-tête/fragment | U22 | Chemin indexé, preuve dépend du graphe |
| `headless/jit_list.h` | en-tête/fragment | J11 | Chemin indexé, preuve dépend du graphe |
| `headless/log_pipe.h` | en-tête/fragment | U37 | Chemin indexé, preuve dépend du graphe |
| `headless/main.cpp` | runtime/bridge | U01 | Chemin indexé, preuve dépend du graphe |
| `headless/memory_check.cpp` | harness/test | J08 | Chemin indexé, preuve dépend du graphe |
| `headless/metadata_bridge.cpp` | runtime/bridge | U13 | Chemin indexé, preuve dépend du graphe |
| `headless/metadata_bridge.h` | en-tête/fragment | U14 | Chemin indexé, preuve dépend du graphe |
| `headless/mock_devices.cpp` | harness/test | — | À qualifier |
| `headless/mock_devices.h` | harness/test | — | À qualifier |
| `headless/mods.h` | en-tête/fragment | U62 | Chemin indexé, preuve dépend du graphe |
| `headless/mods_check.cpp` | harness/test | — | À qualifier |
| `headless/native_directory.h` | en-tête/fragment | U41 | Chemin indexé, preuve dépend du graphe |
| `headless/ncz.cpp` | runtime/bridge | U83 | Chemin indexé, preuve dépend du graphe |
| `headless/ncz.h` | en-tête/fragment | U84 | Chemin indexé, preuve dépend du graphe |
| `headless/ncz_check.cpp` | harness/test | — | À qualifier |
| `headless/ncz_vfs.h` | en-tête/fragment | U85 | Chemin indexé, preuve dépend du graphe |
| `headless/network_audit.c` | runtime/bridge | U05 | Chemin indexé, preuve dépend du graphe |
| `headless/network_audit.h` | en-tête/fragment | U39 | Chemin indexé, preuve dépend du graphe |
| `headless/network_audit_sockets.c` | runtime/bridge | U06 | Chemin indexé, preuve dépend du graphe |
| `headless/network_domain_rules.c` | runtime/bridge | U07 | Chemin indexé, preuve dépend du graphe |
| `headless/network_domain_rules.h` | en-tête/fragment | U38 | Chemin indexé, preuve dépend du graphe |
| `headless/pad.cpp` | runtime/bridge | U03 | Chemin indexé, preuve dépend du graphe |
| `headless/pad_diagnostics.h` | en-tête/fragment | U71 | Chemin indexé, preuve dépend du graphe |
| `headless/performance.cpp` | runtime/bridge | J01 | Chemin indexé, preuve dépend du graphe |
| `headless/performance.h` | en-tête/fragment | U24 | Chemin indexé, preuve dépend du graphe |
| `headless/pipeline_trace_registry.h` | en-tête/fragment | U72 | Chemin indexé, preuve dépend du graphe |
| `headless/preferences.h` | en-tête/fragment | U73 | Chemin indexé, preuve dépend du graphe |
| `headless/preferences_check.cpp` | harness/test | — | À qualifier |
| `headless/present_interval_witness.h` | en-tête/fragment | U42 | Chemin indexé, preuve dépend du graphe |
| `headless/prosperoeden/eden_services.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/eden_services.h` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/fr_fr_embedded.h` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/frontend.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/frontend.h` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/frontend_stub.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/host/fake_services.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/host/fake_services.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/host/preview_main.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/audio/mixer.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/audio/mixer.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/audio/sounds.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/audio/sounds.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/audio/stream_ring.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/audio/wav.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/audio/wav.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/core/file.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/core/log.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/core/strings.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/core/strings.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/core/tween.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/bidi.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/bidi.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/draw_list.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/draw_list.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/font.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/font.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/font_format.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/gl_batch.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/gl_batch.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/gl_program.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/gl_program.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/harfbuzz.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/image.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/image.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/stream_ring_policy.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/system_fonts.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/gfx/system_fonts.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/platform/audio_out.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/platform/audio_out.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/platform/display_egl.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/platform/display_egl.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/browse.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/case_media_selection.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/dualsense_mask_asset.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/hero_text_layout.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/home.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/launcher.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/launcher.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/library.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/mapping.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/services.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/settings.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/switch_theme.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/textures.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/textures.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/theme.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/video_presets.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/widgets.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/pe/ui/widgets.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/ps5_profile_avatar_staging.hpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/radio_input.c` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/radio_input.h` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/runtime_shims.cpp` | launcher/UI | — | À qualifier |
| `headless/prosperoeden/version.h` | launcher/UI | — | À qualifier |
| `headless/ps5_amd_topology_evidence.h` | en-tête/fragment | U79 | Chemin indexé, preuve dépend du graphe |
| `headless/ps5_cpu_topology.h` | en-tête/fragment | U33 | Chemin indexé, preuve dépend du graphe |
| `headless/ps5_guest_system_button_route.h` | en-tête/fragment | U74 | Chemin indexé, preuve dépend du graphe |
| `headless/ps5_net_compat.c` | runtime/bridge | U08 | Chemin indexé, preuve dépend du graphe |
| `headless/romfs_check.cpp` | harness/test | — | À qualifier |
| `headless/ryujinx_check.cpp` | harness/test | — | À qualifier |
| `headless/ryujinx_saves.h` | en-tête/fragment | U63 | Chemin indexé, preuve dépend du graphe |
| `headless/scalar_check.cpp` | harness/test | — | À qualifier |
| `headless/sdk_audit.h` | en-tête/fragment | U64 | Chemin indexé, preuve dépend du graphe |
| `headless/settings_store.h` | en-tête/fragment | U75 | Chemin indexé, preuve dépend du graphe |
| `headless/shader_cache_check.cpp` | harness/test | — | À qualifier |
| `headless/stall_watchdog.h` | en-tête/fragment | U29 | Chemin indexé, preuve dépend du graphe |
| `headless/stop_limit.cpp` | runtime/bridge | U15 | Chemin indexé, preuve dépend du graphe |
| `headless/stop_limit.h` | en-tête/fragment | U16 | Chemin indexé, preuve dépend du graphe |
| `headless/storage_paths.h` | en-tête/fragment | U76 | Chemin indexé, preuve dépend du graphe |
| `headless/title_id_fallback.h` | en-tête/fragment | U40 | Chemin indexé, preuve dépend du graphe |
| `headless/vulkan_allocator.cpp` | runtime/bridge | U10 | Chemin indexé, preuve dépend du graphe |
| `headless/vulkan_gc_budget.h` | en-tête/fragment | U77 | Chemin indexé, preuve dépend du graphe |
| `headless/vulkan_pool_capacity.h` | en-tête/fragment | U78 | Chemin indexé, preuve dépend du graphe |
| `headless/vulkan_surface.cpp` | runtime/bridge | U09 | Chemin indexé, preuve dépend du graphe |
| `headless/watch.h` | en-tête/fragment | U65 | Chemin indexé, preuve dépend du graphe |
| `headless/zbic_compression.cpp` | runtime/bridge | U17 | Chemin indexé, preuve dépend du graphe |
| `headless/zbic_compression.h` | en-tête/fragment | U18 | Chemin indexé, preuve dépend du graphe |
<!-- HEADLESS_SOURCE_CATALOG_END -->

## Interfaces critiques du moteur qualifiées au niveau des chemins

Douze interfaces de `headless/` ont un propriétaire précis dans le graphe
(`U22–U33`) et un consommateur vérifié par
`tools/check-headless-critical-interface-owners.py`. Ce sont des
composants **de l'application**, non des overrides de sources vendor.
Les déplacements vers `encore-active` seraient ici une erreur de
séparation des responsabilités. Le test contrôle les inclusions directes
(JIT A32/A64, runtime, watchdog, comptabilité mémoire et diagnostics GPU)
et les gardes DEV/probe ; il ne prouve pas leur exécution console.

La majorité des chemins restants sans entrée fonctionnelle comprend des
modules de launcher, des harnais de test et des interfaces applicatives.
Ils demeurent inventoriés, mais ne sont pas déclarés comme correctifs
moteur ni comme preuves de performance.

## Priorités de qualification

La priorité technique se porte sur les unités `runtime/bridge`,
`JIT/expérimental`, les en-têtes réellement sélectionnés et les
fonctions CPU/GPU/mémoire ; les fichiers du launcher restent dans
le chantier UI indépendant. Les programmes de test ne doivent pas être
confondus avec des overrides de production. Une source réellement sélectionnée
avec un comportement corrigé doit acquérir une entrée fonctionnelle
dans `EDEN_CORE_AUDIT_DEPENDENCIES.md`, puis une preuve indépendante.
