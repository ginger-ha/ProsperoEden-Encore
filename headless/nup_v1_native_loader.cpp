// SPDX-License-Identifier: GPL-3.0-or-later
#include "nup_v1_native_loader.h"

#include <cstddef>
#include <optional>
#include <utility>

#include "core/file_sys/control_metadata.h"
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

    // The real extracted loader reads main.npdm *in its constructor*.
    // Reject an invalid title and oversized untrusted NPDM BEFORE reaching
    // that constructor (or its metadata, title and icon handling).
    u64 validated_program_id{};
    if (loader->ValidateProgramIdentity(validated_program_id) !=
        Loader::ResultStatus::Success) {
        if (error) *error = "NUP invalid NPDM program identity";
        return {};
    }

    std::optional<std::uint64_t> aoc_base;
    constexpr auto aoc_offset = offsetof(FileSys::RawNACP, dlc_base_title_id);
    static_assert(sizeof(FileSys::RawNACP) == 0x4000);
    static_assert(aoc_offset == 0x3070, "vendor RawNACP AoC base field ABI drift");
    static_assert(aoc_offset + sizeof(std::uint64_t) <= sizeof(FileSys::RawNACP));

    const std::vector<std::uint8_t>* nacp_data = nullptr;
    if (const auto* metadata = loader->mount_->ApplicationMetadata();
        metadata && metadata->control_nacp.size() == sizeof(FileSys::RawNACP)) {
        nacp_data = &metadata->control_nacp; // TLV wins over extracted tree
    }
    std::vector<std::uint8_t> extracted_nacp;
    if (!nacp_data) {
        // Extracted base/update content is also a legitimate NUP source.
        // Use the effective ExeFS control.nacp when the optional TLV is absent.
        const auto exefs = loader->content_->ExeFS();
        const auto control = exefs ? exefs->GetFile("control.nacp") : nullptr;
        if (control && control->GetSize() == sizeof(FileSys::RawNACP)) {
            extracted_nacp.resize(sizeof(FileSys::RawNACP));
            if (control->Read(extracted_nacp.data(), extracted_nacp.size(), 0) ==
                extracted_nacp.size()) {
                nacp_data = &extracted_nacp;
            }
        }
    }
    if (nacp_data) {
        std::uint64_t raw_id{};
        for (std::size_t i = 0; i < sizeof(std::uint64_t); ++i)
            raw_id |= std::uint64_t((*nacp_data)[aoc_offset + i]) << (8 * i);
        if (raw_id != 0) aoc_base = raw_id;
    }
    // Recreate the selection only after the actual NPDM establishes the
    // caller's application identity; an untrusted NACP does not bypass it.
    loader->content_ = std::make_unique<ContentSet>(
        loader->mount_, validated_program_id, aoc_base);

    // No double patching of the NUP effective ExeFS directory: explicitly
    // disable the deconstructed loader's own update-overlay flag.
    // The main-file constructor initializes title/icon/control metadata,
    // unlike the directory-only overload in the pinned extracted loader.
    // Our NativeFile retains its containing ExeFS directory across reads.
    const auto main_file = loader->content_->ExeFS()->GetFile("main");
    loader->extracted_loader_ =
        std::make_unique<Loader::AppLoader_DeconstructedRomDirectory>(
            main_file, false);
    return loader;
}

Loader::ResultStatus NupAppLoader::ValidateProgramIdentity(u64& program_id) const {
    if (!content_ || !mount_) return Loader::ResultStatus::ErrorNoExeFS;
    const auto exefs = content_->ExeFS();
    if (!exefs) return Loader::ResultStatus::ErrorNoExeFS;
    const auto npdm = exefs->GetFile("main.npdm");
    if (!npdm) return Loader::ResultStatus::ErrorMissingNPDM;
    // The real ProgramMetadata reader allocates arrays based on NPDM fields.
    // This is an app description, not a full game image: cap its total size
    // before any vendor parser or extracted-loader constructor touches it.
    constexpr std::size_t MaxNPDMBytes = 4U * 1024U * 1024U;
    if (npdm->GetSize() == 0 || npdm->GetSize() > MaxNPDMBytes)
        return Loader::ResultStatus::ErrorBadNPDMHeader;

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
    // A base package identifies the exact program, including its program
    // index. A standalone update carries the update title ID, so only its
    // common base-program family can be compared with the loaded NPDM.
    if ((declared->kind == 0 && program_id != declared->title_id) ||
        (declared->kind == 1 &&
         FileSys::GetBaseTitleID(program_id) !=
             FileSys::GetBaseTitleID(declared->title_id))) {
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
    u64 program_id{};
    const auto status = ValidateProgramIdentity(program_id);
    if (status != Loader::ResultStatus::Success) return status;
    std::scoped_lock guard(romfs_mutex_);
    if (!effective_romfs_) effective_romfs_ = content_->CreateRomFS();
    if (!effective_romfs_) return Loader::ResultStatus::ErrorNoRomFS;
    out_file = effective_romfs_;
    return Loader::ResultStatus::Success;
}

Loader::ResultStatus NupAppLoader::ReadIcon(std::vector<u8>& out_buffer) {
    u64 program_id{};
    const auto status = ValidateProgramIdentity(program_id);
    if (status != Loader::ResultStatus::Success) return status;
    if (const auto* metadata = mount_->ApplicationMetadata();
        metadata && !metadata->default_icon.empty()) {
        out_buffer = metadata->default_icon;
        return Loader::ResultStatus::Success;
    }
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
    u64 program_id{};
    const auto status = ValidateProgramIdentity(program_id);
    if (status != Loader::ResultStatus::Success) return status;
    if (const auto* metadata = mount_->ApplicationMetadata();
        metadata && !metadata->title.empty()) {
        out_title = metadata->title;
        return Loader::ResultStatus::Success;
    }
    return extracted_loader_ ? extracted_loader_->ReadTitle(out_title)
                             : Loader::ResultStatus::ErrorNoControl;
}

Loader::ResultStatus NupAppLoader::ReadNSOModules(Modules& out_modules) {
    u64 program_id{};
    const auto status = ValidateProgramIdentity(program_id);
    if (status != Loader::ResultStatus::Success) return status;
    return extracted_loader_ ? extracted_loader_->ReadNSOModules(out_modules)
                             : Loader::ResultStatus::ErrorNotInitialized;
}

const std::vector<AddOnDirectory>& NupAppLoader::SelectedAddOns() const {
    return content_->AddOns();
}

} // namespace Eden::NupV1::Native
