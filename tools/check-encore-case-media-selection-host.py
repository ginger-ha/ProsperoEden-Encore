#!/usr/bin/env python3
"""Execute the actual Encore missing-cover media picker on host C++20.

All scenes come from existing locally cached game media. We never fetch,
invent or duplicate screenshot sources to fill a case page.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
header = root / "headless/prosperoeden/pe/ui/case_media_selection.hpp"
renderer = (root / "headless/prosperoeden/pe/ui/library.cpp").read_text()
launcher = (root / "headless/prosperoeden/pe/ui/launcher.cpp").read_text()
textures_header = (root / "headless/prosperoeden/pe/ui/textures.hpp").read_text()
textures_source = (root / "headless/prosperoeden/pe/ui/textures.cpp").read_text()
assert '#include "pe/ui/case_media_selection.hpp"' in renderer
# A missing retail-file path must fall back to composition, not empty ink.
assert 'if (artwork.texture != 0)' in renderer
assert 'const bool use_composed = artwork.texture == 0 && composed_page != 0;' in launcher
# An existing provisional page is rendered IN PLACE, and never counted as a
# third allocation. It stays valid if a transient FBO creation fails.
assert 'std::uint32_t existing = 0' in textures_header
assert 'const bool refresh = existing != 0;' in textures_source
assert 'refresh ? existing :' in textures_source
assert 'if (!refresh) case_pages_.push_back(ink);' in textures_source
assert 'if (!refresh) batch_.delete_texture(ink);' in textures_source
# Failed scan state must remain sticky during a scheduled async retry.
assert '(it->second.loaded || it->second.failed_loads != 0)' in textures_source
assert 'provisional = !inputs_ready;' in launcher
assert 'PageInputReady(page != 0, inputs_ready, seconds)' in launcher
assert 'paper_w, paper_h, page);' in launcher
assert 'if (painting) reconstructed_cover(c, *painting, r);' in renderer
assert 'reconstructed_paper(c, paper);' in renderer
assert 'scene(game.cover,' not in renderer
assert 'glClearColor' not in renderer
assert 'const auto shots = case_media::BackScenes(' in renderer
assert 'constexpr std::array<std::string_view, 3> kSceneMarkers{' in header.read_text()
assert 'const std::string marker =' not in header.read_text()
assert 'const std::string* third = shots[2];' in renderer
assert 'if (third)' in renderer
assert 'shell.x + (rear ? side : 0.0f)' in renderer
assert 'if (painting) reconstructed_cover(c, *painting, r);' in renderer
assert 'scene(game.cover,' not in renderer
source = r"""
#include <cassert>
#include <string>
#include <vector>
#include "pe/ui/case_media_selection.hpp"
int main() {
    using namespace pe::ui::case_media;
    // Cold async media is given four seconds; a provisional GPU page
    // refreshes ONLY when every known texture is actually ready.
    assert(!PageInputReady(false, false, 3.99f));
    assert(PageInputReady(false, false, 4.0f));
    assert(PageInputReady(false, true, 0.1f));
    assert(!PageInputReady(true, false, 50.0f));
    assert(PageInputReady(true, true, 4.2f));
    const std::string hero = "hero.tga";
    const std::string icon = "icon.tga";
    const std::vector<std::string> shots{
        "hero.tga", "hero.tga", "scene-2.tga", "scene-2.tga", "scene-3.tga"
    };
    const auto* front = FrontAlternate(hero, icon, shots);
    assert(front != nullptr && *front == "scene-2.tga");
    const auto pair = BackScenes(hero, icon, shots);
    assert(pair[0] && *pair[0] == "scene-2.tga");
    assert(pair[1] && *pair[1] == "scene-3.tga");
    assert(*pair[0] != *pair[1] && *pair[0] != hero && *pair[1] != hero);
    assert(!pair[2]);
    const std::vector<std::string> indexed{
        "nlib/gameplay.tga", "/cache/box-scene-3-ABCD.tga",
        "/cache/box-scene-2-ABCD.tga", "/cache/box-scene-1-ABCD.tga"};
    const auto categorized = BackScenes(hero, icon, indexed);
    assert(categorized[0] && *categorized[0] == indexed[3]);
    assert(categorized[1] && *categorized[1] == indexed[2]);
    assert(categorized[2] && *categorized[2] == indexed[1]);
    const std::vector<std::string> missing_fanart{
        "/cache/box-scene-2-ABCD.tga", "/cache/box-scene-3-ABCD.tga"};
    const auto role_stable = BackScenes(hero, icon, missing_fanart);
    assert(!role_stable[0]);
    assert(role_stable[1] && *role_stable[1] == missing_fanart[0]);
    assert(role_stable[2] && *role_stable[2] == missing_fanart[1]);
    const std::vector<std::string> nlib_fallback{
        "/cache/box-scene-2-ABCD.tga", "nlib/independent-scene.tga"};
    const auto filled = BackScenes(hero, icon, nlib_fallback);
    assert(filled[0] && *filled[0] == nlib_fallback[1]);
    assert(filled[1] && *filled[1] == nlib_fallback[0]);
    assert(!filled[2]);

    // Only independent screenshot sources may appear on the back.
    // Never insert an app icon as a synthetic second picture.
    const std::vector<std::string> only_hero{"hero.tga", "extra.tga"};
    const auto one = BackScenes(hero, icon, only_hero);
    assert(one[0] && *one[0] == "extra.tga");
    assert(!one[1]);
    assert(FrontAlternate(hero, icon, {"hero.tga", "hero.tga"}) == &icon);

    // A missing icon does not get a fabricated second screenshot.
    const std::string empty;
    const auto alone = BackScenes(hero, empty, only_hero);
    assert(alone[0] && *alone[0] == "extra.tga" && !alone[1]);
    const auto no_media = BackScenes(empty, empty, {});
    assert(!no_media[0] && !no_media[1]);
    assert(FrontAlternate(hero, empty, {"hero.tga"}) == nullptr);

    // When a game only has a front icon/poster, the back stays plain ink.
    const auto only_icon = BackScenes(hero, icon, {});
    assert(!only_icon[0] && !only_icon[1]);
    assert(*FrontPaper(hero, icon, shots) == hero);
    assert(*FrontPaper(empty, icon, shots) == "hero.tga");
    assert(*FrontPaper(empty, icon, {}) == icon);
    assert(FrontPaper(empty, empty, {}) == nullptr);
    const auto excluded_cover = BackScenes(hero, icon, {"icon.tga", "scene.tga"});
    assert(excluded_cover[0] && *excluded_cover[0] == "scene.tga");
    assert(!excluded_cover[1]);

    // All results point into existing metadata, no allocations or copies.
    assert(front == &shots[2]);
    assert(pair[0] == &shots[2] && pair[1] == &shots[4]);
}
"""
compilers = list(dict.fromkeys(filter(None,
    (shutil.which("clang++"), shutil.which("g++"), shutil.which("c++")))))
assert compilers, "Host C++ compiler required"
with tempfile.TemporaryDirectory(prefix="encore-case-media-") as temp:
    cpp = Path(temp) / "case-media.cpp"
    cpp.write_text(source)
    for compiler in compilers:
        for opt in ("-O0", "-O2"):
            exe = Path(temp) / (Path(compiler).name + opt)
            built = subprocess.run(
                [compiler, "-std=c++20", opt, "-Wall", "-Wextra", "-Werror",
                 "-fsanitize=undefined", "-fno-sanitize-recover=all",
                 "-I", str(root / "headless/prosperoeden"), str(cpp), "-o", str(exe)],
                capture_output=True, text=True, timeout=50
            )
            assert built.returncode == 0, (compiler, opt, built.stderr[-4000:])
            result = subprocess.run(
                [str(exe)], capture_output=True, text=True, timeout=15
            )
            assert result.returncode == 0, (compiler, opt, result.stderr[-4000:])
            print("ENCORE_CASE_MEDIA_DEDUP_PASS", Path(compiler).name, opt)
