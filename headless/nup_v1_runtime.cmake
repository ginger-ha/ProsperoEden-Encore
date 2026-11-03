# P5 admission only: prepare the *same* vendor loader and shared native NUP
# sources without changing any ordinary NSP/XCI/NSO or NS1 launch path.
# OFF is the only default and the final release forbids it until P5 evidence.
option(EDEN_NUP_V1_RUNTIME
    "P5 qualification only: route verified NUP containers to shared loader" OFF)
if(EDEN_NUP_V1_RUNTIME)
    if(EDEN_FINAL_RELEASE_PROFILE)
        message(FATAL_ERROR
            "NUP v1 P5 qualification is not yet allowed in a final release")
    endif()
    get_target_property(eden_nup_core_sources core SOURCES)
    set(eden_nup_loader_owners)
    foreach(eden_nup_owner IN LISTS eden_nup_core_sources)
        if(eden_nup_owner MATCHES "(^|/)loader/loader\\.cpp$")
            list(APPEND eden_nup_loader_owners "${eden_nup_owner}")
        endif()
    endforeach()
    list(LENGTH eden_nup_loader_owners eden_nup_owner_count)
    if(NOT eden_nup_owner_count EQUAL 1)
        message(FATAL_ERROR
            "NUP route requires exactly one pinned loader.cpp owner; re-audit source selection")
    endif()
    list(GET eden_nup_loader_owners 0 eden_nup_original_loader)
    # Compile-only token alias changes the original entrypoint's *symbol*
    # to EdenOriginalGetLoader while preserving its unmodified implementation.
    # The wrapper in nup_v1_loader_route.cpp is the only public GetLoader.
    set_property(SOURCE "${eden_nup_original_loader}" TARGET_DIRECTORY core
        APPEND PROPERTY COMPILE_DEFINITIONS GetLoader=EdenOriginalGetLoader)
    target_sources(core PRIVATE
        "${EDEN_PORT_DIR}/nup_v1_vfs.cpp"
        "${EDEN_PORT_DIR}/nup_v1_native_vfs.cpp"
        "${EDEN_PORT_DIR}/nup_v1_native_content.cpp"
        "${EDEN_PORT_DIR}/nup_v1_native_aoc.cpp"
        "${EDEN_PORT_DIR}/nup_v1_native_loader.cpp"
        "${EDEN_PORT_DIR}/nup_v1_loader_route.cpp")
    # The maintained Encore owners of AoC enumeration and RomFS lookup are
    # replaced only for a P5-qualified runtime. Reuse all their NCA/extracted
    # logic, with an additional NUP caller-scoped source and no vendor edits.
    get_target_property(eden_nup_runtime_sources core SOURCES)
    foreach(eden_nup_pair IN ITEMS
            "file_sys/romfs_factory.cpp|nup_v1_romfs_factory.cpp"
            "hle/service/aoc/addon_content_manager.cpp|nup_v1_aoc_service.cpp")
        string(REPLACE "|" ";" eden_nup_parts "${eden_nup_pair}")
        list(GET eden_nup_parts 0 eden_nup_previous_suffix)
        list(GET eden_nup_parts 1 eden_nup_new_name)
        set(eden_nup_matches)
        foreach(eden_nup_source IN LISTS eden_nup_runtime_sources)
            if(eden_nup_source MATCHES "(^|/)${eden_nup_previous_suffix}$")
                list(APPEND eden_nup_matches "${eden_nup_source}")
            endif()
        endforeach()
        list(LENGTH eden_nup_matches eden_nup_match_count)
        if(NOT eden_nup_match_count EQUAL 1)
            message(FATAL_ERROR
                "NUP requires exactly one existing AoC/ROMFS source owner: ${eden_nup_previous_suffix}")
        endif()
        list(GET eden_nup_matches 0 eden_nup_old_source)
        list(REMOVE_ITEM eden_nup_runtime_sources "${eden_nup_old_source}")
        list(APPEND eden_nup_runtime_sources
            "${EDEN_PORT_DIR}/${eden_nup_new_name}")
    endforeach()
    set_property(TARGET core PROPERTY SOURCES "${eden_nup_runtime_sources}")
    set(eden_nup_extracted_aoc_headers
        "${PORT_ROOT}/vendor/encore-active/eden-core/src/core/file_sys")
    if(NOT EXISTS "${eden_nup_extracted_aoc_headers}/extracted_aoc.h")
        message(FATAL_ERROR "NUP AoC requires maintained existing extracted-aoc interface")
    endif()
    target_include_directories(core PRIVATE
        "${EDEN_PORT_DIR}" "${eden_nup_extracted_aoc_headers}")
    # Only the explicit P5 selection enables NUP library discovery.
    target_compile_definitions(eden-headless PRIVATE EDEN_NUP_V1_RUNTIME=1)
    target_compile_definitions(eden-metadata PRIVATE EDEN_NUP_V1_RUNTIME=1)
    if(NOT TARGET libzstd_static OR NOT TARGET ZLIB::ZLIB)
        message(FATAL_ERROR "NUP requires existing pinned zstd and zlib targets")
    endif()
    target_link_libraries(core PRIVATE libzstd_static ZLIB::ZLIB)
    # OpenSSL hashing comes from the pinned core's existing crypto linkage;
    # no new library version is downloaded or bundled.
endif()
