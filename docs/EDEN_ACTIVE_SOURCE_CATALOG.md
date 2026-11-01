# Eden Encore — inventaire exhaustif des sources actives

**Branche :** `main` + recherche NS2. **Relevé :** 31 octobre 2026.

Cet inventaire recense chaque fichier C/C++, en-tête, fragment source et
source OpenCL (`.c`, `.cpp`, `.h`, `.hpp`, `.inc`, `.cl` et variantes voisines)
présent sous `vendor/encore-active`. Il est généré depuis l'arbre réel
et contrôlé par `tools/check-active-source-inventory.py`.

- **337 fichiers** de code et d'en-têtes enregistrés (hors 108 sources NS2 expérimentales, suivies séparément).
- **335 fichiers** possèdent une correspondance exacte avec le registre des fonctions (dont les propriétaires AOC F46–F49).
- **2 fichiers** n'ont pas d'ID de graphe historique : les deux en-têtes partagés suivis par `tools/install-eden-header-hygiene.py` et contrôlés octet par octet avec le snapshot Eden immuable.
- Cet inventaire ne prouve pas le comportement sur console.
- Le manifeste des backports verrouille **83 fichiers livrés**, dont
  **83 fichiers C/C++ enregistrés ci-dessous** et **deux fichiers CMake**
  listés séparément. Les **43 reçus de patches** sont conservés.
- Les `shipping-backport` sont des sources de backports de production, matérialisées en fichiers
  complets et installées dans un arbre épinglé par `tools/install-vendored-eden-backports.py` avec
  contrôle d'empreintes, sans replay `git apply` pendant le build ;
  `driver-fork` représente la dépendance graphique modifiée ;
  `maintained-override` les unités et en-têtes Encore.

**Important :** une correspondance de chemin n'est ni un test hôte,
ni une certification console. Le graphe
`docs/EDEN_CORE_AUDIT_DEPENDENCIES.md` porte les contrats fonctionnels,
leurs états et les preuves. L'inventaire du générateur CMake principal G23,
d'aucun générateur secondaire, d'aucun module indirect actif et des 46 patches
reste dans `docs/EDEN_OVERRIDE_MIGRATION_INVENTORY.md`.

<!-- ACTIVE_SOURCE_CATALOG_START -->
| Chemin relatif à `vendor/encore-active/` | Famille | IDs du graphe (chemin exact) |
| --- | --- | --- |
| `compiler-rt/emutls.c` | `maintained-override` | B04 |
| `eden-backports/src/audio_core/audio_render_manager.cpp` | `shipping-backport` | A06 |
| `eden-backports/src/common/logging.cpp` | `shipping-backport` | F30 |
| `eden-backports/src/common/net/net.cpp` | `shipping-backport` | F31 |
| `eden-backports/src/common/settings.cpp` | `shipping-backport` | F32 |
| `eden-backports/src/common/settings.h` | `shipping-backport` | F33 |
| `eden-backports/src/common/settings_enums.h` | `shipping-backport` | F34 |
| `eden-backports/src/core/device_memory_manager.h` | `shipping-backport` | M12 |
| `eden-backports/src/core/device_memory_manager.inc` | `shipping-backport` | M13 |
| `eden-backports/src/core/file_sys/system_archive/system_version.cpp` | `shipping-backport` | F19 |
| `eden-backports/src/core/frontend/applets/controller.cpp` | `shipping-backport` | H41 |
| `eden-backports/src/core/hle/api_version.h` | `shipping-backport` | F25 |
| `eden-backports/src/core/hle/kernel/k_scheduler.cpp` | `shipping-backport` | H37 |
| `eden-backports/src/core/hle/kernel/k_slab_heap.h` | `shipping-backport` | H42 |
| `eden-backports/src/core/hle/kernel/k_thread.h` | `shipping-backport` | H38 |
| `eden-backports/src/core/hle/kernel/svc/svc_info.cpp` | `shipping-backport` | H43 |
| `eden-backports/src/core/hle/kernel/svc_types.h` | `shipping-backport` | H44 |
| `eden-backports/src/core/hle/service/acc/acc.cpp` | `shipping-backport` | H45 |
| `eden-backports/src/core/hle/service/acc/acc.h` | `shipping-backport` | H46 |
| `eden-backports/src/core/hle/service/am/display_layer_manager.cpp` | `shipping-backport` | N18 |
| `eden-backports/src/core/hle/service/am/frontend/applets.cpp` | `shipping-backport` | L01 |
| `eden-backports/src/core/hle/service/am/lifecycle_manager.h` | `shipping-backport` | H47 |
| `eden-backports/src/core/hle/service/am/service/application_creator.cpp` | `shipping-backport` | F22 |
| `eden-backports/src/core/hle/service/am/service/library_applet_accessor.cpp` | `shipping-backport` | L02 |
| `eden-backports/src/core/hle/service/am/service/library_applet_creator.cpp` | `shipping-backport` | L03 |
| `eden-backports/src/core/hle/service/am/service/self_controller.cpp` | `shipping-backport` | L04 |
| `eden-backports/src/core/hle/service/am/service/self_controller.h` | `shipping-backport` | L05 |
| `eden-backports/src/core/hle/service/audio/audio.cpp` | `shipping-backport` | A07 |
| `eden-backports/src/core/hle/service/bcat/bcat.cpp` | `shipping-backport` | L06 |
| `eden-backports/src/core/hle/service/bpc/bpc.cpp` | `shipping-backport` | L07 |
| `eden-backports/src/core/hle/service/filesystem/filesystem.cpp` | `shipping-backport` | F20 |
| `eden-backports/src/core/hle/service/filesystem/fsp/fsp_srv.cpp` | `shipping-backport` | F21 |
| `eden-backports/src/core/hle/service/filesystem/fsp/fsp_srv.h` | `shipping-backport` | F26 |
| `eden-backports/src/core/hle/service/glue/arp.cpp` | `shipping-backport` | L08 |
| `eden-backports/src/core/hle/service/glue/glue.cpp` | `shipping-backport` | L09 |
| `eden-backports/src/core/hle/service/grc/grc.cpp` | `shipping-backport` | L10 |
| `eden-backports/src/core/hle/service/hid/hid_system_server.cpp` | `shipping-backport` | L11 |
| `eden-backports/src/core/hle/service/ldr/ldr.cpp` | `shipping-backport` | L12 |
| `eden-backports/src/core/hle/service/nfp/nfp.cpp` | `shipping-backport` | L13 |
| `eden-backports/src/core/hle/service/ngc/ngc.cpp` | `shipping-backport` | L14 |
| `eden-backports/src/core/hle/service/nifm/nifm.cpp` | `shipping-backport` | N17 |
| `eden-backports/src/core/hle/service/ns/application_manager_interface.cpp` | `shipping-backport` | F23 |
| `eden-backports/src/core/hle/service/ns/application_manager_interface.h` | `shipping-backport` | F27 |
| `eden-backports/src/core/hle/service/ns/i_async_result.cpp` | `shipping-backport` | F28 |
| `eden-backports/src/core/hle/service/ns/i_async_result.h` | `shipping-backport` | F29 |
| `eden-backports/src/core/hle/service/ns/ns.cpp` | `shipping-backport` | L15 |
| `eden-backports/src/core/hle/service/ns/read_only_application_control_data_interface.cpp` | `shipping-backport` | L16 |
| `eden-backports/src/core/hle/service/nvdrv/devices/nvmap.cpp` | `shipping-backport` | N11 |
| `eden-backports/src/core/hle/service/nvnflinger/buffer_queue_core.cpp` | `shipping-backport` | N12 |
| `eden-backports/src/core/hle/service/nvnflinger/buffer_queue_core.h` | `shipping-backport` | N14 |
| `eden-backports/src/core/hle/service/olsc/transfer_task_list_controller.cpp` | `shipping-backport` | L17 |
| `eden-backports/src/core/hle/service/olsc/transfer_task_list_controller.h` | `shipping-backport` | L18 |
| `eden-backports/src/core/hle/service/pctl/parental_control_service.cpp` | `shipping-backport` | L19 |
| `eden-backports/src/core/hle/service/pctl/parental_control_service.h` | `shipping-backport` | L20 |
| `eden-backports/src/core/hle/service/pctl/pctl_types.h` | `shipping-backport` | L21 |
| `eden-backports/src/core/hle/service/pm/pm.cpp` | `shipping-backport` | L22 |
| `eden-backports/src/core/hle/service/ro/ro.cpp` | `shipping-backport` | L23 |
| `eden-backports/src/core/hle/service/set/settings.cpp` | `shipping-backport` | F24 |
| `eden-backports/src/core/hle/service/sm/sm.cpp` | `shipping-backport` | L24 |
| `eden-backports/src/core/hle/service/sockets/bsd.cpp` | `shipping-backport` | N15 |
| `eden-backports/src/core/hle/service/sockets/bsd.h` | `shipping-backport` | N16 |
| `eden-backports/src/core/hle/service/sockets/encore_guest_network_policy.h` | `shipping-backport` | N09 |
| `eden-backports/src/core/hle/service/sockets/sfdnsres.cpp` | `shipping-backport` | N13 |
| `eden-backports/src/core/hle/service/sockets/sockets.cpp` | `shipping-backport` | L25 |
| `eden-backports/src/core/hle/service/usb/usb.cpp` | `shipping-backport` | L26 |
| `eden-backports/src/core/hle/service/wlan/wlan.cpp` | `shipping-backport` | L27 |
| `eden-backports/src/core/memory.cpp` | `shipping-backport` | M14 |
| `eden-backports/src/hid_core/resources/npad/npad.cpp` | `shipping-backport` | H40 |
| `eden-backports/src/video_core/buffer_cache/buffer_cache.h` | `shipping-backport` | V51 |
| `eden-backports/src/video_core/buffer_cache/buffer_cache_base.h` | `shipping-backport` | V53 |
| `eden-backports/src/video_core/control/channel_state_cache.h` | `shipping-backport` | V57 |
| `eden-backports/src/video_core/dma_pusher.cpp` | `shipping-backport` | V60 |
| `eden-backports/src/video_core/engines/kepler_compute.cpp` | `shipping-backport` | V58 |
| `eden-backports/src/video_core/engines/kepler_compute.h` | `shipping-backport` | V59 |
| `eden-backports/src/video_core/engines/sw_blitter/blitter.cpp` | `shipping-backport` | V63 |
| `eden-backports/src/video_core/fence_manager.h` | `shipping-backport` | V56 |
| `eden-backports/src/video_core/query_cache/query_cache.h` | `shipping-backport` | V55 |
| `eden-backports/src/video_core/renderer_vulkan/vk_buffer_cache.cpp` | `shipping-backport` | V50 |
| `eden-backports/src/video_core/renderer_vulkan/vk_buffer_cache.h` | `shipping-backport` | V62 |
| `eden-backports/src/video_core/texture_cache/texture_cache.h` | `shipping-backport` | V52 |
| `eden-backports/src/video_core/texture_cache/texture_cache_base.h` | `shipping-backport` | V54 |
| `eden-backports/src/video_core/texture_cache/util.cpp` | `shipping-backport` | V61 |
| `eden-build/openssl/cert.h` | `maintained-override` | B28 |
| `eden-build/third_party/xbyak/xbyak.h` | `maintained-override` | J40 |
| `eden-build/tooling/native/app_crt_radv.cpp` | `maintained-override` | B05 |
| `eden-build/tooling/native/app_heap_arenas.c` | `maintained-override` | B06 |
| `eden-build/tooling/native/app_heap_flat.c` | `maintained-override` | B07 |
| `eden-build/tooling/native/heap_guard.h` | `maintained-override` | B08 |
| `eden-core/dynarmic/scalar/scalar-fold.inc` | `maintained-override` | J27 |
| `eden-core/dynarmic/scalar/scalar-memory-read.inc` | `maintained-override` | J28 |
| `eden-core/dynarmic/scalar/scalar-memory-write.inc` | `maintained-override` | J29 |
| `eden-core/dynarmic/shared-jit/a64_jitstate.h` | `maintained-override` | J42 |
| `eden-core/dynarmic/shared-jit/callback.cpp` | `maintained-override` | J43 |
| `eden-core/dynarmic/shared-jit/jit_group.h` | `maintained-override` | J21 |
| `eden-core/dynarmic/shared-jit/jit_group_support.inc` | `maintained-override` | J22 |
| `eden-core/dynarmic/shared-jit/jit_impl.inc` | `maintained-override` | J23 |
| `eden-core/dynarmic/shared-jit/jit_links.inc` | `maintained-override` | J24 |
| `eden-core/dynarmic/shared-jit/jit_push_rsb.inc` | `maintained-override` | J25 |
| `eden-core/dynarmic/shared-jit/jit_state_args.inc` | `maintained-override` | J26 |
| `eden-core/gpu-injections/gpu_sync_failure_wait.inc` | `maintained-override` | V73 |
| `eden-core/guest-bridge/dma_pusher.cpp` | `maintained-override` | V95 |
| `eden-core/guest-bridge/engine_upload.cpp` | `maintained-override` | V94 |
| `eden-core/guest-bridge/gpu_dirty_memory_manager.h` | `maintained-override` | V90 |
| `eden-core/guest-bridge/kepler_compute.cpp` | `maintained-override` | V93 |
| `eden-core/guest-bridge/maxwell_dma.cpp` | `maintained-override` | V92 |
| `eden-core/guest-bridge/memory_manager.cpp` | `maintained-override` | V91 |
| `eden-core/guest-bridge/memory_manager.h` | `maintained-override` | V89 |
| `eden-core/guest-bridge/memory_ps5_a32.cpp` | `maintained-override` | V99 |
| `eden-core/guest-bridge/memory_ps5_standard.cpp` | `maintained-override` | W01 |
| `eden-core/guest-bridge/vulkan_rasterizer.cpp` | `maintained-override` | V96 |
| `eden-core/host-gpu/include/video_core/gpu_thread.h` | `maintained-override` | Q09 |
| `eden-core/include/core/file_sys/bis_factory.h` | `maintained-override` | F13 |
| `eden-core/overrides/core/device_memory_manager.inc` | `maintained-override` | M08 |
| `eden-core/overrides/core/gpu_dirty_memory_manager.h` | `maintained-override` | M09 |
| `eden-core/overrides/core/guest_memory.h` | `maintained-override` | M10 |
| `eden-core/overrides/core/hle/service/sockets/encore_guest_network_policy.h` | `maintained-override` | N10 |
| `eden-core/overrides/slot-vector/common/slot_vector.h` | `maintained-override` | B03,V64 |
| `eden-core/src/audio_core/renderer/voice/voice_info.cpp` | `maintained-override` | A04 |
| `eden-core/src/audio_core/sink/sink_details.cpp` | `maintained-override` | A05 |
| `eden-core/src/audio_core/sink/sink_stream.cpp` | `maintained-override` | A03 |
| `eden-core/src/common/assert.h` | `maintained-override` | F18 |
| `eden-core/src/common/cpu_features.cpp` | `maintained-override` | F07 |
| `eden-core/src/common/fiber.cpp` | `maintained-override` | J18 |
| `eden-core/src/common/fs/fs.cpp` | `maintained-override` | F06 |
| `eden-core/src/common/fs/path_util.cpp` | `maintained-override` | F08 |
| `eden-core/src/common/logging.cpp` | `maintained-override` | F17 |
| `eden-core/src/common/sparse_large_vector.h` | `maintained-override` | J34 |
| `eden-core/src/common/thread.cpp` | `maintained-override` | F05 |
| `eden-core/src/core/arm/dynarmic/arm_dynarmic_32.cpp` | `maintained-override` | J20 |
| `eden-core/src/core/arm/dynarmic/arm_dynarmic_64.cpp` | `maintained-override` | J19 |
| `eden-core/src/core/arm/dynarmic/g11/arm_dynarmic_32_host_dev.cpp` | `maintained-override` | J44 |
| `eden-core/src/core/arm/dynarmic/g11/arm_dynarmic_32_host_normal.cpp` | `maintained-override` | J45 |
| `eden-core/src/core/arm/dynarmic/g11/arm_dynarmic_32_native_dev.cpp` | `maintained-override` | J46 |
| `eden-core/src/core/arm/dynarmic/g11/arm_dynarmic_32_native_normal.cpp` | `maintained-override` | J47 |
| `eden-core/src/core/arm/dynarmic/g11/arm_dynarmic_64_host_dev.cpp` | `maintained-override` | J48 |
| `eden-core/src/core/arm/dynarmic/g11/arm_dynarmic_64_host_normal.cpp` | `maintained-override` | J49 |
| `eden-core/src/core/arm/dynarmic/g11/arm_dynarmic_64_native_dev.cpp` | `maintained-override` | J50 |
| `eden-core/src/core/arm/dynarmic/g11/arm_dynarmic_64_native_normal.cpp` | `maintained-override` | J51 |
| `eden-core/src/core/core_native.cpp` | `maintained-override` | F40 |
| `eden-core/src/core/core_standard.cpp` | `maintained-override` | F39 |
| `eden-core/src/core/file_sys/bis_factory.cpp` | `maintained-override` | F14 |
| `eden-core/src/core/file_sys/card_image.cpp` | `maintained-override` | F42 |
| `eden-core/src/core/file_sys/extracted_aoc.h` | `maintained-override` | F46 |
| `eden-core/src/core/file_sys/extracted_aoc_paths.h` | `maintained-override` | F47 |
| `eden-core/src/core/file_sys/fsmitm_romfsbuild.cpp` | `maintained-override` | F12 |
| `eden-core/src/core/file_sys/ips_layer.cpp` | `maintained-override` | F37 |
| `eden-core/src/core/file_sys/patch_manager.cpp` | `maintained-override` | F35 |
| `eden-core/src/core/file_sys/registered_cache.cpp` | `maintained-override` | F43 |
| `eden-core/src/core/file_sys/romfs_factory.cpp` | `maintained-override` | F48 |
| `eden-core/src/core/file_sys/savedata_factory.cpp` | `maintained-override` | F15 |
| `eden-core/src/core/file_sys/submission_package.cpp` | `maintained-override` | F41 |
| `eden-core/src/core/hle/kernel/k_page_table_base.cpp` | `maintained-override` | B27 |
| `eden-core/src/core/hle/kernel/k_process.cpp` | `maintained-override` | H53 |
| `eden-core/src/core/hle/kernel/k_spin_lock.cpp` | `maintained-override` | H30 |
| `eden-core/src/core/hle/kernel/kernel_dev.cpp` | `maintained-override` | V106 |
| `eden-core/src/core/hle/kernel/kernel_standard.cpp` | `maintained-override` | V105 |
| `eden-core/src/core/hle/kernel/physical_core_dev.cpp` | `maintained-override` | B26 |
| `eden-core/src/core/hle/kernel/physical_core_standard.cpp` | `maintained-override` | B25 |
| `eden-core/src/core/hle/kernel/svc/svc_ipc.cpp` | `maintained-override` | H21 |
| `eden-core/src/core/hle/kernel/svc/svc_ipc_standard.cpp` | `maintained-override` | U80 |
| `eden-core/src/core/hle/service/am/service/application_functions.cpp` | `maintained-override` | H32 |
| `eden-core/src/core/hle/service/aoc/addon_content_manager.cpp` | `maintained-override` | F49 |
| `eden-core/src/core/hle/service/audio/audio_controller.cpp` | `maintained-override` | A10 |
| `eden-core/src/core/hle/service/audio/audio_controller.h` | `maintained-override` | A11 |
| `eden-core/src/core/hle/service/filesystem/filesystem.cpp` | `maintained-override` | F11 |
| `eden-core/src/core/hle/service/filesystem/fsp/fs_i_file.cpp` | `maintained-override` | F02 |
| `eden-core/src/core/hle/service/filesystem/fsp/fs_i_filesystem.cpp` | `maintained-override` | F04 |
| `eden-core/src/core/hle/service/filesystem/fsp/fs_i_storage.cpp` | `maintained-override` | F03 |
| `eden-core/src/core/hle/service/nvdrv/core/container.cpp` | `maintained-override` | N07 |
| `eden-core/src/core/hle/service/nvdrv/devices/ioctl_serialization.h` | `maintained-override` | N22 |
| `eden-core/src/core/hle/service/nvdrv/devices/nvhost_ctrl.cpp` | `maintained-override` | N02,N05 |
| `eden-core/src/core/hle/service/nvnflinger/buffer_queue_consumer.cpp` | `maintained-override` | N24 |
| `eden-core/src/core/hle/service/nvnflinger/buffer_queue_producer.cpp` | `maintained-override` | N03 |
| `eden-core/src/core/hle/service/server_manager.cpp` | `maintained-override` | H56 |
| `eden-core/src/core/hle/service/server_manager.h` | `maintained-override` | H54 |
| `eden-core/src/core/hle/service/server_manager_dev.cpp` | `maintained-override` | H57 |
| `eden-core/src/core/hle/service/server_manager_dev.h` | `maintained-override` | H55 |
| `eden-core/src/core/hle/service/service.cpp` | `maintained-override` | H22,H28 |
| `eden-core/src/core/hle/service/sm/sm.h` | `maintained-override` | H51 |
| `eden-core/src/core/hle/service/sockets/bsd.cpp` | `maintained-override` | N20 |
| `eden-core/src/core/hle/service/sockets/sfdnsres.cpp` | `maintained-override` | N21 |
| `eden-core/src/core/hle/service/vi/conductor.cpp` | `maintained-override` | F36 |
| `eden-core/src/core/internal_network/network.cpp` | `maintained-override` | N19 |
| `eden-core/src/core/internal_network/network_interface.cpp` | `maintained-override` | F10 |
| `eden-core/src/core/loader/deconstructed_rom_directory.cpp` | `maintained-override` | F16 |
| `eden-core/src/core/loader/loader.cpp` | `maintained-override` | F44 |
| `eden-core/src/core/loader/nso.cpp` | `maintained-override` | F38 |
| `eden-core/src/core/loader/nsp.cpp` | `maintained-override` | F45 |
| `eden-core/src/core/memory.cpp` | `maintained-override` | M11 |
| `eden-core/src/core/memory_native_a32.cpp` | `maintained-override` | V98 |
| `eden-core/src/core/memory_native_standard.cpp` | `maintained-override` | V97 |
| `eden-core/src/dynarmic/backend/block_range_information.cpp` | `maintained-override` | U12 |
| `eden-core/src/dynarmic/backend/block_range_information.h` | `maintained-override` | J41 |
| `eden-core/src/dynarmic/backend/x64/a32_emit_x64.cpp` | `maintained-override` | B12 |
| `eden-core/src/dynarmic/backend/x64/a32_emit_x64_memory.cpp` | `maintained-override` | B19 |
| `eden-core/src/dynarmic/backend/x64/a32_interface_native.cpp` | `maintained-override` | B24 |
| `eden-core/src/dynarmic/backend/x64/a64_emit_x64_memory.cpp` | `maintained-override` | B20 |
| `eden-core/src/dynarmic/backend/x64/a64_emit_x64_shared.cpp` | `maintained-override` | B14 |
| `eden-core/src/dynarmic/backend/x64/a64_emit_x64_shared.h` | `maintained-override` | B16 |
| `eden-core/src/dynarmic/backend/x64/a64_emit_x64_standard.cpp` | `maintained-override` | B13 |
| `eden-core/src/dynarmic/backend/x64/a64_emit_x64_standard.h` | `maintained-override` | B15 |
| `eden-core/src/dynarmic/backend/x64/a64_interface_shared.cpp` | `maintained-override` | B11 |
| `eden-core/src/dynarmic/backend/x64/a64_interface_standard.cpp` | `maintained-override` | J10 |
| `eden-core/src/dynarmic/backend/x64/block_of_code.h` | `maintained-override` | B10 |
| `eden-core/src/dynarmic/backend/x64/block_of_code_host.cpp` | `maintained-override` | B09 |
| `eden-core/src/dynarmic/backend/x64/block_of_code_native.cpp` | `maintained-override` | J09 |
| `eden-core/src/dynarmic/backend/x64/constant_pool.cpp` | `maintained-override` | J37 |
| `eden-core/src/dynarmic/backend/x64/emit_x64_data_processing.cpp` | `maintained-override` | J39 |
| `eden-core/src/dynarmic/backend/x64/emit_x64_host.cpp` | `maintained-override` | B17 |
| `eden-core/src/dynarmic/backend/x64/emit_x64_memory.h` | `maintained-override` | B21 |
| `eden-core/src/dynarmic/backend/x64/emit_x64_memory_checked.cpp.inc` | `maintained-override` | B23 |
| `eden-core/src/dynarmic/backend/x64/emit_x64_memory_standard.cpp.inc` | `maintained-override` | B22 |
| `eden-core/src/dynarmic/backend/x64/emit_x64_native.cpp` | `maintained-override` | B18 |
| `eden-core/src/dynarmic/backend/x64/emit_x64_vector.cpp` | `maintained-override` | J38 |
| `eden-core/src/dynarmic/backend/x64/reg_alloc.cpp` | `maintained-override` | J36 |
| `eden-core/src/dynarmic/backend/x64/reg_alloc.h` | `maintained-override` | J35 |
| `eden-core/src/dynarmic/common/spin_lock_x64.cpp` | `maintained-override` | J30 |
| `eden-core/src/dynarmic/frontend/A64/translate/a64_translate.cpp` | `maintained-override` | J32 |
| `eden-core/src/dynarmic/frontend/A64/translate/impl/impl.cpp` | `maintained-override` | J31 |
| `eden-core/src/dynarmic/ir/opt_passes.cpp` | `maintained-override` | J33 |
| `eden-core/src/hid_core/frontend/emulated_controller.cpp` | `maintained-override` | H39 |
| `eden-core/src/hid_core/resource_manager.cpp` | `maintained-override` | H31 |
| `eden-core/src/hid_core/resources/npad/npad.cpp` | `maintained-override` | H48 |
| `eden-core/src/hid_core/resources/npad/npad_pause_diag.cpp` | `maintained-override` | H52 |
| `eden-core/src/shader_recompiler/frontend/maxwell/translate/impl/not_implemented.cpp` | `maintained-override` | V80 |
| `eden-core/src/video_core/buffer_cache/buffer_cache.h` | `maintained-override` | V77 |
| `eden-core/src/video_core/dma_pusher.cpp` | `maintained-override` | V85 |
| `eden-core/src/video_core/dma_pusher_dev.cpp` | `maintained-override` | V86 |
| `eden-core/src/video_core/engines/draw_manager.cpp` | `maintained-override` | V108 |
| `eden-core/src/video_core/engines/fermi_2d_experimental.cpp` | `maintained-override` | V82 |
| `eden-core/src/video_core/engines/fermi_2d_observed.cpp` | `maintained-override` | V81 |
| `eden-core/src/video_core/engines/maxwell_3d.cpp` | `maintained-override` | V78 |
| `eden-core/src/video_core/engines/maxwell_dma.cpp` | `maintained-override` | U81 |
| `eden-core/src/video_core/engines/puller.cpp` | `maintained-override` | V87 |
| `eden-core/src/video_core/engines/puller_dev.cpp` | `maintained-override` | V88 |
| `eden-core/src/video_core/engines/sw_blitter/blitter.cpp` | `maintained-override` | V79 |
| `eden-core/src/video_core/gpu_gl_host.cpp` | `maintained-override` | V100 |
| `eden-core/src/video_core/gpu_gl_host_dev.cpp` | `maintained-override` | V101 |
| `eden-core/src/video_core/gpu_gl_native.cpp` | `maintained-override` | V102 |
| `eden-core/src/video_core/gpu_gl_native_dev.cpp` | `maintained-override` | V103 |
| `eden-core/src/video_core/gpu_vulkan.cpp` | `maintained-override` | V104 |
| `eden-core/src/video_core/host1x/syncpoint_manager.cpp` | `maintained-override` | N04 |
| `eden-core/src/video_core/macro.cpp` | `maintained-override` | Q05,V65 |
| `eden-core/src/video_core/memory_manager.cpp` | `maintained-override` | V71 |
| `eden-core/src/video_core/renderer_opengl/dev_render_passes.inc` | `maintained-override` | V107 |
| `eden-core/src/video_core/renderer_opengl/gl_buffer_cache.cpp` | `maintained-override` | V14 |
| `eden-core/src/video_core/renderer_opengl/gl_query_cache.cpp` | `maintained-override` | V15 |
| `eden-core/src/video_core/renderer_opengl/gl_rasterizer.cpp` | `maintained-override` | V83 |
| `eden-core/src/video_core/renderer_opengl/gl_rasterizer_dev.cpp` | `maintained-override` | V84 |
| `eden-core/src/video_core/renderer_opengl/gl_texture_cache.cpp` | `maintained-override` | V25 |
| `eden-core/src/video_core/shader_cache_reader.inc` | `maintained-override` | V76 |
| `eden-core/src/video_core/shader_environment.cpp` | `maintained-override` | V75 |
| `eden-core/src/video_core/texture_cache/util.cpp` | `maintained-override` | V74 |
| `eden-core/src/video_core/texture_cache/util.h` | `maintained-override` | V23 |
| `eden-core/src/video_core/video_core_opengl.cpp` | `maintained-override` | V12 |
| `eden-gpu/gpu_thread_dev.cpp` | `maintained-override` | Q03 |
| `eden-gpu/gpu_thread_quiet.cpp` | `maintained-override` | Q06 |
| `eden-gpu/include/common/bounded_threadsafe_queue.h` | `maintained-override` | Q02,Q07,V72 |
| `eden-gpu/include/video_core/gpu_thread.h` | `maintained-override` | Q08 |
| `eden-header-hygiene/include/common/page_table.h` | `maintained-override` | — |
| `eden-header-hygiene/include/video_core/macro.h` | `maintained-override` | — |
| `eden-shader/src/shader_recompiler/frontend/maxwell/translate/impl/load_store_local_shared.cpp` | `maintained-override` | V24 |
| `eden-surface-lifecycle/src/core/hle/service/nvnflinger/hardware_composer.cpp` | `maintained-override` | N23 |
| `eden-surface-lifecycle/src/core/hle/service/nvnflinger/surface_flinger.cpp` | `maintained-override` | N06 |
| `eden-sync/src/core/hle/kernel/k_synchronization_object.h` | `maintained-override` | H17 |
| `eden-threading/src/core/hle/kernel/k_address_arbiter.cpp` | `maintained-override` | H07,H10,H11 |
| `eden-threading/src/core/hle/kernel/k_condition_variable.cpp` | `maintained-override` | H01,H08,H09 |
| `eden-threading/src/core/hle/kernel/k_scheduler.cpp` | `maintained-override` | H02,H18,H20 |
| `eden-threading/src/core/hle/kernel/k_slab_heap.h` | `maintained-override` | H33 |
| `eden-threading/src/core/hle/kernel/k_thread.cpp` | `maintained-override` | H03,H19 |
| `eden-threading/src/core/hle/kernel/k_thread.h` | `maintained-override` | H34 |
| `eden-threading/src/core/hle/kernel/k_worker_task_manager.h` | `maintained-override` | H35 |
| `eden-threading/src/core/hle/kernel/slab_helpers.h` | `maintained-override` | H36 |
| `eden-threading/src/core/hle/kernel/svc/svc_address_arbiter.cpp` | `maintained-override` | H13 |
| `eden-threading/src/core/hle/kernel/svc/svc_condition_variable.cpp` | `maintained-override` | H12 |
| `eden-threading/src/core/hle/kernel/svc/svc_synchronization.cpp` | `maintained-override` | H14 |
| `eden-threading/src/core/hle/kernel/svc/svc_thread.cpp` | `maintained-override` | H15 |
| `eden-vulkan-oracles/vulkan_download_batch.inc` | `oracle-only` | V70 |
| `eden-vulkan-oracles/vulkan_gc_downloads.inc` | `oracle-only` | V69 |
| `eden-vulkan-oracles/vulkan_hud_draw.inc` | `oracle-only` | V68 |
| `eden-vulkan-oracles/vulkan_hud_prepare.inc` | `oracle-only` | V67 |
| `eden-vulkan-oracles/vulkan_loading.inc` | `oracle-only` | V66 |
| `eden-vulkan/include/core/frontend/emu_window.h` | `maintained-override` | V36 |
| `eden-vulkan/include/video_core/present.h` | `maintained-override` | V37 |
| `eden-vulkan/include/video_core/renderer_vulkan/pipeline_helper.h` | `maintained-override` | V38 |
| `eden-vulkan/include/video_core/renderer_vulkan/present/window_adapt_pass.h` | `maintained-override` | V39 |
| `eden-vulkan/include/video_core/renderer_vulkan/renderer_vulkan.h` | `maintained-override` | V35 |
| `eden-vulkan/include/video_core/renderer_vulkan/striped_wait.h` | `maintained-override` | V40 |
| `eden-vulkan/include/video_core/renderer_vulkan/vk_blit_screen.h` | `maintained-override` | V34 |
| `eden-vulkan/include/video_core/renderer_vulkan/vk_buffer_cache.h` | `maintained-override` | V111 |
| `eden-vulkan/include/video_core/renderer_vulkan/vk_compute_pipeline.h` | `maintained-override` | V41 |
| `eden-vulkan/include/video_core/renderer_vulkan/vk_descriptor_buffer.h` | `maintained-override` | V33 |
| `eden-vulkan/include/video_core/renderer_vulkan/vk_graphics_pipeline.h` | `maintained-override` | V10 |
| `eden-vulkan/include/video_core/renderer_vulkan/vk_pipeline_cache.h` | `maintained-override` | V110 |
| `eden-vulkan/include/video_core/renderer_vulkan/vk_present_manager.h` | `maintained-override` | V32 |
| `eden-vulkan/include/video_core/renderer_vulkan/vk_scheduler.h` | `maintained-override` | V31 |
| `eden-vulkan/include/video_core/renderer_vulkan/vk_update_descriptor.h` | `maintained-override` | V42 |
| `eden-vulkan/include/video_core/vulkan_common/vulkan.h` | `maintained-override` | V43 |
| `eden-vulkan/include/video_core/vulkan_common/vulkan_wrapper.h` | `maintained-override` | V44 |
| `eden-vulkan/vk_buffer_cache_cost.cpp` | `maintained-override` | R03 |
| `eden-vulkan/vk_compute_pass_cost.cpp` | `maintained-override` | V22 |
| `eden-vulkan/vk_compute_pipeline_cost.cpp` | `maintained-override` | V18 |
| `eden-vulkan/vk_descriptor_buffer_cost.cpp` | `maintained-override` | V17 |
| `eden-vulkan/vk_fence_manager_cost.cpp` | `maintained-override` | V16 |
| `eden-vulkan/vk_graphics_pipeline_cost.cpp` | `maintained-override` | V21 |
| `eden-vulkan/vk_multi_range_buffer_cost.cpp` | `maintained-override` | V20 |
| `eden-vulkan/vk_pipeline_cache_cost.cpp` | `maintained-override` | V07 |
| `eden-vulkan/vk_texture_cache_cost.cpp` | `maintained-override` | V19 |
| `eden-vulkan/vulkan-cache/video_core/texture_cache/texture_cache.h` | `maintained-override` | V45 |
| `eden-vulkan/vulkan_blit_screen.cpp` | `maintained-override` | V28 |
| `eden-vulkan/vulkan_descriptor_buffer.cpp` | `maintained-override` | V46 |
| `eden-vulkan/vulkan_device.cpp` | `maintained-override` | V26 |
| `eden-vulkan/vulkan_hud_shaders.h` | `maintained-override` | V47 |
| `eden-vulkan/vulkan_instance.cpp` | `maintained-override` | V48 |
| `eden-vulkan/vulkan_library.cpp` | `maintained-override` | V49 |
| `eden-vulkan/vulkan_memory_allocator.cpp` | `maintained-override` | V109 |
| `eden-vulkan/vulkan_present_layer.cpp` | `maintained-override` | V09 |
| `eden-vulkan/vulkan_present_manager.cpp` | `maintained-override` | V02 |
| `eden-vulkan/vulkan_query_cache.cpp` | `maintained-override` | V27 |
| `eden-vulkan/vulkan_rasterizer.cpp` | `maintained-override` | V05,V08 |
| `eden-vulkan/vulkan_renderer.cpp` | `maintained-override` | V04 |
| `eden-vulkan/vulkan_scheduler.cpp` | `maintained-override` | V01 |
| `eden-vulkan/vulkan_swapchain.cpp` | `maintained-override` | V03 |
| `eden-vulkan/vulkan_window_adapt_pass.cpp` | `maintained-override` | V29 |
| `eden-vulkan/vulkan_wrapper.cpp` | `maintained-override` | V30 |
| `ps5-mesa/src/amd/vulkan/cl/radv_gs_compute.cl` | `driver-fork` | R23 |
| `ps5-mesa/src/amd/vulkan/meta/radv_meta_clear.c` | `driver-fork` | R12 |
| `ps5-mesa/src/amd/vulkan/meta/radv_meta_resolve.c` | `driver-fork` | R13 |
| `ps5-mesa/src/amd/vulkan/radv_cmd_buffer.c` | `driver-fork` | R14 |
| `ps5-mesa/src/amd/vulkan/radv_descriptor_update_template.c` | `driver-fork` | R15 |
| `ps5-mesa/src/amd/vulkan/radv_descriptor_update_template.h` | `driver-fork` | R16 |
| `ps5-mesa/src/amd/vulkan/radv_physical_device.c` | `driver-fork` | R17 |
| `ps5-mesa/src/amd/vulkan/radv_pipeline.c` | `driver-fork` | R18 |
| `ps5-mesa/src/amd/vulkan/winsys/ps5/radv_ps5_platform.c` | `driver-fork` | R19 |
| `ps5-mesa/src/amd/vulkan/winsys/ps5/radv_ps5_winsys.c` | `driver-fork` | R20 |
| `ps5-mesa/src/util/disk_cache_os.c` | `driver-fork` | R21 |
| `ps5-mesa/src/vulkan/wsi/wsi_common_videoout.c` | `driver-fork` | R22 |
<!-- ACTIVE_SOURCE_CATALOG_END -->

## Fichiers de build du snapshot de backports (hors sources C/C++)

| Chemin | Rôle |
| --- | --- |
| `eden-backports/src/common/CMakeLists.txt` | Adaptation des cibles communes du snapshot épinglé |
| `eden-backports/src/core/CMakeLists.txt` | Adaptation des sources du cœur du snapshot épinglé |

Ces deux fichiers sont inclus dans les **83 entrées** de
`vendor/encore-active/eden-backports/manifest.json`, mais ne sont
pas comptés parmi les fichiers de code et d'en-têtes ci-dessus.

## Inventaire hors `vendor/encore-active`

Les fichiers source/en-tête/fragment de `headless/` sont suivis
dans [`EDEN_HEADLESS_SOURCE_CATALOG.md`](EDEN_HEADLESS_SOURCE_CATALOG.md).
Les chemins du graphe moteur y ont un propriétaire exact ; les autres sont
triés séparément entre moteur, JIT, tests, ressources et launcher.
La couverture de 337/337 ci-dessus ne s'applique **pas** à ce dossier.

## Critères de tenue à jour

Chaque nouveau fichier C/C++ ou en-tête introduit dans le fork doit figurer
dans ce tableau, même s'il n'a pas encore été qualifié. Tout déplacement ou
retrait doit mettre à jour la liste et les liens du graphe.

Tous les chemins actifs sont inventoriés ; seuls les deux en-têtes de correction d'avertissements possèdent un garde dédié sans ID historique dans le graphe. La prochaine étape est de
prouver la sélection native, la parité des transformations et le comportement
console des changements pertinents. Ne pas gonfler les résultats HOST.
