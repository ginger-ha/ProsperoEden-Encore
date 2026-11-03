// SPDX-License-Identifier: GPL-3.0-or-later
#include "nup_v1_native_aoc.h"
#include <iterator>
#include <mutex>
#include <unordered_map>
#include <utility>
#include "core/file_sys/common_funcs.h"

namespace Eden::NupV1::Native {
namespace {
struct ActiveRegistry {
    std::mutex mutex;
    std::unordered_map<const Loader::AppLoader*,
                       std::shared_ptr<const AddOnIndex>> entries;
};
ActiveRegistry& Registry() {
    static ActiveRegistry registry;
    return registry;
}
} // namespace

void PublishActiveAddOns(const Loader::AppLoader* loader,
                         std::shared_ptr<const AddOnIndex> index) {
    if (!loader || !index) return;
    auto& registry = Registry();
    std::lock_guard guard(registry.mutex);
    registry.entries.insert_or_assign(loader, std::move(index));
}

void ForgetActiveAddOns(const Loader::AppLoader* loader) {
    auto& registry = Registry();
    std::lock_guard guard(registry.mutex);
    registry.entries.erase(loader);
}

std::shared_ptr<const AddOnIndex> ActiveAddOnsForLoader(
    const Loader::AppLoader* loader) {
    if (!loader) return {};
    auto& registry = Registry();
    std::lock_guard guard(registry.mutex);
    const auto found = registry.entries.find(loader);
    return found == registry.entries.end() ? nullptr : found->second;
}

std::shared_ptr<const AddOnIndex> SoleActiveAddOns() {
    auto& registry = Registry();
    std::lock_guard guard(registry.mutex);
    return registry.entries.size() == 1 ?
           registry.entries.begin()->second : nullptr;
}

AddOnIndex::AddOnIndex(std::shared_ptr<Mount> mount,
                       std::uint64_t caller_program_id,
                       std::optional<std::uint64_t> nacp_aoc_base_id) {
    if (!mount || !caller_program_id) return;
    owner_base_id_ = FileSys::GetBaseTitleID(caller_program_id);
    // Never grant a caller an add-on family from a base/update of another
    // application. Add-on-only packages require the explicit caller scope.
    for (const auto& pkg : mount->Packages()) {
        if (pkg.kind != 2 &&
            FileSys::GetBaseTitleID(pkg.title_id) != owner_base_id_) {
            owner_base_id_ = 0;
            return;
        }
    }
    if (nacp_aoc_base_id &&
        (*nacp_aoc_base_id & FileSys::AOC_TITLE_ID_MASK))
        return;
    aoc_base_id_ = nacp_aoc_base_id.value_or(
        owner_base_id_ + FileSys::AOC_TITLE_ID_OFFSET);
    content_ = std::make_unique<ContentSet>(
        std::move(mount), caller_program_id, nacp_aoc_base_id);
    for (const auto& addon : content_->AddOns()) {
        if (addon.title_id < *aoc_base_id_ ||
            addon.title_id - *aoc_base_id_ > FileSys::AOC_TITLE_ID_MASK)
            continue;
        indexes_.emplace(
            static_cast<std::uint32_t>(addon.title_id - *aoc_base_id_),
            addon.package_index);
    }
}

bool AddOnIndex::MatchesCaller(std::uint64_t caller_program_id) const {
    return content_ && caller_program_id &&
           FileSys::GetBaseTitleID(caller_program_id) == owner_base_id_;
}

std::optional<std::uint64_t> AddOnIndex::BaseId(
    std::uint64_t caller_program_id) const {
    return MatchesCaller(caller_program_id) ? aoc_base_id_ : std::nullopt;
}

std::size_t AddOnIndex::Count(std::uint64_t caller_program_id) const {
    return MatchesCaller(caller_program_id) ? indexes_.size() : 0;
}

std::vector<std::uint32_t> AddOnIndex::ListIds(
    std::uint64_t caller_program_id, std::size_t offset,
    std::size_t limit) const {
    std::vector<std::uint32_t> result;
    if (!MatchesCaller(caller_program_id) || offset >= indexes_.size() ||
        limit == 0) return result;
    auto it = indexes_.begin();
    std::advance(it, static_cast<std::ptrdiff_t>(offset));
    for (; it != indexes_.end() && result.size() < limit; ++it)
        result.push_back(it->first);
    return result;
}

FileSys::VirtualFile AddOnIndex::OpenRomFS(
    std::uint64_t caller_program_id, std::uint32_t aoc_index) const {
    if (!MatchesCaller(caller_program_id)) return {};
    const auto it = indexes_.find(aoc_index);
    return it == indexes_.end() ? FileSys::VirtualFile{} :
           content_->CreateAddOnRomFS(it->second);
}

} // namespace Eden::NupV1::Native
