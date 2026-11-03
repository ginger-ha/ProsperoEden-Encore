// SPDX-License-Identifier: GPL-3.0-or-later
// Inactive native NUP content bridge: no FileType/launcher/AoC registration.
#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <vector>

#include "nup_v1_native_vfs.h"

namespace Eden::NupV1::Native {

struct AddOnDirectory {
    std::size_t package_index{};
    std::uint64_t title_id{};
    std::uint32_t version{};
    FileSys::VirtualDir romfs;
};

// Assemble the *same* effective ExeFS/RomFS views for NS1 and NS2.
// This is an inert content provider, NOT a game loader. Integration must
// supply metadata validation, title identity, PatchManager/AoC and the
// app loader's ReadRomFS result before NUP can be called playable.
class ContentSet final {
public:
    // Caller title is mandatory when examining an add-on-only archive.
    // Never enumerate add-ons of unknown ownership globally.
    explicit ContentSet(std::shared_ptr<Mount> mount,
                        std::optional<std::uint64_t> caller_program_id = std::nullopt);
    FileSys::VirtualDir ExeFS() const;
    // Read-only RomFS binary via the existing engine's CreateRomFS builder;
    // nullptr when no effective RomFS directory exists.
    FileSys::VirtualFile CreateRomFS() const;
    // The extracted-directory loader requires BOTH main and main.npdm.
    bool HasExecutableMain() const;
    // Directory handles only. Registration into the shared AoC provider
    // is deliberately deferred; no addon is folded into effective RomFS.
    const std::vector<AddOnDirectory>& AddOns() const { return addons_; }
    // Explicit addon-only RomFS binary for a future AoC provider.
    // Base/update packages are rejected, never merged into CreateRomFS().
    FileSys::VirtualFile CreateAddOnRomFS(std::size_t package_index) const;

private:
    std::shared_ptr<Mount> mount_;
    std::vector<AddOnDirectory> addons_;
};

} // namespace Eden::NupV1::Native
