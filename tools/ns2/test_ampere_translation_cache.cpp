// SPDX-License-Identifier: GPL-3.0-or-later
// Tests the real lowerer under a bounded, explicitly owned NS2 cache.
// All programs are synthetic, no user keys/ROMs or PS5 game execution.
#include <array>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "shader_recompiler/frontend/ampere/capture.h"
#include "shader_recompiler/frontend/ampere/translation_cache.h"

using namespace Shader::Ampere;

static void Check(bool ok, const char* why) {
    if (!ok) {
        std::fprintf(stderr, "NS2 native translation cache: FAIL %s\n", why);
        std::exit(1);
    }
}
static void Emit(std::vector<u8>& dst, u32 a, u32 b=0, u32 c=0, u32 d=0) {
    for (u32 word : {a,b,c,d})
        for (u32 shift=0;shift!=32;shift+=8)
            dst.push_back(static_cast<u8>(word >> shift));
}
struct Reader {
    u64 base{0x200000};
    std::vector<u8> bytes{};
    std::size_t mapped{};
    unsigned reads{};
};
static bool Read(void* opaque,u64 addr,void* dst,std::size_t size){
    auto& r=*static_cast<Reader*>(opaque);
    ++r.reads;
    if (addr<r.base || !dst || !size) return false;
    const u64 off=addr-r.base;
    if(off>r.mapped || size>r.mapped-off) return false;
    if(off>r.bytes.size() || size>r.bytes.size()-off) return false;
    std::memcpy(dst,r.bytes.data()+off,size);
    return true;
}
int main() {
    constexpr u32 pt=7u<<12, exit_true=7u<<23;
    std::array<u8,0x50> header{};
    std::vector<u8> program;
    Emit(program,pt|0x918); // NOP
    Emit(program,pt|0x94d,0,exit_true); // EXIT
    NativeTranslationCache cache{1024*1024,2};
    auto one=cache.GetOrTranslate(header,program,4);
    auto two=cache.GetOrTranslate(header,program,4);
    auto st=cache.Stats();
    Check(one.Ready() && two.Ready() && one.code==two.code &&
          st.misses==1 && st.translations==1 && st.hits==1 &&
          st.entries==1 && st.bytes>0,
          "identical full shader content reuses genuine translated image");

    header[0]^=1;
    auto modified_header=cache.GetOrTranslate(header,program,4);
    Check(modified_header.Ready() &&
          modified_header.diagnostic_cache_key!=one.diagnostic_cache_key &&
          cache.Stats().translations==2,
          "changed header cannot reuse stale translation");
    header[0]^=1;
    auto other_stage=cache.GetOrTranslate(header,program,5);
    Check(other_stage.Ready() && cache.Stats().entries==2 &&
          cache.Stats().evictions==1 &&
          other_stage.diagnostic_cache_key!=one.diagnostic_cache_key,
          "stage identity is isolated and bounded LRU evicts oldest");
    auto return_one=cache.GetOrTranslate(header,program,4);
    Check(return_one.Ready() && cache.Stats().translations==4 &&
          cache.Stats().evictions==2,
          "evicted program is retranslated, not resurrected");

    auto invalid=program;
    invalid.pop_back();
    Check(!cache.GetOrTranslate(header,invalid,4).Ready() &&
          cache.Stats().entries==2,
          "malformed native bytes never poison cache");
    auto no_exit=program;
    no_exit.resize(16);
    Check(!cache.GetOrTranslate(header,no_exit,4).Ready() &&
          cache.Stats().entries==2,
          "no-EXIT program does not produce a successful partial entry");
    const auto first_rejected = cache.Stats();
    Check(!cache.GetOrTranslate(header,no_exit,4).Ready() &&
          cache.Stats().translations == first_rejected.translations &&
          cache.Stats().negative_hits == first_rejected.negative_hits + 1,
          "unchanged rejected native shader must hit bounded negative cache");
    no_exit[0] ^= 1;
    Check(!cache.GetOrTranslate(header,no_exit,4).Ready() &&
          cache.Stats().translations == first_rejected.translations + 1,
          "changed native shader bytes must not reuse a previous rejection");

    Reader r;
    r.bytes.resize(0x80);
    Emit(r.bytes,pt|0x918);
    Emit(r.bytes,pt|0x94d,0,exit_true);
    r.mapped=r.bytes.size();
    NativeTranslationCache live{1024*1024,3};
    auto from_guest=CaptureNativeGraphicsShader(r.base,4,Read,&r,&live);
    const unsigned initial_reads=r.reads;
    auto from_guest_again=CaptureNativeGraphicsShader(r.base,4,Read,&r,&live);
    Check(from_guest.Ready() && from_guest_again.Ready() &&
          live.Stats().hits==1 && live.Stats().translations==1 &&
          r.reads==initial_reads+3,
          "cache reuse still validates and reads live GMMU guest bytes");

    // Rewrite the mapped instruction at the SAME GPU address: the cache
    // must see different bytes, not address-based false freshness.
    r.bytes[0x80]=0x02; r.bytes[0x81]=0x72; // MOV, predicate true + R1
    r.bytes[0x82]=0x01; r.bytes[0x84]=0x02; r.bytes[0x89]=0x0f;
    auto changed=CaptureNativeGraphicsShader(r.base,4,Read,&r,&live);
    Check(changed.Ready() && live.Stats().translations==2 &&
          changed.image.diagnostic_cache_key!=from_guest.image.diagnostic_cache_key,
          "same VA but changed bytes must trigger new native translation");

    r.mapped=0x80+16;
    auto unmapped=CaptureNativeGraphicsShader(r.base,4,Read,&r,&live);
    Check(!unmapped.Ready() && live.Stats().entries==2,
          "partial remapping must never return cached success");

    NativeTranslationCache disabled{0,0};
    Check(disabled.GetOrTranslate(header,program,4).Ready() &&
          disabled.Stats().entries==0 &&
          disabled.GetOrTranslate(header,program,4).Ready() &&
          disabled.Stats().translations==2,
          "zero capacity disables retention but not correct translation");

    cache.Clear();
    Check(cache.Stats().entries==0 && cache.Stats().bytes==0,
          "session destruction/invalidation can discard all cached images");
    std::puts("NS2 native shader translation cache: PASS (source-verified LRU)");
}
