#!/usr/bin/env python3
"""P1.2/P2.7: compile real shared GMMU walk and bounds prefixes under sanitizers.

The production PS5-safe DMA read, generic buffer I/O and guest cache flush
share MemoryManager::MemoryOperation. An invalid 40/49-bit GPU interval must
not touch a PTE; ReadBlock must zero-fill it, and cached writes must not
publish an invalid dirty interval. No NS1 valid-range behavior changes.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
source=(ROOT/'vendor/encore-active/eden-core/src/video_core/memory_manager.cpp').read_text()
pinned=(ROOT/'vendor/sources/eden/src/video_core/memory_manager.cpp').read_text()
start='template <typename FuncMapped, typename FuncReserved, typename FuncUnmapped>\ninline void MemoryManager::MemoryOperation('
end='\nvoid MemoryManager::ReadBlockImpl('
assert source.count(start)==source.count(end)==1
method=source[source.index(start):source.index(end)]
assert 'size > address_space_size - gpu_src_addr' in method
assert method.index('size > address_space_size - gpu_src_addr') < method.index('GetEntry(current_address, is_big_page)')
assert 'size > address_space_size - gpu_src_addr' not in pinned[pinned.index(start):pinned.index(end)]
read_signature='void MemoryManager::ReadBlockImpl(GPUVAddr gpu_src_addr, void* dest_buffer, std::size_t size, [[maybe_unused]] VideoCommon::CacheType which, bool unsafe) const {'
read_until='    auto set_to_zero ='
assert source.count(read_signature)==1
read_start=source.index(read_signature)
read_prefix=source[read_start:source.index(read_until,read_start)]
assert 'std::memset(dest_buffer, 0, size);' in read_prefix
write_signature='void MemoryManager::WriteBlockCached(GPUVAddr gpu_dest_addr, const void* src_buffer, std::size_t size) {'
write_until='    WriteBlockImpl(gpu_dest_addr'
assert source.count(write_signature)==1
write_start=source.index(write_signature)
write_prefix=source[write_start:source.index(write_until,write_start)]
assert 'size > address_space_size - gpu_dest_addr' in write_prefix
assert 'accumulator.Add(gpu_dest_addr, size);' in source[write_start:source.index('}\n',write_start)]

fixture='''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <functional>
#include <type_traits>
using u64=std::uint64_t;
using GPUVAddr=u64;
namespace VideoCommon { enum class CacheType {None}; }
class MemoryManager {
public:
    enum class EntryType {Mapped,Reserved,Unmapped};
    u64 address_space_size{1ULL<<40};
    static constexpr u64 page_bits=12,big_page_bits=16;
    static constexpr u64 page_size=1ULL<<page_bits,big_page_size=1ULL<<big_page_bits;
    static constexpr u64 page_mask=page_size-1,big_page_mask=big_page_size-1;
    mutable unsigned probes{},reads{};
    unsigned cached_writes{};
    EntryType GetEntry(GPUVAddr address,bool) const {
        ++probes;
        assert(address<address_space_size);
        return EntryType::Mapped;
    }
    template<typename FuncMapped,typename FuncReserved,typename FuncUnmapped>
    void MemoryOperation(GPUVAddr,std::size_t,bool,FuncMapped&&,FuncReserved&&,FuncUnmapped&&) const;
    void ReadBlockImpl(GPUVAddr,void*,std::size_t,VideoCommon::CacheType,bool) const;
    void WriteBlockCached(GPUVAddr,const void*,std::size_t);
};
'''+method+'\n'+read_prefix+'''    ++reads;
    std::memset(dest_buffer,0x7f,size);
}
'''+write_prefix+'''    ++cached_writes;
}
'''+r'''
int main() {
    for(unsigned va_bits:{40U,49U}) {
        MemoryManager m;
        m.address_space_size=u64{1}<<va_bits;
        const u64 limit=m.address_space_size;
        unsigned mapped=0;
        auto hit=[&](std::size_t,std::size_t,std::size_t){ ++mapped; };
        auto fail=[](std::size_t,std::size_t,std::size_t){ assert(false); };
        m.MemoryOperation(0x1000,4096,false,hit,fail,fail);
        assert(mapped==1 && m.probes==1);
        mapped=0;
        m.MemoryOperation(0xffc,8,false,hit,fail,fail);
        assert(mapped==2 && m.probes==3);
        mapped=0;
        m.MemoryOperation(limit-4,4,true,hit,fail,fail);
        assert(mapped==1 && m.probes==4);
        for (const auto [address,count]:std::array<std::pair<u64,u64>,6>{{
            {0,0},{limit-1,0},{limit,1},{limit+1,1},
            {limit-4,5},{~u64{0},32}}}) {
            const unsigned before=m.probes;
            mapped=0;
            m.MemoryOperation(address,count,true,hit,fail,fail);
            m.MemoryOperation(address,count,false,hit,fail,fail);
            assert(m.probes==before && mapped==0);
        }
        std::array<unsigned char,8> bytes{};
        bytes.fill(0xb7);
        m.ReadBlockImpl(limit-4,bytes.data(),8,VideoCommon::CacheType::None,false);
        assert(m.reads==0 && std::all_of(bytes.begin(),bytes.end(),[](unsigned char x){return x==0;}));
        bytes.fill(0xb7);
        m.ReadBlockImpl(~u64{0},bytes.data(),8,VideoCommon::CacheType::None,true);
        assert(m.reads==0 && std::all_of(bytes.begin(),bytes.end(),[](unsigned char x){return x==0;}));
        m.ReadBlockImpl(limit-8,bytes.data(),8,VideoCommon::CacheType::None,false);
        assert(m.reads==1 && bytes[0]==0x7f && bytes[7]==0x7f);
        const auto dirty_before=m.cached_writes;
        m.WriteBlockCached(limit-7,bytes.data(),8);
        m.WriteBlockCached(~u64{0},bytes.data(),8);
        m.WriteBlockCached(limit,bytes.data(),8);
        m.WriteBlockCached(limit-8,bytes.data(),0);
        assert(m.cached_writes==dirty_before);
        m.WriteBlockCached(limit-8,bytes.data(),8);
        assert(m.cached_writes==dirty_before+1);
    }
}
'''
compiler=shutil.which('clang++') or shutil.which('g++')
assert compiler, 'host compiler required'
env=dict(os.environ)
sdk=Path('/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk')
if sdk.is_dir():env['SDKROOT']=str(sdk)
with tempfile.TemporaryDirectory(prefix='encore-gmmu-walker-') as folder:
    unit=Path(folder)/'walker.cpp'
    unit.write_text(fixture)
    for level in (0,2):
        output=Path(folder)/f'walker-O{level}'
        command=[compiler,'-std=c++20',f'-O{level}','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                 '-fsanitize=address,undefined','-fno-sanitize-recover=all',
                 str(unit),'-o',str(output)]
        result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stderr[-4000:]
        result=subprocess.run([str(output)],env=env,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stderr[-4000:]
        print('P1_2_SHARED_GPU_WALKER_BOUNDS_PASS','O'+str(level),
              'VA=40/49','invalid_ranges=6','read_zero=2',
              'cached_write_guard=4','ASan_UBSan=pass')
