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
assert 'case_media::FrontPaperAvailable(' in renderer
back_owner = renderer.split("void flat_back_fallback(", 1)[1].split(
    "// Static sleeve used by the Library", 1)[0]
assert "case_media::FrontPaperAvailable(" in back_owner
assert "c.textures.cover(*front, front_bucket).missing" in back_owner
assert back_owner.index("case_media::FrontPaperAvailable(") < back_owner.index(
    "case_media::BackScenes("), "rear must exclude the actual selected front"
assert "return !c.textures.cover(path, front_bucket).missing;" in back_owner
ready_owner = renderer.split("bool composed_case_face_ready(", 1)[1].split(
    "void Launcher::start_scan()", 1)[0]
assert "return !textures.cover(path, paper_w).missing;" in ready_owner
assert ready_owner.index("case_media::FrontPaperAvailable(") < ready_owner.index(
    "case_media::BackScenes("), "readiness must match rendered front selection"
assert 'textures.cover(*front, 704.0f).missing' in renderer
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
    // Bad marker roles stay excluded from the Nlib fallback; only real
    // numbered LaunchBox categories may claim a reserved rear slot.
    const std::vector<std::string> role_noise{
        "/cache/box-scene-9-BAD.tga", "/cache/box-scene-1-OK.tga",
        "/cache/box-scene-1-OTHER.tga", "/cache/box-scene-3-YES.tga"};
    unsigned decode_checks = 0;
    const auto role_pick = BackScenes(hero, icon, role_noise,
        [&](const std::string&) { ++decode_checks; return true; });
    assert(role_pick[0] == &role_noise[1] && !role_pick[1]);
    assert(role_pick[2] == &role_noise[3]);
    assert(decode_checks == 3);
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

    // Missing Hero: the first cached screenshot becomes the actual front.
    // It must not reappear on the back under another scene slot.
    const std::vector<std::string> fallback_front{
        "first-front.tga", "back-one.tga", "back-two.tga"};
    const auto no_hero_back = BackScenes(empty, icon, fallback_front);
    assert(no_hero_back[0] == &fallback_front[1]);
    assert(no_hero_back[1] == &fallback_front[2]);
    assert(!no_hero_back[2]);
    const std::vector<std::string> indexed_front{
        "/cache/box-scene-1-FIRST.tga", "/cache/box-scene-2-SECOND.tga"};
    const auto indexed_no_hero = BackScenes(empty, icon, indexed_front);
    assert(!indexed_no_hero[0]);
    assert(indexed_no_hero[1] == &indexed_front[1]);
    assert(!indexed_no_hero[2]);
    const auto only_front = BackScenes(empty, icon, {"only-front.tga"});
    assert(!only_front[0] && !only_front[1] && !only_front[2]);
    // A valid Hero filename can still fail decoding. The actual front
    // falls back to another cached scene, which the back must exclude.
    const std::vector<std::string> failed_hero{
        "failed-hero.tga", "decoded-front.tga", "rear-only.tga"};
    const auto active_front = FrontPaperAvailable(
        failed_hero[0], icon, failed_hero,
        [](const std::string& path) { return path != "failed-hero.tga"; });
    assert(active_front == &failed_hero[1]);
    const auto actual_back = BackScenes(*active_front, icon, failed_hero);
    assert(actual_back[0] == &failed_hero[0]); // source still present but unavailable
    assert(actual_back[1] == &failed_hero[2]);
    assert(*actual_back[1] != *active_front);
    const auto filtered_back = BackScenes(
        *active_front, icon, failed_hero,
        [](const std::string& path) { return path != "failed-hero.tga"; });
    assert(filtered_back[0] == &failed_hero[2]);
    assert(!filtered_back[1] && !filtered_back[2]);
    // A caller may give the ORIGINAL hero filename rather than the
    // resolved front. When its decode fails, the back must still exclude
    // the actual fallback front, not duplicate it as an independent scene.
    const auto direct_fallback_back = BackScenes(
        failed_hero[0], icon, failed_hero,
        [](const std::string& path) { return path != "failed-hero.tga"; });
    assert(direct_fallback_back == filtered_back);
    const std::vector<std::string> no_hero_failed_first{
        "unavailable-front.tga", "actual-front.tga", "rear-shot.tga"};
    const auto clean_back = BackScenes(
        empty, icon, no_hero_failed_first,
        [](const std::string& path) { return path != "unavailable-front.tga"; });
    assert(clean_back[0] == &no_hero_failed_first[2]);
    assert(!clean_back[1] && !clean_back[2]);
    const std::vector<std::string> indexed_failed{
        "/cache/box-scene-1-BAD.tga", "/cache/box-scene-2-OK.tga"};
    const auto filtered_indexed = BackScenes(
        empty, icon, indexed_failed,
        [](const std::string& path) { return path.find("-BAD.") == std::string::npos; });
    // With no hero, the valid indexed title capture becomes the ACTUAL
    // front after the fanart decode fails. It must not be duplicated on
    // the back, even though its original indexed role was category 2.
    assert(!filtered_indexed[0] && !filtered_indexed[1] && !filtered_indexed[2]);
    // With a valid hero front, that same title capture remains eligible
    // for its reserved rear category: genuine source roles are retained.
    const auto indexed_with_hero = BackScenes(
        hero, icon, indexed_failed,
        [](const std::string& path) { return path.find("-BAD.") == std::string::npos; });
    assert(!indexed_with_hero[0] && indexed_with_hero[1] == &indexed_failed[1]);
    assert(!indexed_with_hero[2]);
    assert(FrontAlternate(hero, empty, {"hero.tga"}) == nullptr);

    // When a game only has a front icon/poster, the back stays plain ink.
    const auto only_icon = BackScenes(hero, icon, {});
    assert(!only_icon[0] && !only_icon[1]);
    assert(*FrontPaper(hero, icon, shots) == hero);
    assert(*FrontPaper(empty, icon, shots) == "hero.tga");
    assert(*FrontPaper(empty, icon, {}) == icon);
    assert(FrontPaper(empty, empty, {}) == nullptr);
    // Hero fails: use a distinct cached screenshot; preserve pending Hero
    // priority and last-resort icon. Never invent a new image.
    const auto usable = [](const std::string& path) {
        return path != "hero.tga" && path != "scene-2.tga";
    };
    assert(FrontPaperAvailable(hero, icon, shots, usable) == &shots[4]);
    assert(FrontPaperAvailable(
        hero, icon, shots, [](const std::string&) { return true; }) == &hero);
    assert(FrontPaperAvailable(
        hero, icon, shots, [&](const std::string& path) { return path == icon; }) == &icon);
    assert(FrontPaperAvailable(
        hero, icon, shots, [](const std::string&) { return false; }) == nullptr);
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
