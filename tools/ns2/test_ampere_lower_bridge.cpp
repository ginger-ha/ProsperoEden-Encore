// SPDX-License-Identifier: GPL-3.0-or-later
// Compile against the REAL upstream Ampere->Maxwell lowerer. This does not
// execute shaders, games, Vulkan commands, or PS5 native code.
#include <array>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "shader_recompiler/frontend/ampere/lower_bridge.h"
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
#include "shader_recompiler/frontend/ampere/maxwell_image.h"

using namespace Shader::Ampere;
static void check(bool value, const char* why) {
    if (!value) {
        std::fprintf(stderr, "NS2 Ampere lowering FAIL: %s\n", why);
        std::exit(1);
    }
}
static void Emit(std::vector<u8>& dst, u32 word0, u32 word1 = 0,
                 u32 word2 = 0, u32 word3 = 0) {
    for (const u32 word : {word0, word1, word2, word3}) {
        for (unsigned b=0; b<4; ++b)
            dst.push_back(static_cast<u8>(word >> (b * 8)));
    }
}
int main() {
    constexpr u32 PredTrue = 7U << 12;
    constexpr u32 ExitCondTrue = 7U << 23;
    std::vector<u8> code;
    Emit(code, PredTrue | 0x918);                    // NOP
    Emit(code, PredTrue | 0x94d, 0, ExitCondTrue);   // EXIT
    const auto ok = LowerReviewedToMaxwell(code);
    check(ok.Ready() && ok.preflight.instructions == 2 &&
          ok.preflight.recognized == 2 && ok.preflight.control_flow == 1,
          "recognized NOP+EXIT really lowered through native Maxwell frontend");
    check(ok.consumed_native_bytes == code.size() &&
          ok.source_instruction_offsets.size() == 2 &&
          ok.maxwell_instructions.size() >= 2 &&
          ok.source_instruction_offsets[0] <= ok.source_instruction_offsets[1],
          "source offsets and complete input consumption survived lowering");
    check((ok.maxwell_instructions.back() & 0xff0000000000000fULL) ==
          (0xe30000000000000fULL & 0xff0000000000000fULL),
          "an actual Maxwell EXIT opcode was emitted");

    code.clear();
    Emit(code, PredTrue | 0x202 | (1U << 16), 2, 15U << 8); // MOV R1, R2
    Emit(code, PredTrue | 0x94d, 0, ExitCondTrue);
    const auto mov = LowerReviewedToMaxwell(code);
    check(mov.Ready() && mov.source_instruction_offsets.size() == 2 &&
          mov.maxwell_instructions.front() != 0 &&
          mov.maxwell_instructions.front() != ok.maxwell_instructions.front(),
          "real native MOV lowered into a non-NOP Maxwell move");

    code.resize(1);
    check(LowerReviewedToMaxwell(code).status == LowerBridgeStatus::InvalidInput,
          "partial native instruction rejected before parsing");
    code.clear();
    check(LowerReviewedToMaxwell(code).status == LowerBridgeStatus::InvalidInput,
          "empty shader rejected before lowering");
    code.resize((4096U + 1) * 16U);
    check(LowerReviewedToMaxwell(code).status == LowerBridgeStatus::InvalidInput,
          "hard 4096-instruction analysis bound enforced");

    code.clear();
    Emit(code, PredTrue | 0x202 | (1U << 16) | (1U << 24), 2, 15U << 8);
    Emit(code, PredTrue | 0x94d, 0, ExitCondTrue);
    const auto unknown_bits = LowerReviewedToMaxwell(code);
    check(unknown_bits.status == LowerBridgeStatus::UnreviewedFields &&
          unknown_bits.failed_native_byte_offset == 0 &&
          unknown_bits.maxwell_instructions.empty(),
          "unknown ISA fields must fail closed without fabricated output");

    u32 unknown_opcode = 0;
    while (unknown_opcode != 4096 && FindOpcodeRow(unknown_opcode))
        ++unknown_opcode;
    check(unknown_opcode != 4096, "ISA has deliberately unsupported opcodes");
    code.clear();
    Emit(code, PredTrue | unknown_opcode);
    Emit(code, PredTrue | 0x94d, 0, ExitCondTrue);
    const auto missing = LowerReviewedToMaxwell(code);
    check(missing.status == LowerBridgeStatus::UnrecognizedOpcode &&
          missing.maxwell_instructions.empty(),
          "unrecognized Ampere instruction never lowers via unknown fallback");

    code.clear();
    Emit(code, PredTrue | 0x918);
    const auto no_exit = LowerReviewedToMaxwell(code);
    check(no_exit.status == LowerBridgeStatus::UnsupportedSemantics &&
          no_exit.maxwell_instructions.empty() &&
          !no_exit.reason.empty(),
          "recognizable NOP is not a full executable without an EXIT");

    // A recognized native BRX table must lower to real, relocated Maxwell
    // conditional branches, not a Maxwell BRX with unconverted guest PCs.
    // The direct lowerer test does not authenticate CBUF residency; that is
    // the responsibility of the owning shader-capture front end.
    std::vector<Instruction> computed_program{
        Instruction{{PredTrue|0x949U|(6U<<24),0xfffffff0U,0x0383ffffU,0}},
        Instruction{{PredTrue|0x94dU,0,ExitCondTrue,0}},
        Instruction{{PredTrue|0x918U,0,0,0}},
        Instruction{{PredTrue|0x94dU,0,ExitCondTrue,0}},
    };
    NativeIndirectBranchPlan plan{
        .branch_instruction_index=0,
        .raw_pc_base=0x80U,
        .targets={{0x90U,1U},{0xb0U,3U}},
    };
    const auto expanded=LowerToMaxwell(
        computed_program,{},false,std::span<const NativeIndirectBranchPlan>{&plan,1});
    check(expanded && expanded.source_size==4*16 &&
          expanded.source_instruction_offsets.size()==4 &&
          expanded.instructions.size()>10,
          "native BRX emits branch-to-restoration stubs and consumes complete source");
    bool found_integer_equal=false, found_predicated_branch=false;
    bool found_predicate_save=false, found_predicate_restore=false;
    for (const u64 word : expanded.instructions) {
        found_integer_equal |= (word & 0xfff0000000000000ULL)==
                               0x5b60000000000000ULL &&
                               ((word>>49)&7U)==2U;
        found_predicated_branch |= (word & 0xfff000000007000fULL)==
                                   (0xe24000000006000fULL & 0xfff000000007000fULL);
        found_predicate_save |= (word & 0xfff8000000000000ULL)==0x38e8000000000000ULL;
        found_predicate_restore |= (word & 0xfff8000000000000ULL)==0x38f0000000000000ULL;
    }
    check(found_integer_equal && found_predicated_branch &&
          found_predicate_save && found_predicate_restore,
          "BRX dispatch compares actual native CBUF words and preserves P6");
    const std::array<u8,0x50> synthetic_header{};
    std::vector<u8> computed_bytes;
    for (const auto& instruction : computed_program)
        for (u32 word : instruction.words)
            for (u32 i=0;i<4;++i)
                computed_bytes.push_back(static_cast<u8>(word>>(i*8)));
    const auto resolved_image=BuildMaxwellShaderImage(
        synthetic_header,computed_bytes,4,
        std::span<const NativeIndirectBranchPlan>{&plan,1});
    const auto unresolved_image=BuildMaxwellShaderImage(
        synthetic_header,computed_bytes,4);
    check(resolved_image.ValidForCompiler() &&
          resolved_image.consumed_native_bytes==computed_bytes.size() &&
          resolved_image.TranslateNativeAddress(0).has_value() &&
          resolved_image.TranslateNativeAddress(48).has_value() &&
          resolved_image.diagnostic_cache_key!=unresolved_image.diagnostic_cache_key,
          "resolved BRX produces bounded CFG image with distinct branch-table key");
    plan.targets[1].native_instruction_index=123;
    check(!LowerToMaxwell(
              computed_program,{},false,
              std::span<const NativeIndirectBranchPlan>{&plan,1}),
          "BRX targets outside captured shader must be rejected");
    plan.targets[1].native_instruction_index=3;
    plan.targets[1].native_value=plan.targets[0].native_value;
    check(!LowerToMaxwell(
              computed_program,{},false,
              std::span<const NativeIndirectBranchPlan>{&plan,1}),
          "one native BRX raw value cannot map to contradictory blocks");
    plan.targets[1].native_value=0xb0U;
    plan.raw_pc_base=0;
    check(!LowerToMaxwell(
              computed_program,{},false,
              std::span<const NativeIndirectBranchPlan>{&plan,1}),
          "header-relative CBUF PC must not be accepted as code-relative");
    plan.raw_pc_base=0x80U;
    plan.targets[1].native_value=0xa0U;
    check(!LowerToMaxwell(
              computed_program,{},false,
              std::span<const NativeIndirectBranchPlan>{&plan,1}),
          "BRX expected native PC must agree with index plus header origin");
    plan.targets[1].native_value=0xb0U;
    plan.branch_instruction_index=2;
    check(!LowerToMaxwell(
              computed_program,{},false,
              std::span<const NativeIndirectBranchPlan>{&plan,1}),
          "native BRX dispatch plan cannot be attached to a non-branch opcode");

    // An unknown NOP field is rejected before the lowerer sees it.
    code.clear();
    Emit(code, PredTrue | 0x918, 1);
    check(LowerReviewedToMaxwell(code).status == LowerBridgeStatus::UnreviewedFields,
          "extra unreviewed words cannot slip through translation");

    std::puts("NS2 Ampere->Maxwell lowering: PASS (host translation only)");
}
