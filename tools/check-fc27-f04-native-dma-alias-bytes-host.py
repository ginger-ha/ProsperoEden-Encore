#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""F04 native-source DMA -> alias -> CPU invalidation, with byte payload checks.

The production-selected MaxwellDMA contiguous/row fallback fragment,
TextureCache::SynchronizeAliases and TextureCache::WriteMemory execute
together in a mock memory/cache environment under UBSan. DMA bytes and
alias payload are checked against independent expected copies. This is
NOT a device Vulkan upload, image format decoder, FC27 pixel or FPS proof.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
dma = (ROOT / "vendor/encore-active/eden-core/src/video_core/engines/maxwell_dma.cpp").read_text()
texture = (ROOT / "vendor/encore-active/eden-vulkan/vulkan-cache/video_core/texture_cache/texture_cache.h").read_text()
fast = (ROOT / ".github/workflows/encore-core-fast-gate.yml").read_text()
full = (ROOT / ".github/workflows/encore-core-preflight.yml").read_text()
command = "python3 -B tools/check-fc27-f04-native-dma-alias-bytes-host.py"
assert command in fast and command in full

def section(text, begin, end):
    assert text.count(begin) == 1, begin
    i = text.index(begin)
    assert end in text[i:], end
    return text[i:text.index(end, i)]

coalesce = section(dma, "constexpr bool CanCoalescePitchDma(", "\n}\n} // namespace") + "\n}"
launch = section(dma, "void MaxwellDMA::Launch() {", "\nvoid MaxwellDMA::CopyBlockLinearToPitch()")
contig_start = "            u64 contiguous_bytes = 0;\n            if (CanCoalescePitchDma("
contig_end = "        } else {\n            if (!is_src_pitch && is_dst_pitch)"
pitch_body = section(launch, contig_start, contig_end)
assert "memory_manager.CopyBlock(regs.offset_out, regs.offset_in," in pitch_body
assert "memory_manager.CopyBlock(dest_line, source_line, regs.line_length_in);" in pitch_body
assert "width > (~u32{0}) / rows" in coalesce
alias = section(texture,
    "void TextureCache<P>::SynchronizeAliases(ImageId image_id) {",
    "\ntemplate <class P>\nvoid TextureCache<P>::PrepareImage(")
write = section(texture,
    "void TextureCache<P>::WriteMemory(DAddr cpu_addr, size_t size) {",
    "\ntemplate <class P>\nbool TextureCache<P>::IsDownloadable(")
assert "if (image.modification_tick == modification_tick)" in alias
assert "std::ranges::sort(aliased_images" in alias
assert "CopyImage(image_id, aliased->id, aliased->copies);" in alias
# A failed alias copy must not commit a newer destination tick or GPU-dirty flag.
commit_anchor = "#ifdef PS5_NATIVE\n    // Publish alias freshness only after all Vulkan copies were queued."
assert commit_anchor in alias
assert alias.rindex("image.modification_tick = most_recent_tick;") > alias.rindex(
    "CopyImage(image_id, aliased->id, aliased->copies);")
assert "F07 alias revision publication after copy 1/2" in (
    ROOT / "tools/prepare-vulkan-port.py").read_text()
assert "F07 alias revision publication after copy 2/2" in (
    ROOT / "tools/prepare-vulkan-port.py").read_text()
assert "image.flags |= ImageFlagBits::CpuModified;" in write
assert "UntrackImage(image, image_id);" in write

fixture = r"""
#include <algorithm>
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <numeric>
#include <ranges>
#include <stdexcept>
#include <utility>
#include <vector>
using u32 = std::uint32_t;
using u64 = std::uint64_t;
using s64 = std::int64_t;
using DAddr = u64;
using GPUVAddr = u64;
using ImageId = std::size_t;
namespace boost::container {
template<class T, std::size_t N> using small_vector = std::vector<T>;
}
namespace Eden::Performance {
enum class CachePhase {TextureAliasScan, TextureAliasCopy};
struct CachePhaseTimer {
    explicit CachePhaseTimer(CachePhase) {}
    void Stop() {}
};
}
namespace Settings {
struct Resolution {bool active=false;};
struct Values { Resolution resolution_info; };
inline Values values{};
}
enum class ImageFlagBits : u32 {
    Rescaled=1, GpuModified=2, CpuModified=4, Tracked=8
};
struct Flags {
    u32 bits{};
    Flags operator&(ImageFlagBits bit) const {
        return {bits & static_cast<u32>(bit)};
    }
    Flags& operator|=(ImageFlagBits bit) {
        bits |= static_cast<u32>(bit);
        return *this;
    }
};
inline bool True(Flags f) {return f.bits != 0;}
struct ImageCopy {
    std::size_t dst_offset{}, src_offset{}, length{};
};
struct AliasedImage {
    ImageId id{};
    std::vector<ImageCopy> copies{};
};
struct ImageBase {
    Flags flags{};
    u64 modification_tick{};
    DAddr cpu_addr{};
    std::vector<AliasedImage> aliased_images{};
    std::array<std::uint8_t,128> bytes{};
};
using Image = ImageBase;
template<class P> struct TextureCache {
    std::vector<Image> slot_images{3};
    u64 modification_tick{};
    unsigned copies{}, untracks{};
    int fail_copy_before{-1};
    std::vector<ImageId> order;
    bool ImageCanRescale(Image&) {return true;}
    void ScaleUp(Image&) {}
    void ScaleDown(Image&) {}
    void CopyImage(ImageId dst_id, ImageId src_id, std::vector<ImageCopy> spans) {
        if (fail_copy_before == 0) throw std::runtime_error("injected GPU copy failure");
        if (fail_copy_before > 0) --fail_copy_before;
        assert(dst_id < slot_images.size() && src_id < slot_images.size());
        auto& dst = slot_images[dst_id].bytes;
        const auto& src = slot_images[src_id].bytes;
        for (const auto& span : spans) {
            assert(span.dst_offset <= dst.size() && span.src_offset <= src.size());
            assert(span.length <= dst.size()-span.dst_offset);
            assert(span.length <= src.size()-span.src_offset);
            std::copy_n(src.begin()+span.src_offset,span.length,
                        dst.begin()+span.dst_offset);
        }
        order.push_back(src_id);
        ++copies;
    }
    template<class F> void ForEachImageInRegion(DAddr addr, std::size_t size, F fn) {
        if (size == 0) return;
        for (ImageId id=0; id<slot_images.size(); ++id) {
            Image& img=slot_images[id];
            if (addr < img.cpu_addr + img.bytes.size() &&
                img.cpu_addr < addr + size) {
                fn(id,img);
            }
        }
    }
    void UntrackImage(Image& img, ImageId) {
        ++untracks;
        img.flags.bits &= ~static_cast<u32>(ImageFlagBits::Tracked);
    }
    void SynchronizeAliases(ImageId);
    void WriteMemory(DAddr,std::size_t);
};
__COALESCE__
struct MemoryManager {
    std::vector<std::uint8_t> bytes = std::vector<std::uint8_t>(4096);
    unsigned calls{};
    void CopyBlock(u64 dst,u64 src,std::size_t n) {
        assert(dst <= bytes.size() && src <= bytes.size());
        assert(n <= bytes.size()-dst && n <= bytes.size()-src);
        std::memmove(bytes.data()+dst,bytes.data()+src,n);
        ++calls;
    }
};
struct Regs {
    u64 offset_in{}, offset_out{};
    u32 line_length_in{},line_count{};
    s64 pitch_in{},pitch_out{};
};
struct MockDma {
    Regs regs;
    MemoryManager memory_manager;
    void PitchCopy() {
__PITCH__
    }
};
template<class P>
__ALIAS__
template<class P>
__WRITE__
static void TestPitch(u64 src,u64 dst,u32 width,u32 rows,s64 in,s64 out,unsigned expected_calls) {
    MockDma engine;
    auto& bytes=engine.memory_manager.bytes;
    for(std::size_t i=0;i<bytes.size();++i)
        bytes[i]=static_cast<std::uint8_t>((i*37+11)%251);
    auto expected=bytes;
    // Deliberately independently execute the specified row-by-row result.
    for(u32 line=0;line<rows;++line) {
        const auto a=static_cast<u64>(static_cast<s64>(src)+line*in);
        const auto b=static_cast<u64>(static_cast<s64>(dst)+line*out);
        std::memmove(expected.data()+b,expected.data()+a,width);
    }
    engine.regs={src,dst,width,rows,in,out};
    engine.PitchCopy();
    assert(engine.memory_manager.calls==expected_calls);
    assert(bytes==expected);
}
int main() {
    u64 length{};
    assert(CanCoalescePitchDma(256,1024,64,4,64,64,length) && length==256);
    assert(!CanCoalescePitchDma(256,280,64,4,64,64,length));
    assert(!CanCoalescePitchDma(256,1024,64,4,72,72,length));
    TestPitch(256,1024,64,4,64,64,1);
    TestPitch(256,1024,64,4,72,72,4);
    TestPitch(256,280,64,4,64,64,4);
    std::puts("F04_DMA_BYTE_PARITY_PASS contiguous=1 gapped=1 overlapping=1");

    MockDma dma;
    for(std::size_t i=0;i<dma.memory_manager.bytes.size();++i)
        dma.memory_manager.bytes[i]=static_cast<std::uint8_t>((i*13+29)%253);
    dma.regs={256,1024,16,4,16,16};
    dma.PitchCopy();
    assert(dma.memory_manager.calls==1);

    TextureCache<int> tc;
    auto& dst=tc.slot_images[0];
    auto& first=tc.slot_images[1];
    auto& second=tc.slot_images[2];
    dst.cpu_addr=0x1000;
    first.cpu_addr=0x2000;
    second.cpu_addr=0x3000;
    dst.bytes.fill(0xA5);
    std::copy_n(dma.memory_manager.bytes.begin()+1024,64,first.bytes.begin());
    second.bytes.fill(0x3C);
    dst.modification_tick=1;
    first.modification_tick=4;
    second.modification_tick=7;
    tc.modification_tick=7;
    first.flags |= ImageFlagBits::GpuModified;
    second.flags |= ImageFlagBits::GpuModified;
    // Reverse the source order; the native method must sort by modification tick.
    dst.aliased_images={{2,{{64,0,32}}},{1,{{0,0,64}}}};
    tc.SynchronizeAliases(0);
    assert((tc.order==std::vector<ImageId>{1,2}));
    assert(tc.copies==2 && dst.modification_tick==7);
    assert(True(dst.flags & ImageFlagBits::GpuModified));
    for(std::size_t i=0;i<64;++i) assert(dst.bytes[i]==first.bytes[i]);
    for(std::size_t i=64;i<96;++i) assert(dst.bytes[i]==0x3C);
    for(std::size_t i=96;i<128;++i) assert(dst.bytes[i]==0xA5);
    tc.SynchronizeAliases(0);
    assert(tc.copies==2); // same tick: no redundant copy

    // Newer alias wins only its own region; untouched bytes remain untouched.
    first.modification_tick=8;
    tc.modification_tick=8;
    first.bytes.fill(0x5E);
    tc.SynchronizeAliases(0);
    assert(tc.copies==3 && tc.order.back()==1);
    assert(dst.modification_tick==8);
    for(std::size_t i=0;i<64;++i) assert(dst.bytes[i]==0x5E);
    for(std::size_t i=64;i<96;++i) assert(dst.bytes[i]==0x3C);
    for(std::size_t i=96;i<128;++i) assert(dst.bytes[i]==0xA5);

    // Failure after the first successful GPU copy: destination revision
    // remains old, so the next draw retries both aliases in tick order.
    TextureCache<int> rollback;
    auto& stale = rollback.slot_images[0];
    auto& source1 = rollback.slot_images[1];
    auto& source2 = rollback.slot_images[2];
    stale.modification_tick = 1;
    source1.modification_tick = 10;
    source2.modification_tick = 13;
    source1.flags |= ImageFlagBits::GpuModified;
    source2.flags |= ImageFlagBits::GpuModified;
    rollback.modification_tick = 13;
    stale.bytes.fill(0);
    source1.bytes.fill(0xA1);
    source2.bytes.fill(0xB2);
    stale.aliased_images = {{2,{{64,0,32}}},{1,{{0,0,64}}}};
    rollback.fail_copy_before = 1;
    bool copy_failed = false;
    try {
        rollback.SynchronizeAliases(0);
    } catch (const std::runtime_error&) {
        copy_failed = true;
    }
    assert(copy_failed);
    assert(rollback.copies == 1 && stale.modification_tick == 1);
    assert(!True(stale.flags & ImageFlagBits::GpuModified));
    rollback.fail_copy_before = -1;
    rollback.SynchronizeAliases(0);
    assert(rollback.copies == 3 && stale.modification_tick == 13);
    assert((rollback.order == std::vector<ImageId>{1,1,2}));
    assert(True(stale.flags & ImageFlagBits::GpuModified));
    for (unsigned i=0;i<64;++i) assert(stale.bytes[i]==0xA1);
    for (unsigned i=64;i<96;++i) assert(stale.bytes[i]==0xB2);

    first.flags |= ImageFlagBits::Tracked;
    tc.WriteMemory(first.cpu_addr+8,16);
    assert(True(first.flags & ImageFlagBits::CpuModified));
    assert(!True(first.flags & ImageFlagBits::Tracked));
    assert(tc.untracks==1);
    tc.WriteMemory(first.cpu_addr+8,16);
    assert(tc.untracks==1);
    tc.WriteMemory(0x5000,64);
    assert(tc.untracks==1);
    assert(!True(second.flags & ImageFlagBits::CpuModified));
    std::puts("F04_NATIVE_DMA_ALIAS_CONTENT_PASS ordered_aliases=2 updated_aliases=1 "
              "byte_regions=3 cpu_invalidations=1 alias_copy_failure_retry=1 "
              "scope=source_extracted_host_mock_gpu_bytes");
}
"""
fixture=(fixture.replace("__COALESCE__",coalesce)
        .replace("__PITCH__",pitch_body)
        .replace("__ALIAS__",alias)
        .replace("__WRITE__",write))
compiler=shutil.which("clang++-18") or shutil.which("clang++") or shutil.which("g++")
assert compiler, "C++20 compiler is required"
with tempfile.TemporaryDirectory(prefix="encore-f04-dma-alias-") as directory:
    src=Path(directory)/"payload.cpp"
    src.write_text(fixture)
    for opt in ("-O0","-O2"):
        exe=Path(directory)/("payload"+opt)
        args=[compiler,"-std=c++20",opt,"-DPS5_NATIVE=1","-Wall","-Wextra",
              "-Werror","-fsanitize=undefined","-fno-sanitize-recover=all",
              str(src),"-o",str(exe)]
        built=subprocess.run(args,capture_output=True,text=True,timeout=75)
        assert built.returncode==0,(opt,built.stderr[-6000:])
        run=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
        assert run.returncode==0,(opt,run.stdout,run.stderr[-5000:])
        assert "F04_NATIVE_DMA_ALIAS_CONTENT_PASS" in run.stdout
        assert "F04_DMA_BYTE_PARITY_PASS" in run.stdout
        print(run.stdout.strip(),opt,flush=True)
print("F04_REAL_VULKAN_UPLOAD_AND_GUEST_PIXELS_NOT_PROVEN")


# T01/F04: compile the actual FindDMAImage method with the original candidate
# matching decisions. In the native path the newest matching image must be
# selected during the first scan; equal ticks keep the first match. The
# desktop still has the original multi-candidate max_element selection.
dma_begin = "ImageId TextureCache<P>::FindDMAImage("
dma_end = "\ntemplate <class P>\nstd::pair<u32, u32> TextureCache<P>::PrepareDmaImage"
assert texture.count(dma_begin) == 1
candidate_fn = texture.split(dma_begin, 1)[1].split(dma_end, 1)[0]
candidate_fn = dma_begin + candidate_fn
assert "const auto consider_candidate =" in candidate_fn
assert candidate_fn.count("consider_candidate(existing_image_id, existing_image);") == 2
assert "std::ranges::max_element(image_ids, image_ids_compare)" in candidate_fn
assert "F07 T01 single-pass freshest DMA image candidate selection" in (
    ROOT / "tools/prepare-vulkan-port.py").read_text()
test_cpp = r"""
#include <algorithm>
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <optional>
#include <vector>
using u32=std::uint32_t;
using DAddr=std::uint64_t;
using GPUVAddr=std::uint64_t;
using ImageId=u32;
enum class ImageType {Linear,Tiled};
enum class ImageFlagBits : unsigned {None=0,Remapped=1,Strong=2};
ImageFlagBits operator&(ImageFlagBits a,ImageFlagBits b) {
    return ImageFlagBits(unsigned(a)&unsigned(b));
}
bool True(ImageFlagBits value) {return unsigned(value)!=0;}
struct ImageInfo {ImageType type{ImageType::Tiled};size_t pitch{128};int format{7};};
struct ImageBase {
    ImageInfo info{};
    GPUVAddr gpu_addr{42};
    ImageFlagBits flags{ImageFlagBits::None};
    std::uint64_t modification_tick{};
};
size_t CalculateGuestSizeInBytes(const ImageInfo&) {return 4096;}
bool IsPitchLinearSameSize(const ImageInfo& a,const ImageInfo& b,bool strict) {
    return a.pitch==b.pitch && (!strict || a.format==b.format);
}
bool IsViewCompatible(int a,int b,bool,bool) {return a==b;}
bool IsSubCopy(const ImageInfo& info,const ImageBase& image,GPUVAddr gpu_addr) {
    return info.type==image.info.type && image.gpu_addr==gpu_addr &&
           image.info.format==info.format;
}
struct Gpu {
    bool miss_first{},miss_all{};
    std::optional<DAddr> GpuToCpuAddress(GPUVAddr) {
        if(miss_first||miss_all)return {};
        return DAddr{42};
    }
    std::optional<DAddr> GpuToCpuAddress(GPUVAddr,size_t) {
        if(miss_all)return {};
        return DAddr{42};
    }
};
template<class P> struct TextureCache {
    Gpu* gpu_memory{};
    std::array<ImageBase,32> slot_images{};
    std::vector<ImageId> ids;
    template<class F> void ForEachImageInRegion(DAddr,size_t,F callback) {
        for(ImageId id:ids) (void)callback(id,slot_images[id]);
    }
    ImageId FindDMAImage(const ImageInfo&,GPUVAddr);
};
__METHOD__
int main() {
    Gpu gpu;TextureCache<int> c; c.gpu_memory=&gpu;
    ImageInfo linear{ImageType::Linear,128,7};
    for(unsigned i=1;i<32;++i) {
        c.slot_images[i].info=linear;
        c.slot_images[i].gpu_addr=42;
        c.slot_images[i].modification_tick=i*10;
    }
    assert(c.FindDMAImage(linear,42)==0);
    c.ids={1};
    assert(c.FindDMAImage(linear,42)==1);
    c.ids={1,3,2};
    assert(c.FindDMAImage(linear,42)==3);
    c.slot_images[2].modification_tick=30; // equal timestamp: FIRST wins
    c.ids={2,3,1};
    assert(c.FindDMAImage(linear,42)==2);
    c.slot_images[3].flags=ImageFlagBits::Remapped;
    c.ids={3,1};
    assert(c.FindDMAImage(linear,42)==1);
    c.slot_images[3].flags=ImageFlagBits::None;
    c.slot_images[3].info.pitch=256;
    assert(c.FindDMAImage(linear,42)==1); // invalid linear pitch excluded
    c.slot_images[3].info.pitch=128;
    c.slot_images[1].flags=ImageFlagBits::Strong;
    assert(c.FindDMAImage(linear,42)==3); // strongest compatible match
    gpu.miss_first=true;
    assert(c.FindDMAImage(linear,42)==3); // second GpuToCpu lookup
    gpu.miss_all=true;
    assert(c.FindDMAImage(linear,42)==0);
    gpu.miss_all=false;gpu.miss_first=false;
    ImageInfo tiled{ImageType::Tiled,128,7};
    c.slot_images[4].info=tiled;
    c.slot_images[5].info=tiled;
    c.slot_images[4].modification_tick=51;
    c.slot_images[5].modification_tick=53;
    c.ids={4,5};
    assert(c.FindDMAImage(tiled,42)==5);
    c.ids.clear();
    for(unsigned i=6;i<=20;i++){
        c.slot_images[i].info=tiled;
        c.ids.push_back(i);
    }
    assert(c.FindDMAImage(tiled,42)==20); // >8 matching images
    std::puts("F07_T01_DMA_SINGLE_SCAN_PASS");
}
""".replace("__METHOD__","template<class P>\n"+candidate_fn.replace(
    "boost::container::small_vector<ImageId, 8> image_ids;",
    "std::vector<ImageId> image_ids;"))
with tempfile.TemporaryDirectory(prefix="encore-f07-dma-find-image-") as directory:
    source=Path(directory)/"find_dma.cpp"
    source.write_text(test_cpp)
    for native in (False,True):
        for opt in ("-O0","-O2"):
            exe=Path(directory)/("find-"+str(int(native))+opt)
            args=[compiler,"-std=c++20",opt,"-Wall","-Wextra","-Werror",
                  "-fsanitize=undefined","-fno-sanitize-recover=all",
                  *(["-DPS5_NATIVE=1"] if native else []),
                  str(source),"-o",str(exe)]
            built=subprocess.run(args,capture_output=True,text=True,timeout=60)
            assert built.returncode==0,(native,opt,built.stderr[-5500:])
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=25)
            assert result.returncode==0,(native,opt,result.stderr[-4000:])
            assert "F07_T01_DMA_SINGLE_SCAN_PASS" in result.stdout
            print("F07_T01_DMA_SINGLE_SCAN_PASS", "native",int(native),opt)
