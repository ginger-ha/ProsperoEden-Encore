// SPDX-License-Identifier: GPL-3.0-or-later
// INACTIVE NUP v1 application-loader adapter. It is not registered in
// GetLoader, FileType, CMake, ROM scanning, the frontend, or AoC.
#pragma once

#include <memory>
#include <string>
#include <vector>

#include "nup_v1_native_content.h"
#include "core/loader/loader.h"

namespace Eden::NupV1::Native {

// Reuse the existing deconstructed ExeFS/NSO loader, while providing the
// effective NUP RomFS explicitly. No title-ID special cases or new CPU/GPU path.
class NupAppLoader final : public Loader::AppLoader {
public:
    // A valid NUP containing main and main.npdm is required; no boot is
    // initiated. The loader stays a local explicit-only adapter until vetted.
    static std::unique_ptr<NupAppLoader> Open(FileSys::VirtualFile source,
                                               std::string* error = nullptr);
    ~NupAppLoader() override;

    // NUP has no registered FileType yet. Never advertise it as NSP or NCA.
    Loader::FileType GetFileType() const override { return Loader::FileType::Unknown; }
    LoadResult Load(Kernel::KProcess& process, Core::System& system) override;
    Loader::ResultStatus ReadRomFS(FileSys::VirtualFile& out_file) override;
    Loader::ResultStatus ReadIcon(std::vector<u8>& out_buffer) override;
    Loader::ResultStatus ReadProgramId(u64& out_program_id) override;
    Loader::ResultStatus ReadTitle(std::string& out_title) override;
    Loader::ResultStatus ReadNSOModules(Modules& out_modules) override;
    // NUP has already applied its highest-version directory overlay.
    bool IsRomFSUpdatable() const override { return false; }

private:
    // Use the actual common NPDM parser before exposing a program ID or boot.
    Loader::ResultStatus ValidateProgramIdentity(u64& program_id) const;
    explicit NupAppLoader(FileSys::VirtualFile source);
    std::shared_ptr<Mount> mount_;
    std::unique_ptr<ContentSet> content_;
    std::unique_ptr<Loader::AppLoader> extracted_loader_;
    FileSys::VirtualFile effective_romfs_;
};

} // namespace Eden::NupV1::Native
