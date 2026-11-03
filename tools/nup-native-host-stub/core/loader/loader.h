// SPDX-License-Identifier: GPL-3.0-or-later
// Host ONLY signature stub for the AppLoader bridge. Not the engine.
#pragma once
#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>
#include "core/file_sys/vfs/vfs.h"
namespace Core { class System {}; }
namespace FileSys { class NACP; }
namespace Kernel { class KProcess {}; }
namespace Loader {
enum class FileType { Error, Unknown, DeconstructedRomDirectory };
enum class ResultStatus {
    Success, ErrorNoExeFS, ErrorNoRomFS, ErrorNoIcon, ErrorNoControl,
    ErrorNotInitialized, ErrorMissingNPDM, ErrorBadNPDMHeader, ErrorAlreadyLoaded,
    ErrorIntegrityVerificationFailed,
};
class AppLoader {
public:
    struct LoadParameters { int main_thread_priority; std::uint64_t main_thread_stack_size; };
    using LoadResult = std::pair<ResultStatus, std::optional<LoadParameters>>;
    using Modules = std::map<std::uint64_t, std::string>;
    explicit AppLoader(FileSys::VirtualFile source) : file(std::move(source)) {}
    virtual ~AppLoader() = default;
    virtual FileType GetFileType() const = 0;
    virtual LoadResult Load(Kernel::KProcess&, Core::System&) = 0;
    virtual ResultStatus ReadRomFS(FileSys::VirtualFile&) { return ResultStatus::ErrorNoRomFS; }
    virtual ResultStatus ReadIcon(std::vector<u8>&) { return ResultStatus::ErrorNoIcon; }
    virtual ResultStatus ReadControlData(FileSys::NACP&) { return ResultStatus::ErrorNoControl; }
    virtual ResultStatus ReadProgramId(std::uint64_t&) { return ResultStatus::ErrorNoExeFS; }
    virtual ResultStatus ReadTitle(std::string&) { return ResultStatus::ErrorNoControl; }
    virtual ResultStatus ReadNSOModules(Modules&) { return ResultStatus::ErrorNotInitialized; }
    virtual bool IsRomFSUpdatable() const { return true; }
protected:
    FileSys::VirtualFile file;
};
} // namespace Loader
