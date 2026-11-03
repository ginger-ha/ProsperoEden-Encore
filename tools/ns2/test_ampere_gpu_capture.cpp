// SPDX-License-Identifier: GPL-3.0-or-later
// Synthetic mapped-memory fixture for the actual Ampere GPU shader capture.
// Does not execute GPU code or require access to copyrighted game images.
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <optional>
#include <stdexcept>
#include <vector>
#include "shader_recompiler/frontend/ampere/capture.h"
#include "shader_recompiler/frontend/ampere/program_capture.h"
#include "shader_recompiler/stage.h"

using namespace Shader::Ampere;
struct MappedMemory {
    u64 base{0x100000};
    std::vector<u8> data;
    std::size_t mapped_bytes{};
    u32 reads{};
    bool reject_batch{};
    bool throw_on_batch{};
    u64 throw_at_address{};
};
static bool Read(void* opaque, u64 address, void* destination, std::size_t size) {
    auto& mem = *static_cast<MappedMemory*>(opaque);
    ++mem.reads;
    if ((mem.throw_at_address && address == mem.throw_at_address) ||
        (mem.throw_on_batch && size > 16))
        throw std::runtime_error("guest mapping changed during shader capture");
    if (!destination || !size || address < mem.base || (mem.reject_batch && size > 16))
        return false;
    const u64 offset = address - mem.base;
    if (offset > mem.mapped_bytes || size > mem.mapped_bytes - offset ||
        offset > mem.data.size() || size > mem.data.size() - offset)
        return false;
    std::memcpy(destination, mem.data.data() + offset, size);
    return true;
}
struct MutatingGpuRead {
    MappedMemory* memory{};
    u64 watch_address{};
    std::size_t watch_size{};
    u32 watch_hits{};
};
static bool ReadMutatingGpu(void* context, u64 address, void* destination,
                            std::size_t size) {
    auto& fixture=*static_cast<MutatingGpuRead*>(context);
    if (!Read(fixture.memory,address,destination,size)) return false;
    if (address==fixture.watch_address && size==fixture.watch_size &&
        ++fixture.watch_hits>=2)
        static_cast<u8*>(destination)[0]^=1U;
    return true;
}
static void Require(bool condition, const char* why) {
    if (!condition) {
        std::fprintf(stderr, "NS2 shader memory capture FAIL: %s\n", why);
        std::exit(1);
    }
}
static void Push(std::vector<u8>& dst, u32 a, u32 b=0, u32 c=0, u32 d=0) {
    for (u32 word : {a,b,c,d})
        for (u32 byte=0;byte!=4;++byte)
            dst.push_back(static_cast<u8>(word >> (byte*8)));
}
struct CbufFixture {
    std::array<u32,16> entries{};
    u32 reads{};
    bool missing{};
    bool throw_reader{};
    bool mutate_between_reads{};
};
static std::optional<u32> ReadCheckedCbuf(void* context,u32 bank,u32 offset) {
    auto& cbuf=*static_cast<CbufFixture*>(context);
    ++cbuf.reads;
    if (cbuf.throw_reader)
        throw std::runtime_error("CBUF guest mapping changed");
    if (cbuf.missing || bank!=7 || offset<0xffc0U ||
        offset>=0x10000U || offset&3U)
        return {};
    const u32 word=(offset-0xffc0U)/4;
    if (cbuf.mutate_between_reads && cbuf.reads>16 && word==0)
        return 0x100U;
    return cbuf.entries[word];
}

int main() {
    constexpr u32 pred_true=7u<<12;
    constexpr u32 exit_true=7u<<23;
    MappedMemory mem{};
    mem.data.resize(0x80);
    mem.data[0]=0x38;
    Push(mem.data,pred_true|0x918); // native NOP
    Push(mem.data,pred_true|0x94d,0,exit_true); // native EXIT
    mem.mapped_bytes=mem.data.size();
    auto ok=CaptureNativeGraphicsShader(mem.base,4,Read,&mem);
    Require(ok.Ready() && ok.captured_native_bytes==32 &&
            ok.image.consumed_native_bytes==32 &&
            ok.image.TranslateNativeAddress(0).has_value(),
            "read mapped native program, detect EXIT and lower to Maxwell image");
    Require(mem.reads==3,"exact one 128-byte header and two native instruction reads");
    // Compute starts at the real QMD program code, not at a fabricated
    // graphics header. Only the actual mapped 16-byte instructions are read.
    const auto compute=CaptureNativeComputeShader(mem.base+0x80,Read,&mem);
    Require(compute.Ready() && compute.captured_native_bytes==32 &&
            compute.image.native_stage==static_cast<u32>(Shader::Stage::Compute) &&
            compute.image.diagnostic_cache_key!=ok.image.diagnostic_cache_key &&
            compute.image.ReadMaxwellInstruction(0x50).has_value(),
            "compute capture must use a separate headerless stage domain");
    Require(mem.reads==5,
            "compute capture must read only the two actual instructions");
    // Native QMD3 shader code can live above the 32-bit-PCAS or legacy
    // 40-bit GPU address window. The capture reader must not alias the
    // low guest address when a valid 49-bit GPU VA is supplied.
    MappedMemory high_shader{};
    high_shader.base = 0x10100000000ULL;
    high_shader.data = mem.data;
    high_shader.mapped_bytes = high_shader.data.size();
    const auto upper_compute = CaptureNativeComputeShader(
        high_shader.base+0x80,Read,&high_shader);
    Require(upper_compute.Ready() &&
            upper_compute.captured_native_bytes==32 &&
            high_shader.reads==2 &&
            upper_compute.image.diagnostic_cache_key==
                compute.image.diagnostic_cache_key,
            "49-bit native Compute GPU address retains exact program bytes");
    mem.mapped_bytes=0x80+16;
    const auto compute_fault=CaptureNativeComputeShader(mem.base+0x80,Read,&mem);
    Require(compute_fault.status==NativeCaptureStatus::Unmapped &&
            compute_fault.first_error_offset==16 &&
            compute_fault.image.code.empty(),
            "compute second instruction unmapped rejects with code-relative offset");
    mem.mapped_bytes=mem.data.size();
    // Exception in the guest reader must become the same fail-closed
    // Unmapped result as an ordinary GMMU read failure, with exact offsets.
    mem.throw_at_address=mem.base;
    const auto throwing_header=CaptureNativeGraphicsShader(mem.base,4,Read,&mem);
    Require(throwing_header.status==NativeCaptureStatus::Unmapped &&
            throwing_header.image.code.empty(),
            "throwing graphics header reader fails closed");
    mem.throw_at_address=mem.base+0x90;
    const auto throwing_compute=CaptureNativeComputeShader(mem.base+0x80,Read,&mem);
    Require(throwing_compute.status==NativeCaptureStatus::Unmapped &&
            throwing_compute.first_error_offset==16 &&
            throwing_compute.image.code.empty(),
            "throwing compute second-instruction read preserves failure offset");
    mem.throw_at_address=0;
    const auto reads_before_invalid_stage=mem.reads;
    Require(CaptureNativeGraphicsShader(
                mem.base,static_cast<u32>(Shader::Stage::Compute),Read,&mem).status==
                NativeCaptureStatus::InvalidInput,
            "compute stage requires distinct QMD metadata, not graphics SPH");
    Require(CaptureNativeGraphicsShader(mem.base,0xffffffffU,Read,&mem).status==
                NativeCaptureStatus::InvalidInput,
            "out-of-range stage cannot build graphics shader cache identity");
    Require(mem.reads==reads_before_invalid_stage,
            "invalid stages fail before a single guest GMMU read");
    auto stable=CaptureNativeGraphicsShader(mem.base,4,Read,&mem);
    Require(stable.Ready() &&
            stable.image.diagnostic_cache_key==ok.image.diagnostic_cache_key,
            "source-verified repeated capture gives stable diagnostic identity");

    mem.mapped_bytes=0x80+16;
    auto fault=CaptureNativeGraphicsShader(mem.base,4,Read,&mem);
    Require(fault.status==NativeCaptureStatus::Unmapped &&
            fault.first_error_offset==0x90 &&
            fault.image.code.empty(),
            "guest memory fault at second instruction yields no partial shader");
    mem.mapped_bytes=0x4f;
    auto header_fault=CaptureNativeGraphicsShader(mem.base,4,Read,&mem);
    Require(header_fault.status==NativeCaptureStatus::Unmapped &&
            header_fault.image.code.empty(),
            "native header must be fully mapped");
    mem.mapped_bytes=mem.data.size();

    mem.data.resize(0x80);
    Push(mem.data,pred_true|0x947,0xffffffe0u,0); // BRA invalid target
    mem.mapped_bytes=mem.data.size();
    auto branch=CaptureNativeGraphicsShader(mem.base,4,Read,&mem);
    Require(branch.status==NativeCaptureStatus::InvalidBranch &&
            branch.first_error_offset==0x80 &&
            branch.image.code.empty(),
            "out-of-bounds native branch is rejected before compiler");
    mem.data.resize(0x80);
    Push(mem.data,pred_true|0x949); // BRX requires unimplemented CBUF table
    Push(mem.data,pred_true|0x94d,0,exit_true);
    mem.mapped_bytes=mem.data.size();
    auto indirect=CaptureNativeGraphicsShader(mem.base,4,Read,&mem);
    Require(indirect.status==NativeCaptureStatus::UnresolvedIndirectBranch &&
            indirect.first_error_offset==0x80 &&
            indirect.image.code.empty(),
            "BRX must not become a valid image without target-table resolution");
    mem.data.resize(0x80);
    Push(mem.data,pred_true|0x958); // Uniform BRXU is indirect too.
    Push(mem.data,pred_true|0x94d,0,exit_true);
    mem.mapped_bytes=mem.data.size();
    const auto indirect_uniform=CaptureNativeGraphicsShader(mem.base,4,Read,&mem);
    Require(indirect_uniform.status==NativeCaptureStatus::UnresolvedIndirectBranch &&
            indirect_uniform.first_error_offset==0x80 &&
            indirect_uniform.image.code.empty(),
            "BRXU must not publish an untracked native-PC shader");

    // The existing native-PC jump-table recognizer is useful only as a
    // preflight; the CBUF words still require a native->Maxwell address
    // transform and shader-visible value remap before a BRX can execute.
    // Validate the last possible 16-entry U32 table and reject wrap/invalid
    // banks without performing any guest CBUF reads.
    std::vector<Instruction> motif{
        Instruction{{pred_true|0x817U|(4U<<16),15U,0x03800000U,0}},
        Instruction{{pred_true|0x819U|(5U<<16)|(4U<<24),2U,0x000006ffU,0}},
        Instruction{{pred_true|0xb82U|(6U<<16)|(5U<<24),
                     (7U<<22)|(0xffc0U<<6),0x00000800U,0}},
        Instruction{{pred_true|0x949U|(6U<<24),0xffffffc0U,0x0383ffffU,0}},
    };
    auto table=TrackCaptureIndirectBranches(motif);
    Require(table.size()==1 && table[0].index==3 &&
            table[0].cbuf_index==7 && table[0].cbuf_offset==0xffc0U &&
            table[0].entries==16,
            "BRX table ending at 64-KiB CBUF boundary is valid metadata");
    auto spaced_motif=motif;
    spaced_motif.insert(spaced_motif.begin()+1,
                        Instruction{{pred_true|0x918U,0,0,0}});
    // BRX moved one native instruction: its absolute-zero relative base
    // must change from -64 to -80 bytes as well.
    spaced_motif[4].words[1]=0xffffffb0U;
    Require(TrackCaptureIndirectBranches(spaced_motif).size()==1,
            "canonical NOP between jump-table definitions is transparent");
    auto clobbered_motif=motif;
    clobbered_motif.insert(clobbered_motif.begin()+3,
                          Instruction{{pred_true|0x202U|(6U<<16),0,0,0}});
    clobbered_motif[4].words[1]=0xffffffb0U;
    Require(TrackCaptureIndirectBranches(clobbered_motif).empty(),
            "intervening register overwrite cannot reuse stale LDC target");
    auto interleaved_motif=motif;
    interleaved_motif.insert(interleaved_motif.begin()+1,
                            Instruction{{pred_true|0x202U|(9U<<16),0,0,0}});
    interleaved_motif[4].words[1]=0xffffffb0U;
    Require(TrackCaptureIndirectBranches(interleaved_motif).empty(),
            "unproved interleaved source instructions fail closed");
    motif[2].words[1]=(7U<<22)|(0xffc4U<<6);
    Require(TrackCaptureIndirectBranches(motif).empty(),
            "BRX table crossing 64-KiB CBUF boundary must not be read");
    motif[2].words[1]=(18U<<22)|(0xffc0U<<6);
    Require(TrackCaptureIndirectBranches(motif).empty(),
            "BRX CBUF bank outside 18 reflected shader banks rejected");

    // Exact native-PC -> emitted-Maxwell-PC map. No arithmetic 16:8
    // assumption: a native instruction may expand and Maxwell has scheduler
    // words. The actual captured image must resolve both entries.
    CaptureIndirectResult captured_table{};
    captured_table.tables.push_back({
        .branch=0, .cbuf_index=7, .cbuf_offset=0xfff8U,
        .values={0x80U,0x90U}, .targets={0,1}});
    const auto mapped_header_table=TranslateCaptureIndirectTargets(
        captured_table,ok.image,CaptureIndirectValueOrigin::GraphicsHeader);
    Require(mapped_header_table && mapped_header_table->size()==1 &&
            mapped_header_table->front().entries.size()==2 &&
            mapped_header_table->front().cbuf_index==7 &&
            mapped_header_table->front().cbuf_offset==0xfff8U &&
            mapped_header_table->front().entries[0].native_code_offset==0 &&
            mapped_header_table->front().entries[0].maxwell_byte_offset==
                *ok.image.TranslateNativeAddress(0) &&
            mapped_header_table->front().entries[1].native_code_offset==16 &&
            mapped_header_table->front().entries[1].maxwell_byte_offset==
                *ok.image.TranslateNativeAddress(16),
            "BRX native shader-header table maps every PC through actual Maxwell image");
    Require(!TranslateCaptureIndirectTargets(
                captured_table,ok.image,CaptureIndirectValueOrigin::NativeCode),
            "BRX must not interpret header-relative entries as code-relative");
    captured_table.tables[0].values={0,16};
    const auto mapped_code_table=TranslateCaptureIndirectTargets(
        captured_table,ok.image,CaptureIndirectValueOrigin::NativeCode);
    Require(mapped_code_table && mapped_code_table->front().entries[0].raw_value==0 &&
            mapped_code_table->front().entries[0].maxwell_byte_offset==
                *ok.image.TranslateNativeAddress(0),
            "BRX zero is a valid code-relative target, not a missing entry");
    Require(!TranslateCaptureIndirectTargets(
                captured_table,ok.image,CaptureIndirectValueOrigin::GraphicsHeader),
            "code-relative zero must not become a graphics-header-relative PC");
    captured_table.tables[0].values={0x80U,0x91U};
    Require(!TranslateCaptureIndirectTargets(
                captured_table,ok.image,CaptureIndirectValueOrigin::GraphicsHeader),
            "BRX misaligned entry invalidates complete target map");
    captured_table.tables[0].values={0x80U,0xa0U};
    Require(!TranslateCaptureIndirectTargets(
                captured_table,ok.image,CaptureIndirectValueOrigin::GraphicsHeader),
            "BRX target beyond captured shader invalidates complete target map");
    captured_table.tables[0].values={0x80U,0x90U};
    captured_table.tables[0].cbuf_offset=0xfffcU;
    Require(!TranslateCaptureIndirectTargets(
                captured_table,ok.image,CaptureIndirectValueOrigin::GraphicsHeader),
            "BRX table that wraps 64 KiB CBUF must not map");
    captured_table.tables[0].cbuf_offset=0xfff8U;
    captured_table.tables[0].cbuf_index=18;
    Require(!TranslateCaptureIndirectTargets(
                captured_table,ok.image,CaptureIndirectValueOrigin::GraphicsHeader),
            "BRX table with invalid CBUF bank must not map");
    captured_table.tables[0].cbuf_index=7;
    // Lowering may leave two distinct native instructions at the same
    // emitted address. Such an image can be structurally valid for linear
    // translation, but may never be used as an indirect branch target map.
    auto aliased_image=ok.image;
    const std::size_t map_count=static_cast<std::size_t>(
        aliased_image.code[aliased_image.code.size()-2]);
    const std::size_t map_start=aliased_image.code.size()-map_count-2;
    aliased_image.code[map_start+1]=aliased_image.code[map_start];
    Require(aliased_image.ValidForCompiler() &&
            !TranslateCaptureIndirectTargets(
                captured_table,aliased_image,CaptureIndirectValueOrigin::GraphicsHeader),
            "two distinct native BRX targets must not alias one Maxwell PC");
    captured_table.tables.push_back(captured_table.tables[0]);
    Require(!TranslateCaptureIndirectTargets(
                captured_table,ok.image,CaptureIndirectValueOrigin::GraphicsHeader),
            "duplicate BRX index must not publish competing target tables");

    // Extend a recognized BRX source capture beyond its first EXIT using
    // explicit CBUF origin, immutable snapshot verification and bounded
    // per-instruction reads. Neither this test nor the helper executes BRX.
    auto source_motif=motif;
    source_motif[2].words[1]=(7U<<22)|(0xffc0U<<6);
    source_motif.push_back(Instruction{{pred_true|0x94d,0,exit_true,0}});
    ProgramCaptureState initial_capture;
    for (u32 i=0; i<source_motif.size(); ++i)
        initial_capture.Observe(source_motif[i],i);
    std::array<u32,16> guest_targets{};
    for (u32 i=0;i<guest_targets.size();++i)
        guest_targets[i]=i&1U ? 0x100U : 0x80U;
    const auto cbuf_reader=[&](u32 bank,u32 offset)->std::optional<u32> {
        if (bank!=7 || offset<0xffc0U || offset>=0x10000U || offset&3U)
            return {};
        return guest_targets[(offset-0xffc0U)/4];
    };
    const auto tail_reader=[&](u32 index)->std::optional<Instruction> {
        if (index<5 || index>9) return {};
        if (index==9) return Instruction{{pred_true|0x94d,0,exit_true,0}};
        return Instruction{{pred_true|0x918,0,0,0}};
    };
    auto extended_source=source_motif;
    auto extended_state=initial_capture;
    const auto extended=ResolveCaptureIndirectBranchesChecked(
        extended_source,extended_state,
        CaptureIndirectValueOrigin::GraphicsHeader,tail_reader,cbuf_reader);
    Require(extended && extended->extended && extended->base==0x80U &&
            extended->tables.size()==1 && extended->tables[0].branch==3 &&
            extended->tables[0].values.size()==16 &&
            extended->tables[0].targets.size()==2 &&
            extended->tables[0].targets[0]==0 &&
            extended->tables[0].targets[1]==8 &&
            extended_source.size()==10,
            "BRX capture extends beyond earlier EXIT through final verified target");
    const auto dispatch_plans=MakeNativeIndirectBranchPlans(
        *extended,extended_source);
    Require(dispatch_plans && dispatch_plans->size()==1 &&
            dispatch_plans->front().branch_instruction_index==3 &&
            dispatch_plans->front().raw_pc_base==0x80U &&
            dispatch_plans->front().targets.size()==16 &&
            dispatch_plans->front().targets[0].native_value==0x80U &&
            dispatch_plans->front().targets[1].native_instruction_index==8,
            "verified BRX CBUF snapshot produces exact compiler dispatch plan");
    auto malformed_capture=*extended;
    malformed_capture.tables[0].cbuf_index=18;
    Require(!MakeNativeIndirectBranchPlans(malformed_capture,extended_source),
            "BRX plan cannot bind a different CBUF bank than captured shader");
    malformed_capture=*extended;
    malformed_capture.tables[0].values[1]=0x91U;
    Require(!MakeNativeIndirectBranchPlans(malformed_capture,extended_source),
            "BRX plan rejects non-16-byte native target alignment");
    auto mutated_source=extended_source;
    mutated_source[3].words[0]=pred_true|0x958U;
    Require(!MakeNativeIndirectBranchPlans(*extended,mutated_source),
            "BRX plan must reject a newly replaced BRXU opcode");
    guest_targets[1]=0x81U;
    auto bad_source=source_motif;
    auto bad_state=initial_capture;
    Require(!ResolveCaptureIndirectBranchesChecked(
                bad_source,bad_state,CaptureIndirectValueOrigin::GraphicsHeader,
                tail_reader,cbuf_reader) && bad_source.size()==source_motif.size(),
            "misaligned BRX CBUF target rejects without mutating source");
    guest_targets[1]=0x100U;
    bad_source=source_motif;
    bad_state=initial_capture;
    const auto faulting_tail=[&](u32 index)->std::optional<Instruction> {
        return index>=8 ? std::nullopt : tail_reader(index);
    };
    Require(!ResolveCaptureIndirectBranchesChecked(
                bad_source,bad_state,CaptureIndirectValueOrigin::GraphicsHeader,
                faulting_tail,cbuf_reader) && bad_source.size()==source_motif.size(),
            "BRX GMMU fault while extending shader rolls back all appended instructions");
    bad_source=source_motif;
    bad_state=initial_capture;
    const auto unexpected_brx=[&](u32 index)->std::optional<Instruction> {
        if (index==6) return Instruction{{pred_true|0x958,0,0,0}};
        return tail_reader(index);
    };
    Require(!ResolveCaptureIndirectBranchesChecked(
                bad_source,bad_state,CaptureIndirectValueOrigin::GraphicsHeader,
                unexpected_brx,cbuf_reader) && bad_source.size()==source_motif.size(),
            "BRX extended tail must reject newly discovered untracked BRXU");
    bad_source=source_motif;
    bad_state=initial_capture;
    u32 snapshot_reads{};
    const auto changing_table=[&](u32 bank,u32 offset)->std::optional<u32> {
        ++snapshot_reads;
        const auto value=cbuf_reader(bank,offset);
        if (!value) return {};
        return snapshot_reads>16 && offset==0xffc0U
            ? std::optional<u32>{0x100U} : value;
    };
    Require(!ResolveCaptureIndirectBranchesChecked(
                bad_source,bad_state,CaptureIndirectValueOrigin::GraphicsHeader,
                tail_reader,changing_table) && bad_source.size()==source_motif.size(),
            "BRX changed guest CBUF between read and capture must roll back");
    bad_source=source_motif;
    bad_state=initial_capture;
    const auto throwing_table=[&](u32,u32)->std::optional<u32> {
        throw std::runtime_error("guest CBUF mapping changed");
    };
    Require(!ResolveCaptureIndirectBranchesChecked(
                bad_source,bad_state,CaptureIndirectValueOrigin::GraphicsHeader,
                tail_reader,throwing_table) && bad_source.size()==source_motif.size(),
            "BRX throwing CBUF reader must roll back without publishing a shader");


    // GMMU 49-bit admission applies to every real source/CBUF read, not
    // just host-u64 overflow. A mock reader may claim that out-of-range
    // synthetic bytes are mapped; the capture must still refuse them.
    constexpr u64 GmmuLimit49=u64{1}<<49;
    Require(NativeGpuRange49(GmmuLimit49-16,16) &&
            !NativeGpuRange49(GmmuLimit49-16,17) &&
            !NativeGpuRange49(GmmuLimit49,1) &&
            !NativeGpuRange49(1,0) &&
            !NativeGpuRange49(~u64{0},16),
            "native shader GMMU reads enforce complete 49-bit range");
    MappedMemory edge_shader{};
    edge_shader.base=GmmuLimit49-0xa0U;
    edge_shader.data.resize(0x80U);
    edge_shader.data[0]=0x38;
    Push(edge_shader.data,pred_true|0x918U);
    Push(edge_shader.data,pred_true|0x94dU,0,exit_true);
    edge_shader.mapped_bytes=edge_shader.data.size();
    const auto valid_edge_shader=CaptureNativeGraphicsShader(
        edge_shader.base,4,Read,&edge_shader);
    Require(valid_edge_shader.Ready() &&
            valid_edge_shader.captured_native_bytes==2*sizeof(Instruction),
            "short native shader ending at top of 49-bit VA stays supported");
    edge_shader.base=GmmuLimit49-0x90U;
    const auto over_edge_shader=CaptureNativeGraphicsShader(
        edge_shader.base,4,Read,&edge_shader);
    Require(over_edge_shader.status==NativeCaptureStatus::Unmapped &&
            over_edge_shader.first_error_offset==0x90U &&
            over_edge_shader.image.code.empty(),
            "native shader rejects second instruction beyond 49-bit VA even if mock maps it");

    // Exercise the real checked capture/lowerer handoff. The native shader
    // has a tracked BRX at instruction 3, a first EXIT at 4, and a target
    // after that EXIT. The executing CBUF value remains an original guest PC.
    MappedMemory brx_memory{};
    brx_memory.data.resize(0x80);
    brx_memory.data[0]=0x38;
    Push(brx_memory.data,pred_true|0x817U|(4U<<16),15U,0x03800000U);
    Push(brx_memory.data,pred_true|0x819U|(5U<<16)|(4U<<24),2U,0x000006ffU);
    Push(brx_memory.data,pred_true|0xb82U|(6U<<16)|(5U<<24),
         (7U<<22)|(0xffc0U<<6),0x00000800U);
    Push(brx_memory.data,pred_true|0x949U|(6U<<24),0xffffffc0U,0x0383ffffU);
    Push(brx_memory.data,pred_true|0x94dU,0,exit_true);
    for(u32 i=0;i<4;++i) Push(brx_memory.data,pred_true|0x918U);
    Push(brx_memory.data,pred_true|0x94dU,0,exit_true);
    brx_memory.mapped_bytes=brx_memory.data.size();
    CbufFixture stable_cbuf{};
    for(u32 i=0;i<stable_cbuf.entries.size();++i)
        stable_cbuf.entries[i]=i&1 ? 0x100U : 0x80U;
    const auto compiled_brx=CaptureNativeGraphicsShaderChecked(
        brx_memory.base,4,Read,&brx_memory,ReadCheckedCbuf,&stable_cbuf);
    Require(compiled_brx.Ready() &&
            compiled_brx.captured_native_bytes==10*sizeof(Instruction) &&
            compiled_brx.image.ValidForCompiler() &&
            compiled_brx.image.TranslateNativeAddress(8*16).has_value() &&
            stable_cbuf.reads>=3*stable_cbuf.entries.size(),
            "checked graphics BRX captures post-EXIT target and lowers dispatch");
    // Verify both legitimate PC conventions without guessing a table
    // origin from the first nonzero CBUF word. The native image and every
    // generated branch must retain the exact selected convention.
    for(u32 i=0;i<stable_cbuf.entries.size();++i)
        stable_cbuf.entries[i]=i&1 ? 0x80U : 0U;
    stable_cbuf.reads=0;
    const auto code_relative_brx=CaptureNativeGraphicsShaderChecked(
        brx_memory.base,4,Read,&brx_memory,ReadCheckedCbuf,&stable_cbuf);
    Require(code_relative_brx.Ready() &&
            code_relative_brx.captured_native_bytes==10*sizeof(Instruction) &&
            code_relative_brx.image.ValidForCompiler() &&
            code_relative_brx.image.diagnostic_cache_key!=
                compiled_brx.image.diagnostic_cache_key,
            "code-relative BRX CBUF addresses use the independent verified origin");
    // Both candidate origins can be fully mapped on a sufficiently long
    // shader. Reject this ambiguity, rather than running the wrong block.
    auto ambiguous_memory=brx_memory;
    for (u32 i=10;i<19;++i)
        Push(ambiguous_memory.data,pred_true|0x918U);
    Push(ambiguous_memory.data,pred_true|0x94dU,0,exit_true);
    ambiguous_memory.mapped_bytes=ambiguous_memory.data.size();
    for(u32 i=0;i<stable_cbuf.entries.size();++i)
        stable_cbuf.entries[i]=i&1 ? 0x110U : 0x100U;
    const auto ambiguous_brx=CaptureNativeGraphicsShaderChecked(
        ambiguous_memory.base,4,Read,&ambiguous_memory,
        ReadCheckedCbuf,&stable_cbuf);
    Require(!ambiguous_brx.Ready() && ambiguous_brx.image.code.empty(),
            "simultaneously valid BRX origins must fail closed");
    for(u32 i=0;i<stable_cbuf.entries.size();++i)
        stable_cbuf.entries[i]=i&1 ? 0x100U : 0x80U;
    stable_cbuf.reads=0;
    const auto no_cbuf_brx=CaptureNativeGraphicsShader(
        brx_memory.base,4,Read,&brx_memory);
    Require(no_cbuf_brx.status==NativeCaptureStatus::UnresolvedIndirectBranch,
            "BRX without authenticated CBUF callback remains fail-closed");
    stable_cbuf.reads=0;
    stable_cbuf.mutate_between_reads=true;
    const auto racing_brx=CaptureNativeGraphicsShaderChecked(
        brx_memory.base,4,Read,&brx_memory,ReadCheckedCbuf,&stable_cbuf);
    Require(!racing_brx.Ready() && racing_brx.image.code.empty(),
            "CBUF remap between snapshot passes never publishes shader");
    stable_cbuf.mutate_between_reads=false;
    stable_cbuf.missing=true;
    const auto unmapped_brx=CaptureNativeGraphicsShaderChecked(
        brx_memory.base,4,Read,&brx_memory,ReadCheckedCbuf,&stable_cbuf);
    Require(!unmapped_brx.Ready() && unmapped_brx.image.code.empty(),
            "missing native CBUF bank prevents indirect shader publication");
    stable_cbuf.missing=false;
    stable_cbuf.throw_reader=true;
    const auto throwing_brx=CaptureNativeGraphicsShaderChecked(
        brx_memory.base,4,Read,&brx_memory,ReadCheckedCbuf,&stable_cbuf);
    Require(!throwing_brx.Ready() && throwing_brx.image.code.empty(),
            "throwing CBUF callback cannot escape GPU capture or expose partial image");
    stable_cbuf.throw_reader=false;
    // A shader rewrite after its initial read but before pipeline
    // publication must fail even if the checked CBUF table is unchanged.
    MutatingGpuRead modified_code{&brx_memory,brx_memory.base+0x80U,16U};
    const auto changed_shader=CaptureNativeGraphicsShaderChecked(
        brx_memory.base,4,ReadMutatingGpu,&modified_code,
        ReadCheckedCbuf,&stable_cbuf);
    Require(changed_shader.status==NativeCaptureStatus::TranslationFailed &&
            changed_shader.first_error_offset==0x80U &&
            changed_shader.image.code.empty() &&
            modified_code.watch_hits>=2,
            "BRX rechecks all native source words after CBUF resolution");
    MutatingGpuRead modified_header{&brx_memory,brx_memory.base,0x80U};
    const auto changed_header=CaptureNativeGraphicsShaderChecked(
        brx_memory.base,4,ReadMutatingGpu,&modified_header,
        ReadCheckedCbuf,&stable_cbuf);
    Require(changed_header.status==NativeCaptureStatus::TranslationFailed &&
            changed_header.image.code.empty() &&
            modified_header.watch_hits>=2,
            "BRX rechecks graphics SPH bytes before image publication");

    mem.data.resize(0x80);
    Push(mem.data,pred_true|0xfff);
    Push(mem.data,pred_true|0x94d,0,exit_true);
    mem.mapped_bytes=mem.data.size();
    auto unsupported=CaptureNativeGraphicsShader(mem.base,4,Read,&mem);
    Require(unsupported.status==NativeCaptureStatus::TranslationFailed &&
            unsupported.image.code.empty(),
            "unrecognized native opcodes fail closed after capture");

    mem.data.resize(0x80);
    for(u32 i=0;i<4096;++i) Push(mem.data,pred_true|0x918);
    mem.mapped_bytes=mem.data.size();
    auto unterminated=CaptureNativeGraphicsShader(mem.base,4,Read,&mem);
    Require(unterminated.status==NativeCaptureStatus::NoTerminator &&
            unterminated.captured_native_bytes==4096*16 &&
            unterminated.image.code.empty(),
            "bounded capture never invents a valid program without EXIT");
    Require(CaptureNativeGraphicsShader(mem.base,4,nullptr,&mem).status==
                NativeCaptureStatus::InvalidInput,
            "null memory reader must fail before any guest access");
    Require(CaptureNativeGraphicsShader(std::numeric_limits<u64>::max()-10,4,Read,&mem).status==
                NativeCaptureStatus::InvalidInput,
            "GPU address arithmetic overflow rejected before guest access");
    // A mapped long shader spans several 4 KiB GMMU pages. The coherent
    // reader should batch operations within each page without changing the
    // exact native instruction stream or consuming memory beyond termination.
    MappedMemory long_shader{};
    long_shader.base=0x200000;
    long_shader.data.resize(0x80);
    for (u32 index=0;index<512;++index)
        Push(long_shader.data,pred_true|0x918);
    Push(long_shader.data,pred_true|0x94d,0,exit_true);
    long_shader.mapped_bytes=long_shader.data.size();
    const auto long_result=CaptureNativeComputeShader(
        long_shader.base+0x80,Read,&long_shader);
    Require(long_result.Ready() &&
            long_result.captured_native_bytes==513*16 &&
            long_shader.reads < 20,
            "long native shaders use bounded coherent GPU page reads");
    // A reader that only accepts 16-byte accesses must still work exactly.
    long_shader.reads=0;
    long_shader.reject_batch=true;
    const auto non_batched=CaptureNativeComputeShader(
        long_shader.base+0x80,Read,&long_shader);
    Require(non_batched.Ready() &&
            non_batched.image.diagnostic_cache_key==
                long_result.image.diagnostic_cache_key &&
            long_shader.reads >= 513,
            "failed page prefetch falls back to exact mapped instruction reads");
    // A speculative 4-KiB batch reader may throw while an exact
    // 16-byte instruction reader remains valid. Retry the exact reads
    // rather than converting a valid shader into a false GPU mapping fault.
    long_shader.reject_batch=false;
    long_shader.throw_on_batch=true;
    long_shader.reads=0;
    const auto throwing_batch=CaptureNativeComputeShader(
        long_shader.base+0x80,Read,&long_shader);
    Require(throwing_batch.Ready() &&
            throwing_batch.image.diagnostic_cache_key==
                long_result.image.diagnostic_cache_key &&
            long_shader.reads>=513,
            "throwing prefetch falls back to exact per-instruction reads");
    long_shader.throw_on_batch=false;
    // Last instruction missing: the status and byte-accurate fault offset
    // must match the historical per-instruction implementation.
    long_shader.reject_batch=false;
    long_shader.reads=0;
    long_shader.mapped_bytes-=16;
    const auto end_fault=CaptureNativeComputeShader(
        long_shader.base+0x80,Read,&long_shader);
    Require(end_fault.status==NativeCaptureStatus::Unmapped &&
            end_fault.first_error_offset==512*16 &&
            end_fault.image.code.empty(),
            "partial final page returns the original unmapped shader offset");
    std::puts("NS2 mapped native shader capture: PASS (no PS5 game execution)");
}
