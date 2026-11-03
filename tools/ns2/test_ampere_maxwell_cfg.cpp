// SPDX-License-Identifier: GPL-3.0-or-later
// Execute actual Eden Maxwell CFG and the NS2 IR handoff ABI.
// TranslateProgram is an explicit link-time SPY here, NOT the maintained IR compiler.
// Synthetic NOP/MOV/EXIT only; no copyrighted game shader or GPU execution.
#include <array>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <vector>
#include "common/logging.h"
#include "shader_recompiler/frontend/ampere/maxwell_environment.h"
#include "shader_recompiler/frontend/maxwell/control_flow.h"
#include "shader_recompiler/frontend/ampere/ir_bridge.h"
#include "shader_recompiler/host_translate_info.h"
#include <stdexcept>

// Link only the CFG and decoder, not the full emulator's logging runtime.
// Never let a decoder assertion or log event count as a passing fixture.
void AssertFailSoftImpl() { std::abort(); }
namespace Common::Log {
void FmtLogMessageImpl(Class, Level, const char*, unsigned int,
                       const char*, fmt::string_view, const fmt::format_args&) {
    std::abort();
}
} // namespace Common::Log

using namespace Shader::Ampere;
static void Require(bool pass, const char* reason) {
    if (!pass) { std::fprintf(stderr, "NS2 Maxwell CFG: %s\n", reason); std::exit(1); }
}
struct NativeSource final : Shader::Environment {
    explicit NativeSource(Shader::Stage shader_stage = Shader::Stage::VertexB) {
        stage=shader_stage;
        start_address=0;
    }
    u64 ReadInstruction(u32) override {
        // The real CFG must NEVER decode the raw native Ampere instruction.
        std::abort();
    }
    u32 ReadCbufValue(u32,u32) override { return 0; }
    Shader::TextureType ReadTextureType(u32) override { return {}; }
    Shader::TexturePixelFormat ReadTexturePixelFormat(u32) override { return {}; }
    bool IsTexturePixelFormatInteger(u32) override { return false; }
    u32 ReadViewportTransformState() override { return 0; }
    u32 TextureBoundBuffer() const override { return 0; }
    u32 LocalMemorySize() const override { return 0; }
    u32 SharedMemorySize() const override { return 0; }
    std::array<u32,3> WorkgroupSize() const override { return {}; }
    bool HasHLEMacroState() const override { return false; }
    std::optional<Shader::ReplaceConstant> GetReplaceConstBuffer(u32,u32) override { return {}; }
    void Dump(u64,u64) override { std::abort(); }
};
static void Emit(std::vector<u8>& v,u32 a,u32 b=0,u32 c=0,u32 d=0) {
    for (u32 w : {a,b,c,d})
        for (u32 shift=0;shift<32;shift+=8)
            v.push_back(static_cast<u8>(w>>shift));
}

namespace {
// Deliberate stub, allowing actual TranslateReviewedGraphicsIR + CFG to be
// executed independently of the hundreds of maintained IR translation units.
Shader::Environment* expected_env{};
bool expected_dispatcher{};
u32 calls{};
}
namespace Shader::Maxwell {
Shader::IR::Program TranslateProgram(
    Shader::ObjectPool<Shader::IR::Inst>&,
    Shader::ObjectPool<Shader::IR::Block>&,
    Shader::Environment& actual,
    Shader::Maxwell::Flow::CFG& cfg,
    const Shader::HostTranslateInfo& info) {
    Require(&actual == expected_env &&
            cfg.ExitsToDispatcher() == expected_dispatcher &&
            !cfg.Functions().empty() &&
            cfg.Functions().front().entrypoint.Offset() == 0x50 &&
            info.min_ssbo_alignment == 64,
            "bridge passes actual Maxwell CFG, owned environment and host info");
    ++calls;
    Shader::IR::Program sentinel{};
    sentinel.stage = actual.ShaderStage();
    return sentinel;
}
} // namespace Shader::Maxwell

int main() {
    std::array<u8,0x50> header{};
    constexpr u32 pt=7U<<12, exit_true=7U<<23;
    std::vector<u8> native;
    Emit(native,pt|0x918);                        // NOP
    Emit(native,pt|0x202|(1U<<16),2,15U<<8);    // MOV R1,R2
    Emit(native,pt|0x918);                        // NOP, crosses scheduling slot
    Emit(native,pt|0x918);                        // NOP
    Emit(native,pt|0x94d,0,exit_true);            // unconditional EXIT
    auto translated=BuildMaxwellShaderImage(
        header,native,static_cast<u32>(Shader::Stage::VertexB));
    Require(translated.ValidForCompiler() &&
            translated.ReadMaxwellInstruction(0x50).has_value() &&
            !translated.ReadMaxwellInstruction(0x60).has_value(),
            "translated synthetic graphics program must be well formed");
    auto env=NativeMaxwellEnvironment::CreateOwned(
        std::make_unique<NativeSource>(),std::move(translated));
    Require(env && env->StartAddress()==0,
            "owned source metadata and start address must be coherent");
    for (bool dispatcher : {false,true}) {
        Shader::ObjectPool<Shader::Maxwell::Flow::Block> blocks{64};
        Shader::Maxwell::Flow::CFG cfg{
            *env,blocks,static_cast<u32>(env->StartAddress()+sizeof(Shader::ProgramHeader)),dispatcher};
        Require(cfg.ExitsToDispatcher()==dispatcher && !cfg.Functions().empty(),
                "real Maxwell CFG decoded reviewed native translation");
        const auto& first=cfg.Functions().front();
        Require(first.entrypoint.Offset()==0x50 && !first.blocks.empty(),
                "real CFG begins after the SPH, not at the native header");
        bool saw_exit=false;
        for (const auto& block : first.blocks) {
            if (block.end_class==Shader::Maxwell::Flow::EndClass::Exit ||
                (dispatcher && block.end_class==Shader::Maxwell::Flow::EndClass::Branch))
                saw_exit=true;
        }
        Require(saw_exit,"translated EXIT yields a terminating CFG edge");
    }
    Shader::HostTranslateInfo host{};
    host.min_ssbo_alignment = 64;
    expected_env = env.get();
    Shader::ObjectPool<Shader::IR::Inst> inst_pool{4};
    Shader::ObjectPool<Shader::IR::Block> block_pool{4};
    Shader::ObjectPool<Shader::Maxwell::Flow::Block> flow_pool{64};
    for (bool dispatcher : {false, true}) {
        expected_dispatcher = dispatcher;
        auto sentinel = TranslateReviewedGraphicsIR(
            inst_pool, block_pool, flow_pool, *env, host, dispatcher);
        Require(sentinel.stage == Shader::Stage::VertexB,
                "IR bridge calls the supplied compiler interface");
    }
    Require(calls == 2, "VertexB IR bridge invoked once per dispatcher mode");
    // Standalone Fragment uses the very same real Maxwell CFG and IR handoff,
    // without pretending it is VertexB or inventing pipeline attachment data.
    auto fragment_image=BuildMaxwellShaderImage(
        header,native,static_cast<u32>(Shader::Stage::Fragment));
    Require(fragment_image.ValidForCompiler(),
            "Fragment native translation must contain a complete shader");
    auto fragment_env=NativeMaxwellEnvironment::CreateOwned(
        std::make_unique<NativeSource>(Shader::Stage::Fragment),
        std::move(fragment_image));
    Require(fragment_env && fragment_env->ShaderStage()==Shader::Stage::Fragment,
            "Fragment metadata must survive native Maxwell environment");
    expected_env=fragment_env.get();
    for (bool dispatcher:{false,true}) {
        expected_dispatcher=dispatcher;
        Shader::ObjectPool<Shader::IR::Inst> fragment_inst{4};
        Shader::ObjectPool<Shader::IR::Block> fragment_blocks{4};
        Shader::ObjectPool<Shader::Maxwell::Flow::Block> fragment_flow{64};
        auto program=TranslateReviewedGraphicsIR(
            fragment_inst,fragment_blocks,fragment_flow,*fragment_env,host,dispatcher);
        Require(program.stage==Shader::Stage::Fragment,
                "Fragment must retain its stage into the actual Maxwell CFG/IR handoff");
    }
    Require(calls==4,"VertexB and Fragment must each reach CFG/IR exactly twice");
    // A pretranslated native image must never smuggle Compute/QMD or
    // an unknown stage into the graphics Maxwell compiler.
    auto compute_image=BuildMaxwellShaderImage(
        header,native,static_cast<u32>(Shader::Stage::Compute));
    Require(compute_image.ValidForCompiler(), "compute image is structurally valid");
    Require(!NativeMaxwellEnvironment::CreateOwned(
                std::make_unique<NativeSource>(Shader::Stage::Compute),
                std::move(compute_image)),
            "Compute stage rejected before GPU IR bridge");
    auto unknown_image=BuildMaxwellShaderImage(header,native,0xffffffffU);
    Require(!NativeMaxwellEnvironment::CreateOwned(
                std::make_unique<NativeSource>(static_cast<Shader::Stage>(0xffffffffU)),
                std::move(unknown_image)),
            "Unknown stage rejected before GPU IR bridge");
    // P2.4: an authenticated native BRX dispatch expands into compares,
    // predicate-preserving stubs and native-PC -> Maxwell-PC relocations.
    // Run it through the REAL Maxwell CFG, not only the source/image oracle.
    std::vector<u8> indirect_native;
    Emit(indirect_native,pt|0x817U|(4U<<16),15U,0x03800000U); // bounded index
    Emit(indirect_native,pt|0x819U|(5U<<16)|(4U<<24),2U,0x000006ffU);
    Emit(indirect_native,pt|0xb82U|(6U<<16)|(5U<<24),
         (7U<<22)|(0xffc0U<<6),0x00000800U);       // LDC CBUF[7]
    Emit(indirect_native,pt|0x949U|(6U<<24),0xffffffc0U,0x0383ffffU); // BRX
    Emit(indirect_native,pt|0x94dU,0,exit_true);    // first EXIT
    for (u32 i=0;i<4;++i) Emit(indirect_native,pt|0x918U);
    Emit(indirect_native,pt|0x94dU,0,exit_true);    // post-EXIT target
    NativeIndirectBranchPlan indirect_plan{};
    indirect_plan.branch_instruction_index=3;
    indirect_plan.raw_pc_base=0x80U;
    indirect_plan.targets={{0x80U,0U},{0x100U,8U}};
    auto indirect_image=BuildMaxwellShaderImage(
        header,indirect_native,static_cast<u32>(Shader::Stage::VertexB),
        std::span<const NativeIndirectBranchPlan>{&indirect_plan,1});
    Require(indirect_image.ValidForCompiler() &&
            indirect_image.TranslateNativeAddress(0).has_value() &&
            indirect_image.TranslateNativeAddress(8*16).has_value(),
            "real checked BRX lowering must produce exact runnable address map");
    auto indirect_env=NativeMaxwellEnvironment::CreateOwned(
        std::make_unique<NativeSource>(),std::move(indirect_image));
    Require(bool(indirect_env),"real BRX image admitted to Maxwell environment");
    for (bool dispatcher:{false,true}) {
        Shader::ObjectPool<Shader::Maxwell::Flow::Block> branch_blocks{128};
        Shader::Maxwell::Flow::CFG branch_cfg{
            *indirect_env,branch_blocks,
            static_cast<u32>(indirect_env->StartAddress()+sizeof(Shader::ProgramHeader)),
            dispatcher};
        Require(!branch_cfg.Functions().empty() &&
                !branch_cfg.Functions().front().blocks.empty(),
                "real Maxwell CFG accepts checked BRX compare/stub dispatch");
    }
    std::puts("NS2 actual Maxwell CFG and IR handoff ABI: PASS "
              "(BRX relocations checked; TranslateProgram spy, no Vulkan execution)");
}
