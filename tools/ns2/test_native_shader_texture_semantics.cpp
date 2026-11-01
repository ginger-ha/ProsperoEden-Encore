// SPDX-License-Identifier: GPL-3.0-or-later
// Validate actual Ampere lowering of texture-constant widths and packed
// half predicates against reviewed EglantinePS5 compatibility cases.
#include <array>
#include <cassert>
#include "shader_recompiler/frontend/ampere/lower_to_maxwell.h"

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
