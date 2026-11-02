#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""P3.4: run the actual launcher game-list publication under host C++20.

Tests an incomplete asynchronous scan, atomic replacement, selected-title
stability, failed discovery and launch cancellation. No PS5 build or ROM I/O.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "headless/prosperoeden/pe/ui/library.cpp").read_text()
launcher = (ROOT / "headless/prosperoeden/pe/ui/launcher.cpp").read_text()

def owner(start: str, following: str) -> str:
    assert source.count(start) == 1, ("source owner changed", start)
    tail = source.split(start, 1)[1]
    assert following in tail, ("owner boundary changed", following)
    return start + tail.split(following, 1)[0]

finish = owner("void Launcher::finish_scan(bool wait)", "\nvoid Launcher::start_home_media()")
apply = owner("void Launcher::apply_games(std::vector<Game> games)", "\nvoid Launcher::sync_home_game(")
media_finish = owner("void Launcher::finish_selected_media()", "\nvoid Launcher::apply_games(")
home_finish = owner("void Launcher::finish_home_media()", "\nvoid Launcher::start_selected_media(")
enter = owner("void Launcher::enter_library()", "\nbool Launcher::open_game_settings_at_file(")
draw = owner("void Launcher::draw_library(Canvas &c)", "\nvoid Launcher::",) if False else source

# A tab change cannot invalidate a good list, synchronously scan the filesystem,
# or render the initial pending scan as a verified empty collection.
assert "if (!games_loaded_ && !scan_.valid()) start_scan();" in enter
assert "if (!games_loaded_) {" in source
assert 'tr("Loading game library...")' in source
assert 'tr("No ROM files found.")' in source
assert source.index('if (!games_loaded_) {\n        // First-ever discovery is pending.') < source.index('tr("No ROM files found.")')
assert "games_ = std::move(games);" in apply
assert "if (!scan_cancel_.load(std::memory_order_acquire))" in finish
assert "scan_.wait_for(std::chrono::seconds(0))" in finish
assert "open(Screen::library, true);" in launcher

cpp = r"""
#include <algorithm>
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstdint>
#include <exception>
#include <future>
#include <stdexcept>
#include <string>
#include <utility>
#include <unordered_map>
#include <string_view>
#include <vector>
struct Game {
    std::string file;
    bool docked = false;
    bool mods_enabled = false;
    std::uint64_t title_id = 0;
    std::string name;
    bool artwork_changed = false;
    unsigned case_artwork_changed = 0;
    std::string cover, box_front, box_back, hero;
    std::vector<std::string> screenshots;
    std::string intro, description, publisher, developer, release_date, categories;
    int max_players = 0;
    Game() = default;
    Game(std::string file_, bool docked_) : file(std::move(file_)), docked(docked_) {}
};
enum class Cue { error };
namespace sys {
template<class... Args> void log(const char*, Args...) {}
}
std::string tr(const char* message) { return message; }
struct Textures { int invalidated = 0; void invalidate(const std::string&) { ++invalidated; } };
struct Recent {
    std::uint64_t title_id = 0;
    std::string cover, hero, screenshot, title, intro, description;
    int max_players = 0;
};
struct Home {
    std::uint64_t last_title_id = 0;
    std::string last_cover, last_hero, last_screenshot, last_title;
    std::string last_intro, last_description;
    int last_max_players = 0;
    std::vector<Recent> recents;
};
class Launcher {
public:
    Textures textures_;
    std::future<Game> media_scan_;
    std::future<Game> home_media_scan_;
    std::uint64_t media_scan_title_id_ = 0, home_media_scan_title_id_ = 0;
    Home home_;
    int home_syncs = 0, home_media_started = 0;
    struct Library {
        int selected = -1, count = 0, resets = 0;
        void reset(int n, int selection) {
            assert(n >= 0 && (n == 0 || (selection >= 0 && selection < n)));
            count = n;
            selected = n ? selection : -1;
            ++resets;
        }
    } library_;
    struct Mode {
        int snaps = 0;
        float last = 0.0f;
        void snap(float value) { last = value; ++snaps; }
    } mode_, mods_switch_;
    std::vector<Game> games_;
    std::future<std::vector<Game>> scan_;
    std::atomic<bool> scan_cancel_{false};
    std::string pending_settings_file_;
    bool games_loaded_ = false, library_back_focused_ = false;
    bool library_back_zoom_ = false, docked_refresh_after_scan_ = false;
    bool selected_docked_ = false;
    int refreshed = 0, named = 0, media = 0, started = 0, errors = 0;
    void apply_games(std::vector<Game> games);
    void finish_scan(bool wait);
    void finish_selected_media();
    void finish_home_media();
    void sync_home_game(const Game&) { ++home_syncs; }
    void start_home_media() { ++home_media_started; }
    void start_scan() { ++started; }
    void refresh_selected_game() {
        ++refreshed;
        if (library_.selected >= 0 &&
            library_.selected < static_cast<int>(games_.size()))
            selected_docked_ = games_[static_cast<std::size_t>(library_.selected)].docked;
    }
    void name_home_games() { ++named; }
    void start_selected_media() { ++media; }
    void say(const std::string&, bool) { ++errors; }
    void cue(Cue) {}
};
""" + finish + "\n" + apply + "\n" + media_finish + "\n" + home_finish + r"""
int main() {
    // An unchanged ROM list may still carry a changed Mods preference.
    // This must update the selected switch once, without resetting cards,
    // restarting image requests or triggering a full selection animation.
    {
        Launcher same;
        Game old{"Bananza", true};
        old.title_id = 0x111;
        old.mods_enabled = false;
        same.games_ = {old};
        same.games_loaded_ = true;
        same.library_.selected = 0;
        same.library_.count = 1;
        Game updated = old;
        updated.mods_enabled = true;
        same.apply_games({updated});
        assert(same.mods_switch_.snaps == 1 && same.mods_switch_.last == 1.0f);
        assert(same.library_.resets == 0 && same.refreshed == 0);
        same.apply_games({updated});
        assert(same.mods_switch_.snaps == 1 && same.library_.resets == 0);
        updated.mods_enabled = false;
        same.apply_games({updated});
        assert(same.mods_switch_.snaps == 2 && same.mods_switch_.last == 0.0f);
    }
    // A HOME-origin enrichment must also reach every installed physical
    // copy of a TitleID. This uses the actual asynchronous owner method.
    {
        Launcher home;
        home.home_.last_title_id = 0x777;
        Recent last_played;
        last_played.title_id = 0x777;
        home.home_.recents.push_back(std::move(last_played));
        Game a{"MKW alpha", true}; a.title_id = 0x777;
        Game b{"MKW beta", true}; b.title_id = 0x777;
        Game other{"Different", true}; other.title_id = 0x888;
        home.games_ = {a, b, other};
        Game enriched{"MKW", true};
        enriched.title_id = 0x777;
        enriched.box_front = "front.webp";
        enriched.box_back = "rear.webp";
        enriched.cover = "icon.webp";
        enriched.hero = "hero.webp";
        enriched.screenshots = {"scene.webp"};
        enriched.description = "Real title metadata";
        std::promise<Game> found;
        home.home_media_scan_ = found.get_future();
        home.home_media_scan_title_id_ = 0x777;
        found.set_value(enriched);
        home.finish_home_media();
        assert(home.games_[0].box_back == "rear.webp");
        assert(home.games_[1].box_back == "rear.webp");
        assert(home.games_[1].screenshots.size() == 1);
        assert(home.games_[2].box_back.empty());
        assert(home.home_.last_cover == "icon.webp");
        assert(home.home_.recents.front().hero == "hero.webp");
        assert(home.home_media_started == 1);
        Game zero{"Invalid", false};
        zero.title_id = 0;
        zero.box_front = "zero.webp";
        std::promise<Game> no_identity;
        home.home_media_scan_ = no_identity.get_future();
        no_identity.set_value(zero);
        home.home_media_scan_title_id_ = 0x777;
        home.finish_home_media();
        assert(home.games_[2].box_front.empty());
        // An unrelated, even valid, TitleID cannot contaminate the active
        // Home or the library when a worker returns a stale response.
        Game wrong = enriched;
        wrong.title_id = 0x888;
        wrong.cover = "wrong.webp";
        std::promise<Game> stale;
        home.home_media_scan_ = stale.get_future();
        home.home_media_scan_title_id_ = 0x777;
        stale.set_value(wrong);
        home.finish_home_media();
        assert(home.games_[2].cover.empty());
        assert(home.home_.last_cover == "icon.webp");
    }
    // Duplicate installations of the same TitleID must all inherit Nlib
    // artwork. Never distribute an invalid zero ID to unrelated ROMs.
    {
        Launcher copies;
        Game first{"MKW copy 1", true};
        first.title_id = 0x123;
        Game second{"MKW copy 2", true};
        second.title_id = 0x123;
        Game unrelated{"Other game", true};
        unrelated.title_id = 0x456;
        copies.games_ = {first, second, unrelated};
        Game nlib{"MKW copy 1", false};
        nlib.title_id = 0x123;
        nlib.cover = "mkw-icon.webp";
        nlib.box_front = "mkw-front.webp";
        nlib.box_back = "mkw-back.webp";
        nlib.hero = "mkw-hero.webp";
        nlib.description = "Mario Kart World";
        nlib.screenshots = {"mkw-shot.webp"};
        std::promise<Game> done;
        copies.media_scan_ = done.get_future();
        copies.media_scan_title_id_ = 0x123;
        done.set_value(nlib);
        copies.finish_selected_media();
        assert(copies.games_[0].box_back == "mkw-back.webp");
        assert(copies.games_[1].box_back == "mkw-back.webp");
        assert(copies.games_[1].hero == "mkw-hero.webp");
        assert(copies.games_[1].screenshots.size() == 1);
        assert(copies.games_[2].box_front.empty());
        assert(copies.home_syncs == 2 && copies.media == 1);
        Game zero{"Invalid", false};
        zero.title_id = 0;
        zero.cover = "bad.webp";
        copies.games_.push_back(zero);
        std::promise<Game> invalid;
        copies.media_scan_ = invalid.get_future();
        copies.media_scan_title_id_ = 0x123;
        invalid.set_value(zero);
        copies.finish_selected_media();
        assert(copies.games_[3].cover == "bad.webp");
        assert(copies.home_syncs == 2);
        // The worker accidentally reports another *valid* title: refuse
        // before invalidating its textures or touching the matching game.
        Game spoof = nlib;
        spoof.title_id = 0x456;
        spoof.box_front = "wrong.webp";
        std::promise<Game> bad_title;
        copies.media_scan_ = bad_title.get_future();
        copies.media_scan_title_id_ = 0x123;
        bad_title.set_value(spoof);
        copies.finish_selected_media();
        assert(copies.games_[2].box_front.empty());
        assert(copies.home_syncs == 2);
    }
    // Fresh discovery is pending: the UI cannot declare "No ROM" until
    // a complete worker result has been committed on the owner thread.
    {
        Launcher cold;
        std::promise<std::vector<Game>> first;
        cold.scan_ = first.get_future();
        cold.finish_scan(false);
        assert(!cold.games_loaded_ && cold.games_.empty());
        assert(cold.library_.resets == 0 && cold.library_.count == 0);
        first.set_value({{"Switch 2 title", false}});
        cold.finish_scan(true);
        assert(cold.games_loaded_ && cold.library_.count == 1);
        assert(cold.games_[0].file == "Switch 2 title");
    }
    // A same-title settings refresh must preserve already loaded cover/
    // back/hero media, but never keep old art for a replaced TitleID.
    {
        Launcher media;
        Game old{"MKW", true};
        old.title_id = 0x1234;
        old.cover = "icon.webp";
        old.box_front = "front.webp";
        old.box_back = "back.webp";
        old.hero = "hero.webp";
        old.screenshots = {"shot.webp"};
        old.description = "existing summary";
        old.max_players = 4;
        media.apply_games({old});
        Game refreshed{"MKW", false};
        refreshed.title_id = old.title_id;
        media.apply_games({refreshed});
        assert(!media.games_[0].docked);
        assert(media.games_[0].box_front == "front.webp");
        assert(media.games_[0].box_back == "back.webp");
        assert(media.games_[0].hero == "hero.webp");
        assert(media.games_[0].cover == "icon.webp");
        assert(media.games_[0].screenshots.size() == 1);
        assert(media.games_[0].description == "existing summary");
        assert(media.games_[0].max_players == 4);
        Game newer{"MKW", false};
        newer.title_id = old.title_id;
        newer.box_front = "updated.webp";
        media.apply_games({newer});
        assert(media.games_[0].box_front == "updated.webp");
        Game replaced{"MKW", false};
        replaced.title_id = 0x4567;
        media.apply_games({replaced});
        assert(media.games_[0].box_front.empty());
        assert(media.games_[0].hero.empty());
        assert(media.games_[0].screenshots.empty());
        // Reorder / insert a title between scans: keep the art that already
        // belongs to the same file+TitleID, without crossing into a new game.
        Game b{"B", true};
        b.title_id = 0xBBBB;
        b.box_front = "b-front.webp";
        b.box_back = "b-back.webp";
        Game a{"A", true};
        a.title_id = 0xAAAA;
        a.box_front = "a-front.webp";
        media.apply_games({a, b});
        Game inserted{"C", true};
        inserted.title_id = 0xCCCC;
        Game reordered_b{"B", false};
        reordered_b.title_id = 0xBBBB;
        Game reordered_a{"A", false};
        reordered_a.title_id = 0xAAAA;
        media.apply_games({inserted, reordered_b, reordered_a});
        assert(media.games_[0].box_front.empty());
        assert(media.games_[1].box_front == "b-front.webp");
        assert(media.games_[1].box_back == "b-back.webp");
        assert(media.games_[2].box_front == "a-front.webp");
        assert(!media.games_[1].docked && !media.games_[2].docked);
        Game reused{"B", false};
        reused.title_id = 0xDEAD;
        media.apply_games({reused, reordered_a});
        assert(media.games_[0].box_front.empty());
        assert(media.games_[1].box_front == "a-front.webp");
    }
    Launcher v;
    v.apply_games({{"A", true}, {"B", false}});
    assert(v.games_loaded_ && v.library_.count == 2);
    assert(v.library_.selected == 0 && v.library_.resets == 1);
    v.library_.selected = 1;
    v.library_back_focused_ = true;
    v.library_back_zoom_ = true;
    v.apply_games({{"A", false}, {"B", true}});
    assert(v.library_.selected == 1 && v.library_.resets == 1);
    assert(v.selected_docked_ && !v.library_back_focused_ && !v.library_back_zoom_);
    v.apply_games({{"B", true}, {"A", false}, {"C", false}});
    assert(v.library_.selected == 0 && v.library_.count == 3);
    assert(v.library_.resets == 2 && v.games_[0].file == "B");

    // An incomplete scan is never published as empty or as a failure.
    std::promise<std::vector<Game>> pending;
    v.scan_ = pending.get_future();
    const int before = v.library_.resets;
    v.finish_scan(false);
    assert(v.games_.size() == 3 && v.library_.resets == before);
    pending.set_value({{"C", false}, {"B", true}});
    v.finish_scan(true);
    assert(v.games_.size() == 2 && v.games_[1].file == "B");
    assert(v.library_.selected == 1 && v.library_.resets == before + 1);

    // Failed discovery preserves last-known-good contents and selection.
    std::promise<std::vector<Game>> failure;
    v.scan_ = failure.get_future();
    failure.set_exception(std::make_exception_ptr(std::runtime_error("disk unavailable")));
    v.finish_scan(true);
    assert(v.games_.size() == 2 && v.library_.selected == 1);
    assert(v.games_loaded_);

    // Results collected after launch cancellation are discarded.
    std::promise<std::vector<Game>> cancelled;
    v.scan_ = cancelled.get_future();
    v.scan_cancel_.store(true, std::memory_order_release);
    cancelled.set_value({});
    v.finish_scan(true);
    assert(v.games_.size() == 2 && v.games_loaded_);
    v.scan_cancel_.store(false, std::memory_order_release);

    // An overlapping preferences refresh requeues exactly one later scan.
    std::promise<std::vector<Game>> refresh;
    v.scan_ = refresh.get_future();
    v.docked_refresh_after_scan_ = true;
    refresh.set_value({{"C", false}, {"B", false}});
    v.finish_scan(true);
    assert(v.started == 1 && !v.docked_refresh_after_scan_);
    assert(v.games_[1].file == "B" && !v.selected_docked_);

    // A new scan must not blank a known-good shelf while it is in flight.
    // An *actually completed* empty inventory is different: removing all
    // ROMs can legitimately leave the Library empty.
    std::promise<std::vector<Game>> empty;
    v.scan_ = empty.get_future();
    const int before_empty = v.library_.resets;
    v.finish_scan(false);
    assert(v.games_.size() == 2 && v.library_.resets == before_empty);
    empty.set_value({});
    v.finish_scan(true);
    assert(v.games_loaded_ && v.games_.empty());
    assert(v.library_.count == 0 && v.library_.selected == -1);
}
""";

compilers = list(dict.fromkeys(
    p for name in ("clang++", "g++") if (p := shutil.which(name))))
assert compilers, "C++20 compiler required for P3.4 source extraction"
with tempfile.TemporaryDirectory(prefix="encore-library-atomic-") as folder:
    folder = Path(folder)
    test = folder / "library-atomic.cpp"
    test.write_text(cpp)
    for compiler in compilers:
        for opt in ("-O0", "-O2"):
            exe = folder / (Path(compiler).name + opt)
            built = subprocess.run(
                [compiler, "-std=c++20", "-pthread", opt, "-Wall", "-Wextra",
                 "-Werror", str(test), "-o", str(exe)],
                capture_output=True, text=True, timeout=45)
            assert built.returncode == 0, (compiler, opt, built.stderr[-5000:])
            ran = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15)
            assert ran.returncode == 0, (compiler, opt, ran.stderr[-5000:])
            print("P3_4_LAUNCHER_ATOMIC_SCAN_PASS", Path(compiler).name, opt)
