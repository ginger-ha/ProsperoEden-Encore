// SPDX-License-Identifier: GPL-3.0-or-later
// The launcher on the console: its display, sound and controller, and the frame loop around
// pe::ui::Launcher. Everything here is created when the launcher appears and gone before a game
// starts: the game's own window takes over the screen.
#include "frontend.h"
#include "launch_handoff.hpp"

#include "assets_dir.h"
#include "audio_out_init.h"
#include "diagnostics.h"
#include "eden_services.h"
#include "pe/audio/sounds.hpp"
#include "pe/core/file.hpp"
#include "pe/core/strings.hpp"
#include "pe/gfx/gl_batch.hpp"
#include "pe/gfx/system_fonts.hpp"
#include "pe/platform/audio_out.hpp"
#include "pe/platform/display_egl.hpp"
#include "pe/ui/launcher.hpp"
#include "pe/ui/theme.hpp"
#include "radio_input.h"
#include <cerrno>
#include <cstring>
#include "ps5_system_language.hpp"
#include "fr_fr_embedded.h"
#ifdef EDEN_DEV_ROM_ID
#include "crash_trigger.h"
#include "development_input.h"
#include <fstream>
#endif

#include <algorithm>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <iterator>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <new>
#include <pthread.h>
#include <string>
#include <utility>
#include <vector>

extern "C" int sceKernelUsleep(std::uint32_t microseconds);
extern "C" int sceSystemServiceHideSplashScreen(void);

namespace {

using Clock = std::chrono::steady_clock;

// The launcher draws at the size of Settings > Video > Output resolution (settings_store.h,
// kOutputKeys); the console scales it to the TV. *output names the size that opened: 1080p when
// the chosen one did not.
bool OpenDisplay(pe::ps5::Display& display, int* output) {
    if (display.open(Eden::kOutputWidth[*output], Eden::kOutputHeight[*output])) return true;
    if (*output == 0) return false;
    *output = 0;
    return display.open(Eden::kOutputWidth[0], Eden::kOutputHeight[0]);
}

// The controller's keys arrive in the launcher's order.
static_assert(static_cast<int>(pe::ui::Key::cross) == RADIO_INPUT_CROSS &&
              static_cast<int>(pe::ui::Key::options) == RADIO_INPUT_OPTIONS &&
              static_cast<int>(pe::ui::Key::right) == RADIO_INPUT_RIGHT);

long long Milliseconds(Clock::duration value) {
    return std::chrono::duration_cast<std::chrono::milliseconds>(value).count();
}

// Menu sound level 0-100 as a gain: quiet steps stay audible, the top is full level.
float MenuGain(int volume) {
    const float level = static_cast<float>(std::clamp(volume, 0, 100)) / 100.0f;
    return level * level;
}

// The launcher speaks the console's language when the app has a catalog for it
// (ui/lang/<tag>.po, tags as in third_party/ps5_system_language.hpp), and English otherwise.
// Development profiles may override it with language.txt; release builds always follow the saved setting.
//
// Montserrat has Latin and Cyrillic letters. The other scripts (Japanese, Korean, Chinese, Greek,
// Thai, Arabic: in the launcher's own text, a game's title or a file name) are drawn with the
// console's own fonts, which the font is told of here every time the launcher opens. A catalog
// those fonts cannot draw in full is not used: English is better than missing letters.
void LoadLanguage(pe::gfx::Font& font) {
    int system_language = -1;
    const int rc = sceSystemServiceParamGetInt(ps5::i18n::kSystemLanguageParameter, &system_language);
    const Eden::Preferences preferences = Eden::LoadPreferences();
    const int language = std::clamp(preferences.language, 0,
                                    int(std::size(Eden::kLanguageCatalogTags)) - 1);
    std::string tag = Eden::kLanguageCatalogTags[language];
#ifdef EDEN_DEV_PROFILE
    // Development builds may force a catalog without rewriting preferences. Release builds must
    // never honor a stale language.txt left behind by an older test install.
    std::string chosen;
    if (pe::read_file(Eden::AppFile("language.txt"), &chosen, 64)) {
        while (!chosen.empty() && static_cast<unsigned char>(chosen.back()) <= ' ') chosen.pop_back();
        if (!chosen.empty()) tag = chosen;
    }
#endif

    std::string folder = "none";
    std::size_t files = 0;
    for (const std::string& candidate : pe::gfx::system_font_folders()) {
        std::vector<std::string> found = pe::gfx::system_font_files(candidate, tag);
        if (found.empty()) continue;
        folder = candidate;
        files = found.size();
        font.use_system_fonts(std::move(found), tag);
        break;
    }

    // Every launcher instance starts with a clean catalog. This is essential when switching from
    // a translated language back to English, whose candidate list is deliberately empty.
    pe::catalog().clear();
    std::string catalog = "none";
    std::size_t texts = 0;
    for (const std::string& candidate : pe::catalog_candidates(tag)) {
        std::string po;
        bool read = pe::read_file(Eden::AppResourceFile("ui/lang/" + candidate + ".po"), &po, 1u << 20);
        if (!read)
            read = pe::read_file(Eden::AppResourceFile("ui/lang/" + candidate + ".txt"), &po, 1u << 20);
        // Some PS5 package-image/ShadowMount paths preserve ui/lang but strip its text payloads.
        // French is our primary tested locale, so keep an embedded copy as a final in-binary
        // fallback. The external catalog stays authoritative whenever it is actually present.
        if (!read && candidate.rfind("fr", 0) == 0) {
            po.assign(pe::ui::embedded::kFrFr.data(), pe::ui::embedded::kFrFr.size());
            read = true;
            catalog = candidate + " (embedded)";
        }
        if (!read) continue;
        texts = pe::catalog().load(po);
        if (catalog == "none") catalog = candidate;
        break;
    }
    if (texts != 0 && !pe::catalog().every([&font](std::string_view text) { return font.can_draw(text); })) {
        pe::catalog().clear();
        catalog += " (not used: no font for it)";
        texts = 0;
    }
    if (tag.rfind("en", 0) != 0 && texts == 0) {
        Eden::Report("language", ("Requested launcher catalog unavailable: " + tag +
                                   " under " + Eden::AppFile("ui/lang")).c_str());
    }
    std::fprintf(stderr, "EDEN_LANGUAGE system=%d rc=0x%x tag=%s catalog=%s texts=%zu\n", system_language,
                 static_cast<unsigned>(rc), tag.c_str(), catalog.c_str(), texts);
    std::fprintf(stderr, "EDEN_FONTS folder=%s files=%zu read=%s\n", folder.c_str(), files,
                 font.system_fonts_read().c_str());
}

#ifdef EDEN_DEV_ROM_ID
// The frame as drawn, bottom row first: a 24-bit BMP for the development runner.
int SaveCapture(const std::string& path, int width, int height) {
    std::vector<unsigned char> pixels(static_cast<std::size_t>(width) * height * 4);
    glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
    const std::uint32_t row = (static_cast<std::uint32_t>(width) * 3 + 3) & ~3u;
    const std::uint32_t size = 54 + row * static_cast<std::uint32_t>(height);
    unsigned char header[54]{'B', 'M'};
    const auto put = [&](int at, std::uint32_t value) {
        for (int i = 0; i < 4; ++i) header[at + i] = static_cast<unsigned char>(value >> (8 * i));
    };
    put(2, size);
    put(10, 54);
    put(14, 40);
    put(18, static_cast<std::uint32_t>(width));
    put(22, static_cast<std::uint32_t>(height));
    header[26] = 1;
    header[28] = 24;
    put(34, size - 54);
    std::FILE* file = std::fopen(path.c_str(), "wb");
    if (!file) return -1;
    bool ok = std::fwrite(header, 1, sizeof(header), file) == sizeof(header);
    std::vector<unsigned char> line(row);
    for (int y = 0; ok && y < height; ++y) {
        const unsigned char* in = pixels.data() + static_cast<std::size_t>(y) * width * 4;
        for (int x = 0; x < width; ++x) {
            line[static_cast<std::size_t>(x) * 3 + 0] = in[x * 4 + 2];
            line[static_cast<std::size_t>(x) * 3 + 1] = in[x * 4 + 1];
            line[static_cast<std::size_t>(x) * 3 + 2] = in[x * 4 + 0];
        }
        ok = std::fwrite(line.data(), 1, line.size(), file) == line.size();
    }
    return std::fclose(file) == 0 && ok ? 0 : -1;
}
#endif

std::string RunApp(const std::string& launch_error, bool first_start, bool* restart_requested) {
    // A fresh/legacy config with no explicit game language follows the PS5 once. Once saved,
    // Settings > Language remains authoritative and is never overwritten by later system changes.
    if (first_start && !Eden::HasSavedLanguage()) {
        int system_language = -1;
        if (sceSystemServiceParamGetInt(ps5::i18n::kSystemLanguageParameter, &system_language) == 0) {
            const std::string_view tag = ps5::i18n::language_tag(system_language);
            const int language = Eden::LanguageIndexForLocale(tag);
            if (language >= 0) {
                Eden::Preferences preferences = Eden::LoadPreferences();
                preferences.language = language;
                if (Eden::SavePreferences(preferences))
                    Eden::Report("language", (std::string("Initial game language follows PS5: ") +
                                               std::string(tag)).c_str());
            }
        }
    }
    const auto opened = Clock::now();
    // What Settings > Video asks for, and what opened.
    int output = std::clamp(Eden::LoadPreferences().output, 0, static_cast<int>(std::size(Eden::kOutputKeys)) - 1);
    int output_open = output;
    pe::ps5::Display display;
    if (!OpenDisplay(display, &output_open)) {
        Eden::Report("menu video failure", pe::ps5::egl_error_name(display.last_error()));
        return {};
    }
    // Something on screen at once: the launcher's own dark, then the first real frame.
    glClearColor(0.024f, 0.035f, 0.039f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    display.swap();
    sceSystemServiceHideSplashScreen();

    std::string selected_game;
    {
        pe::gfx::GlBatch batch;
        pe::gfx::Font font;
        std::string font_data;
        const std::string font_path = Eden::AppFile("ui/fonts/montserrat-medium.pefont");
        const bool shaders_ready = batch.init();
        errno = 0;
        const bool font_read = shaders_ready && pe::read_file(font_path, &font_data);
        const int font_errno = errno;
        const bool ready = font_read && font.load(font_data);
        if (!ready) {
            const std::string why = !shaders_ready ?
                "The launcher's shaders could not be built" :
                !font_read ?
                    "The launcher's font could not be read: " + font_path +
                        (font_errno ? " (" + std::string{std::strerror(font_errno)} + ")" : "") :
                    "The launcher's font is invalid: " + font_path + " (" +
                        std::to_string(font_data.size()) + " bytes)";
            Eden::Report("menu failure", why.c_str());
            glClearColor(0.7f, 0.08f, 0.16f, 1.0f);
            glClear(GL_COLOR_BUFFER_BIT);
            display.swap();
            batch.release();
            display.close();
            return {};
        }
        LoadLanguage(font);
        std::uint32_t font_texture = batch.create_font_texture(font);
        const pe::ui::Fonts fonts{&font, font_texture};

        Eden::Report("setup", "Checking supplied keys and firmware");
        EdenServices services(launch_error);
        pe::ui::Textures textures(batch, services);
        if (!textures.load_art(Eden::AppFile("ui")))
            Eden::Report("menu", "Launcher art is incomplete; check the app's ui/art folder");
        textures.set_output_scale(static_cast<float>(display.width()) / 1920.0f);

        // Sound: its own thread feeds the console's audio port from the mixer.
        auto mixer = std::make_unique<pe::audio::Mixer>();
        pe::audio::SoundBank sounds;
        std::vector<std::string> sound_errors;
        const int sound_files = sounds.load(Eden::AppFile("ui/sounds"), &sound_errors);
        for (const auto& error : sound_errors) Eden::Report("menu sound", error.c_str());
        pe::ps5::AudioOut audio;
        const bool audio_ready = Eden::AudioOutReady() && audio.start(*mixer);
        if (!audio_ready) Eden::Report("menu sound", "Audio output is not available; the launcher stays silent");

        const bool input_ready = radio_input_init();
        if (!input_ready) Eden::Report("menu failure", "The controller could not be opened");
        pe::ui::Launcher launcher(services, textures, fonts, first_start);
        int menu_volume = launcher.menu_volume();
        mixer->set_bus_gain(pe::audio::Bus::ui, MenuGain(menu_volume));
        std::fprintf(stderr, "EDEN_LAUNCHER display=%dx%d sounds=%d audio=%d ready_ms=%lld\n", display.width(),
                     display.height(), sound_files, audio_ready, Milliseconds(Clock::now() - opened));

        bool running = input_ready;
#ifdef EDEN_DEV_ROM_ID
        static Eden::DevelopmentInput development_input;
        auto next_development_poll = Clock::now();
        // A capture waits for the screen to settle after the input that asked for it.
        int capture_wait = 60;
        std::fprintf(stderr, "EDEN_DEV_LAUNCHER_READY ready=%d\n", running);
#endif
        pe::gfx::DrawList list;
        pe::gfx::Viewport viewport = pe::gfx::fit_viewport(display.width(), display.height());
        auto previous = Clock::now();
        bool first_frame = true;
#ifdef EDEN_DEV_ROM_ID
        // Five-second aggregate only; no text formatting or filesystem I/O
        // inside a normal menu frame. Distinguish delayed animation from
        // real input/update, GL draw and swap/presentation frame stalls.
        auto ui_sample_begin = previous;
        unsigned ui_frames = 0, ui_late_20 = 0, ui_late_33 = 0, ui_late_50 = 0;
        long long ui_max_update_us = 0, ui_max_draw_us = 0, ui_max_present_us = 0;
#endif
        Eden::LaunchHandoff::Clear();
        bool handoff_captured = false;
        while (running && !launcher.done() && !launcher.restart_requested()) {
            const auto frame_start = Clock::now();
            // Start-to-start frame time; a long frame does not make the animations jump.
            const float dt = first_frame ? 1.0f / 60.0f :
                std::min(0.05f, std::chrono::duration<float>(frame_start - previous).count());
            previous = frame_start;
            first_frame = false;

#ifdef EDEN_DEV_ROM_ID
            const auto now = static_cast<std::uint64_t>(Milliseconds(frame_start.time_since_epoch()));
            // Manual DualSense use needs at most one synchronous filesystem
            // command sweep per real second. Script replay gets ~6Hz even
            // when menu FPS falls: a frame-count timer would become slower
            // precisely while diagnosing a stuttering launcher. Do not catch
            // up missed polls in a burst after a slow EGL swap.
            if (frame_start >= next_development_poll) {
                next_development_poll = frame_start +
                    (development_input.active ? std::chrono::milliseconds(160)
                                              : std::chrono::seconds(1));
                std::ifstream command(Eden::AppFile("compat-input.txt"));
                if (development_input.Read(command, now)) {
                    capture_wait = 60;
                    std::fprintf(stderr, "EDEN_DEV_UI_INPUT sequence=%llu buttons=%x\n",
                        static_cast<unsigned long long>(development_input.sequence), development_input.buttons);
                }
                // The runner's quit request: leave the launcher and end the process normally, so a run
                // ends without killing the app (two console losses followed killed runs).
                if (std::remove(Eden::AppFile("quit-app.txt").c_str()) == 0) {
                    std::fprintf(stderr, "EDEN_DEV_QUIT requested=1\n");
                    running = false;
                }
                // The runner's crash request, to test the crash report in the launcher.
                Eden::Crash::DevelopmentRequest(Eden::AppFile("crash-app.txt"));
            }
            if (!development_input.active) radio_input_poll();
            if (const auto sample = development_input.Sample(now)) {
                static_assert(sizeof(*sample) == 120);
                radio_input_development_sample(&*sample);
            }
#else
            radio_input_poll();
#endif
            radio_input_event_t input{};
            while (radio_input_next(&input)) {
                if (!input.pressed) continue;
                // A slow handler names itself in the log (opening the Library reads every game).
                const auto pressed_at = Clock::now();
                launcher.press(static_cast<pe::ui::Key>(input.key));
                const auto ms = Milliseconds(Clock::now() - pressed_at);
                if (ms >= 50)
                    Eden::Report("slow input", ("key " + std::to_string(static_cast<int>(input.key)) + ": " +
                                                std::to_string(ms) + " ms").c_str());
            }
            launcher.update(dt);
            if (launcher.output() != output) {
                // Output resolution changed in Settings > Video: the display opens again at the new
                // size, and with it everything that lives in its GL context. The launcher stays as
                // it is, on the row that was changed.
                const auto reopen = Clock::now();
                output = output_open = std::clamp(launcher.output(), 0, static_cast<int>(std::size(Eden::kOutputKeys)) - 1);
                textures.release();
                batch.delete_texture(font_texture);
                font_texture = 0;
                batch.release();
                display.close();
                if (!OpenDisplay(display, &output_open) || !batch.init()) {
                    Eden::Report("menu video failure", pe::ps5::egl_error_name(display.last_error()));
                    break;
                }
                font_texture = batch.create_font_texture(font);
                launcher.set_font_texture(font_texture);
                if (!textures.load_art(Eden::AppFile("ui")))
                    Eden::Report("menu", "Launcher art is incomplete; check the app's ui/art folder");
                textures.set_output_scale(static_cast<float>(display.width()) / 1920.0f);
                viewport = pe::gfx::fit_viewport(display.width(), display.height());
                std::fprintf(stderr, "EDEN_LAUNCHER display=%dx%d reopened_ms=%lld\n", display.width(),
                             display.height(), Milliseconds(Clock::now() - reopen));
            }
            for (const pe::audio::Cue cue : launcher.take_cues()) sounds.play(*mixer, cue);
            if (launcher.menu_volume() != menu_volume) {
                menu_volume = launcher.menu_volume();
                mixer->set_bus_gain(pe::audio::Bus::ui, MenuGain(menu_volume));
            }
            const auto updated = Clock::now();

            list.clear();
            launcher.draw(list);
            batch.sync_font_texture(font_texture, font);
            glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
            glClear(GL_COLOR_BUFFER_BIT);
            batch.draw(list, viewport, display.width(), display.height());
            // Preserve the ACTUAL jacket/hero/title composition before EGL
            // is destroyed and Vulkan takes over. Capture the final complete
            // case frame once, without any black-fade interstitial. Vulkan
            // reuses this exact scene until the first guest frame.
            if (!handoff_captured && launcher.done() &&
                !launcher.selected_game().empty()) {
                    // The final launcher frame remains fully visible, with
                    // the 3D case settled and NO black outro. Capture this
                    // exact presentation instead of an earlier spin angle.
                    handoff_captured = true;
                    const int width = display.width();
                    const int height = display.height();
                    if (width > 0 && height > 0 && width <= 4096 && height <= 2160) {
                        try {
                            Eden::LaunchHandoff::Frame snapshot;
                            snapshot.width = static_cast<std::uint32_t>(width);
                            snapshot.height = static_cast<std::uint32_t>(height);
                            const std::size_t row_bytes =
                                static_cast<std::size_t>(width) * 4;
                            snapshot.rgba.resize(row_bytes * static_cast<std::size_t>(height));
                            glPixelStorei(GL_PACK_ALIGNMENT, 1);
                            glReadPixels(0, 0, width, height, GL_RGBA,
                                         GL_UNSIGNED_BYTE, snapshot.rgba.data());
                            const GLenum error = glGetError();
                            glPixelStorei(GL_PACK_ALIGNMENT, 4);
                            if (error == GL_NO_ERROR) {
                                // GL readback starts at the lower left; Vulkan
                                // buffer copies expect image rows from the top.
                                std::vector<std::uint8_t> row(row_bytes);
                                for (int y = 0; y < height / 2; ++y) {
                                    auto* top = snapshot.rgba.data() +
                                        static_cast<std::size_t>(y) * row_bytes;
                                    auto* bottom = snapshot.rgba.data() +
                                        static_cast<std::size_t>(height - y - 1) * row_bytes;
                                    std::memcpy(row.data(), top, row_bytes);
                                    std::memcpy(top, bottom, row_bytes);
                                    std::memcpy(bottom, row.data(), row_bytes);
                                }
                                Eden::LaunchHandoff::Publish(std::move(snapshot));
                                std::fprintf(stderr,
                                    "EDEN_LOADER_JACKET_HANDOFF_CAPTURE size=%dx%d ready=1\n",
                                    width, height);
                            } else {
                                std::fprintf(stderr,
                                    "EDEN_LOADER_JACKET_HANDOFF_CAPTURE ready=0 gl_error=%x\n",
                                    static_cast<unsigned>(error));
                            }
                        } catch (const std::bad_alloc&) {
                            std::fprintf(stderr,
                                "EDEN_LOADER_JACKET_HANDOFF_CAPTURE ready=0 memory=insufficient\n");
                        }
                    }
            }
            const auto drawn = Clock::now();
            bool captured = false;
#ifdef EDEN_DEV_ROM_ID
            if (capture_wait > 0 && --capture_wait == 0 && std::ifstream(Eden::AppFile("ui-capture.txt")).good()) {
                const int rc = SaveCapture(Eden::LogFile("launcher.bmp"), display.width(), display.height());
                std::fprintf(stderr, "EDEN_DEV_UI_CAPTURE rc=%d\n", rc);
                captured = true; // saving the picture is slow, the frame is not
            }
#endif
            if (!display.swap()) {
                Eden::Report("menu video failure", pe::ps5::egl_error_name(display.last_error()));
                running = false;
            }
            {
                // A slow launcher frame names its stage in the log, at most once a second.
                const auto done = Clock::now();
                static auto last_report = done - std::chrono::seconds(2);
                if (!captured && done - frame_start >= std::chrono::milliseconds(100) &&
                    done - last_report >= std::chrono::seconds(1)) {
                    last_report = done;
                    const std::string detail = "update " + std::to_string(Milliseconds(updated - frame_start)) +
                        " ms, draw " + std::to_string(Milliseconds(drawn - updated)) +
                        " ms, present " + std::to_string(Milliseconds(done - drawn)) + " ms";
                    Eden::Report("slow frame", detail.c_str());
                }
#ifdef EDEN_DEV_ROM_ID
                if (!captured) {
                    const long long update_us = std::chrono::duration_cast<std::chrono::microseconds>(
                        updated - frame_start).count();
                    const long long draw_us = std::chrono::duration_cast<std::chrono::microseconds>(
                        drawn - updated).count();
                    const long long present_us = std::chrono::duration_cast<std::chrono::microseconds>(
                        done - drawn).count();
                    const long long whole_us = std::chrono::duration_cast<std::chrono::microseconds>(
                        done - frame_start).count();
                    ++ui_frames;
                    ui_late_20 += whole_us >= 20000;
                    ui_late_33 += whole_us >= 33000;
                    ui_late_50 += whole_us >= 50000;
                    ui_max_update_us = std::max(ui_max_update_us, update_us);
                    ui_max_draw_us = std::max(ui_max_draw_us, draw_us);
                    ui_max_present_us = std::max(ui_max_present_us, present_us);
                }
                if (done - ui_sample_begin >= std::chrono::seconds(5)) {
                    std::fprintf(stderr,
                        "EDEN_UI_FRAMES frames=%u elapsed_ms=%lld late_20=%u late_33=%u late_50=%u "
                        "max_update_us=%lld max_draw_us=%lld max_present_us=%lld\n",
                        ui_frames, Milliseconds(done - ui_sample_begin),
                        ui_late_20, ui_late_33, ui_late_50,
                        ui_max_update_us, ui_max_draw_us, ui_max_present_us);
                    ui_sample_begin = done;
                    ui_frames = ui_late_20 = ui_late_33 = ui_late_50 = 0;
                    ui_max_update_us = ui_max_draw_us = ui_max_present_us = 0;
                }
#endif
            }
        }

        if (restart_requested != nullptr)
            *restart_requested = launcher.restart_requested();
        selected_game = launcher.selected_game();
        if (!launcher.done()) selected_game.clear();
        // Let the last sound end (the screen is already dark), then give everything back.
        for (int wait = 0; audio_ready && wait < 60 && mixer->active_voices() > 0; ++wait) sceKernelUsleep(10000);
        audio.stop();
        if (input_ready) radio_input_shutdown();
        textures.release();
        batch.delete_texture(font_texture);
        batch.release();
    }
    display.close();
    std::fprintf(stderr, "EDEN_LAUNCHER closed game=%d\n", !selected_game.empty());
    return selected_game;
}

} // namespace

std::string SelectProsperoEdenGame(const std::string& launch_error) {
    // The first time is the app opening; afterwards the launcher returns from a game. A language
    // change rebuilds only the launcher in this same call so translated text/font caches refresh.
    static bool first_start = true;
    bool opening = std::exchange(first_start, false);
    for (;;) {
        bool restart = false;
        std::string selected = RunApp(launch_error, opening, &restart);
        opening = false;
        if (!restart)
            return selected;
        std::fprintf(stderr, "EDEN_LANGUAGE launcher-restart=1\n");
    }
}
