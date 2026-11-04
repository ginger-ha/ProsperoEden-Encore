// SPDX-License-Identifier: GPL-3.0-or-later
// Real IR opcode/block and QMD3 CBUF admission. Host-only, no guest keys.
#include <array>
#include <cassert>
#include <cstdlib>
#include <cstdio>
#include "shader_recompiler/frontend/ampere/native_indirect_cbuf.h"
#include "shader_recompiler/object_pool.h"

using Shader::IR::Opcode;
using Shader::IR::Value;

static void Check(Opcode op, u32 bank, u32 offset, u32 reflected,
                  u32 enabled, bool dynamic_bank, bool dynamic_offset,
                  bool accepted, u32 required) {
    Shader::ObjectPool<Shader::IR::Inst> pool{16};
    Shader::IR::Block block{pool};
    Shader::IR::Program program{};
    program.stage=Shader::Stage::Compute;
    program.blocks.push_back(&block);
    program.info.constant_buffer_mask=reflected;
    for (u32 i=0;i<8;++i)
        if (reflected & (1U<<i))
            program.info.constant_buffer_descriptors.push_back({i,1});
    Value source{bank}, byte_offset{offset};
    if (dynamic_bank) {
        block.AppendNewInst(Opcode::IAdd32,{Value{u32{0}},Value{u32{1}}});
        source=Value{&block.back()};
    }
    if (dynamic_offset) {
        block.AppendNewInst(Opcode::IAdd32,{Value{u32{0}},Value{u32{4}}});
        byte_offset=Value{&block.back()};
    }
    block.AppendNewInst(op,{source,byte_offset});
    const bool ok=Shader::Ampere::NormalizeNativeQmdIndirectCbufIR(program,enabled);
    if (ok!=accepted || (ok && program.info.constant_buffer_used_sizes[bank]!=required)) {
        std::fprintf(stderr,"QMD3 direct CBUF bank=%u offset=%u op=%u ok=%u required=%u actual=%u\n",
                     bank,offset,static_cast<unsigned>(op),ok,required,
                     program.info.constant_buffer_used_sizes[bank]);
        std::abort();
    }
}
int main() {
    Check(Opcode::GetCbufU32,0,0,1,1,false,false,true,16);
    Check(Opcode::GetCbufU32,0,0xfffc,1,1,false,false,true,0x10000);
    Check(Opcode::GetCbufU32,0,0xffff,1,1,false,false,false,0);
    Check(Opcode::GetCbufU8,0,0xffff,1,1,false,false,true,0x10000);
    Check(Opcode::GetCbufS16,0,0xffff,1,1,false,false,false,0);
    Check(Opcode::GetCbufU32x2,0,0xfff8,1,1,false,false,true,0x10000);
    Check(Opcode::GetCbufU32x2,0,0xfffc,1,1,false,false,false,0);
    Check(Opcode::GetCbufU32,0,0,1,1,false,true,true,0x10000);
    Check(Opcode::GetCbufU32,1,0,1,3,false,false,false,0);
    Check(Opcode::GetCbufU32,0,0,1,1,true,false,false,0);
    Check(Opcode::GetCbufU32,0,0,1,0,false,false,false,0);
    std::puts("P2_3_NATIVE_QMD_REAL_DIRECT_CBUF_PASS masks=reflected widths=bounded dynamic=64KiB");
}
