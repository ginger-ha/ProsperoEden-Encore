// ProsperoEden - The launcher: home, library, settings and their dialogs.
// Copyright (C) 2026 BlackBearReloaded
// SPDX-License-Identifier: GPL-3.0-or-later

#pragma once

#include "pe/audio/sounds.hpp"
#include "pe/ui/widgets.hpp"

#include <array>
#include <atomic>
#include <chrono>
#include <future>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace pe::ui
{

// Every screen of the launcher as one state machine. The frontend feeds it
// pressed buttons and frame time, draws its list and plays its cues; it ends
// when a game is chosen (and the closing animation has run).
class Launcher
{
  public:
    // first_start: the app just opened (false after returning from a game).
    Launcher(Services &services, Textures &textures, const Fonts &fonts, bool first_start);
    ~Launcher();
    Launcher(const Launcher &) = delete;
    Launcher &operator=(const Launcher &) = delete;

    void press(Key key);
    void update(float dt);
    void draw(gfx::DrawList &list);

    // Host preview readiness probes are side-effect free. A focus sound
    // on Home cannot certify that the async Library worker has completed.
    // No filesystem, locks or GPU state change in either query.
    [[nodiscard]] bool preview_home_ready() const noexcept {
        return screen_ == Screen::home && home_loaded_;
    }
    [[nodiscard]] bool preview_library_ready(std::size_t required) const noexcept {
        return screen_ == Screen::library && games_loaded_ &&
               games_.size() >= required &&
               library_.count == static_cast<int>(games_.size());
    }

    // The sounds asked for since the last call.
    std::vector<audio::Cue> take_cues();
    // Launcher sound level (0-100) as set in Settings > Audio.
    int menu_volume() const
    {
        return prefs_.menu_volume;
    }
    // The size the picture is put out at, as set in Settings > Video (Preferences::output). The
    // frontend opens its display again when it changes, and then names its new font texture.
    int output() const
    {
        return prefs_.output;
    }
    void set_font_texture(std::uint32_t texture)
    {
        fonts_.texture = texture;
    }
    bool done() const
    {
        return done_;
    }
    // A language change rebuilds the launcher in-process so its catalog, fonts and cached labels
    // all change together without closing Encore.
    bool restart_requested() const
    {
        return restart_requested_;
    }
    // Empty until a game is chosen.
    const std::string &selected_game() const
    {
        return selected_game_;
    }

  private:
    enum class Screen : std::uint8_t
    {
        home,
        library,
        settings,
        files,
        language,
        about,
    };
    enum class Modal : std::uint8_t
    {
        none,
        video,
        audio,
        controls,
        accessibility,
        appearance,
        diagnostics,
        game,
        mods, // a game's mods, opened from its settings
        mapping, // global or per-game DualSense button mapping
    };
    enum class Confirmation : std::uint8_t
    {
        none,
        restore_defaults,
        game_overrides,
        mapping_reset,
        shader_caches,
        console_mode,
        exit_app,
    };

    // ---- shell (launcher.cpp) ----
    void cue(audio::Cue value)
    {
        cues_.push_back(value);
    }
    void open(Screen screen, bool forward);
    void open_modal(Modal modal);
    void close_modal();
    void clear_confirmation();
    bool confirm_action(Confirmation action);
    void say(const std::string &text, bool warning = false);
    void launch(const std::string &file, const std::string &title, const std::string &cover);
    void draw_screen(Canvas &c, Screen screen);
    bool press_top_nav(Key key);
    void draw_top_nav(Canvas &c, int active_tab, int focus_tab = -1, float focus_amount = 0.0f);
    void draw_frame(Canvas &c, const char *title, const char *copy);
    void draw_footer(Canvas &c, const Hint *hints, int count);
    void draw_confirmation(Canvas &c);
    void draw_launch(Canvas &c);
    // quiet: a change that shows at once needs no "Saved" line.
    bool save_preferences(bool quiet = false);
    // The switches of a dialog as the preferences have them, in the order of its rows.
    std::array<bool, 3> switch_states(Modal modal) const;
    // Shows the launcher as the preferences' accessibility switches say.
    void apply_look();

    // ---- home (home.cpp) ----
    void press_home(Key key);
    void update_controllers(float dt);
    void draw_home(Canvas &c);
    void draw_switch_home(Canvas &c);
    void press_switch_home(Key key);
    void draw_switch_library(Canvas &c);
    void press_switch_library(Key key);
    void draw_switch_settings(Canvas &c);
    void draw_switch_files(Canvas &c);
    void draw_switch_language(Canvas &c);
    void draw_switch_about(Canvas &c);
    void draw_switch_dialog(Canvas &c, Modal modal, float open);
    void draw_switch_confirmation(Canvas &c);
    void draw_switch_game(Canvas &c, float opened);
    void draw_switch_mods(Canvas &c, float opened);
    void draw_switch_mapping(Canvas &c, float opened);
    void press_switch_settings(Key key);
    void draw_switch_header(Canvas &c, const char *heading);
    void draw_switch_footer(Canvas &c, const char *hint);
    void draw_controllers(Canvas &c);
    void open_library_at_file(const std::string &file);
    void refresh_home_hero();

    // ---- library and game settings (library.cpp) ----
    // The game list is read beside the menu: reading every game takes a moment.
    void start_scan();
    void finish_scan(bool wait);
    void start_home_media();
    void finish_home_media();
    void start_selected_media();
    void finish_selected_media();
    void apply_games(std::vector<Game> games);
    void name_home_games();
    void sync_home_game(const Game& game); // one Nlib update must not walk every installed title
    // The home screen's content, with its game's mods counted.
    void read_home(); // queue native metadata refresh, never blocks the UI frame
    void finish_home_scan(); // owner-thread application of one complete Home snapshot
    void start_diagnostics(bool force = false);
    void finish_diagnostics();
    // Games removed/moved while the launcher is open disappear without a full rescan.
    void check_games_present();
    bool drop_missing_games(const std::vector<std::string>* known_missing = nullptr);
    // A game's mods as its list has them: how many, and how many are switched on.
    void count_mods(Game &game, const std::vector<Mod> &mods);
    // What a game comes with, on one line: "Update 1.2.0, 2 DLC, 2 mods"; "None" without any.
    // brief: for Game::addons_short, where the line would not fit ("v1.2.0, 2 DLC, 1/2 mods").
    static std::string addons_line(const std::string &addons, int mods, int mods_on,
                                   bool brief = false);
    // A refresh rate setting as the player reads it: 0 is "60 Hz", 1 is "120 Hz".
    static std::string hertz(int refresh);
    void enter_library();
    bool open_game_settings_at_file(const std::string &file);
    void press_library(Key key);
    void draw_library(Canvas &c);
    void refresh_selected_game();
    void press_game(Key key);
    void draw_game(Canvas &c, float open);
    void press_mods(Key key);
    void draw_mods(Canvas &c, float open);
    void open_mapping(bool for_game);
    void press_mapping(Key key);
    void draw_mapping(Canvas &c, float open);

    // ---- settings and its dialogs (settings.cpp) ----
    void press_settings(Key key);
    void draw_settings(Canvas &c);
    void press_dialog(Key key);
    void draw_dialog(Canvas &c, Modal modal, float open);
    int dialog_rows(Modal modal) const;
    float dialog_row_top(Modal modal, int row) const;

    // ---- game files, language, about (browse.cpp) ----
    void enter_files();
    bool browse_to(const std::string &directory);
    void press_files(Key key);
    void draw_files(Canvas &c);
    void enter_language();
    void press_language(Key key);
    void draw_language(Canvas &c);
    void draw_about(Canvas &c);

    Services &services_;
    Textures &textures_;
    Fonts fonts_;
    Backdrop backdrop_;
    std::vector<audio::Cue> cues_;
    float time_ = 0.0f;
    float clock_wait_ = 0.0f;
    float presence_wait_ = 0.0f;
    // Bounded PS5 update-stall diagnoses: never log in the normal 60 Hz path.
    std::chrono::steady_clock::time_point last_ui_hotspot_report_{};
    std::string clock_;
    std::string version_;
    struct ProfileAvatarProbe {
        std::string path;
        std::uint64_t device = 0, inode = 0, size = 0, mtime = 0, ctime = 0;
        bool operator==(const ProfileAvatarProbe&) const = default;
    };
    static ProfileAvatarProbe probe_profile_avatar(Services &services);
    // At most one worker; a missing profile is retried every five seconds.
    std::future<ProfileAvatarProbe> profile_avatar_scan_;
    ProfileAvatarProbe profile_avatar_active_{};
    float profile_avatar_refresh_elapsed_ = 0.0f;
    std::string profile_avatar_path_;

    // navigation
    Screen screen_ = Screen::home;
    Screen leaving_ = Screen::home;
    tween::Timer transition_;
    bool forward_ = true;
    Modal modal_ = Modal::none;
    Modal modal_shown_ = Modal::none; // still drawn while it closes
    tween::Spring modal_open_;
    tween::Spring dim_;   // darkness over the art behind full screens
    float press_ = 0.0f;  // 1 at a confirm, then decays: the focused item dips
    std::string message_; // the last result ("Saved..."), shown where the screen has room
    bool message_warning_ = false;
    float message_age_ = 0.0f;
    Confirmation confirmation_ = Confirmation::none;
    Key confirmation_key_ = Key::cross;
    Key pressed_key_ = Key::cross;
    int top_nav_focus_ = -1; // -1 = content; 0..3 = Home/Library/Recents/Settings
    int active_main_tab_ = 0; // the Recent rail is its own tab, sharing Home content

    // launching a game
    std::string selected_game_;
    std::string launch_title_;
    std::string launch_cover_;
    std::string launch_hero_;
    std::string launch_box_front_;
    std::string launch_box_back_;
    std::string launch_box_spine_;
    std::uint64_t launch_title_id_ = 0; // single launch provenance in case draw logs
    unsigned launch_case_placeholder_mask_ = 0; // one-time per-face diagnostic
    unsigned launch_case_ready_mask_ = 0;
    std::string launch_description_;
    std::vector<std::string> launch_screenshots_;
    // Snapshot the selected title once. These pages are rendered from the
    // same code as the Library's replacement sleeves, never remote fetches.
    Game launch_case_game_;
    std::uint32_t launch_composed_front_ = 0;
    std::uint32_t launch_composed_back_ = 0;
    bool launch_composed_front_attempted_ = false;
    bool launch_composed_back_attempted_ = false;
    // A fallback printed before late async media becomes available can be
    // overwritten once, on the SAME texture, without allocating another page.
    bool launch_composed_front_provisional_ = false;
    bool launch_composed_back_provisional_ = false;
    // Retry only a bounded number of times after a transient GL/FBO failure.
    // A failed first allocation must not permanently suppress the missing side.
    unsigned launch_composed_front_failures_ = 0;
    unsigned launch_composed_back_failures_ = 0;
    float launch_composed_front_retry_after_ = 0.0f;
    float launch_composed_back_retry_after_ = 0.0f;
    tween::Timer launch_;
    bool done_ = false;
    bool restart_requested_ = false;

    // home: 0 hero, 1-3 header, 4 details, 5-11 recent, 12 quick card, 13-19 quick rows, 20 storage, 21 controllers, 22 full settings
    Home home_;
    std::future<Home> home_scan_; // costly recent-game metadata is read off-thread
    bool home_loaded_ = false; // no game launch or Home actions before snapshot
    bool home_reload_pending_ = false; // don't apply an obsolete in-flight refresh
    DiagnosticsInfo home_diagnostics_{};
    std::future<DiagnosticsInfo> diagnostics_scan_; // asynchronous cache/log disk inventory
    bool diagnostics_refresh_pending_ = false; // discard an outdated scan after maintenance
    int home_recent_ = -1; // -1 = last played; otherwise the selected Recent card becomes the hero
    GameSettings home_game_settings_{};
    bool home_game_docked_ = true;
    // Repeated recent-card navigation and quick-setting saves must not
    // reread the same game JSON file on every controller input.
    std::unordered_map<std::uint64_t, std::pair<GameSettings, bool>> home_settings_cache_;
    // The controllers connected now (bit 0 is player 1), and how lit each one's icon is.
    unsigned controllers_ = 0;
    bool controllers_known_ = false;
    float controller_poll_elapsed_ = 0.0f; // presence only; input remains frame-driven
    std::array<tween::Spring, 4> controller_lit_{};
    std::array<float, 4> controller_pop_{}; // 1 when a controller appears, then decays
    int home_focus_ = 0;
    int home_quick_edit_ = -1; // -1 browsing; 0-6 editing one quick-setting row
    std::array<tween::Spring, 23> home_springs_{};
    float intro_ = 0.0f;
    bool first_start_ = true;

    // library
    std::vector<Game> games_;
    std::string pending_settings_file_; // Home game options requested before async scan completes
    std::atomic<bool> home_cancel_{false}; // exit stops unfinished native Home metadata work
    std::atomic<bool> scan_cancel_{false}; // game launch/teardown cancels remaining mod enumeration
    std::atomic<bool> media_cancel_{false}; // stop launching new Nlib requests on game start
    std::atomic<bool> diagnostics_cancel_{false}; // stop disk inventory between entries on game start
    std::future<std::vector<Game>> scan_; // the list being read
    bool docked_refresh_after_scan_ = false; // global settings saved during an in-flight scan
    std::future<std::vector<std::string>> presence_scan_; // nonblocking filesystem presence results
    std::vector<std::string> previous_missing_; // sorted previous poll; two-scan absence confirmation
    std::vector<std::string> home_missing_refresh_; // refresh once per confirmed missing-Home set
    // Home enrichment is independent of the full library scan: the hero should get its
    // banner/player metadata as soon as the network/cache can provide it.
    std::future<Game> home_media_scan_;
    std::uint64_t home_media_scan_title_id_ = 0;
    std::unordered_map<std::uint64_t, std::chrono::steady_clock::time_point> home_media_next_retry_;
    std::future<Game> media_scan_; // Nlib enrichment of every installed title
    std::uint64_t media_scan_title_id_ = 0;
    std::unordered_map<std::uint64_t, std::chrono::steady_clock::time_point> media_next_retry_;
    float media_retry_timer_ = 0.0f; // only periodically poll for failed/late Nlib artwork
    bool games_loaded_ = false;
    ListView library_;
    bool library_back_focused_ = false; // Down selects rear jacket
    bool library_back_zoom_ = false; // Cross opens, Circle alone closes the viewer
    float library_back_scale_ = 1.0f; // L2 / R2; no artwork stretching
    float library_back_pan_x_ = 0.0f; // D-pad or left stick in viewer
    float library_back_pan_y_ = 0.0f;
    bool selected_docked_ = true;
    tween::Spring mode_;   // 0 docked .. 1 handheld
    tween::Spring mods_switch_; // the selected game's Mods switch: 0 off .. 1 on
    tween::Spring detail_; // the details fade in after the selection moves

    // settings and dialogs
    Preferences prefs_;
    int switch_home_focus_ = 0;
    int switch_home_last_tile_ = 0; // remember selected title when visiting system shortcuts
    ListView settings_;
    tween::Spring section_;
    int option_ = 0;
    tween::Spring option_cursor_; // highlight position in pixels
    std::array<tween::Spring, 4> switches_{};
    ListView video_rows_; // the Video dialog's rows (more than it shows)
    GameSettings game_settings_;
    bool game_docked_ = true;
    SaveSource import_source_ = SaveSource::none; // what Save data could import for the game
    bool import_armed_ = false;                   // Cross was pressed once: the next one imports
    ListView game_rows_;                          // the game dialog's rows (more than it shows)
    std::vector<Mod> mods_;                       // the game's mods, read when its dialog opens
    ListView mod_rows_;
    bool mapping_for_game_ = false;
    ListView mapping_rows_;

    // game files
    std::string browse_dir_;
    std::vector<std::string> browse_entries_; // ".." first unless at "/", then subfolders
    ListView files_;
    FolderInfo folder_info_;

    // language
    ListView language_;
};

} // namespace pe::ui
