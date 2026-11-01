// SPDX-License-Identifier: GPL-3.0-or-later
// Actual native Ampere/Turing TU104 96-bit MME interpreter host probes.
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <string_view>
#include <utility>
#include <vector>
#include "video_core/macro_turing.h"

using I=Tegra::TuringMacroInterpreter;
using W=std::uint32_t;

static std::array<W,3> Insn(W method, W value, bool fifo, bool end) {
    std::array<W,3> bits{};
    const auto set=[&](unsigned low,unsigned width,W data){
        for(unsigned bit=0;bit<width;++bit)
            if(data & (1u<<bit))
                bits[(low+bit)/32] |= W{1}<<((low+bit)%32);
    };
    // Zero-input operands: lane 0 may instead read register 28 (FIFO).
    set(15,5,24);set(20,5,fifo?28:24);set(25,5,24);
    set(51,5,24);set(56,5,24);set(61,5,24);
    set(30,16,method);set(66,16,value);
    set(82,3,5); // output method address from immediate 0
    set(85,4,fifo?1:6); // output value from ALU 0 or immediate 1
    if(end)set(0,1,1);
    // Native upload words are reverse of the decoded 96-bit order.
    return {bits[2],bits[1],bits[0]};
}
static void Append(std::vector<W>& dst,const std::array<W,3>& insn){
    dst.insert(dst.end(),insn.begin(),insn.end());
}
int main(){
    std::vector<W> code;
    Append(code,Insn(0x230,0x9876,false,true));
    Append(code,Insn(0,0,false,false));
    std::vector<W> fifo;
    std::vector<std::pair<W,W>> emitted;
    I macro;
    const auto read=[](W)->W{return 0;};
    const auto emit=[&](W addr,W value){emitted.emplace_back(addr,value);return true;};
    auto result=macro.Execute(std::span<const W>(code),0,fifo,read,emit);
    assert(result.success && result.consumed==0 && emitted.size()==1);
    assert(emitted[0].first==0x230 && emitted[0].second==0x9876);
    // FIFO paths use the real interpreter: one fetched parameter becomes
    // the ALU result and is emitted as a GPU method write.
    code.clear();emitted.clear();
    Append(code,Insn(0x270,0,true,true));
    Append(code,Insn(0,0,false,false));
    fifo={0xC0DEC0DE};
    result=macro.Execute(std::span<const W>(code),0,fifo,read,emit);
    assert(result.success && result.consumed==1 && emitted.size()==1);
    assert(emitted[0]==std::pair<W,W>(0x270,0xC0DEC0DE));
    fifo.clear();emitted.clear();
    result=macro.Execute(std::span<const W>(code),0,fifo,read,emit);
    assert(!result.success && result.error=="parameter FIFO underflow");
    // Guest MME emit target must be checked by the engine owner.
    fifo={17};
    const auto refuse=[](W,W){return false;};
    result=macro.Execute(std::span<const W>(code),0,fifo,read,refuse);
    assert(!result.success && result.error=="unsupported emitted method");
    // A truncated 96-bit program must not execute or read outside RAM.
    code={1};
    result=macro.Execute(std::span<const W>(code),0,fifo,read,emit);
    assert(!result.success && result.error=="instruction outside uploaded RAM");
    // A nonterminated MME sequence never falls through into unknown memory.
    code.clear();fifo.clear();
    Append(code,Insn(0,0,false,false));Append(code,Insn(0,0,false,false));
    result=macro.Execute(std::span<const W>(code),0,fifo,read,emit);
    assert(!result.success && result.error=="instruction outside uploaded RAM");
}
