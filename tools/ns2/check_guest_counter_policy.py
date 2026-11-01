#!/usr/bin/env python3
"""N76: compile exact vendor guest-clock policy + inspect native owners."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
vendor=root/"vendor/encore-active/eden-core"
clock=(vendor/"src/common/cpu_features.cpp").read_text()
clock_header=(vendor/"include/common/cpu_features.h").read_text()
timing_owner=(root/"vendor/sources/eden/src/core/core_timing.cpp").read_text()
assert "return Eden::GuestCounter::NanosecondsToGuest(ns);" in clock_header
assert "return Eden::GuestCounter::CpuTicksToGuest(cpu_tick);" in clock_header
assert "Common::WallClock::CPUTickToCNTPCT(cpu_ticks)" in timing_owner
assert "Common::WallClock::NSToCNTPCT" in (root/"vendor/sources/eden/src/common/cpu_features.h").read_text() or "NSToCNTPCT" in clock_header
jit=(vendor/"src/core/arm/dynarmic/arm_dynarmic_64.cpp").read_text()
npdm=(root/"vendor/encore-active/ns2-experimental/src/core/file_sys/program_metadata.cpp").read_text()
loader=(root/"vendor/encore-active/ns2-experimental/src/core/loader/deconstructed_rom_directory.cpp").read_text()
cmake=(root/"headless/CMakeLists.txt").read_text()
for witness in ("Eden::GuestCounter::NativeFactor()", "Eden::GuestCounter::NanosecondsToGuest(", "rdtsc_frequency == 0"):
    assert witness in clock,witness
assert "config.cntfrq_el0 = static_cast<u32>(Eden::GuestCounter::Rate());" in jit
assert "Eden::GuestCounter::SelectProgram(" not in npdm
assert "Eden::GuestCounter::SelectProgram(metadata.IsSwitch2(), Common::g_cpu_caps.tsc_frequency)" in loader
assert loader.index("Eden::GuestCounter::SelectProgram(") > loader.index("metadata.Reload(npdm)")
assert loader.index("Eden::GuestCounter::SelectProgram(") < loader.index("is_loaded = true")
assert "option(EDEN_NS2_GUEST_COUNTER_EXPERIMENTAL" in cmake
assert "EDEN_SHARED_NS2_GUEST_COUNTER" in cmake
assert "if(EDEN_NS2_GUEST_COUNTER_EXPERIMENTAL OR EDEN_SHARED_NS2_GUEST_COUNTER)" in cmake
assert "foreach(n76_target IN ITEMS core common eden-headless)" in cmake
main=(root/"headless/main.cpp").read_text()
assert "Eden::GuestCounter::SelectProgram(false, Common::g_cpu_caps.tsc_frequency);" in main
assert main.index("Eden::GuestCounter::SelectProgram(false, Common::g_cpu_caps.tsc_frequency);") < main.index("loaded = system.Load(window, guest, params);")
assert "if(EDEN_NS2_EXEFS_EXPERIMENTAL OR EDEN_SHARED_NS2_EXEFS)" in cmake
assert "n76_core_sources" in cmake
program=r"""
#include <cassert>
#include <cstdint>
#include <cstdio>
#include "encore/guest_counter_policy.h"
#include "common/cpu_features.h"
using namespace Eden::GuestCounter;
static std::uint64_t Counter(std::uint64_t ticks) {
 return static_cast<std::uint64_t>(
   (static_cast<unsigned __int128>(ticks)*NativeFactor())>>64);
}
int main() {
 static_assert(Switch1Hz==19'200'000 && Switch2Hz==31'250'000);
 assert(Rate()==Switch1Hz);
 SelectProgram(false,3'000'000'000ULL);
 assert(NanosecondsToGuest(1'000'000'000ULL)==19'200'000ULL);
 assert(Common::WallClock::NSToCNTPCT(1'000'000'000ULL)==Switch1Hz);
 assert(Common::WallClock::CPUTickToCNTPCT(GuestCpuHz)==Switch1Hz);
 assert(CpuTicksToGuest(1'020'000'000ULL)==19'200'000ULL);
 SelectProgram(true,3'000'000'000ULL);
 assert(Rate()==Switch2Hz);
 assert(NanosecondsToGuest(1'000'000'000ULL)==31'250'000ULL);
 assert(Common::WallClock::NSToCNTPCT(1'000'000'000ULL)==Switch2Hz);
 assert(Common::WallClock::CPUTickToCNTPCT(GuestCpuHz)==Switch2Hz);
 assert(Common::WallClock::NSToCNTPCT(16'666'666ULL)==520'833ULL);
 assert(CpuTicksToGuest(1'020'000'000ULL)==31'250'000ULL);
 assert(NanosecondsToGuest(16'666'666)==520'833ULL);
 const auto ticks=Counter(3'000'000'000ULL);
 assert(ticks>=31'249'998ULL && ticks<=31'250'001ULL);
 SelectProgram(false,3'000'000'000ULL);
 assert(Rate()==Switch1Hz);
 assert(Common::WallClock::CPUTickToCNTPCT(GuestCpuHz)==Switch1Hz);
 assert(Common::WallClock::NSToCNTPCT(16'666'666ULL)==319'999ULL);
 assert(Counter(3'000'000'000ULL)>=19'199'998ULL);
 SelectProgram(true,0);
 assert(Rate()==Switch2Hz && NativeFactor()==0);
 SelectProgram(false,0);
 assert(Rate()==Switch1Hz && NativeFactor()==0);
 std::puts("N76_GUEST_COUNTER_RESET_AND_RATIO_PASS");
}
"""
with tempfile.TemporaryDirectory(prefix="n76-clock-") as tmp:
 d=Path(tmp)
 src=d/"test.cpp";src.write_text(program)
 for compiler in ("clang++","g++"):
  exe=d/compiler.replace("+","p")
  subprocess.run([compiler,"-std=c++20","-O2","-Wall","-Wextra","-Werror",
    "-fsanitize=undefined","-fno-sanitize-recover=all",
    "-DEDEN_NS2_GUEST_COUNTER=1",
    "-I",str(vendor/"include"),"-I",str(root/"vendor/sources/eden/src"),
    str(src),"-o",str(exe)],check=True)
  subprocess.run([str(exe)],check=True)
print("N76_ENCORE_CLOCK_CLANG_GCC_UBSAN_PASS")

# A release / NS1-only compilation must not acquire the experimental rate.
legacy=r"""
#include <cassert>
#include "encore/guest_counter_policy.h"
#include "common/cpu_features.h"
int main() {
 Eden::GuestCounter::SelectProgram(true, 3'000'000'000ULL);
 assert(Common::WallClock::NSToCNTPCT(1'000'000'000ULL)==19'200'000ULL);
 assert(Common::WallClock::CPUTickToCNTPCT(1'020'000'000ULL)==19'200'000ULL);
}
"""
with tempfile.TemporaryDirectory(prefix="n77-legacy-") as tmp:
 src=Path(tmp)/"legacy.cpp";src.write_text(legacy)
 for compiler in ("clang++","g++"):
  exe=Path(tmp)/compiler.replace("+","p")
  subprocess.run([compiler,"-std=c++20","-O2","-Wall","-Wextra","-Werror",
    "-fsanitize=undefined","-fno-sanitize-recover=all",
    "-I",str(vendor/"include"),"-I",str(root/"vendor/sources/eden/src"),
    str(src),"-o",str(exe)],check=True)
  subprocess.run([str(exe)],check=True)
print("N77_REAL_WALLCLOCK_SERVICE_AND_NONMULTICORE_TICKS_PASS")
