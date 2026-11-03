// SPDX-License-Identifier: GPL-3.0-or-later
// Host-only stand-in for NPDM parsing, not a substitute for the real parser.
#pragma once
#include <string>
#include <utility>
#include "core/loader/loader.h"

namespace FileSys {
class ProgramMetadata {
public:
    Loader::ResultStatus Load(VirtualFile file) {
        if (!file) return Loader::ResultStatus::ErrorMissingNPDM;
        std::string data(file->GetSize(), '\0');
        if (!data.empty() &&
            file->Read(reinterpret_cast<u8*>(data.data()), data.size(), 0) != data.size())
            return Loader::ResultStatus::ErrorBadNPDMHeader;
        if (data == "latest-npdm") {
            program_id_ = 0x0100123400000000ULL;
        } else if (data == "foreign-npdm") {
            program_id_ = 0x0100123400002000ULL;
        } else {
            return Loader::ResultStatus::ErrorBadNPDMHeader;
        }
        return Loader::ResultStatus::Success;
    }
    u64 GetTitleID() const { return program_id_; }
private:
    u64 program_id_{};
};
} // namespace FileSys
