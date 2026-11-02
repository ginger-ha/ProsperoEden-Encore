#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep GitHub's native cache genuinely restorable instead of silently rejecting sibling paths."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
workflow = (root / ".github/workflows/build-040-zbic.yml").read_text()
linker = (root / "tools/ci/link-sibling-deps.sh").read_text()
build = (root / "tools/build-headless-native.sh").read_text()
deps = (root / "tools/deps.py").read_text()

for path in (
    "../ps5-native-app-boilerplate",
    "../ps5-opengl-review",
    "../mihawk-vulkan-review",
    "../mihawk-mesa-review",
    "../mihawk-sdk-review",
):
    assert path not in workflow, f"actions/cache still contains unsupported path {path}"

# Native all-on builds must provision the same Boost.Container header as
# the separate host-only core preflight. Four Vulkan host C++ checks consume
# boost/container/small_vector.hpp before PS5-native compilation starts.
host_workflow = (root / ".github/workflows/encore-core-preflight.yml").read_text()
native_toolchain = workflow.split("      - name: Install build toolchain", 1)[1].split(
    "      - name: Upgrade Meson", 1)[0]
# Native source changes now trigger core verification independent of commit
# message suffixes. Narrow push paths avoid unnecessary runs.
# Per-SHA groups keep previous long-running audits conclusive while new native
# pushes validate independently; no cancellation of an older SHA.
host_push = host_workflow.split("  push:", 1)[1].split("  workflow_dispatch:", 1)[0]
host_group = host_workflow.split("concurrency:", 1)[1].split("jobs:", 1)[0]
assert "branches: [main]" in host_push
assert "paths:" in host_push
for selected in (
    "'vendor/encore-active/**'",
    "'headless/**'",
    "'tools/**'",
    "'.github/workflows/encore-core-preflight.yml'",
):
    assert selected in host_push, ("core source path missing", selected)
assert "'docs/**'" not in host_push
assert "'launcher/**'" not in host_push
assert "${{ github.ref }}" in host_group
assert "${{ github.event_name }}" in host_group
assert "${{ github.sha }}" in host_group
assert "cancel-in-progress: false" in host_group
assert "if: ${{ github.event_name == 'workflow_dispatch' ||" not in host_workflow

assert "libboost-container-dev" in host_workflow
assert "libboost-container-dev" in native_toolchain
assert "clang++-18 -std=c++20 -x c++ -fsyntax-only -" in native_toolchain
assert native_toolchain.index("libboost-container-dev") < native_toolchain.index(
    "clang++-18 -std=c++20 -x c++ -fsyntax-only -"
)
# Ordinary main UI/docs pushes start a *skipped* native workflow.
# They must not cancel a long-running explicitly requested native package.
native_group = workflow.split("concurrency:", 1)[1].split("jobs:", 1)[0]
assert "github.ref == 'refs/heads/main'" in native_group
assert "github.event_name == 'push'" in native_group
assert "!contains(github.event.head_commit.message || '', '[full-build]')" in native_group
assert "!contains(github.event.head_commit.message || '', '[resume-stage:37728435816]')" in native_group
assert "'skip-only' || 'build-capable'" in native_group
assert "cancel-in-progress: true" in native_group
# Preserve existing one-at-a-time build-capable behavior for explicitly
# requested native pushes; workflow_dispatch has its own event scope.
assert "${{ github.event_name }}" in native_group

assert "PROSPEROEDEN_GIT_DEPS_ROOT: .deps/repos" in workflow
assert "PROSPEROEDEN_GIT_DEPS_ROOT" in deps
assert "item.get('path', '').startswith('../')" in deps
assert "pathlib.Path(item['path']).name" in deps
assert "PROSPEROEDEN_GIT_DEPS_ROOT" in linker

assert workflow.count("            .deps\n") == 2
assert "Prepare cacheable sibling dependency paths" in workflow
assert workflow.index("Prepare cacheable sibling dependency paths") < workflow.index("Prepare native build inputs")
for name in (
    "ps5-native-app-boilerplate",
    "ps5-opengl-review",
    "mihawk-vulkan-review",
    "mihawk-mesa-review",
    "mihawk-sdk-review",
):
    assert name in linker
assert '.deps/repos' in linker

assert "fork-source-stamps.json" in build
assert "sha256(path.read_bytes())" in build
assert "os.utime(path" in build
assert "-exec touch" not in build
# Catch PS5 ABI/source errors before spending time on the native Ninja build.
assert '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON' in build
assert 'tools/check-native-source-syntax.py' in build
assert build.index('tools/check-native-source-syntax.py') < build.index('cmake --build "$scratch/native-local"')
# One release artifact: publish verified FTP and release bundle BEFORE any
# optional cache upload. Do not restore the obsolete all-on/dev package path.
assert "EDEN_TEST_ALL_ON" not in workflow
assert "Upload validated native development package" not in workflow
assert "Upload native development debug symbols" not in workflow
assert "bash tools/build-package.sh dev" not in workflow
assert workflow.index("Upload FTP-ready title folder") < workflow.index("Save build caches after verified artifact uploads")
assert workflow.index("Upload compiled release bundle") < workflow.index("Save build caches after verified artifact uploads")
# Only the verified FTP title archive is presented as the installable package.
# Preserve resumable failed-job state internally; historical downloads are a
# restore fallback, never an additional upload in a new run.
assert "Upload resumable staged app" not in workflow
assert "Verify downloadable staged ZIP root" not in workflow
assert "Reject flattened staged archives" not in workflow
assert workflow.count("name: Prospero.Eden-Encore-staged-app") == 1
assert "Restore internal stage checkpoint" in workflow
assert "Restore historical staged artifact if no checkpoint exists" in workflow
assert "steps.restore_stage.outputs.cache-hit != 'true'" in workflow
assert "encore-internal-stage-v1-${{ runner.os }}-${{ github.run_id }}" in workflow
assert "encore-internal-stage-v1-${{ runner.os }}-${{ env.RESUME_STAGE_RUN_ID }}" in workflow
assert workflow.index("Validate freshly built staged app") < workflow.index("Save internal stage checkpoint")
assert workflow.index("Save internal stage checkpoint") < workflow.index("Assemble release files")
assert workflow.index("Upload FTP-ready title folder") < workflow.index("Validate actual downloadable FTP ZIP root")
assert "name: Eden-Encore-PS5-FTP-PPSA99008" in workflow

cache_block = workflow.split("      - name: Save build caches after verified artifact uploads", 1)[1].split("  release:", 1)[0]
assert "continue-on-error: true" in cache_block, "optional cache write must not fail artifact delivery"
print("Encore CI incremental-cache and early syntax gate contract PASS")
