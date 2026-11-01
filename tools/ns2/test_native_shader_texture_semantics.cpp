// SPDX-License-Identifier: GPL-3.0-or-later
// Validate actual Ampere lowering of texture-constant widths and packed
// half predicates against reviewed EglantinePS5 compatibility cases.
#include <array>
#include <cassert>
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"
#include "shader_recompiler/frontend/ampere/program_capture.h"

using Shader::Ampere::Instruction;
using Shader::Ampere::LowerToMaxwell;
constexpr std::uint32_t pred = 7u << 12;
constexpr std::uint32_t exit_cond = 7u << 23;
static Instruction Exit() { return {{{pred | 0x94d, 0, exit_cond, 0}}}; }
int main() {
    // The final scalar LDC format must preserve its native width in the
    // generated Maxwell instruction. 6/7 are unsupported and fail closed.
    for (std::uint32_t width=0; width<8; ++width) {
        const Instruction ldc{{pred | 0xb82 | (2u << 16), 0, width << 9, 0}};
        const std::array<Instruction,2> code{ldc,Exit()};
        const auto result=LowerToMaxwell(code);
        if(width<=5) {
            assert(result && result.source_size==32);
            assert(!result.instructions.empty());
        } else {
            assert(!result && result.instructions.empty());
        }
    }
    // Exact five-instruction NVN geometry ATEXIT prologue: the first EXIT
    // must branch to the static cleanup handler, not end the capture.
    {
        using Shader::Ampere::ProgramCaptureState;
        using Shader::Ampere::StaticAtExitTarget;
        const std::array<Instruction, 9> code{
            Instruction{{0x0000734e, 0, 0, 0}},
            Instruction{{0x00037802, 7u * 16u, 0x00000f00, 0}},
            Instruction{{0x00007210, 3, 0x07f1e0ff, 0}},
            Instruction{{0xff017224, 0xff, 0x000e0401, 0}},
            Instruction{{0x00007357, 0, 0, 0}},
            Exit(),
            Instruction{{pred | 0x918, 0, 0, 0}},
            Instruction{{0x00007957, 0, 0, 0}},
            Exit(),
        };
        assert(StaticAtExitTarget(code) == 7);
        ProgramCaptureState capture;
        for (std::uint32_t index = 0; index < code.size(); ++index) {
            const auto observed = capture.Observe(code[index], index);
            assert(observed == (index + 1 == code.size()
                                   ? ProgramCaptureState::Result::Complete
                                   : ProgramCaptureState::Result::Continue));
        }
        const auto lowered = LowerToMaxwell(code);
        assert(lowered && lowered.source_size == code.size() * sizeof(Instruction));
        assert(lowered.source_instruction_offsets.size() == code.size());
        auto invalid = code;
        invalid[1].words[1] = 1; // An unaligned target cannot be silently guessed.
        assert(!StaticAtExitTarget(invalid));
        const auto unsafe = LowerToMaxwell(invalid);
        assert(!unsafe && unsafe.instructions.empty());
        // A clear without an installed ATEXIT handler must also fail closed.
        const std::array<Instruction, 2> stray_clear{
            Instruction{{0x00007957, 0, 0, 0}}, Exit()};
        assert(!LowerToMaxwell(stray_clear));
    }
    // Packed half predicate compare is emitted as a Maxwell predicate-set,
    // but an unreviewed native mode cannot be translated as an arbitrary op.
    {
        const std::array<Instruction,2> code{
            Instruction{{pred | 0x234 | (2u << 16), 0, 7u << 23, 0}},Exit()};
        const auto result=LowerToMaxwell(code);
        assert(result && result.source_size==32);
        assert(result.instructions.size()>=2);
    }
    {
        const std::array<Instruction,2> code{
            Instruction{{pred | 0x234 | (2u << 16), 0, (7u << 23) | (1u << 27), 0}},Exit()};
        const auto result=LowerToMaxwell(code);
        assert(!result && result.instructions.empty());
    }
}
