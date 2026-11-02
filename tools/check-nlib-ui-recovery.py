#!/usr/bin/env python3
from pathlib import Path
root = Path(__file__).resolve().parents[1]
def src(name): return (root / name).read_text()
svc = src("headless/prosperoeden/eden_services.cpp")
svc_h = src("headless/prosperoeden/eden_services.h")
svc_base = src("headless/prosperoeden/pe/ui/services.hpp")
lib = src("headless/prosperoeden/pe/ui/library.cpp")
home = src("headless/prosperoeden/pe/ui/home.cpp")
hdr = src("headless/prosperoeden/pe/ui/launcher.hpp")
nav = src("headless/prosperoeden/pe/ui/launcher.cpp")
settings_src = src("headless/prosperoeden/pe/ui/settings.cpp")
# Transient unavailability of the whole ROM directory cannot delete every title.
assert "virtual bool game_storage_available() { return true; }" in svc_base
assert "bool game_storage_available() override;" in svc_h
assert "bool EdenServices::game_storage_available()" in svc
assert 'std::filesystem::is_directory(Eden::AssetsPath("roms"), error)' in svc
assert "if (!services_.game_storage_available())" in lib
# A directory remaining mounted does not prove individual title stats
# succeeded. Any unexpected I/O or permission error invalidates the WHOLE
# scan; only a genuine missing path can be dropped.
scan_owner = svc.split("std::vector<pe::ui::Game> EdenServices::games(const", 1)[1].split(
    "pe::ui::Game EdenServices::", 1)[0]
stat_failure = scan_owner.split("if (stat(path.c_str(), &info) != 0)", 1)[1].split(
    "if (!S_ISREG(info.st_mode))", 1)[0]
assert "const int stat_error = errno;" in stat_failure
assert "stat_error != ENOENT && stat_error != ENOTDIR" in stat_failure
assert 'throw std::system_error{stat_error, std::generic_category(),' in stat_failure
assert "continue;" in stat_failure
assert stat_failure.index("throw std::system_error") < stat_failure.index("continue;")
# Compile/execute the EXACT production stat-error refusal expression
# instead of accepting a regex that would still swallow an EIO at runtime.
# Two optimization levels guard the ENOENT/ENOTDIR vs EIO/EACCES contract.
import subprocess
import tempfile
policy = "if (stat_error" + stat_failure.split("if (stat_error", 1)[1].split(
    "continue;", 1)[0]
cpp = """
#include <cassert>
#include <cerrno>
#include <system_error>
bool publish(int stat_error) {
    try {
""" + policy + """
    } catch (const std::system_error& error) {
        assert(error.code().value() == stat_error);
        return false;
    }
    return true;
}
int main() {
    assert(publish(ENOENT) && publish(ENOTDIR));
    assert(!publish(EIO) && !publish(EACCES) && !publish(ENODEV));
}
"""
with tempfile.TemporaryDirectory(prefix="encore-rom-stat-") as temp:
    source = Path(temp) / "stat_policy.cpp"
    source.write_text(cpp)
    for optimization in ("-O0", "-O2"):
        binary = Path(temp) / ("stat_policy" + optimization[2:])
        subprocess.run(
            ["c++", "-std=c++20", "-Wall", "-Wextra", "-Werror",
             optimization, str(source), "-o", str(binary)],
            check=True, capture_output=True, text=True)
        subprocess.run([str(binary)], check=True, capture_output=True, text=True)
assert "return errno != ENOENT && errno != ENOTDIR;" in svc
assert "if (lstat(path.c_str(), &info) == 0)" in svc
assert lib.count('if (!services_.game_storage_available())') == 2
assert 'missing.clear();' in lib
assert "bool ValidNlibTga(" in svc
# Cached media must be rejected if the full TGA header/payload is invalid,
# while an already valid image may still be refreshed when its TTL expires.
assert "return ValidNlibTga(path) ? path : std::string{};" in svc
assert "if (ValidNlibTga(path)) screens.push_back(path);" in svc
assert "if (!ValidNlibTga(path) || refresh_existing_artwork)" in svc
assert "info.st_size < 18" in svc
assert "info.st_size) >= bytes" in svc
assert "const bool sparse_metadata = current_metadata_cache" in svc
assert "metadata_expired || sparse_metadata" in svc
assert 'metadata["_encore_checked_at"] = now_seconds' in svc
assert "refresh_existing_artwork" in svc
assert "CachedNlibHero(title_id).empty()" in svc
assert "game.artwork_changed = enrichment.artwork_changed" in svc
assert "textures_.invalidate(enriched.hero)" in lib
assert "void Textures::invalidate(" in src("headless/prosperoeden/pe/ui/textures.cpp")
assert "EDEN_NLIB_ASSETS title_id=" in svc
assert "home_media_next_retry_" in hdr and "media_next_retry_" in hdr
assert "media_retry_timer_ >= 8.0f" in nav
# The physical sleeve prefers an original box scan; the fallback still
# permits a game to render with only its older cover/hero artwork.
assert "const std::string& scan = rear ? game.box_back : game.box_front;" in lib
assert "flat_front_fallback(c, game, paper);" in lib
# Actual absent-front paper intentionally fills its entire physical sleeve,
# using the same 440x704 ink renderer in Library and rotating 3D launch.
# The old floating aspect-fit art and its helper have been removed.
front_fallback = lib.split("void flat_front_fallback(", 1)[1].split(
    "void flat_back_fallback(", 1)[0]
assert 'const auto* painting = case_media::FrontPaper(' in front_fallback
assert 'if (painting) reconstructed_cover(c, *painting, r);' in front_fallback
assert 'reconstructed_paper(c, paper);' in lib
assert 'kReconstructedPaperRGB = 0x112235' in lib
assert 'const Rect logo{r.x, r.y, logo_w,' in front_fallback
assert "fit_fallback_art(" not in front_fallback
assert "case_art_contain(c, game.cover" not in front_fallback
assert "flat_composed_ink(c, game, paper, rear);" in lib
assert "if (image.missing) continue;" in lib
assert "Loading artwork" in home and "Artwork unavailable" in home
assert "text_shrink(c, title_label" in home
# R385 switched the hero's non-warning description to semantic ellipsis.
# Preserve the actual rendering and warning-priority contracts, rather
# than locking the test to an obsolete text_block() call.
assert "text_block_semantic(c, hero_caption" in home
assert "notice_block(c, hero_caption" in home
assert "if (hero_caption_warning)" in home
assert "hero_description;" in home
assert "label_area.w - 4.0f, Align::center" in home
assert 'TR("Recent")' in nav
# Regression from FC27 hardware tests: use the matching game's proper Nlib
# description before a short marketing intro after returning to the Hero.
# Genuinely missing-ROM/language warnings remain higher priority.
hero_types = src("headless/prosperoeden/pe/ui/services.hpp")
native_svc = src("headless/prosperoeden/eden_services.cpp")
native_hdr = src("headless/prosperoeden/eden_services.h")
assert "std::string last_description;" in hero_types
assert "std::string description; // detailed, title-keyed Nlib text for the Hero" in hero_types
assert "home.last_description = nlib.description;" in svc
assert "recent.description = nlib.description;" in svc
assert "home_.last_description = enriched.description;" in lib
assert "recent.description = enriched.description;" in lib
assert "home_.last_description = game.description;" in lib
assert "const std::string &hero_description =" in home
assert "hero_description;" in home
assert "hero_caption_warning ? home_.last_caption :" in home
# Never decompress or resize Nlib artwork inside the frame update.
texture_h = src("headless/prosperoeden/pe/ui/textures.hpp")
texture_cpp = src("headless/prosperoeden/pe/ui/textures.cpp")
assert "std::future<DecodedCover> decode_;" in texture_h
assert "decoded.ok = services_.load_image(path, &decoded.image);" in texture_cpp
assert "decode_ = std::async(std::launch::async" in texture_cpp
assert "it->second.generation == result.generation" in texture_cpp
assert "entry.texture = create(result.image);" in texture_cpp
assert "decode_.wait_for(std::chrono::seconds(0))" in texture_cpp
# Nlib media must be scaled on the decode worker to the dimensions the
# launcher actually draws. Otherwise every 300px card uploads a 1080p image.
assert "int target_pixels = 64;" in texture_cpp
assert "target_pixels *= 2;" in texture_cpp
assert "path + '#' + std::to_string(target_pixels)" in texture_cpp
assert "entry.target_pixels = target_pixels;" in texture_cpp
assert "const int target_pixels = it->second.target_pixels;" in texture_cpp
assert "std::max(decoded.image.width, decoded.image.height) >" in texture_cpp
assert "target_pixels * 3 / 2" in texture_cpp
assert "decoded.image = gfx::halve(decoded.image);" in texture_cpp
assert "int target_pixels = 64;" in texture_h
assert "kMaxTextureReclaimsPerFrame = 2" in texture_cpp
assert "reclaimed < kMaxTextureReclaimsPerFrame" in texture_cpp
# The old cache collected/sorted a vector of 160+ records every frame and
# erased the first item from a vector queue. Neither belongs in D-pad input.
assert "std::deque<std::string> queue_;" in texture_h
# Home controller *presence* is optional UI metadata; do not poll native
# device status at 60Hz while held-button/D-pad repeat animations run.
assert "float controller_poll_elapsed_ = 0.0f;" in hdr
assert "controller_poll_elapsed_ += dt;" in home
assert "controller_poll_elapsed_ >= 0.10f" in home
assert "poll ? (services_.controllers() & 0xfu) : controllers_" in home
assert "controller_lit_[index].update(dt, 10.0f);" in home

assert "queue_.pop_front();" in texture_cpp
# Repeated Nlib cover invalidations may accumulate stale FIFO requests.
# Limit the total dictionary lookups in a UI frame as well as GL deletes.
assert "constexpr std::size_t kMaxCoverQueueLookupsPerFrame = 24;" in texture_cpp
assert "std::size_t inspected = 0;" in texture_cpp
assert "while (!queue_.empty() && inspected < kMaxCoverQueueLookupsPerFrame)" in texture_cpp
assert "++inspected;" in texture_cpp
assert "queue_.erase(queue_.begin());" not in texture_cpp
assert "std::sort(order.begin(), order.end());" not in texture_cpp
assert "auto oldest = covers_.end();" in texture_cpp
assert "oldest->second.used" in texture_cpp
assert "covers_.erase(oldest);" in texture_cpp
# Nlib media replacement must NEVER burst-delete GPU textures on a
# single UI frame. Frame-time invalidation and cache eviction share a
# two-texture budget; release() drains all IDs before context teardown.
assert "std::deque<std::uint32_t> pending_deletes_;" in texture_h
invalidation = texture_cpp.split("void Textures::invalidate(", 1)[1].split(
    "void Textures::pump(", 1)[0]
assert "pending_deletes_.push_back(it->second.texture);" in invalidation
assert "batch_.delete_texture" not in invalidation
assert "deleted_this_frame < kMaxTextureReclaimsPerFrame" in texture_cpp
assert "deleted_this_frame + reclaimed < kMaxTextureReclaimsPerFrame" in texture_cpp
assert "pending_deletes_.pop_front();" in texture_cpp
release_entry = texture_cpp.split("void Textures::release()", 1)[1].split(
    "Cover Textures::cover(", 1)[0]
assert "for (const std::uint32_t texture : pending_deletes_)" in release_entry
assert "pending_deletes_.clear();" in release_entry



# A rare native frame overrun gets one bounded phase label (no noisy per-frame
# printf) so the next PS5 test can tell GPU texture upload, cache/media merge,
# and 2-second game-presence file I/O apart.
assert "EDEN_UI_HOTSPOT phase=%s elapsed_ms=%lld" in nav
assert 'slow_stage("texture_upload", update_stage_begin);' in nav
assert 'slow_stage("media_merge", media_started);' in nav
assert 'slow_stage("game_presence_scan", presence_started);' in nav
assert "now - last_ui_hotspot_report_ >= std::chrono::seconds(2)" in nav

# Presence checks may run every two seconds, but normal PS5 UI navigation
# must not synchronously stat the entire game library.
assert "std::future<std::vector<std::string>> presence_scan_;" in hdr
assert "presence_scan_.wait_for(std::chrono::seconds(0))" in lib
assert "presence_scan_ = std::async(std::launch::async" in lib
assert "if (!services_.game_exists(path))" in lib
# Library navigation must not wait for a full scan or stat every game on the UI thread.
library_entry = lib.split("void Launcher::enter_library()", 1)[1].split("bool Launcher::open_game_settings_at_file", 1)[0]
assert "finish_scan(false);" in library_entry
assert "finish_scan(true);" not in library_entry
# Home Triangle game options can be requested before the first background
# library scan returns: defer it rather than blocking the UI for a full scan.
settings_entry = lib.split("bool Launcher::open_game_settings_at_file(", 1)[1].split(
    "void Launcher::refresh_selected_game()", 1)[0]
assert "finish_scan(false);" in settings_entry
assert "finish_scan(true);" not in settings_entry
assert "pending_settings_file_ = file;" in settings_entry
assert "std::string pending_settings_file_;" in hdr
# Home recent cards and quick-setting saves reuse a per-title settings
# snapshot; editing settings in another screen invalidates that snapshot.
assert "home_settings_cache_;" in hdr
assert "home_settings_cache_.find(title_id)" in home
assert "home_settings_cache_.emplace(title_id," in home
assert "home_settings_cache_[title_id] = {home_game_settings_, home_game_docked_};" in home
assert "home_settings_cache_.clear();" in nav
assert "const bool game_settings_closed = modal_ == Modal::game;" in nav

assert "const std::string file = std::move(pending_settings_file_);" in nav
assert "if (games_loaded_ && !pending_settings_file_.empty())" in nav
assert "pending_settings_file_.clear();" in nav
assert "(void)open_game_settings_at_file(file);" in nav

assert "drop_missing_games();" not in library_entry
assert "if (!games_loaded_ && !scan_.valid()) start_scan();" in library_entry
assert library_entry.count("start_scan();") == 1, "tab navigation must not trigger a ROM rescan"
assert "if (library_.count != static_cast<int>(games_.size()))" in library_entry
draw_library = lib.split("void Launcher::draw_library(", 1)[1].split("void Launcher::", 1)[0]
assert 'if (!games_loaded_) {' in draw_library
assert 'tr("Loading game library...")' in draw_library
assert draw_library.index("if (!games_loaded_) {") < draw_library.index('tr("No ROM files found.")')
assert "library_.selected >= 0 &&" in lib
# Per-title mod directories/config are resolved on the scan worker, not
# synchronously when finish_scan() updates the visible Library.
scan_entry = lib.split("void Launcher::start_scan()", 1)[1].split("void Launcher::finish_scan(", 1)[0]
apply_entry = lib.split("void Launcher::apply_games(", 1)[1].split("void Launcher::name_home_games()", 1)[0]
assert "std::vector<Game> games = services_.games(&scan_cancel_);" in scan_entry
assert "services_.mods(game.title_id)" in scan_entry
assert "services_.mods_enabled(game.title_id)" in scan_entry
# Each completed Nlib request changes one title. Do not execute an O(N*M)
# full Home/library name/metadata reconciliation on a D-pad frame.
assert "void sync_home_game(const Game& game);" in hdr
# Regression: diagnostics() recursively counts cache/log files. It once
# ran on every frame in TWO draw routines, and on initial Home construction.
assert "services_.diagnostics()" not in settings_src
assert settings_src.count("const DiagnosticsInfo& info = home_diagnostics_;") == 2
assert "start_diagnostics();" in settings_src
assert "std::future<DiagnosticsInfo> diagnostics_scan_;" in hdr
assert "bool diagnostics_refresh_pending_ = false;" in hdr
assert "void Launcher::start_diagnostics(bool force)" in lib
assert "void start_diagnostics(bool force = false);" in hdr
assert "start_diagnostics(true); // recount after explicit maintenance" in settings_src
assert "void Launcher::finish_diagnostics()" in lib
assert "diagnostics_scan_ = std::async(std::launch::async" in lib
assert "diagnostics_scan_.wait_for(std::chrono::seconds(0))" in lib
assert "if (!diagnostics_refresh_pending_)" in lib
assert "if (diagnostics_refresh_pending_)" in lib
read_home_entry = lib.split("void Launcher::read_home()", 1)[1].split(
    "void Launcher::finish_home_scan()", 1)[0]
finish_home_entry = lib.split("void Launcher::finish_home_scan()", 1)[1].split(
    "void Launcher::check_games_present()", 1)[0]
assert "start_diagnostics();" in read_home_entry
assert "home_scan_ = std::async(std::launch::async" in read_home_entry
assert "return services_.home(&home_cancel_);" in read_home_entry
assert "std::atomic<bool> home_cancel_{false};" in hdr
assert "home_cancel_.store(true, std::memory_order_release);" in nav
assert "home_cancel_.load(std::memory_order_acquire)" in finish_home_entry
assert "virtual Home home(const std::atomic<bool>* cancel)" in hero_types
assert "pe::ui::Home home(const std::atomic<bool>* cancel) override;" in native_hdr
native_home = native_svc.split(
    "pe::ui::Home EdenServices::home(const std::atomic<bool>* cancel)", 1)[1].split(
    "std::string EdenServices::clock()", 1)[0]
assert "const auto cancelled = [cancel]" in native_home
assert "if (cancelled()) return {};" in native_home
assert "for (const auto& name : history)" in native_home
assert 'if (cancelled()) return {};\n        const std::string recent_path' in native_home
assert "services_.home();" not in nav
assert "std::future<Home> home_scan_;" in hdr
assert "home_reload_pending_" in hdr
assert "home_scan_.wait_for(std::chrono::seconds(0))" in finish_home_entry
assert "Home snapshot = home_scan_.get();" in finish_home_entry
assert "if (home_reload_pending_)" in finish_home_entry
assert "home_focus_ = home_recent_ >= 0 ? 5 + home_recent_" in finish_home_entry
assert "const std::string previous_file =" in finish_home_entry
assert "entry.file == previous_file" in finish_home_entry
assert "home_ = std::move(snapshot);" in finish_home_entry
assert "home_loaded_ = true;" in finish_home_entry
assert "refresh_home_hero();" in finish_home_entry
assert "start_scan();" in finish_home_entry
assert "finish_home_scan();" in nav
assert "home_scan_.wait();" in nav
assert "if (!home_loaded_)" in nav
assert "services_.mods(home_.last_title_id)" not in read_home_entry
assert "services_.mods_enabled(home_.last_title_id)" not in read_home_entry
assert "home_.last_mods = game->mods;" in finish_home_entry
assert "home_.last_mods_on = game->mods_on;" in finish_home_entry
assert "home_diagnostics_ = services_.diagnostics();" not in read_home_entry
assert "finish_diagnostics();" in nav
assert "diagnostics_scan_.wait();" in nav
# Launcher/game transition cancels even the deep native cache/log inventory.
# Old code joined a full TreeBytes() walk after launch while the menu was gone.
assert "std::atomic<bool> diagnostics_cancel_{false};" in hdr
assert "diagnostics_cancel_.store(true, std::memory_order_release);" in nav
assert "diagnostics_cancel_.load(std::memory_order_acquire)" in lib
assert "services_.diagnostics(&diagnostics_cancel_)" in lib
assert "virtual DiagnosticsInfo diagnostics(const std::atomic<bool>* cancel)" in hero_types
assert "diagnostics(const std::atomic<bool>* cancel) override;" in native_hdr
assert "EdenServices::diagnostics(const std::atomic<bool>* cancel)" in native_svc
assert "TreeBytes(const std::filesystem::path& root," in native_svc
tree_walk = native_svc.split("std::uintmax_t TreeBytes(", 1)[1].split(
    "std::string StorageSize(", 1)[0]
assert "if (cancel && cancel->load(std::memory_order_acquire)) return 0;" in tree_walk
native_diagnostics = native_svc.split(
    "EdenServices::diagnostics(const std::atomic<bool>* cancel)", 1)[1].split(
    "bool EdenServices::clear_shader_caches(", 1)[0]
assert 'TreeBytes(cache / "shader", cancel)' in native_diagnostics
assert 'TreeBytes(Eden::LogsDir(), cancel)' in native_diagnostics


# Once a user launches a game, native Nlib workers must not start another
# queued HTTP request or JPEG/TGA conversion. Already in-flight HTTP remains
# non-preemptive and workers are joined before Launcher/Services destruction.
assert "std::atomic<bool> media_cancel_{false};" in hdr
assert "media_cancel_.store(true, std::memory_order_release);" in nav
assert "media_cancel_.load(std::memory_order_acquire)" in lib
assert "services_.enrich_game_media(std::move(request), &media_cancel_)" in lib
assert "services_.enrich_game_media(std::move(copy), &media_cancel_)" in lib
assert "virtual Game enrich_game_media(Game game, const std::atomic<bool>* cancel)" in hero_types
assert "enrich_game_media(pe::ui::Game game, const std::atomic<bool>* cancel) override;" in native_hdr
assert "EnsureNlibEnrichment(game.title_id, language_choice, cancel)" in native_svc
assert "NlibEnrichment EnsureNlibEnrichment(std::uint64_t title_id, int language_choice," in native_svc
assert "const auto cancelled = [cancel]" in native_svc
assert "const std::atomic<bool>* cancel = nullptr)" in native_svc
assert "if (!response || (cancel && cancel->load(std::memory_order_acquire)))" in native_svc
assert "return CacheNlibJpeg(endpoint, path, minimum, cancel);" in native_svc
assert "if (cancelled()) return;" in native_svc
assert "if (cancelled()) break;" in native_svc

assert "void Launcher::sync_home_game(const Game& game)" in lib
selected_media = lib.split("void Launcher::finish_selected_media()", 1)[1].split(
    "void Launcher::apply_games(", 1)[0]
assert "sync_home_game(game);" in selected_media
assert "name_home_games();" not in selected_media
full_sync = lib.split("void Launcher::name_home_games()", 1)[1].split(
    "void Launcher::", 1)[0]
assert "for (const Game& game : games_)" in full_sync
assert "sync_home_game(game);" in full_sync

assert "catch (const std::bad_alloc&)" in scan_entry
assert "catch (const std::exception& error)" in scan_entry
assert "if (mod_scan_errors++ < 3)" in scan_entry
# Obsolete scans must stop enumerating optional per-game mod folders
# when the user launches a game. Do not asynchronously kill a thread.
assert "std::atomic<bool> scan_cancel_{false};" in hdr
assert "scan_cancel_.load(std::memory_order_acquire)" in scan_entry
assert "if (scan_cancel_.load(std::memory_order_acquire)) break;" in scan_entry
assert "if (!scan_cancel_.load(std::memory_order_acquire))" in lib
assert "scan_cancel_.store(true, std::memory_order_release);" in nav
# Native game enumeration must itself honor cancellation between ROMs,
# not merely skip the follow-up mod scan in the Launcher wrapper.
assert "virtual std::vector<Game> games(const std::atomic<bool>* cancel)" in hero_types
assert "games(const std::atomic<bool>* cancel) override;" in native_hdr
assert "EdenServices::games(const std::atomic<bool>* cancel)" in native_svc
native_scan = native_svc.split(
    "EdenServices::games(const std::atomic<bool>* cancel)", 1)[1].split(
    "EdenServices::enrich_game_media", 1)[0]
assert "cancel && cancel->load(std::memory_order_acquire)" in native_scan
assert "return {}; // discard partial results and stop per-title disk work" in native_scan
assert "return {}; // extraction finished; skip ID/Nlib/add-on metadata" in native_scan

assert "auto games = scan_.get();" in lib
# A failed first scan must not become a valid empty list. Otherwise the
# delayed Home settings action reports a nonexistent missing ROM.
finish_entry = lib.split("void Launcher::finish_scan(", 1)[1].split(
    "void Launcher::start_home_media()", 1)[0]
assert "games_loaded_ = true;" not in finish_entry
assert "if (!games_loaded_ && !pending_settings_file_.empty())" in finish_entry
assert "pending_settings_file_.clear();" in finish_entry

assert "apply_games(std::move(games));" in lib

assert "#include <new>" in lib
assert "services_.mods(game.title_id)" not in apply_entry
assert "home_.last_mods = game.mods;" in lib
assert "home_.last_mods_on = game.mods_on;" in lib
# Preserve UI responsiveness without pruning a ROM based on one stale
# asynchronous filesystem snapshot (e.g. an atomic replacement during scan).
assert "std::vector<std::string> previous_missing_;" in hdr
assert "std::set_intersection(observed_missing.begin()" in lib
assert "previous_missing_ = observed_missing;" in lib
assert "std::vector<std::string> home_missing_refresh_;" in hdr
assert "if (observed_missing.empty())" in lib
assert "home_missing_refresh_.clear();" in lib
assert "home_missing != home_missing_refresh_" in lib
assert "home_missing_refresh_ = home_missing;" in lib
assert lib.index("home_missing_refresh_ = home_missing;") < lib.index(
    "read_home();", lib.index("home_missing_refresh_ = home_missing;"))
# Repeating a confirmed disappearance must not invalidate a newly queued
# Home snapshot over and over; a newly missing file/reappeared file is new.
def should_refresh_home(previous, missing):
    return bool(missing) and missing != previous
assert should_refresh_home([], ["last.nsp"])
assert not should_refresh_home(["last.nsp"], ["last.nsp"])
assert should_refresh_home(["last.nsp"], ["last.nsp", "recent.nsp"])
assert not should_refresh_home(["last.nsp"], [])

assert 'previous_missing_.clear();' in lib
assert "#include <iterator>" in lib
def stable_absence(previous, observed):
    return sorted(set(previous) & set(observed))
assert stable_absence([], ["game.nsp"]) == []
assert stable_absence(["game.nsp"], []) == []
assert stable_absence(["game.nsp"], ["game.nsp"]) == ["game.nsp"]


assert "if (presence_scan_.valid())" in nav
assert "drop_missing_games(&missing);" in lib
assert "if (known_missing)" in lib
assert "bool drop_missing_games(const std::vector<std::string>* known_missing = nullptr);" in hdr

print("Nlib and four PS5 capture regressions: SOURCE CONTRACT PASS")
