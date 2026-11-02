// SPDX-License-Identifier: GPL-3.0-or-later
// Host-only conformance for the real QMD3 -> Shader::Environment ABI.
// No fake Vulkan submission or Switch 1 Kepler launch metadata.
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <memory>
#include <stdexcept>
#include <utility>
#include "shader_recompiler/frontend/ampere/native_qmd_compute_environment.h"

struct TextureMetadata final : Shader::Environment {
    TextureMetadata() { stage=Shader::Stage::Compute; }
    u64 ReadInstruction(u32) override { return 0; }
    u32 ReadCbufValue(u32,u32) override { return 0; }
    Shader::TextureType ReadTextureType(u32) override { return {}; }
    Shader::TexturePixelFormat ReadTexturePixelFormat(u32) override { return {}; }
    bool IsTexturePixelFormatInteger(u32) override { return true; }
    u32 ReadViewportTransformState() override { return 7; }
    u32 TextureBoundBuffer() const override { return 2; }
    u32 LocalMemorySize() const override { return 1; }
    u32 SharedMemorySize() const override { return 1; }
    std::array<u32,3> WorkgroupSize() const override { return {9,9,9}; }
    bool HasHLEMacroState() const override { return false; }
    std::optional<Shader::ReplaceConstant> GetReplaceConstBuffer(u32,u32) override {
        return std::nullopt;
    }
    void Dump(u64,u64) override { std::abort(); }
};
// The production native Compute retirement helper, tested with a
// timeline-backed scheduler and a fence manager that does NOT delay the
// guest callback. Only SyncOperation can retain the owner until completion.
struct NativeRetirementMockScheduler {
    u64 current_tick{};
    u64 waited{};
    bool gpu_completed{};
    u64 Flush() { return ++current_tick; }
    void Wait(u64 tick) {
        assert(gpu_completed && tick == current_tick);
        waited = tick;
    }
};
struct NativeRetirementMockFences {
    std::function<void()> pending{};
    bool signaled{};
    bool reject_registration{};
    void SyncOperation(std::function<void()>&& operation) {
        if (reject_registration) throw std::runtime_error{"mock fence registration failure"};
        assert(!pending);
        pending = std::move(operation);
    }
    void SignalReference() {
        // Guest callbacks would run immediately in this fence policy,
        // but the SyncOperation callback is still pending.
        signaled = true;
    }
};
struct MockMappedGpu {
    u64 address{};
    std::array<u32,8> words{0xabcdef01,0x11223344,0x55667788,0x99aabbcc};
    unsigned reads{};
    bool mapped{true};
};
static bool Read(void* context,u64 address,void* destination,std::size_t bytes) {
    auto& memory=*static_cast<MockMappedGpu*>(context);
    ++memory.reads;
    if (!memory.mapped || !destination || bytes!=sizeof(u32) ||
        address < memory.address || address-memory.address > 28 ||
        (address-memory.address)%4)
        return false;
    std::memcpy(destination,
                &memory.words[(address-memory.address)/4],sizeof(u32));
    return true;
}
template <typename F>
static bool Reject(F&& call) {
    try { call(); } catch (const std::exception&) { return true; }
    return false;
}
int main() {
    using Shader::Ampere::NativeQmdComputeEnvironment;
    {
        NativeRetirementMockScheduler scheduler{};
        NativeRetirementMockFences fences{};
        int destroyed{};
        auto pipeline = std::shared_ptr<int>(
            new int(7), [&](int* value) { ++destroyed; delete value; });
        Shader::Ampere::RetainNativeComputeUntilGpuTick(
            scheduler, fences, std::move(pipeline));
        assert(fences.signaled && fences.pending && scheduler.current_tick == 1);
        assert(destroyed == 0 && scheduler.waited == 0);
        scheduler.gpu_completed = true;
        auto deferred = std::move(fences.pending);
        fences.pending = {};
        deferred();
        assert(scheduler.waited == 1 && destroyed == 0);
        deferred = {};
        assert(destroyed == 1);
    }
    {
        // A failed SyncOperation registration must not destroy the
        // pipeline before the submitted GPU tick has been waited.
        NativeRetirementMockScheduler scheduler{};
        scheduler.gpu_completed = true;
        NativeRetirementMockFences fences{};
        fences.reject_registration = true;
        int destroyed{};
        auto pipeline = std::shared_ptr<int>(
            new int(9), [&](int* value) {
                assert(scheduler.waited == scheduler.current_tick);
                ++destroyed;
                delete value;
            });
        bool refused{};
        try {
            Shader::Ampere::RetainNativeComputeUntilGpuTick(
                scheduler, fences, std::move(pipeline));
        } catch (const std::runtime_error&) {
            refused = true;
        }
        assert(refused && scheduler.current_tick == 1 &&
               scheduler.waited == 1 && destroyed == 1);
    }
    Tegra::NativeQmdScheduler::Descriptor qmd{};
    qmd[8]=0x80;
    qmd[12]=3; qmd[13]=4; qmd[14]=5;
    qmd[17]=0x320;
    qmd[18]=0x30 | (8U<<16);
    qmd[19]=(2U<<16)|16U;
    qmd[20]=1U;
    qmd[23]=0x100080;
    qmd[48]=0x12000000U;
    qmd[49]=0x10000U;
    qmd[50]=0x100040U;
    qmd[32]=0x12340000U;
    qmd[33]=0x10000U | (1U<<19); // 49-bit CBUF, exactly 16 bytes.
    // Bound the product, not only individual block axes: Ampere has a
    // maximum of 1024 threads per CTA. Invalid launch resource requests
    // must fail before a Vulkan shader or descriptor allocation is started.
    auto oversized=qmd;
    oversized[18]=0x30U | (64U<<16);
    oversized[19]=(2U<<16)|16U; // 2048 threads
    assert(!Tegra::DecodeNativeComputeLaunch(oversized));
    auto boundary=qmd;
    boundary[18]=0x30U | (32U<<16);
    boundary[19]=(2U<<16)|16U; // exactly 1024 threads
    assert(Tegra::DecodeNativeComputeLaunch(boundary));
    auto zero_block=qmd;
    zero_block[19]=(2U<<16); // zero Y dimension
    assert(!Tegra::DecodeNativeComputeLaunch(zero_block));
    const auto decoded=Tegra::DecodeNativeComputeLaunch(qmd);
    assert(decoded && decoded->constant_buffers[0].enabled);
    // Device limits are stricter than the Ampere 1024-thread QMD bound.
    // Validate the same policy without a PS5/Vulkan driver at host time.
    Tegra::NativeComputeDeviceLimits limits{
        {65535,65535,65535},{1024,1024,64},1024,65536};
    assert(Tegra::NativeComputeLaunchWithinDeviceLimits(*decoded,limits));
    limits.max_grid[1]=3; // actual grid Y = 4
    assert(!Tegra::NativeComputeLaunchWithinDeviceLimits(*decoded,limits));
    limits.max_grid[1]=65535;
    limits.max_block[2]=1; // actual CTA Z = 2
    assert(!Tegra::NativeComputeLaunchWithinDeviceLimits(*decoded,limits));
    limits.max_block[2]=64;
    limits.max_invocations=255; // actual CTA = 8 * 16 * 2 = 256
    assert(!Tegra::NativeComputeLaunchWithinDeviceLimits(*decoded,limits));
    limits.max_invocations=1024;
    limits.max_shared_bytes=0x31f; // actual dynamic shared = 0x320
    assert(!Tegra::NativeComputeLaunchWithinDeviceLimits(*decoded,limits));
    limits.max_shared_bytes=0x320;
    assert(Tegra::NativeComputeLaunchWithinDeviceLimits(*decoded,limits));
    limits.max_invocations=0;
    assert(!Tegra::NativeComputeLaunchWithinDeviceLimits(*decoded,limits));
    assert(decoded->constant_buffers[0].gpu_address==0x1000012340000ULL);
    MockMappedGpu memory{};
    memory.address=decoded->constant_buffers[0].gpu_address;
    NativeQmdComputeEnvironment env{
        *decoded,Read,&memory,std::make_unique<TextureMetadata>()};
    assert(env.ShaderStage()==Shader::Stage::Compute);
    assert(env.Launch().program_address==0x1000012000080ULL);
    assert((env.WorkgroupSize()==std::array<u32,3>{8,16,2}));
    assert((env.Launch().grid==std::array<u32,3>{3,4,5}));
    assert(env.SharedMemorySize()==0x320);
    assert(env.LocalMemorySize()==0x2000c0);
    assert(env.TextureBoundBuffer()==2 && env.ReadViewportTransformState()==7);
    assert(env.IsTexturePixelFormatInteger(99));
    assert(env.ReadCbufValue(0,0)==0xabcdef01);
    assert(env.ReadCbufValue(0,12)==0x99aabbcc);
    assert(memory.reads==2);
    assert(Reject([&]{(void)env.ReadCbufValue(0,16);}));
    assert(Reject([&]{(void)env.ReadCbufValue(0,2);}));
    assert(Reject([&]{(void)env.ReadCbufValue(1,0);}));
    assert(Reject([&]{(void)env.ReadCbufValue(8,0);}));
    assert(memory.reads==2); // Invalid ranges never touch guest memory.
    memory.mapped=false;
    assert(Reject([&]{(void)env.ReadCbufValue(0,0);}));
    assert(Reject([&]{(void)env.ReadInstruction(0);}));
    auto invalid=*decoded;
    invalid.constant_buffers[0].gpu_address=(u64{1}<<49)-4;
    invalid.constant_buffers[0].size=16;
    NativeQmdComputeEnvironment overflow{
        invalid,Read,&memory,std::make_unique<TextureMetadata>()};
    assert(Reject([&]{(void)overflow.ReadCbufValue(0,0);}));
    assert(Reject([&]{
        NativeQmdComputeEnvironment null_reader{
            *decoded,nullptr,&memory,std::make_unique<TextureMetadata>()};
    }));
    assert(Reject([&]{
        NativeQmdComputeEnvironment null_metadata{
            *decoded,Read,&memory,nullptr};
    }));
    assert(Reject([&]{
        auto bad=*decoded; bad.block[1]=0;
        NativeQmdComputeEnvironment invalid_block{
            bad,Read,&memory,std::make_unique<TextureMetadata>()};
    }));
    // Shader descriptor metadata must produce the SAME 49-bit SSBO base
    // encoded in QMD CBUF words, rather than Kepler's 40-bit address alias.
    memory.mapped=true;
    memory.reads=0;
    memory.words={0x12345000U,0x10000U,0x40U,0U};
    Shader::Info shader_info{};
    shader_info.constant_buffer_mask=1;
    shader_info.constant_buffer_used_sizes[0]=16;
    shader_info.constant_buffer_descriptors.push_back({0,1});
    shader_info.storage_buffers_descriptors.push_back({0,0,1,true});
    const auto plan=env.BuildResourcePlan(shader_info);
    assert(plan && plan->uniform_buffers.size()==1 &&
           plan->uniform_buffers[0].qmd_index==0 &&
           plan->uniform_buffers[0].gpu_address==memory.address &&
           plan->uniform_buffers[0].bytes==16 &&
           plan->storage_buffers.size()==1 &&
           plan->storage_buffers[0].gpu_address==0x1000012345000ULL &&
           plan->storage_buffers[0].bytes==0x40 &&
           plan->storage_buffers[0].is_written &&
           plan->storage_buffers[0].known_size &&
           !plan->requires_memory_layout && !plan->requires_tic_tsc &&
           memory.reads==4);
    assert(plan->HasResolvedBufferBindings());
    // P2.2: reflected TIC/TSC handle words must be read from the native QMD
    // CBUF, in the shared cache descriptor order. This is NOT an image binding.
    {
        auto textured = shader_info;
        Shader::TextureDescriptor tex{};
        tex.cbuf_index = 0;
        tex.cbuf_offset = 0;
        tex.count = 2;
        tex.size_shift = 2;
        textured.texture_descriptors.push_back(tex);
        const auto tp = env.BuildResourcePlan(textured);
        assert(tp && tp->requires_tic_tsc &&
               tp->image_handles.size() == 2 &&
               tp->image_handles[0].kind ==
                   Shader::Ampere::NativeQmdImageKind::SampledTexture &&
               tp->image_handles[0].primary_word == 0x12345000U &&
               tp->image_handles[1].primary_word == 0x10000U &&
               !tp->HasResolvedBufferBindings());
        // Real TIC/TSC entries are 32-byte guest records, not Vulkan views.
        {
            using Shader::Ampere::NativeQmdTextureTables;
            const u64 tic_base = 0x1000000200000ULL;
            // Keep the fixture sampler pool beyond the largest tested TIC span.
            // The old 4 MiB spacing aliased TIC[0x10000] to TSC[0].
            const u64 tsc_base = 0x1000002000000ULL;
            NativeQmdTextureTables tables{
                .tic_base = tic_base, .tsc_base = tsc_base,
                .tic_limit = 0x45000U, .tsc_limit = 0x123U};
            unsigned tic_reads{}, tsc_reads{};
            const auto reader = [&](u64 address, void* out, std::size_t bytes) {
                if (bytes != 32 || !out) return false;
                auto* words = static_cast<u32*>(out);
                for (unsigned i = 0; i < 8; ++i) words[i] = 0xabc00000U + i;
                if (address == tic_base + u64{0x45000} * 32 ||
                    address == tic_base + u64{0x10000} * 32) {
                    ++tic_reads; return true;
                }
                if (address == tsc_base + u64{0x123} * 32 ||
                    address == tsc_base) {
                    ++tsc_reads; return true;
                }
                return false;
            };
            const auto records = tables.Capture(*tp, reader);
            assert(records && records->size() == 2 &&
                   (*records)[0].raw_handle == 0x12345000U &&
                   (*records)[0].tic_index == 0x45000U &&
                   (*records)[0].tsc_index == 0x123U &&
                   (*records)[0].has_sampler &&
                   (*records)[0].tic_words[0] == 0xabc00000U &&
                   (*records)[1].tic_index == 0x10000U &&
                   (*records)[1].tsc_index == 0 &&
                   tic_reads == 2 && tsc_reads == 2);
            auto invalid = tables;
            invalid.tsc_limit = 0x122U;
            assert(!invalid.Capture(*tp, reader));
            invalid = tables;
            invalid.tic_base = 0;
            assert(!invalid.Capture(*tp, reader));
            invalid = tables;
            invalid.tic_base = (u64{1} << 49) - 32;
            assert(!invalid.Capture(*tp, reader));
            invalid = tables;
            invalid.linked_tsc = true;
            assert(!invalid.Capture(*tp, reader));
            invalid = tables;
            invalid.tic_base++;
            assert(!invalid.Capture(*tp, reader));
            assert(!tables.Capture(*tp, [&](u64 address, void* out,
                                            std::size_t bytes) {
                return address < tsc_base && reader(address, out, bytes);
            }));
            auto overflowing = *tp;
            overflowing.image_handles[0].primary_shift = 31;
            assert(!tables.Capture(overflowing, reader));
            const auto none = tables.Capture(*plan, reader);
            assert(none && none->empty());
        }
        // A separate sampler/texture word must never be mistaken for a
        // contiguous NS1 TIC/TSC table, even when both source banks match.
        tex.has_secondary = true;
        tex.count = 1;
        tex.shift_left = 3;
        tex.secondary_cbuf_index = 0;
        tex.secondary_cbuf_offset = 8;
        tex.secondary_shift_left = 4;
        textured.texture_descriptors.clear();
        textured.texture_descriptors.push_back(tex);
        const auto paired = env.BuildResourcePlan(textured);
        assert(paired && paired->image_handles.size() == 1 &&
               paired->image_handles[0].has_secondary &&
               paired->image_handles[0].primary_word == 0x12345000U &&
               paired->image_handles[0].secondary_word == 0x40U &&
               paired->image_handles[0].primary_shift == 3 &&
               paired->image_handles[0].secondary_shift == 4);
        tex.secondary_cbuf_offset = 16; // four-byte word past QMD CBUF
        textured.texture_descriptors.clear();
        textured.texture_descriptors.push_back(tex);
        assert(!env.BuildResourcePlan(textured));
        tex.secondary_cbuf_offset = 8;
        tex.secondary_shift_left = 32; // undefined shift is invalid
        textured.texture_descriptors.clear();
        textured.texture_descriptors.push_back(tex);
        assert(!env.BuildResourcePlan(textured));
        tex.secondary_shift_left = 4;
        tex.secondary_cbuf_offset = 6; // unaligned secondary word
        textured.texture_descriptors.clear();
        textured.texture_descriptors.push_back(tex);
        assert(!env.BuildResourcePlan(textured));
        tex.secondary_cbuf_offset = 8;
        tex.size_shift = 32; // invalid index stride
        textured.texture_descriptors.clear();
        textured.texture_descriptors.push_back(tex);
        assert(!env.BuildResourcePlan(textured));
        tex.size_shift = 2;
        tex.count = 257; // native preflight handle budget
        textured.texture_descriptors.clear();
        textured.texture_descriptors.push_back(tex);
        assert(!env.BuildResourcePlan(textured));
        textured.texture_descriptors.clear();
        Shader::ImageDescriptor image{};
        image.cbuf_index = 0;
        image.cbuf_offset = 4;
        image.count = 1;
        image.is_written = true;
        textured.image_descriptors.push_back(image);
        const auto storage_image = env.BuildResourcePlan(textured);
        assert(storage_image && storage_image->image_handles.size() == 1 &&
               storage_image->image_handles[0].kind ==
                   Shader::Ampere::NativeQmdImageKind::StorageImage &&
               storage_image->image_handles[0].is_written &&
               storage_image->image_handles[0].primary_word == 0x10000U);
        {
            Shader::Ampere::NativeQmdTextureTables tables{
                .tic_base = 0x1000000200000ULL,
                .tsc_base = 0, .tic_limit = 0x10000U, .tsc_limit = 0};
            unsigned reads{};
            const auto records = tables.Capture(*storage_image,
                [&](u64 addr, void* out, std::size_t size) {
                    if (size != 32 ||
                        addr != tables.tic_base + u64{0x10000} * 32)
                        return false;
                    std::memset(out, 0x7f, size);
                    ++reads; return true;
                });
            assert(records && records->size() == 1 &&
                   !(*records)[0].has_sampler &&
                   (*records)[0].is_written && reads == 1);
        }
        image.count = 0;
        textured.image_descriptors.clear();
        textured.image_descriptors.push_back(image);
        assert(!env.BuildResourcePlan(textured));
        memory.mapped = false;
        image.count = 1;
        textured.image_descriptors.clear();
        textured.image_descriptors.push_back(image);
        assert(!env.BuildResourcePlan(textured)); // stale GMMU denied
        memory.mapped = true;
    }
    unsigned mapped_spans{};
    assert(plan->ValidateGpuMappings([&](u64 addr, std::size_t bytes) {
        ++mapped_spans;
        return (addr==memory.address && bytes==16) ||
               (addr==0x1000012345000ULL && bytes==0x40);
    }));
    assert(mapped_spans==2);
    // Mutable native CBUF descriptors can change during shader compilation
    // without making either GPU address unmapped. Compare every binding,
    // including write rights and known-size admission, before Vulkan use.
    assert(plan->SameBufferBindings(*plan));
    auto changed_plan = *plan;
    changed_plan.uniform_buffers[0].gpu_address += 0x1000;
    assert(!plan->SameBufferBindings(changed_plan));
    changed_plan = *plan;
    changed_plan.uniform_buffers[0].bytes += 4;
    assert(!plan->SameBufferBindings(changed_plan));
    changed_plan = *plan;
    ++changed_plan.uniform_buffers[0].qmd_index;
    assert(!plan->SameBufferBindings(changed_plan));
    changed_plan = *plan;
    changed_plan.storage_buffers[0].gpu_address += 0x1000;
    assert(!plan->SameBufferBindings(changed_plan));
    changed_plan = *plan;
    changed_plan.storage_buffers[0].bytes += 16;
    assert(!plan->SameBufferBindings(changed_plan));
    changed_plan = *plan;
    changed_plan.storage_buffers[0].is_written =
        !changed_plan.storage_buffers[0].is_written;
    assert(!plan->SameBufferBindings(changed_plan));
    changed_plan = *plan;
    changed_plan.storage_buffers[0].known_size = false;
    assert(!plan->SameBufferBindings(changed_plan));
    changed_plan = *plan;
    changed_plan.storage_buffers.clear();
    assert(!plan->SameBufferBindings(changed_plan));
    changed_plan = *plan;
    changed_plan.uses_global_memory = !changed_plan.uses_global_memory;
    assert(!plan->SameBufferBindings(changed_plan));
    // A corrupt CBUF/SSBO range at the end of the 49-bit GMMU must fail
    // before the renderer stages even one Vulkan buffer descriptor.
    auto overflowing_plan = *plan;
    overflowing_plan.uniform_buffers[0].gpu_address = (u64{1} << 49) - 8;
    assert(!overflowing_plan.ValidateGpuMappings([](u64, std::size_t) {
        return true;
    }));
    overflowing_plan = *plan;
    overflowing_plan.storage_buffers[0].gpu_address = (u64{1} << 49) - 1;
    assert(!overflowing_plan.ValidateGpuMappings([](u64, std::size_t) {
        return true;
    }));
    // Vulkan BufferCache entrypoint receives the native QMD3 descriptor
    // order without copying the legacy Kepler launch descriptor. Refuse all
    // guest spans before any staging; rollback partial renderer submissions.
    unsigned uniform_binds{}, storage_binds{}, rollback_count{}, stage_order{};
    const auto mapped_all=[&](u64 addr, std::size_t bytes) {
        return (addr==memory.address && bytes==16) ||
               (addr==0x1000012345000ULL && bytes==0x40);
    };
    auto uniform=[&](u32 index,u32 bank,u64 addr,u32 bytes) {
        assert(index==0 && bank==0 && addr==memory.address && bytes==16);
        assert(stage_order++==0);
        ++uniform_binds; return true;
    };
    auto storage=[&](u32 index,u64 addr,u32 bytes,bool written) {
        assert(index==0 && addr==0x1000012345000ULL &&
               bytes==0x40 && written);
        assert(stage_order++==1);
        ++storage_binds; return true;
    };
    auto rollback=[&] { ++rollback_count; stage_order=0; };
    assert(plan->StageVulkanBufferBindings(
        mapped_all,uniform,storage,rollback));
    assert(uniform_binds==1 && storage_binds==1 && rollback_count==0);
    stage_order=0;
    assert(!plan->StageVulkanBufferBindings(
        [](u64,std::size_t){return false;},uniform,storage,rollback));
    assert(uniform_binds==1 && storage_binds==1 && rollback_count==0);
    assert(!plan->StageVulkanBufferBindings(
        mapped_all,
        [&](u32,u32,u64,u32){++uniform_binds; return false;},
        storage,rollback));
    assert(uniform_binds==2 && storage_binds==1 && rollback_count==1);
    stage_order=0;
    assert(!plan->StageVulkanBufferBindings(
        mapped_all,uniform,
        [&](u32,u64,u32,bool){++storage_binds; return false;},rollback));
    assert(uniform_binds==3 && storage_binds==2 && rollback_count==2);
    stage_order=0;
    assert(!plan->StageVulkanBufferBindings(
        mapped_all,uniform,
        [&](u32,u64,u32,bool)->bool{
            throw std::runtime_error{"Vulkan descriptor pool exhausted"};
        },rollback));
    assert(rollback_count==3);
    assert(!plan->ValidateGpuMappings([](u64, std::size_t) {
        return false;
    })); // A mapped QMD is not proof of mapped descriptor targets.
    // Never infer an SSBO size from a high packed tag: the upstream
    // BufferCache must resolve the real memory layout before submission.
    // Two native SSBOs are distinct 16-byte QMD3 CBUF records.
    auto array_launch = *decoded;
    array_launch.constant_buffers[0].size = 32;
    memory.words = {0x12345000U,0x10000U,0x40U,0U,
                    0x22345000U,0x10000U,0x80U,0U};
    NativeQmdComputeEnvironment array_env{
        array_launch,Read,&memory,std::make_unique<TextureMetadata>()};
    auto array_info = shader_info;
    array_info.constant_buffer_used_sizes[0] = 32;
    array_info.storage_buffers_descriptors.clear();
    array_info.storage_buffers_descriptors.push_back({0,0,2,true});
    const auto array_plan = array_env.BuildResourcePlan(array_info);
    assert(array_plan && array_plan->HasResolvedBufferBindings());
    assert(array_plan->storage_buffers.size() == 2);
    assert(array_plan->storage_buffers[0].gpu_address == 0x1000012345000ULL);
    assert(array_plan->storage_buffers[0].bytes == 0x40);
    assert(array_plan->storage_buffers[1].gpu_address == 0x1000022345000ULL);
    assert(array_plan->storage_buffers[1].bytes == 0x80);
    unsigned array_binds{};
    assert(array_plan->StageVulkanBufferBindings(
        [](u64,u32){return true;},
        [](u32,u32,u64,u32){return true;},
        [&](u32 index,u64 address,u32 bytes,bool written) {
            assert(index == array_binds && written);
            assert(address == (index == 0 ? 0x1000012345000ULL
                                          : 0x1000022345000ULL));
            assert(bytes == (index == 0 ? 0x40U : 0x80U));
            ++array_binds; return true;
        },[]{}));
    assert(array_binds == 2);
    auto short_launch = array_launch;
    short_launch.constant_buffers[0].size = 24;
    NativeQmdComputeEnvironment short_env{
        short_launch,Read,&memory,std::make_unique<TextureMetadata>()};
    array_info.constant_buffer_used_sizes[0] = 16;
    assert(!short_env.BuildResourcePlan(array_info));
    array_info.storage_buffers_descriptors[0].count = 33;
    assert(!array_env.BuildResourcePlan(array_info));
    memory.words = {0x12345000U,0x10000U,0x40U,0U};
    memory.words[3]=1;
    const auto unresolved=env.BuildResourcePlan(shader_info);
    assert(unresolved && unresolved->requires_memory_layout &&
           !unresolved->storage_buffers[0].known_size);
    assert(!unresolved->HasResolvedBufferBindings() &&
           !unresolved->ValidateGpuMappings([](u64, std::size_t) {
               return true;
           }));
    memory.words[3]=0;
    shader_info.constant_buffer_mask=1U<<9;
    assert(!env.BuildResourcePlan(shader_info));
    shader_info.constant_buffer_mask=1;
    shader_info.constant_buffer_descriptors.clear();
    assert(!env.BuildResourcePlan(shader_info)); // mandatory bank is not declared
    shader_info.constant_buffer_descriptors.push_back({0,1});
    shader_info.constant_buffer_descriptors.push_back({0,1});
    assert(!env.BuildResourcePlan(shader_info)); // two descriptors alias bank 0
    shader_info.constant_buffer_descriptors.pop_back();
    shader_info.storage_buffers_descriptors.clear();
    shader_info.storage_buffers_descriptors.push_back({0,4,1,true});
    assert(!env.BuildResourcePlan(shader_info)); // 16 bytes exceed CBUF
    shader_info.storage_buffers_descriptors.clear();
    shader_info.storage_buffers_descriptors.push_back({0,0,1,true});
    memory.words[1]=0x20000U;
    assert(!env.BuildResourcePlan(shader_info)); // >49-bit target
    memory.words[1]=0x10000U;
    shader_info.uses_cbuf_indirect=true;
    assert(!env.BuildResourcePlan(shader_info)); // no invented indirect binding
    shader_info.uses_cbuf_indirect=false;
    memory.mapped=false;
    assert(!env.BuildResourcePlan(shader_info)); // no stale GMMU read
    // P2.2 native image preflight: authentic 32-byte TIC/TSC ABI, 49-bit
    // backing and entire 4 KiB GMMU span before shared cache admission.
    // No Vulkan image allocation is claimed by this host-only witness.
    {
        using namespace Tegra::Texture;
        using Shader::Ampere::NativeQmdContiguousGpuSpan;
        using Shader::Ampere::NativeQmdWithinTexelBudget;
        using Shader::Ampere::NativeQmdSamplerSupported;
        using Shader::Ampere::NativeQmdImageHandle;
        using Shader::Ampere::NativeQmdImageKind;
        using Shader::Ampere::NativeQmdResourcePlan;
        using Shader::Ampere::NativeQmdImageLayoutMatches;
        using Shader::Ampere::NativeQmdTextureTables;
        constexpr u64 texture_va = (u64{1} << 40) + 0x4000;
        constexpr u64 physical_va = (u64{1} << 41) + 0x8000;
        // A large 1D width times 14-bit depth plus 11-bit layers must
        // not wrap u64 and accidentally pass the small-image budget.
        assert(NativeQmdWithinTexelBudget(64, 64, 1, 1, 64ULL * 1024 * 1024));
        assert(!NativeQmdWithinTexelBudget(0, 64, 1, 1, 64ULL * 1024 * 1024));
        assert(!NativeQmdWithinTexelBudget(
            0x100000000ULL, 65536, 16384, 2048, 64ULL * 1024 * 1024));
        assert(!NativeQmdWithinTexelBudget(64, 64, 1, 1, 0));
        assert(!NativeQmdWithinTexelBudget(8192, 8192, 2, 1, 64ULL * 1024 * 1024));
        TICEntry tic{};
        tic.header_version.Assign(TICHeaderVersion::BlockLinear);
        tic.texture_type.Assign(TextureType::Texture2D);
        tic.address_high.Assign(texture_va >> 32);
        tic.address_low = static_cast<u32>(texture_va);
        tic.width_minus_one.Assign(63);
        tic.height_minus_1.Assign(63);
        tic.depth_minus_1.Assign(0);
        tic.max_mip_level.Assign(0);
        tic.res_min_mip_level.Assign(0);
        tic.res_max_mip_level.Assign(0);
        TSCEntry tsc{};
        tsc.mag_filter.Assign(TextureFilter::Nearest);
        tsc.min_filter.Assign(TextureFilter::Linear);
        tsc.mipmap_filter.Assign(TextureMipmapFilter::None);
        assert(NativeQmdSamplerSupported(tsc));
        const TSCEntry valid_sampler = tsc;
        const auto mapper = [&](u64 addr) -> std::optional<u64> {
            if (addr < texture_va || addr - texture_va >= 8192)
                return std::nullopt;
            return physical_va + addr - texture_va;
        };
        assert(NativeQmdContiguousGpuSpan(texture_va, 8192, mapper));
        assert(!NativeQmdContiguousGpuSpan(0, 8192, mapper));
        assert(!NativeQmdContiguousGpuSpan(texture_va, 0, mapper));
        assert(!NativeQmdContiguousGpuSpan((u64{1} << 49) - 4, 8, mapper));
        assert(!NativeQmdContiguousGpuSpan(texture_va, 8193, mapper));
        assert(!NativeQmdContiguousGpuSpan(texture_va, 256 * 1024 * 1024 + 1U, mapper));
        assert(!NativeQmdContiguousGpuSpan(texture_va, 8192,
            [&](u64 addr) -> std::optional<u64> {
                if (addr >= texture_va + 4096) return std::nullopt;
                return mapper(addr);
            }));
        assert(!NativeQmdContiguousGpuSpan(texture_va, 8192,
            [&](u64 addr) -> std::optional<u64> {
                if (addr >= texture_va + 4096) return *mapper(addr) + 4096;
                return mapper(addr);
            }));
        NativeQmdTextureTables guest_tables{
            .tic_base = 0x1000001000000ULL, .tsc_base = 0x1000002000000ULL,
            .tic_limit = 0, .tsc_limit = 0
        };
        NativeQmdResourcePlan textured{};
        textured.requires_tic_tsc = true;
        NativeQmdImageHandle sampled{};
        sampled.kind = NativeQmdImageKind::SampledTexture;
        sampled.primary_word = 0;
        textured.image_handles.push_back(sampled);
        // Match flattened SPIR-V layout before touching guest TIC/TSC:
        // texture buffers, image buffers, samples, writable storage images.
        Shader::Info layout{};
        Shader::TextureDescriptor sampled_description{};
        sampled_description.count = 1;
        layout.texture_descriptors.push_back(sampled_description);
        assert(NativeQmdImageLayoutMatches(layout, textured));
        layout.texture_descriptors[0].count = 2;
        assert(!NativeQmdImageLayoutMatches(layout, textured));
        layout.texture_descriptors[0].count = 1;
        textured.image_handles[0].kind = NativeQmdImageKind::StorageImage;
        assert(!NativeQmdImageLayoutMatches(layout, textured));
        textured.image_handles[0].kind = NativeQmdImageKind::SampledTexture;
        textured.image_handles[0].is_written = true;
        assert(!NativeQmdImageLayoutMatches(layout, textured));
        textured.image_handles[0].is_written = false;
        Shader::Info mixed_info{};
        Shader::TextureBufferDescriptor texture_buffer_description{};
        texture_buffer_description.count = 1;
        mixed_info.texture_buffer_descriptors.push_back(texture_buffer_description);
        Shader::ImageBufferDescriptor image_buffer_description{};
        image_buffer_description.is_written = true;
        image_buffer_description.count = 1;
        mixed_info.image_buffer_descriptors.push_back(image_buffer_description);
        mixed_info.texture_descriptors.push_back(sampled_description);
        Shader::ImageDescriptor storage_description{};
        storage_description.is_written = true;
        storage_description.count = 1;
        mixed_info.image_descriptors.push_back(storage_description);
        NativeQmdResourcePlan mixed_plan{};
        mixed_plan.requires_tic_tsc = true;
        mixed_plan.image_handles = {
            NativeQmdImageHandle{.kind = NativeQmdImageKind::TextureBuffer},
            NativeQmdImageHandle{.kind = NativeQmdImageKind::ImageBuffer,
                                 .is_written = true},
            NativeQmdImageHandle{.kind = NativeQmdImageKind::SampledTexture},
            NativeQmdImageHandle{.kind = NativeQmdImageKind::StorageImage,
                                 .is_written = true},
        };
        assert(NativeQmdImageLayoutMatches(mixed_info, mixed_plan));
        std::swap(mixed_plan.image_handles[0], mixed_plan.image_handles[2]);
        assert(!NativeQmdImageLayoutMatches(mixed_info, mixed_plan));
        std::swap(mixed_plan.image_handles[0], mixed_plan.image_handles[2]);
        mixed_plan.image_handles[1].is_written = false;
        assert(!NativeQmdImageLayoutMatches(mixed_info, mixed_plan));
        mixed_plan.image_handles[1].is_written = true;
        mixed_plan.image_handles.pop_back();
        assert(!NativeQmdImageLayoutMatches(mixed_info, mixed_plan));
        assert(NativeQmdImageLayoutMatches(layout, textured));
        const auto read_guest = [&](u64 addr, void* dst, std::size_t bytes) {
            if (!dst || bytes != 32) return false;
            if (addr == guest_tables.tic_base) {
                std::memcpy(dst, &tic, bytes); return true;
            }
            if (addr == guest_tables.tsc_base) {
                std::memcpy(dst, &tsc, bytes); return true;
            }
            return false;
        };
        unsigned admissions{};
        const auto admit = [&](const TICEntry& entry) {
            ++admissions;
            return entry.Address() == texture_va &&
                NativeQmdContiguousGpuSpan(entry.Address(), 8192, mapper);
        };
        const auto image = guest_tables.CaptureAdmissible(
            textured, read_guest, admit);
        assert(image && image->size() == 1 && admissions == 1);
        assert((*image)[0].has_sampler && (*image)[0].tic_index == 0);
        // Decoding admitted bytes must not invent Vulkan resources.
        // A malformed/writable/mismatched TSC must fail before the cache.
        const auto typed = guest_tables.DecodeAdmitted(textured, *image);
        assert(typed && typed->size() == 1 &&
               (*typed)[0].tic.Address() == texture_va &&
               (*typed)[0].sampler.has_value() &&
               (*typed)[0].kind == NativeQmdImageKind::SampledTexture &&
               !(*typed)[0].is_written);
        auto corrupted_record = *image;
        corrupted_record[0].is_written = true;
        assert(!guest_tables.DecodeAdmitted(textured, corrupted_record));
        corrupted_record = *image;
        corrupted_record[0].has_sampler = false;
        assert(!guest_tables.DecodeAdmitted(textured, corrupted_record));
        corrupted_record = *image;
        corrupted_record[0].tsc_words.fill(0);
        assert(!guest_tables.DecodeAdmitted(textured, corrupted_record));
        corrupted_record = *image;
        corrupted_record[0].raw_handle ^= 1;
        assert(!guest_tables.DecodeAdmitted(textured, corrupted_record));
        corrupted_record = *image;
        ++corrupted_record[0].tic_index;
        assert(!guest_tables.DecodeAdmitted(textured, corrupted_record));
        corrupted_record = *image;
        ++corrupted_record[0].tsc_index;
        assert(!guest_tables.DecodeAdmitted(textured, corrupted_record));
        auto other_plan = textured;
        other_plan.image_handles[0].primary_word = 1;
        assert(!guest_tables.DecodeAdmitted(other_plan, *image));
        other_plan = textured;
        other_plan.image_handles[0].primary_shift = 32;
        assert(!guest_tables.DecodeAdmitted(other_plan, *image));
        corrupted_record = *image;
        corrupted_record[0].tic_words.fill(0);
        assert(!guest_tables.DecodeAdmitted(textured, corrupted_record));
        assert(!guest_tables.DecodeAdmitted(textured, {}));
        assert(guest_tables.DecodeAdmitted(textured, *image));
        // The second TIC/TSC read is now a streaming, allocation-free
        // comparison under TextureCache's channel mutex. A duplicate
        // descriptor must read both records, but a mismatch in the first
        // must stop before reading the second.
        auto duplicate_plan = textured;
        duplicate_plan.image_handles.push_back(textured.image_handles[0]);
        const auto duplicated = guest_tables.Capture(duplicate_plan, read_guest);
        assert(duplicated && duplicated->size() == 2);
        unsigned rereads{};
        const auto counted_read = [&](u64 addr, void* dst, std::size_t bytes) {
            ++rereads;
            return read_guest(addr, dst, bytes);
        };
        assert(guest_tables.MatchesSnapshot(duplicate_plan, *duplicated, counted_read));
        assert(rereads == 4); // two TICs + two TSCs
        auto stale_first = *duplicated;
        stale_first[0].tic_words[0] ^= 1;
        rereads = 0;
        assert(!guest_tables.MatchesSnapshot(duplicate_plan, stale_first, counted_read));
        assert(rereads == 2); // early reject; no second descriptor lookup
        rereads = 0;
        assert(!guest_tables.MatchesSnapshot(duplicate_plan, *image, counted_read));
        assert(rereads == 0); // mismatched span never touches guest memory
        auto oversize_plan = duplicate_plan;
        oversize_plan.image_handles.resize(257, textured.image_handles[0]);
        rereads = 0;
        assert(!guest_tables.MatchesSnapshot(
            oversize_plan, std::vector<Shader::Ampere::NativeQmdImageTableRecord>(257), counted_read));
        assert(rereads == 0);
        // TIC/TSC can mutate in guest memory independently of the channel
        // epoch. Do not accept a mixed or stale descriptor-table snapshot.
        assert(guest_tables.MatchesSnapshot(textured, *image, read_guest));
        tic.width_minus_one.Assign(64);
        assert(!guest_tables.MatchesSnapshot(textured, *image, read_guest));
        tic.width_minus_one.Assign(63);
        tsc.raw[1] ^= 1;
        assert(!guest_tables.MatchesSnapshot(textured, *image, read_guest));
        tsc.raw[1] ^= 1;
        assert(guest_tables.MatchesSnapshot(textured, *image, read_guest));
        assert(!guest_tables.MatchesSnapshot(
            textured, *image, [](u64, void*, std::size_t) { return false; }));
        auto changed_during_admission = guest_tables.CaptureAdmissible(
            textured, read_guest, [&](const TICEntry&) {
                tic.width_minus_one.Assign(65);
                return true;
            });
        assert(!changed_during_admission);
        tic.width_minus_one.Assign(63);
        assert(guest_tables.MatchesSnapshot(textured, *image, read_guest));
        tic.header_version.Assign(static_cast<TICHeaderVersion>(7));
        assert(!guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tic.header_version.Assign(TICHeaderVersion::BlockLinear);
        tic.is_sparse.Assign(1);
        assert(!guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tic.is_sparse.Assign(0);
        tic.res_min_mip_level.Assign(2);
        assert(!guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tic.res_min_mip_level.Assign(0);
        tic.depth_minus_1.Assign(1); // plain 2D must be one layer
        assert(!guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tic.depth_minus_1.Assign(0);
        tsc.raw.fill(0);
        assert(!NativeQmdSamplerSupported(tsc));
        assert(!guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tsc = valid_sampler;
        tsc.mag_filter.Assign(static_cast<TextureFilter>(0));
        assert(!NativeQmdSamplerSupported(tsc));
        assert(!guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tsc = valid_sampler;
        tsc.min_filter.Assign(static_cast<TextureFilter>(3));
        assert(!guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tsc = valid_sampler;
        tsc.mipmap_filter.Assign(static_cast<TextureMipmapFilter>(0));
        assert(!guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tsc = valid_sampler;
        tsc.reduction_filter.Assign(static_cast<SamplerReduction>(3));
        assert(!guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tsc = valid_sampler;
        tsc.wrap_u.Assign(WrapMode::MirrorOnceBorder);
        assert(!NativeQmdSamplerSupported(tsc));
        assert(!guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tsc = valid_sampler;
        tsc.wrap_v.Assign(WrapMode::MirrorOnceBorder);
        assert(!NativeQmdSamplerSupported(tsc));
        tsc = valid_sampler;
        tsc.wrap_p.Assign(WrapMode::MirrorOnceBorder);
        assert(!NativeQmdSamplerSupported(tsc));
        tsc = valid_sampler;
        assert(NativeQmdSamplerSupported(tsc));
        tic.msaa_mode.Assign(static_cast<MsaaMode>(7));
        assert(!guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tic.msaa_mode.Assign(MsaaMode::Msaa4x2_VC8);
        assert(guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tic.msaa_mode.Assign(MsaaMode::Msaa4x2_VC24);
        assert(guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tic.msaa_mode.Assign(static_cast<MsaaMode>(12));
        assert(!guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tic.msaa_mode.Assign(MsaaMode::Msaa2x2_VC4);
        assert(guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tic.msaa_mode.Assign(MsaaMode::Msaa2x2_VC12);
        assert(guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tic.msaa_mode.Assign(MsaaMode::Msaa1x1);
        tic.width_minus_one.Assign(16383);
        tic.height_minus_1.Assign(8191);
        assert(!guest_tables.CaptureAdmissible(textured, read_guest, admit));
        tic.width_minus_one.Assign(63);
        tic.height_minus_1.Assign(63);
        assert(!guest_tables.CaptureAdmissible(
            textured, read_guest, [&](const TICEntry&) { return false; }));
        assert(guest_tables.CaptureAdmissible(
            textured, read_guest, admit)); // no stale rejection state
    }
    return 0;
}
