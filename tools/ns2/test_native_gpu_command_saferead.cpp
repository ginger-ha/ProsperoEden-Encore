// SPDX-License-Identifier: GPL-3.0-or-later
// P2.7: actual Eden GuestMemory<SafeRead> sees GPU-produced command words.
// This is a host fake device, not Vulkan/PS5. Both contiguous GPU backing
// and the fallback ReadBlock path must flush before presenting guest words.
#include <array>
#include <cassert>
#include <cstdint>
#include <cstring>
#include "common/common_types.h"
#include "core/guest_memory.h"

struct MockGpuMemory {
    static constexpr bool HAS_FLUSH_INVALIDATION = true;
    static constexpr u64 base = 0x50000U;
    std::array<u32,2> backing{0x11111111U,0x22222222U};
    std::array<u32,2> gpu_words{0xdeadbeefU,0xfeedfaceU};
    bool coherent{},contiguous{true};
    unsigned flush_count{},read_count{},unsafe_count{};

    u8* GetSpan(u64 address, std::size_t bytes) {
        if (!contiguous || address!=base || bytes!=sizeof(backing)) return nullptr;
        return reinterpret_cast<u8*>(backing.data());
    }
    void FlushRegion(u64 address, std::size_t bytes) {
        assert(address==base && bytes==sizeof(backing));
        ++flush_count;
        backing=gpu_words;
        coherent=true;
    }
    void ReadBlock(u64 address, void* destination, std::size_t bytes) {
        ++read_count;
        FlushRegion(address,bytes);
        std::memcpy(destination,backing.data(),bytes);
    }
    void ReadBlockUnsafe(u64 address, void* destination, std::size_t bytes) {
        assert(address==base && bytes==sizeof(backing));
        ++unsafe_count;
        std::memcpy(destination,backing.data(),bytes);
    }
};
int main() {
    using Core::Memory::GuestMemory;
    using Core::Memory::GuestMemoryFlags;
    for(bool contiguous:{true,false}) {
        MockGpuMemory memory{};
        memory.contiguous=contiguous;
        {
            GuestMemory<MockGpuMemory,u32,GuestMemoryFlags::UnsafeRead> unsafe(memory,memory.base,2);
            assert(unsafe.size()==2 && unsafe[0]==0x11111111U &&
                   unsafe[1]==0x22222222U && !memory.coherent && memory.flush_count==0);
        }
        {
            GuestMemory<MockGpuMemory,u32,GuestMemoryFlags::SafeRead> safe(memory,memory.base,2);
            assert(safe.size()==2 && safe[0]==0xdeadbeefU &&
                   safe[1]==0xfeedfaceU && memory.coherent && memory.flush_count==1);
        }
        assert(memory.read_count==(contiguous?0U:1U));
        assert(memory.unsafe_count==(contiguous?0U:1U));
    }
}
