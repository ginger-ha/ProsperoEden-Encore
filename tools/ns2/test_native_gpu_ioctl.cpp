// SPDX-License-Identifier: GPL-3.0-or-later
// Strict synthetic NVDRV reply fixtures. Tests the exact helper used by
// the experimental nvhost_ctrl_gpu.cpp owner; no physical NVIDIA GPU needed.
#include <array>
#include <cassert>
#include <cstring>
#include <cstdint>
#include <limits>
#include <span>
#include <iostream>
#include "core/hle/service/nvdrv/devices/native_characteristics_ioctl.h"

using namespace Service::Nvidia::Devices;
static u32 le32(const u8* p) {
    return u32{p[0]} | (u32{p[1]}<<8) | (u32{p[2]}<<16) | (u32{p[3]}<<24);
}
static u64 le64(const u8* p) {
    return u64{le32(p)} | (u64{le32(p+4)}<<32);
}
int main() {
    std::array<u8, 0xa0> legacy{};
    legacy[0x34]=0x00; legacy[0x35]=0x00; legacy[0x36]=0x03;
    legacy[0x50]=0x55;
    for (const auto [raw,size,sm,channel] :
         {std::array<u32,4>{0xc0e04705,0xd0,0x808,0x1d},
          std::array<u32,4>{0xc0e84705,0xd8,0x808,0x1f}}) {
        std::array<u8, 0x110> input{},output{},inline_output{};
        input.fill(0xab);output.fill(0xcd);inline_output.fill(0xef);
        const auto packet_size=size+0x10;
        auto st=WriteNativeCharacteristicsIoctlReply(raw,
            std::span<const u8>(input.data(),packet_size),
            std::span<u8>(output.data(),packet_size+2),
            std::span<u8>(inline_output.data(),size+2),legacy);
        assert(st==NativeCharacteristicsIoctlStatus::Success);
        assert(le64(output.data())==size);
        assert(le32(output.data()+0x10)==0x170);
        assert(le32(output.data()+0x14)==0xe);
        assert(le32(output.data()+0x10+0x3c)==sm);
        assert(le32(output.data()+0x10+0x40)==sm);
        assert(le32(output.data()+0x10+0x28)==0x1000);
        // Never publish NS1 Maxwell engine classes in native GPU replies.
        assert(le32(output.data()+0x10+0x5c)==0xc797);
        assert(le32(output.data()+0x10+0x60)==0xc7c0);
        assert(le32(output.data()+0x10+0x64)==0xc56f);
        assert(le32(output.data()+0x10+0x6c)==0xc7b5);
        assert((le64(output.data()+0x10+0x50)&((1ULL<<8)|(1ULL<<22)))==
               ((1ULL<<8)|(1ULL<<22)));
        assert(le32(output.data()+0x10+0xb4)==64);
        assert((le32(output.data()+0x10+0x76)&0xffffU)==channel);
        assert(std::memcmp(output.data()+0x10,inline_output.data(),size)==0);
        assert(output[packet_size]==0xcd && output[packet_size+1]==0xcd);
        assert(inline_output[size]==0xef && inline_output[size+1]==0xef);
        // Truncated in/out/inline buffers: reject WITHOUT mutating outputs.
        for(int which=0;which<3;++which){
            output.fill(0xcd);inline_output.fill(0xef);
            const auto ib=which==0?packet_size-1:packet_size;
            const auto ob=which==1?packet_size-1:packet_size;
            const auto il=which==2?size-1:size;
            st=WriteNativeCharacteristicsIoctlReply(raw,
                std::span<const u8>(input.data(),ib),
                std::span<u8>(output.data(),ob),
                std::span<u8>(inline_output.data(),il),legacy);
            assert(st==NativeCharacteristicsIoctlStatus::BadParameter);
            assert(output[0]==0xcd && inline_output[0]==0xef);
        }
        output.fill(0xcd);inline_output.fill(0xef);
        st=WriteNativeCharacteristicsIoctlReply(0xc0a04705,
            input,output,inline_output,legacy);
        assert(st==NativeCharacteristicsIoctlStatus::NotNative);
        assert(output[0]==0xcd && inline_output[0]==0xef);
    }
    std::cout<<"NS2 native GPU ioctl packet validation: PASS\n";
}
