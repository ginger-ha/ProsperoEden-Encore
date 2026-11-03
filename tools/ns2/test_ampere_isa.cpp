// SPDX-License-Identifier: GPL-3.0-or-later
// Synthetic SM70+/Ampere instruction and native-to-Maxwell address-map tests.
// This does not claim SM86 shader execution or RADV compatibility.
#include <array>
#include <cassert>
#include <cstdint>
#include <string_view>
#include <vector>
#include "shader_recompiler/frontend/ampere/instruction.h"
#include "shader_recompiler/frontend/ampere/classify.h"
#include "shader_recompiler/frontend/ampere/ampere_isa_table.h"
#include "shader_recompiler/frontend/ampere/probe.h"
#include "shader_recompiler/frontend/ampere/program_address_map.h"
#include "shader_recompiler/frontend/ampere/native_graphics_stage_policy.h"

using namespace Shader::Ampere;
static_assert(sizeof(Instruction)==16);
static_assert(Classify(0x947).kind==OpKind::Bra);
static_assert(Classify(0x94d).kind==OpKind::Exit);
static_assert(Classify(0x950).kind==OpKind::Ret);
static_assert(Classify(0x918).kind==OpKind::Nop);
static_assert(Classify(0x210).pure);




int main() {
    assert(RelativeOffset48(Instruction{{0,0,0,0}})==0);
    assert(RelativeOffset30(Instruction{{0,0,0,0}})==0);
    assert(RelativeOffset48(Instruction{{0,0,0x20000,0}})<0);
    assert(ISA_ROW_COUNT==629);
    const auto* add=FindOpcodeRow(0x210);
    assert(add && std::string_view(add->name)=="IAdd3/IAdd3X");
    assert(FindOpcodeRow(0x1210)==add); // Explicit 12-bit opcode mask
    assert(FindOpcodeRow(0xfff)==nullptr);
    Instruction zero{{0,0,0,0}};
    assert(FirstUnreviewedBit(zero,*add)==-1);
    Instruction unknown{{0,0,0,1}};
    assert(FirstUnreviewedBit(unknown,*add)==96);
    assert(zero.Bits(0,12)==0);
    Instruction cross{{0xffffffff,0xffffffff,0,0}};
    assert(cross.Bits(29,8)==0xff);
    assert(cross.Bits(63,2)==1);

    std::vector<std::uint64_t> code(100,0);
    assert(!HasNativeAddressMap(code));
    assert(!NativeProgramAddress(code,0));
    std::array<std::uint32_t,3> offsets{0,1,2};
    AppendNativeAddressMap(code,offsets);
    assert(HasNativeAddressMap(code));
    assert(NativeProgramAddress(code,0)==std::optional<std::uint32_t>{0x50});
    assert(NativeProgramAddress(code,16)==std::optional<std::uint32_t>{0x58});
    assert(NativeProgramAddress(code,32)==std::optional<std::uint32_t>{0x68});
    assert(!NativeProgramAddress(code,1)); // Ampere instructions align to 16 bytes
    assert(!NativeProgramAddress(code,48)); // count=3
    // SYNC -> barrier must not be reached by an illegal computed branch.
    code[0x50/8]=0xf0f800000007000fULL;
    code[0x58/8]=0xef98000000070100ULL;
    assert(!NativeProgramAddress(code,16));
    code[code.size()-2]=65537;
    assert(!NativeProgramAddress(code,0));
    code[code.size()-2]=3;
    code.back()=0;
    assert(!NativeProgramAddress(code,0));
    // P2.4: authentic native 3D pipeline builder needs VertexB; standalone
    // VertexA and unsupported tessellation/geometry must never enter its CFG.
    for (u32 mask : {0x02U, 0x03U, 0x22U, 0x23U})
        assert(NativeGraphicsStageMaskSupported(mask));
    for (u32 mask : {0x00U, 0x01U, 0x04U, 0x06U, 0x08U, 0x10U,
                     0x20U, 0x21U, 0x24U, 0x26U, 0x40U, 0xffU})
        assert(!NativeGraphicsStageMaskSupported(mask));
}
