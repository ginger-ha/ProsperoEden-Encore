// SPDX-License-Identifier: GPL-3.0-or-later
// Host validation of the *real* Shader::Environment virtual API used by
// Eden's Maxwell CFG and shader IR compiler (without a PS5 GPU).
#include <array>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <type_traits>
#include <memory>
#include <vector>
#include "shader_recompiler/frontend/ampere/maxwell_environment.h"

using namespace Shader::Ampere;
static void Check(bool condition, const char* why) {
    if (!condition) { std::fprintf(stderr,"NS2 shader environment FAIL: %s\n",why); std::exit(1); }
}
struct FakeMaxwellEnvironment final : Shader::Environment {
    u32 cbuf_reads{};
    u32 texture_reads{};
    u32 dumped{};
    int* destroyed{};
    ~FakeMaxwellEnvironment() override {
        if (destroyed) ++*destroyed;
    }
    explicit FakeMaxwellEnvironment(
        Shader::Stage selected=Shader::Stage::VertexB) {
        stage=selected;
        start_address=0x50;
        gp_passthrough_mask[0]=0xa5a5;
        is_proprietary_driver=true;
    }
    u64 ReadInstruction(u32) override { std::abort(); }
    u32 ReadCbufValue(u32 index,u32 offset) override {
        ++cbuf_reads; return index*256+offset;
    }
    Shader::TextureType ReadTextureType(u32) override {
        ++texture_reads; return Shader::TextureType{};
    }
    Shader::TexturePixelFormat ReadTexturePixelFormat(u32) override {
        return Shader::TexturePixelFormat{};
    }
    bool IsTexturePixelFormatInteger(u32) override {return true;}
    u32 ReadViewportTransformState() override {return 7;}
    u32 TextureBoundBuffer() const override {return 9;}
    u32 LocalMemorySize() const override {return 1024;}
    u32 SharedMemorySize() const override {return 2048;}
    std::array<u32,3> WorkgroupSize() const override {return {2,4,8};}
    bool HasHLEMacroState() const override {return true;}
    std::optional<Shader::ReplaceConstant> GetReplaceConstBuffer(u32,u32) override {
        return {};
    }
    void Dump(u64,u64) override {++dumped;}
};
static void Emit(std::vector<u8>& code,u32 w0,u32 w1=0,u32 w2=0,u32 w3=0) {
    for(u32 word:{w0,w1,w2,w3})
        for(u32 k=0;k!=4;++k) code.push_back(static_cast<u8>(word>>(k*8)));
}
int main() {
    static_assert(std::is_base_of_v<Shader::Environment,NativeMaxwellEnvironment>);
    std::array<u8,0x50> hdr{};
    std::vector<u8> native;
    constexpr u32 true_pred=7u<<12, exit_true=7u<<23;
    Emit(native,true_pred|0x918);
    Emit(native,true_pred|0x94d,0,exit_true);
    FakeMaxwellEnvironment fake;
    auto env=NativeMaxwellEnvironment::Create(
        fake, BuildMaxwellShaderImage(hdr,native,static_cast<u32>(Shader::Stage::VertexB)));
    Check(env && env->StartAddress()==0 &&
          env->StartAddress()+sizeof(Shader::ProgramHeader)==0x50 &&
          env->ShaderStage()==fake.ShaderStage() &&
          env->GpPassthroughMask()==fake.GpPassthroughMask() &&
          env->IsProprietaryDriver(),
          "real Maxwell compiler CFG start and environment metadata match graphics pipeline");
    Check(env->ReadInstruction(0x50)==env->Image().code[0x50/8] &&
          env->ReadInstruction(0x58)==env->Image().code[0x58/8],
          "native instruction stream fed to Maxwell ReadInstruction virtual");
    for (u32 bad:{0u,0x48u,0x60u,0xfffffffcU,env->Image().instruction_end_address}) {
        bool rejected=false;
        try { (void)env->ReadInstruction(bad); }
        catch (const std::out_of_range&) { rejected=true; }
        Check(rejected,"scheduler, header and metadata cannot reach Maxwell decoder");
    }
    auto compute_image=BuildMaxwellShaderImage(
        hdr,native,static_cast<u32>(Shader::Stage::Compute));
    auto compute_env=NativeMaxwellEnvironment::CreateComputeOwned(
        std::make_unique<FakeMaxwellEnvironment>(Shader::Stage::Compute),
        std::move(compute_image));
    Check(compute_env && compute_env->StartAddress()==0x50 &&
          compute_env->ShaderStage()==Shader::Stage::Compute &&
          compute_env->ReadInstruction(0x50)==env->ReadInstruction(0x50) &&
          compute_env->WorkgroupSize()==std::array<u32,3>{2,4,8},
          "QMD Compute environment starts at synthetic Maxwell code, not SPH");
    Check(!NativeMaxwellEnvironment::CreateComputeOwned(
          std::make_unique<FakeMaxwellEnvironment>(),
          BuildMaxwellShaderImage(hdr,native,static_cast<u32>(Shader::Stage::Compute))),
          "graphics source cannot impersonate authenticated Compute QMD");
    Check(env->ReadCbufValue(2,7)==519 &&
          fake.cbuf_reads==1 &&
          env->IsTexturePixelFormatInteger(5) &&
          env->ReadViewportTransformState()==7 &&
          env->TextureBoundBuffer()==9 &&
          env->LocalMemorySize()==1024 &&
          env->SharedMemorySize()==2048 &&
          env->WorkgroupSize()[2]==8 &&
          env->HasHLEMacroState() &&
          !env->GetReplaceConstBuffer(0,0),
          "actual compiler environment virtual methods delegate metadata and CBUF");
    (void)env->ReadTextureType(3);
    (void)env->ReadTexturePixelFormat(3);
    Check(fake.texture_reads==1, "texture metadata delegated");
    env->Dump(1,2);
    Check(fake.dumped==0,"NS2 image never dumps using a Switch 1 guest shader identity");
    Check(!NativeMaxwellEnvironment::Create(
              fake, BuildMaxwellShaderImage(hdr,native,
                  static_cast<u32>(Shader::Stage::Fragment))),
          "stage-mismatched image cannot borrow shader compilation context");
    auto forged=BuildMaxwellShaderImage(
        hdr,native,static_cast<u32>(Shader::Stage::VertexB));
    forged.cached_highest_address+=8;
    Check(!NativeMaxwellEnvironment::Create(fake,std::move(forged)),
          "corrupted image extent never reaches Maxwell CFG");
    Check(!NativeMaxwellEnvironment::Create(fake,MaxwellShaderImage{}),
          "invalid/untranslated image cannot enter existing Maxwell compiler");
    std::array<u8,0x50> unrelated_header{};
    unrelated_header[0] = 0x38;
    Check(!NativeMaxwellEnvironment::Create(
              fake, BuildMaxwellShaderImage(unrelated_header,native,static_cast<u32>(Shader::Stage::VertexB))),
          "captured shader header must match the compiler's original SPH");
    int mismatch_destroyed = 0;
    auto mismatch_source = std::make_unique<FakeMaxwellEnvironment>();
    mismatch_source->destroyed = &mismatch_destroyed;
    Check(!NativeMaxwellEnvironment::CreateOwned(
              std::move(mismatch_source),
              BuildMaxwellShaderImage(unrelated_header,native,static_cast<u32>(Shader::Stage::VertexB))) &&
          mismatch_destroyed == 1,
          "mismatched owned GPU context is rejected and released before return");
    // Real shader caches defer IR compilation: a borrowed stack environment
    // would dangle after the surrounding renderer method returns. The new
    // ownership path must keep the source alive until the wrapper is freed.
    int destroyed = 0;
    auto source = std::make_unique<FakeMaxwellEnvironment>();
    source->destroyed = &destroyed;
    auto* live_source = source.get();
    {
        auto owned = NativeMaxwellEnvironment::CreateOwned(
            std::move(source),BuildMaxwellShaderImage(hdr,native,static_cast<u32>(Shader::Stage::VertexB)));
        Check(!source && owned && destroyed==0,
              "ownership transferred to native environment wrapper");
        Check(owned->ReadCbufValue(3,2)==770 &&
              live_source->cbuf_reads==1 &&
              owned->ShaderStage()==Shader::Stage::VertexB &&
              owned->StartAddress()+sizeof(Shader::ProgramHeader)==0x50,
              "owned original is alive for deferred compiler CBUF queries");
    }
    Check(destroyed==1, "original graphics environment destroyed exactly once");
    int invalid_destroyed = 0;
    auto invalid_source = std::make_unique<FakeMaxwellEnvironment>();
    invalid_source->destroyed = &invalid_destroyed;
    // C++ permits a by-value function parameter to be destroyed at the
    // end of its enclosing full expression (rather than before the logical
    // && rhs). Keep the lifetime assertion in a distinct full expression.
    auto rejected = NativeMaxwellEnvironment::CreateOwned(
        std::move(invalid_source), MaxwellShaderImage{});
    Check(!rejected, "invalid image cannot publish a Maxwell environment");
    Check(invalid_destroyed == 1,
          "failed image construction releases its guest graphics context");
    Check(!NativeMaxwellEnvironment::CreateOwned(
              {},BuildMaxwellShaderImage(hdr,native,static_cast<u32>(Shader::Stage::VertexB))),
          "null source cannot publish an executable shader environment");
    std::puts("NS2 Maxwell Shader::Environment bridge: PASS");
}
