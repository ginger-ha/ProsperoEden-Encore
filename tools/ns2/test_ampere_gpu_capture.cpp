// SPDX-License-Identifier: GPL-3.0-or-later
// Synthetic mapped-memory fixture for the actual Ampere GPU shader capture.
// Does not execute GPU code or require access to copyrighted game images.
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <vector>
#include "shader_recompiler/frontend/ampere/capture.h"
#include "shader_recompiler/stage.h"

using namespace Shader::Ampere;
struct MappedMemory {
    u64 base{0x100000};
    std::vector<u8> data;
    std::size_t mapped_bytes{};
    u32 reads{};
    bool reject_batch{};
};
static bool Read(void* opaque, u64 address, void* destination, std::size_t size) {
    auto& mem = *static_cast<MappedMemory*>(opaque);
    ++mem.reads;
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
    mem.mapped_bytes=0x80+16;
    const auto compute_fault=CaptureNativeComputeShader(mem.base+0x80,Read,&mem);
    Require(compute_fault.status==NativeCaptureStatus::Unmapped &&
            compute_fault.first_error_offset==16 &&
            compute_fault.image.code.empty(),
            "compute second instruction unmapped rejects with code-relative offset");
    mem.mapped_bytes=mem.data.size();
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
