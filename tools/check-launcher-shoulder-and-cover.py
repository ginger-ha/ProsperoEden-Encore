#!/usr/bin/env python3
"""Check user-facing shoulder navigation and composed case fallback contract.

These are source ownership checks; host OpenGL screenshots validate the
actual pixels separately. No generated image is shipped as retail art.
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def source(path):
    return (ROOT / path).read_text()
def method(text, start, stop):
    assert text.count(start) == 1, start
    assert text.count(stop) >= 1, stop
    return text.split(start, 1)[1].split(stop, 1)[0]
settings = source("headless/prosperoeden/pe/ui/settings.cpp")
launcher = source("headless/prosperoeden/pe/ui/launcher.cpp")
launcher_h = source("headless/prosperoeden/pe/ui/launcher.hpp")
library = source("headless/prosperoeden/pe/ui/library.cpp")
switch = source("headless/prosperoeden/pe/ui/switch_theme.cpp")
mapping = source("headless/prosperoeden/pe/ui/mapping.cpp")
general = method(settings, "void Launcher::press_settings(Key key)", "void Launcher::draw_settings(")
dialog = method(settings, "void Launcher::press_dialog(Key key)", "void Launcher::draw_dialog(")
game = method(library, "void Launcher::press_game(Key key)", "void Launcher::draw_game(")
mods = method(library, "void Launcher::press_mods(Key key)", "void Launcher::draw_mods(")
switch_keys = method(switch, "void Launcher::press_switch_settings(Key key)", "} // namespace pe::ui")
mapping_keys = method(mapping, "void Launcher::press_mapping(Key key)", "void Launcher::draw_mapping(")
for label, body in (("settings",general),("game",game),("mods",mods),
                    ("switch",switch_keys),("mapping",mapping_keys)):
    assert "Key::l1" in body and "Key::r1" in body, label
for label, body in (("dialog",dialog),("mapping",mapping_keys),
                    ("game",game),("mods",mods)):
    assert "key == Key::r1 ? 1 : -1" in body, label
assert "const bool activate = key == Key::cross;" in dialog
assert "const bool adjust = key == Key::left || key == Key::right;" in dialog
assert "if (!adjust && !activate)" in dialog
assert "const int step = key == Key::left ? -1 : 1;" in mapping_keys
assert "settings_.move(delta)" in general
assert "key==Key::r1?1:-1" in switch_keys
# True scanned faces must take precedence over any composited fallback.
render = method(library, "void flat_retail_sleeve(", "// ONE physical shell: narrow top/bottom")
assert 'const std::string& scan = rear ? game.box_back : game.box_front;' in render
assert render.index("if (artwork.texture != 0)") < render.index("flat_composed_ink(c, game, paper, rear)")
front = method(library, "void flat_front_fallback(", "void flat_back_fallback(")
back = method(library, "void flat_back_fallback(", "// Static sleeve used")
for attr in ("game.hero","game.cover","game.screenshots","game.name","reconstructed_cover"):
    assert attr in front, attr
for attr in ("game.hero","case_media::BackScenes(",
             "game.description", "text_block(c, desc,", "const Rect footer"):
    assert attr in back, attr
assert '"SWITCH"' in front
# Native fixed paper rasters use vertically reversed sampling. The layered
# 3D paper has its own independent FBO flip and MUST NOT be changed.
assert 'c.list.image(c.textures.switch_logo(), logo,\n                     {0.0f, 1.0f, 1.0f, -1.0f}' in front
assert 'c.list.image(c.textures.switch_logo(), logo,\n                     {0.0f, 0.0f, 1.0f, 1.0f}' not in front
# Front uses a full-width cover UV crop, never stretched independently in X/Y.
front_cover = method(library, "void reconstructed_cover(", "// Reconstructed paper inserts")
for token in ("uv.w = target / source;", "uv.h = source / target;",
              "c.list.image(art.texture, paper, uv,"):
    assert token in front_cover, token
assert 'if (painting) reconstructed_cover(c, *painting, r);' in front
assert "case_media::FrontPaper(" in front
assert "case_media::FrontPaper(" in back
assert 'scene(game.cover,' not in back
assert 'case_art_contain(' not in library
assert 'reconstructed_paper(c, paper);' in library
assert "constexpr float kFixedFooter = 0.41f;" in back
# The user's fixed retail-style footer must be upright in flat Library
# previews AND the loader's offscreen ink renderer (both share this code).
assert 'c.list.image(c.textures.switch_rear_footer(), footer,\n                     {0.0f, 1.0f, 1.0f, -1.0f}' in back
assert 'c.list.image(c.textures.switch_rear_footer(), footer,\n                     {0.0f, 0.0f, 1.0f, 1.0f}' not in back
# Main tabs are navigated by L1/R1 before Library page/Settings list handlers.
# Confirmation/modal/game input remains untouched by this global shortcut.
press = method(launcher, "void Launcher::press(Key key)", "void Launcher::update(float dt)")
assert press.index('if (modal_ != Modal::none)') < press.index('if ((key == Key::l1 || key == Key::r1)')
assert press.index('if ((key == Key::l1 || key == Key::r1)') < press.index('switch (screen_)')
assert '(active_main_tab_ + (key == Key::r1 ? 1 : 3)) % 4' in press
assert '(void)press_top_nav(Key::cross);' in press
assert 'int active_main_tab_ = 0;' in launcher_h
# OpenGL screenshot harness must navigate the selected retail game by D-pad,
# now that main-tab shoulders belong to the shared launcher shell.
preview = source("headless/prosperoeden/host/preview_main.cpp")
library_fixture = preview.split('if (const char* library_only', 1)[1].split(
    'if (const char*', 1)[0]
assert 's.press({Key::right, Key::right, Key::right, Key::right, Key::right,' in library_fixture
assert 's.press({Key::r1, Key::r1});' not in library_fixture
assert 'active_main_tab_ = 2;' in launcher
for initial in range(4):
    assert (initial + 1) % 4 in range(4)
    assert ((initial + 1) % 4 + 3) % 4 == initial
assert 'c.textures.switch_rear_footer() != 0' in back
assert "ENCORE / GAME INFORMATION" in back
assert "const std::string& credit = !game.publisher.empty()" in back
# A real face remains untouched while asynchronous texture decoding runs;
# a different missing face can still receive a reconstructed paper insert.
# Every Library jacket uses the same height and visual composition as
# the launcher's paper face, regardless of a downloaded cover.
for token in ("constexpr float kCaseShellAspect = 454.0f / 730.0f;",
              "constexpr float kCaseInkWidth = 440.0f;",
              "constexpr float kCaseInkHeight = 704.0f;",
              "void flat_composed_ink(Canvas& c, const Game& game,",
              "const float sleeve_w = sleeve_h * kCaseShellAspect;",
              "constexpr float rear_h = 247.0f;",
              "constexpr float rear_w = rear_h * kCaseShellAspect;"):
    assert token in library, token
assert "flat_composed_ink(c, game, paper, rear);" in render
assert "selected ? 1.025f : 1.0f" not in library
assert "if (artwork.texture != 0) {" in render
assert "if (artwork.texture != 0)" in render
assert "reconstructed_paper(c, paper);" in render
assert "if (rear)\\n                flat_back_fallback(c, game, paper);" not in render
# No invented regulatory content in the procedural fallback. The user-
# supplied reference footer is drawn as a static asset only, separately.
footer = back.split("if (c.textures.switch_rear_footer() != 0)",1)[1]
for word in ("PEGI", "HAC-P", "ESRB", "MADE IN JAPAN"):
    assert word not in footer, word
print("ENCORE_UI_SHOULDER_AND_COMPOSED_SLEEVES_PASS")
