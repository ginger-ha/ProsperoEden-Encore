// SPDX-License-Identifier: GPL-3.0-or-later
// Host test implementation: validates pass-through, NOT real NSO/NPDM loading.
#pragma once
#include "core/loader/loader.h"
namespace Loader {
class AppLoader_DeconstructedRomDirectory final : public AppLoader {
public:
    explicit AppLoader_DeconstructedRomDirectory(FileSys::VirtualDir directory,
                                                 bool override_update = false)
      : AppLoader(directory ? directory->GetFile("main") : nullptr),
        directory_(std::move(directory)), override_update_(override_update) {}
    FileType GetFileType() const override { return FileType::DeconstructedRomDirectory; }
    LoadResult Load(Kernel::KProcess&, Core::System&) override {
        if (override_update_ || !directory_ || !directory_->GetFile("main"))
            return {ResultStatus::ErrorNoExeFS, {}};
        if (!directory_->GetFile("main.npdm"))
            return {ResultStatus::ErrorMissingNPDM, {}};
        loaded_ = true;
        return {ResultStatus::Success, LoadParameters{1, 4096}};
    }
    ResultStatus ReadProgramId(std::uint64_t& id) override {
        id = 0x0100123400000000ULL;
        return ResultStatus::Success;
    }
    ResultStatus ReadTitle(std::string& name) override {
        name = "Synthetic Host App";
        return ResultStatus::Success;
    }
    ResultStatus ReadNSOModules(Modules& modules) override {
        if (!loaded_) return ResultStatus::ErrorNotInitialized;
        modules.emplace(0, "main");
        return ResultStatus::Success;
    }
private:
    FileSys::VirtualDir directory_;
    bool override_update_{};
    bool loaded_{};
};
} // namespace Loader
