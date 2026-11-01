// SPDX-License-Identifier: GPL-3.0-or-later
// Upstream EglantinePS5 regression for the final geometry varying slot.
#include <cassert>
#include "shader_recompiler/frontend/ir/attribute.h"
int main() {
    using namespace Shader::IR;
    for (unsigned i=0; i<32U*4U; ++i) {
        const auto a=Attribute::Generic0X+i;
        assert(IsGeneric(a));
        assert(GenericAttributeIndex(a)==i/4U);
        assert(GenericAttributeElement(a)==i%4U);
    }
    assert(IsGeneric(Attribute::Generic31W));
    assert(!IsGeneric(Attribute::PositionW));
    assert(!IsGeneric(Attribute::ColorFrontDiffuseR));
    assert(!IsGeneric(Attribute::ViewportMask));
    return 0;
}
