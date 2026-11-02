#!/usr/bin/env python3
from pathlib import Path
import re
root=Path(__file__).resolve().parents[1]
def read(path): return (root/path).read_text()
home=read('headless/prosperoeden/pe/ui/home.cpp')
library=read('headless/prosperoeden/pe/ui/library.cpp')
settings=read('headless/prosperoeden/pe/ui/settings.cpp')
browse=read('headless/prosperoeden/pe/ui/browse.cpp')
launcher=read('headless/prosperoeden/pe/ui/launcher.cpp')
launcher_h=read('headless/prosperoeden/pe/ui/launcher.hpp')
widgets=read('headless/prosperoeden/pe/ui/widgets.cpp')
widgets_h=read('headless/prosperoeden/pe/ui/widgets.hpp')
mapping=read('headless/prosperoeden/pe/ui/mapping.cpp')
services=read('headless/prosperoeden/eden_services.cpp')
presets=read('headless/prosperoeden/pe/ui/video_presets.hpp')
store=read('headless/settings_store.h')
# FPS readout is opt-in on a fresh install; diagnostics continue running
# independently. Respect an already-saved choice rather than clearing prefs.
ui_preferences=read('headless/prosperoeden/pe/ui/services.hpp')
for source in (store, ui_preferences):
    assert re.search(r'^\s*bool hud = false;', source, re.MULTILINE)
assert 'result.hud = Settings::Bool(document, Json::json_pointer("/video/fps_overlay"), result.hud);' in store
assert 'document["video"]["fps_overlay"] = value.hud;' in store
assert '{tr("FPS OVERLAY"), on_off(prefs_.hud)}' in settings
devices=read('headless/devices.h')
pad=read('headless/pad.cpp')
main=read('headless/main.cpp')
staged_check=read('tools/ci/check-staged-app.py')
generated=read('headless/encore_overrides_generated.h')

# One TV shell everywhere.
assert 'void Launcher::draw_top_nav' in launcher
for call in ('draw_top_nav(c, 0','draw_top_nav(c, 1','draw_top_nav(c, 3'):
    assert call in home+library+settings, call
assert 'list.hgradient_rect(r, 19.0f' in launcher
assert 'theme::kFocusBlue.with_alpha(0.96f)' in launcher
assert 'static constexpr const char* labels[] = {TR("Home"), TR("Library"), TR("Recent")};' in launcher
assert 'settings_gear(c, gx, gy, 19.0f, ink);' in launcher
assert 'constexpr float avatar_x = 1640.0f, avatar_y = 70.0f;' in launcher
# Account artwork is discovered read-only for the foreground user. It must
# never be queried or decoded on the draw path, and must gracefully fall back.
assert 'profile_avatar_scan_ = std::async(std::launch::async' in launcher
assert 'profile_avatar_scan_.wait_for(std::chrono::seconds(0))' in launcher
assert 'profile_avatar_scan_.wait();' in launcher
assert 'list.rounded_image(avatar.texture,' in launcher
assert 'std::future<ProfileAvatarProbe> profile_avatar_scan_;' in launcher_h
assert 'static ProfileAvatarProbe probe_profile_avatar(Services &services);' in launcher_h
assert 'profile_avatar_refresh_elapsed_ >= 5.0f' in launcher
assert 'textures_.invalidate(profile_avatar_path_)' in launcher
assert 'probe.inode' in launcher and 'probe.mtime' in launcher
assert 'virtual std::string profile_avatar() { return {}; }' in ui_preferences
assert 'sceUserServiceGetForegroundUser(&user_id)' in services
# The prefix is deliberately constructed only after the foreground user ID
# has been resolved. Checking the old literal /0x path rejected the safer
# multi-revision cache lookup without exercising its actual owner boundary.
assert 'sceUserServiceGetForegroundUser(&user_id)' in services
assert '"/system_data/priv/cache/profile/"' in services
assert 'for (const char* prefix : {"0x", "0X", ""})' in services
assert 'avatar128.dds' in services and 'avatar.png' in services
assert 'load_avatar_dds(resolved, image)' in services
assert 'localized_clock(services_.clock(), services_.language_region(prefs_.language))' in launcher
assert 'list.image(c.textures.brand(), {56.0f, 17.0f, 110.0f, 110.0f}' in launcher

# Home composition and controller-first navigation.
assert 'kHomeRecentMax = 7' in home
assert 'kHomeQuickPanel' in home
assert 'focus == kHomeQuickPanel' in home
assert 'Open quick settings' in home
assert 'constexpr std::array utility{kHomeQuickPanel, kHomeStorage, kHomeControllers, kHomeFullSettings}' in home
assert 'position == 0 && delta < 0' in home
assert 'utility[static_cast<std::size_t>((position + delta + 4) % 4)]' in home
# Regression: the connected-controller icons must not overlap the hero metadata chips.
assert '410.0f, 72.0f, 50.0f' in home
assert 'const Rect players_chip{552.0f, 406.0f, 210.0f, 36.0f}' in home
assert 'list.image(c.textures.brand(), {56.0f, 17.0f, 110.0f, 110.0f}' in launcher
assert 'Color::rgb(0xbb59ff)' in read('headless/prosperoeden/pe/ui/theme.hpp')
# Regression: do not remove the only width-measure helper while rearranging the hero.
assert 'text_width(c, chips[i], 18.0f)' in home
assert 'constexpr float kChipGap = 9.0f' in home
assert 'const float room = kHeroX + kHeroContentWidth - chip_x - kChipGap * 3.0f' in home
assert 'width *= factor' in home
assert 'if (focus == kHomeQuickPanel)' in home and 'focus = kHomeQuickFirst' in home
assert 'home_quick_edit_' in home and 'Pad::cross, TR("Edit")' in home
assert 'VIEW ALL GAMES' not in home
assert 'View all games' not in home
assert 'const Rect hero{0.0f, 0.0f, 1920.0f, 1080.0f}' in home
assert 'const Rect quick{' not in home and 'const Rect status{' not in home
for marker in ('kHomeStorage', 'kHomeControllers', 'kHomeFullSettings', 'quick_sheet',
               'utility_card(0', 'utility_card(1', 'utility_card(2', 'utility_card(3'):
    assert marker in home, marker
assert 'open_mapping(false)' in home
assert 'clear_shader_caches' not in home and 'clear_shader_caches' in settings
# PS5 startup safety: diagnostics is called synchronously by Launcher::Launcher before
# the first frame. Direct libc statfs/statvfs caused 0xa002030a on FW 13.60 in build #182.
assert 'Ps5ConsoleStorage' not in services
services_code = re.sub(r'/\*.*?\*/|//[^\n]*', '', services, flags=re.S)
assert 'statfs(' not in services_code and 'statvfs(' not in services_code
assert 'std::filesystem::space(Eden::AssetsDir(), error)' not in services
# Current async directory inventory retains the substantive FW13.60 fix,
# not an obsolete diagnostic's numeric error-code wording.
assert 'previously raised SYSTEM_ILLEGAL_FUNCTION_CALL' in services
assert 'result.storage_root = Eden::AssetsDir();' in services
assert 'TreeBytes(cache / "shader", cancel)' in services
assert 'TreeBytes(Eden::LogsDir(), cancel)' in services
assert 'home_diagnostics_.free_bytes' not in home  # no invented PS5 total capacity
assert 'home_diagnostics_.storage_root' in home

assert 'const std::string hero_artwork = !hero_banner.empty() ? hero_banner : hero_screenshot;' in home
# Hero content is game media only: banner -> screenshot -> opaque neutral fallback.
hero_draw = home[home.index('// ---- full-bleed cinematic game hero'):home.index('// Effective values:')]
assert 'const Cover hero_picture = c.textures.cover(hero_artwork, 1920.0f)' in hero_draw
assert 'list.image(hero_picture.texture, hero, uv' in hero_draw
assert 'if (hero_picture.texture != 0)' in hero_draw
assert 'hero_recent->cover' not in hero_draw and 'home_.last_cover' not in hero_draw
assert 'if (hero_picture.texture != 0)' in hero_draw
assert 'a solid' not in hero_draw.lower() or 'NOT a solid' in hero_draw
assert 'bool Launcher::press_top_nav(Key key)' in launcher
assert 'top_nav_focus_ = 3' in settings and 'top_nav_focus_ = 1' in library

# Cards: gameplay media first and no ugly language subtitle under recent titles.
assert 'recent.screenshot' in home
assert 'const std::string& art = !recent.cover.empty() ? recent.cover' in home
recent_block=home[home.index('// ---- recently played: seven-ish large artwork tiles'):home.index('// ---- compact system strip')]
assert 'recent.language' not in recent_block
assert 'const int shown = std::min<int>(kHomeRecentMax' in recent_block
assert 'constexpr float available = 1770.0f' in recent_block
assert 'card_w = (available - gap * 6.0f) / 7.0f' in recent_block

# The library now shows a 5-slot, controller-navigated retail sleeve shelf.
# Check the real geometry and navigation instead of a retired comment.
assert 'constexpr int slots = 5;' in library
assert 'constexpr float rail_x = 72.0f, rail_y = 204.0f, rail_w = 1776.0f;' in library
assert 'constexpr float sleeve_h = 346.0f;' in library
assert 'const float sleeve_w = sleeve_h * kCaseShellAspect;' in library
assert 'const Rect detail{72.0f, 620.0f, 1776.0f, 276.0f};' in library
assert 'constexpr float kCaseInkHeight = 704.0f;' in library
assert 'constexpr float kCaseInkWidth = 440.0f;' in library
assert 'flat_composed_ink(c, game, paper, rear);' in library
assert 'if (painting) reconstructed_cover(c, *painting, r);' in library
assert 'reconstructed_paper(c, paper);' in library
assert 'uv.w = target / source;' in library and 'uv.h = source / target;' in library
assert 'const float opening_x = rear ? shell.x : shell.x + shell.w - side;' in library
assert 'c.list.gradient_rect({shell.x, shell.y, shell.w, top}' in library
assert 'c.list.gradient_rect({shell.x, shell.y + shell.h - top,' in library
assert 'const float side = shell.w * (7.0f / 454.0f);' in library
assert 'c.list.image(artwork.texture, fitted, {0.0f, 0.0f, 1.0f, 1.0f},' in library
assert 'fitted.x += paper.w - fitted.w;' in library
assert 'c.list.image(artwork.texture, paper, uv,' in library
assert 'if (artwork.texture != 0) {' in library
assert 'flat_retail_sleeve(c, game, sleeve, false, 0.24f);' in library
assert 'flat_retail_sleeve(c, *game, art, true, 0.60f);' in library
assert 'flat_retail_sleeve(c, *game, enlarged, true, 0.92f,' in library
assert 'const float opening_x = rear ? shell.x : shell.x + shell.w - side;' in library
assert 'library_.move(key == Key::right ? 1 : -1)' in library
press_library=library[library.index('void Launcher::press_library'):library.index('void Launcher::draw_library')]
assert 'set_docked' not in press_library
assert 'game->screenshots' in library
assert 'category rail: one row, controller-first' in settings
assert browse.count('draw_top_nav(c, 3)') >= 3
assert 'draw_frame(c' not in browse
assert '1080p is recommended for stability and memory' not in settings
assert 'Game render scale. 1x is recommended' not in settings
assert 'PlayStation uses Cross=A and Circle=B' not in settings
assert '1x is the safe default' not in library

# Face button visuals: PS-style primitives and coloured symbols.
for name in ('cross','circle','square','triangle','dpad','l1','r1','l2','r2','l3','r3','options','create','touchpad'):
    assert f'Pad::{name}' in widgets_h or name in widgets_h, name
assert 'face_ink' in widgets
for rgb in ('0x55b7ff','0xff6b8a','0xe987ff','0x66e6a6'):
    assert rgb in widgets, rgb
assert 'physical_pad_icon' in mapping and 'draw_pad(c, icon' in mapping

# Micro-DA: glass depth, double edge, focus bloom, active-vs-focus differentiation.
for marker in ('Two-layer elevation','Inner hairline','Eden Encore luminous focus','kFocusCore','kFocusBlue'):
    assert marker in widgets+read('headless/prosperoeden/pe/ui/theme.hpp'), marker

# Nlib rich media: icon + banner + screenshots + metadata.
for marker in ('/banner/1080p','/screen/','/icon/512','fields=name,intro,description,publisher,developer,releaseDate',
               'CachedNlibScreens','result.screenshots','result.hero'):
    assert marker in services, marker
assert 'hero_description;' in home
assert 'hero_intro' not in home
# Artwork arrives in the background, possibly after its first texture lookup.
widgets_src = read('headless/prosperoeden/pe/ui/widgets.cpp')
textures_src = read('headless/prosperoeden/pe/ui/textures.cpp')
assert 'if (image.missing && c.textures.brand() != 0)' not in widgets_src
# Retry age is computed lazily per queried cover in the shipping launcher.
# Keep the first-load retry and never briefly discard the confirmed-missing
# cover state while its asynchronous refresh is queued.
assert 'uptime_seconds_ - it->second.loaded_at_seconds' in textures_src
assert 'it->second.loaded && it->second.texture == 0 &&' in textures_src
assert 'age >= retry_after' in textures_src
assert 'it->second.loaded_at_seconds = uptime_seconds_;' in textures_src
assert 'it->second.loaded || it->second.failed_loads != 0' in textures_src
# Visual regressions from actual 1920x1080 PS5 captures (2026-10-08): the
# Zelda title must not occupy the same vertical lines as its description.
# R385 screenshot geometry: one bounded hero column, readable title and
# semantic Nlib description truncation instead of the removed 1680px rail.
assert 'constexpr float kHeroX = 90.0f' in home
assert 'constexpr float kHeroContentWidth = 1250.0f' in home
assert 'text_shrink(c, title_label, kHeroX' in home
assert 'kTitleSize, theme::kTitle, kHeroContentWidth, Align::left, 0.0f, 0.45f)' in home
assert 'text_block_semantic(c, hero_caption, kHeroX' in home
assert 'theme::kBody, kHeroContentWidth, 2, 0.90f)' in home
assert 'label_area.x + label_area.w * 0.5f' in home
# Rear jacket remains in the lower details pane; its title begins at x=337,
# clear of the printed scan and its focus highlight.
assert 'constexpr float rear_w = rear_h * kCaseShellAspect;' in library
assert 'const Rect art{280.0f - rear_w, 882.0f - rear_h, rear_w, rear_h};' in library
assert '807.0f * kCaseShellAspect' in library
assert 'tr("Down: view back cover")' not in library
assert 'text_shrink(c, game->name, 337.0f, baseline(633.0f, 52.0f, 40.0f)' in library
assert 'text_block(c, game->name, 558.0f' not in library
assert 'kNlibCacheSchema = 3' in services
assert 'current_metadata_cache' in services
assert 'artwork_files.resize(6)' not in services
assert 'const int wanted_screens = std::clamp(screen_count, 0, 3);' in services
assert 'for (std::size_t offset = 0; offset < games_.size(); ++offset)' in library
assert 'game->screenshots' in library

# Controller contract after investigation of oscillating glyph/face-button
# contexts: select ONE effective per-title/global mapping before guest HID.
# The emulator cannot reliably infer in-game menu vs gameplay from HID and
# must not silently swap A/B/X/Y during cutscenes or popup transitions.
# Assert the actual fixed mapping, not the removed auto-context implementation.
assert 'void SetMapping(const ButtonMapping& value)' in devices
assert 'if (slots[0].handle >= 0) return;' in devices
assert 'pad->SetMapping(mapping);' in main
assert 'SetGameplayMapping' not in main + devices + pad
assert 'pad->Open()' in main
assert main.index('pad->SetMapping(mapping);') < main.index('if (!pad->Open())')
assert 'EDEN_PAD_MAPPING_FIXED title=%016llx' in main
assert 'EDEN_PAD_MAPPING_LOCKED scope=session mode=static game_actions=guest_owned' in main
assert 'EDEN_PAD_MAPPING_CONTEXT title=%016llx mode=game_owned' in main
assert '"EDEN_PAD_MAPPING_FIXED title="' in staged_check
assert '"EDEN_PAD_MAPPING_LOCKED scope=session mode=static game_actions=guest_owned"' in staged_check
assert '(effective_layout == 1 ? "Switch" : "PlayStation")' in main
assert 'SetAdaptivePlayStation' not in devices + main + pad
assert 'mapping_context.observe(' not in pad
assert 'menu_evidence' not in pad
assert '#ifdef EDEN_DEV_PROFILE\n        // Diagnostic input trace only.' in pad
assert 'frame_late_200' in read('headless/graphics.cpp')
assert 'frame_max_slow_streak' in read('headless/graphics.h')

# Four authored performance tiers + derived Custom.
for label in ('"Minimum"','"Recommended"','"High"','"Ultra"','"Custom"'):
    assert label in store
assert 'kAuthoredVideoProfiles = Eden::EncoreOverrides::kAuthoredProfileCount' in presets
assert 'VideoPresetForTitle' in presets


# Final Home polish contracts: full-bleed banner, explicit violet/teal values, local-player capacity,
# full-width recent rail, four utility cards and no permanent debug/dashboard column.
assert 'const Rect hero{0.0f, 0.0f, 1920.0f, 1080.0f}' in home
assert 'list.hgradient_rect(hero, 0.0f' in home
assert 'kAccentTeal' in read('headless/prosperoeden/pe/ui/theme.hpp')
assert 'tr("Max. players: {0}")' in home and 'std::to_string(hero_max_players)' in home
assert '552.0f, 406.0f, 210.0f, 36.0f' in home
assert 'float chip_x = hero_max_players > 0 ? 774.0f : 570.0f;' in home
assert 'gfx::mix(theme::kAccentTeal, theme::kTitle, f)' in home
assert 'constexpr float card_h = 214.0f' in home
assert '551.0f, card_w, card_h' in home
assert 'constexpr float utility_w = (1800.0f - utility_gap * 3.0f) / 4.0f' in home
assert 'std::array<tween::Spring, 23> home_springs_' in launcher_h
assert 'const bool quick_open' in home
assert 'begin_band(0, -16.0f);' in home[home.index('// Header must be composited AFTER'):]
assert 'fake CPU' not in home and 'Storage' in home


# Custom low-cost settings keep the light hidden runtime policy.
assert 'runtime_performance_profile' in main
assert 'effective_resolution_for_tuning <= Eden::kNativeResolution' in main
assert 'performance_policy.async_shaders && backend == Eden::GraphicsBackend::Vulkan' in main

# Nlib HTTP identity is applied as an audited pinned-Eden backport.
apply=(root/'tools/apply-eden-backports.sh').read_text()
net_patch=(root/'headless/backports/eden-ps5-net-user-agent.patch').read_text()
assert 'eden-ps5-net-user-agent.patch' in apply
assert 'Prospero.Eden-Encore/1' in net_patch and 'User-Agent' in net_patch

# The final staged-app checker must reference real Home focus identifiers. In
# run #37710086280 it required removed kHomeCache despite the native app passing
# all package inventory, import and compiled-string checks. Validate this contract
# in the early fast preflight, before consuming hours on another native build.
# Avoid another multi-hour native build failing on stale controller markers:
# the staged eboot must expose the fixed mapping diagnostics from main.cpp,
# not old PlayStation Auto / EDEN_PAD_CONTEXT strings removed from source.
assert '"EDEN_PAD_MAPPING_FIXED title="' in staged_check
assert '"EDEN_PAD_MAPPING_LOCKED scope=session mode=static game_actions=guest_owned"' in staged_check
assert '"EDEN_PAD_MAPPING_LOCKED scope=fc27 mode=dual_manual"' not in staged_check
assert '"PlayStation Auto"' not in staged_check
assert '"EDEN_PAD_CONTEXT mode=gameplay reason=sustained_activity sticky=1"' not in staged_check
match = re.search(r'assert all\(marker in home_source for marker in \((.*?)\)\)', staged_check, re.S)
assert match, 'staged-app Home focus contract has no explicit named marker list'
for marker in re.findall(r'"(kHome[^\"]+)"', match.group(1)):
    assert marker in home, f'staged-app checker references missing Home identifier: {marker}'

print('Encore UX/media/profile contracts: PASS')
