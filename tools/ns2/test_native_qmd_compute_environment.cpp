// SPDX-License-Identifier: GPL-3.0-or-later
// Host-only conformance for the real QMD3 -> Shader::Environment ABI.
// No fake Vulkan submission or Switch 1 Kepler launch metadata.
#include <array>
#include <cassert>
#include <cstdint>
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
    std::array<u32,4> words{0xabcdef01,0x11223344,0x55667788,0x99aabbcc};
    unsigned reads{};
    bool mapped{true};
};
static bool Read(void* context,u64 address,void* destination,std::size_t bytes) {
    auto& memory=*static_cast<MockMappedGpu*>(context);
    ++memory.reads;
    if (!memory.mapped || !destination || bytes!=sizeof(u32) ||
        address < memory.address || address-memory.address > 12 ||
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
    const auto decoded=Tegra::DecodeNativeComputeLaunch(qmd);
    assert(decoded && decoded->constant_buffers[0].enabled);
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
    return 0;
}
