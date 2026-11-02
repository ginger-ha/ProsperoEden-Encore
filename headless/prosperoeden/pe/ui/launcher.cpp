// ProsperoEden - The launcher: home, library, settings and their dialogs.
// Copyright (C) 2026 BlackBearReloaded
// SPDX-License-Identifier: GPL-3.0-or-later

#include "pe/ui/launcher.hpp"
#include "pe/ui/case_media_selection.hpp"
#include "pe/core/log.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <utility>
#include <sys/stat.h>

namespace pe::ui
{

using audio::Cue;

namespace
{

constexpr Rect kScreen{0.0f, 0.0f, 1920.0f, 1080.0f};
const Color kWhite{1.0f, 1.0f, 1.0f, 1.0f};

// The native clock is local console time in 24-hour form. Format its
// display for the selected language region, without guessing missing time.
std::string localized_clock(const std::string& value, const std::string& region)
{
    if (region != tr("USA") && region != tr("Australia"))
        return value;
    if (value.size() != 5 || value[2] != ':' ||
        !std::isdigit(static_cast<unsigned char>(value[0])) ||
        !std::isdigit(static_cast<unsigned char>(value[1])) ||
        !std::isdigit(static_cast<unsigned char>(value[3])) ||
        !std::isdigit(static_cast<unsigned char>(value[4])))
        return value;
    const int hour = (value[0] - '0') * 10 + value[1] - '0';
    const int minute = (value[3] - '0') * 10 + value[4] - '0';
    if (hour > 23 || minute > 59)
        return value;
    return std::to_string((hour + 11) % 12 + 1) + value.substr(2) +
           (hour < 12 ? " AM" : " PM");
}

} // namespace

Launcher::ProfileAvatarProbe Launcher::probe_profile_avatar(Services &services)
{
    ProfileAvatarProbe probe;
    probe.path = services.profile_avatar();
    if (probe.path.empty()) return probe;
    // This worker-only file fingerprint makes an in-place NiakPS5 broker
    // replacement visible without stat/decode work in the 60 Hz UI path.
    struct stat file{};
    if (::stat(probe.path.c_str(), &file) != 0 || !S_ISREG(file.st_mode)) {
        probe.path.clear();
        return probe;
    }
    probe.device = static_cast<std::uint64_t>(file.st_dev);
    probe.inode = static_cast<std::uint64_t>(file.st_ino);
    probe.size = static_cast<std::uint64_t>(file.st_size);
    probe.mtime = static_cast<std::uint64_t>(file.st_mtime);
    probe.ctime = static_cast<std::uint64_t>(file.st_ctime);
    return probe;
}

Launcher::Launcher(Services &services, Textures &textures, const Fonts &fonts, bool first_start)
    : services_(services), textures_(textures), fonts_(fonts), first_start_(first_start)
{
    version_ = services_.version();
    prefs_ = services_.preferences();
    clock_ = localized_clock(services_.clock(), services_.language_region(prefs_.language));
    // Only the background worker queries the profile and its local cache.
    profile_avatar_scan_ = std::async(std::launch::async, [this] {
        return probe_profile_avatar(services_);
    });
    apply_look();
    // Show the existing Home shell immediately; native recent-ROM metadata
    // comes from one background snapshot. This is NOT a failed setup state.
    home_.setup_ready = true;
    home_.status = tr("Loading game library...");
    home_.system_status = tr("Loading game library...");
    home_focus_ = 2;
    home_springs_[static_cast<std::size_t>(home_focus_)].snap(1.0f);
    read_home();
    settings_.visible = 7;
    settings_.pitch = 88.0f;
    settings_.reset(8, 0);
    section_.snap(1.0f);
    detail_.snap(1.0f);
    // Defer the welcome/recovery cue and ROM enumeration until Home
    // reports its actual setup status; no visible UI design is altered.
}

Launcher::~Launcher()
{
    // The worker may still be reading files; cancel optional per-game
    // enumeration before joining, then keep Services alive through teardown.
    home_cancel_.store(true, std::memory_order_release);
    scan_cancel_.store(true, std::memory_order_release);
    media_cancel_.store(true, std::memory_order_release);
    diagnostics_cancel_.store(true, std::memory_order_release);
    if (scan_.valid())
        scan_.wait();
    if (home_scan_.valid())
        home_scan_.wait();
    if (presence_scan_.valid())
        presence_scan_.wait();
    if (home_media_scan_.valid())
        home_media_scan_.wait();
    if (media_scan_.valid())
        media_scan_.wait();
    if (diagnostics_scan_.valid())
        diagnostics_scan_.wait();
    if (profile_avatar_scan_.valid())
        profile_avatar_scan_.wait();
}

std::vector<Cue> Launcher::take_cues()
{
    std::vector<Cue> result;
    result.swap(cues_);
    return result;
}

void Launcher::say(const std::string &text, bool warning)
{
    message_ = text;
    message_warning_ = warning;
    message_age_ = 0.0f;
}

void Launcher::clear_confirmation()
{
    confirmation_ = Confirmation::none;
}

bool Launcher::confirm_action(Confirmation action)
{
    if (confirmation_ != action)
    {
        confirmation_ = action;
        confirmation_key_ = pressed_key_;
        const char *question = TR("Confirm this action?");
        switch (action)
        {
        case Confirmation::restore_defaults: question = TR("Restore default settings?"); break;
        case Confirmation::game_overrides: question = TR("Reset this game's custom settings?"); break;
        case Confirmation::mapping_reset: question = TR("Reset controller mapping?"); break;
        case Confirmation::shader_caches: question = TR("Clear cache?"); break;
        case Confirmation::console_mode: question = TR("Change console mode for this game?"); break;
        case Confirmation::exit_app: question = TR("Exit Eden Encore?"); break;
        default: break;
        }
        say(tr(question), true);
        cue(Cue::notify);
        return false;
    }
    clear_confirmation();
    message_.clear();
    return true;
}

void Launcher::open(Screen screen, bool forward)
{
    leaving_ = screen_;
    screen_ = screen;
    top_nav_focus_ = -1;
    // Home, Library and Settings are physical tabs. The Recent tab uses
    // Home's screen but its own active position until another tab is opened.
    if (screen == Screen::home) active_main_tab_ = 0;
    else if (screen == Screen::library) active_main_tab_ = 1;
    else if (screen == Screen::settings) active_main_tab_ = 3;
    forward_ = forward;
    transition_.start(theme::kScreenSeconds);
    message_.clear();
    clear_confirmation();
    cue(forward ? Cue::open : Cue::back);
}

void Launcher::open_modal(Modal modal)
{
    if (modal == Modal::diagnostics)
        start_diagnostics(); // refresh without recursive filesystem I/O in draw()
    modal_ = modal_shown_ = modal;
    option_ = 0;
    option_cursor_.snap(dialog_row_top(modal, 0));
    message_.clear();
    clear_confirmation();
    // Switches show their state at once; they only animate when changed.
    const std::array<bool, 3> states = switch_states(modal);
    for (std::size_t i = 0; i < states.size(); ++i)
        switches_[i].snap(states[i] ? 1.0f : 0.0f);
    cue(Cue::modal_open);
}

std::array<bool, 3> Launcher::switch_states(Modal modal) const
{
    switch (modal)
    {
    case Modal::video:
        return {prefs_.hud, false, false};
    case Modal::audio:
        return {prefs_.mute, false, false};
    case Modal::controls:
        return {false, prefs_.vibration, false};
    case Modal::accessibility:
        return {prefs_.large_text, prefs_.high_contrast, prefs_.reduce_motion};
    default:
        return {prefs_.detailed_logging, false, false};
    }
}

void Launcher::close_modal()
{
    const bool game_settings_closed = modal_ == Modal::game;
    modal_ = Modal::none;
    message_.clear();
    clear_confirmation();
    // A game dialog can change the same overrides displayed on Home.
    // Invalidate the UI-only cache after returning from that editor.
    if (game_settings_closed) {
        home_settings_cache_.clear();
        if (screen_ == Screen::home)
            refresh_home_hero();
    }
    cue(Cue::modal_close);
}

void Launcher::apply_look()
{
    look() = {prefs_.large_text, prefs_.high_contrast, prefs_.reduce_motion};
}

bool Launcher::save_preferences(bool quiet)
{
    const bool saved = services_.set_preferences(prefs_);
    if (saved) {
        // Global defaults can change whether an uncustomized title is
        // docked. Don't keep a stale per-title Home profile across saves.
        home_settings_cache_.clear();
        // A full-library scan is already a background job. Reuse it to
        // recalculate effective docked modes after global changes without
        // introducing per-selection JSON reads or stalling the Save key.
        if (scan_.valid())
            docked_refresh_after_scan_ = true;
        else
            start_scan();
        if (screen_ == Screen::home)
            refresh_home_hero();
    }
    if (!saved)
        say(tr("Could not save settings. Please try again."), true);
    else if (quiet)
        message_.clear();
    else
        say(tr("Saved. Applies when a game starts."));
    return saved;
}

void Launcher::launch(const std::string &file, const std::string &title, const std::string &cover)
{
    if (!services_.game_exists(file))
    {
        read_home();
        drop_missing_games();
        say(tr("ROM missing from the game files folder"), true);
        cue(Cue::error);
        return;
    }
    // Home can launch before its background library/mod sweep finishes.
    // Avoid wasting direct-memory and filesystem bandwidth on a list that
    // will be destroyed as the emulator takes over the console.
    home_cancel_.store(true, std::memory_order_release);
    scan_cancel_.store(true, std::memory_order_release);
    media_cancel_.store(true, std::memory_order_release);
    diagnostics_cancel_.store(true, std::memory_order_release);
    selected_game_ = services_.game_path(file);
    launch_title_ = title;
    launch_cover_ = cover;
    textures_.clear_case_pages();
    launch_composed_front_ = 0;
    launch_composed_back_ = 0;
    launch_composed_front_attempted_ = false;
    launch_composed_back_attempted_ = false;
    launch_composed_front_provisional_ = false;
    launch_composed_back_provisional_ = false;
    launch_composed_front_failures_ = 0;
    launch_composed_back_failures_ = 0;
    launch_composed_front_retry_after_ = 0.0f;
    launch_composed_back_retry_after_ = 0.0f;
    launch_case_game_ = Game{};
    launch_case_game_.name = title;
    launch_case_game_.cover = cover;
    launch_hero_.clear();
    launch_description_.clear();
    launch_screenshots_.clear();
    // Resolve metadata once. Never scan the disk or reach a remote artwork
    // provider in the draw loop, and preserve Home-only launches before a
    // complete Library scan has finished.
    std::uint64_t title_id = 0;
    for (const Game& game : games_) {
        if (game.file != file) continue;
        launch_case_game_ = game;
        title_id = game.title_id;
        launch_description_ = !game.description.empty() ? game.description : game.intro;
        launch_hero_ = game.hero;
        launch_screenshots_ = game.screenshots;
        break;
    }
    for (const Recent& recent : home_.recents) {
        if (recent.file != file) continue;
        if (title_id == 0) title_id = recent.title_id;
        if (launch_hero_.empty()) launch_hero_ = recent.hero;
        if (launch_description_.empty())
            launch_description_ = !recent.description.empty() ? recent.description : recent.intro;
        if (launch_screenshots_.empty() && !recent.screenshot.empty())
            launch_screenshots_.push_back(recent.screenshot);
        break;
    }
    if (home_.last_file == file) {
        if (title_id == 0) title_id = home_.last_title_id;
        if (launch_hero_.empty()) launch_hero_ = home_.last_hero;
        if (launch_description_.empty())
            launch_description_ = !home_.last_description.empty() ?
                home_.last_description : home_.last_intro;
        if (launch_screenshots_.empty() && !home_.last_screenshot.empty())
            launch_screenshots_.push_back(home_.last_screenshot);
    }
    if (launch_hero_.empty() && !launch_screenshots_.empty())
        launch_hero_ = launch_screenshots_.front();
    // Home and Recent launch routes may not have a fully populated Library
    // snapshot. Use their actual cached metadata, never an invented scan.
    launch_case_game_.name = title;
    launch_case_game_.cover = cover;
    launch_case_game_.hero = launch_hero_;
    launch_case_game_.screenshots = launch_screenshots_;
    launch_case_game_.description = launch_description_;
    // Front case ink is visible immediately on launch. Put its exact 704px
    // compositor bucket FIRST in the asynchronous decode queue, instead of
    // waiting behind the cover, every screenshot and the 1920px hero. This
    // only prioritizes existing local art; no synchronous decode or GPU work.
    if (const auto* front = case_media::FrontPaper(
            launch_case_game_.hero, launch_case_game_.cover,
            launch_case_game_.screenshots))
        (void)textures_.cover(*front, 704.0f);
    if (!launch_case_game_.cover.empty())
        (void)textures_.cover(launch_case_game_.cover, 760.0f);
    for (const auto& shot : launch_case_game_.screenshots)
        if (!shot.empty()) (void)textures_.cover(shot, 760.0f);
    if (!launch_hero_.empty())
        (void)textures_.cover(launch_hero_, 1920.0f);

    // Real, locally cached retail scans win independently per face. A missing
    // back is composed from cached game metadata, never faked as a real scan.
    const BoxArt case_art = services_.box_art(title_id);
    launch_box_front_ = case_art.front;
    launch_box_back_ = case_art.back;
    launch_box_spine_ = case_art.spine;
    launch_title_id_ = title_id;
    launch_case_placeholder_mask_ = 0;
    launch_case_ready_mask_ = 0;
    if (!launch_box_front_.empty()) (void)textures_.cover(launch_box_front_, 760.0f);
    if (!launch_box_back_.empty()) (void)textures_.cover(launch_box_back_, 760.0f);
    if (!launch_box_spine_.empty()) (void)textures_.cover(launch_box_spine_, 760.0f);
    launch_.start(theme::kLaunchSeconds);
    press_ = 1.0f;
    cue(Cue::launch);
}

void Launcher::press(Key key)
{
    // Avoid opening/launching the placeholder while the initial native
    // Home snapshot is still being read in the background.
    if (!home_loaded_)
        return;
    if (!selected_game_.empty())
        return; // a game is starting
    // A newer user action invalidates an asynchronous Home Triangle request.
    // Another Triangle press may immediately schedule a replacement request.
    pending_settings_file_.clear();
    // Confirmation is a real modal: Circle cancels, Cross confirms. Other buttons cannot leak
    // through to the underlying screen while the dialog is visible.
    if (confirmation_ != Confirmation::none)
    {
        // Exit is unlike setting resets: confirming it must not be replayed
        // as another Circle event, which would immediately reopen the dialog.
        if (confirmation_ == Confirmation::exit_app && key == Key::cross) {
            clear_confirmation();
            message_.clear();
            done_ = true; // normal RunApp -> main exit(0); no game selected
            cue(Cue::saved);
            return;
        }
        if (key == Key::circle)
        {
            clear_confirmation();
            message_.clear();
            cue(Cue::back);
            return;
        }
        if (key == Key::cross)
            key = confirmation_key_;
        else
        {
            cue(Cue::error);
            return;
        }
    }
    pressed_key_ = key;
    if (modal_ == Modal::game)
        return press_game(key);
    if (modal_ == Modal::mods)
        return press_mods(key);
    if (modal_ == Modal::mapping)
        return press_mapping(key);
    if (modal_ != Modal::none)
        return press_dialog(key);
    // L1/R1 are global main-tab shortcuts, including when focus is on a
    // Library cover. Dialogs and the 3D game handoff above remain exclusive.
    // Cross enters the existing tab handler; never duplicate screen setup.
    if ((key == Key::l1 || key == Key::r1) &&
        (screen_ == Screen::home || screen_ == Screen::library ||
         screen_ == Screen::settings)) {
        top_nav_focus_ = (active_main_tab_ + (key == Key::r1 ? 1 : 3)) % 4;
        (void)press_top_nav(Key::cross);
        return;
    }
    if (top_nav_focus_ >= 0 && screen_ != Screen::home)
    {
        if (press_top_nav(key))
            return;
    }
    switch (screen_)
    {
    case Screen::home:
        return prefs_.ui_theme == 1 ? press_switch_home(key) : press_home(key);
    case Screen::library:
        return prefs_.ui_theme == 1 ? press_switch_library(key) : press_library(key);
    case Screen::settings:
        return prefs_.ui_theme == 1 ? press_switch_settings(key) : press_settings(key);
    case Screen::files:
        return press_files(key);
    case Screen::language:
        return press_language(key);
    case Screen::about:
        if (key == Key::circle)
            open(Screen::home, false);
        return;
    }
}

void Launcher::update(float dt)
{
    time_ += dt;
    intro_ += dt;
    message_age_ += dt;
    backdrop_.update(dt);
    // When a user holds Down and the highlight appears to lag the panel,
    // attribute a rare >24 ms UPDATE stall to a specific subsystem instead
    // of guessing from the frame's draw/present times. No work/logging
    // beyond a few monotonic reads is added to normal smooth frames.
    const auto update_stage_begin = std::chrono::steady_clock::now();
    const auto slow_stage = [this](const char* phase, std::chrono::steady_clock::time_point started) {
        const auto now = std::chrono::steady_clock::now();
        if (now - started >= std::chrono::milliseconds(24) &&
            now - last_ui_hotspot_report_ >= std::chrono::seconds(2)) {
            last_ui_hotspot_report_ = now;
            const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - started);
            sys::log("EDEN_UI_HOTSPOT phase=%s elapsed_ms=%lld",
                     phase, static_cast<long long>(elapsed.count()));
        }
    };
    textures_.pump(dt);
    if (profile_avatar_scan_.valid() &&
        profile_avatar_scan_.wait_for(std::chrono::seconds(0)) == std::future_status::ready) {
        ProfileAvatarProbe found;
        try {
            found = profile_avatar_scan_.get();
        } catch (...) {
            // A failed foreground-user lookup must never retain a stale portrait.
        }
        if (found != profile_avatar_active_) {
            if (!profile_avatar_path_.empty())
                textures_.invalidate(profile_avatar_path_);
            profile_avatar_path_ = found.path;
            profile_avatar_active_ = std::move(found);
            if (!profile_avatar_path_.empty())
                (void)textures_.cover(profile_avatar_path_, 56.0f);
        }
    }
#ifdef PS5_NATIVE
    // Late account-cache mounting, broker staging and profile changes must
    // not leave the startup silhouette permanently blank. Only a worker
    // runs the PS5 user service, file I/O and avatar decoding.
    profile_avatar_refresh_elapsed_ += std::clamp(dt, 0.0f, 1.0f);
    if (!profile_avatar_scan_.valid() && profile_avatar_refresh_elapsed_ >= 5.0f) {
        profile_avatar_refresh_elapsed_ = 0.0f;
        profile_avatar_scan_ = std::async(std::launch::async, [this] {
            return probe_profile_avatar(services_);
        });
    }
#endif
    slow_stage("texture_upload", update_stage_begin);
    const auto media_started = std::chrono::steady_clock::now();
    finish_home_scan(); // nonblocking one-time Home application
    finish_scan(false);
    finish_diagnostics(); // nonblocking; heavy cache/log enumeration stays off the UI frame
    if (games_loaded_ && !pending_settings_file_.empty()) {
        const std::string file = std::move(pending_settings_file_);
        pending_settings_file_.clear();
        if (screen_ == Screen::home && modal_ == Modal::none && selected_game_.empty())
            (void)open_game_settings_at_file(file);
    }
    finish_home_media();
    finish_selected_media();
    slow_stage("media_merge", media_started);
    media_retry_timer_ += dt;
    if (media_retry_timer_ >= 8.0f) {
        media_retry_timer_ = 0.0f;
        if (screen_ == Screen::home) start_home_media();
        start_selected_media();
    }
    update_controllers(dt);
    transition_.update(dt);
    press_ = std::max(0.0f, press_ - dt / 0.18f);

    modal_open_.target = modal_ != Modal::none ? 1.0f : 0.0f;
    modal_open_.update(dt, 20.0f);
    if (modal_ == Modal::none && modal_open_.value < 0.01f)
        modal_shown_ = Modal::none;
    dim_.target = screen_ == Screen::home ? 0.0f : 0.30f;
    dim_.update(dt, 8.0f);

    for (std::size_t i = 0; i < home_springs_.size(); ++i)
    {
        home_springs_[i].target = static_cast<int>(i) == home_focus_ ? 1.0f : 0.0f;
        home_springs_[i].update(dt, theme::kFocusSpring);
    }
    library_.update(dt);
    settings_.update(dt);
    files_.update(dt);
    language_.update(dt);
    video_rows_.update(dt);
    game_rows_.update(dt);
    mod_rows_.update(dt);
    mapping_rows_.update(dt);
    mode_.target = selected_docked_ ? 0.0f : 1.0f;
    mode_.update(dt, 22.0f);
    const bool mods_on = library_.selected >= 0 && library_.selected < static_cast<int>(games_.size()) &&
                         games_[static_cast<std::size_t>(library_.selected)].mods_enabled;
    mods_switch_.target = mods_on ? 1.0f : 0.0f;
    mods_switch_.update(dt, 22.0f);
    detail_.target = 1.0f;
    detail_.update(dt, 14.0f);
    section_.target = 1.0f;
    section_.update(dt, 14.0f);
    if (modal_ != Modal::none && modal_ != Modal::mapping)
        option_cursor_.target = dialog_row_top(modal_, option_);
    option_cursor_.update(dt, theme::kCursorSpring);
    const std::array<bool, 3> states = switch_states(modal_shown_);
    for (std::size_t i = 0; i < states.size(); ++i)
    {
        switches_[i].target = states[i] ? 1.0f : 0.0f;
        switches_[i].update(dt, 22.0f);
    }

    presence_wait_ += dt;
    if (presence_wait_ >= 2.0f && selected_game_.empty())
    {
        presence_wait_ = 0.0f;
        const auto presence_started = std::chrono::steady_clock::now();
        check_games_present();
        slow_stage("game_presence_scan", presence_started);
    }

    clock_wait_ += dt;
    if (clock_wait_ >= 1.0f)
    {
        clock_wait_ = 0.0f;
        clock_ = localized_clock(services_.clock(), services_.language_region(prefs_.language));
    }

    if (!selected_game_.empty())
    {
        launch_.update(dt);
        if (!launch_.running)
            done_ = true;
    }
}

void Launcher::draw_screen(Canvas &c, Screen screen)
{
    switch (screen)
    {
    case Screen::home:
        return prefs_.ui_theme == 1 ? draw_switch_home(c) : draw_home(c);
    case Screen::library:
        return prefs_.ui_theme == 1 ? draw_switch_library(c) : draw_library(c);
    case Screen::settings:
        return prefs_.ui_theme == 1 ? draw_switch_settings(c) : draw_settings(c);
    case Screen::files:
        return prefs_.ui_theme == 1 ? draw_switch_files(c) : draw_files(c);
    case Screen::language:
        return prefs_.ui_theme == 1 ? draw_switch_language(c) : draw_language(c);
    case Screen::about:
        return prefs_.ui_theme == 1 ? draw_switch_about(c) : draw_about(c);
    }
}

bool Launcher::press_top_nav(Key key)
{
    if (top_nav_focus_ < 0)
        return false;

    switch (key)
    {
    case Key::left:
    case Key::right:
    {
        const int step = key == Key::right ? 1 : -1;
        top_nav_focus_ = (top_nav_focus_ + step + 4) % 4;
        cue(Cue::focus);
        return true;
    }
    case Key::down:
    case Key::circle:
        top_nav_focus_ = -1;
        cue(Cue::back);
        return true;
    case Key::up:
        return true;
    case Key::cross:
    {
        const int target = top_nav_focus_;
        if (target == 0)
        {
            open(Screen::home, false);
        }
        else if (target == 1)
        {
            if (screen_ == Screen::library)
            {
                top_nav_focus_ = -1;
                cue(Cue::focus);
            }
            else
            {
                open(Screen::library, true);
                enter_library();
            }
        }
        else if (target == 2)
        {
            open(Screen::home, false);
            active_main_tab_ = 2;
            if (!home_.recents.empty())
            {
                home_recent_ = 0;
                home_focus_ = 5; // first card in the Home recently-played rail
                refresh_home_hero();
            }
            else
            {
                home_focus_ = 2; // Home's Recently Played header item
            }
        }
        else
        {
            if (screen_ == Screen::settings)
            {
                top_nav_focus_ = -1;
                cue(Cue::focus);
            }
            else
            {
                open(Screen::settings, true);
                prefs_ = services_.preferences();
                section_.snap(1.0f);
            }
        }
        return true;
    }
    default:
        return true;
    }
}

void Launcher::draw_top_nav(Canvas &c, int active_tab, int focus_tab, float focus_amount)
{
    auto& list = c.list;
    // The packaged brand.tga comes from assets/icon0.png: the real
    // neon palm Eden Encore logo, not a synthetic cyan flower.
    // Draw the brand texture unmodified; never recolor its authored pixels.
    if (c.textures.brand() != 0)
        list.image(c.textures.brand(), {56.0f, 17.0f, 110.0f, 110.0f},
                   {0.0f, 0.0f, 1.0f, 1.0f}, kWhite);
    text(c, "EDEN", 175.0f, baseline(31.0f, 39.0f, 30.0f), 30.0f,
         theme::kTitle, Align::left, 2.3f);
    text(c, "ENCORE", 176.0f, baseline(76.0f, 21.0f, 17.0f), 17.0f,
         theme::kLimePale, Align::left, 4.0f);

    // Three principal tabs; Settings is the separate top-right gear.
    // Four stable focus positions preserve controller navigation and actions.
    static constexpr const char* labels[] = {TR("Home"), TR("Library"), TR("Recent")};
    static constexpr float xs[] = {355.0f, 558.0f, 790.0f, 1480.0f};
    static constexpr float widths[] = {190.0f, 218.0f, 220.0f, 68.0f};
    for (int i = 0; i < 4; ++i)
    {
        const Rect r{xs[i], i == 3 ? 40.0f : 44.0f, widths[i], i == 3 ? 60.0f : 54.0f};
        const bool active = i == active_tab;
        const float focused = i == focus_tab ? tween::clamp01(focus_amount) : 0.0f;
        if (active)
        {
            list.shadow({r.x - 5.0f, r.y - 5.0f, r.w + 10.0f, r.h + 10.0f},
                        23.0f, 27.0f, theme::kLime.with_alpha(0.29f));
            list.hgradient_rect(r, 19.0f,
                                Color::rgb(0x301446, 0.73f),
                                Color::rgb(0x110a21, 0.48f),
                                2.0f, theme::kFocusBlue.with_alpha(0.96f));
            list.bordered_rect({r.x + 2.0f, r.y + 2.0f, r.w - 4.0f, r.h - 4.0f},
                               17.0f, kWhite.with_alpha(0.0f), 0.8f,
                               theme::kLimePale.with_alpha(0.28f));
        }
        if (focused > 0.001f)
            plate_focus(c, kNavPlate, r, focused);
        const float gx = i == 3 ? r.x + r.w * 0.5f : r.x + 30.0f;
        const float gy = r.y + r.h * 0.5f;
        const Color ink = active || focused > 0.01f ? theme::kTitle : theme::kMuted;
        if (i == 0) {
            list.triangle({gx - 13.0f, gy - 16.0f, 26.0f, 17.0f}, ink);
            list.rounded_rect({gx - 10.0f, gy - 2.0f, 20.0f, 16.0f}, 2.0f, ink);
        } else if (i == 1) {
            list.bordered_rect({gx - 12.0f, gy - 14.0f, 16.0f, 30.0f}, 3.0f,
                               theme::kGlass, 2.0f, ink);
            list.bordered_rect({gx + 5.0f, gy - 10.0f, 11.0f, 27.0f}, 3.0f,
                               theme::kGlass, 2.0f, ink);
        } else if (i == 2) {
            list.ring(gx, gy, 13.0f, 2.6f, ink);
            list.line(gx, gy, gx, gy - 8.0f, 2.6f, ink);
            list.line(gx, gy, gx + 7.0f, gy + 5.0f, 2.6f, ink);
        } else {
            settings_gear(c, gx, gy, 19.0f, ink);
        }
        if (i < 3) {
            const float label_width = r.w - 70.0f;
            text_shrink(c, tr(labels[i]), r.x + 60.0f + label_width * 0.5f,
                        baseline(r.y, r.h, theme::kSmall), theme::kSmall,
                        ink, label_width - 8.0f, Align::center);
        }
    }

    // Use the real foreground console profile when a readable local cache
    // image exists; otherwise keep a neutral silhouette. No network request.
    constexpr float avatar_x = 1640.0f, avatar_y = 70.0f;
    list.rounded_rect({avatar_x - 27.0f, avatar_y - 27.0f, 54.0f, 54.0f},
                      27.0f, theme::kPanel.with_alpha(0.90f));
    const Cover avatar = profile_avatar_path_.empty() ? Cover{} :
        c.textures.cover(profile_avatar_path_, 54.0f);
    if (avatar.texture != 0) {
        Rect uv{0.0f, 0.0f, 1.0f, 1.0f};
        const float aspect = std::max(0.01f, avatar.aspect);
        if (aspect > 1.0f) {
            uv.w = 1.0f / aspect;
            uv.x = (1.0f - uv.w) * 0.5f;
        } else if (aspect < 1.0f) {
            uv.h = aspect;
            uv.y = (1.0f - uv.h) * 0.5f;
        }
        list.rounded_image(avatar.texture,
                           {avatar_x - 25.0f, avatar_y - 25.0f, 50.0f, 50.0f},
                           uv, 25.0f, kWhite);
    } else {
        list.rounded_rect({avatar_x - 8.0f, avatar_y - 16.0f, 16.0f, 16.0f},
                          8.0f, theme::kTitle.with_alpha(0.94f));
        list.rounded_rect({avatar_x - 17.0f, avatar_y + 5.0f, 34.0f, 14.0f},
                          7.0f, theme::kTitle.with_alpha(0.94f));
    }
    list.ring(avatar_x, avatar_y, 26.0f, 1.8f,
              theme::kPanelEdge.with_alpha(0.88f));

    text(c, clock_, 1848.0f, baseline(42.0f, 54.0f, theme::kClock), theme::kClock,
         theme::kTitle, Align::right);
    list.rounded_rect({72.0f, 126.0f, 1776.0f, 1.0f}, 0.0f, theme::kText.with_alpha(0.12f));
}

void Launcher::draw_frame(Canvas &c, const char *title, const char *copy)
{
    // Storage, Language and About are Settings subpages; keep the global TV shell visible so
    // entering a utility never feels like falling back to the old launcher.
    draw_top_nav(c, 3);
    text_shrink(c, title, 72.0f, baseline(142.0f, 38.0f, theme::kHeading), theme::kHeading,
                theme::kTitle, 1280.0f);
    text_shrink(c, copy, 72.0f, baseline(176.0f, 24.0f, 18.0f), 18.0f, theme::kMeta,
                1540.0f);
}

void Launcher::draw_footer(Canvas &c, const Hint *hints, int count)
{
    c.list.rounded_rect({108.0f, 955.0f, 1704.0f, 1.0f}, 0.0f, theme::kRule.with_alpha(0.9f));
    draw_hints(c, hints, count, 108.0f, 987.0f, theme::kCopy, 1704.0f);
}

void Launcher::draw_confirmation(Canvas &c)
{
    if (confirmation_ == Confirmation::none)
        return;

    const char *title = tr("Settings");
    if (confirmation_ == Confirmation::console_mode)
        title = tr("Console mode");
    else if (confirmation_ == Confirmation::mapping_reset)
        title = tr("Controls");
    else if (confirmation_ == Confirmation::shader_caches)
        title = tr("Diagnostics");
    else if (confirmation_ == Confirmation::exit_app)
        title = tr("Exit Eden Encore");

    c.list.rounded_rect(kScreen, 0.0f, theme::kScrim.with_alpha(0.74f));
    const Rect panel{548.0f, 354.0f, 824.0f, 330.0f};
    c.list.shadow({panel.x - 16.0f, panel.y - 12.0f, panel.w + 32.0f, panel.h + 36.0f},
                  38.0f, 74.0f, theme::kLime.with_alpha(0.20f));
    glass(c, panel, 30.0f, theme::kGlass.with_alpha(0.94f), theme::kLime.with_alpha(0.68f), 1.2f);
    c.list.rounded_rect({panel.x + 28.0f, panel.y + 34.0f, 6.0f, 94.0f}, 3.0f, theme::kLime);
    text_shrink(c, title, panel.x + 64.0f, baseline(panel.y + 38.0f, 54.0f, theme::kHeading),
                theme::kHeading, theme::kTitle, panel.w - 104.0f);
    text_block(c, message_, panel.x + 64.0f, baseline(panel.y + 142.0f, 38.0f, theme::kText24),
               theme::kText24, 40.0f, theme::kBody, panel.w - 128.0f, 2, kShrink);
    static constexpr Hint kConfirmHints[] = {
        {Pad::cross, TR("Confirm")}, {Pad::circle, TR("Cancel")}};
    draw_hints(c, kConfirmHints, 2, panel.x + 64.0f, panel.y + panel.h - 52.0f,
               theme::kText, panel.w - 128.0f);
}

void Launcher::draw_launch(Canvas &c)
{
    const float t = tween::clamp01(launch_.progress());
    const float seconds = theme::kLaunchSeconds * t;
    // No fade to black: the Vulkan loading surface reuses this EXACT final
    // launcher picture until the guest actually presents its first frame.
    const float appear = tween::cubic_out(seconds / 0.25f);
    const float leave = 1.0f; // Hold the jacket/hero, never a second empty loader.

    // Use exactly the full-bleed Hero asset already shown for this title on
    // Home (Nlib banner, then screenshot). No menu cards, duplicate text or
    // navigation beneath this overlay. The Eden wallpaper stays as fallback.
    if (!launch_hero_.empty()) {
        const Cover background = c.textures.cover(launch_hero_, 1920.0f);
        if (background.texture != 0) {
            constexpr float target = 1920.0f / 1080.0f;
            const float source = std::max(0.01f, background.aspect);
            Rect uv{0.0f, 0.0f, 1.0f, 1.0f};
            if (source > target) {
                uv.w = target / source;
                uv.x = (1.0f - uv.w) * 0.5f;
            } else if (source < target) {
                uv.h = source / target;
                uv.y = (1.0f - uv.h) * 0.5f;
            }
            c.list.image(background.texture, kScreen, uv,
                         kWhite.with_alpha(tween::cubic_out(background.age / 0.26f)));
        }
    }
    // Preserve the colors of the game's scene while providing a legible right
    // column. Unlike the former 91% black scrim, the Hero remains recognizable.
    c.list.rounded_rect(kScreen, 0.0f, theme::kScrim.with_alpha(0.16f));
    c.list.hgradient_rect(kScreen, 0.0f,
                          theme::kScrim.with_alpha(0.12f),
                          theme::kScrim.with_alpha(0.83f));
    c.list.gradient_rect({0.0f, 490.0f, 1920.0f, 590.0f}, 0.0f,
                         theme::kBase.with_alpha(0.0f),
                         theme::kBase.with_alpha(0.65f));

    c.list.push_opacity(appear * leave);

    // Low-cost elliptical light trails behind the case, drawn with the
    // launcher's own line primitives (no extra textures or shaders). Their
    // glow stays off the text column and does not tint the printed covers.
    constexpr float pi = 3.14159265358979323846f;
    for (int i = 0; i < 72; ++i) {
        const float a = static_cast<float>(i) * (2.0f * pi / 72.0f);
        const float b = static_cast<float>(i + 1) * (2.0f * pi / 72.0f);
        const float drift = motion() > 0.0f ? t * 0.45f : 0.0f;
        const float brightness = 0.16f + 0.26f *
            (0.5f + 0.5f * std::sin(a * 2.0f - c.time * 1.6f));
        c.list.line(512.0f + 454.0f * std::cos(a + drift),
                    526.0f + 117.0f * std::sin(a + drift),
                    512.0f + 454.0f * std::cos(b + drift),
                    526.0f + 117.0f * std::sin(b + drift),
                    2.3f, theme::kLime.with_alpha(brightness));
    }
    c.list.shadow({194.0f, 796.0f, 795.0f, 80.0f}, 42.0f, 94.0f,
                  theme::kSun.with_alpha(0.18f));

    // Every game uses this exact geometric case, independent of the artwork
    // source. The *same pivot* and camera project front/back and the plastic
    // side in the OpenGL vertex shader; the scan is a perspective-correct
    // texture on the face rather than a 2D width squash.
    // Hold the rear cover 4.5 seconds at full width. A constant 360-degree
    // spin would make the physical description impossible to read.
    const float turn_start = theme::kCaseFrontHold;
    const float back_start = turn_start + theme::kCaseTurnSeconds;
    const float return_start = back_start + theme::kCaseBackHold;
    // The front exposes the real LEFT red spine. On the nearly face-on
    // back, the real clear opening appears on the LEFT through perspective.
    // No cosmetic red stripe is superimposed on the right edge. Both poses
    // use the exact same shared case geometry for every game.
    constexpr float kFrontYaw = 0.52f;
    constexpr float kBackYaw = 3.14159265358979323846f + 0.18f;
    constexpr float kFullTurn = 6.28318530717958647692f;
    float angle = kFrontYaw;
    if (motion() > 0.0f) {
        if (seconds < turn_start) {
            angle = kFrontYaw;
        } else if (seconds < back_start) {
            angle = kFrontYaw + (kBackYaw - kFrontYaw) *
                tween::cubic_in_out((seconds - turn_start) / theme::kCaseTurnSeconds);
        } else if (seconds < return_start) {
            angle = kBackYaw;
        } else {
            angle = kBackYaw + (kFullTurn + kFrontYaw - kBackYaw) *
                tween::cubic_in_out((seconds - return_start) / theme::kCaseTurnSeconds);
        }
    }
    const float facing = std::cos(angle);
    const bool back = facing < 0.0f;
    constexpr float case_depth = 44.0f;
    constexpr float case_radius = 22.0f;
    // Use the actual reusable case outline for projected shadow/geometry.
    // The reference template is taller than the previous 422x655 poster.
    const Rect physical{374.0f, 126.0f, 454.0f, 730.0f};
    const float width = physical.w * std::abs(facing) +
                        case_depth * std::abs(std::sin(angle));
    // The case shell is wider than its continuous rectangular paper wrap:
    // the LEFT and RIGHT 7px are molded clear-plastic lips, not blank
    // gaps BETWEEN the three printed surfaces. Front, printed spine and
    // back have identical paper coordinates and share the very same folds.
    // Only the plastic gets rounded corners. Paper corners stay square.
    constexpr float kPaperSideInset = 7.0f;
    constexpr float kPaperTopInset = 13.0f;
    const Rect face{physical.x + kPaperSideInset,
                    physical.y + kPaperTopInset,
                    physical.w - 2.0f * kPaperSideInset,
                    physical.h - 2.0f * kPaperTopInset};
    const float mid_x = physical.x + physical.w * 0.5f;
    c.list.shadow({mid_x - width * 0.5f - 72.0f, physical.y - 8.0f,
                   width + 144.0f, physical.h + 34.0f}, 35.0f, 105.0f,
                  Color::rgb(0x05040b, 0.84f));
    c.list.shadow({mid_x - width * 0.5f - 22.0f, physical.y + 6.0f,
                   width + 44.0f, physical.h - 6.0f}, 29.0f, 33.0f,
                  Color::rgb(0x190f23, 0.44f));
    c.list.shadow({mid_x - width * 0.39f - 50.0f,
                   physical.y + physical.h - 18.0f,
                   width * 0.78f + 100.0f, 86.0f}, 39.0f, 80.0f,
                  Color::rgb(0x020208, 0.83f));

    // The molded plastic is rendered by its own shell/cap/corner surfaces.
    // Do not draw another opaque full-size face under the printed paper.

    // An authentic front/back has first priority. When no physical scan was
    // found, existing Nlib game art supplies the relevant face. No title-
    // specific look, filenames or artwork are hardcoded in production.
    const std::string& scan = back ? launch_box_back_ : launch_box_front_;
    // A missing retail face must NEVER expose a raw front/hero image with
    // source-ratio UV gaps during the transition. Only the composed opaque
    // paper face or its plain opaque paper substrate may be displayed.
    const Cover artwork = scan.empty() ? Cover{} : c.textures.cover(scan, 760.0f);
    // Warm BOTH missing faces during the initial front hold. Previous code
    // first requested the rear's small scene textures only AFTER turning,
    // then permanently baked a black collage because its 760px prefetch
    // represented a DIFFERENT cache entry than the 256/512px rear panels.
    // Pre-render each side only after the exact compositor texture buckets
    // are decoded. Authentic scans bypass this entire path.
    const auto prepare_case_page = [&](bool rear) {
        const std::string& retail = rear ? launch_box_back_ : launch_box_front_;
        std::uint32_t& page = rear ? launch_composed_back_ : launch_composed_front_;
        bool& attempted = rear ? launch_composed_back_attempted_
                               : launch_composed_front_attempted_;
        bool& provisional = rear ? launch_composed_back_provisional_
                                 : launch_composed_front_provisional_;
        unsigned& failures = rear ? launch_composed_back_failures_
                                  : launch_composed_front_failures_;
        float& retry_after = rear ? launch_composed_back_retry_after_
                                  : launch_composed_front_retry_after_;
        // A path in the metadata is not proof that the scan exists. Wait
        // while it decodes, but use the composed print after a failed load;
        // the authentic scan automatically resumes priority if retried.
        if (!retail.empty() && !c.textures.cover(retail, 760.0f).missing)
            return;
        if ((page != 0 && !provisional) ||
            (page == 0 && attempted) || failures >= 3u) return;
        if (seconds < retry_after) return;
        // Keep the opaque provisional paper available after a bounded wait,
        // but revisit it when ALL known async sources have finished decoding.
        // Refreshes reuse its GL ID: only two case pages are ever allocated.
        const bool inputs_ready = composed_case_face_ready(
            c.textures, launch_case_game_, rear, false);
        if (!case_media::PageInputReady(page != 0, inputs_ready, seconds))
            return;
        const bool refreshing = page != 0;
        attempted = true;
        constexpr float ink_scale = 1.5f;
        constexpr int paper_w = 660, paper_h = 1056;
        gfx::DrawList print;
        Canvas ink{print, c.fonts, c.textures, c.backdrop, c.time};
        print.push_transform(ink_scale, 0.0f, 0.0f, 0.0f, 0.0f);
        draw_composed_case_face(ink, launch_case_game_,
                                {0.0f, 0.0f, 440.0f, 704.0f}, rear);
        print.pop_transform();
        const std::uint32_t rendered = c.textures.render_case_page(
            print, c.fonts.font, c.fonts.texture, paper_w, paper_h, page);
        if (rendered == 0) {
            // Do not discard an already displayed provisional page after a
            // transient framebuffer failure. Retry at most three GL draws.
            ++failures;
            if (failures < 3u) {
                if (!refreshing) attempted = false;
                retry_after = seconds + 0.25f * static_cast<float>(failures);
            }
        } else {
            page = rendered;
            provisional = !inputs_ready;
            failures = 0;
        }
        if (rendered != 0)
            sys::log("EDEN_CASE_COMPOSE title=%016llX side=%s status=%s page=%u",
                     static_cast<unsigned long long>(launch_title_id_),
                     rear ? "back" : "front",
                     refreshing ? "refreshed" : (provisional ? "provisional" : "ready"), page);
        else
            sys::log("EDEN_CASE_COMPOSE title=%016llX side=%s status=failed",
                     static_cast<unsigned long long>(launch_title_id_),
                     rear ? "back" : "front");
    };
    prepare_case_page(false);
    prepare_case_page(true);
    const std::uint32_t composed_page =
        back ? launch_composed_back_ : launch_composed_front_;
    const bool use_composed = (scan.empty() || artwork.missing) &&
                              composed_page != 0;
    const std::uint32_t visible_texture =
        use_composed ? composed_page : artwork.texture;
    // One event per visible paper face and state, NEVER a per-frame log.
    // Stored/decoded/uploaded assets can still fail to reach the render list;
    // this is the last observable stage before the case-face GPU draw call.
    const unsigned face_bit = back ? 2u : 1u;
    if (visible_texture == 0 && !(launch_case_placeholder_mask_ & face_bit)) {
        launch_case_placeholder_mask_ |= face_bit;
        sys::log("EDEN_CASE_DRAW title=%016llX side=%s status=placeholder retail_path=%d",
                 static_cast<unsigned long long>(launch_title_id_),
                 back ? "back" : "front", !scan.empty());
    } else if (visible_texture != 0 && !(launch_case_ready_mask_ & face_bit)) {
        launch_case_ready_mask_ |= face_bit;
        sys::log("EDEN_CASE_DRAW title=%016llX side=%s status=ready source=%s texture=%u",
                 static_cast<unsigned long long>(launch_title_id_),
                 back ? "back" : "front",
                 use_composed ? "composed" : (scan.empty() ? "fallback" : "retail"),
                 visible_texture);
    }
    // One fully opaque paper sheet underneath either face. A narrow genuine
    // scan and the first frames of an async composition can never reveal
    // transparent black or molded plastic through its upper/lower margins.
    c.list.case_face(0, face, angle, back, Color::rgb(0x112235));
    if (use_composed) {
        // OpenGL framebuffer textures have bottom-left origin. Flip Y once,
        // then let the existing 3D case-face shader project both printed
        // faces onto the same physical shell as original retailer scans.
        c.list.case_face(composed_page, face, angle, back, kWhite,
                         {0.0f, 1.0f, 1.0f, -1.0f});
    } else if (!scan.empty() && artwork.texture != 0) {
        // Keep the WHOLE printed back visible: never stretch a scan or crop
        // its French description. Letterbox only for unmatched source ratios.
        // Transparent excess UV is discarded by the case-face fragment shader.
        const float target_aspect = face.w / face.h;
        const float source_aspect = std::max(0.01f, artwork.aspect);
        Rect paper_uv{0.0f, 0.0f, 1.0f, 1.0f};
        if (source_aspect > target_aspect) {
            paper_uv.h = source_aspect / target_aspect;
            paper_uv.y = (1.0f - paper_uv.h) * 0.5f;
        } else {
            paper_uv.w = target_aspect / source_aspect;
            // The printed paper meets the spine with NO UV letterbox gap:
            // the front attaches at the left, the back at the right.
            paper_uv.x = back ? 1.0f - paper_uv.w : 0.0f;
        }
        c.list.case_face(artwork.texture, face, angle, back, kWhite, paper_uv);
    }
    // Depth-bearing top/bottom plastic caps remain in painter order above
    // the scan. Their front/rear refractive outline is separately lit by
    // the single shape-11 shell rim, even when these faces project edge-on.
    c.list.case_cap({physical.x + case_radius, physical.y,
                     physical.w - 2.0f * case_radius, physical.h},
                    angle, false, case_depth,
                    Color::rgb(0xe9f3ff, 0.79f),
                    Color::rgb(0x71859d, 0.62f));
    c.list.case_cap({physical.x + case_radius, physical.y,
                     physical.w - 2.0f * case_radius, physical.h},
                    angle, true, case_depth,
                    Color::rgb(0xddeaf8, 0.78f),
                    Color::rgb(0x60748a, 0.65f));
    // One 12px latch plus 13px TOP/BOTTOM mold lines, NEVER a translucent
    // second face over the print: the shader clips strictly to these strips.
    // On the rear view the same physical right opening projects to the left.
    c.list.case_plastic(physical, angle, back, Color::rgb(0xd9e8f7, 0.93f));

    // A real case has TWO different sides. The left is the printed red
    // retail spine, the right is the mostly clear hinged latch edge.
    // The visible side changes as the rigid box rotates; no artificial red
    // strip on the wrong side during the back-cover hold.
    // The flat spine printing follows the SAME vertical paper limits as the
    // two faces: all three share a 704px paper height inside the 730px shell.
    // Only the translucent molded caps/rounded corners extend beyond it.
    // Critical seam invariant: print side plane and both face planes share
    // precisely the same X boundaries; a transparent plastic margin exists
    // OUTSIDE these boundaries, never in between paper and paper.
    const Rect side_strip = face;
    const bool printed_side_visible = std::sin(angle) >= 0.0f;
    if (printed_side_visible) {
        const Cover ink = c.textures.cover(launch_box_spine_, 760.0f);
        if (ink.texture != 0) {
            // Printed spine fills the SAME depth as the front/back paper:
            // neither an inset (3px) nor a shorter strip (depth-6px).
            c.list.case_spine(side_strip, angle, case_depth,
                              Color::rgb(0xa90e20), Color::rgb(0x6d1020));
            c.list.case_spine_image(ink.texture, side_strip, angle,
                                    case_depth, kWhite);
        } else {
            // Source-independent empty spine: vector white reference-style
            // marks and red ink, never any low-res or invented game title.
            c.list.case_spine_blank(side_strip, angle, case_depth,
                                    Color::rgb(0xd91b2e, 0.96f));
        }
    } else {
        // One actual left opening wall: no extra hinge bars pasted across
        // the back scan and no second white lip at the paper/spine seam.
        c.list.case_spine(side_strip, angle, case_depth,
                          Color::rgb(0xc9d7e7, 0.57f),
                          Color::rgb(0x75879b, 0.48f));
    }
    // Deliberately NO right-side red stripe on the rear view.
    // Only genuinely visible projected shell edges are rendered.
    // Do not add two fake white depth strips at paper-to-spine junctions.
    // The real rounded plastic corner mesh below defines the shell edge.

    // A true curved perimeter: 8 actual depth-bearing strips per quarter
    // arc. Only the visible pair occludes the printed insert.
    const bool show_left = std::sin(angle) >= 0.0f;
    for (int quadrant = 0; quadrant < 4; ++quadrant) {
        const bool left = quadrant == 0 || quadrant == 3;
        if (left != show_left) continue;
        for (int part = 0; part < 8; ++part)
            c.list.case_corner(physical, angle, case_radius, case_depth,
                               quadrant, part, Color::rgb(0xdbe5f0, 0.59f),
                               Color::rgb(0x677588, 0.49f));
    }

    // The brand/title column begins well after the 3D case's cast shadow.
    constexpr float brand_x = 1382.0f;
    if (c.textures.brand() != 0)
        c.list.image(c.textures.brand(), {brand_x - 151.0f, 147.0f, 302.0f, 302.0f},
                     {0.0f, 0.0f, 1.0f, 1.0f}, kWhite);
    text_shrink(c, launch_title_, brand_x, 535.0f, 45.0f,
                theme::kTitle, 650.0f, Align::center, 0.0f, 0.57f);
    c.list.rounded_rect({brand_x - 155.0f, 574.0f, 310.0f, 2.0f}, 1.0f,
                        theme::kLimePale.with_alpha(0.66f));
    text(c, tr("STARTING"), brand_x, 659.0f, theme::kText24,
         theme::kText, Align::center);
    for (int i = 0; i < 3; ++i) {
        const float pulse = 0.32f + 0.68f *
            (0.5f + 0.5f * std::sin(c.time * 5.5f - i * 1.15f));
        c.list.circle(brand_x - 26.0f + 26.0f * i, 716.0f, 4.0f,
                      theme::kBlue.with_alpha(pulse));
    }
    c.list.pop_opacity();
}

void Launcher::draw(gfx::DrawList &list)
{
    Canvas c{list, fonts_, textures_, backdrop_, time_};
    if (prefs_.ui_theme == 1 && selected_game_.empty())
        list.rounded_rect(kScreen, 0.0f, gfx::Color::rgb(0xf7f7f7));
    else
        backdrop_.draw(list, textures_, dim_.value);

    // During the game handoff only the selected game's cinematic Hero and
    // rotating box are drawn, not Home/Library controls behind a black scrim.
    if (!selected_game_.empty()) {
        draw_launch(c);
        return;
    }
    const bool launching = false;
    const float zoom =
        launching ? 1.0f + 0.045f * tween::cubic_in_out(launch_.progress()) * motion() : 1.0f;
    list.push_transform(zoom, 960.0f, 540.0f, 0.0f, 0.0f);
    if (transition_.running)
    {
        // The old screen slides away as the new one arrives from the other side.
        const float t = transition_.progress();
        const float e = tween::cubic_in_out(t);
        const float direction = forward_ ? 1.0f : -1.0f;
        list.push_opacity(1.0f - tween::cubic_out(t / 0.55f));
        list.push_transform(1.0f, 0.0f, 0.0f, -direction * 56.0f * e * motion(), 0.0f);
        draw_screen(c, leaving_);
        list.pop_transform();
        list.pop_opacity();
        list.push_opacity(tween::cubic_out((t - 0.2f) / 0.8f));
        list.push_transform(1.0f, 0.0f, 0.0f, direction * 56.0f * (1.0f - e) * motion(), 0.0f);
        draw_screen(c, screen_);
        list.pop_transform();
        list.pop_opacity();
    }
    else
    {
        draw_screen(c, screen_);
    }
    if (modal_shown_ != Modal::none)
    {
        const float opened = tween::clamp01(modal_open_.value);
        list.rounded_rect(kScreen, 0.0f, theme::kScrim.with_alpha(0.69f * opened));
        if (modal_shown_ == Modal::game)
            prefs_.ui_theme == 1 ? draw_switch_game(c, opened) : draw_game(c, opened);
        else if (modal_shown_ == Modal::mods)
            prefs_.ui_theme == 1 ? draw_switch_mods(c, opened) : draw_mods(c, opened);
        else if (modal_shown_ == Modal::mapping)
            prefs_.ui_theme == 1 ? draw_switch_mapping(c, opened) : draw_mapping(c, opened);
        else if (prefs_.ui_theme == 1)
            draw_switch_dialog(c, modal_shown_, opened);
        else
            draw_dialog(c, modal_shown_, opened);
    }
    if (prefs_.ui_theme == 1)
        draw_switch_confirmation(c);
    else
        draw_confirmation(c);
    list.pop_transform();
    if (launching)
        draw_launch(c);

    // The launcher arrives out of the dark.
    const float arrival = 1.0f - tween::cubic_out(intro_ / (first_start_ ? 0.7f : 0.45f));
    if (arrival > 0.0f)
        list.rounded_rect(kScreen, 0.0f, Color{0.0f, 0.0f, 0.0f, arrival});
}

} // namespace pe::ui
