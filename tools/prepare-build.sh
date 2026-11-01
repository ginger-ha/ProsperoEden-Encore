#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Prepares everything the PS5 build needs besides Eden itself (make prepare), after the pinned
# inputs are in place (make deps): this checkout's build cache, Eden's source tree, the Payload
# SDK, FFmpeg for the PS5, the native packaging tool, the runtime libc.prx, the libSceAgcDriver
# link stub and the isolated RADV driver. Each step is skipped when its result already exists.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
source "$root/tools/host-env.sh"
eden_host_env "$root"
cd "$root"
step() { echo "== $*"; }

# Thousands of small files: keep the build cache on a native Linux filesystem, one per checkout.
cache_parent="${XDG_CACHE_HOME:-$HOME/.cache}"
if [[ ! -f .local/headless-cache ]] || [[ ! -d "$(cat .local/headless-cache)" ]]; then
    scratch="$cache_parent/ps5-eden-headless.$(printf '%s' "$root" | sha256sum | cut -c1-12)"
    mkdir -p .local "$scratch"
    printf '%s\n' "$root" > "$scratch/owner"
    printf '%s\n' "$scratch" > .local/headless-cache
fi
scratch=$(cat .local/headless-cache)
[[ "$(cd -- "$(cat "$scratch/owner")" && pwd -P)" == "$root" ]] || { echo "Build cache $scratch belongs to another checkout" >&2; exit 1; }

eden="$scratch/source"
# R289: safely refresh the precise old C++20 atomic Eden source cache; retain
# the pinned CPM downloads, SDK, RADV, ccache and native-object caches.
python3 -B "$root/tools/refresh-eden-atomic-source-cache.py" "$scratch" \
    "$root/.deps/eden-5f142c79.tar.gz" "$root"
if [[ ! -f $eden/CMakeLists.txt ]]; then
    step "Eden source"
    mkdir -p "$eden"
    tar -xzf .deps/eden-5f142c79.tar.gz --strip-components=1 -C "$eden"
fi
printf '%s\n' '5f142c7926d0c7fcbbd0ce30794d72f638a43b2a' > "$eden/GIT-COMMIT"
printf '%s\n' 'ps5-headless' > "$eden/GIT-REFSPEC"
step "Versioned Encore Eden fork (43 audited shipping patches, 83 full sources)"
python3 -B tools/install-vendored-eden-backports.py --repair-owned-cache "$eden"
# Native build recipe is a fully versioned translation unit, not a string
# replacement performed during CMake configure. Original Eden is immutable.
python3 -B tools/install-vendored-eden-build-flags.py "$eden"
# The tested I-cache and service-manager host-wait implementations are
# always installed into the ACTIVE native core. This is source materialization,
# not an environment-variable runtime opt-in or a debug-only wrapper.
step "Always-on guest I-cache and host-service wait backports"
python3 -B tools/install-active-core-backports.py "$eden" --repair-owned-cache
python3 -B tools/install-active-core-backports.py "$eden" --check
step "Two audited, warning-free shared Eden headers (original pin unchanged)"
python3 -B tools/install-eden-header-hygiene.py "$eden"
python3 -B tools/install-eden-header-hygiene.py "$eden" --check
step "R352 fence-safe NVNflinger layer/display cleanup (versioned complete source)"
python3 -B tools/install-vendored-surface-lifecycle.py "$eden"
python3 -B tools/check-nvnflinger-dequeue-wakeup.py "$eden"

# Optional: seed Eden's package cache from another checkout's (CI reuses a development cache).
if [[ -n ${EDEN_CPM_CACHE_SEED:-} && ! -d $eden/.cache/cpm ]]; then
    step "Eden package cache from $EDEN_CPM_CACHE_SEED"
    mkdir -p "$eden/.cache"
    cp -a "$EDEN_CPM_CACHE_SEED" "$eden/.cache/cpm"
fi
# R349: the actual 22 PS5 CPM source trees are checked into this Git repo
# (full 1-GiB source plus pinned upstream cpmfile.json SHA and content locks).
# Only missing package/version directories are copied into mutable build cache;
# existing native CPM caches remain available for incremental builds.
step "Pinned PS5 Eden CPM source cache (fully vendored)"
python3 -B tools/vendor-eden-cpm.py --stage "$eden"
# The FFmpeg source Eden pins, where Eden's package cache keeps it.
ffmpeg_source="$eden/.cache/cpm/ffmpeg/c7b5f1537d"
if [[ ! -f $ffmpeg_source/configure ]]; then
    step "FFmpeg source"
    mkdir -p "$(dirname "$ffmpeg_source")"
    cp -a .deps/ffmpeg-c7b5f1537d "$ffmpeg_source"
fi

if [[ ! -f $scratch/sdk/.complete ]]; then
    step "Payload SDK"
    mkdir -p "$scratch/sdk"
    cp -a ../ps5-native-app-boilerplate/.deps/native/ps5-payload-sdk/target "$scratch/sdk/"
    touch "$scratch/sdk/.complete"
fi
if [[ ! -f $scratch/ffmpeg-native/install/lib/libavcodec.a ]]; then
    step "FFmpeg for the PS5"
    bash tools/build-headless-ffmpeg.sh
fi
step "Native packaging tool"
bash tools/build-native-tool.sh
# The app's runtime libc.prx: the boilerplate's clean-room build, checked against its recorded digest.
if [[ ! -f ../ps5-native-app-boilerplate/runtime/libc.prx ]]; then
    step "Runtime libc.prx"
    bash ../ps5-native-app-boilerplate/tools/rebuild-libc.sh
fi
step "libSceAgcDriver link stub"
bash tools/build-agc-driver-stub.sh
step "PS5 OpenGL audited SDK (ad2807d)"
bash tools/build-opengl-sdk.sh
# Reuse RADV only when both its Mesa revision and this fork's display adaptation match.
# A stale cached archive can link successfully while carrying different weak entrypoints/behaviour.
radv_release=../mihawk-vulkan-review/.deps/native/radv-release
mesa_pin=$(python3 -c 'import json; print(next(i["commit"] for i in json.load(open("tools/deps.json"))["items"] if i["name"] == "ps5-mesa"))')
if [[ -f $radv_release/lib/libvulkan_radeon.ps5.a ]]; then
    built=$(sed -n 's/^revision: //p' "$radv_release/PROVENANCE.txt" 2>/dev/null || true)
    if [[ $built != "$mesa_pin" ]]; then
        step "RADV: cached Mesa ${built:0:12} differs from pin ${mesa_pin:0:12}"
        bash tools/build-radv-dependencies.sh
        rm -f build/radv-isolated/libvulkan_radeon.ps5.a
    elif ! python3 -B tools/patch-radv-wsi.py --check "$radv_release/EDEN_WSI_SHA256"; then
        step "RADV: the display code's adaptation changed"
        bash tools/build-radv-dependencies.sh
        rm -f build/radv-isolated/libvulkan_radeon.ps5.a
    elif ! python3 -B tools/radv-active-inputs.py --check "$radv_release/EDEN_ACTIVE_INPUTS_SHA256"; then
        # Cache hits require ALL maintained compiled units, not just WSI.
        # Otherwise cache-policy, descriptor and draw fixes may remain absent
        # from a perfectly linkable archive despite passing source checks.
        step "RADV: maintained compiled source set changed; rebuilding archive"
        bash tools/build-radv-dependencies.sh
        rm -f build/radv-isolated/libvulkan_radeon.ps5.a
    fi
fi
# A restored isolated archive is not trusted if its source build stamp is
# missing, even when the original pre-isolation archive was not restored.
if [[ -f build/radv-isolated/libvulkan_radeon.ps5.a ]] &&
   ! python3 -B tools/radv-active-inputs.py --check "$radv_release/EDEN_ACTIVE_INPUTS_SHA256"; then
    step "RADV: old isolated archive has no matching compiler input proof"
    rm -f build/radv-isolated/libvulkan_radeon.ps5.a
fi
if [[ ! -f build/radv-isolated/libvulkan_radeon.ps5.a ]]; then
    if [[ ! -f $radv_release/lib/libvulkan_radeon.ps5.a ]]; then
        step "RADV (Mesa) for the PS5 - this takes a while"
        bash tools/build-radv-dependencies.sh
    fi
    step "Isolating RADV beside the OpenGL Mesa"
    python3 -B tools/isolate-radv.py
fi
step "Prepared: $scratch"
