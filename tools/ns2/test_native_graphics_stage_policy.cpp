// SPDX-License-Identifier: GPL-3.0-or-later
// Native Ampere stage admission must never invent a missing pipeline/QMD.
#include <cassert>
#include "shader_recompiler/frontend/ampere/native_graphics_stage_policy.h"
int main() {
    using Shader::Ampere::IsStandaloneNativeGraphicsStage;
    using Shader::Ampere::RequiresNativeVertexMerge;
    using Shader::Stage;
    assert(IsStandaloneNativeGraphicsStage(Stage::VertexB));
    assert(IsStandaloneNativeGraphicsStage(Stage::Fragment));
    assert(!IsStandaloneNativeGraphicsStage(Stage::VertexA));
    assert(RequiresNativeVertexMerge(Stage::VertexA));
    assert(!RequiresNativeVertexMerge(Stage::Fragment));
    assert(!IsStandaloneNativeGraphicsStage(Stage::TessellationControl));
    assert(!IsStandaloneNativeGraphicsStage(Stage::TessellationEval));
    assert(!IsStandaloneNativeGraphicsStage(Stage::Geometry));
    assert(!IsStandaloneNativeGraphicsStage(Stage::Compute));
    assert(!IsStandaloneNativeGraphicsStage(static_cast<Stage>(0xffffffffu)));
}
