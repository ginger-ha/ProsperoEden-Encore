// SPDX-License-Identifier: GPL-3.0-or-later
#include "nup_v1_native_vfs.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <mutex>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <utility>

#include "core/file_sys/vfs/vfs.h"

namespace Eden::NupV1::Native {

bool HasNupV1Header(const FileSys::VirtualFile& source) {
    if (!source || !source->IsReadable() || source->GetSize() < 0x80)
        return false;
    std::array<u8, 0x80> header{};
    if (source->Read(header.data(), header.size(), 0) != header.size())
        return false;
    const auto le16 = [&](std::size_t off) -> std::uint64_t {
        return std::uint64_t(header[off]) | (std::uint64_t(header[off + 1]) << 8);
    };
    const auto le64 = [&](std::size_t off) -> std::uint64_t {
        std::uint64_t value{};
        for (std::size_t i = 0; i < 8; ++i)
            value |= std::uint64_t(header[off + i]) << (8 * i);
        return value;
    };
    const auto toc_size = le64(0x10);
    const auto blob_offset = le64(0x38);
    const auto actual_size = std::uint64_t(source->GetSize());
    return header[0] == 'N' && header[1] == 'U' &&
           header[2] == 'P' && header[3] == 1 &&
           le16(4) == 0x80 && le16(6) == 1 &&
           le64(8) == 0x80 && toc_size > 0 &&
           toc_size <= 64ULL * 1024 * 1024 &&
           toc_size <= actual_size - 0x80 &&
           blob_offset >= 0x80 + toc_size &&
           blob_offset <= actual_size &&
           blob_offset % 16 == 0 &&
           le64(0x40) == actual_size;
}

namespace {
class NativeSource final : public Eden::NupV1::Source {
public:
    explicit NativeSource(FileSys::VirtualFile file)
        : file_(std::move(file)), size_(file_ ? file_->GetSize() : 0) {}

    std::uint64_t Size() const override { return size_; }

    bool ReadAt(std::uint64_t offset, std::span<std::uint8_t> dst) const override {
        std::scoped_lock guard(mutex_);
        if (!file_ || !file_->IsReadable() || file_->GetSize() != size_ ||
            offset > size_ || dst.size() > size_ - offset ||
            offset > std::numeric_limits<std::size_t>::max()) {
            return false;
        }
        return dst.empty() || file_->Read(dst.data(), dst.size(),
                                          static_cast<std::size_t>(offset)) == dst.size();
    }

    // Even a read-only VfsFile can change externally. Do not reuse SHA-256
    // results across reads of an unpinned backing source.
    bool AllowsVerifiedMemberCache() const override { return false; }

private:
    FileSys::VirtualFile file_;
    std::uint64_t size_{};
    mutable std::mutex mutex_;
};
} // namespace

namespace Detail {
struct State {
    explicit State(FileSys::VirtualFile file) : source(std::move(file)) {}
    NativeSource source;
    std::unique_ptr<Eden::NupV1::Archive> archive; // destructed before source
};
} // namespace Detail

namespace {
class NativeFile final : public FileSys::VfsFile {
public:
    NativeFile(std::shared_ptr<Detail::State> state, std::size_t index,
               std::string name, FileSys::VirtualDir parent)
        : state_(std::move(state)), index_(index), name_(std::move(name)),
          parent_(std::move(parent)) {}

    std::string GetName() const override { return name_; }
    std::size_t GetSize() const override {
        return static_cast<std::size_t>(state_->archive->MemberSize(index_));
    }
    bool Resize(std::size_t) override { return false; }
    FileSys::VirtualDir GetContainingDirectory() const override { return parent_; }
    bool IsWritable() const override { return false; }
    bool IsReadable() const override { return true; }

    std::size_t Read(u8* dst, std::size_t len, std::size_t offset) const override {
        const auto size = GetSize();
        if (!dst || offset >= size || len == 0) return 0;
        const auto count = (std::min)(len, size - offset);
        // ReadMember can write a partial range before finding an integrity
        // or decoding error. Clear that range so callers can never observe
        // unverified data even when they mishandle a short VFS read.
        if (!state_->archive->ReadMember(index_, offset,
                                         std::span<std::uint8_t>(dst, count))) {
            std::fill_n(dst, count, u8{});
            return 0;
        }
        return count;
    }
    std::size_t Write(const u8*, std::size_t, std::size_t) override { return 0; }
    bool Rename(std::string_view) override { return false; }

private:
    std::shared_ptr<Detail::State> state_;
    std::size_t index_{};
    std::string name_;
    FileSys::VirtualDir parent_;
};

class NativeDirectory final : public FileSys::ReadOnlyVfsDirectory,
                              public std::enable_shared_from_this<NativeDirectory> {
public:
    NativeDirectory(std::shared_ptr<Detail::State> state,
                    std::optional<std::size_t> package, ContentView view,
                    std::string path, std::string name,
                    FileSys::VirtualDir parent = {})
        : state_(std::move(state)), package_(package), view_(view),
          path_(std::move(path)), name_(std::move(name)), parent_(std::move(parent)) {}

    std::vector<FileSys::VirtualFile> GetFiles() const override {
        std::vector<FileSys::VirtualFile> result;
        const auto& entries = Entries();
        if (!entries) return result;
        const auto self = std::const_pointer_cast<NativeDirectory>(shared_from_this());
        for (const auto& entry : *entries) {
            if (entry.directory || !entry.file_index) continue;
            const auto size = state_->archive->MemberSize(*entry.file_index);
            if (size > std::numeric_limits<std::size_t>::max()) continue;
            result.emplace_back(std::make_shared<NativeFile>(
                state_, *entry.file_index, entry.name, self));
        }
        return result;
    }

    std::vector<FileSys::VirtualDir> GetSubdirectories() const override {
        std::vector<FileSys::VirtualDir> result;
        const auto& entries = Entries();
        if (!entries) return result;
        const auto self = std::const_pointer_cast<NativeDirectory>(shared_from_this());
        for (const auto& entry : *entries) {
            if (!entry.directory) continue;
            const auto next = path_.empty() ? entry.name : path_ + "/" + entry.name;
            result.emplace_back(std::make_shared<NativeDirectory>(
                state_, package_, view_, next, entry.name, self));
        }
        return result;
    }

    std::string GetName() const override { return name_; }
    FileSys::VirtualDir GetParentDirectory() const override { return parent_; }

private:
    const std::optional<std::vector<DirEntry>>& Entries() const {
        // The mounted NUP TOC and effective overlay are immutable. Cache only
        // directory metadata; NativeFile::Read still verifies the live source.
        // Both VFS GetFiles/GetSubdirectories may be called by different
        // services, so initialize exactly once and never copy the entry vector.
        std::call_once(entries_once_, [this] {
            entries_ = package_
                ? state_->archive->ListPackageDirectory(*package_, view_, path_)
                : state_->archive->ListEffectiveDirectory(view_, path_);
        });
        return entries_;
    }

    mutable std::once_flag entries_once_;
    mutable std::optional<std::vector<DirEntry>> entries_;
    std::shared_ptr<Detail::State> state_;
    std::optional<std::size_t> package_;
    ContentView view_;
    std::string path_;
    std::string name_;
    FileSys::VirtualDir parent_;
};
} // namespace

Mount::Mount(std::shared_ptr<Detail::State> state) : state_(std::move(state)) {}
Mount::~Mount() = default;

std::shared_ptr<Mount> Mount::Open(FileSys::VirtualFile file, std::string* error) {
    if (!file || !file->IsReadable()) {
        if (error) *error = "NUP input VFS file is not readable";
        return {};
    }
    auto state = std::make_shared<Detail::State>(std::move(file));
    state->archive = Eden::NupV1::Archive::Mount(state->source, error);
    if (!state->archive) return {};
    return std::shared_ptr<Mount>(new Mount(std::move(state)));
}

const std::vector<Eden::NupV1::Package>& Mount::Packages() const {
    return state_->archive->Packages();
}

const Eden::NupV1::PackageMetadata* Mount::ApplicationMetadata() const {
    return state_->archive->ApplicationMetadata();
}

FileSys::VirtualDir Mount::Effective(ContentView view) const {
    if (!state_->archive->ListEffectiveDirectory(view)) return {};
    return std::make_shared<NativeDirectory>(
        state_, std::nullopt, view, "", view == ContentView::ExeFS ? "exefs" : "romfs");
}

FileSys::VirtualDir Mount::PackageView(std::size_t package_index, ContentView view) const {
    if (!state_->archive->ListPackageDirectory(package_index, view)) return {};
    return std::make_shared<NativeDirectory>(
        state_, package_index, view, "", view == ContentView::ExeFS ? "exefs" : "romfs");
}
} // namespace Eden::NupV1::Native
