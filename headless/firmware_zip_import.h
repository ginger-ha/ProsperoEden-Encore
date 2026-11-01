// SPDX-License-Identifier: GPL-3.0-or-later
// Automatic, bounded ZIP import of user-supplied firmware. Never downloads,
// decrypts, executes or overwrites system modules; import is data staging only.
#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>
#include <vector>
#include <zlib.h>

namespace Eden::FirmwareZip {
namespace fs = std::filesystem;
inline std::uint16_t U16(const unsigned char* p) {
    return std::uint16_t(p[0]) | std::uint16_t(p[1]) << 8;
}
inline std::uint32_t U32(const unsigned char* p) {
    return std::uint32_t(U16(p)) | std::uint32_t(U16(p + 2)) << 16;
}
inline bool Read(std::ifstream& stream, std::uint64_t at, void* ptr, std::size_t n) {
    stream.clear();
    stream.seekg(static_cast<std::streamoff>(at));
    return static_cast<bool>(stream.read(static_cast<char*>(ptr), n));
}
inline bool SafeName(std::string_view name) {
    if (name.empty() || name.size() > 240 || name[0] == '/' ||
        name.find('\\') != name.npos || name.find('\0') != name.npos ||
        name.find(':') != name.npos) return false;
    if (name.back() == '/') name.remove_suffix(1);
    if (name.empty()) return false;
    const fs::path path{name};
    for (const auto& part : path)
        if (part == "." || part == ".." || part.empty()) return false;
    return !path.is_absolute();
}
struct Entry {
    std::string name;
    std::uint16_t method = 0;
    std::uint32_t compressed = 0;
    std::uint32_t expanded = 0;
    std::uint32_t crc = 0;
    std::uint32_t local_offset = 0;
};
// Central-directory validated ZIP32 only; reject multivolume, encryption,
// symlinks, Zip64 and oversized files instead of silently truncating data.
inline bool Index(std::ifstream& stream, std::vector<Entry>* out) {
    constexpr std::uint64_t max_zip = 1024ULL * 1024 * 1024;
    constexpr std::uint64_t max_expanded = 3ULL * 1024 * 1024 * 1024;
    if (!out) return false;
    stream.seekg(0, std::ios::end);
    const auto end = stream.tellg();
    if (end < 22 || static_cast<std::uint64_t>(end) > max_zip) return false;
    const std::uint64_t size = static_cast<std::uint64_t>(end);
    const std::uint64_t start = size > 65557 ? size - 65557 : 0;
    std::vector<unsigned char> tail(size - start);
    if (!Read(stream, start, tail.data(), tail.size())) return false;
    std::size_t pos = tail.size() - 22;
    while (!(tail[pos] == 0x50 && tail[pos+1] == 0x4b &&
             tail[pos+2] == 0x05 && tail[pos+3] == 0x06)) {
        if (pos == 0) return false;
        --pos;
    }
    const auto* e = tail.data() + pos;
    if (U16(e+4) || U16(e+6) || U16(e+8) != U16(e+10) ||
        U16(e+10) == 0 || U16(e+10) > 8192 ||
        U32(e+12) == 0xffffffffu || U32(e+16) == 0xffffffffu ||
        pos + 22u + U16(e+20) != tail.size()) return false;
    const std::uint64_t cd = U32(e+16), cd_end = cd + U32(e+12);
    if (cd_end > start + pos) return false;
    std::uint64_t cursor = cd, total = 0;
    for (unsigned index = 0; index < U16(e+10); ++index) {
        std::array<unsigned char,46> header{};
        if (cursor > cd_end || cd_end - cursor < header.size() ||
            !Read(stream, cursor, header.data(), header.size()) ||
            U32(header.data()) != 0x02014b50u) return false;
        const auto* h = header.data();
        const std::uint16_t name_size=U16(h+28), extra=U16(h+30), comment=U16(h+32);
        const std::uint16_t flags=U16(h+8), method=U16(h+10);
        const std::uint32_t compressed=U32(h+20), expanded=U32(h+24);
        const std::uint64_t next=cursor+46ull+name_size+extra+comment;
        const unsigned mode=(U32(h+38)>>16)&0170000;
        if (next > cd_end || !name_size || name_size > 240 ||
            flags & 1u || (method != 0 && method != 8) ||
            mode == 0120000 || U16(h+34) != 0 ||
            compressed == 0xffffffffu || expanded == 0xffffffffu ||
            U32(h+42) == 0xffffffffu ||
            expanded > max_expanded - total) return false;
        std::string name(name_size, '\0');
        if (!Read(stream, cursor+46, name.data(), name.size()) ||
            !SafeName(name)) return false;
        total += expanded;
        if (name.back() != '/' && name.rfind("__MACOSX/",0) != 0 &&
            name.find("/._") == std::string::npos && name != ".DS_Store" &&
            !name.ends_with("/.DS_Store")) {
            out->push_back({std::move(name), method, compressed, expanded,
                            U32(h+16), U32(h+42)});
        }
        cursor=next;
    }
    return cursor == cd_end && !out->empty();
}
inline bool ExtractEntry(std::ifstream& zip, const Entry& file, const fs::path& output) {
    std::array<unsigned char,30> local{};
    if (!Read(zip,file.local_offset,local.data(),local.size()) ||
        U32(local.data())!=0x04034b50u || U16(local.data()+8)!=file.method ||
        (U16(local.data()+6)&1u)) return false;
    const std::uint64_t content=file.local_offset + 30ull +
        U16(local.data()+26)+U16(local.data()+28);
    std::error_code ec;
    fs::create_directories(output.parent_path(),ec);
    if (ec || fs::exists(output,ec)) return false;
    std::ofstream output_file(output,std::ios::binary);
    if (!output_file) return false;
    std::array<unsigned char,65536> in{}, out{};
    std::uint64_t remaining=file.compressed, position=content, written=0;
    auto crc=crc32(0,Z_NULL,0);
    z_stream inflater{};
    const bool deflate=file.method==8;
    if (deflate && inflateInit2(&inflater,-MAX_WBITS)!=Z_OK) return false;
    bool ok=true, complete=!deflate;
    while (ok && remaining) {
        const auto count=static_cast<std::size_t>(std::min<std::uint64_t>(remaining,in.size()));
        if (!Read(zip,position,in.data(),count)) { ok=false; break; }
        remaining-=count; position+=count;
        if (!deflate) {
            if (written+count > file.expanded) {ok=false;break;}
            output_file.write(reinterpret_cast<const char*>(in.data()),count);
            crc=crc32(crc,in.data(),static_cast<uInt>(count));written+=count;
            ok=static_cast<bool>(output_file);
        } else {
            inflater.next_in=in.data(); inflater.avail_in=static_cast<uInt>(count);
            do {
                inflater.next_out=out.data(); inflater.avail_out=static_cast<uInt>(out.size());
                const int rc=inflate(&inflater,Z_NO_FLUSH);
                const auto produced=out.size()-inflater.avail_out;
                if ((rc!=Z_OK && rc!=Z_STREAM_END) || written+produced>file.expanded) {
                    ok=false;break;
                }
                output_file.write(reinterpret_cast<const char*>(out.data()),produced);
                crc=crc32(crc,out.data(),static_cast<uInt>(produced));
                written+=produced;
                if (!output_file) {ok=false;break;}
                if (rc==Z_STREAM_END) {complete=true;break;}
            } while (inflater.avail_in);
            if (complete && (remaining || inflater.avail_in)) ok=false;
        }
    }
    if (deflate) inflateEnd(&inflater);
    output_file.close();
    return ok && complete && written==file.expanded && crc==file.crc &&
           file.compressed >= (deflate ? 0u : file.expanded);
}
inline bool Import(const fs::path& archive, const fs::path& target, std::string* reason=nullptr) {
    auto fail=[&](const char* why) {if (reason) *reason=why;return false;};
    std::error_code ec;
    const auto status=fs::symlink_status(archive,ec);
    if (ec || !fs::is_regular_file(status) || fs::is_symlink(status))
        return fail("archive is missing or is a symlink");
    const auto target_status=fs::symlink_status(target,ec);
    if (!ec && target_status.type()!=fs::file_type::not_found)
        return fail("import already exists; preserving user files");
    ec.clear();
    std::ifstream zip(archive,std::ios::binary);
    if (!zip) return fail("archive cannot be opened");
    std::vector<Entry> files;
    if (!Index(zip,&files)) return fail("ZIP index or entry policy rejected");
    const bool firmware_content=std::any_of(files.begin(),files.end(),[](const Entry& item) {
        return item.name.ends_with(".nca") || item.name.ends_with("/main.npdm") ||
               item.name.ends_with("firmware-dump-named.json");
    });
    if (!firmware_content) return fail("ZIP does not contain recognizable firmware content");
    const fs::path stage=target.string()+".incomplete";
    const auto stage_status=fs::symlink_status(stage,ec);
    if (!ec && stage_status.type()!=fs::file_type::not_found)
        return fail("stale partial import; will not overwrite");
    ec.clear();
    if (!fs::create_directories(stage,ec) || ec) return fail("cannot prepare staging directory");
    bool ok=true;
    for (const auto& file : files) {
        const fs::path relative=file.name;
        const fs::path dest=stage/relative;
        if (!ExtractEntry(zip,file,dest)) {ok=false;break;}
    }
    if (ok && !fs::exists(target,ec)) {
        fs::rename(stage,target,ec);
        ok=!ec;
    } else ok=false;
    if (!ok) {
        std::error_code cleanup;
        fs::remove_all(stage,cleanup);
        return fail("archive extraction or commit failed; original ZIP unchanged");
    }
    if (reason) *reason="firmware ZIP imported without modifying original";
    return true;
}
} // namespace Eden::FirmwareZip
