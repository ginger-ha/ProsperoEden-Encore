// SPDX-License-Identifier: GPL-3.0-or-later
// Host-only conformance for the real QMD3 -> Shader::Environment ABI.
// No fake Vulkan submission or Switch 1 Kepler launch metadata.
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
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
    return 0;
}
