// SPDX-License-Identifier: GPL-3.0-or-later
#include "nup_v1_native_loader.h"

#include <utility>

#include "core/loader/deconstructed_rom_directory.h"

namespace Eden::NupV1::Native {

NupAppLoader::NupAppLoader(FileSys::VirtualFile source)
    : Loader::AppLoader(std::move(source)) {}
NupAppLoader::~NupAppLoader() = default;

std::unique_ptr<NupAppLoader> NupAppLoader::Open(FileSys::VirtualFile source,
                                                 std::string* error) {
    if (error) error->clear();
    if (!source) {
        if (error) *error = "NUP source is null";
        return {};
    }

    auto loader = std::unique_ptr<NupAppLoader>(new NupAppLoader(std::move(source)));
    loader->mount_ = Mount::Open(loader->file, error);
    if (!loader->mount_) return {};
    loader->content_ = std::make_unique<ContentSet>(loader->mount_);
    if (!loader->content_->HasExecutableMain()) {
        if (error) *error = "NUP effective ExeFS lacks main or main.npdm";
        return {};
    }

    // No double patching of the NUP effective ExeFS directory: explicitly
    // disable the deconstructed loader's own update-overlay flag.
    loader->extracted_loader_ =
        std::make_unique<Loader::AppLoader_DeconstructedRomDirectory>(
            loader->content_->ExeFS(), false);
    return loader;
}

NupAppLoader::LoadResult NupAppLoader::Load(Kernel::KProcess& process,
                                             Core::System& system) {
    if (!extracted_loader_)
        return {Loader::ResultStatus::ErrorNoExeFS, {}};
    return extracted_loader_->Load(process, system);
}

Loader::ResultStatus NupAppLoader::ReadRomFS(FileSys::VirtualFile& out_file) {
    out_file.reset();
    if (!content_) return Loader::ResultStatus::ErrorNoRomFS;
    if (!effective_romfs_) effective_romfs_ = content_->CreateRomFS();
    if (!effective_romfs_) return Loader::ResultStatus::ErrorNoRomFS;
    out_file = effective_romfs_;
    return Loader::ResultStatus::Success;
}

Loader::ResultStatus NupAppLoader::ReadIcon(std::vector<u8>& out_buffer) {
    return extracted_loader_ ? extracted_loader_->ReadIcon(out_buffer)
                             : Loader::ResultStatus::ErrorNoIcon;
}

Loader::ResultStatus NupAppLoader::ReadProgramId(u64& out_program_id) {
    return extracted_loader_ ? extracted_loader_->ReadProgramId(out_program_id)
                             : Loader::ResultStatus::ErrorNoExeFS;
}

Loader::ResultStatus NupAppLoader::ReadTitle(std::string& out_title) {
    return extracted_loader_ ? extracted_loader_->ReadTitle(out_title)
                             : Loader::ResultStatus::ErrorNoControl;
}

Loader::ResultStatus NupAppLoader::ReadNSOModules(Modules& out_modules) {
    return extracted_loader_ ? extracted_loader_->ReadNSOModules(out_modules)
                             : Loader::ResultStatus::ErrorNotInitialized;
}

} // namespace Eden::NupV1::Native
