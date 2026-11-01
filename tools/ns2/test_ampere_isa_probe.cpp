// SPDX-License-Identifier: GPL-3.0-or-later
// Host-only Ampere ISA reconnaissance, not PS5 shader translation.
#include <array>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "shader_recompiler/frontend/ampere/ampere_isa_table.h"
#include "shader_recompiler/frontend/ampere/probe.h"

using namespace Shader::Ampere;
static void check(bool value, const char* desc) {
    if (!value) {
        std::fprintf(stderr, "NS2 Ampere probe FAIL: %s\n", desc);
        std::exit(1);
    }
}
static void Append(std::vector<u8>& data, u32 opcode, u32 override_word0 = 0) {
    const u32 words[]{opcode | override_word0, 0, 0, 0};
    for (u32 word : words) {
        for (int i=0; i<4; ++i) data.push_back(static_cast<u8>(word >> (i*8)));
    }
}
int main() {
    static_assert(sizeof(Instruction) == 16);
    check(ISA_ROW_COUNT == 629, "pinned upstream SM70 ISA row count");
    check(FindOpcodeRow(0x202) && FindOpcodeRow(0x947) &&
          FindOpcodeRow(0x94d) && FindOpcodeRow(0x918) &&
          FindOpcodeRow(0x34e) && FindOpcodeRow(0x357) &&
          FindOpcodeRow(0x957),
          "MOV, BRA, EXIT and NOP have real opcode definitions");
    check(Classify(0x947).kind == OpKind::Bra &&
          Classify(0x94d).kind == OpKind::Exit &&
          Classify(0x918).kind == OpKind::Nop,
          "Ampere branch, exit and no-op classification");
    check(ProbeProgram({}).status == ProbeStatus::Empty,
          "zero-length shader data is not a recognized program");
    const std::array<u8, 15> invalid{};
    check(ProbeProgram(invalid).status == ProbeStatus::InvalidSize,
          "partial 128-bit GPU instruction rejected");
    std::vector<u8> valid;
    Append(valid, 0x202);
    Append(valid, 0x947);
    Append(valid, 0x94d);
    auto result = ProbeProgram(valid);
    check(result.status == ProbeStatus::Recognized && result.instructions == 3 &&
          result.recognized == 3 && result.control_flow == 2,
          "bounded sample recognized without claiming shader execution");
    std::vector<u8> geometry_prologue;
    Append(geometry_prologue, 0x34e, 7u << 12);
    Append(geometry_prologue, 0x357, 7u << 12);
    Append(geometry_prologue, 0x957, 7u << 12);
    check(ProbeProgram(geometry_prologue).status == ProbeStatus::Recognized,
          "verified geometry ATEXIT opcodes reach the lowering preflight");
    geometry_prologue[3] = 1; // Disallowed LEPC operand encoding.
    check(ProbeProgram(geometry_prologue).status == ProbeStatus::UnreviewedFields,
          "non-reviewed LEPC operand mode remains fail closed");
    auto misaligned=valid;
    misaligned.erase(misaligned.begin());
    check(ProbeProgram(misaligned).status == ProbeStatus::InvalidSize,
          "unaligned stream fails before instruction access");
    u32 unknown_opcode{};
    while (unknown_opcode < 4096 && FindOpcodeRow(unknown_opcode)) ++unknown_opcode;
    check(unknown_opcode < 4096, "table correctly leaves unrecognized opcodes");
    std::vector<u8> unknown;
    Append(unknown, unknown_opcode);
    auto unknown_result=ProbeProgram(unknown);
    check(unknown_result.status == ProbeStatus::UnknownOpcode &&
          unknown_result.first_problem_index == 0 &&
          unknown_result.first_problem_opcode == unknown_opcode,
          "unrecognized instruction must never be reported as supported");
    const auto* mov = FindOpcodeRow(0x202);
    check(mov && (mov->known[0] & (1U<<24)) == 0,
          "pinned ISA mask leaves documented MOV unknown upper bit");
    std::vector<u8> unreviewed;
    Append(unreviewed, 0x202, 1U<<24);
    const auto field = ProbeProgram(unreviewed);
    check(field.status == ProbeStatus::UnreviewedFields &&
          field.first_unknown_bit == 24 && field.unreviewed_fields == 1,
          "unreviewed ISA bit is reported, not silently accepted");
    std::vector<u8> too_big((65536U + 1) * 16U);
    check(ProbeProgram(too_big).status == ProbeStatus::TooManyInstructions,
          "hard cap bounds arbitrary executable blobs before parsing");
    std::puts("NS2 Ampere 128-bit ISA host probe: PASS (decode only)");
}
