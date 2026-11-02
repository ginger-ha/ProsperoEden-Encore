#!/usr/bin/env python3
"""Offline launch case-artwork wiring contract (host-only, no network)."""
from pathlib import Path
import math
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
service = (root / "headless/prosperoeden/pe/ui/services.hpp").read_text()
native = (root / "headless/prosperoeden/eden_services.cpp").read_text()
header = (root / "headless/prosperoeden/pe/ui/launcher.hpp").read_text()
launcher = (root / "headless/prosperoeden/pe/ui/launcher.cpp").read_text()
theme = (root / "headless/prosperoeden/pe/ui/theme.hpp").read_text()

assert "struct BoxArt" in service
assert "virtual BoxArt box_art(std::uint64_t)" in service
assert "pe::ui::BoxArt EdenServices::box_art(std::uint64_t title_id)" in native
native_resolver = native.split("pe::ui::BoxArt EdenServices::box_art(", 1)[1].split(
    "std::string EdenServices::game_path(", 1
)[0]
for fragment in (
    'Eden::CoversDir() + "/box-"',
    'artwork.front = find_face("front");',
    'artwork.back = find_face("back");',
    'artwork.spine = find_face("spine");',
    '"png", "jpg", "jpeg", "tga"',
    "stbi_info(path.c_str()",
    "info.st_size > (16LL << 20)",
):
    assert fragment in native_resolver, fragment
assert "MakeRequest" not in native_resolver

launch_setup = launcher.split("void Launcher::launch(", 1)[1].split(
    "void Launcher::press(", 1
)[0]
assert "services_.box_art(title_id)" in launch_setup
assert "launch_box_front_ = case_art.front;" in launch_setup
assert "launch_box_back_ = case_art.back;" in launch_setup
assert "launch_box_spine_ = case_art.spine;" in launch_setup
assert "launch_title_id_ = title_id;" in launch_setup
assert "launch_case_placeholder_mask_ = 0;" in launch_setup
assert "launch_case_ready_mask_ = 0;" in launch_setup
assert "EDEN_CASE_DRAW title=%016llX side=%s status=placeholder" in launcher
assert "EDEN_CASE_DRAW title=%016llX side=%s status=ready" in launcher
assert 'scan.empty() ? "fallback" : "retail"' in launcher
assert 'launch_case_ready_mask_ & face_bit' in launcher
assert "launch_description_" in launch_setup
assert "launch_screenshots_" in launch_setup
assert "launch_case_game_ = game;" in launch_setup
assert "textures_.clear_case_pages();" in launch_setup
# The initial full-bleed case front must enter the existing asynchronous
# source-decode queue BEFORE screenshots and large Hero. Same 704px bucket
# as the actual reconstructed renderer: no added synchronous GL decode.
prewarm = 'textures_.cover(*front, 704.0f)'
assert "case_media::FrontPaper(" in launch_setup
assert launch_setup.count(prewarm) == 1
assert launch_setup.index(prewarm) < launch_setup.index('textures_.cover(shot, 760.0f)')
assert launch_setup.index(prewarm) < launch_setup.index('textures_.cover(launch_hero_, 1920.0f)')
assert "launch_composed_front_ = 0;" in launch_setup
assert "launch_composed_back_ = 0;" in launch_setup
assert "textures_.cover(launch_box_front_, 760.0f)" in launch_setup
assert "textures_.cover(launch_box_back_, 760.0f)" in launch_setup
assert "textures_.cover(launch_box_spine_, 760.0f)" in launch_setup
assert "Common::Net" not in launch_setup

draw = launcher.split("void Launcher::draw_launch(", 1)[1].split(
    "void Launcher::draw(", 1
)[0]
for fragment in (
    "const std::string& scan = back ? launch_box_back_ : launch_box_front_;",
    "const Cover artwork = scan.empty() ? Cover{} : c.textures.cover(scan, 760.0f);",
    "c.list.case_face(artwork.texture, face, angle, back, kWhite, paper_uv);",
    "c.list.case_spine(side_strip, angle, case_depth,",
    "const bool inputs_ready = composed_case_face_ready(",
    "const Rect physical{374.0f, 126.0f, 454.0f, 730.0f};",
    "c.textures.brand()",
    "motion() > 0.0f",
    'tr("STARTING")',
):
    assert fragment in draw, fragment
assert "MakeRequest" not in draw
assert "progress%" not in draw
# Missing box art follows the same native, source-independent compositing as
# the Library. Rendered ink becomes ONE temporary texture on the existing 3D
# face; no separate geometry, loader or network request is introduced.
for fragment in (
    "draw_composed_case_face(ink, launch_case_game_",
    "c.textures.render_case_page(",
    "if (decoded.texture != 0 ||",
    "const bool use_composed = artwork.texture == 0 && composed_page != 0;",
    "c.list.case_face(composed_page, face, angle, back, kWhite,",
    "{0.0f, 1.0f, 1.0f, -1.0f}",
    "EDEN_CASE_COMPOSE title=%016llX side=%s status=%s page=%u",
    "const bool inputs_ready = composed_case_face_ready(",
):
    assert fragment in draw, ("native composed 3D jacket contract", fragment)
assert draw.index("if (use_composed)") < draw.index("} else if (!scan.empty() && artwork.texture != 0)")
# A valid authentic scan always supersedes provisional reconstruction;
# a failed scan may fall back, and partially decoded game images refresh
# the same FBO instead of allocating new textures every 60Hz tick.
assert "if ((page != 0 && !provisional) ||" in draw
assert "(page == 0 && attempted) || failures >= 3u" in draw
assert "if (!case_media::PageInputReady(page != 0, inputs_ready, seconds))" in draw
assert "provisional = !inputs_ready;" in draw
assert "print, c.fonts.font, c.fonts.texture, paper_w, paper_h, page);" in draw
assert "bool launch_composed_front_provisional_ = false;" in header
assert "bool launch_composed_back_provisional_ = false;" in header
assert "launch_composed_front_provisional_ = false;" in launch_setup
assert "launch_composed_back_provisional_ = false;" in launch_setup
assert "attempted = true;" in draw
assert "launch_composed_front_attempted_ = false;" in launch_setup
assert "launch_composed_back_attempted_ = false;" in launch_setup
# A failed compositor FBO can be transient. Each missing physical face may
# retry at most twice after its initial failure; neither a retail scan nor a
# successful composed face is ever regenerated inside the 60 Hz draw loop.
for name in ("front", "back"):
    assert f"launch_composed_{name}_failures_ = 0;" in launch_setup
    assert f"launch_composed_{name}_retry_after_ = 0.0f;" in launch_setup
    assert f"unsigned launch_composed_{name}_failures_ = 0;" in header
    assert f"float launch_composed_{name}_retry_after_ = 0.0f;" in header
for marker in (
    "if (seconds < retry_after) return;",
    "if (rendered == 0) {",
    "++failures;",
    "if (failures < 3u)",
    "attempted = false;",
    "retry_after = seconds + 0.25f * static_cast<float>(failures);",
):
    assert marker in draw, ("bounded transient compositor retry missing", marker)
assert "const std::string& scan = back ? launch_box_back_ : launch_box_front_;" in draw
assert "std::vector<std::string> launch_screenshots_;" in header
assert "constexpr float kCaseBackHold = 4.50f;" in theme
assert "constexpr float kCaseTurnSeconds = 0.72f;" in theme
assert "constexpr float kCaseBackHold = 4.50f;" in theme
assert "s.wait(0.51f); // instantaneous ~90-degree spine glimpse, no dwell" in (
    root / "headless/prosperoeden/host/preview_main.cpp").read_text()
assert "constexpr float kLaunchSeconds = kCaseFrontHold" in theme

# The temporary FBO painter must be bounded (two faces) and cleaned up
# when changing titles or leaving the native OpenGL context.
textures_h = (root / "headless/prosperoeden/pe/ui/textures.hpp").read_text()
textures_cpp = (root / "headless/prosperoeden/pe/ui/textures.cpp").read_text()
library_src = (root / "headless/prosperoeden/pe/ui/library.cpp").read_text()
widgets_src = (root / "headless/prosperoeden/pe/ui/widgets.hpp").read_text()
for token in ("case_pages_.size() >= 2", "glCheckFramebufferStatus(GL_FRAMEBUFFER)",
              "glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(old_fbo));",
              "glDeleteFramebuffers(1, &framebuffer);",
              "glIsEnabled(GL_SCISSOR_TEST)",
              "if (old_scissor) glEnable(GL_SCISSOR_TEST);",
              "case_pages_.push_back(ink);",
              "clear_case_pages();"):
    assert token in textures_cpp, token
for token in ("render_case_page(", "void clear_case_pages();"):
    assert token in textures_h, token
assert "draw_composed_case_face(Canvas &c, const Game &game," in widgets_src
assert "draw_composed_case_face(Canvas &c, const Game &game," in library_src
assert "flat_front_fallback(c, game, paper);" in library_src
assert "flat_back_fallback(c, game, paper);" in library_src
assert "bool composed_case_face_ready(Textures &textures, const Game &game," in widgets_src
assert "bool composed_case_face_ready(Textures& textures, const Game& game," in library_src
assert 'const auto shots = case_media::BackScenes(' in library_src
assert 'if (shots[0] && !ready(*shots[0], paper_w)) return false;' in library_src
assert 'if (shots[1] && !ready(*shots[1], std::max(left_w - gap, top_h)))' in library_src
assert 'if (shots[2] && !ready(*shots[2], paper_w))' in library_src
assert 'prepare_case_page(false);' in draw
assert 'prepare_case_page(true);' in draw
assert 'Color::rgb(0x08111d, 0.45f)' in library_src
assert 'c.list.gradient_rect({r.x, r.y, r.w, dynamic_h}, 0.0f,' in library_src
assert 'c.list.hgradient_rect(' not in library_src.split("void flat_back_fallback(", 1)[1].split("// Static sleeve used", 1)[0]
assert 'c.list.hgradient_rect(description' not in library_src
assert 'Color::rgb(0x030507, 0.98f)' not in library_src


# A cached original face is authoritative even while its texture is pending.
# Independent reconstruction occurs ONLY for the specific missing face.
assert "if (decoded.texture != 0 ||" in draw
assert "(!decoded.missing && seconds < 4.0f)" in draw
assert "const bool use_composed = artwork.texture == 0 && composed_page != 0;" in draw
assert "if (scan.empty() || artwork.texture == 0)" not in draw
assert "if (rear)\n                flat_back_fallback(c, game, paper);" not in library_src
assert 'if (std::getenv("PE_PREVIEW_NO_BOX_FRONT") == nullptr)' in (
    root / "headless/prosperoeden/host/fake_services.cpp").read_text()
assert 'if (std::getenv("PE_PREVIEW_NO_BOX_BACK") == nullptr)' in (
    root / "headless/prosperoeden/host/fake_services.cpp").read_text()
# User-provided fixed raster parts must be in the repo AND converted for
# preview and PS5 packaging, not merely named by dormant renderer branches.
import base64
import hashlib
import struct
for stem, wh, digest in (
    ("switch-logo", (193, 190),
     "e4299753479b26855f3817806e77c6710295a30b96add0f6e38ba83b66a1868d"),
    ("switch-rear-footer", (600, 286),
     "3b8cd6f6a3af33f986e0539ac8a6e305582f5746d60d433e4eee4d18d209171c"),
):
    packed = (root / f"headless/prosperoeden/ui/art/{stem}.png.b64").read_text().strip()
    raw = base64.b64decode(packed, validate=True)
    assert raw[:8] == bytes((137, 80, 78, 71, 13, 10, 26, 10))
    assert struct.unpack(">II", raw[16:24]) == wh
    assert hashlib.sha256(raw).hexdigest() == digest, stem
loader = (root / "headless/prosperoeden/pe/ui/textures.cpp").read_text()
for fragment in ('load("art/switch-logo.tga", &switch_logo_)',
                 'load("art/switch-rear-footer.tga", &switch_rear_footer_)',
                 '&switch_logo_, &switch_rear_footer_'):
    assert fragment in loader
# Host and PS5 packaging MUST reproduce the same gold reference seal ink.
# A source-only grayscale conversion would silently lose this fixed element.
render_fixed = (root / "tools/launcher/render-art.py").read_text()
assert 'ink[x, y] = (175, 136, 76, alpha)' in render_fixed
assert "brand fixed" in (root / "tools/launcher/preview.sh").read_text()
package = (root / "tools/package-headless-native.sh").read_text()
for fragment in ("for stem in switch-logo switch-rear-footer; do",
                 "base64.b64decode", "tga:bits-per-pixel=32",
                 "-region '82x80+182+195'", "-fill '#af884c'"):
    assert fragment in package

# Quarter turn becomes an edge; the full back is visible half a turn later.
assert math.cos(0.52) > 0 and math.sin(0.52) > 0
assert math.cos(math.pi + 0.18) < -0.98
assert math.sin(math.pi + 0.18) < 0
assert math.cos(2.0 * math.pi + 0.52) > 0
library = (root / "headless/prosperoeden/pe/ui/library.cpp").read_text()
assert "game.box_front" in library and "game.box_back" in library
assert "library_back_zoom_" in library and "library_back_focused_" in library
assert "library_format(game->format)" in library
assert "library_size(game->size)" in library
assert "library_date(game->release_date" in library
assert "library_genres(game->categories)" in library
# The obsolete footer hint was removed from the UI: keep this invariant
# in the rear-cover checks below, rather than requiring stale text here.
assert 'tr("Enlarge cover")' in library
assert "flat_retail_sleeve(c, *game, art, true, 0.60f);" in library
assert "flat_retail_sleeve(c, *game, enlarged, true, 0.92f," in library
assert "library_back_scale_);" in library
assert "std::max(paper.w, paper.h) * texture_scale" in library
assert "fitted.x += paper.w - fitted.w;" in library
assert "if (!rear) {" in library
assert "uv.w = target / source;" in library
assert "uv.h = source / target;" in library
assert "c.list.image(artwork.texture, fitted, {0.0f, 0.0f, 1.0f, 1.0f}," in library
assert "Rect fitted = paper;" in library and "if (source > target)" in library
assert "paper_uv.x = (1.0f - paper_uv.w) * 0.5f;" in draw
assert "flat_retail_sleeve(c, game, sleeve, false, 0.24f);" in library
assert "const Rect paper{shell.x + (rear ? side : 0.0f), shell.y + top," in library
assert "flat_back_fallback(c, game, paper);" in library
assert "flat_front_fallback(c, game, paper);" in library
# No retail face: compose the real game images and description into a
# dynamic sleeve rather than leaving a square app icon on a blank backdrop.
front = library.split("void flat_front_fallback(", 1)[1].split(
    "void flat_back_fallback(", 1)[0]
back_fallback = library.split("void flat_back_fallback(", 1)[1].split(
    "// Static sleeve used", 1)[0]
for token in ("game.hero", "game.cover", "game.screenshots", "reconstructed_cover(",
              "game.name", 'Color::rgb(0xe31930)', '"SWITCH"'):
    assert token in front, ("Front fallback dropped", token)
for token in ("case_media::FrontPaper(", "case_media::BackScenes(",
              "game.description", "text_block(c, desc,", "const Rect footer",
              "ENCORE / GAME INFORMATION"):
    assert token in back_fallback, ("Back fallback dropped", token)
assert 'c.textures.switch_logo() != 0' in front
assert 'const Rect logo{r.x, r.y, logo_w,' in front
assert 'if (painting) reconstructed_cover(c, *painting, r);' in front
assert 'reconstructed_paper(c, paper);' in library
assert 'case_media::BackScenes(' in back_fallback
assert 'case_media::BackScenes(' in library.split("bool composed_case_face_ready(",1)[1]
assert 'scene(game.cover,' not in back_fallback
assert 'case_art_contain(' not in back_fallback
assert 'case_art_contain(' not in library
assert 'c.list.hgradient_rect(' not in back_fallback
assert 'reconstructed_cover(c, *first, {r.x, r.y, r.w, dynamic_h});' in back_fallback
assert 'if (second)' in back_fallback
assert 'if (third)' in back_fallback
assert 'const std::string* third = shots[2];' in back_fallback
assert 'if (first)' in back_fallback
assert 'kReconstructedPaperRGB = 0x112235' in library
assert 'uv.w = target / source;' in library and 'uv.h = source / target;' in library
assert 'glClearColor(17.0f / 255.0f, 34.0f / 255.0f,' in textures_cpp
assert '53.0f / 255.0f, 1.0f);' in textures_cpp
assert 'const Cover artwork = scan.empty() ? Cover{} : c.textures.cover(scan, 760.0f);' in draw
assert 'std::string fallback;' not in draw
assert "if (artwork.texture != 0) {" in library
assert library.index("if (artwork.texture != 0) {") < library.index("flat_composed_ink(c, game, paper, rear);")
# The non-official fallback footer must never invent regulatory labels,
# game ratings or scan-style barcodes.
assert "const Rect footer" in back_fallback, "Back footer removed"
assert "if (c.textures.switch_rear_footer() != 0)" in back_fallback
assert "shell.y + shell.h - top" in library
# The fallback fixture must reach the same eleventh Library title as the
# retail-scan fixture. R1 now switches main tabs and cannot select this title.
preview = (root / "headless/prosperoeden/host/preview_main.cpp").read_text()
fallback = preview.split('if (const char* missing = std::getenv("PE_PREVIEW_LIBRARY_FALLBACK")', 1)[1].split(
    'if (const char* library_only', 1)[0]
assert 's.press({Key::right, Key::right, Key::right, Key::right, Key::right,' in fallback
assert 's.press({Key::r1, Key::r1});' not in fallback
assert 's.shoot("03-library-back-zoom-pan");' in (
    root / "headless/prosperoeden/host/preview_main.cpp").read_text()
assert "RADIO_INPUT_L2" in (root / "headless/prosperoeden/radio_input.h").read_text()
assert "RADIO_INPUT_R2" in (root / "headless/prosperoeden/radio_input.h").read_text()
assert "if (key == Key::circle)" in library
assert "{Pad::r2, TR(\"Zoom in\")}" in library
assert "{Pad::dpad, TR(\"Move cover\")}" in library

assert "PE_PREVIEW_LIBRARY_ONLY" in (
    root / "headless/prosperoeden/host/preview_main.cpp").read_text()
assert "case_face(artwork.texture, face, angle, back, kWhite, paper_uv);" in draw
assert "c.list.case_cap(" in draw and draw.index("c.list.case_cap(") > draw.index("c.list.case_face(artwork.texture")
assert "c.list.case_plastic(physical, angle, back, Color::rgb(0xd9e8f7, 0.93f));" in draw
assert draw.count("c.list.case_plastic(physical, angle, back") == 1
assert "for (int hinge" not in draw
assert "const float return_start = back_start + theme::kCaseBackHold;" in draw
assert "constexpr float kFrontYaw = 0.52f;" in draw
assert "constexpr float kBackYaw = 3.14159265358979323846f + 0.18f;" in draw
assert "case_depth, 3.2f" not in draw
assert "const bool printed_side_visible = std::sin(angle) >= 0.0f;" in draw
assert "Color::rgb(0xb61626, 0.78f)" not in draw
assert "c.list.case_spine(side_strip, angle, 3.2f," not in draw
indexer = (root / "tools/launcher/build-box-art-index.py").read_text()
workflow = (root / ".github/workflows/build-040-zbic.yml").read_text()
packager = (root / "tools/package-headless-native.sh").read_text()
assert '"Nintendo Switch", "Nintendo Switch 2"' in indexer
assert '"https://gamesdb-images.launchbox.gg"' in native
assert 'const bool r2 = filename.rfind("r2_", 0) == 0;' in native
assert "return FetchKnownNs2Front" not in native
# Execute the actual streaming Metadata.xml parser with both console types.
# No HTTP access or native console build needed for this self-test.
subprocess.run([sys.executable, str(root / "tools/launcher/build-box-art-index.py"),
                "--self-test"], check=True)
assert "Nintendo Switch" in indexer
assert "def candidates(items, limit=6):" in indexer
assert "fanart" in indexer and "title_screen" in indexer and "gameplay" in indexer
assert "Box - Front" in indexer and "Box - Back" in indexer
assert "gamesdb.launchbox-app.com/Metadata.zip" in indexer
assert "if len(matching) != 1:" in indexer
assert "SafeCaseFilename" in native
assert 'std::array<std::vector<std::string>, 6>' in native
# A physical scan remains independent; only missing backs use LaunchBox
# game-specific scenic art and all CDN traffic stays on the worker.
assert '"Screenshot - Gameplay"' in indexer
assert '"Fanart - Background"' in indexer
assert '"Screenshot - Game Title"' in indexer
assert 'EDEN_CASE_INDEX_MEDIA fanart={} game_title={} gameplay={} titles={}' in indexer
assert 'AppendCaseScenes(game.screenshots, game.title_id);' in native
assert 'side >= 3 && ValidNlibTga(CaseFacePath(title_id, "back"))' in native
assert 'const char* const names[]' in native
assert '"scene-1", "scene-2", "scene-3"' in native
assert "for (int side = 0; side < 6; ++side)" in native
assert 'scene_columns{"-", "-", "-"}' in native
assert "best_source = filename;" in native
assert "std::ofstream receipt(destination + \".source\"" in native
assert "cached_source == candidates.front()" in native
assert "best_pixels" not in native.split("bool FetchCaseFace(", 1)[1].split(
    "unsigned EnsureRetailCase(", 1)[0]
assert "EUROPE_FRONT_PINS" in indexer
assert "regional_candidates(front)" in indexer
assert 'region_code(element.findtext("Region", ""))' in indexer
assert '"north america": "us"' in indexer
assert 'region:filename' in native
assert "SafeCaseCandidate(part)" in native
assert "LocaleCaseCandidates(selected->second[side], language_choice, side)" in native
assert 'regions = {"us", "ca", "world", "uk", "eu", "fr"};' in native
assert 'regions = {"fr", "eu", "world", "uk", "ca", "us"};' in native
assert "face == 1" in native
assert "EnsureRetailCase(game.title_id, scanned_name, CleanTitle(game.file)," in native
assert "9524e5f7-ccc8-4ce6-a581-03f82c51825e.jpg" in indexer
assert "a8bcb4cc-a3b0-4cf0-82f3-cb10dd18b27c.jpg" in indexer
assert "BotW_NA_Switch_Box_Art" not in (root / "tools/launcher/preview-botw-media.py").read_text()
assert '"Box - Spine"' in indexer
assert "unsigned EnsureRetailCase(" in native
assert "RetailCaseIndex()" in native
assert 'Eden::AppResourceFile("ui/box-art-index.tsv")' in native
assert 'Eden::AppFile("ui/box-art-index.tsv")' not in native
assert '"EDEN_CASE_INDEX status=%s entries=%zu path=%s' in native
assert '"EDEN_CASE_FETCH status=unavailable' in native
assert '"EDEN_CASE_LOOKUP title=%016llX status=no-match' in native
assert '"EDEN_CASE_LOOKUP title=%016llX status=match' in native
assert "std::chrono::minutes(5)" in native
assert "std::chrono::hours(4)" not in native.split("unsigned EnsureRetailCase(", 1)[1].split("NlibEnrichment CachedNlibEnrichment(", 1)[0]
assert "both_faces_cached_at_start" not in native
# A competing background Home/Library request must wait for the atomic
# retail-case writer instead of disappearing behind the five-minute retry.
case_fetch = native.split("unsigned EnsureRetailCase(", 1)[1].split(
    "NlibEnrichment CachedNlibEnrichment(", 1
)[0]
assert "std::unique_lock guard(locks[title_id % locks.size()], std::defer_lock);" in case_fetch
assert "while (!guard.try_lock()) {" in case_fetch
assert "std::this_thread::sleep_for(std::chrono::milliseconds(50));" in case_fetch
assert "if (all_ready || (cancel && cancel->load(std::memory_order_acquire))) {" in case_fetch
assert "retries.erase(title_id);" in case_fetch
assert "all_ready = false;\n            break;" in case_fetch
assert "if (cancel && cancel->load(std::memory_order_acquire)) return 0;" in case_fetch
assert "if (cancel && cancel->load(std::memory_order_acquire)) {" in case_fetch
assert "return changed_faces;" in case_fetch
# The first successful front/back download permits the optional spine in the
# same background pass; no enforced five-minute wait for an empty case side.
assert 'if (side == 2 && !both_faces_cached_at_start &&' not in case_fetch
assert 'side >= 3 && ValidNlibTga(CaseFacePath(title_id, "back"))' in case_fetch
assert "attempts >= 3" in native
assert 'std::fprintf(stderr, "EDEN_CASE_FACE title=%016llX side=%d status=unavailable' in native
assert "const bool both_faces_cached_at_start =" not in native
# Preserve the already resident GPU jacket when a background metadata scan
# found the same file; explicitly distinguish successful front/back replacement.
service = (root / "headless/prosperoeden/pe/ui/services.hpp").read_text()
assert "unsigned case_artwork_changed = 0;" in service
case_fetch = native.split("unsigned EnsureRetailCase(", 1)[1].split(
    "NlibEnrichment CachedNlibEnrichment(", 1
)[0]
assert "changed_faces |= (1u << side);" in case_fetch
assert "return changed_faces;" in case_fetch
assert "game.case_artwork_changed = EnsureRetailCase(" in native
assert "game.case_artwork_changed |= EnsureRetailCase(" in native
assert library.count("if (enriched.case_artwork_changed & 1u)") == 2
assert library.count("if (enriched.case_artwork_changed & 2u)") == 2
assert 'game.box_front = cached_case.front;' in native
assert 'game.box_back = cached_case.back;' in native
assert 'game.box_front = box.front;' in native
assert 'game.box_back = box.back;' in native
assert 'const bool opened = static_cast<bool>(input);' in native
assert "const pe::ui::BoxArt cached_case = box_art(game.title_id);" in native
case_worker = native.split("pe::ui::Game EdenServices::enrich_game_media(pe::ui::Game game,", 1)[1].split("pe::ui::BoxArt EdenServices::box_art(", 1)[0]
assert case_worker.index("EnsureRetailCase(game.title_id, scanned_name") < case_worker.index("EnsureNlibEnrichment(game.title_id")
# A generated retail TGA must not be fetched again merely because stb_image's
# format probe does not recognize the native loader's uncompressed BGRA TGA.
case_cache = native.split("unsigned EnsureRetailCase(", 1)[1].split("NlibEnrichment CachedNlibEnrichment(", 1)[0]
assert 'if (cached_source == candidates.front() && ValidNlibTga(path))' in case_cache
assert 'stbi_info(path.c_str(), &width, &height, &channels)' not in case_cache
assert 'std::fread(header, 1, sizeof(header), input)' in case_cache
staged_validator = (root / "tools/ci/check-staged-app.py").read_text()
assert 'case_index_source = source_ui / "box-art-index.tsv"' in staged_validator
assert 'case_index_staged = app / "ui/box-art-index.tsv"' in staged_validator
assert 'ui_expected.add("ui/box-art-index.tsv")' in staged_validator
assert 'if case_index_source.is_file():' in staged_validator
assert 'Common::Net::MakeRequest(' in native
assert '"https://images.launchbox-app.com"' in native
assert "EnsureRetailCase(game.title_id, game.name," in native
assert "1500.0f / width, 2100.0f / height" in native
assert "ValidNlibTga(path)" in native
assert "EnsureRetailCase(game.title_id, scanned_name, CleanTitle(game.file)," in native
assert 'IsFile(base + ".png")' in native
assert "ui/box-art-index.tsv" in workflow
assert "tools/launcher/build-box-art-index.py --download" in workflow
assert 'cp -a "$root/headless/prosperoeden/ui" "$app/ui"' in packager
assert "MakeRequest" not in launch_setup and "MakeRequest" not in draw
assert "launch_hero_ = game.hero;" in launcher
assert "launch_hero_ = home_.last_hero;" in launcher
assert "c.list.image(background.texture, kScreen, uv," in draw
assert "theme::kScrim.with_alpha(0.16f)" in draw
# Projective body and spine are shared geometry; game title only selects art.
assert "const std::string& scan = back ? launch_box_back_ : launch_box_front_;" in draw
assert "0x01007EF00011E000" not in draw
shapes = (root / "headless/prosperoeden/pe/gfx/draw_list.hpp").read_text()
drawlist = (root / "headless/prosperoeden/pe/gfx/draw_list.cpp").read_text()
shader = (root / "headless/prosperoeden/pe/gfx/gl_batch.cpp").read_text()
assert "case_face = 9" in shapes and "case_spine = 10" in shapes
assert "case_plastic = 11" in shapes
assert "case_cap = 12" in shapes
assert "case_corner = 13" in shapes
assert "case_spine_image = 14" in shapes
assert "case_spine_blank = 15" in shapes
assert "void DrawList::case_spine_blank(" in drawlist
assert "void DrawList::case_face(" in drawlist
assert "void DrawList::case_spine(" in drawlist
assert "void DrawList::case_plastic(" in drawlist
assert "void DrawList::case_cap(" in drawlist
assert "void DrawList::case_corner(" in drawlist
assert "void DrawList::case_spine_image(" in drawlist
assert "depth_offset * transform_.scale" in drawlist
assert "clip_w = max(0.65, 1.0 - pitched_z / 820.0)" in shader
assert "float pitched_y = world_y * cos(pitch) - z * sin(pitch);" in shader
assert "gl_Position = vec4(ndc.x * clip_w, -ndc.y * clip_w, 0.0, clip_w);" in shader
assert "1.0 - corner.x : corner.x" in shader
assert "shape == 9 || shape == 10 || shape == 11 || shape == 12" in shader
assert "else if (shape == 11)" in shader
assert "else if (shape == 12)" in shader
assert "else if (shape == 13)" in shader
assert "else if (shape == 14)" in shader
assert "else if (shape == 15)" in shader
assert "printed_side_visible" in draw
assert "c.list.case_spine_image(ink.texture, side_strip, angle," in draw
assert "True rounded corner" in shader
assert "float d = round_box(v_local, v_half, 0.0);" in shader
assert "float scan_inside = v_params.z > 0.5 ?" in shader
assert "paper_uv.h = source_aspect / target_aspect;" in draw
assert "paper_uv.w = target_aspect / source_aspect;" in draw
assert "paper_uv.y = (1.0f - paper_uv.h) * 0.5f;" in draw
assert "w < (narrow_spine ? 64 : 128)" in native
assert "h < (narrow_spine ? 600 : 200)" in native
assert "c.list.case_spine(side_strip, angle, 3.2f," not in draw
assert "c.list.case_spine_blank(side_strip, angle, case_depth," in draw
# Single paper wrap with one localized projected rim; no second full-face
# coating and no clear border at the rear's printed spine fold.
assert draw.count("c.list.case_plastic(physical, angle, back") == 1
assert "Color::rgb(0xe6effa, 0.38f)" not in draw
assert "case_spine({physical.x, y" not in draw
# Navigation in the enlarged Library viewer is not delegated to the game.
assert "key == Key::circle || key == Key::cross" not in library
assert "key == Key::l2 || key == Key::r2" in library
assert "library_back_pan_x_" in library and "library_back_pan_y_" in library
assert "list.push_clip(viewer);" in library
assert "list.push_transform(library_back_scale_" in library
assert "{Pad::circle, TR(\"Close\")}" in library
assert '{Pad::cross, TR("Close")}' not in library
assert "RADIO_INPUT_L2" in (root / "headless/prosperoeden/radio_input.c").read_text()
assert "RADIO_INPUT_R2" in (root / "headless/prosperoeden/radio_input.c").read_text()
assert "constexpr float kPaperSideInset = 7.0f;" in draw
assert "constexpr float kPaperTopInset = 13.0f;" in draw
assert "const Rect face{physical.x + kPaperSideInset," in draw
assert draw.count("const Rect face{") == 1
assert "const Rect side_strip = face;" in draw
assert "physical.h - 2.0f * kPaperTopInset" in draw
assert "physical.h - 2.0f * case_radius" not in draw
# The continuous WRAP must meet the spine without left/right paper margins.
# All three scanned faces share EXACTLY one physical Y interval. Front Z=0,
# spine Z=[0,-depth], back Z=-depth: there is no paper break at either seam.
assert "const Rect face{physical.x + kPaperSideInset," in draw
assert "physical.w - 2.0f * kPaperSideInset," in draw
assert "physical.h - 2.0f * kPaperTopInset};" in draw
assert "const Rect side_strip = face;" in draw
assert "c.list.case_face(0, physical" not in draw
assert "case_depth - 6.0f" not in draw
assert "2.5f" not in draw.split("void Launcher::draw_launch(", 1)[-1]
assert "c.list.case_spine(side_strip, angle, case_depth," in draw
assert "float d = round_box(v_local, v_half, 0.0);" in shader
assert "float radius = v_params.z > 0.5 ?" not in shader
assert "float from_edge = (1.0 - v_st.x)" in shader
paper_top, paper_bottom, side_lip, box_h, width, depth = 13.0, 13.0, 7.0, 730.0, 454.0, 44.0
paper_h = box_h - paper_top - paper_bottom
paper_l = side_lip
paper_r = width - side_lip
front_x = (paper_l, paper_r)
back_x = (paper_l, paper_r)
spine_x = (paper_l, paper_r)
spine_z = (0.0, -depth)
front_z, back_z = 0.0, -depth
assert front_x == back_x == spine_x
assert spine_z == (front_z, back_z)
assert (paper_l, width - paper_r) == (7.0, 7.0)
assert paper_h == 704.0 and paper_top + paper_h == box_h - paper_bottom
lib_sleeve = library.split("void flat_retail_sleeve(", 1)[1].split(
    "std::string controller_profile_name(", 1)[0]
assert "const Rect paper{shell.x + (rear ? side : 0.0f), shell.y + top," in lib_sleeve
assert "shell.w - side, shell.h - 2.0f * top" in lib_sleeve
assert "const Cover artwork = scan.empty() ? Cover{} : c.textures.cover(" in lib_sleeve
assert "scan, std::max(paper.w, paper.h) * texture_scale);" in lib_sleeve
assert "const float other_x" not in lib_sleeve
assert "cover(c, scan, paper, 0.0f, 0.0f);" not in lib_sleeve
assert "c.list.image(artwork.texture, fitted, {0.0f, 0.0f, 1.0f, 1.0f}," in lib_sleeve
assert "Rect fitted = paper;" in lib_sleeve
assert "fitted.w = paper.h * source;" in lib_sleeve
assert "fitted.h = paper.w / source;" in lib_sleeve
assert "if (source > target) {" in lib_sleeve
assert "if (source < target) {" in lib_sleeve
assert "fitted.y += (paper.h - fitted.h) * 0.5f;" in lib_sleeve
assert "fitted.x += paper.w - fitted.w;" in lib_sleeve
assert "c.list.image(artwork.texture, paper, uv," in lib_sleeve
assert "const float side = shell.w * (7.0f / 454.0f);" in lib_sleeve
# The 2D library's case geometry and reconstruction are independent of a
# retail source's aspect ratio and use the 3D launcher's paper coordinates.
# Original scans remain entirely visible, aspect-contained in a fixed shell.
shelf_height = 346.0
shelf_width = shelf_height * (454.0 / 730.0)
paper_side = shelf_width * (7.0 / 454.0)
paper_top = shelf_height * (13.0 / 730.0)
actual_paper_aspect = (shelf_width - paper_side) / (shelf_height - 2*paper_top)
assert abs(actual_paper_aspect - 447.0/704.0) < 1.e-6
assert "const float sleeve_w = sleeve_h * kCaseShellAspect;" in library
assert "const Cover front_scan = game.box_front.empty() ? Cover{} :" not in library
assert "list.push_transform(1.0f, x + sleeve_w * 0.5f," in library
assert "selected ? 1.025f : 1.0f" not in library
assert "constexpr float kCaseInkWidth = 440.0f;" in library
assert "constexpr float kCaseInkHeight = 704.0f;" in library
assert "const float scale = std::min(paper.w / kCaseInkWidth," in library
assert "draw_composed_case_face(c, game," in library
assert "flat_composed_ink(c, game, paper, rear);" in lib_sleeve

# A missing face is laid out in 440x704 coordinates in both UI surfaces.
# The launcher uses the same draw_composed_case_face entry point at 440x704.
assert 'draw_composed_case_face(ink, launch_case_game_,' in draw
assert '{0.0f, 0.0f, 440.0f, 704.0f}, rear);' in draw
assert 'const float top = shell.h * (13.0f / 730.0f);' in lib_sleeve
assert "Rect uv{0.0f, 0.0f, 1.0f, 1.0f};" in lib_sleeve
assert "if (!rear) {" in lib_sleeve
assert "c.list.image(artwork.texture, fitted, {0.0f, 0.0f, 1.0f, 1.0f}," in lib_sleeve
# The row label must finish before the detail panel begins. No overprinting
# text onto the scan, and no loss of the cover's printed header/footer.
shelf_top, detail_top = 204.0, 620.0
shelf_bottom = shelf_top + shelf_height
assert shelf_bottom + 6.0 + 24.0 < detail_top
assert abs(shelf_width/shelf_height - 454.0/730.0) < 1.e-6
assert 'const Rect detail{72.0f, 620.0f, 1776.0f, 276.0f};' in library
assert 'constexpr float shelf_y = 551.0f;' in library
# The rear detail/zoom case is NEVER wider or shorter for one game.
assert "constexpr float rear_h = 247.0f;" in library
assert "constexpr float rear_w = rear_h * kCaseShellAspect;" in library
assert "const Rect art{280.0f - rear_w, 882.0f - rear_h, rear_w, rear_h};" in library
assert "const Cover back_scan = game->box_back.empty() ? Cover{} :" not in library
assert "const Rect enlarged{960.0f - 807.0f * kCaseShellAspect * 0.5f," in library
assert 'tr("Down: view back cover")' not in library
for height in (247.0, 346.0, 807.0):
    width = height * (454.0/730.0)
    side = width * 7.0/454.0
    top = height * 13.0/730.0
    assert abs((width - side)/(height - 2.0*top) - 447/704) < 1.e-6

# The 3D caps run the SAME 13px plastic skirt on either projected face.
assert "float from_cap = min(v_st.y, 1.0 - v_st.y)" in shader
assert "max(rim_intensity, cap_intensity)" in shader
assert "shell.w - side, shell.h - 2.0f * top" in lib_sleeve
assert "const float opening_x = rear ? shell.x : shell.x + shell.w - side;" in lib_sleeve

assert "c.list.bordered_rect(shell, radius" not in lib_sleeve
assert "const float opening_x = rear ? shell.x : shell.x + shell.w - side;" in lib_sleeve
assert "const float glint_x = rear ? opening_x : opening_x + side - highlight_w;" in lib_sleeve
assert "c.list.gradient_rect(shell, radius" in lib_sleeve
assert "for (int i = 1; i < 5; ++i)" in lib_sleeve
assert "color.rgb = vec3(0.97, 0.025, 0.07);" not in shader
assert "float from_edge = (1.0 - v_st.x)" in shader
assert "float outer_glint" in shader
assert "float from_cap = min(v_st.y, 1.0 - v_st.y)" in shader
assert "float cap_band = 1.0 - smoothstep(11.5, 13.2, from_cap);" in shader
assert "float cap_outer = exp(" in shader
assert "float cap_inner = exp(" in shader
assert "max(rim_intensity, cap_intensity)" in shader
assert "round_box(v_local, v_half, 22.0)" in shader
assert "v_border.x > 0.5 && v_params.y < 0.5" not in shader
assert "float inner_ridge" in shader
assert "vec4(material, v_top.a *" in shader
assert "simplify_switch_header" not in shapes and "simplify_switch_header" not in drawlist
assert "float inner_ridge = exp(" in shader
assert "angle, false, case_depth," in draw
assert "Color::rgb(0xe9f3ff, 0.79f)" in draw
assert "Color::rgb(0xddeaf8, 0.78f)" in draw
assert "c.list.case_corner(physical, angle, case_radius, case_depth," in draw
assert "constexpr float case_depth = 44.0f;" in draw
assert "float depth = a_params.y > 0.5 ? 44.0 : 0.0;" in shader
assert "constexpr float case_radius = 22.0f;" in draw
assert "float inner_ridge = exp(" in shader
assert "float grazing = 0.15 + 0.20" in shader
assert "case_depth * std::abs(std::sin(angle))" in draw
assert "if (!selected_game_.empty()) {\n        draw_launch(c);\n        return;" in launcher
preview_source = (root / "headless/prosperoeden/host/preview_main.cpp").read_text()
preview_workflow = (root / ".github/workflows/launcher-production-preview.yml").read_text()
assert 'PE_PREVIEW_BOTW: "1"' in preview_workflow
assert "tools/launcher/preview-botw-media.py" in preview_workflow
assert "00-launch-case-front" in preview_source
assert "01-launch-case-spine" in preview_source
assert "02-launch-case-back" in preview_source
assert "PE_PREVIEW_NO_BOX_SCANS" in preview_workflow
assert "UNIVERSAL_CASE_NO_RETAIL_ART: PASS" in preview_workflow
assert "const float return_start = back_start + theme::kCaseBackHold;" in draw
assert "angle = kBackYaw;" in draw
assert "const Cover ink = c.textures.cover(launch_box_spine_, 760.0f);" in draw
assert "std::string fallback;" not in draw
assert "constexpr float kPaperSideInset = 7.0f;" in draw
assert "constexpr float kPaperTopInset = 13.0f;" in draw
assert "const Rect face{physical.x + kPaperSideInset," in draw
assert draw.count("const Rect face{") == 1
assert "int side = 0" in shapes
assert "a_extra.x < -0.5 ? -0.5 :" in shader
assert "botw-back.tga" in (root / "tools/launcher/preview-botw-media.py").read_text()
assert "4b815db4-d2d1-4587-89c7-f82524750914.jpg" in (
    root / "tools/launcher/preview-botw-media.py").read_text()
assert "source_replacement_guard" not in native
assert "textures_.invalidate(enriched.box_front);" in library
assert "textures_.invalidate(enriched.box_back);" in library
assert '"https://images.launchbox-app.com/9524e5f7-ccc8-4ce6-a581-03f82c51825e.jpg"' in (
    root / "tools/launcher/preview-botw-media.py").read_text()
assert 'EUROPE_FRONT_PINS["79189"]' in indexer or '"79189": (' in indexer
assert 'region_code' in indexer and 'REGION_ORDER' in indexer
assert "LocaleCaseCandidates" in native

# Compile and invoke the actual launcher decoder on a generated retail-case
# BGRA TGA, not a hand-written Python approximation of its file contract.
# This is still a host-only decoder check, not evidence of PS5 GL upload.
compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
if not compiler:
    raise RuntimeError("native case decoder contract needs a host C++ compiler")
with tempfile.TemporaryDirectory(prefix="encore-retail-tga-") as workspace:
    temp = Path(workspace)
    source = temp / "case_decode.cpp"
    binary = temp / "case_decode"
    case_file = temp / "case.tga"
    width, height = 128, 200
    header = bytearray(18)
    header[2] = 2  # Uncompressed, true-color
    header[12:14] = width.to_bytes(2, "little")
    header[14:16] = height.to_bytes(2, "little")
    header[16] = 32  # BGRA
    header[17] = 0x28  # top-left origin and 8 alpha bits
    # Different top and bottom scanlines exercise the actual orientation.
    top = bytes((0x11, 0x22, 0x33, 0xff))
    bottom = bytes((0x44, 0x55, 0x66, 0xee))
    case_file.write_bytes(header + top * (width * (height // 2)) +
                          bottom * (width * (height // 2)))
    source.write_text(r"""
#include "pe/gfx/image.hpp"
#include <cstddef>
#include <cstdint>
int main(int argc, char** argv) {
    if (argc != 2) return 1;
    pe::gfx::Image image;
    if (!pe::gfx::load_tga(argv[1], &image)) return 2;
    if (image.width != 128 || image.height != 200) return 3;
    if (image.rgba.size() != 128u * 200u * 4u) return 4;
    const auto is_pixel = [&](std::size_t y,
                              std::uint8_t r, std::uint8_t g,
                              std::uint8_t b, std::uint8_t a) {
        const std::size_t i = 4 * (y * 128);
        return image.rgba[i] == r && image.rgba[i + 1] == g &&
               image.rgba[i + 2] == b && image.rgba[i + 3] == a;
    };
    if (!is_pixel(0, 0x33, 0x22, 0x11, 0xff)) return 5;
    if (!is_pixel(199, 0x66, 0x55, 0x44, 0xee)) return 6;
    pe::gfx::Image small = pe::gfx::halve(image);
    if (small.width != 64 || small.height != 100) return 7;
    if (small.rgba[0] != 0x33 || small.rgba[1] != 0x22 ||
        small.rgba[2] != 0x11 || small.rgba[3] != 0xff) return 8;
    return 0;
}
""", encoding="utf-8")
    subprocess.run([
        compiler, "-std=c++17", "-O0",
        "-I", str(root / "headless/prosperoeden"),
        str(source),
        str(root / "headless/prosperoeden/pe/gfx/image.cpp"),
        "-o", str(binary)
    ], check=True, capture_output=True, text=True)
    subprocess.run([str(binary), str(case_file)], check=True,
                   capture_output=True, text=True)
    # The same native loader also accepts a bottom-up physical scan.
    header[17] = 0x08  # 8-bit alpha, bottom-left origin
    case_file.write_bytes(header + bottom * (width * (height // 2)) +
                          top * (width * (height // 2)))
    subprocess.run([str(binary), str(case_file)], check=True,
                   capture_output=True, text=True)
    # An interrupted atomic download can leave a short body. It must never
    # be accepted by the UI decoder as a valid texture.
    case_file.write_bytes(header + top * 4)
    truncated = subprocess.run([str(binary), str(case_file)],
                               capture_output=True, text=True)
    assert truncated.returncode == 2, truncated.returncode
print("PASS native-format BGRA retail TGA decoder, orientation and truncation (host only)")

print("PASS regional fronts/backs, case geometry and zoom/pan source contracts")
