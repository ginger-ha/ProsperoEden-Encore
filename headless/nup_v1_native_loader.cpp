// SPDX-License-Identifier: GPL-3.0-or-later
#include "nup_v1_native_loader.h"

#include <utility>

#include "core/file_sys/common_funcs.h"
#include "core/file_sys/program_metadata.h"
#include "core/file_sys/vfs/vfs.h"
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

Loader::ResultStatus NupAppLoader::ValidateProgramIdentity(u64& program_id) const {
    if (!content_ || !mount_) return Loader::ResultStatus::ErrorNoExeFS;
    const auto exefs = content_->ExeFS();
    if (!exefs) return Loader::ResultStatus::ErrorNoExeFS;
    const auto npdm = exefs->GetFile("main.npdm");
    if (!npdm) return Loader::ResultStatus::ErrorMissingNPDM;

    FileSys::ProgramMetadata metadata;
    const auto status = metadata.Load(npdm);
    if (status != Loader::ResultStatus::Success) return status;

    // Both the NUP record and the actual executable's NPDM must identify
    // the same base program. Without this check an otherwise valid archive
    // can misassociate a dumped executable with another application's ID.
    const auto& packages = mount_->Packages();
    const Package* declared = nullptr;
    for (const auto& package : packages) {
        if (package.kind == 0) {
            declared = &package;
            break;
        }
        if (package.kind == 1 && (!declared || package.version > declared->version))
            declared = &package;
    }
    if (!declared) return Loader::ResultStatus::ErrorNoExeFS;
    program_id = metadata.GetTitleID();
    if (FileSys::GetBaseTitleID(program_id) !=
        FileSys::GetBaseTitleID(declared->title_id)) {
        return Loader::ResultStatus::ErrorBadNPDMHeader;
    }
    return Loader::ResultStatus::Success;
}

NupAppLoader::LoadResult NupAppLoader::Load(Kernel::KProcess& process,
                                             Core::System& system) {
    if (!extracted_loader_)
        return {Loader::ResultStatus::ErrorNoExeFS, {}};
    u64 program_id{};
    const auto status = ValidateProgramIdentity(program_id);
    if (status != Loader::ResultStatus::Success) return {status, {}};
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
    u64 validated{};
    const auto status = ValidateProgramIdentity(validated);
    if (status == Loader::ResultStatus::Success) out_program_id = validated;
    return status;
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
