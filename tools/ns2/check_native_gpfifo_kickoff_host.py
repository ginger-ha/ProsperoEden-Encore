#!/usr/bin/env python3
"""Execute the actual native nvhost-gpu GPFIFO kickoff parser with fake guest RAM.

The pointer-backed H:0x1b ioctl has no inline entry array. This host
witness checks the real C++ method's distinction, bounded allocation and
unchanged inline H:0x8 path; no GPU/PS5 build or frame is claimed.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OWNER = (ROOT / "vendor/encore-active/ns2-runtime/nvdrv_gpu/core/hle/service/nvdrv/devices/nvhost_gpu.cpp").read_text()
start = "NvResult nvhost_gpu::SubmitGPFIFOBase1("
end = "\nNvResult nvhost_gpu::SubmitGPFIFOBase2("
assert OWNER.count(start) == OWNER.count(end) == 1
method = OWNER[OWNER.index(start):OWNER.index(end)]
assert "if (kickoff)" in method
assert "params.num_entries > MaxKickoffEntries" in method
assert "params.num_entries != 0 && params.address == 0" in method
assert "else if (params.num_entries > commands.size())" in method
assert method.index("else if (params.num_entries > commands.size())") < method.index(
    "Tegra::CommandList entries(params.num_entries)")
assert "GetSessionMemory(fd).ReadBlock(params.address" in method
assert "if (params.num_entries != 0) {" in method
assert "const auto it = sessions.find(fd);" in method
assert "if (!session || !session->process)" in method
assert "std::memcpy(entries.command_lists.data(), commands.data()" in method

cpp = r"""
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <span>
#include <unordered_map>
#include <utility>
#include <vector>
using u32 = std::uint32_t;
using DeviceFD = int;
namespace Tegra {
struct CommandListHeader { std::uint64_t word{}; };
struct CommandList {
    explicit CommandList(std::size_t count): command_lists(count) {}
    std::vector<CommandListHeader> command_lists;
};
}
enum class NvResult { Success, InvalidSize, InvalidState };
struct IoctlSubmitGpfifo {
    std::uint64_t address{};
    u32 num_entries{};
};
#define UNIMPLEMENTED() ((void)0)
struct GuestRam {
    std::array<Tegra::CommandListHeader,3> src{{{11},{22},{33}}};
    unsigned reads{};
    void ReadBlock(std::uint64_t address,void* out,std::size_t bytes) {
        assert(address == 0x1000 && bytes == sizeof(src));
        assert(out != nullptr);
        ++reads;
        std::memcpy(out,src.data(),bytes);
    }
};
struct StubProcess {};
struct StubSession { StubProcess* process{}; };
struct StubCore {
    StubProcess process;
    StubSession session{&process};
    StubSession* GetSession(int id) { return id == 1 ? &session : nullptr; }
};
class nvhost_gpu {
public:
    GuestRam memory;
    StubCore core;
    std::unordered_map<DeviceFD,int> sessions{{42,1}};
    std::vector<Tegra::CommandListHeader> captured;
    unsigned submissions{};
    GuestRam& GetSessionMemory(DeviceFD) { return memory; }
    NvResult SubmitGPFIFOImpl(IoctlSubmitGpfifo&,Tegra::CommandList&& list,DeviceFD) {
        captured=std::move(list.command_lists);
        ++submissions;
        return NvResult::Success;
    }
    NvResult SubmitGPFIFOBase1(IoctlSubmitGpfifo&,
                               std::span<Tegra::CommandListHeader>,DeviceFD,bool);
};
""" + method + r"""
int main() {
    nvhost_gpu gpu;
    IoctlSubmitGpfifo pointer{0x1000,3};
    // H:0x1b uses guest RAM, not its empty variable span.
    assert(gpu.SubmitGPFIFOBase1(pointer, {}, 42, true) == NvResult::Success);
    assert(gpu.memory.reads == 1 && gpu.submissions == 1);
    assert(gpu.captured.size() == 3 && gpu.captured[0].word == 11 &&
           gpu.captured[1].word == 22 && gpu.captured[2].word == 33);

    // The old H:0x8 inline command list remains subject to its byte count.
    std::array<Tegra::CommandListHeader,3> inline_entries{{{7},{8},{9}}};
    IoctlSubmitGpfifo inline_params{0,3};
    assert(gpu.SubmitGPFIFOBase1(inline_params, inline_entries, 42, false)
           == NvResult::Success);
    assert(gpu.memory.reads == 1 && gpu.submissions == 2);
    assert(gpu.captured.size() == 3 && gpu.captured[0].word == 7);
    inline_params.num_entries = 4;
    assert(gpu.SubmitGPFIFOBase1(inline_params, inline_entries, 42, false)
           == NvResult::InvalidSize);

    // An arbitrary guest-provided count must not allocate gigabytes.
    IoctlSubmitGpfifo oversized{0x1000,65537};
    assert(gpu.SubmitGPFIFOBase1(oversized, {}, 42, true)
           == NvResult::InvalidSize);
    IoctlSubmitGpfifo no_pointer{0,1};
    assert(gpu.SubmitGPFIFOBase1(no_pointer, {}, 42, true)
           == NvResult::InvalidSize);
    assert(gpu.memory.reads == 1 && gpu.submissions == 2);
    // An unknown FD or retired process must never fall back to an
    // unrelated application's address space for a native kickoff.
    IoctlSubmitGpfifo stale_fd{0x1000,3};
    assert(gpu.SubmitGPFIFOBase1(stale_fd, {}, 99, true)
           == NvResult::InvalidState);
    gpu.sessions[42]=77;
    assert(gpu.SubmitGPFIFOBase1(stale_fd, {}, 42, true)
           == NvResult::InvalidState);
    gpu.sessions[42]=1;
    gpu.core.session.process=nullptr;
    assert(gpu.SubmitGPFIFOBase1(stale_fd, {}, 42, true)
           == NvResult::InvalidState);
    assert(gpu.memory.reads == 1 && gpu.submissions == 2);
    gpu.core.session.process = &gpu.core.process;
    // Fence-only submissions can legitimately have no GPFIFO entries.
    // Neither the pointer-backed nor inline path may read a null buffer.
    IoctlSubmitGpfifo empty{0,0};
    assert(gpu.SubmitGPFIFOBase1(empty, {}, 42, true)
           == NvResult::Success);
    assert(gpu.captured.empty() && gpu.memory.reads == 1 &&
           gpu.submissions == 3);
    assert(gpu.SubmitGPFIFOBase1(empty, {}, 42, false)
           == NvResult::Success);
    assert(gpu.captured.empty() && gpu.memory.reads == 1 &&
           gpu.submissions == 4);
}
"""
compilers = list(dict.fromkeys(p for name in ("clang++", "g++")
                               if (p := shutil.which(name))))
assert compilers, "C++20 host compiler missing"
with tempfile.TemporaryDirectory(prefix="encore-gpfifo-kickoff-") as work:
    unit=Path(work)/"kickoff.cpp"
    unit.write_text(cpp)
    for compiler in compilers:
        for opt in ("-O0", "-O2"):
            exe=Path(work)/(Path(compiler).name+opt)
            subprocess.run([compiler,"-std=c++20",opt,"-Wall","-Wextra","-Werror",
                            "-fsanitize=undefined","-fno-sanitize-recover=all",
                            str(unit),"-o",str(exe)],check=True,timeout=60)
            subprocess.run([str(exe)],check=True,timeout=30)
            print("NS2_GPFIFO_KICKOFF_HOST_PASS",Path(compiler).name,opt)
