// SPDX-License-Identifier: GPL-3.0-or-later
// INACTIVE NUP addon provider. Not registered with the guest aoc:u service.
#pragma once
#include <cstddef>
#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <vector>
#include "nup_v1_native_content.h"

namespace Loader { class AppLoader; }
namespace Eden::NupV1::Native {

// Per-application AoC snapshot: the caller ID must come from the kernel's
// verified process identity, NEVER from archive metadata or the launcher UI.
class AddOnIndex final {
public:
    AddOnIndex(std::shared_ptr<Mount> mount, std::uint64_t caller_program_id,
               std::optional<std::uint64_t> nacp_aoc_base_id = std::nullopt);
    std::uint64_t OwnerBaseId() const { return owner_base_id_; }
    std::optional<std::uint64_t> BaseId(std::uint64_t caller_program_id) const;
    std::size_t Count(std::uint64_t caller_program_id) const;
    std::vector<std::uint32_t> ListIds(std::uint64_t caller_program_id,
                                       std::size_t offset, std::size_t limit) const;
    FileSys::VirtualFile OpenRomFS(std::uint64_t caller_program_id,
                                   std::uint32_t aoc_index) const;
private:
    bool MatchesCaller(std::uint64_t caller_program_id) const;
    std::uint64_t owner_base_id_{};
    std::optional<std::uint64_t> aoc_base_id_;
    std::unique_ptr<ContentSet> content_;
    std::map<std::uint32_t, std::size_t> indexes_;
};

// Keep per-title snapshots alive only while their native AppLoader exists.
// The shared_ptr protects concurrent IPC requests during teardown.
void PublishActiveAddOns(const Loader::AppLoader* loader,
                         std::shared_ptr<const AddOnIndex> index);
void ForgetActiveAddOns(const Loader::AppLoader* loader);
std::shared_ptr<const AddOnIndex> ActiveAddOnsForLoader(
    const Loader::AppLoader* loader);
std::shared_ptr<const AddOnIndex> SoleActiveAddOns();

} // namespace Eden::NupV1::Native
