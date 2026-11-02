// SPDX-License-Identifier: GPL-3.0-or-later
// Host-only Ampere -> real Maxwell CFG -> optimized IR -> SPIR-V emission.
// Synthetic shader only; not a Vulkan pipeline or a PS5 execution test.
#include <array>
#include <algorithm>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <string>
#include <vector>
#define CANNOT_EXPLICITLY_INSTANTIATE
#include "common/settings.h"
#include "shader_recompiler/frontend/ampere/renderer_spirv_bridge.h"
#include "shader_recompiler/frontend/ampere/native_qmd_compute_environment.h"
#include "video_core/ns2_shader_spirv_compile.h"
#include "core/hle/service/nvdrv/devices/native_gpu_process_registry.h"
#include "shader_recompiler/frontend/ampere/ir_bridge.h"
#include "shader_recompiler/host_translate_info.h"
#include "shader_recompiler/profile.h"
#include "shader_recompiler/runtime_info.h"

namespace Settings { Values values{}; }
using namespace Shader::Ampere;
static void Require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "NS2 SPIR-V: %s\n", why); std::exit(1); }
}
struct SyntheticSource final : Shader::Environment {
    explicit SyntheticSource(Shader::Stage stage_=Shader::Stage::VertexB) { stage=stage_; start_address=0; }
    u64 ReadInstruction(u32) override { std::abort(); }
    u32 ReadCbufValue(u32,u32) override { return 0; }
    Shader::TextureType ReadTextureType(u32) override { return {}; }
    Shader::TexturePixelFormat ReadTexturePixelFormat(u32) override { return {}; }
    bool IsTexturePixelFormatInteger(u32) override { return false; }
    u32 ReadViewportTransformState() override { return 0; }
    u32 TextureBoundBuffer() const override { return 0; }
    u32 LocalMemorySize() const override { return 0; }
    u32 SharedMemorySize() const override { return 0; }
    std::array<u32,3> WorkgroupSize() const override {
        return stage == Shader::Stage::Compute ?
            std::array<u32,3>{2,4,8} : std::array<u32,3>{};
    }
    bool HasHLEMacroState() const override { return false; }
    std::optional<Shader::ReplaceConstant> GetReplaceConstBuffer(u32,u32) override { return {}; }
    void Dump(u64,u64) override { std::abort(); }
};
static void Emit(std::vector<u8>& out,u32 a,u32 b=0,u32 c=0,u32 d=0) {
    for (u32 w:{a,b,c,d})
        for (u32 shift=0;shift<32;shift+=8) out.push_back(static_cast<u8>(w>>shift));
}
namespace Kernel { class KProcess {}; }
namespace VideoCommon {
// Host-only link stand-in for the real GMMU reader. The actual compiled
// integration test below directly supplies a bounded fake guest reader.
bool ReadNs2GpuShader(void*, u64, void*, std::size_t) { return false; }
}
struct GuestFixture {
    std::vector<u8> bytes;
    u64 address{0x100000};
    std::size_t reads{};
    Kernel::KProcess* unregister_on_read{};
};
static bool ReadGuest(void* ptr,u64 address,void* output,std::size_t count) {
    auto& fixture=*static_cast<GuestFixture*>(ptr);
    ++fixture.reads;
    if (address<fixture.address) return false;
    const u64 offset=address-fixture.address;
    if (offset>fixture.bytes.size() || count>fixture.bytes.size()-offset)
        return false;
    std::memcpy(output,fixture.bytes.data()+offset,count);
    if (fixture.unregister_on_read) {
        auto* process=fixture.unregister_on_read;
        fixture.unregister_on_read=nullptr;
        Service::Nvidia::Devices::NativeGpuProcessRegistry::Instance().Unregister(process);
    }
    return true;
}
int main(int argc,char** argv) {
    Require(argc==2,"missing output prefix");
    std::array<u8,0x50> header{};
    constexpr u32 pred=7U<<12,exit_true=7U<<23;
    std::vector<u8> code;
    Emit(code,pred|0x918);
    Emit(code,pred|0x202|(1U<<16),2,15U<<8);
    Emit(code,pred|0x918);
    Emit(code,pred|0x918);
    Emit(code,pred|0x94d,0,exit_true);
    auto image=BuildMaxwellShaderImage(header,code,static_cast<u32>(Shader::Stage::VertexB));
    Require(image.ValidForCompiler(),"verified native shader image absent");
    auto env=NativeMaxwellEnvironment::CreateOwned(std::make_unique<SyntheticSource>(),std::move(image));
    Require(bool(env),"owned environment creation failed");
    Shader::HostTranslateInfo host{};
    host.min_ssbo_alignment=64;
    host.support_float64=true;
    host.support_float16=true;
    host.support_int64=true;
    host.support_conditional_barrier=true;
    Shader::Profile profile{};
    profile.supported_spirv=0x00010500; // SPIR-V 1.5
    // Emit an authentic Compute execution model from the same synthetic
    // 128-bit Ampere instruction sequence, without a graphics SPH.
    auto compute_image=BuildMaxwellShaderImage(
        header,code,static_cast<u32>(Shader::Stage::Compute));
    Require(compute_image.ValidForCompiler(),"compute native lowering invalid");
    auto compute_env=NativeMaxwellEnvironment::CreateComputeOwned(
        std::make_unique<SyntheticSource>(Shader::Stage::Compute),
        std::move(compute_image));
    Require(bool(compute_env) && compute_env->StartAddress()==0x50,
            "compute translation environment rejected");
    const auto compute=CompileReviewedNativeComputeSpirv(
        *compute_env,host,profile,Shader::RuntimeInfo{});
    Require(compute.ComputeMetadataReady() &&
            !compute.PipelineMetadataReady() &&
            compute.words.size()>5 && compute.words[0]==0x07230203U,
            "Ampere Compute CFG/IR -> actual SPIR-V failed");
    {
        const auto output=std::string(argv[1])+"-compute.spv";
        std::ofstream file{output,std::ios::binary|std::ios::trunc};
        Require(bool(file),"cannot write Compute SPIR-V");
        file.write(reinterpret_cast<const char*>(compute.words.data()),
                   static_cast<std::streamsize>(compute.words.size()*sizeof(u32)));
        file.close();
        Require(bool(file),"could not flush Compute SPIR-V");
        std::printf("SPIR-V emitted: %s (%zu words)\\n",
                    output.c_str(),compute.words.size());
    }
    // Exercise the production-facing QMD3 metadata environment with the
    // ACTUAL reviewed Maxwell CFG/IR/SPIR-V compiler. The earlier synthetic
    // source has no native 49-bit CBUF metadata, so it cannot prove this ABI.
    Tegra::NativeQmdScheduler::Descriptor native_qmd{};
    native_qmd[8]=0x80;
    native_qmd[12]=3; native_qmd[13]=4; native_qmd[14]=5;
    native_qmd[18]=0x30U | (2U<<16);
    native_qmd[19]=4U | (8U<<16);
    native_qmd[20]=1U; // Enabled CBUF0.
    native_qmd[32]=0x12340000U;
    native_qmd[33]=0x10000U | (1U<<19); // GPU VA above 40 bits, 16 bytes.
    native_qmd[48]=0x100000U; native_qmd[49]=0x10000U;
    const auto launch=Tegra::DecodeNativeComputeLaunch(native_qmd);
    Require(launch && launch->constant_buffers[0].gpu_address==0x1000012340000ULL,
            "QMD3 Compute compiler lost native CBUF upper address bits");
    GuestFixture cbuf_guest{};
    cbuf_guest.address=launch->constant_buffers[0].gpu_address;
    cbuf_guest.bytes.resize(16);
    cbuf_guest.bytes[0]=0x78; cbuf_guest.bytes[1]=0x56;
    cbuf_guest.bytes[2]=0x34; cbuf_guest.bytes[3]=0x12;
    auto native_qmd_context=std::make_unique<NativeQmdComputeEnvironment>(
        *launch,ReadGuest,&cbuf_guest,
        std::make_unique<SyntheticSource>(Shader::Stage::Compute));
    Require(native_qmd_context->ReadCbufValue(0,0)==0x12345678 &&
            (native_qmd_context->WorkgroupSize()==std::array<u32,3>{2,4,8}),
            "real QMD context must provide 49-bit mapped CBUF and workgroups");
    auto qmd_image=BuildMaxwellShaderImage(
        header,code,static_cast<u32>(Shader::Stage::Compute));
    auto qmd_compiler_env=NativeMaxwellEnvironment::CreateComputeOwned(
        std::move(native_qmd_context),std::move(qmd_image));
    Require(bool(qmd_compiler_env) && qmd_compiler_env->StartAddress()==0x50,
            "native QMD environment did not enter compiler CFG");
    const auto real_qmd_spirv=CompileReviewedNativeComputeSpirv(
        *qmd_compiler_env,host,profile,Shader::RuntimeInfo{});
    Require(real_qmd_spirv.ComputeMetadataReady() &&
            real_qmd_spirv.words.size()>5 &&
            real_qmd_spirv.words[0]==0x07230203U,
            "native QMD3 metadata failed real Ampere IR/SPIR-V emission");
    // Distinct workgroups, CB metadata and program ownership must be carried
    // through this real compiler; no guest execution is asserted here.
    std::vector<u32> baseline_direct;
    for (bool dispatcher:{false,true}) {
        const auto compiled=CompileReviewedNativeVertexSpirv(
            *env,host,profile,Shader::RuntimeInfo{},dispatcher);
        Require(compiled.PipelineMetadataReady() && compiled.stage == Shader::Stage::VertexB,
                "native VertexB shader must return pipeline Info and stage");
        const auto& words=compiled.words;
        if (!dispatcher) baseline_direct=words;
        Require(words.size()>5&&words[0]==0x07230203U,"missing SPIR-V magic");
        Require(words[1]==profile.supported_spirv&&words[3]>0,"bad version or ID bound");
        const auto output=std::string(argv[1])+(dispatcher?"-dispatcher.spv":"-direct.spv");
        std::ofstream file{output,std::ios::binary|std::ios::trunc};
        Require(bool(file),"cannot create validation file");
        file.write(reinterpret_cast<const char*>(words.data()),
                   static_cast<std::streamsize>(words.size()*sizeof(u32)));
        file.close();
        Require(bool(file),"cannot flush complete SPIR-V");
        std::printf("SPIR-V emitted: %s (%zu words)\n",output.c_str(),words.size());
    }
    // Compile an actual native Fragment stage through Maxwell IR and Sirit.
    // The explicit stage-aware path must emit a real Fragment execution model;
    // it must not relabel the old VertexB module as Fragment.
    auto fragment_image=BuildMaxwellShaderImage(
        header,code,static_cast<u32>(Shader::Stage::Fragment));
    Require(fragment_image.ValidForCompiler(),"fragment shader lowering invalid");
    auto fragment_env=NativeMaxwellEnvironment::CreateOwned(
        std::make_unique<SyntheticSource>(Shader::Stage::Fragment),
        std::move(fragment_image));
    Require(bool(fragment_env),"fragment source ownership rejected");
    const auto fragment_via_legacy=CompileReviewedNativeVertexSpirv(
        *fragment_env,host,profile,Shader::RuntimeInfo{});
    Require(fragment_via_legacy.status==NativeSpirvStatus::UnsupportedStage &&
            fragment_via_legacy.words.empty(),
            "legacy VertexB API must reject a real Fragment stage");
    const auto fragment=CompileReviewedNativeGraphicsSpirv(
        *fragment_env,host,profile,Shader::RuntimeInfo{});
    Require(fragment.PipelineMetadataReady() && fragment.stage == Shader::Stage::Fragment &&
            fragment.words.size()>5 &&
            fragment.words[0]==0x07230203U && fragment.words[3]!=0,
            "stage-aware native Fragment SPIR-V emission failed");
    {
        const auto output=std::string(argv[1])+"-fragment.spv";
        std::ofstream file{output,std::ios::binary|std::ios::trunc};
        Require(bool(file),"cannot write Fragment SPIR-V");
        file.write(reinterpret_cast<const char*>(fragment.words.data()),
                   static_cast<std::streamsize>(fragment.words.size()*sizeof(u32)));
        file.close();
        Require(bool(file),"could not flush actual Fragment SPIR-V");
    }
    // The VertexA program must run before VertexB, exactly as in the real
    // maintained Vulkan pipeline's MergeDualVertexPrograms call.
    auto merge_a=BuildMaxwellShaderImage(
        header,code,static_cast<u32>(Shader::Stage::VertexA));
    auto merge_b=BuildMaxwellShaderImage(
        header,code,static_cast<u32>(Shader::Stage::VertexB));
    auto merge_env_a=NativeMaxwellEnvironment::CreateOwned(
        std::make_unique<SyntheticSource>(Shader::Stage::VertexA),std::move(merge_a));
    auto merge_env_b=NativeMaxwellEnvironment::CreateOwned(
        std::make_unique<SyntheticSource>(Shader::Stage::VertexB),std::move(merge_b));
    Require(merge_env_a && merge_env_b,
            "both native vertex stages need owned Maxwell environments");
    const auto merged=CompileReviewedNativeMergedVertexSpirv(
        *merge_env_a,*merge_env_b,host,profile,Shader::RuntimeInfo{});
    Require(merged.PipelineMetadataReady() && merged.stage == Shader::Stage::VertexB &&
            merged.words.size()>5 &&
            merged.words[0]==0x07230203U && merged.words[3]!=0,
            "real VertexA+VertexB Maxwell merge SPIR-V emission failed");
    {
        const auto output=std::string(argv[1])+"-merged.spv";
        std::ofstream file{output,std::ios::binary|std::ios::trunc};
        Require(bool(file),"cannot write merged vertex SPIR-V");
        file.write(reinterpret_cast<const char*>(merged.words.data()),
                   static_cast<std::streamsize>(merged.words.size()*sizeof(u32)));
        file.close();Require(bool(file),"could not flush merged native vertex SPIR-V");
    }
    // Native stages must share the same descriptor binding sequence as the
    // maintained Vulkan graphics pipeline; each stage may not restart at 0.
    Shader::Backend::Bindings initial_bindings{};
    initial_bindings.uniform_buffer = 3;
    initial_bindings.texture = 11;
    const auto chained_vertex = CompileReviewedNativeMergedVertexSpirv(
        *merge_env_a,*merge_env_b,host,profile,Shader::RuntimeInfo{},initial_bindings);
    Require(chained_vertex.PipelineMetadataReady() &&
            chained_vertex.next_bindings.uniform_buffer >= initial_bindings.uniform_buffer &&
            chained_vertex.next_bindings.texture >= initial_bindings.texture,
            "native merged vertex pipeline lost the incoming binding seed");
    const auto chained_fragment = CompileReviewedNativeGraphicsSpirv(
        *fragment_env,host,profile,Shader::RuntimeInfo{},false,
        chained_vertex.next_bindings);
    Require(chained_fragment.PipelineMetadataReady() &&
            chained_fragment.stage == Shader::Stage::Fragment &&
            chained_fragment.next_bindings.uniform_buffer >= chained_vertex.next_bindings.uniform_buffer &&
            chained_fragment.next_bindings.texture >= chained_vertex.next_bindings.texture,
            "native graphics stages lost their cumulative Vulkan descriptor bindings");
    const auto rejected_merge=CompileReviewedNativeMergedVertexSpirv(
        *merge_env_b,*merge_env_a,host,profile,Shader::RuntimeInfo{});
    Require(rejected_merge.status==NativeSpirvStatus::UnsupportedStage &&
            rejected_merge.words.empty(),
            "swapped native vertex stages must never generate a module");
    auto vertex_a_image=BuildMaxwellShaderImage(
        header,code,static_cast<u32>(Shader::Stage::VertexA));
    Require(vertex_a_image.ValidForCompiler(),"VertexA negative fixture failed");
    auto vertex_a_env=NativeMaxwellEnvironment::CreateOwned(
        std::make_unique<SyntheticSource>(Shader::Stage::VertexA),
        std::move(vertex_a_image));
    Require(bool(vertex_a_env),"VertexA environment must exist before stage gate");
    const auto rejected=CompileReviewedNativeVertexSpirv(
        *vertex_a_env,host,profile,Shader::RuntimeInfo{});
    Require(rejected.status==NativeSpirvStatus::UnsupportedStage &&
            rejected.words.empty(),"unmerged VertexA must fail closed");
    auto& registry=Service::Nvidia::Devices::NativeGpuProcessRegistry::Instance();
    Kernel::KProcess process{};
    GuestFixture guest{};
    guest.bytes.resize(0x1000+0x80+code.size());
    std::copy(header.begin(),header.end(),guest.bytes.begin());
    std::copy(code.begin(),code.end(),guest.bytes.begin()+0x80);
    std::copy(header.begin(),header.end(),guest.bytes.begin()+0x1000);
    std::copy(code.begin(),code.end(),guest.bytes.begin()+0x1000+0x80);
    auto compile=[&](Shader::Stage stage,bool dispatcher=false) {
        return VideoCommon::CompileCapturedNs2VertexSpirvFromReader(
            &process,std::make_unique<SyntheticSource>(stage),
            guest.address,ReadGuest,&guest,host,profile,Shader::RuntimeInfo{},
            nullptr,dispatcher);
    };
    const auto missing=compile(Shader::Stage::VertexB);
    Require(missing.status==NativeSpirvStatus::InactiveSession &&
            missing.words.empty() && guest.reads==0,
            "unregistered process must not access guest GPU memory");
    Require(registry.Register(&process),"failed creating NS2 session fixture");
    // The explicit session-owned Compute API reads only code bytes, not a
    // shader graphics header. Reject unrelated stages before GMMU access.
    guest.reads=0;
    const auto wrong_compute_stage=VideoCommon::CompileCapturedNs2ComputeSpirvFromReader(
        &process,std::make_unique<SyntheticSource>(Shader::Stage::VertexB),
        guest.address+0x80,ReadGuest,&guest,host,profile,Shader::RuntimeInfo{});
    Require(wrong_compute_stage.status==NativeSpirvStatus::UnsupportedStage &&
            wrong_compute_stage.words.empty() && guest.reads==0,
            "QMD Compute compiler must reject graphics stages before GMMU read");
    const auto session_compute=VideoCommon::CompileCapturedNs2ComputeSpirvFromReader(
        &process,std::make_unique<SyntheticSource>(Shader::Stage::Compute),
        guest.address+0x80,ReadGuest,&guest,host,profile,Shader::RuntimeInfo{});
    Require(session_compute.ComputeMetadataReady() &&
            session_compute.words==compute.words && guest.reads>0,
            "QMD-owned compute capture did not compile identical SPIR-V");
    // The existing graphics-stage isolation tests must begin with a clean
    // guest read counter; the Compute test intentionally performed real reads.
    guest.reads=0;
    const auto token=registry.CaptureTicket(&process);
    Require(token.has_value(),"no live NS2 GPU ticket");
    const auto no_vertex_a=compile(Shader::Stage::VertexA);
    Require(no_vertex_a.status==NativeSpirvStatus::UnsupportedStage &&
            no_vertex_a.words.empty() && guest.reads==0,
            "unmerged VertexA must reject without GMMU reads");
    const auto fragment_legacy=compile(Shader::Stage::Fragment);
    Require(fragment_legacy.status==NativeSpirvStatus::UnsupportedStage &&
            fragment_legacy.words.empty() && guest.reads==0,
            "legacy vertex session API must reject Fragment before GMMU read");
    const auto fragment_capture=VideoCommon::CompileCapturedNs2GraphicsSpirvFromReader(
        &process,std::make_unique<SyntheticSource>(Shader::Stage::Fragment),
        guest.address,ReadGuest,&guest,host,profile,Shader::RuntimeInfo{});
    Require(fragment_capture.PipelineMetadataReady() &&
            fragment_capture.words==fragment.words,
            "authenticated Fragment capture must compile the same SPIR-V module");
    guest.reads=0;
    const auto seeded_guest_fragment=VideoCommon::CompileCapturedNs2GraphicsSpirvFromReader(
        &process,std::make_unique<SyntheticSource>(Shader::Stage::Fragment),
        guest.address,ReadGuest,&guest,host,profile,Shader::RuntimeInfo{},
        nullptr,false,chained_vertex.next_bindings);
    Require(seeded_guest_fragment.PipelineMetadataReady() &&
            seeded_guest_fragment.stage == Shader::Stage::Fragment &&
            seeded_guest_fragment.next_bindings.uniform_buffer >= chained_vertex.next_bindings.uniform_buffer &&
            seeded_guest_fragment.next_bindings.texture >= chained_vertex.next_bindings.texture &&
            guest.reads>0,
            "authenticated GPU capture failed to propagate graphics binding seed");
    guest.reads=0;
    const auto merged_capture=VideoCommon::CompileCapturedNs2MergedVertexSpirvFromReader(
        &process,std::make_unique<SyntheticSource>(Shader::Stage::VertexA),
        std::make_unique<SyntheticSource>(Shader::Stage::VertexB),
        guest.address,guest.address+0x1000,ReadGuest,&guest,
        host,profile,Shader::RuntimeInfo{});
    Require(merged_capture.PipelineMetadataReady() && merged_capture.words==merged.words,
            "same-process native VertexA/B capture must match real merged IR/SPIR-V");
    const auto rejected_pair=VideoCommon::CompileCapturedNs2MergedVertexSpirvFromReader(
        &process,std::make_unique<SyntheticSource>(Shader::Stage::VertexA),
        std::make_unique<SyntheticSource>(Shader::Stage::VertexB),
        guest.address,guest.address,ReadGuest,&guest,
        host,profile,Shader::RuntimeInfo{});
    Require(rejected_pair.status==NativeSpirvStatus::UnsupportedStage &&
            rejected_pair.words.empty(),
            "ambiguous same-address native dual vertex pair must reject");
    const auto complete=compile(Shader::Stage::VertexB);
    Require(complete.PipelineMetadataReady() && complete.words==baseline_direct && guest.reads>0,
            "registered guest shader capture must match real Maxwell SPIR-V");
    guest.reads=0;
    guest.unregister_on_read=&process;
    const auto torn_down=compile(Shader::Stage::VertexB);
    Require(torn_down.status==NativeSpirvStatus::InactiveSession &&
            torn_down.words.empty() && guest.reads>0,
            "session teardown during shader capture must not publish SPIR-V");
    Require(!registry.IsCurrent(*token),"closed session ticket still authorized");
    Require(registry.Register(&process),"failed reopening NS2 session");
    const auto reopened=registry.CaptureTicket(&process);
    Require(reopened && reopened->generation!=token->generation &&
            !registry.IsCurrent(*token),"reopened session reused old ticket");
    const auto after_reopen=compile(Shader::Stage::VertexB,true);
    Require(after_reopen.Ready(),"reopened authenticated session must compile");
    registry.Unregister(&process);
    Require(registry.Count()==0,"test session leaked");
    std::puts("NS2 verified GMMU reader -> Maxwell IR -> SPIR-V: PASS "
              "(no-session/VertexA reject, mid-capture teardown, reopen)");
    std::puts("NS2 real SPIR-V emitter PASS (host-only; Vulkan and PS5 not executed)");
}
