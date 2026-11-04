// SPDX-License-Identifier: GPL-3.0-or-later
#include <cassert>
#include <initializer_list>
#include <cstdint>
#include "video_core/native_graphics_cbuf_bounds.h"
int main() {
    using VideoCommon::NativeGraphicsCbufWordAdmissible;
    constexpr std::uint64_t limit = std::uint64_t{1} << 49;
    static_assert(NativeGraphicsCbufWordAdmissible(true, 0x1000,4,0));
    static_assert(NativeGraphicsCbufWordAdmissible(true, 0x1000,0x10000,0xfffc));
    static_assert(NativeGraphicsCbufWordAdmissible(true, limit-4,4,0));
    static_assert(!NativeGraphicsCbufWordAdmissible(true, limit-2,4,0));
    static_assert(!NativeGraphicsCbufWordAdmissible(true, limit,4,0));
    static_assert(!NativeGraphicsCbufWordAdmissible(true,0,0x10000,0));
    static_assert(!NativeGraphicsCbufWordAdmissible(true,0x1000,0x20000,0x10000));
    static_assert(!NativeGraphicsCbufWordAdmissible(true,0x1000,0x10000,0xffff));
    static_assert(!NativeGraphicsCbufWordAdmissible(true,0x1000,0x10000,1));
    static_assert(!NativeGraphicsCbufWordAdmissible(false,0x1000,0x10000,0));
    static_assert(!NativeGraphicsCbufWordAdmissible(true,0x1000,3,0));
    static_assert(!NativeGraphicsCbufWordAdmissible(true,0x1000,4,4));
    for (const std::uint64_t limit_size: {0U, 1U, 3U, 4U, 16U, 0x10000U, 0x20000U}) {
        for (std::uint32_t offset=0; offset<=0x10004; ++offset) {
            const bool permitted=NativeGraphicsCbufWordAdmissible(true,0x1000,limit_size,offset);
            const bool oracle=offset%4==0 && offset<=0xfffc &&
                limit_size>=4 && offset<=limit_size-4;
            assert(permitted==oracle);
        }
    }
}
