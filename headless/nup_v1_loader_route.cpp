// SPDX-License-Identifier: GPL-3.0-or-later
// Prepared P5-only loader-factory bridge. The CMake switch is OFF by default.
// All ordinary NS1/NS2 formats continue through the original vendor factory.
#include "nup_v1_native_loader.h"
#include "nup_v1_native_vfs.h"

#include <memory>
#include <string>
#include <utility>

#include "common/logging.h"
#include "core/file_sys/common_funcs.h"
#include "core/loader/loader.h"

namespace Loader {

// The original pinned loader.cpp is compiled with the source-local
// GetLoader=EdenOriginalGetLoader token alias. No vendor C++ is rewritten,
// and all non-NUP requests continue to use the exact existing implementation.
std::unique_ptr<AppLoader> EdenOriginalGetLoader(
    Core::System& system, FileSys::VirtualFile file,
    u64 program_id, std::size_t program_index);

std::unique_ptr<AppLoader> GetLoader(
    Core::System& system, FileSys::VirtualFile file,
    u64 program_id, std::size_t program_index) {
    if (!file) return nullptr;
    if (!Eden::NupV1::Native::HasNupV1Header(file))
        return EdenOriginalGetLoader(system, std::move(file),
                                     program_id, program_index);
    // A NUP bundles one effective application. Never select a guessed NCA
    // program index, and never fall back to interpreting failed NUP as NSP.
    if (program_index != 0) return nullptr;
    std::string error;
    auto loader = Eden::NupV1::Native::NupAppLoader::Open(
        std::move(file), &error);
    if (!loader) {
        LOG_WARNING(Loader, "Rejected NUP v1 container: {}", error);
        return nullptr;
    }
    u64 actual_program_id{};
    if (loader->ReadProgramId(actual_program_id) != ResultStatus::Success ||
        (program_id != 0 &&
         FileSys::GetBaseTitleID(program_id) !=
             FileSys::GetBaseTitleID(actual_program_id))) {
        LOG_WARNING(Loader, "NUP program identity does not match request");
        return nullptr;
    }
    return loader;
}

} // namespace Loader
