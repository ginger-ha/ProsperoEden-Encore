// SPDX-License-Identifier: GPL-3.0-or-later
// Actual native Ampere/Turing TU104 96-bit MME interpreter host probes.
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string_view>
#include <utility>
#include <vector>
#include "video_core/macro_turing.h"
#include "video_core/native_ampere_macro_state.h"

using I=Tegra::TuringMacroInterpreter;
using W=std::uint32_t;

static std::array<W,3> Insn(W method, W value, bool fifo, bool end, bool emit=true) {
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
    if(emit) {
        set(82,3,5); // output method address from immediate 0
        set(85,4,fifo?1:6); // output value from ALU 0 or immediate 1
    }
    if(end)set(0,1,1);
    // Native upload words are reverse of the decoded 96-bit order.
    return {bits[2],bits[1],bits[0]};
}
static void Append(std::vector<W>& dst,const std::array<W,3>& insn){
    dst.insert(dst.end(),insn.begin(),insn.end());
}
// TU104 DRAM opcodes: ALU0 reads/writes the channel-owned 0xc00-word
// scratch bank. MME_DWRITE then a failing output must roll back that bank.
static std::array<W,3> DataRamInsn(W opcode,W address,W payload,
                                    bool end,bool emit) {
    std::array<W,3> bits{};
    const auto set=[&](unsigned low,unsigned width,W data) {
        for(unsigned bit=0;bit<width;++bit)
            if(data & (1u<<bit))
                bits[(low+bit)/32] |= W{1}<<((low+bit)%32);
    };
    set(10,5,opcode);
    set(15,5,24); set(20,5,25); set(25,5,26);
    set(30,16,address); set(66,16,payload);
    set(51,5,24); set(56,5,24); set(61,5,24);
    if(emit) {set(82,3,6);set(85,4,1);}
    if(end) set(0,1,1);
    return {bits[2],bits[1],bits[0]};
}
static std::array<W,3> RegisterReadInsn(W index) {
    std::array<W,3> bits{};
    const auto set=[&](unsigned low,unsigned width,W data){
        for(unsigned bit=0;bit<width;++bit)
            if(data & (1u<<bit))
                bits[(low+bit)/32] |= W{1}<<((low+bit)%32);
    };
    set(0,1,1); // end after the next (nonemitting) instruction
    set(10,5,22); // TU104 MME_READ
    set(15,5,0); set(20,5,25); set(25,5,24);
    set(30,16,index); // first ALU operand = sign-extended immediate
    set(51,5,24); set(56,5,24); set(61,5,24);
    set(66,16,0x250);
    set(82,3,6); set(85,4,1); // method from imm1, emitted ALU read
    return {bits[2],bits[1],bits[0]};
}
int main(){
    std::vector<W> code;
    Append(code,Insn(0x230,0x9876,false,true));
    Append(code,Insn(0,0,false,false,false));
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
    Append(code,Insn(0,0,false,false,false));
    fifo={0xC0DEC0DE};
    result=macro.Execute(std::span<const W>(code),0,fifo,read,emit);
    assert(result.success && result.consumed==1 && emitted.size()==1);
    assert((emitted[0]==std::pair<W,W>(0x270,0xC0DEC0DE)));
    fifo.clear();emitted.clear();
    result=macro.Execute(std::span<const W>(code),0,fifo,read,emit);
    assert(!result.success && result.error=="parameter FIFO underflow");
    // Guest MME emit target must be checked by the engine owner.
    fifo={17};
    const auto refuse=[](W,W){return false;};
    result=macro.Execute(std::span<const W>(code),0,fifo,read,refuse);
    assert(!result.success && result.error=="unsupported emitted method");
    // The actual guest upload protocol writes 3 consecutive 32-bit words
    // for each native 96-bit instruction. Each channel owns its macro DRAM.
    Tegra::NativeAmpereMacroState state;
    assert(!state.SetCodePointer(0x1000));
    assert(state.SetCodePointer(0));
    for (auto w : code) assert(state.PushCode(w));
    assert(!state.SetPositionPointer(0x80));
    assert(state.SetPositionPointer(0));
    assert(state.BindPosition(0));
    emitted.clear();fifo={23};
    result=state.Execute(0xe00,std::span<const W>{fifo},read,emit);
    assert(result.success && result.consumed==1);
    assert(emitted.size()==1 && emitted.front().first==0x270 &&
           emitted.front().second==23);
    assert(!state.Execute(0xe01,std::span<const W>{fifo},read,emit).success);
    assert(!state.Execute(0xe02,std::span<const W>{fifo},read,emit).success);

    // P2.4: macro writes must be atomic at the GPU-method boundary.
    // A later invalid output cannot dispatch an earlier valid PCAS/draw.
    Tegra::NativeAmpereMacroState atomic;
    code.clear();
    Append(code,Insn(0x230,0xAAAA,false,false));
    Append(code,Insn(0x10,0xBBBB,false,true)); // invalid 3D method after valid emit
    Append(code,Insn(0,0,false,false,false));
    assert(atomic.SetCodePointer(0));
    for(W w:code) assert(atomic.PushCode(w));
    assert(atomic.SetPositionPointer(0) && atomic.BindPosition(0));
    std::vector<std::pair<W,W>> committed;
    const auto allowed=[](W addr,W){return addr>=0x40 && addr<0xe00;};
    const auto commit=[&](W addr,W val){committed.emplace_back(addr,val);};
    const auto valid=[](){return true;};
    result=atomic.ExecuteStaged(0xe00,std::span<const W>{},read,allowed,commit,valid);
    assert(!result.success && committed.empty());
    // With BOTH outputs admissible, preserve the exact emission order.
    const auto allow_all=[](W addr,W){return addr<0xe00;};
    result=atomic.ExecuteStaged(0xe00,std::span<const W>{},read,allow_all,commit,valid);
    assert(result.success && committed.size()==2);
    assert((committed[0]==std::pair<W,W>(0x230,0xAAAA)));
    assert((committed[1]==std::pair<W,W>(0x10,0xBBBB)));
    committed.clear();
    // A late invalid native register read must not publish an earlier
    // perfectly valid method, even if the interpreter itself returns true.
    Tegra::NativeAmpereMacroState late_read;
    code.clear();
    Append(code,Insn(0x230,0x1234,false,false));
    Append(code,RegisterReadInsn(0x4000));
    Append(code,Insn(0,0,false,false,false));
    assert(late_read.SetCodePointer(0));
    for(W w:code) assert(late_read.PushCode(w));
    assert(late_read.SetPositionPointer(0) && late_read.BindPosition(0));
    bool bad_native_read=false;
    const auto read_checked=[&](W index)->W {
        if(index>=0x1000){bad_native_read=true;return 0;}
        return index;
    };
    result=late_read.ExecuteStaged(
        0xe00,std::span<const W>{},read_checked,allow_all,commit,
        [&]{return !bad_native_read;});
    assert(!result.success && bad_native_read && committed.empty());

    // The native 0xc00-word MME data RAM is also a transaction: an error
    // after DWRITE must not corrupt a later, valid macro from this channel.
    Tegra::NativeAmpereMacroState ram_state;
    code.clear(); committed.clear();
    Append(code,DataRamInsn(31,0x27,0x42,false,false));
    Append(code,Insn(0x10,0,false,true));
    Append(code,Insn(0,0,false,false,false));
    assert(ram_state.SetCodePointer(0));
    for(W w:code) assert(ram_state.PushCode(w));
    assert(ram_state.SetPositionPointer(0) && ram_state.BindPosition(0));
    result=ram_state.ExecuteStaged(
        0xe00,std::span<const W>{},read,allowed,commit,valid);
    assert(!result.success && committed.empty());
    code.clear();
    Append(code,DataRamInsn(30,0x27,0x230,true,true));
    Append(code,Insn(0,0,false,false,false));
    assert(ram_state.SetCodePointer(3));
    for(W w:code) assert(ram_state.PushCode(w));
    assert(ram_state.SetPositionPointer(1) && ram_state.BindPosition(3));
    result=ram_state.ExecuteStaged(
        0xe02,std::span<const W>{},read,allowed,commit,valid);
    assert(result.success && committed.size()==1 &&
           (committed[0]==std::pair<W,W>(0x230,0)));
    committed.clear();
    // A validator may throw after a successful TU104 DWRITE. Validation
    // still precedes GPU-method commit, so the channel's DRAM must be
    // restored before unwinding and the next macro must read the old zero.
    code.clear();
    Append(code,DataRamInsn(31,0x27,0x42,false,false));
    Append(code,Insn(0x230,0xA55A,false,true));
    Append(code,Insn(0,0,false,false,false));
    assert(ram_state.SetCodePointer(5));
    for(W w:code) assert(ram_state.PushCode(w));
    assert(ram_state.SetPositionPointer(2) && ram_state.BindPosition(5));
    bool validator_threw{};
    try {
        (void)ram_state.ExecuteStaged(
            0xe04,std::span<const W>{},read,allowed,commit,
            []() -> bool { throw std::runtime_error("channel epoch changed"); });
    } catch (const std::runtime_error&) {
        validator_threw = true;
    }
    assert(validator_threw && committed.empty());
    result=ram_state.ExecuteStaged(
        0xe02,std::span<const W>{},read,allowed,commit,valid);
    assert(result.success && committed.size()==1 &&
           (committed[0]==std::pair<W,W>(0x230,0)));
    committed.clear();
    std::vector<W> oversized(Tegra::NativeAmpereMacroState::MaxFifo+1,3);
    auto too_many=state.Execute(0xe00,std::span<const W>{oversized},read,emit);
    assert(!too_many.success &&
           too_many.error=="native macro FIFO limit exceeded");
    // A truncated 96-bit program must not execute or read outside RAM.
    code={1};
    result=macro.Execute(std::span<const W>(code),0,fifo,read,emit);
    assert(!result.success && result.error=="instruction outside uploaded RAM");
    // A nonterminated MME sequence never falls through into unknown memory.
    code.clear();fifo.clear();
    Append(code,Insn(0,0,false,false,false));Append(code,Insn(0,0,false,false,false));
    result=macro.Execute(std::span<const W>(code),0,fifo,read,emit);
    assert(!result.success && result.error=="instruction outside uploaded RAM");

    // P2.4: a guest MME_READ may request a register beyond its native
    // class's declared bank. The engine must reject that read before an
    // emitted QMD/PCAS method can use a fabricated zero register value.
    code.clear(); fifo.clear(); emitted.clear();
    Append(code,RegisterReadInsn(0x120));
    Append(code,Insn(0,0,false,false,false));
    bool out_of_range=false;
    const auto checked_read=[&](W index)->W {
        if(index >= 0x1000) {out_of_range=true; return 0;}
        assert(index == 0x120);
        return 0xFEEDBEEF;
    };
    const auto checked_emit=[&](W address,W value)->bool {
        if(out_of_range) return false;
        emitted.emplace_back(address,value);
        return true;
    };
    result=macro.Execute(std::span<const W>(code),0,fifo,checked_read,checked_emit);
    assert(result.success && !out_of_range && emitted.size()==1);
    assert(emitted.front().first==0x250 && emitted.front().second==0xFEEDBEEF);
    code.clear(); emitted.clear();
    Append(code,RegisterReadInsn(0x4000));
    Append(code,Insn(0,0,false,false,false));
    out_of_range=false;
    result=macro.Execute(std::span<const W>(code),0,fifo,checked_read,checked_emit);
    assert(out_of_range && !result.success && emitted.empty());
}
