// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

// SPDX-FileCopyrightText: Copyright 2018 yuzu Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <algorithm>
#include <memory>
#include "common/settings.h"
#include "nup_v1_native_aoc.h"
#include "common/assert.h"
#include "common/common_types.h"
#include "common/logging.h"
#include "core/file_sys/common_funcs.h"
#include "core/file_sys/content_archive.h"
#include "core/file_sys/nca_metadata.h"
#include "core/file_sys/patch_manager.h"
#include "core/file_sys/registered_cache.h"
#include "core/file_sys/romfs_factory.h"
#include "extracted_aoc.h"
#include "core/hle/kernel/k_process.h"
#include "core/hle/service/filesystem/filesystem.h"
#include "core/loader/loader.h"

namespace FileSys {

RomFSFactory::RomFSFactory(Loader::AppLoader& app_loader, ContentProvider& provider,
                           Service::FileSystem::FileSystemController& controller)
    : content_provider{provider}, filesystem_controller{controller} {
    // Load the RomFS from the app
    if (app_loader.ReadRomFS(file) != Loader::ResultStatus::Success) {
        LOG_WARNING(Service_FS, "Unable to read base RomFS");
    }

    updatable = app_loader.IsRomFSUpdatable();
}

RomFSFactory::~RomFSFactory() = default;

void RomFSFactory::SetPackedUpdate(VirtualFile update_raw_file) {
    packed_update_raw = std::move(update_raw_file);
}

VirtualFile RomFSFactory::OpenCurrentProcess(u64 current_process_title_id) const {
    if (!updatable) {
        return file;
    }

    const auto type = ContentRecordType::Program;
    const auto nca = content_provider.GetEntry(current_process_title_id, type);
    const PatchManager patch_manager{current_process_title_id, filesystem_controller,
                                     content_provider};
    return patch_manager.PatchRomFS(nca.get(), file, ContentRecordType::Program, packed_update_raw);
}

VirtualFile RomFSFactory::OpenPatchedRomFS(u64 title_id, ContentRecordType type) const {
    auto nca = content_provider.GetEntry(title_id, type);

    if (nca == nullptr) {
        return nullptr;
    }

    const PatchManager patch_manager{title_id, filesystem_controller, content_provider};

    return patch_manager.PatchRomFS(nca.get(), nca->GetRomFS(), type);
}

VirtualFile RomFSFactory::OpenPatchedRomFSWithProgramIndex(u64 title_id, u8 program_index,
                                                           ContentRecordType type) const {
    const auto res_title_id = GetBaseTitleIDWithProgramIndex(title_id, program_index);

    return OpenPatchedRomFS(res_title_id, type);
}

VirtualFile RomFSFactory::Open(u64 title_id, StorageId storage, ContentRecordType type) const {
    const auto nup = Eden::NupV1::Native::SoleActiveAddOns();
    const bool nup_data = nup && type == ContentRecordType::Data;
    const auto active_base = nup_data ? nup->BaseId(nup->OwnerBaseId())
                                      : std::nullopt;
    const bool nup_addon_id = active_base && title_id >= *active_base &&
        title_id - *active_base <= FileSys::AOC_TITLE_ID_MASK;
    const auto try_nup = [&]() -> VirtualFile {
        if (!nup_addon_id) return {};
        const auto current = nup->OwnerBaseId();
        const auto& disabled = Settings::values.disabled_addons[current];
        if (std::find(disabled.begin(), disabled.end(), "DLC") != disabled.end())
            return {};
        return nup->OpenRomFS(current, static_cast<u32>(title_id - *active_base));
    };
    const u64 aoc_suffix = title_id & 0x1fffU;
    const bool extracted_aoc_id = type == ContentRecordType::Data &&
                                  aoc_suffix >= 0x1000U && aoc_suffix <= 0x17ffU;
    // Host storage has no NCA provider in GetEntry: avoid its
    // UNIMPLEMENTED path for explicitly installed extracted AOC content.
    if (storage == StorageId::Host && (extracted_aoc_id || nup_addon_id)) {
        if (const auto extracted = extracted_aoc_id ?
                ExtractedAoc::OpenRomFS(title_id) : VirtualFile{})
            return extracted;
        return try_nup();
    }
    const std::shared_ptr<NCA> res = GetEntry(title_id, storage, type);
    if (res == nullptr) {
        // Existing extracted RomFS and authentic NCA retain precedence;
        // NUP is only another explicit, title-scoped read-only DLC provider.
        const bool allowed_storage = storage == StorageId::None ||
            storage == StorageId::NandUser || storage == StorageId::SdCard;
        if (allowed_storage && extracted_aoc_id) {
            if (const auto extracted = ExtractedAoc::OpenRomFS(title_id))
                return extracted;
        }
        return allowed_storage ? try_nup() : VirtualFile{};
    }

    return res->GetRomFS();
}

std::shared_ptr<NCA> RomFSFactory::GetEntry(u64 title_id, StorageId storage,
                                            ContentRecordType type) const {
    switch (storage) {
    case StorageId::None:
        return content_provider.GetEntry(title_id, type);
    case StorageId::NandSystem:
        return filesystem_controller.GetSystemNANDContents()->GetEntry(title_id, type);
    case StorageId::NandUser:
        return filesystem_controller.GetUserNANDContents()->GetEntry(title_id, type);
    case StorageId::SdCard:
        return filesystem_controller.GetSDMCContents()->GetEntry(title_id, type);
    case StorageId::Host:
    case StorageId::GameCard:
    default:
        UNIMPLEMENTED_MSG("Unimplemented storage_id={:02X}", static_cast<u8>(storage));
        return nullptr;
    }
}

} // namespace FileSys
