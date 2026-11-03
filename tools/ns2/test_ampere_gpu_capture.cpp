// SPDX-License-Identifier: GPL-3.0-or-later
// Synthetic mapped-memory fixture for the actual Ampere GPU shader capture.
// Does not execute GPU code or require access to copyrighted game images.
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
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
