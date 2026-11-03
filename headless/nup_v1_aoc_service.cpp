// SPDX-FileCopyrightText: Copyright 2026 Eden Emulator Project
// SPDX-License-Identifier: GPL-3.0-or-later

// SPDX-FileCopyrightText: Copyright 2018 yuzu Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <algorithm>
#include <limits>
#include <numeric>
#include <vector>

#include "common/logging.h"
#include "common/settings.h"
#include "core/core.h"
#include "core/file_sys/common_funcs.h"
#include "core/file_sys/content_archive.h"
#include "core/file_sys/control_metadata.h"
#include "core/file_sys/nca_metadata.h"
#include "core/file_sys/patch_manager.h"
#include "core/file_sys/registered_cache.h"
#include "extracted_aoc.h"
#include "nup_v1_native_aoc.h"
#include "core/hle/kernel/k_event.h"
#include "core/hle/service/aoc/addon_content_manager.h"
#include "core/hle/service/aoc/purchase_event_manager.h"
#include "core/hle/service/cmif_serialization.h"
#include "core/hle/service/ipc_helpers.h"
#include "core/hle/service/server_manager.h"
#include "core/hle/service/am/am_results.h"
#include "core/loader/loader.h"

namespace Service::AOC {

static bool CheckAOCTitleIDMatchesBase(u64 title_id, u64 base) {
    return FileSys::GetBaseTitleID(title_id) == base;
}

static u64 GetCallerBaseTitleID(Core::System& system, const ClientProcessId& process_id) {
    return FileSys::GetBaseTitleID(system.ResolveCallerProgramId(*process_id));
}

// P5-only common AoC supplement: only the loaded NUP title contributes.
// NCA/extracted AOC retains its original precedence and identification.
static std::vector<u64> VisibleAddOnTitleIds(
    const std::vector<u64>& installed, u64 caller_base) {
    std::vector<u64> result;
    for (const auto id : installed) {
        if (CheckAOCTitleIDMatchesBase(id, caller_base))
            result.push_back(id);
    }
    const auto nup = Eden::NupV1::Native::SoleActiveAddOns();
    if (nup && nup->OwnerBaseId() == caller_base) {
        const auto base = nup->BaseId(caller_base);
        if (base) {
            // The NUP package parser bounds title indices to 11 bits.
            for (const auto index : nup->ListIds(caller_base, 0, 2048))
                result.push_back(*base + index);
        }
    }
    std::sort(result.begin(), result.end());
    result.erase(std::unique(result.begin(), result.end()), result.end());
    return result;
}

static std::vector<u64> AccumulateAOCTitleIDs(Core::System& system) {
    std::vector<u64> add_on_content;
    const auto& rcu = system.GetContentProvider();
    const auto list =
        rcu.ListEntriesFilter(FileSys::TitleType::AOC, FileSys::ContentRecordType::Data);
    std::transform(list.begin(), list.end(), std::back_inserter(add_on_content),
                   [](const FileSys::ContentProviderEntry& rce) { return rce.title_id; });
    add_on_content.erase(
        std::remove_if(
            add_on_content.begin(), add_on_content.end(),
            [&rcu](u64 tid) {
                // A registered content ID can become unavailable before
                // aoc:u is constructed. Never dereference a missing NCA.
                const auto entry = rcu.GetEntry(tid, FileSys::ContentRecordType::Data);
                return !entry || entry->GetStatus() != Loader::ResultStatus::Success;
            }),
        add_on_content.end());
    // Also advertise safely extracted AOC content by its explicit Nintendo
    // AOC Title ID. The folder scanner rejects ambiguous IDs and only
    // discovers content in the selected game's registered storage roots.
    const auto extracted = FileSys::ExtractedAoc::InstalledIds();
    add_on_content.insert(add_on_content.end(), extracted.begin(), extracted.end());
    std::sort(add_on_content.begin(), add_on_content.end());
    add_on_content.erase(std::unique(add_on_content.begin(), add_on_content.end()),
                         add_on_content.end());
    return add_on_content;
}

IAddOnContentManager::IAddOnContentManager(Core::System& system_)
    : ServiceFramework{system_, "aoc:u"}, add_on_content{AccumulateAOCTitleIDs(system)},
      service_context{system_, "aoc:u"} {
    // clang-format off
    static const FunctionInfo functions[] = {
        {0, nullptr, "CountAddOnContentByApplicationId"},
        {1, nullptr, "ListAddOnContentByApplicationId"},
        {2, D<&IAddOnContentManager::CountAddOnContent>, "CountAddOnContent"},
        {3, D<&IAddOnContentManager::ListAddOnContent>, "ListAddOnContent"},
        {4, nullptr, "GetAddOnContentBaseIdByApplicationId"},
        {5, D<&IAddOnContentManager::GetAddOnContentBaseId>, "GetAddOnContentBaseId"},
        {6, nullptr, "PrepareAddOnContentByApplicationId"},
        {7, D<&IAddOnContentManager::PrepareAddOnContent>, "PrepareAddOnContent"},
        {8, D<&IAddOnContentManager::GetAddOnContentListChangedEvent>, "GetAddOnContentListChangedEvent"},
        {9, nullptr, "GetAddOnContentLostErrorCode"},
        {10, D<&IAddOnContentManager::GetAddOnContentListChangedEventWithProcessId>, "GetAddOnContentListChangedEventWithProcessId"},
        {11, D<&IAddOnContentManager::NotifyMountAddOnContent>, "NotifyMountAddOnContent"},
        {12, D<&IAddOnContentManager::NotifyUnmountAddOnContent>, "NotifyUnmountAddOnContent"},
        {13, nullptr, "IsAddOnContentMountedForDebug"},
        {50, D<&IAddOnContentManager::CheckAddOnContentMountStatus>, "CheckAddOnContentMountStatus"},
        {100, D<&IAddOnContentManager::CreateEcPurchasedEventManager>, "CreateEcPurchasedEventManager"},
        {101, D<&IAddOnContentManager::CreatePermanentEcPurchasedEventManager>, "CreatePermanentEcPurchasedEventManager"},
        {110, nullptr, "CreateContentsServiceManager"},
        {200, nullptr, "SetRequiredAddOnContentsOnContentsAvailabilityTransition"},
        {300, nullptr, "SetupHostAddOnContent"},
        {301, nullptr, "GetRegisteredAddOnContentPath"},
        {302, nullptr, "UpdateCachedList"},
    };
    // clang-format on

    RegisterHandlers(functions);

    aoc_change_event = service_context.CreateEvent("GetAddOnContentListChanged:Event");
}

IAddOnContentManager::~IAddOnContentManager() {
    service_context.CloseEvent(aoc_change_event);
}

Result IAddOnContentManager::CountAddOnContent(Out<u32> out_count, ClientProcessId process_id) {
    LOG_DEBUG(Service_AOC, "called. process_id={}", process_id.pid);

    const auto current = GetCallerBaseTitleID(system, process_id);

    const auto& disabled = Settings::values.disabled_addons[current];
    if (std::find(disabled.begin(), disabled.end(), "DLC") != disabled.end()) {
        *out_count = 0;
        R_SUCCEED();
    }

    *out_count = static_cast<u32>(
        VisibleAddOnTitleIds(add_on_content, current).size());

    R_SUCCEED();
}

Result IAddOnContentManager::ListAddOnContent(Out<u32> out_count,
                                              OutBuffer<BufferAttr_HipcMapAlias> out_addons,
                                              u32 offset, u32 count, ClientProcessId process_id) {
    LOG_DEBUG(Service_AOC, "called with offset={}, count={}, process_id={}", offset, count,
              process_id.pid);

    const auto current = GetCallerBaseTitleID(system, process_id);

    std::vector<u32> out;
    const auto& disabled = Settings::values.disabled_addons[current];
    if (std::find(disabled.begin(), disabled.end(), "DLC") == disabled.end()) {
        const auto ids = VisibleAddOnTitleIds(add_on_content, current);
        const auto nup = Eden::NupV1::Native::SoleActiveAddOns();
        const auto nacp_base = nup ? nup->BaseId(current) : std::nullopt;
        for (u64 content_id : ids) {
            // Only NUP-selected titles use a custom NACP AoC base.
            // Keep the common GetAOCID contract for NCA/extracted titles.
            if (nacp_base && content_id >= *nacp_base &&
                content_id - *nacp_base <= FileSys::AOC_TITLE_ID_MASK)
                out.push_back(static_cast<u32>(content_id - *nacp_base));
            else
                out.push_back(static_cast<u32>(FileSys::GetAOCID(content_id)));
        }
        std::sort(out.begin(), out.end());
        out.erase(std::unique(out.begin(), out.end()), out.end());
    }

    R_UNLESS(out.size() >= offset, AM::ResultApplicationRecordNotFound);

    // IPC supplies the actual destination span, not a promise that the
    // caller's requested count fits it. Never write past a short HIPC
    // map-alias buffer, even when the NUP addon index is otherwise valid.
    const std::size_t capacity = out_addons.size() / sizeof(u32);
    *out_count = static_cast<u32>(std::min({
        out.size() - offset, static_cast<std::size_t>(count), capacity}));
    if (*out_count) {
        std::memcpy(out_addons.data(), out.data() + offset,
                    static_cast<std::size_t>(*out_count) * sizeof(u32));
    }

    R_SUCCEED();
}

Result IAddOnContentManager::GetAddOnContentBaseId(Out<u64> out_title_id,
                                                   ClientProcessId process_id) {
    LOG_DEBUG(Service_AOC, "called. process_id={}", process_id.pid);

    const auto title_id = system.ResolveCallerProgramId(*process_id);
    if (const auto nup = Eden::NupV1::Native::SoleActiveAddOns()) {
        if (const auto base = nup->BaseId(title_id)) {
            *out_title_id = *base;
            R_SUCCEED();
        }
    }
    const FileSys::PatchManager pm{title_id, system.GetFileSystemController(),
                                   system.GetContentProvider()};

    const auto res = pm.GetControlMetadata();
    if (res.first == nullptr) {
        *out_title_id = FileSys::GetAOCBaseTitleID(title_id);
        R_SUCCEED();
    }

    *out_title_id = res.first->GetDLCBaseTitleId();

    R_SUCCEED();
}

Result IAddOnContentManager::PrepareAddOnContent(s32 addon_index, ClientProcessId process_id) {
    const auto program_id = system.ResolveCallerProgramId(*process_id);
    const auto current = FileSys::GetBaseTitleID(program_id);
    const auto& disabled = Settings::values.disabled_addons[current];
    // This is an AoC ID, not an array index or an arbitrary title ID.
    // An absent/disabled DLC must not return success to the guest.
    R_UNLESS(addon_index >= 0 &&
             static_cast<u32>(addon_index) <= FileSys::AOC_TITLE_ID_MASK &&
             std::find(disabled.begin(), disabled.end(), "DLC") == disabled.end(),
             AM::ResultApplicationRecordNotFound);
    if (const auto nup = Eden::NupV1::Native::SoleActiveAddOns();
        nup && nup->BaseId(program_id)) {
        // The actual data storage is mounted by the shared FSP RomFSFactory.
        R_UNLESS(nup->OpenRomFS(program_id, static_cast<u32>(addon_index)),
                 AM::ResultApplicationRecordNotFound);
        R_SUCCEED();
    }
    // Ordinary NCA and extracted AoC must use the caller's NACP base,
    // not a guessed high prefix. Only an actually enumerated, usable
    // installation may be acknowledged.
    const FileSys::PatchManager pm{program_id, system.GetFileSystemController(),
                                   system.GetContentProvider()};
    const auto control = pm.GetControlMetadata();
    const u64 aoc_base = control.first ? control.first->GetDLCBaseTitleId()
                                       : FileSys::GetAOCBaseTitleID(program_id);
    R_UNLESS(aoc_base != 0 &&
             aoc_base <= std::numeric_limits<u64>::max() -
                             static_cast<u32>(addon_index),
             AM::ResultApplicationRecordNotFound);
    const u64 requested_id = aoc_base + static_cast<u32>(addon_index);
    R_UNLESS(std::find(add_on_content.begin(), add_on_content.end(), requested_id) !=
                 add_on_content.end(), AM::ResultApplicationRecordNotFound);
    R_SUCCEED();
}

Result IAddOnContentManager::GetAddOnContentListChangedEvent(
    OutCopyHandle<Kernel::KReadableEvent> out_event) {
    LOG_WARNING(Service_AOC, "(STUBBED) called");

    *out_event = &aoc_change_event->GetReadableEvent();

    R_SUCCEED();
}

Result IAddOnContentManager::GetAddOnContentListChangedEventWithProcessId(
    OutCopyHandle<Kernel::KReadableEvent> out_event, ClientProcessId process_id) {
    LOG_WARNING(Service_AOC, "(STUBBED) called");

    *out_event = &aoc_change_event->GetReadableEvent();

    R_SUCCEED();
}

Result IAddOnContentManager::NotifyMountAddOnContent() {
    LOG_WARNING(Service_AOC, "(STUBBED) called");

    R_SUCCEED();
}

Result IAddOnContentManager::NotifyUnmountAddOnContent() {
    LOG_WARNING(Service_AOC, "(STUBBED) called");

    R_SUCCEED();
}

Result IAddOnContentManager::CheckAddOnContentMountStatus() {
    LOG_WARNING(Service_AOC, "(STUBBED) called");

    R_SUCCEED();
}

Result IAddOnContentManager::CreateEcPurchasedEventManager(
    OutInterface<IPurchaseEventManager> out_interface) {
    LOG_WARNING(Service_AOC, "(STUBBED) called");

    *out_interface = std::make_shared<IPurchaseEventManager>(system);

    R_SUCCEED();
}

Result IAddOnContentManager::CreatePermanentEcPurchasedEventManager(
    OutInterface<IPurchaseEventManager> out_interface) {
    LOG_WARNING(Service_AOC, "(STUBBED) called");

    *out_interface = std::make_shared<IPurchaseEventManager>(system);

    R_SUCCEED();
}

void LoopProcess(Core::System& system) {
    auto server_manager = std::make_unique<ServerManager>(system);
    server_manager->RegisterNamedService("aoc:u", std::make_shared<IAddOnContentManager>(system));
    ServerManager::RunServer(std::move(server_manager));
}

} // namespace Service::AOC
