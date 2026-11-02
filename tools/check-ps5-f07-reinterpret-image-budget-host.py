#!/usr/bin/env python3
"""F07 P0.4: compile the actual PS5 reinterpret scratch-allocation bounds.

Use source-extracted native checks for empty copies, zero extents, overflowed
3D multiplicands, and accumulated overflow; compare desktop behavior without
invoking a Vulkan device. Runtime image pixels and FC27 FPS are not measured.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/"vendor/encore-active/eden-vulkan/vk_texture_cache_cost.cpp").read_text()
generator=(ROOT/"tools/prepare-vulkan-port.py").read_text()
fast=(ROOT/".github/workflows/encore-core-fast-gate.yml").read_text()
pre=(ROOT/".github/workflows/encore-core-preflight.yml").read_text()
invocation="python3 -B tools/check-ps5-f07-reinterpret-image-budget-host.py"
assert invocation in fast and invocation in pre
for description in ("F07 reject empty native Vulkan reinterpret image copies",
                    "F07 validate native Vulkan reinterpret scratch byte budget"):
    assert description in generator
method_start="void TextureCacheRuntime::ReinterpretImage(Image& dst, Image& src,"
method_end="\nvoid TextureCacheRuntime::BlitImage("
assert source.count(method_start) == source.count(method_end) == 1
start=source.index(method_start)
method=source[start:source.index(method_end,start)]
early_start="#ifdef PS5_NATIVE\n    // An empty reinterpret has no image pixels"
early_end="#ifndef PS5_NATIVE\n    if (ENABLE_MSAA_RESOLVE_CONSUME)"
assert method.count(early_start)==method.count(early_end)==1
early=method[method.index(early_start):method.index(early_end)]
body_start="    const u32 img_bpp = BytesPerBlock(dst.info.format);"
body_end="    const VkImage dst_image = dst.Handle();"
assert method.count(body_start)==method.count(body_end)==1
# Allocation and input/output conversion now happen only after native
# dimension/overflow checks. Keep the size-guard fixture restricted to
# the real preflight plus the later scratch handle/resolve guard.
copies_start="    // Rejected reinterpret copies must not allocate or convert while holding the texture lock."
scratch_start="    const VkBuffer copy_buffer = GetTemporaryBuffer(total_size);"
assert method.count(copies_start)==method.count(scratch_start)==1
assert method.index(body_start) < method.index(copies_start) < method.index(scratch_start) < method.index(body_end)
size=(method[method.index(body_start):method.index(copies_start)] +
      method[method.index(scratch_start):method.index(body_end)])
assert method.index("if (total_size > scratch_max)") < method.index(copies_start)
assert "if (copies.empty())" in early
assert "if (total_size > max_size - bytes)" in size
assert "width > max_size / height" in size
assert "area > max_size / depth" in size
assert "volume > max_size / img_bpp" in size
assert "scratch_max = size_t{1} << (std::numeric_limits<size_t>::digits - 1)" in size
assert "if (total_size > scratch_max)" in size
assert "F07 defer native reinterpret resolve invalidation until valid allocation" in generator
assert "F07 invalidate native reinterpret resolve after scratch allocation" in generator
assert method.index("const VkBuffer copy_buffer = GetTemporaryBuffer(total_size);") < method.index(
    "#ifdef PS5_NATIVE\n    // A mapped scratch allocation")
assert method.index("InvalidateResolveShadow(dst.Handle());", method.index("const VkBuffer copy_buffer")) < method.index("scheduler.RequestOutsideRenderPassOperationContext();")
assert "F07 reject scratch sizes outside Vulkan transient buffer slots" in generator
assert "F07 reject null native image reinterpret scratch handle" in generator
assert "if (copy_buffer == VK_NULL_HANDLE)" in size
assert size.index("if (copy_buffer == VK_NULL_HANDLE)") < size.index("InvalidateResolveShadow(dst.Handle());")
assert "F07 preserve resolve validity on rejected size-incompatible CopyImage" in generator
assert "F07 skip empty size-compatible native Vulkan CopyImage without stale resolve" in generator
assert "F07 skip empty native MSAA image copies before helper GPU dispatch" in generator
assert "F07 avoid empty native image upload and unnecessary MSAA resolve invalidation" in generator
upload_start="void Image::UploadMemory(VkBuffer buffer, VkDeviceSize offset,"
upload_end="    // TODO: Move this to another API"
assert source.count(upload_start)==1
upload=source[source.index(upload_start):]
upload_guard=upload[upload.index("#ifdef PS5_NATIVE"):upload.index(upload_end)]
assert upload_guard.count("if (copies.empty())")==1
assert upload_guard.index("if (copies.empty())") < upload_guard.index("return;")
assert upload.index("if (copies.empty())") < upload.index("InvalidateResolveShadow(Handle());")

assert "F07 skip zero-area native Vulkan image blits" in generator
blit_header="void TextureCacheRuntime::BlitImage(Framebuffer* dst_framebuffer, ImageView& dst, ImageView& src,"
blit_tail="    const VkImageAspectFlags aspect_mask = ImageAspectMask(src.format);"
assert source.count(blit_header)==1
blit_method=source[source.index(blit_header):]
assert blit_method.count(blit_tail)==1
blit_guard=blit_method[blit_method.index("{")+1:blit_method.index(blit_tail)]
assert blit_guard.count("==") == 4 and blit_guard.count("return;") == 1
assert blit_guard.index("#ifdef PS5_NATIVE") < blit_guard.index("if (dst_region.start.x")
assert "src_region.start.y == src_region.end.y" in blit_guard

msaa_start="void TextureCacheRuntime::CopyImageMSAA(Image& dst, Image& src,"
assert source.count(msaa_start)==1
msaa_source=source[source.index(msaa_start):]
msaa_guard_start="#ifdef PS5_NATIVE\n    // A zero-region MSAA transfer"
msaa_end="    const bool msaa_to_non_msaa ="
assert msaa_source.count(msaa_guard_start)==1 and msaa_source.count(msaa_end)==1
msaa_guard=msaa_source[msaa_source.index(msaa_guard_start):msaa_source.index(msaa_end)]
assert "if (copies.empty())" in msaa_guard
assert msaa_guard.index("if (copies.empty())") < msaa_guard.index("return;")

copy_start="void TextureCacheRuntime::CopyImage(Image& dst, Image& src,"
copy_end="    // As per the size-compatible formats section of vulkan, copy manually via ReinterpretImage"
assert source.count(copy_start)==source.count(copy_end)==1
copy_method=source[source.index(copy_start):]
copy_guard=copy_method[copy_method.index("{")+1:copy_method.index(copy_end)]
assert "BytesPerBlock(src.info.format) == BytesPerBlock(dst.info.format)" in copy_guard
assert "if (copies.empty() &&" in copy_guard
assert copy_guard.index("if (copies.empty() &&") < copy_guard.index("InvalidateResolveShadow(dst.Handle());")
assert copy_guard.count("#else") == 1 and "if (ENABLE_MSAA_RESOLVE_CONSUME)" in copy_guard
assert copy_guard.index("BytesPerBlock(src.info.format)") < copy_guard.index("#else")
assert size.index("#else\n    for (const auto& copy") > size.index("#ifdef PS5_NATIVE")
assert size.index("const VkBuffer copy_buffer = GetTemporaryBuffer(total_size);") > size.index("#endif")
cpp=r"""
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>
using u32=std::uint32_t;
using VkBuffer=std::size_t;
using VkImage=std::size_t;
constexpr VkBuffer VK_NULL_HANDLE=0;
inline constexpr bool ENABLE_MSAA_RESOLVE_CONSUME=true;
struct Extent {u32 width{},height{},depth{};};
struct ImageCopy {Extent extent{};};
struct ImageInfo {u32 format{};};
struct Offset2D {int x{},y{};};
struct Region2D {Offset2D start{},end{};};
struct Image {ImageInfo info{}; VkImage Handle() const {return 73;} };
u32 BytesPerBlock(u32 format) {return format;}
struct Runtime {
    std::size_t calls{},last_size{};
    std::size_t invalidates{},direct_copies{};
    bool null_scratch{};
    void InvalidateResolveShadow(VkImage image) {assert(image==73);++invalidates;}
    VkBuffer GetTemporaryBuffer(std::size_t bytes) {
#ifdef PS5_NATIVE
        assert(bytes!=0);
#endif
        ++calls;
        last_size=bytes;
        return null_scratch ? VK_NULL_HANDLE : bytes;
    }
    void ReinterpretImage(Image& dst,const std::vector<ImageCopy>& copies) {
#ifndef PS5_NATIVE
        if (ENABLE_MSAA_RESOLVE_CONSUME) InvalidateResolveShadow(dst.Handle());
#endif
__SOURCE_EMPTY_GUARD__
__SOURCE_SIZE_GUARD__
        static_cast<void>(copy_buffer);
    }
    void CopyImage(Image& dst, Image& src, const std::vector<ImageCopy>& copies) {
__SOURCE_COPY_GUARD__
        if (BytesPerBlock(src.info.format) != BytesPerBlock(dst.info.format)) {
            ReinterpretImage(dst, copies);
        } else {
            ++direct_copies;
        }
    }
    std::size_t blits{};
    void BlitImage(const Region2D& dst_region, const Region2D& src_region) {
__SOURCE_BLIT_GUARD__
        // Desktop intentionally has no native guard; mark fixture parameters
        // used without altering either mode's source-extracted behavior.
        static_cast<void>(dst_region);
        static_cast<void>(src_region);
        ++blits;
    }
    std::size_t msaa_copies{};
    void CopyImageMSAA(const std::vector<ImageCopy>& copies) {
__SOURCE_MSAA_GUARD__
        // The pinned desktop has no MSAA no-op guard; retain its call,
        // but mark this reduced fixture's otherwise-unused parameter.
        static_cast<void>(copies);
        ++msaa_copies;
    }
};
int main() {
    Image normal{{4}};
    Runtime empty;
    empty.ReinterpretImage(normal,{});
#ifdef PS5_NATIVE
    assert(empty.calls==0 && empty.invalidates==0);
#else
    assert(empty.calls==1 && empty.last_size==0);
#endif
    Runtime valid;
    valid.ReinterpretImage(normal,{{{4,5,1}},{{4,1,2}}});
    assert(valid.calls==1 && valid.last_size==112);
    assert(valid.invalidates==1);
    Runtime rejected_handle;
    rejected_handle.null_scratch=true;
    rejected_handle.ReinterpretImage(normal,{{{4,5,1}}});
#ifdef PS5_NATIVE
    assert(rejected_handle.calls==1 && rejected_handle.invalidates==0);
#else
    assert(rejected_handle.calls==1 && rejected_handle.invalidates==1);
#endif
    Runtime empty_compatible;
    empty_compatible.CopyImage(normal,normal,{});
#ifdef PS5_NATIVE
    assert(empty_compatible.calls==0 && empty_compatible.invalidates==0 &&
           empty_compatible.direct_copies==0);
#else
    // Desktop retains its historical empty-command and resolve invalidation.
    assert(empty_compatible.calls==0 && empty_compatible.invalidates==1 &&
           empty_compatible.direct_copies==1);
#endif
    Runtime blit;
    const Region2D valid_region{{0,0},{12,9}};
    const Region2D flipped_region{{12,9},{0,0}};
    const Region2D no_x{{4,0},{4,9}};
    const Region2D no_y{{0,4},{12,4}};
    blit.BlitImage(valid_region,valid_region);
    blit.BlitImage(flipped_region,valid_region);
    blit.BlitImage(valid_region,flipped_region);
    blit.BlitImage(no_x,valid_region);
    blit.BlitImage(no_y,valid_region);
    blit.BlitImage(valid_region,no_x);
    blit.BlitImage(valid_region,no_y);
#ifdef PS5_NATIVE
    assert(blit.blits==3);
#else
    assert(blit.blits==7);
#endif
    Runtime msaa_empty;
    msaa_empty.CopyImageMSAA({});
#ifdef PS5_NATIVE
    assert(msaa_empty.msaa_copies==0);
#else
    assert(msaa_empty.msaa_copies==1);
#endif
    Runtime msaa_valid;
    msaa_valid.CopyImageMSAA({{{4,5,1}}});
    assert(msaa_valid.msaa_copies==1);
    Runtime mismatch;
    Image second_format{{8}};
    mismatch.CopyImage(normal,second_format,{{{4,5,1}}});
    assert(mismatch.calls==1 && mismatch.last_size==80);
#ifdef PS5_NATIVE
    assert(mismatch.invalidates==1);
#else
    assert(mismatch.invalidates==2);  // pinned desktop double invalidation
#endif
    Runtime mismatch_rejected;
    mismatch_rejected.null_scratch=true;
    mismatch_rejected.CopyImage(normal,second_format,{{{4,5,1}}});
#ifdef PS5_NATIVE
    assert(mismatch_rejected.invalidates==0);  // valid previous resolve survives
#else
    assert(mismatch_rejected.invalidates==2);  // pinned desktop outer + inner invalidation
#endif
    Runtime direct;
    direct.CopyImage(normal,normal,{{{4,5,1}}});
    assert(direct.direct_copies==1 && direct.calls==0 && direct.invalidates==1);
    Image invalid_format{{0}};
    Runtime invalid;
    invalid.ReinterpretImage(invalid_format,{{{4,5,1}}});
#ifdef PS5_NATIVE
    assert(invalid.calls==0 && invalid.invalidates==0);
#endif
    for (ImageCopy copy : {ImageCopy{{0,5,1}},ImageCopy{{4,0,1}},
                           ImageCopy{{4,5,0}}}) {
        Runtime zero;
        zero.ReinterpretImage(normal,{copy});
#ifdef PS5_NATIVE
        assert(zero.calls==0 && zero.invalidates==0);
#endif
    }
    const u32 max=(std::numeric_limits<u32>::max)();
    Runtime product;
    product.ReinterpretImage(normal,{{{max,max,max}}});
#ifdef PS5_NATIVE
    assert(product.calls==0 && product.invalidates==0);
#endif
    // A positive, non-overflowing size above the last scratch-array slot
    // must also be rejected before GetTemporaryBuffer can index past it.
    Image one_byte{{1}};
    Runtime above_slot;
    above_slot.ReinterpretImage(one_byte,{{{max,max,1}}});
#ifdef PS5_NATIVE
    assert(above_slot.calls==0 && above_slot.invalidates==0);
#endif
    // Keep an independent accumulative overflow witness in the source;
    // the scratch slot ceiling normally rejects this sequence even earlier.
    Runtime aggregate;
    aggregate.ReinterpretImage(one_byte,{{{max,max,1}},{{max,max,1}}});
#ifdef PS5_NATIVE
    assert(aggregate.calls==0 && aggregate.invalidates==0);
#endif
}
""".replace("__SOURCE_EMPTY_GUARD__",early).replace("__SOURCE_SIZE_GUARD__",size).replace("__SOURCE_COPY_GUARD__",copy_guard).replace("__SOURCE_MSAA_GUARD__",msaa_guard).replace("__SOURCE_BLIT_GUARD__",blit_guard)
compiler=shutil.which("clang++-18") or shutil.which("clang++") or shutil.which("g++")
assert compiler,"F07 reinterpret scratch witness needs C++20 compiler"
with tempfile.TemporaryDirectory(prefix="eden-f07-vulkan-reinterpret-") as folder:
    path=Path(folder)/"reinterpret.cpp"
    path.write_text(cpp)
    for opt in ("-O0","-O2"):
        for native in (False,True):
            binary=Path(folder)/("reinterpret"+opt[1:]+("-ps5" if native else "-desktop"))
            cmd=[compiler,"-std=c++20",opt,"-Wall","-Wextra","-Werror",
                 "-fsanitize=undefined","-fno-sanitize-recover=all",
                 *(['-DPS5_NATIVE=1'] if native else []),str(path),"-o",str(binary)]
            built=subprocess.run(cmd,capture_output=True,text=True,timeout=45)
            assert built.returncode==0,(native,opt,built.stderr[-6000:])
            ran=subprocess.run([str(binary)],capture_output=True,text=True,timeout=15)
            assert ran.returncode==0,(native,opt,ran.stderr[-6000:])
# Execute the maintained native image upload no-op before any resolve,
# rescale or GPU copy. The original desktop path still enters normally.
upload_cpp = r"""
#include <cassert>
#include <cstddef>
#include <span>
struct Copy { unsigned pixels{}; };
struct Image {
    unsigned invalidations{}, rescales{}, submissions{};
    void UploadMemory(std::span<const Copy> copies) {
__UPLOAD_GUARD__
        static_cast<void>(copies); // desktop retains the original no-guard path
        ++invalidations;
        ++rescales;
        ++submissions;
    }
};
int main() {
    Image image;
    image.UploadMemory({});
#ifdef PS5_NATIVE
    assert(image.invalidations==0 && image.rescales==0 && image.submissions==0);
#else
    assert(image.invalidations==1 && image.rescales==1 && image.submissions==1);
#endif
    const Copy actual[]{Copy{64}};
    image.UploadMemory(actual);
#ifdef PS5_NATIVE
    assert(image.invalidations==1 && image.rescales==1 && image.submissions==1);
#else
    assert(image.invalidations==2 && image.rescales==2 && image.submissions==2);
#endif
}
""".replace("__UPLOAD_GUARD__", upload_guard)
with tempfile.TemporaryDirectory(prefix="eden-f07-empty-upload-") as folder:
    cpp_path=Path(folder)/"upload.cpp"
    cpp_path.write_text(upload_cpp)
    for opt in ("-O0","-O2"):
        for native in (False,True):
            binary=Path(folder)/("upload"+opt[2:]+("ps5" if native else "desktop"))
            cmd=[compiler,"-std=c++20",opt,"-Wall","-Wextra","-Werror",
                 "-fsanitize=undefined","-fno-sanitize-recover=all",
                 *(["-DPS5_NATIVE=1"] if native else []),
                 str(cpp_path),"-o",str(binary)]
            run=subprocess.run(cmd,capture_output=True,text=True,timeout=45)
            assert run.returncode==0,(native,opt,run.stderr[-5000:])
            run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=20)
            assert run.returncode==0,(native,opt,run.stderr[-5000:])
print("F07_NATIVE_EMPTY_IMAGE_UPLOAD_PASS no_resolve_drop=1 no_gpu_work=1 desktop_original=1 O0=1 O2=1")
print("F07_REINTERPRET_SCRATCH_BOUNDS_PASS native_empty=1 zero_extents=1 invalid_format=1 overflow_product=1 overflow_sum=1 scratch_slot_ceiling=1 invalid_resolve_untouched=1 null_handle_not_submitted=1 copy_reinterpret_shadow=1 empty_copy_noop=1 empty_msaa_noop=1 zero_area_blit_noop=1 flipped_blit_preserved=1 valid=1 desktop_original=1 O0=1 O2=1")


# F07 P0.3: compile the selected scratch-reuse and frame-GC methods, not a
# hand-copied implementation. The native path reads one monotone GPU tick per
# pass; the desktop path keeps scheduler.IsFree for every candidate.
gc_begin="VkImage TextureCacheRuntime::AcquireMsaaScratchImage("
gc_end="\nvoid TextureCacheRuntime::ReleaseMsaaScratchImage("
tick_begin="void TextureCacheRuntime::TickFrame() {"
tick_end="\nImage::Image(TextureCacheRuntime& runtime_"
assert source.count(gc_begin)==source.count(gc_end)==1
assert source.count(tick_begin)==source.count(tick_end)==1
gc_acquire=source[source.index(gc_begin):source.index(gc_end,source.index(gc_begin))]
gc_tick=source[source.index(tick_begin):source.index(tick_end,source.index(tick_begin))]
assert "F07 snapshot native MSAA scratch reuse GPU completion" in generator
assert "F07 snapshot native MSAA scratch and resolve cleanup GPU completion" in generator
assert "F07 skip GPU completion probe on empty native MSAA scratch list" in generator
assert "F07 skip GPU completion probe on empty native MSAA GC frame" in generator
assert "F07 avoid native MSAA GPU completion probe without matching image key" in generator
assert "F07 skip MSAA GPU probe when every scratch image is checked out" in generator
assert "sampled_completed_tick" in gc_acquire
assert gc_acquire.index("if (scratch.key != key)") < gc_acquire.index("KnownGpuTick()")
assert "if (msaa_scratch_images.empty() && pending_resolve_shadows.empty() &&" in gc_tick
assert "pending_retired_views.empty() && pending_retired_images.empty()" in gc_tick
assert "pending_resolve_shadows.empty() && pending_retired_views.empty() &&" in gc_tick
assert "std::erase_if(pending_retired_views, ready);" in gc_tick
assert "std::erase_if(pending_retired_images, ready);" in gc_tick
assert gc_tick.index("std::erase_if(pending_retired_views, ready);") < gc_tick.index(
    "std::erase_if(pending_retired_images, ready);")
assert "std::all_of(msaa_scratch_images.begin()" in gc_tick
assert "return scratch.tick == (std::numeric_limits<u64>::max)();" in gc_tick
assert gc_tick.index("if (msaa_scratch_images.empty() && pending_resolve_shadows.empty() &&") < gc_tick.index("KnownGpuTick()")
assert gc_acquire.count("KnownGpuTick()")==1
assert gc_tick.count("KnownGpuTick()")==1
assert "scratch.tick > completed_tick" in gc_acquire
assert "tick <= completed_tick" in gc_tick
assert gc_tick.count("is_free(")==3
gc_cpp=r"""
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <memory>
#include <utility>
#include <vector>
using u32=std::uint32_t;
using u64=std::uint64_t;
using VkImage=u64;
struct VkImageCreateInfo {
    int format{},imageType{};
    struct {u32 width{},height{},depth{};} extent;
    u32 mipLevels{},arrayLayers{},usage{},flags{};
};
struct MsaaScratchKey {
    int format{},type{};
    u32 width{},height{},depth{},levels{},layers{},usage{},flags{};
    bool operator==(const MsaaScratchKey&) const = default;
};
struct MsaaScratchImage {
    MsaaScratchKey key{};
    std::shared_ptr<VkImage> image{};
    u64 tick{};
    u32 unused_frames{};
};
struct PendingGpuResource {
    u64 tick{};
    u64 frame{};
};
struct Semaphore {
    u64 completed{};
    mutable u32 polls{};
    u64 KnownGpuTick() const {++polls;return completed;}
};
struct Scheduler {
    Semaphore semaphore{};
    u32 is_free_calls{};
    Semaphore& GetMasterSemaphore() {return semaphore;}
    bool IsFree(u64 tick) {++is_free_calls;return tick<=semaphore.KnownGpuTick();}
    u64 CurrentTick() {return 100;}
};
struct Allocator {
    u64 next=1;
    std::shared_ptr<VkImage> CreateImage(const VkImageCreateInfo&) {
        return std::make_shared<VkImage>(next++);
    }
};
struct TextureCacheRuntime {
    Scheduler scheduler{};
    Allocator memory_allocator{};
    std::vector<MsaaScratchImage> msaa_scratch_images{};
    std::vector<std::pair<u64,int>> pending_resolve_shadows{};
    std::vector<PendingGpuResource> pending_retired_views{};
    std::vector<PendingGpuResource> pending_retired_images{};
    u64 gpu_retire_frame{};
    VkImage AcquireMsaaScratchImage(const VkImageCreateInfo&);
    void TickFrame();
};
__GC_ACQUIRE__
__GC_TICK__
int main() {
    TextureCacheRuntime r;
    // Native has no pending MSAA objects at startup. Both operations must
    // avoid even the formerly unconditional GPU completion snapshot.
    r.TickFrame();
#ifdef PS5_NATIVE
    assert(r.scheduler.semaphore.polls==0);
#endif
    // Checked-out scratch has no retired tick. Multiple GC frames must not
    // probe the GPU; releasing it must resume the original aging behavior.
    TextureCacheRuntime checked_out;
    checked_out.msaa_scratch_images.push_back(
        {{},std::make_shared<VkImage>(4242),std::numeric_limits<u64>::max(),0});
    checked_out.TickFrame();
    checked_out.TickFrame();
#ifdef PS5_NATIVE
    assert(checked_out.scheduler.semaphore.polls==0);
    assert(checked_out.scheduler.is_free_calls==0);
#else
    assert(checked_out.scheduler.is_free_calls==2);
#endif
    assert(checked_out.msaa_scratch_images[0].unused_frames==0);
    checked_out.msaa_scratch_images[0].tick=5;
    checked_out.scheduler.semaphore.completed=5;
    checked_out.TickFrame();
    assert(checked_out.msaa_scratch_images[0].unused_frames==1);
#ifdef PS5_NATIVE
    assert(checked_out.scheduler.semaphore.polls==1);
#else
    assert(checked_out.scheduler.is_free_calls==3);
#endif
    VkImageCreateInfo ci{};
    ci.format=2;ci.imageType=3;ci.extent={64,32,1};
    ci.mipLevels=1;ci.arrayLayers=1;ci.usage=7;ci.flags=0;
    const MsaaScratchKey key{2,3,64,32,1,1,1,7,0};
    TextureCacheRuntime cold;
    assert(cold.AcquireMsaaScratchImage(ci)==1);
#ifdef PS5_NATIVE
    assert(cold.scheduler.semaphore.polls==0);
#endif
    // Nonempty cache, no matching image key: the native GPU semaphore must
    // not be sampled. The original desktop key rejection is unchanged.
    TextureCacheRuntime no_match;
    auto other_key=key;
    other_key.format=999;
    no_match.msaa_scratch_images.push_back(
        {other_key,std::make_shared<VkImage>(777),0,0});
    assert(no_match.AcquireMsaaScratchImage(ci)==1);
#ifdef PS5_NATIVE
    assert(no_match.scheduler.semaphore.polls==0);
#else
    assert(no_match.scheduler.is_free_calls==0);
#endif
    for (u64 i=0;i<8;++i)
        r.msaa_scratch_images.push_back({key,std::make_shared<VkImage>(100+i),
                                        i==0 ? u64{8} : u64{20}, 0});
    r.scheduler.semaphore.completed=5;
    assert(r.AcquireMsaaScratchImage(ci)==1);
#ifdef PS5_NATIVE
    assert(r.scheduler.semaphore.polls==1 && r.scheduler.is_free_calls==0);
#else
    assert(r.scheduler.is_free_calls==8);
#endif
    r.scheduler.semaphore.completed=8;
    assert(r.AcquireMsaaScratchImage(ci)==100);
    assert(r.msaa_scratch_images[0].tick==std::numeric_limits<u64>::max());
    r.msaa_scratch_images[1].tick=9;
    r.msaa_scratch_images[1].unused_frames=60;
    r.msaa_scratch_images[2].tick=10;
    r.msaa_scratch_images[2].unused_frames=60;
    r.msaa_scratch_images[3].tick=7;
    r.msaa_scratch_images[3].unused_frames=1;
    r.pending_resolve_shadows={{7,1},{9,2},{10,3}};
    r.scheduler.semaphore.completed=9;
    [[maybe_unused]] const auto before_polls=r.scheduler.semaphore.polls;
    const auto before_isfree=r.scheduler.is_free_calls;
    r.TickFrame();
    assert(r.msaa_scratch_images.size()==8);
    assert(r.pending_resolve_shadows.size()==1);
    assert(r.pending_resolve_shadows[0].first==10);
    const auto find_image=[&](u64 id) {
        return std::find_if(r.msaa_scratch_images.begin(),r.msaa_scratch_images.end(),
                            [id](const auto& s){return *s.image==id;});
    };
    assert(find_image(101)==r.msaa_scratch_images.end());
    assert(find_image(102)!=r.msaa_scratch_images.end());
    assert(find_image(102)->unused_frames==0);
    assert(find_image(103)->unused_frames==2);
#ifdef PS5_NATIVE
    assert(r.scheduler.semaphore.polls==before_polls+1);
    assert(r.scheduler.is_free_calls==before_isfree);
#else
    assert(r.scheduler.is_free_calls>before_isfree+3);
#endif
    r.scheduler.semaphore.completed=10;
    r.TickFrame();
    assert(r.pending_resolve_shadows.empty());
    // The first completed tick starts the 60-frame idle counter. The scratch
    // must NOT be retired after only one eligible frame (native and desktop).
    assert(find_image(102)!=r.msaa_scratch_images.end());
    assert(find_image(102)->unused_frames==1);
    for (u32 frame=0;frame<59;++frame) r.TickFrame();
    assert(find_image(102)!=r.msaa_scratch_images.end());
    assert(find_image(102)->unused_frames==60);
    r.TickFrame();
    assert(find_image(102)==r.msaa_scratch_images.end());
    // Also cover resolve-only cleanup, which must still query completion.
    TextureCacheRuntime resolve_only;
    resolve_only.pending_resolve_shadows={{1,1}};
    resolve_only.scheduler.semaphore.completed=1;
    resolve_only.TickFrame();
    assert(resolve_only.pending_resolve_shadows.empty());
#ifdef PS5_NATIVE
    assert(resolve_only.scheduler.semaphore.polls==1);
    // Resource retirement shares the same GPU completion snapshot: a
    // view/image-only frame MUST NOT take the old empty-GC fast path.
    TextureCacheRuntime retirement;
    retirement.pending_retired_views.push_back({7, 0});
    retirement.pending_retired_images.push_back({8, 0});
    retirement.scheduler.semaphore.completed = 7;
    for (u32 i=0; i<7; ++i) retirement.TickFrame();
    assert(retirement.pending_retired_views.size()==1);
    assert(retirement.pending_retired_images.size()==1);
    retirement.TickFrame();
    assert(retirement.pending_retired_views.empty());
    assert(retirement.pending_retired_images.size()==1); // tick 8 not done
    retirement.scheduler.semaphore.completed = 8;
    retirement.TickFrame();
    assert(retirement.pending_retired_images.empty());
    assert(retirement.scheduler.semaphore.polls==9);
#else
    assert(resolve_only.scheduler.is_free_calls==1);
#endif
    std::puts("F07_MSAA_COMPLETION_SNAPSHOT_PASS");
}
""".replace("__GC_ACQUIRE__",gc_acquire).replace("__GC_TICK__",gc_tick)
with tempfile.TemporaryDirectory(prefix="eden-f07-msaa-snapshot-") as folder:
    unit=Path(folder)/"msaa.cpp"
    unit.write_text(gc_cpp)
    for opt in ("-O0","-O2"):
        for native in (False,True):
            binary=Path(folder)/("msaa"+opt[1:]+("-ps5" if native else "-desktop"))
            cmd=[compiler,"-std=c++20",opt,"-Wall","-Wextra","-Werror",
                 "-fsanitize=undefined","-fno-sanitize-recover=all",
                 *(['-DPS5_NATIVE=1'] if native else []),str(unit),"-o",str(binary)]
            built=subprocess.run(cmd,capture_output=True,text=True,timeout=45)
            assert built.returncode==0,(native,opt,built.stderr[-6000:])
            ran=subprocess.run([str(binary)],capture_output=True,text=True,timeout=15)
            assert ran.returncode==0,(native,opt,ran.stderr[-6000:])
print("F07_MSAA_GC_SOURCE_EXTRACTED_PASS native_one_tick_per_scan=1 empty_scan_no_poll=1 checked_out_no_poll=1 wrong_key_no_poll=1 resolve_only=1 desktop_original=1 delayed_reuse_safe=1 O0=1 O2=1")
