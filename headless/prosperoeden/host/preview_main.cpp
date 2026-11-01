// ProsperoEden - Launcher preview on a PC: draws the real screens to PNG files.
// Copyright (C) 2026 BlackBearReloaded
// SPDX-License-Identifier: GPL-3.0-or-later
//
// usage: pe_preview <ui assets dir> <output dir> [width height]
//        pe_preview <ui assets dir> <output dir> --tour [width height]   (raw RGBA frames on stdout)
// Renders with the launcher's own draw list, shaders and font through Mesa's
// surfaceless EGL (llvmpipe), with sample data in place of the console.

#include "fake_services.hpp"
#include "pe/core/file.hpp"
#include "pe/gfx/gl_batch.hpp"
#include "pe/gfx/gl_program.hpp"
#include "pe/gfx/system_fonts.hpp"
#include "pe/ui/launcher.hpp"

#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glcorearb.h>

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

#include <algorithm>
#include <chrono>
#include <thread>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <map>
#include <memory>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace
{

using pe::ui::Key;

bool open_context()
{
    auto get_platform_display = reinterpret_cast<PFNEGLGETPLATFORMDISPLAYEXTPROC>(
        eglGetProcAddress("eglGetPlatformDisplayEXT"));
    EGLDisplay display =
        get_platform_display != nullptr ?
            get_platform_display(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, nullptr) :
            eglGetDisplay(EGL_DEFAULT_DISPLAY);
    EGLint major = 0;
    EGLint minor = 0;
    if (display == EGL_NO_DISPLAY || !eglInitialize(display, &major, &minor) ||
        !eglBindAPI(EGL_OPENGL_API))
        return false;
    const EGLint attributes[] = {EGL_CONTEXT_MAJOR_VERSION, 4, EGL_CONTEXT_MINOR_VERSION, 5,
                                 EGL_CONTEXT_OPENGL_PROFILE_MASK,
                                 EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT, EGL_NONE};
    EGLContext context = eglCreateContext(display, EGL_NO_CONFIG_KHR, EGL_NO_CONTEXT, attributes);
    return context != EGL_NO_CONTEXT &&
           eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, context);
}

struct Stage
{
    pe::host::FakeServices &services;
    pe::ui::Textures &textures;
    pe::ui::Fonts fonts;
    pe::gfx::GlBatch &batch;
    int width;
    int height;
    std::string output;
    std::unique_ptr<pe::ui::Launcher> launcher;
    pe::gfx::DrawList list;
    std::vector<unsigned char> pixels;
    bool tour = false;
    bool ok = true;
    std::vector<pe::audio::Cue> heard;

    void restart(bool first_start = false)
    {
        launcher = std::make_unique<pe::ui::Launcher>(services, textures, fonts, first_start);
    }
    void frame()
    {
        launcher->update(1.0f / 60.0f);
        for (pe::audio::Cue cue : launcher->take_cues())
            heard.push_back(cue);
        if (tour)
            emit();
    }
    void wait(float seconds)
    {
        for (int i = 0; i < static_cast<int>(seconds * 60.0f + 0.5f); ++i)
            frame();
    }
    void press(std::initializer_list<Key> keys, float pause = 0.0f)
    {
        for (Key key : keys)
        {
            launcher->press(key);
            frame();
            if (pause > 0.0f)
                wait(pause);
        }
    }
    void render()
    {
        list.clear();
        launcher->draw(list);
        batch.sync_font_texture(fonts.texture, *fonts.font);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        batch.draw(list, pe::gfx::fit_viewport(width, height), width, height);
        glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
    }
    // One frame of the tour, top row first, to stdout.
    void emit()
    {
        render();
        const std::size_t stride = static_cast<std::size_t>(width) * 4;
        for (int y = height - 1; y >= 0; --y)
            std::fwrite(pixels.data() + static_cast<std::size_t>(y) * stride, 1, stride, stdout);
    }
    void shoot(const char *name)
    {
        if (tour)
            return;
        render();
        const std::string path = output + "/" + name + ".png";
        const bool written =
            stbi_write_png(path.c_str(), width, height, 4, pixels.data(), width * 4) != 0;
        std::fprintf(stderr, "%s: %zu instances, %zu draw calls, GL error 0x%x%s\n", name,
                     list.instances().size(), batch.last_draw_calls(), glGetError(),
                     written ? "" : " (not written)");
        ok = ok && written;
    }
};

void pictures(Stage &s)
{
    if (const char* mode = std::getenv("PE_PREVIEW_SWITCH_THEME");
        mode != nullptr && std::strcmp(mode, "1") == 0) {
        s.restart(false);
        s.wait(1.5f);
        s.shoot("00-switch-home");
        // The HOME top row no longer wraps: move right to the final
        // All Software item (six recent game slots at most).
        s.press({Key::right, Key::right, Key::right, Key::right,
                 Key::right, Key::right, Key::cross});
        s.wait(1.5f);
        s.shoot("01-switch-all-software");
        s.press({Key::circle});
        s.wait(0.5f);
        // Six bottom icons: About, Files, Multiplayer, Controllers, Settings, Exit.
        s.press({Key::down, Key::right, Key::right, Key::right, Key::right, Key::cross});
        s.wait(0.5f);
        s.shoot("02-switch-settings");
        s.press({Key::down, Key::down, Key::down, Key::down, Key::cross});
        s.wait(0.3f);
        s.shoot("03-switch-appearance");
        s.press({Key::circle, Key::down, Key::down, Key::cross});
        s.wait(0.3f);
        s.shoot("04-switch-storage");
        s.press({Key::circle, Key::down, Key::cross});
        s.wait(0.3f);
        s.shoot("05-switch-language");
        // Verify the alternative theme's native confirmation overlay.
        s.press({Key::circle, Key::circle, Key::down,
                 Key::right, Key::right, Key::right, Key::right, Key::right,
                 Key::cross});
        s.wait(0.3f);
        s.shoot("06-switch-exit-confirm");
        s.press({Key::circle, Key::up, Key::cross});
        s.wait(1.0f);
        // Triangle opens the real game's per-title settings.
        s.press({Key::triangle});
        s.wait(0.3f);
        s.shoot("07-switch-game-options");
        // The tenth Down reaches Mods while the options list scrolls.
        s.press({Key::down,Key::down,Key::down,Key::down,Key::down,
                 Key::down,Key::down,Key::down,Key::down,Key::down,
                 Key::cross});
        s.wait(0.3f);
        s.shoot("08-switch-game-mods");
        // Return from mods to game options, then Library and HOME.
        // Use the same Controllers shortcut as the user.
        s.press({Key::circle,Key::circle,Key::circle,Key::down,
                 Key::right,Key::right,Key::right,Key::cross});
        s.wait(0.3f);
        s.shoot("09-switch-button-mapping");
        // Back from a HOME-launched controller editor must close to HOME.
        // Then select a title which has three sample mods, including an
        // initially disabled one. Exercise its REAL save action.
        s.press({Key::circle,Key::up,Key::cross});
        s.wait(0.5f);
        s.press({Key::right,Key::right,Key::triangle});
        s.wait(0.3f);
        s.press({Key::down,Key::down,Key::down,Key::down,Key::down,
                 Key::down,Key::down,Key::down,Key::down,Key::down,
                 Key::cross});
        s.wait(0.3f);
        s.shoot("10-switch-mods-installed");
        s.press({Key::down,Key::cross});
        s.wait(0.2f);
        s.shoot("11-switch-mod-enabled");
        const auto game_list=s.services.games();
        const auto game=std::find_if(game_list.begin(),game_list.end(),
            [](const pe::ui::Game& candidate){
                return candidate.name=="Echoes of the Valley";
            });
        if(game==game_list.end() ||
           s.services.mods(game->title_id).size()!=3 ||
           !s.services.mods(game->title_id)[1].enabled) {
            std::fprintf(stderr,"Switch mods preview: toggle not saved to fixture backend\\n");
            s.ok=false;
        }
        return;
    }
    // Independently verify the game's real launch transition using the same
    // original C++ draw list, EGL context and shader backend as Home. This
    // takes *screenshots*, not image synthesis or a mock-up of the layout.
    // Real C++/OpenGL Library visual evidence WITHOUT either retail face.
    // Uses the same selected title and layout as the original-scan preview.
    // This exercises the fixed corner logo, reconstructed rear footer and
    // uniform-size shelf jackets, rather than only testing the 3D launch.
    if (const char* missing = std::getenv("PE_PREVIEW_LIBRARY_FALLBACK");
        missing != nullptr && std::strcmp(missing, "1") == 0)
    {
        s.restart(false);
        s.wait(2.0f);
        s.press({Key::up, Key::cross});
        s.wait(1.0f);
        // R1 switches the main tab, not the Library page. Select the
        // eleventh fixture with the same D-pad path as the retail-scan test;
        // otherwise the fallback screenshots can capture another screen.
        s.press({Key::right, Key::right, Key::right, Key::right, Key::right,
                 Key::right, Key::right, Key::right, Key::right, Key::right});
        s.wait(0.4f);
        const auto sample = s.services.games();
        const auto case_scan = s.services.box_art(sample.at(10).title_id);
        if (!case_scan.front.empty() || !case_scan.back.empty()) {
            std::fprintf(stderr,
                         "library-fallback-preview: original scan unexpectedly enabled\\n");
            s.ok = false;
            return;
        }
        // Do not capture the first asynchronous frame, when Nlib imagery may
        // still be in the CPU decode queue. No UI repaint or alternate renderer.
        for (int attempt = 0; attempt < 48; ++attempt) {
            s.render();
            std::this_thread::sleep_for(std::chrono::milliseconds(45));
            s.launcher->update(1.0f / 60.0f);
        }
        s.shoot("00-library-fallback-front");
        s.press({Key::down});
        s.wait(0.22f);
        s.shoot("01-library-fallback-back");
        s.press({Key::cross});
        s.wait(0.32f);
        s.shoot("02-library-fallback-zoom");
        return;
    }
    if (const char* library_only = std::getenv("PE_PREVIEW_LIBRARY_ONLY");
        library_only != nullptr && std::strcmp(library_only, "1") == 0)
    {
        s.restart(false);
        s.wait(2.0f);
        s.press({Key::up, Key::cross});
        s.wait(1.0f);
        // Fixture games are alphabetically sorted. BOTW's real flat scans
        // are on the eleventh title (index 10), not on Moss & Lantern.
        // L1/R1 now change main tabs globally. The old R1 page shortcut
        // would leave Library before this L2/R2 viewer test. Navigate ten
        // items with ordinary D-pad Right to reach the SAME BOTW fixture.
        s.press({Key::right, Key::right, Key::right, Key::right, Key::right,
                 Key::right, Key::right, Key::right, Key::right, Key::right});
        s.wait(0.4f);
        // The host advances game-list frames far faster than the console.
        // Wait for the actual original retail textures AND their fade-in
        // before taking evidence. Do not capture an empty placeholder as
        // though it were a successful rendering.
        const auto sample_games = s.services.games();
        const auto retail = s.services.box_art(sample_games.at(10).title_id);
        bool shelf_ready = false;
        for (int attempt = 0; attempt < 75; ++attempt) {
            s.render();
            std::this_thread::sleep_for(std::chrono::milliseconds(45));
            s.launcher->update(1.0f / 60.0f);
            const auto front = s.textures.cover(retail.front, 181.0f);
            const auto back = s.textures.cover(retail.back, 181.0f);
            if (front.texture && back.texture &&
                front.age > 0.24f && back.age > 0.24f) {
                shelf_ready = true;
                break;
            }
        }
        if (!shelf_ready) {
            std::fprintf(stderr, "library-preview: real front/back scan never became visible\n");
            s.ok = false;
            return;
        }
        s.shoot("00-library-front-shelf");
        s.press({Key::down});
        s.wait(0.15f);
        s.shoot("01-library-back-focus");
        s.press({Key::cross});
        s.wait(0.20f);
        bool zoom_ready = false;
        for (int attempt = 0; attempt < 75; ++attempt) {
            s.render();
            std::this_thread::sleep_for(std::chrono::milliseconds(45));
            s.launcher->update(1.0f / 60.0f);
            const auto full = s.textures.cover(retail.back, 670.0f);
            if (full.texture && full.age > 0.24f) {
                zoom_ready = true;
                break;
            }
        }
        if (!zoom_ready) {
            std::fprintf(stderr, "library-preview: full-resolution rear scan never became visible\n");
            s.ok = false;
            return;
        }
        s.shoot("02-library-back-zoom");
        // Regression evidence: shoulders must zoom the REAL high-res back
        // insert, while D-pad moves the magnified view (not selected game).
        s.press({Key::r2, Key::r2, Key::down, Key::right});
        s.wait(0.42f);
        s.shoot("03-library-back-zoom-pan");
        s.press({Key::l2});
        s.wait(0.30f);
        s.shoot("04-library-back-zoom-out");
        // Cross no longer closes the viewer or launches the title.
        s.press({Key::cross});
        s.wait(0.12f);
        s.shoot("05-library-back-cross-ignored");
        s.press({Key::circle});
        s.wait(0.16f);
        s.shoot("06-library-back-closed");
        return;
    }
    if (const char* launch_only = std::getenv("PE_PREVIEW_LAUNCH_ONLY");
        launch_only != nullptr && std::strcmp(launch_only, "1") == 0)
    {
        s.restart(false);
        s.wait(2.0f); // settle UI transitions in virtual frame time
        // The Home snapshot is assembled asynchronously on a REAL host
        // thread. Virtual 120-frame waits can complete in milliseconds,
        // before the worker finishes; one Cross would be discarded.
        // Pump the launcher and give the worker bounded real time to
        // complete. Never fake selected_game() or bypass the Cross handler.
        bool launched = false;
        for (int attempt = 0; attempt < 30; ++attempt) {
            s.launcher->update(0.0f);
            // Initial Home focuses Continue. Only its actual Cross action
            // may enter the title's normal launch path.
            s.press({Key::cross});
            if (!s.launcher->selected_game().empty()) {
                launched = true;
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
        if (!launched) {
            std::fprintf(stderr,
                         "launch-preview: real Cross never launched after waiting for the Home snapshot\n");
            s.ok = false;
            return;
        }
        // This host program advances 60 virtual frames almost instantly.
        // The actual launcher renders/pumps in real time, so let the async
        // texture workers finish before taking evidence. Zero-delta updates
        // complete queued uploads without advancing the game's transition.
        for (int attempt = 0; attempt < 8; ++attempt) {
            s.render();
            std::this_thread::sleep_for(std::chrono::milliseconds(55));
            s.launcher->update(0.0f);
        }
        s.wait(1.02f); // hold initial cover before the 3D turn
        s.shoot("00-launch-case-front");
        s.wait(0.51f); // instantaneous ~90-degree spine glimpse, no dwell
        s.shoot("01-launch-case-spine");
        s.wait(1.57f); // back well inside its 4.5-second readable hold
        s.shoot("02-launch-case-back");
        return;
    }

    // Home, as it settles after the app opens.
    s.restart(true);
    s.wait(0.42f);
    s.shoot("00-arriving");
    s.wait(3.0f);
    // Host-only screenshot gate. The simulated 60 Hz ticks advance much
    // faster than wall time, so asynchronous cover uploads may still be
    // pending when the Home image is written. Require all seven GL textures.
    if (const char *branded = std::getenv("PE_PREVIEW_BRANDED_HOME");
        branded != nullptr && std::strcmp(branded, "1") == 0) {
        const auto recents = s.services.home().recents;
        const std::size_t count = std::min<std::size_t>(7, recents.size());
        std::size_t ready = 0;
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(20);
        do {
            ready = 0;
            for (std::size_t i = 0; i < count; ++i)
                if (!recents[i].cover.empty() &&
                    s.textures.cover(recents[i].cover, 214.0f).texture != 0)
                    ++ready;
            if (ready == 7 && count == 7) break;
            s.frame(); // normal upload/decoder pump, never a rendering bypass
            std::this_thread::sleep_for(std::chrono::milliseconds(30));
        } while (std::chrono::steady_clock::now() < deadline);
        std::fprintf(stderr, "ENCORE_PREVIEW_CARD_ART_READY: %zu/%zu\n", ready, count);
        if (ready != 7 || count != 7) {
            std::fprintf(stderr, "README preview: missing illustrated game tiles\n");
            s.ok = false;
        }
        s.wait(0.5f); // finish tile opacity transitions
    }
    s.shoot("01-home");
    s.press({Key::right});
    s.wait(0.6f);
    s.shoot("02-home-details-focus");
    s.press({Key::down, Key::right});
    s.wait(0.6f);
    s.shoot("03-home-recent-focus");
    s.press({Key::up, Key::up, Key::right});
    s.wait(0.6f);
    s.shoot("04-home-settings-focus");
    // Mini production renderer: real launcher C++/GL pipeline, Home-only output.
    // Run by the lightweight GitHub preview job (not a full PS5 emulator build).
    if (const char* home_only = std::getenv("PE_PREVIEW_HOME_ONLY");
        home_only != nullptr && std::strcmp(home_only, "1") == 0)
        return;

    // Library.
    s.restart();
    s.wait(1.0f);
    s.press({Key::up, Key::cross});
    s.wait(0.14f);
    s.shoot("05-opening-library");
    s.wait(1.2f);
    s.shoot("06-library");
    s.press({Key::down, Key::down, Key::down, Key::down, Key::down, Key::down, Key::down,
             Key::down, Key::down});
    s.wait(0.8f);
    s.shoot("07-library-scrolled");
    s.press({Key::right});
    s.wait(0.6f);
    s.shoot("08-library-handheld");
    // The Library's Mods switch: all of this game's mods off, and on again.
    s.press({Key::square});
    s.wait(0.6f);
    s.shoot("44-library-mods-off");
    s.press({Key::square});
    s.wait(0.6f);
    s.shoot("45-library-mods-on");
    s.press({Key::triangle});
    s.wait(0.8f);
    s.shoot("09-game-settings");
    s.press({Key::down, Key::right});
    s.wait(0.6f);
    s.shoot("10-game-settings-changed");
    // The output's refresh rate for this game.
    s.press({Key::down, Key::down, Key::down, Key::right, Key::right});
    s.wait(0.6f);
    s.shoot("40-game-refresh");
    // The game's mods: the row, the list, one switched on, and a game that has none.
    s.press({Key::down});
    s.wait(0.6f);
    s.shoot("35-game-mods-row");
    s.press({Key::cross});
    s.wait(0.6f);
    s.shoot("36-mods");
    s.press({Key::down, Key::cross});
    s.wait(0.4f);
    s.shoot("37-mods-switched");
    s.services.has_mods = false;
    s.press({Key::circle, Key::cross});
    s.wait(0.6f);
    s.shoot("38-mods-none");
    s.press({Key::square});
    s.wait(0.4f);
    s.shoot("39-mods-folder-made");
    s.services.has_mods = true;
    s.press({Key::circle, Key::down});
    s.wait(0.6f);
    s.shoot("32-game-save-data");
    s.press({Key::cross});
    s.wait(0.4f);
    s.shoot("33-game-save-asked");
    s.press({Key::square});
    s.wait(0.4f);
    s.shoot("34-game-save-exported");
    s.press({Key::circle});
    s.wait(0.3f);
    s.press({Key::cross});
    s.wait(0.30f);
    s.shoot("11-launching");
    s.wait(0.32f);
    s.shoot("12-launching-late");

    // Settings and its dialogs.
    s.restart();
    s.wait(1.0f);
    s.press({Key::up, Key::right, Key::cross});
    s.wait(1.0f);
    s.shoot("13-settings");
    s.press({Key::cross});
    s.wait(0.8f);
    s.shoot("14-video");
    s.press({Key::down, Key::right});
    s.wait(0.6f);
    s.shoot("15-video-saved");
    s.press({Key::down, Key::down, Key::down, Key::right});
    s.wait(0.6f);
    s.shoot("41-video-refresh");
    // The sixth row: the list scrolls to it.
    s.press({Key::down});
    s.wait(0.6f);
    s.shoot("43-video-overlay");
    s.press({Key::circle, Key::down, Key::cross});
    s.wait(0.8f);
    s.shoot("16-audio");
    s.press({Key::circle, Key::down, Key::cross});
    s.wait(0.8f);
    s.shoot("17-controls");
    s.press({Key::circle, Key::down, Key::cross});
    s.wait(0.8f);
    s.shoot("30-accessibility");
    s.press({Key::down, Key::down});
    s.wait(0.6f);
    s.shoot("31-accessibility-motion");
    s.press({Key::circle, Key::down, Key::cross});
    s.wait(0.8f);
    s.shoot("18-diagnostics");
    s.press({Key::circle, Key::down, Key::cross});
    s.wait(1.0f);
    s.shoot("19-game-files");
    s.press({Key::down, Key::down, Key::triangle});
    s.wait(0.6f);
    s.shoot("20-game-files-saved");
    s.press({Key::circle});
    s.wait(0.5f);
    s.press({Key::down, Key::cross});
    s.wait(1.0f);
    s.shoot("21-language");
    s.press({Key::down, Key::down, Key::down, Key::down, Key::down, Key::down, Key::down,
             Key::down, Key::down, Key::cross});
    s.wait(0.8f);
    s.shoot("22-language-chosen");

    // About.
    s.restart();
    s.wait(1.0f);
    s.press({Key::up, Key::right, Key::right, Key::cross});
    s.wait(1.0f);
    s.shoot("23-about");

    // What the home screen says when something is wrong, and before any game was played.
    s.services.setup_ready = false;
    s.restart();
    s.wait(2.0f);
    s.shoot("24-home-setup-required");
    s.services.setup_ready = true;
    s.services.launch_error = "The game's keys are missing from prod.keys.";
    s.restart();
    s.wait(2.0f);
    s.shoot("25-home-launch-failed");
    s.services.launch_error.clear();
    s.services.crash_report = "/data/prosperoeden/logs/crash-20261001-213000.txt";
    s.restart();
    s.wait(2.0f);
    s.shoot("25b-home-crash-report");
    s.services.crash_report.clear();
    s.services.has_history = false;
    s.restart();
    s.wait(2.0f);
    s.shoot("26-home-first-run");
    s.services.has_history = true;

    // Controllers: one, then a third one joining (caught mid-bounce), then all four.
    s.services.connected_controllers = 0b0001;
    s.restart();
    s.wait(2.0f);
    s.shoot("27-home-one-controller");
    s.services.connected_controllers = 0b0101;
    s.wait(0.2f);
    s.shoot("28-home-controller-joining");
    s.services.connected_controllers = 0b1111;
    s.wait(2.0f);
    s.shoot("29-home-four-controllers");
    s.services.connected_controllers = 0b0011;
}

// A walk through the launcher, one frame per call of frame().
void tour(Stage &s)
{
    s.services.connected_controllers = 0b0001;
    s.restart(true);
    s.wait(2.0f);
    // A second controller is switched on, then a third.
    s.services.connected_controllers = 0b0011;
    s.wait(1.2f);
    s.services.connected_controllers = 0b0111;
    s.wait(1.4f);
    s.press({Key::right, Key::left, Key::down, Key::right, Key::right, Key::left, Key::up}, 0.32f);
    s.wait(0.5f);
    s.press({Key::up}, 0.4f);
    s.press({Key::cross});
    s.wait(1.0f);
    s.press({Key::down, Key::down, Key::down, Key::down, Key::down, Key::down, Key::down,
             Key::down, Key::up, Key::up},
            0.22f);
    s.press({Key::right}, 0.6f);
    s.press({Key::triangle}, 0.8f);
    s.press({Key::down, Key::right, Key::down, Key::right}, 0.4f);
    s.press({Key::circle}, 0.6f);
    s.press({Key::circle}, 0.8f);
    s.press({Key::right}, 0.3f);
    s.press({Key::cross});
    s.wait(0.9f);
    s.press({Key::down, Key::down, Key::up}, 0.3f);
    s.press({Key::cross}, 0.8f);
    s.press({Key::right, Key::down, Key::left}, 0.4f);
    s.press({Key::circle}, 0.6f);
    s.press({Key::circle}, 0.9f);
    s.press({Key::down}, 0.5f);
    s.press({Key::cross});
    s.wait(1.2f);
}

} // namespace

namespace
{

// Text that did not fit its place at full size, and how it was fitted (the smallest scale seen).
std::map<std::string, std::pair<float, bool>> fits;

void note_fit(std::string_view text, float scale, bool cut)
{
    auto [entry, added] = fits.try_emplace(std::string{text}, scale, cut);
    if (!added)
    {
        entry->second.first = std::min(entry->second.first, scale);
        entry->second.second = entry->second.second || cut;
    }
}

// The catalog reader, the pattern filler and the choice of catalog, checked before anything is drawn.
bool strings_check()
{
    pe::Catalog catalog;
    const std::size_t count = catalog.load("\xef\xbb\xbf# comment\n"
                                           "msgid \"\"\nmsgstr \"Language: xx\\n\"\n\n"
                                           "#. note\n#: file.cpp\n"
                                           "msgid \"Back\"\r\nmsgstr \"Voltar\"\r\n\n"
                                           "msgid \"Say \\\"{0}\\\" twice\"\n"
                                           "msgstr \"\"\n\"Diga \\\"{0}\\\" \"\n\"duas vezes\"\n\n"
                                           "msgid \"Untranslated\"\nmsgstr \"\"\n");
    const auto same = [](const std::vector<std::string> &left, std::initializer_list<const char *> right)
    { return std::equal(left.begin(), left.end(), right.begin(), right.end(),
                        [](const std::string &a, const char *b) { return a == b; }); };
    const bool ok =
        count == 2 && catalog.find("Back") == "Voltar" &&
        catalog.find("Say \"{0}\" twice") == "Diga \"{0}\" duas vezes" &&
        catalog.find("Untranslated") == "Untranslated" && catalog.find("Missing") == "Missing" &&
        pe::fill("{0} OF {1}", {"3", "12"}) == "3 OF 12" && pe::fill("{1}{0}{2}", {"a", "b"}) == "ba" &&
        pe::fill("{x} {0", {"a"}) == "{x} {0" &&
        same(pe::catalog_candidates("fr-CA"), {"fr-CA", "fr-FR"}) &&
        same(pe::catalog_candidates("pt-PT"), {"pt-PT", "pt-BR"}) &&
        same(pe::catalog_candidates("es-419"), {"es-419", "es-ES"}) &&
        same(pe::catalog_candidates("de-DE"), {"de-DE"}) && pe::catalog_candidates("en-GB").empty() &&
        pe::catalog_candidates("en-US").empty() && pe::catalog_candidates("").empty();
    if (!ok)
        std::fprintf(stderr, "error: the launcher's text functions fail their check\n");
    return ok;
}

} // namespace

int main(int argc, char **argv)
{
    if (argc < 3)
    {
        std::fprintf(stderr, "usage: %s <ui assets dir> <output dir> [--tour] [width height]\n",
                     argv[0]);
        return 2;
    }
    const std::string assets = argv[1];
    const std::string output = argv[2];
    int argument = 3;
    const bool make_tour = argc > argument && std::strcmp(argv[argument], "--tour") == 0;
    if (make_tour)
        ++argument;
    const int width = argc > argument + 1 ? std::atoi(argv[argument]) : 1920;
    const int height = argc > argument + 1 ? std::atoi(argv[argument + 1]) : 1080;

    if (!open_context())
    {
        std::fprintf(stderr, "no surfaceless EGL OpenGL 4.5 context\n");
        return 1;
    }
    std::fprintf(stderr, "GL %s / %s\n", reinterpret_cast<const char *>(glGetString(GL_VERSION)),
                 reinterpret_cast<const char *>(glGetString(GL_RENDERER)));
    pe::gfx::set_glsl_prefix("#version 450 core\n");

    if (!strings_check())
        return 1;
    // PE_LANG=<tag>: the launcher in that language, as on a console set to it.
    if (const char *language = std::getenv("PE_LANG"); language != nullptr && language[0] != 0)
    {
        std::string used;
        for (const std::string &candidate : pe::catalog_candidates(language))
        {
            std::string catalog;
            if (pe::read_file(assets + "/lang/" + candidate + ".po", &catalog) &&
                pe::catalog().load(catalog) > 0)
            {
                used = candidate;
                break;
            }
        }
        std::fprintf(stderr, "language %s: catalog %s, %zu texts\n", language,
                     used.empty() ? "none (English)" : used.c_str(), pe::catalog().size());
        pe::ui::set_fit_report(note_fit);
    }

    pe::gfx::Font font;
    std::string font_data;
    if (!pe::read_file(assets + "/fonts/montserrat-medium.pefont", &font_data) ||
        !font.load(font_data))
    {
        std::fprintf(stderr, "cannot load the font: %s\n", font.error().c_str());
        return 1;
    }
    // The console's fonts for the scripts the baked one lacks (PE_SYSTEM_FONTS: copies of them).
    {
        const char *language = std::getenv("PE_LANG");
        const std::string tag = language != nullptr && language[0] != 0 ? language : "en-US";
        for (const std::string &folder : pe::gfx::system_font_folders())
        {
            std::vector<std::string> files = pe::gfx::system_font_files(folder, tag);
            if (files.empty())
                continue;
            std::fprintf(stderr, "system fonts: %zu files in %s\n", files.size(), folder.c_str());
            font.use_system_fonts(std::move(files), tag);
            break;
        }
        if (!pe::catalog().every([&font](std::string_view text) { return font.can_draw(text); }))
        {
            std::fprintf(stderr, "error: the catalog has characters no font here has; on the console the "
                                 "launcher would stay English (PE_SYSTEM_FONTS names a folder with the "
                                 "console's fonts)\n");
            return 1;
        }
    }
    pe::gfx::GlBatch batch;
    if (!batch.init())
        return 1;

    GLuint framebuffer = 0;
    GLuint color = 0;
    glGenFramebuffers(1, &framebuffer);
    glGenRenderbuffers(1, &color);
    glBindRenderbuffer(GL_RENDERBUFFER, color);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, width, height);
    glBindFramebuffer(GL_FRAMEBUFFER, framebuffer);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, color);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
        return 1;

    pe::host::FakeServices services(output);
    // PE_LOOK=large,contrast,calm: the accessibility settings, in any combination.
    if (const char *wanted = std::getenv("PE_LOOK"); wanted != nullptr)
    {
        const std::string_view names{wanted};
        pe::ui::Preferences preferences = services.preferences();
        preferences.large_text = names.find("large") != std::string_view::npos;
        preferences.high_contrast = names.find("contrast") != std::string_view::npos;
        preferences.reduce_motion = names.find("calm") != std::string_view::npos;
        services.set_preferences(preferences);
    }
    if (const char *mode = std::getenv("PE_PREVIEW_SWITCH_THEME");
        mode != nullptr && std::strcmp(mode, "1") == 0) {
        pe::ui::Preferences preferences = services.preferences();
        preferences.ui_theme = 1;
        services.set_preferences(preferences);
    }
    pe::ui::Textures textures(batch, services);
    if (!textures.load_art(assets))
        std::fprintf(stderr, "warning: launcher art is incomplete\n");
    textures.set_output_scale(static_cast<float>(width) / 1920.0f);

    // PE_SPECIMEN=<file>: instead of the screens, one picture of the file's lines of text (a line
    // starting with "W " is wrapped to a column), to look at a script or a translation closely.
    if (const char *specimen = std::getenv("PE_SPECIMEN"); specimen != nullptr && specimen[0] != 0)
    {
        std::string lines;
        if (!pe::read_file(specimen, &lines))
        {
            std::fprintf(stderr, "cannot read %s\n", specimen);
            return 1;
        }
        const std::uint32_t texture = batch.create_font_texture(font);
        pe::gfx::DrawList list;
        list.rounded_rect({0.0f, 0.0f, 1920.0f, 1080.0f}, 0.0f, pe::ui::theme::kPanel);
        float x = 40.0f;
        float y = 60.0f;
        const float size = 30.0f;
        const float pitch = 44.0f;
        const float column = 900.0f;
        const auto advance = [&]
        {
            y += pitch;
            if (y > 1060.0f)
            {
                y = 60.0f;
                x += column + 40.0f;
            }
        };
        for (std::size_t start = 0; start < lines.size();)
        {
            std::size_t end = lines.find('\n', start);
            if (end == std::string::npos)
                end = lines.size();
            std::string_view line{lines.data() + start, end - start};
            start = end + 1;
            if (!line.empty() && line.back() == '\r')
                line.remove_suffix(1);
            if (line.substr(0, 2) == "W ")
            {
                for (const std::string &part : font.wrap(line.substr(2), size, column))
                {
                    list.rounded_rect({x, y - size, column, pitch - 6.0f}, 4.0f, pe::ui::theme::kRow);
                    list.text(font, texture, part, x, y, size, pe::ui::theme::kText);
                    advance();
                }
                continue;
            }
            if (line.substr(0, 2) == "F ")
            {
                // Cut to a narrow place, as a long title is.
                list.rounded_rect({x, y - size, 420.0f, pitch - 6.0f}, 4.0f, pe::ui::theme::kRow);
                list.text(font, texture, font.fit(line.substr(2), size, 420.0f), x, y, size, pe::ui::theme::kText);
                advance();
                continue;
            }
            list.text(font, texture, line, x, y, size, pe::ui::theme::kText);
            list.text(font, texture, line, x + column, y, 20.0f, pe::ui::theme::kLime, pe::gfx::Align::right);
            advance();
        }
        batch.sync_font_texture(texture, font);
        std::vector<unsigned char> pixels(static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 4);
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        batch.draw(list, pe::gfx::fit_viewport(width, height), width, height);
        glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
        stbi_flip_vertically_on_write(1);
        const std::string path = output + "/specimen.png";
        const bool written = stbi_write_png(path.c_str(), width, height, 4, pixels.data(), width * 4) != 0;
        std::fprintf(stderr, "specimen: %zu instances, GL error 0x%x, system fonts read: %s\n", list.instances().size(),
                     glGetError(), font.system_fonts_read().c_str());
        return written ? 0 : 1;
    }

    Stage stage{services, textures, {&font, batch.create_font_texture(font)}, batch, width, height,
                output, nullptr, {}, {}, make_tour, true, {}};
    stage.pixels.resize(static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 4);
    stbi_flip_vertically_on_write(1);
    if (make_tour)
        tour(stage);
    else
        pictures(stage);
    std::fprintf(stderr, "cues heard: %zu\n", stage.heard.size());
    std::fprintf(stderr, "system fonts read: %s\n", font.system_fonts_read().c_str());
    for (const auto &[text, fit] : fits)
        std::fprintf(stderr, "%s %.2f: %s\n", fit.second ? "cut" : "shrunk", fit.first, text.c_str());
    return stage.ok ? 0 : 1;
}
