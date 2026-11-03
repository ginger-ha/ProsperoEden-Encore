// ProsperoEden - Launcher library: the game list, its details and per-game settings.
// Copyright (C) 2026 BlackBearReloaded
// SPDX-License-Identifier: GPL-3.0-or-later

#include "pe/ui/launcher.hpp"
#include "pe/ui/video_presets.hpp"
#include "pe/ui/case_media_selection.hpp"

#include "pe/core/log.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdio>
#include <cctype>
#include <sstream>
#include <exception>
#include <stdexcept>
#include <iterator>
#include <new>
#include <string>
#include <string_view>
#include <unordered_map>

namespace pe::ui
{

using audio::Cue;

namespace
{

constexpr Rect kDialog{550.0f, 180.0f, 820.0f, 720.0f};

// The game settings dialog's rows, and the window that shows five of them (also the Mods list's).
enum GameRow : int
{
    row_mode,
    row_renderer,
    row_performance,
    row_output,
    row_resolution,
    row_filter,
    row_fsr_sharpness,
    row_anti_aliasing,
    row_refresh,
    row_controls,
    row_mods,
    row_save, // in builds that move saves
};
constexpr float kDialogRowsTop = 334.0f;
constexpr float kDialogRowPitch = 96.0f;
constexpr float kDialogRowHeight = 94.0f;
constexpr int kDialogRowsShown = 5;
constexpr Rect kDialogWindow{592.0f, kDialogRowsTop, 736.0f,
                             kDialogRowPitch * (kDialogRowsShown - 1) + kDialogRowHeight};
constexpr float kDialogHints = 848.0f;

// Presentation-only conversions: never rewrite the original Nlib metadata.
std::string library_date(const std::string& iso, const std::string& region)
{
    if (iso.size() < 10 || iso[4] != '-' || iso[7] != '-')
        return iso;
    for (const int pos : {0, 1, 2, 3, 5, 6, 8, 9})
        if (!std::isdigit(static_cast<unsigned char>(iso[static_cast<std::size_t>(pos)])))
            return iso;
    const auto y = iso.substr(0, 4), m = iso.substr(5, 2), d = iso.substr(8, 2);
    if (region == tr("USA")) return m + "/" + d + "/" + y;
    if (region == tr("Japan") || region == tr("China") ||
        region == tr("Korea") || region == tr("Taiwan")) return y + "/" + m + "/" + d;
    return d + "/" + m + "/" + y;
}
std::string library_genres(const std::string& genres)
{
    std::istringstream stream(genres);
    std::string part, result;
    while (std::getline(stream, part, ',')) {
        const auto start = part.find_first_not_of(" \\t");
        if (start == std::string::npos) continue;
        const auto stop = part.find_last_not_of(" \\t");
        if (!result.empty()) result += " · ";
        result += tr(part.substr(start, stop - start + 1));
    }
    return result;
}
std::string library_size(const std::string& size)
{
    const auto pos = size.find(" GB");
    return pos == std::string::npos ? size :
        size.substr(0, pos) + " " + tr("GB") + size.substr(pos + 3);
}
std::string library_format(const std::string& format)
{
    if (format.empty()) return tr("Unknown");
    return format.front() == '.' ? format : "." + format;
}

// One opaque printed-paper substrate per missing face, BELOW artwork and
// typography and ABOVE the independently rendered molded case plastic.
// Never add a local dark panel under a game icon or editorial caption.
constexpr unsigned kReconstructedPaperRGB = 0x112235;
void reconstructed_paper(Canvas& c, const Rect& r)
{
    c.list.rounded_rect(r, 0.0f, Color::rgb(kReconstructedPaperRGB));
}

// CSS background-size: cover. Crop the SOURCE UVs, not the rendered paper
// dimensions: identical X/Y scale, no stretched square icon, full-width ink.
// An absent/decoding bitmap simply reveals the continuous paper underneath.
void reconstructed_cover(Canvas& c, const std::string& path, const Rect& paper)
{
    if (path.empty()) return;
    const Cover art = c.textures.cover(path, std::max(paper.w, paper.h));
    if (art.texture == 0) return;
    const float source = std::max(0.01f, art.aspect);
    const float target = paper.w / std::max(1.0f, paper.h);
    Rect uv{0.0f, 0.0f, 1.0f, 1.0f};
    if (source > target) {
        uv.w = target / source;
        uv.x = (1.0f - uv.w) * 0.5f;
    } else if (source < target) {
        uv.h = source / target;
        uv.y = (1.0f - uv.h) * 0.5f;
    }
    c.list.image(art.texture, paper, uv,
                 Color::rgb(0xffffff, tween::cubic_out(art.age / 0.22f)));
}

// Reconstructed paper inserts share the exact same proportions in the Library
// and in the launch transition's offscreen 3D texture. An actual flat retail
// scan is always preferred by flat_retail_sleeve()/draw_launch().
void flat_front_fallback(Canvas& c, const Game& game, const Rect& r)
{
    // Artwork occupies the WHOLE paper face; the corner logo is printed on
    // top of it, not placed beside it or clipped by the physical case lip.
    // The shared opaque paper has already been painted for BOTH Library
    // and 3D. Hero, screenshot or last-resort icon covers its full width
    // with preserved source proportions (UV crop only).
    const auto* painting = case_media::FrontPaper(
        game.hero, game.cover, game.screenshots);
    // A confirmed missing Hero must not hide a valid screenshot or icon.
    // An in-flight decode keeps priority until it actually fails.
    const float front_bucket = std::max(r.w, r.h);
    if (painting && c.textures.cover(*painting, front_bucket).missing) {
        painting = case_media::FrontPaperAvailable(
            game.hero, game.cover, game.screenshots,
            [&](const std::string& path) {
                return !c.textures.cover(path, front_bucket).missing;
            });
    }
    if (painting) reconstructed_cover(c, *painting, r);
    // A very light FULL-PAPER print tint, not a boxed title background.
    if (painting)
        c.list.gradient_rect(r, 0.0f, Color::rgb(0x09101c, 0.04f),
                            Color::rgb(0x09101c, 0.36f));
    const float title_h = r.h * 0.145f;
    const float font = std::clamp(r.w * 0.083f, 12.0f, 34.0f);
    text_shrink(c, game.name, r.x + r.w * 0.5f,
                baseline(r.y + r.h - title_h * 0.82f, title_h * 0.68f, font),
                font, theme::kTitle, r.w * 0.92f, Align::center);

    // The user's fixed square corner insert is preferred over the legacy
    // simplified badge. It is loaded ONCE with the other launcher art.
    // These dimensions follow logo_front.jpg (193 x 190), not an arbitrary
    // height tied to the cover aspect ratio. No crop and no rounded edges.
    const float logo_w = r.w * 0.222f;
    const Rect logo{r.x, r.y, logo_w, logo_w * (190.0f / 193.0f)};
    if (c.textures.switch_logo() != 0) {
        // This fixed top-left raster insert shares the footer's TGA upload
        // orientation, not the dynamically generated paper texture.
        // Flip the insert ONCE here; the 3D case's final FBO UV flip is
        // separate and must remain unchanged.
        c.list.image(c.textures.switch_logo(), logo,
                     {0.0f, 1.0f, 1.0f, -1.0f}, Color::rgb(0xffffff));
    } else {
        c.list.rounded_rect(logo, 0.0f, Color::rgb(0xe31930));
        const float mark = logo.w * 0.43f;
        const Rect glyph{logo.x + (logo.w - mark) * 0.5f,
                         logo.y + logo.h * 0.17f, mark, logo.h * 0.42f};
        c.list.rounded_rect({glyph.x, glyph.y, mark * 0.47f, glyph.h},
                            mark * 0.09f, Color::rgb(0xffffff));
        c.list.rounded_rect({glyph.x + mark * 0.56f, glyph.y,
                             mark * 0.44f, glyph.h},
                            mark * 0.09f, Color::rgb(0xffffff));
        text_shrink(c, "SWITCH", logo.x + logo.w * 0.5f,
                    baseline(logo.y + logo.h * 0.68f, logo.h * 0.22f,
                             std::max(7.0f, logo.w * 0.145f)),
                    std::max(7.0f, logo.w * 0.145f),
                    Color::rgb(0xffffff), logo.w * 0.95f, Align::center);
    }
}

void flat_back_fallback(Canvas& c, const Game& game, const Rect& r)
{
    // Every missing paper side is FULLY OPAQUE before any asynchronous
    // texture becomes available. No empty scene can reveal the 3D plastic
    // substrate, nor can a missing screenshot cause hero duplication.
    constexpr float kFixedFooter = 0.41f;
    const float footer_h = r.h * kFixedFooter;
    const float dynamic_h = r.h - footer_h;
    const float gap = std::max(2.0f, r.w * 0.007f);
    // A SINGLE opaque paper sheet is drawn by draw_composed_case_face().
    // Scenes are independent of the front's full-bleed hero/icon. Never
    // paste game.cover on the back as a square or panel.
    const float front_bucket = std::max(r.w, r.h);
    const std::string* front = case_media::FrontPaper(
        game.hero, game.cover, game.screenshots);
    // Match the actual front's confirmed-missing fallback. Otherwise a
    // failed Hero may cause the same screenshot to appear on BOTH papers.
    if (front && c.textures.cover(*front, front_bucket).missing) {
        front = case_media::FrontPaperAvailable(
            game.hero, game.cover, game.screenshots,
            [&](const std::string& path) {
                return !c.textures.cover(path, front_bucket).missing;
            });
    }
    const auto shots = case_media::BackScenes(
        front ? *front : game.cover, game.cover, game.screenshots);
    const std::string* first = shots[0];
    const std::string* second = shots[1];
    const std::string* third = shots[2];

    // A back has ONE printed background, optionally with a second distinct
    // scene laid directly on the ink. No rectangular black panel/matte
    // belongs beneath artwork or description.
    const float left_w = r.w * 0.39f;
    const float top_h = dynamic_h * 0.47f;
    const Rect description{r.x + left_w, r.y + top_h * 0.39f + gap,
                           r.w - left_w, top_h * 0.61f - gap};
    if (first) reconstructed_cover(c, *first, {r.x, r.y, r.w, dynamic_h});
    if (second)
        reconstructed_cover(c, *second,
                            {r.x, r.y, left_w - gap, top_h});
    if (third)
        reconstructed_cover(c, *third,
                            {r.x, r.y + top_h + gap, r.w,
                             dynamic_h - top_h - gap});
    // Scene-wide ink glaze: covers the WHOLE upper sheet, not a label box.
    if (first)
        c.list.gradient_rect({r.x, r.y, r.w, dynamic_h}, 0.0f,
                             Color::rgb(0x08111d, 0.07f),
                             Color::rgb(0x08111d, 0.45f));
    const std::string& desc = !game.description.empty() ? game.description :
                              !game.intro.empty() ? game.intro : game.name;
    const float copy_font = std::clamp(r.w * 0.042f, 8.0f, 18.0f);
    const float line_h = copy_font * 1.22f;
    const float usable_h = std::max(line_h, description.h - gap * 3.0f);
    const int lines = std::clamp(static_cast<int>(usable_h / line_h), 1, 8);
    text_block(c, desc, description.x + gap * 1.6f,
               baseline(description.y + gap * 1.4f, copy_font * 1.12f,
                        copy_font), copy_font, line_h,
               Color::rgb(0xffffff), description.w - gap * 3.2f,
               lines, kShrink);

    const Rect footer{r.x, r.y + dynamic_h, r.w, footer_h};
    if (c.textures.switch_rear_footer() != 0) {
        // The exact immutable source-image rectangle is drawn in full.
        // This is a static template, never cropped or tinted, and keeps the
        // reference's game-specific printing independent of dynamic scenes.
        // The supplied footer is upside-down with the GL/TGA default UV
        // orientation. Correct ONLY this static paper insert. The 3D
        // composed case performs its own final offscreen texture Y-flip.
        c.list.image(c.textures.switch_rear_footer(), footer,
                     {0.0f, 1.0f, 1.0f, -1.0f}, Color::rgb(0xffffff));
    } else {
        // Works without a bundled template, but does NOT invent a publisher,
        // barcode, age rating, technical compatibility or certification.
        c.list.rounded_rect(footer, 0.0f, Color::rgb(0xf7f7f7));
        const Color black = Color::rgb(0x151515);
        const Rect rule{footer.x + footer.w * 0.025f,
                        footer.y + footer.h * 0.025f,
                        footer.w * 0.95f, footer.h * 0.18f};
        c.list.rounded_rect(rule, 0.0f, Color::rgb(0xffffff));
        text_shrink(c, "ENCORE / GAME INFORMATION", rule.x + rule.w * 0.5f,
                    baseline(rule.y, rule.h, std::max(8.0f, copy_font * 0.82f)),
                    std::max(8.0f, copy_font * 0.82f), black,
                    rule.w * 0.92f, Align::center);
        c.list.rounded_rect({footer.x + footer.w * 0.025f,
                             footer.y + footer.h * 0.26f,
                             footer.w * 0.95f, 1.2f}, 0.0f, black);
        text_shrink(c, game.name, footer.x + footer.w * 0.5f,
                    baseline(footer.y + footer.h * 0.30f, footer.h * 0.22f,
                             std::max(8.0f, copy_font)),
                    std::max(8.0f, copy_font), black,
                    footer.w * 0.90f, Align::center);
        const std::string& credit = !game.publisher.empty() ?
                                     game.publisher : game.developer;
        if (!credit.empty())
            text_shrink(c, credit, footer.x + footer.w * 0.5f,
                        baseline(footer.y + footer.h * 0.57f,
                                 footer.h * 0.17f, copy_font * 0.82f),
                        copy_font * 0.82f, black,
                        footer.w * 0.90f, Align::center);
    }
}

// Static sleeve used by the Library's front shelf, back detail, and zoom.
// Unlike the spinning launcher model, this is deliberately 2D, but BOTH
// faces use one physical outline with identical inset paper dimensions.
// Neither PNG nor the source art contains baked-in 3D plastic.
// One physical jacket silhouette, regardless of available image aspect.
// Its paper shape matches the 454x730 case with a 440x704 ink rectangle
// used in the launcher 3D composite. The missing-art layout is authored
// exactly once at native ink coordinates, then uniformly scaled.
constexpr float kCaseShellAspect = 454.0f / 730.0f;
constexpr float kCaseInkWidth = 440.0f;
constexpr float kCaseInkHeight = 704.0f;

void flat_composed_ink(Canvas& c, const Game& game,
                       const Rect& paper, bool rear)
{
    const float scale = std::min(paper.w / kCaseInkWidth,
                                 paper.h / kCaseInkHeight);
    if (scale <= 0.0f) return;
    // Uniform viewport inside the paper: no independent typography,
    // altered collages, stretched fixed footer or clipped corner mark.
    const float x = paper.x + (paper.w - kCaseInkWidth * scale) * 0.5f;
    const float y = paper.y + (paper.h - kCaseInkHeight * scale) * 0.5f;
    c.list.push_transform(scale, x, y, 0.0f, 0.0f);
    draw_composed_case_face(c, game,
                             {x, y, kCaseInkWidth, kCaseInkHeight}, rear);
    c.list.pop_transform();
}

void flat_retail_sleeve(Canvas& c, const Game& game, const Rect& shell,
                        bool rear, float shadow, float texture_scale = 1.0f)
{
    // Keep the front nearly edge-to-edge: the retail scan should dominate
    // the jacket, not an oversized clear-plastic strip on its right.
    // The back retains its original print-preserving proportions.
    // Physically scaled 7px lateral and 13px upper/lower lips, matching
    // both 3D face planes. Never depend on original image dimensions.
    const float side = shell.w * (7.0f / 454.0f);
    const float top = shell.h * (13.0f / 730.0f);
    const float radius = std::max(5.0f, shell.w * 0.028f);
    // One continuous square-corner paper wrap, folded directly onto the
    // printed red spine: front touches its LEFT hinge, back its RIGHT hinge.
    // The ONLY exposed clear-plastic vertical opening is the opposite edge.
    // Front/back both use the same paper height; do not add a second frame.
    // Back paper reaches the RIGHT fold: plastic opening only on the LEFT.
    // Front paper mirrors it and meets the LEFT spine.
    const Rect paper{shell.x + (rear ? side : 0.0f), shell.y + top,
                     shell.w - side, shell.h - 2.0f * top};
    if (shadow > 0.0f)
        c.list.shadow({shell.x + 2.0f, shell.y + 7.0f, shell.w - 4.0f,
                       shell.h - 1.0f}, radius, 21.0f * shadow,
                      Color::rgb(0x02030a, 0.64f));

    // The pale molded case substrate is BEHIND the printed sleeve. The
    // opening side remains readable against dark UI backgrounds without
    // coating the entire front/back scan in a translucent second layer.
    if (rear)
        c.list.gradient_rect(shell, radius, Color::rgb(0xb6c4d5, 0.78f),
                             Color::rgb(0x66778c, 0.79f));
    else
        // Any spare margin belongs to the dark cover backing, never a wide
        // pale-plastic column. Only top/bottom/right retain a clear case rim.
        c.list.gradient_rect(shell, radius, Color::rgb(0x171126, 0.96f),
                             Color::rgb(0x0e0a19, 0.97f));

    const std::string& scan = rear ? game.box_back : game.box_front;
    // One continuous opaque sheet beneath BOTH original and reconstructed
    // printing. The back's right edge must never reveal molded plastic.
    reconstructed_paper(c, paper);
    const Cover artwork = scan.empty() ? Cover{} : c.textures.cover(
        scan, std::max(paper.w, paper.h) * texture_scale);
    if (artwork.texture != 0) {
        // A real scan wins only after it is actually decoded. While pending,
        // the paper underneath remains opaque, with no fake dark panel.
        // Both printed faces are shown in full: never crop titles or logos.
        const float source = std::max(0.01f, artwork.aspect);
        const float target = paper.w / paper.h;
        if (!rear) {
            // Original NS1 and NS2 fronts are printed edge-to-edge. UV crop
            // preserves their proportions while removing the large blank
            // side gutters previously produced by aspect-fit presentation.
            Rect uv{0.0f, 0.0f, 1.0f, 1.0f};
            if (source > target) {
                uv.w = target / source;
                uv.x = (1.0f - uv.w) * 0.5f;
            } else if (source < target) {
                uv.h = source / target;
                uv.y = (1.0f - uv.h) * 0.5f;
            }
            c.list.image(artwork.texture, paper, uv,
                         Color::rgb(0xffffff, tween::cubic_out(artwork.age / 0.22f)));
        } else {
            // Preserve every word and logo on a genuine printed back.
            Rect fitted = paper;
            if (source > target) {
                fitted.h = paper.w / source;
                fitted.y += (paper.h - fitted.h) * 0.5f;
            } else if (source < target) {
                fitted.w = paper.h * source;
                fitted.x += paper.w - fitted.w;
            }
            c.list.image(artwork.texture, fitted, {0.0f, 0.0f, 1.0f, 1.0f},
                         Color::rgb(0xffffff, tween::cubic_out(artwork.age / 0.22f)));
        }
    } else {
        // Empty OR confirmed-unreadable retail media: preserve the shared
        // 440x704 composition rather than leaving a permanently blank sleeve.
        // It automatically yields to the real scan if its retry later works.
        flat_composed_ink(c, game, paper, rear);
    }

    // ONE physical shell: narrow top/bottom molded caps and ONE clear
    // opening edge. On the front it is RIGHT; on the rear it is LEFT.
    // Never add a clear vertical border at the rear's RIGHT printed fold.
    c.list.gradient_rect({shell.x, shell.y, shell.w, top}, 0.0f,
                         Color::rgb(0xf7fcff, 0.76f),
                         Color::rgb(0x71859d, 0.54f));
    c.list.gradient_rect({shell.x, shell.y + shell.h - top,
                          shell.w, top}, 0.0f,
                         Color::rgb(0x74869d, 0.55f),
                         Color::rgb(0xf3f9ff, 0.78f));
    const float cap_ridge = std::max(1.0f, top * 0.17f);
    c.list.gradient_rect({shell.x, shell.y + top - cap_ridge,
                          shell.w, cap_ridge}, 0.0f,
                         Color::rgb(0xffffff, 0.43f),
                         Color::rgb(0x99b1c9, 0.24f));
    c.list.gradient_rect({shell.x, shell.y + shell.h - top,
                          shell.w, cap_ridge}, 0.0f,
                         Color::rgb(0x33465d, 0.29f),
                         Color::rgb(0xf5faff, 0.34f));

    const float opening_x = rear ? shell.x : shell.x + shell.w - side;
    const float opening_y = shell.y + top;
    const float opening_h = shell.h - 2.0f * top;
    const float highlight_w = rear ? std::max(1.1f, side * 0.25f)
                                   : std::min(side, std::max(0.5f, side * 0.30f));
    // Diffused body plus separate refractive outside highlight and darker
    // inner seal. Gradients reverse with the side, not with the scan UV.
    c.list.hgradient_rect({opening_x, opening_y, side, opening_h}, 0.0f,
                          rear ? Color::rgb(0xf7fbff, 0.91f)
                               : Color::rgb(0x788fa9, 0.68f),
                          rear ? Color::rgb(0x7489a2, 0.70f)
                               : Color::rgb(0xf5faff, 0.92f));
    const float glint_x = rear ? opening_x : opening_x + side - highlight_w;
    c.list.hgradient_rect({glint_x, opening_y, highlight_w, opening_h}, 0.0f,
                          Color::rgb(0xffffff, rear ? 0.64f : 0.35f),
                          Color::rgb(0xe6f4ff, rear ? 0.35f : 0.72f));
    const float seal_x = rear ? opening_x + side - highlight_w : opening_x;
    c.list.hgradient_rect({seal_x, opening_y, highlight_w, opening_h}, 0.0f,
                          Color::rgb(0x354a66, rear ? 0.36f : 0.17f),
                          Color::rgb(0xa4bed6, rear ? 0.15f : 0.35f));
    // Fine manufacturing striations live on the opening rim ONLY.
    // They suggest transparent textured plastic without painting the art.
    for (int i = 1; i < 5; ++i) {
        const float y = opening_y + opening_h * (float(i) / 5.0f);
        c.list.gradient_rect({opening_x, y, side, 1.0f}, 0.0f,
                             Color::rgb(0xffffff, 0.18f),
                             Color::rgb(0x7189a4, 0.12f));
    }
    // The paper keeps square corners and its original branding untouched.
}

std::string controller_profile_name(int layout, const ButtonMapping& mapping)
{
    const bool custom = mapping_is_custom(mapping, layout);
    if (layout == 1)
        return custom ? tr("Custom Switch") : tr("Switch");
    return custom ? tr("Custom PS5") : tr("PlayStation");
}

} // namespace

void draw_composed_case_face(Canvas &c, const Game &game, const Rect &paper, bool rear)
{
    // The 2D shelf and rotating 3D case share one continuous paper layer.
    // Plastic/caps remain separate; no per-element background is permitted.
    reconstructed_paper(c, paper);
    if (rear)
        flat_back_fallback(c, game, paper);
    else
        flat_front_fallback(c, game, paper);
}
bool composed_case_face_ready(Textures& textures, const Game& game,
                              bool rear, bool allow_missing)
{
    // Use the exact media drawn by the shared procedural composition.
    // A front icon is NEVER a dependency for the reconstructed rear.
    const auto ready = [&](const std::string& path, float extent) {
        if (path.empty()) return true;
        const Cover item = textures.cover(path, extent);
        return (item.texture != 0 && item.age >= 0.22f) ||
               (allow_missing && item.missing);
    };
    const auto* front = case_media::FrontPaper(
        game.hero, game.cover, game.screenshots);
    if (!rear) {
        if (front && textures.cover(*front, 704.0f).missing) {
            front = case_media::FrontPaperAvailable(
                game.hero, game.cover, game.screenshots,
                [&](const std::string& path) {
                    return !textures.cover(path, 704.0f).missing;
                });
        }
        return !front || ready(*front, 704.0f);
    }

    constexpr float paper_w = 440.0f;
    constexpr float dynamic_h = 704.0f * (1.0f - 0.41f);
    constexpr float top_h = dynamic_h * 0.47f;
    constexpr float left_w = paper_w * 0.39f;
    const float gap = std::max(2.0f, paper_w * 0.007f);
    const auto shots = case_media::BackScenes(
        front ? *front : game.cover, game.cover, game.screenshots);
    if (shots[0] && !ready(*shots[0], paper_w)) return false;
    if (shots[1] && !ready(*shots[1], std::max(left_w - gap, top_h)))
        return false;
    if (shots[2] && !ready(*shots[2], paper_w))
        return false;
    return true; // legitimate all-ink page with no bitmap sources
}


void Launcher::start_scan()
{
    // A missing volume is not an empty game library, including FIRST load.
    // Never publish an empty initial snapshot or overwrite a last-good one.
    if (!scan_cancel_.load(std::memory_order_acquire) &&
        !scan_.valid() && home_.setup_ready)
        scan_ = std::async(std::launch::async, [this] {
            std::vector<Game> games = services_.games(&scan_cancel_);
            if (scan_cancel_.load(std::memory_order_acquire))
                return std::vector<Game>{};
            // Reading mod folders / disabled-mod settings for each installed
            // title used to happen inside apply_games() on the UI update
            // thread, potentially scanning hundreds of directories at once.
            // Populate the immutable game-list snapshot on this worker instead.
            // One immutable global preference snapshot for the whole worker
            // pass. The native service still reads per-game override JSON
            // independently, but never rereads the global JSON for each ROM.
            const Preferences docked_preferences = services_.preferences();
            unsigned mod_scan_errors = 0;
            for (Game &game : games) {
                if (scan_cancel_.load(std::memory_order_acquire)) break;
                if (game.title_id == 0) continue;
                try {
                    // The UI used to reload both per-game and global JSON
                    // settings in refresh_selected_game() on EVERY D-pad move.
                    // Resolve the effective mode once on this worker instead.
                    game.docked = services_.docked_for_scan(game.title_id, docked_preferences);
                    const std::vector<Mod> mods = services_.mods(game.title_id);
                    game.mods = static_cast<int>(mods.size());
                    game.mods_enabled = mods.empty() || services_.mods_enabled(game.title_id);
                    game.mods_on = !game.mods_enabled ? 0 : static_cast<int>(
                        std::count_if(mods.begin(), mods.end(),
                                      [](const Mod &mod) { return mod.enabled; }));
                } catch (const std::bad_alloc&) {
                    throw; // never disguise memory exhaustion as an absent mod
                } catch (const std::exception& error) {
                    // One damaged/inaccessible mod folder must not discard the
                    // entire game list. Keep defaults for that title only.
                    if (mod_scan_errors++ < 3)
                        sys::log("mod scan title=%llx: %s",
                                 static_cast<unsigned long long>(game.title_id), error.what());
                }
            }
            // Recheck after enumeration and enrichment on this worker. A
            // missing volume can return an empty or truncated success-shaped
            // result; avoid a false "No ROM" even on the first-ever scan.
            // A truly empty library on an available volume remains valid.
            if (!services_.game_storage_available())
                throw std::runtime_error{"ROM storage unavailable during scan; retaining last-good library"};
            return games;
        });
}

void Launcher::finish_scan(bool wait)
{
    if (!scan_.valid())
        return;
    if (!wait && scan_.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
        return;
    try
    {
        auto games = scan_.get();
        // A completed worker is still joined, but never apply its stale
        // results after a game launch has begun.
        if (!scan_cancel_.load(std::memory_order_acquire))
            apply_games(std::move(games));
    }
    catch (const std::exception &error)
    {
        sys::log("game list: %s", error.what());
        // Preserve an existing list but do not mark an empty first scan as
        // successfully loaded. Home Triangle may have a deferred request;
        // report a scan error, not a misleading "ROM missing" result.
        if (!games_loaded_) {
            pending_settings_file_.clear();
            say(tr("Could not load game list. Please try again."), true);
            cue(Cue::error);
        }
    }
    // A preferences save could overlap the previous worker's settings
    // reads. Rescan once after it completes so docked values come from
    // the new global profile, not the old in-flight snapshot.
    if (docked_refresh_after_scan_) {
        docked_refresh_after_scan_ = false;
        if (!scan_cancel_.load(std::memory_order_acquire))
            start_scan();
    }
}

void Launcher::start_home_media()
{
    if (media_cancel_.load(std::memory_order_acquire) || home_media_scan_.valid()) return;

    const Recent* recent =
        home_recent_ >= 0 && home_recent_ < static_cast<int>(home_.recents.size()) ?
            &home_.recents[static_cast<std::size_t>(home_recent_)] : nullptr;
    const std::uint64_t title_id = recent != nullptr ? recent->title_id : home_.last_title_id;
    if (title_id == 0) return;
    const auto now = std::chrono::steady_clock::now();
    const auto due = home_media_next_retry_.find(title_id);
    if (due != home_media_next_retry_.end() && now < due->second)
        return;

    // Do not infer the full Nlib media set from a banner/intro: an otherwise
    // rich-looking cached title can still be missing all three screenshots.
    Game request;
    request.title_id = title_id;
    if (recent != nullptr) {
        request.file = recent->file;
        request.name = recent->title;
        request.cover = recent->cover;
        request.hero = recent->hero;
        if (!recent->screenshot.empty()) request.screenshots.push_back(recent->screenshot);
        request.max_players = recent->max_players;
        request.intro = recent->intro;
    } else {
        request.file = home_.last_file;
        request.name = home_.last_title;
        request.cover = home_.last_cover;
        request.hero = home_.last_hero;
        if (!home_.last_screenshot.empty()) request.screenshots.push_back(home_.last_screenshot);
        request.max_players = home_.last_max_players;
        request.intro = home_.last_intro;
    }

    // An incomplete response must never blacklist this game until restart.
    // A short cooldown keeps the UI responsive without retrying every frame.
    home_media_next_retry_[title_id] = now + std::chrono::minutes(2);
    home_media_scan_title_id_ = title_id;
    home_media_scan_ = std::async(std::launch::async, [this, request = std::move(request)]() mutable {
        return services_.enrich_game_media(std::move(request), &media_cancel_);
    });
}

void Launcher::finish_home_media()
{
    if (!home_media_scan_.valid() ||
        home_media_scan_.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
        return;

    try {
        Game enriched = home_media_scan_.get();
        // A worker response belongs strictly to the request that launched
        // it. Do not publish a zero/wrong TitleID into Home, Recents or the
        // library during an overlapping selection or failed lookup.
        if (!enriched.title_id || enriched.title_id != home_media_scan_title_id_)
            throw std::runtime_error{"stale Home media identity"};
        if (enriched.artwork_changed) {
            textures_.invalidate(enriched.cover);
            textures_.invalidate(enriched.hero);
            for (const auto& path : enriched.screenshots) textures_.invalidate(path);
        }
        // Preserve stable, already-uploaded GL covers across unchanged
        // metadata refreshes. Only a successful atomic file replacement may
        // invalidate the corresponding physical-case texture.
        if (enriched.case_artwork_changed & 1u)
            textures_.invalidate(enriched.box_front);
        if (enriched.case_artwork_changed & 2u)
            textures_.invalidate(enriched.box_back);
        if (enriched.title_id == home_.last_title_id) {
            if (!enriched.cover.empty()) home_.last_cover = enriched.cover;
            if (!enriched.hero.empty()) home_.last_hero = enriched.hero;
            if (!enriched.screenshots.empty()) home_.last_screenshot = enriched.screenshots.front();
            if (enriched.max_players > 0) home_.last_max_players = enriched.max_players;
            if (!enriched.name.empty()) home_.last_title = enriched.name;
            if (!enriched.intro.empty()) home_.last_intro = enriched.intro;
            if (!enriched.description.empty()) home_.last_description = enriched.description;
        }
        for (Recent& recent : home_.recents) {
            if (recent.title_id != enriched.title_id) continue;
            if (!enriched.cover.empty()) recent.cover = enriched.cover;
            if (!enriched.hero.empty()) recent.hero = enriched.hero;
            if (!enriched.screenshots.empty()) recent.screenshot = enriched.screenshots.front();
            if (enriched.max_players > 0) recent.max_players = enriched.max_players;
            if (!enriched.name.empty()) recent.title = enriched.name;
            if (!enriched.intro.empty()) recent.intro = enriched.intro;
            if (!enriched.description.empty()) recent.description = enriched.description;
        }
        // If the library scan completed while the Home request was in flight, keep both views
        // on the same cache result without another network request.
        for (Game& game : games_) {
            if (!enriched.title_id || game.title_id != enriched.title_id) continue;
            if (!enriched.cover.empty()) game.cover = enriched.cover;
            if (!enriched.box_front.empty()) game.box_front = enriched.box_front;
            if (!enriched.box_back.empty()) game.box_back = enriched.box_back;
            if (!enriched.hero.empty()) game.hero = enriched.hero;
            if (!enriched.screenshots.empty()) game.screenshots = enriched.screenshots;
            if (enriched.max_players > 0) game.max_players = enriched.max_players;
            if (!enriched.name.empty()) game.name = enriched.name;
            if (!enriched.intro.empty()) game.intro = enriched.intro;
            if (!enriched.description.empty()) game.description = enriched.description;
            if (!enriched.publisher.empty()) game.publisher = enriched.publisher;
            if (!enriched.developer.empty()) game.developer = enriched.developer;
            if (!enriched.release_date.empty()) game.release_date = enriched.release_date;
            if (!enriched.categories.empty()) game.categories = enriched.categories;
            // Home's Nlib result must refresh every installed copy of this
            // TitleID, not just the first item encountered in a rescan.
            // A zero or changed identity never inherits its metadata.
        }
    }
    catch (const std::exception& error)
    {
        sys::log("Nlib home media: %s", error.what());
    }
    home_media_scan_title_id_ = 0;
    // If the user selected another Recent card while this request ran, start that title now.
    start_home_media();
}

void Launcher::start_selected_media()
{
    if (media_cancel_.load(std::memory_order_acquire) ||
        media_scan_.valid() || games_.empty()) return;
    // Prefer the highlighted title but then cover ALL installed titles, even
    // those never selected. Download the complete Nlib media set per title
    // without blocking input, drawing or ROM enumeration.
    const int selected = std::clamp(library_.selected, 0, static_cast<int>(games_.size()) - 1);
    for (std::size_t offset = 0; offset < games_.size(); ++offset) {
        const auto index = (static_cast<std::size_t>(selected) + offset) % games_.size();
        const Game& game = games_[index];
        if (game.title_id == 0) continue;
        const auto now = std::chrono::steady_clock::now();
        const auto due = media_next_retry_.find(game.title_id);
        if (due != media_next_retry_.end() && now < due->second) continue;
        // Retry missing/corrupt cached artwork after a bounded cooldown rather
        // than treating the first failed HTTPS request as permanent.
        media_next_retry_[game.title_id] = now + std::chrono::minutes(5);
        media_scan_title_id_ = game.title_id;
        Game copy = game;
        media_scan_ = std::async(std::launch::async, [this, copy = std::move(copy)]() mutable {
            return services_.enrich_game_media(std::move(copy), &media_cancel_);
        });
        return;
    }
}

void Launcher::finish_selected_media()
{
    if (!media_scan_.valid() || media_scan_.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
        return;
    try {
        Game enriched = media_scan_.get();
        if (!enriched.title_id || enriched.title_id != media_scan_title_id_)
            throw std::runtime_error{"stale library media identity"};
        if (enriched.artwork_changed) {
            textures_.invalidate(enriched.cover);
            textures_.invalidate(enriched.hero);
            for (const auto& path : enriched.screenshots) textures_.invalidate(path);
        }
        // Preserve stable, already-uploaded GL covers across unchanged
        // metadata refreshes. Only a successful atomic file replacement may
        // invalidate the corresponding physical-case texture.
        if (enriched.case_artwork_changed & 1u)
            textures_.invalidate(enriched.box_front);
        if (enriched.case_artwork_changed & 2u)
            textures_.invalidate(enriched.box_back);
        for (Game& game : games_) {
            if (!enriched.title_id || game.title_id != enriched.title_id) continue;
            if (!enriched.cover.empty()) game.cover = enriched.cover;
            if (!enriched.box_front.empty()) game.box_front = enriched.box_front;
            if (!enriched.box_back.empty()) game.box_back = enriched.box_back;
            if (!enriched.hero.empty()) game.hero = enriched.hero;
            if (!enriched.screenshots.empty()) game.screenshots = enriched.screenshots;
            if (enriched.max_players > 0) game.max_players = enriched.max_players;
            if (!enriched.name.empty()) game.name = enriched.name;
            if (!enriched.intro.empty()) game.intro = enriched.intro;
            if (!enriched.description.empty()) game.description = enriched.description;
            if (!enriched.publisher.empty()) game.publisher = enriched.publisher;
            if (!enriched.developer.empty()) game.developer = enriched.developer;
            if (!enriched.release_date.empty()) game.release_date = enriched.release_date;
            if (!enriched.categories.empty()) game.categories = enriched.categories;
            // A single Nlib lookup belongs to a TitleID and must update
            // EVERY installed copy; moving into the first one silently
            // starved later entries with that same identity.
            sync_home_game(game);
        }
    }
    catch (const std::exception& error)
    {
        sys::log("Nlib selected media: %s", error.what());
    }
    media_scan_title_id_ = 0;
    // If the player moved while that request was running, enrich the title highlighted now.
    start_selected_media();
}

void Launcher::apply_games(std::vector<Game> games)
{
    // The same games in the same order (the usual case) keep the list where it is; otherwise
    // the selection follows its game.
    bool same = games_loaded_ && games.size() == games_.size();
    for (std::size_t i = 0; same && i < games.size(); ++i)
        same = games[i].file == games_[i].file &&
               games[i].title_id == games_[i].title_id;
    const std::string selected = library_.selected >= 0 &&
                                 library_.selected < static_cast<int>(games_.size()) ?
                                     games_[static_cast<std::size_t>(library_.selected)].file :
                                     std::string{};
    // A fresh filesystem snapshot can reorder ROMs when updates/DLC are
    // discovered or a title is added. Keep already enriched media for the
    // same physical file and nonzero TitleID, regardless of its list index.
    // New metadata still takes precedence; never inherit media from an
    // unrelated game reusing a path. No filesystem I/O on the UI thread.
    const auto merge_media = [](Game& incoming, const Game& previous) {
        if (!incoming.title_id || incoming.title_id != previous.title_id ||
            incoming.file != previous.file)
            return;
        const auto keep_missing = [](auto& target, const auto& cached) {
            if (target.empty()) target = cached;
        };
        keep_missing(incoming.cover, previous.cover);
        keep_missing(incoming.box_front, previous.box_front);
        keep_missing(incoming.box_back, previous.box_back);
        keep_missing(incoming.hero, previous.hero);
        keep_missing(incoming.screenshots, previous.screenshots);
        keep_missing(incoming.intro, previous.intro);
        keep_missing(incoming.description, previous.description);
        keep_missing(incoming.publisher, previous.publisher);
        keep_missing(incoming.developer, previous.developer);
        keep_missing(incoming.release_date, previous.release_date);
        keep_missing(incoming.categories, previous.categories);
        if (incoming.max_players <= 0)
            incoming.max_players = previous.max_players;
    };
    if (same) {
        // Fast path: original scan order, no dictionary construction.
        for (std::size_t i = 0; i < games.size(); ++i)
            merge_media(games[i], games_[i]);
    } else if (games_loaded_ && !games_.empty()) {
        // Indexed once, not O(new ROMs * old ROMs) and not a disk scan.
        // String views only borrow the old filenames until the final move.
        std::unordered_map<std::string_view, const Game*> previous_by_file;
        previous_by_file.reserve(games_.size());
        for (const Game& previous : games_)
            previous_by_file.emplace(previous.file, &previous);
        for (Game& incoming : games) {
            const auto found = previous_by_file.find(incoming.file);
            if (found != previous_by_file.end())
                merge_media(incoming, *found->second);
        }
    }
    // A same-order scan may carry changed per-title mod preferences.
    // Update the selected Mods switch without a full selection refresh
    // (which would reset its detail animation and restart media requests).
    const bool selected_mods_changed =
        same && library_.selected >= 0 &&
        library_.selected < static_cast<int>(games.size()) &&
        games[static_cast<std::size_t>(library_.selected)].mods_enabled !=
            games_[static_cast<std::size_t>(library_.selected)].mods_enabled;
    games_ = std::move(games);
    games_loaded_ = true;
    // Keep the player's jacket inspection during a same-identity metadata
    // or preferences refresh. A different file/TitleID or a reordered list
    // resets the viewer so it cannot show a stale game's rear artwork.
    if (!same) {
        library_back_focused_ = false;
        library_back_zoom_ = false;
    }
    // Even if file order stayed identical, a preferences refresh may
    // have changed the selected game's effective docked mode.
    if (same && library_.selected >= 0 &&
        library_.selected < static_cast<int>(games_.size())) {
        const Game& selected_game = games_[static_cast<std::size_t>(library_.selected)];
        selected_docked_ = selected_game.docked;
        if (selected_mods_changed)
            mods_switch_.snap(selected_game.mods_enabled ? 1.0f : 0.0f);
    }
    // Mod counts were resolved by the background scan; never perform a
    // second synchronous per-title disk walk while applying the list.
    if (!same)
    {
        int index = 0;
        for (int i = 0; i < static_cast<int>(games_.size()); ++i)
            if (games_[static_cast<std::size_t>(i)].file == selected)
                index = i;
        library_.reset(static_cast<int>(games_.size()), index);
        refresh_selected_game();
        mode_.snap(selected_docked_ ? 0.0f : 1.0f);
    }
    name_home_games();
    // Start the global artwork queue as soon as game enumeration completes.
    start_selected_media();
}

void Launcher::sync_home_game(const Game& game)
{
    // Nlib updates only one title. Updating every installed ROM here
    // creates avoidable work on the PS5 UI thread during navigation.
    if (game.file == home_.last_file)
    {
        home_.last_mods = game.mods;
        home_.last_mods_on = game.mods_on;
        home_.last_title = game.name;
        if (!game.hero.empty()) home_.last_hero = game.hero;
        if (!game.screenshots.empty()) home_.last_screenshot = game.screenshots.front();
        if (!game.intro.empty()) home_.last_intro = game.intro;
        if (!game.description.empty()) home_.last_description = game.description;
        if (game.max_players > 0) home_.last_max_players = game.max_players;
    }
    for (Recent &recent : home_.recents)
        if (recent.file == game.file)
        {
            recent.title = game.name;
            if (!game.hero.empty()) recent.hero = game.hero;
            if (!game.screenshots.empty()) recent.screenshot = game.screenshots.front();
            if (!game.intro.empty()) recent.intro = game.intro;
            if (!game.description.empty()) recent.description = game.description;
            if (game.max_players > 0) recent.max_players = game.max_players;
        }
}

void Launcher::name_home_games()
{
    // One complete pass only after the native ROM-list scan changes.
    for (const Game& game : games_)
        sync_home_game(game);
}

void Launcher::start_diagnostics(bool force)
{
    if (diagnostics_cancel_.load(std::memory_order_acquire))
        return;
    if (diagnostics_scan_.valid()) {
        // A modal opened immediately after category navigation should
        // reuse its ongoing scan. Only an explicit mutation/maintenance
        // invalidates the result and demands a second disk inventory.
        if (force)
            diagnostics_refresh_pending_ = true;
        return;
    }
    diagnostics_scan_ = std::async(std::launch::async,
        [this] { return services_.diagnostics(&diagnostics_cancel_); });
}

void Launcher::finish_diagnostics()
{
    if (!diagnostics_scan_.valid() ||
        diagnostics_scan_.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
        return;
    try {
        DiagnosticsInfo result = diagnostics_scan_.get();
        // Never replace post-maintenance UI state with a scan started
        // before the deletion of stale cache/log files.
        if (!diagnostics_refresh_pending_)
            home_diagnostics_ = std::move(result);
    } catch (const std::exception& error) {
        sys::log("diagnostics scan: %s", error.what());
    } catch (...) {
        sys::log("diagnostics scan failed");
    }
    if (diagnostics_refresh_pending_) {
        diagnostics_refresh_pending_ = false;
        start_diagnostics();
    }
}

void Launcher::read_home()
{
    // The native Home service performs ROM filesystem reads, per-title
    // metadata, addon scanning and cached Nlib reads. Never run it on the
    // UI owner thread, including missing-ROM recovery.
    if (home_cancel_.load(std::memory_order_acquire))
        return;
    start_diagnostics();
    if (home_scan_.valid()) {
        home_reload_pending_ = true;
        return;
    }
    home_scan_ = std::async(std::launch::async, [this] {
        return services_.home(&home_cancel_);
    });
}

void Launcher::finish_home_scan()
{
    if (!home_scan_.valid() ||
        home_scan_.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
        return;

    try {
        Home snapshot = home_scan_.get();
        if (home_cancel_.load(std::memory_order_acquire) ||
            !selected_game_.empty())
            return; // never apply results after game launch
        if (home_reload_pending_) {
            // A ROM was removed or a fresh state was requested while
            // the prior snapshot was in flight. Discard it rather than
            // briefly exposing stale game tiles.
            home_reload_pending_ = false;
            read_home();
            return;
        }
        const bool initial = !home_loaded_;
        const std::string previous_file =
            home_recent_ >= 0 && home_recent_ < static_cast<int>(home_.recents.size()) ?
                home_.recents[static_cast<std::size_t>(home_recent_)].file : std::string{};
        home_ = std::move(snapshot);
        home_loaded_ = true;
        if (!previous_file.empty()) {
            const auto recent = std::find_if(home_.recents.begin(), home_.recents.end(),
                [&](const Recent& entry) { return entry.file == previous_file; });
            home_recent_ = recent == home_.recents.end() ? -1 :
                static_cast<int>(recent - home_.recents.begin());
        } else {
            home_recent_ = -1;
        }
        if (!initial && home_focus_ >= 5 && home_focus_ <= 11) {
            // The recent list may reorder while its metadata worker runs.
            // Keep focus on the same game by filename, never on a stale
            // numerical card index or on a removed tile.
            home_focus_ = home_recent_ >= 0 ? 5 + home_recent_ :
                home_.last_exists ? 0 : (home_.setup_ready ? 1 : 2);
        }

        // Mod counts are already calculated by the asynchronous library
        // enumeration. Do not reopen every mod directory on this frame.
        if (home_.last_title_id != 0 && games_loaded_) {
            const auto game = std::find_if(games_.begin(), games_.end(),
                [this](const Game& entry) { return entry.file == home_.last_file; });
            if (game != games_.end()) {
                home_.last_mods = game->mods;
                home_.last_mods_on = game->mods_on;
            }
        }
        if (initial) {
            const bool continue_ready = home_.setup_ready && home_.last_exists;
            home_focus_ = continue_ready ? 0 : home_.setup_ready ? 1 : 2;
            for (std::size_t i = 0; i < home_springs_.size(); ++i)
                home_springs_[i].snap(static_cast<int>(i) == home_focus_ ? 1.0f : 0.0f);
            cue(home_.launch_failed ? Cue::notify :
                first_start_ ? Cue::welcome : Cue::resume);
        } else if (home_focus_ == 4 && !home_.last_exists) {
            home_focus_ = home_.setup_ready ? 1 : 2;
        }
        refresh_home_hero();
        if (!games_loaded_ && !scan_.valid())
            start_scan();
    } catch (const std::exception& error) {
        home_reload_pending_ = false;
        if (!home_loaded_) {
            home_.setup_ready = false;
            home_.status = tr("Could not load game library. Reopen Encore to retry.");
            home_.system_status = tr("Game library unavailable");
            home_focus_ = 2;
            home_loaded_ = true; // recovery/settings remain accessible
        }
        sys::log("Home metadata scan: %s", error.what());
    } catch (...) {
        home_reload_pending_ = false;
        if (!home_loaded_) {
            home_.setup_ready = false;
            home_.status = tr("Could not load game library. Reopen Encore to retry.");
            home_.system_status = tr("Game library unavailable");
            home_focus_ = 2;
            home_loaded_ = true;
        }
        sys::log("Home metadata scan failed");
    }
}

void Launcher::check_games_present()
{
    // The old two-second poll stat'ed every Home/Library path on the UI
    // update thread. A slow PS5 filesystem response stalled menu navigation.
    // Collect an immutable filename snapshot on the owner thread and query
    // existence in a single worker. Only UI-thread code mutates game state.
    if (presence_scan_.valid()) {
        if (presence_scan_.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
            return;
        try {
            const std::vector<std::string> observed_missing = presence_scan_.get();
            // Results can be stale after a ROM folder refresh or atomic file
            // replacement. Require the same missing path in two independent
            // scans before removing UI items. Worker paths are sorted, so
            // this confirmation needs no filesystem I/O on the UI thread.
            std::vector<std::string> missing;
            std::set_intersection(observed_missing.begin(), observed_missing.end(),
                                  previous_missing_.begin(), previous_missing_.end(),
                                  std::back_inserter(missing));
            previous_missing_ = observed_missing;
            if (observed_missing.empty())
                home_missing_refresh_.clear(); // future removal is a NEW transition
            if (missing.empty())
                return;
            // Refresh Home once for a confirmed group of absent tiles.
            // Reissuing read_home() for the same missing path every two
            // seconds could repeatedly mark the next async scan stale,
            // starving its snapshot indefinitely on a slow PS5 filesystem.
            std::vector<std::string> home_missing;
            for (const std::string& file : missing) {
                const bool is_home = (home_.last_exists && file == home_.last_file) ||
                    std::any_of(home_.recents.begin(), home_.recents.end(),
                        [&](const Recent& recent) { return recent.file == file; });
                if (is_home) home_missing.push_back(file);
            }
            if (home_missing.empty())
                home_missing_refresh_.clear();
            if (screen_ == Screen::home && modal_ == Modal::none &&
                !home_missing.empty() && home_missing != home_missing_refresh_) {
                home_missing_refresh_ = home_missing;
                read_home();
                const int recents = std::min<int>(7, static_cast<int>(home_.recents.size()));
                if (home_focus_ >= 5 && home_focus_ < 11 && home_focus_ - 5 >= recents)
                    home_focus_ = home_.last_exists ? 0 : (home_.setup_ready ? 1 : 2);
                if (home_focus_ == 4 && !home_.last_exists)
                    home_focus_ = 0;
            }
            if (modal_ == Modal::none)
                drop_missing_games(&missing);
        } catch (const std::exception &error) {
            previous_missing_.clear();
            sys::log("presence scan: %s", error.what());
        } catch (...) {
            previous_missing_.clear();
            sys::log("presence scan failed");
        }
        return;
    }

    std::vector<std::string> paths;
    if (screen_ == Screen::home && modal_ == Modal::none) {
        if (home_.last_exists && !home_.last_file.empty())
            paths.push_back(home_.last_file);
        for (const Recent &recent : home_.recents)
            if (!recent.file.empty())
                paths.push_back(recent.file);
    }
    if (modal_ == Modal::none && games_loaded_)
        for (const Game &game : games_)
            if (!game.file.empty())
                paths.push_back(game.file);
    if (paths.empty()) {
        previous_missing_.clear();
        home_missing_refresh_.clear();
        return;
    }
    std::sort(paths.begin(), paths.end());
    paths.erase(std::unique(paths.begin(), paths.end()), paths.end());
    presence_scan_ = std::async(std::launch::async,
        [this, paths = std::move(paths)] {
            std::vector<std::string> missing;
            // A temporarily unavailable ROM root (e.g. after a crash) must
            // not make every game appear deleted on two successive polls.
            // Check on this filesystem worker only, never on the UI frame.
            if (!services_.game_storage_available())
                return missing;
            for (const std::string &path : paths)
                if (!services_.game_exists(path))
                    missing.push_back(path);
            // The volume may unmount midway through this batch. A second
            // root check prevents a partial-I/O failure from evicting every
            // title even when the directory was accessible at the start.
            if (!services_.game_storage_available())
                missing.clear();
            return missing;
        });
}

bool Launcher::drop_missing_games(const std::vector<std::string>* known_missing)
{
    if (!games_loaded_)
        return false;
    const std::string selected =
        library_.selected >= 0 && library_.selected < static_cast<int>(games_.size()) ?
            games_[static_cast<std::size_t>(library_.selected)].file : std::string{};
    const auto gone = std::remove_if(games_.begin(), games_.end(),
        [this, known_missing](const Game &game) {
            // Input is sorted by set_intersection of two worker-sorted lists.
            // Binary search avoids O(game count * confirmed missing) scans.
            // Periodic background poll has already checked these paths.
            // Avoid repeating hundreds of filesystem calls on the UI thread.
            if (known_missing)
                return std::binary_search(known_missing->begin(), known_missing->end(), game.file);
            return !services_.game_exists(game.file);
        });
    if (gone == games_.end())
        return false;
    games_.erase(gone, games_.end());

    int index = std::min(library_.selected, std::max(0, static_cast<int>(games_.size()) - 1));
    for (int i = 0; i < static_cast<int>(games_.size()); ++i)
        if (games_[static_cast<std::size_t>(i)].file == selected)
            index = i;
    library_.reset(static_cast<int>(games_.size()), index);
    refresh_selected_game();
    name_home_games();
    return true;
}

void Launcher::count_mods(Game &game, const std::vector<Mod> &mods)
{
    game.mods = static_cast<int>(mods.size());
    // The game's Mods switch (the Library's) comes first: off, none of its mods is used, whatever
    // their own switches say.
    game.mods_enabled = mods.empty() || services_.mods_enabled(game.title_id);
    game.mods_on = !game.mods_enabled ? 0 : static_cast<int>(
        std::count_if(mods.begin(), mods.end(), [](const Mod &mod) { return mod.enabled; }));
    // The home screen says the same of its game.
    if (game.file == home_.last_file && home_.last_title_id != 0)
    {
        home_.last_mods = game.mods;
        home_.last_mods_on = game.mods_on;
    }
}

std::string Launcher::addons_line(const std::string &addons, int mods, int mods_on, bool brief)
{
    std::string line = addons;
    if (mods > 0)
    {
        // Mods that are switched off are still there: "1 of 2 mods on", or "1/2 mods" where there
        // is little room.
        const std::string count = std::to_string(mods);
        const char *counted = mods == 1 ? tr("{0} mod") : tr("{0} mods");
        line += (line.empty() ? "" : ", ") +
                (mods_on == mods ? fill(counted, {count}) :
                 brief ? fill(counted, {std::to_string(mods_on) + "/" + count}) :
                         fill(tr("{0} of {1} mods on"), {std::to_string(mods_on), count}));
    }
    return line.empty() ? std::string{tr("None")} : line;
}

std::string Launcher::hertz(int refresh)
{
    return fill(tr("{0} Hz"), {refresh == 1 ? "120" : "60"});
}

void Launcher::enter_library()
{
    // Library navigation must never block on game enumeration or a full
    // synchronous stat() sweep. The launcher constructor already starts the
    // initial scan; poll its completion here and let update() apply the result.
    // The normal periodic presence worker handles removals in the background.
    finish_scan(false);
    // Tab navigation must not rescan ROM/update/DLC trees. Reopening the
    // Library previously launched a fresh expensive flexible discovery on
    // every visit and briefly exposed a misleading empty-state. The owner
    // keeps its immutable last-good snapshot until an explicit refresh,
    // initial load, preferences change, or confirmed media removal.
    if (!games_loaded_ && !scan_.valid()) start_scan();
    library_.visible = 5;
    library_.pitch = 1.0f;
    library_back_focused_ = false;
    library_back_zoom_ = false;
    if (library_.count != static_cast<int>(games_.size()))
        library_.reset(static_cast<int>(games_.size()),
                       std::clamp(library_.selected, 0,
                                  std::max(0, static_cast<int>(games_.size()) - 1)));
    refresh_selected_game();
    detail_.snap(1.0f);
    mode_.snap(selected_docked_ ? 0.0f : 1.0f);
}

bool Launcher::open_game_settings_at_file(const std::string &file)
{
    if (!games_loaded_) {
        start_scan();
        finish_scan(false);
        if (!games_loaded_ && !scan_.valid()) {
            // A setup-disabled library cannot start a worker; avoid leaving
            // an impossible pending request that never resolves.
            say(tr("ROM missing from the game files folder"), true);
            cue(Cue::error);
            return false;
        }
        if (!games_loaded_) {
            // Home Triangle can arrive while first-time game enumeration is
            // still running. Never block a PS5 UI frame waiting for NACP,
            // updates, DLC or the mods scan; complete the request in update().
            pending_settings_file_ = file;
            return true;
        }
    }
    for (int i = 0; i < static_cast<int>(games_.size()); ++i)
    {
        Game &game = games_[static_cast<std::size_t>(i)];
        if (game.file != file) continue;
        if (game.title_id == 0)
        {
            say(tr("This game's settings cannot be saved (no title ID)."), true);
            cue(Cue::error);
            return false;
        }
        library_.reset(static_cast<int>(games_.size()), i);
        refresh_selected_game();
        game_settings_ = services_.game_settings(game.title_id);
        game_docked_ = selected_docked_;
        import_source_ = services_.save_transfer_available() ?
                             services_.save_import_source(game.title_id) : SaveSource::none;
        import_armed_ = false;
        mods_ = services_.mods(game.title_id);
        count_mods(game, mods_);
        open_modal(Modal::game);
        game_rows_.visible = kDialogRowsShown;
        game_rows_.pitch = kDialogRowPitch;
        game_rows_.reset(dialog_rows(Modal::game), 0);
        return true;
    }
    say(tr("ROM missing from the game files folder"), true);
    cue(Cue::error);
    return false;
}

void Launcher::refresh_selected_game()
{
    // Library selection can repeat at 9+ Hz. Never touch per-title/global
    // JSON files on the UI/input thread: the worker owns that snapshot.
    // The library scanner can complete while the selection is transitioning
    // from an empty/removed list. Invalid indices mean no active title, not
    // an unchecked vector access (especially -1 cast to a huge size_t).
    const bool has_selected = library_.selected >= 0 &&
        library_.selected < static_cast<int>(games_.size());
    selected_docked_ = !has_selected ||
        games_[static_cast<std::size_t>(library_.selected)].docked;
    // Its Mods switch shows its state at once; it only animates when changed.
    mods_switch_.snap(has_selected &&
                      games_[static_cast<std::size_t>(library_.selected)].mods_enabled ?
                          1.0f : 0.0f);
    detail_.value = 0.0f;
    detail_.velocity = 0.0f;
    start_selected_media();
}

void Launcher::press_library(Key key)
{
    if (library_back_zoom_) {
        if (key == Key::circle) {
            library_back_zoom_ = false;
            cue(Cue::back);
        } else if (key == Key::l2 || key == Key::r2) {
            const float old = library_back_scale_;
            const float factor = key == Key::r2 ? 1.30f : (1.0f / 1.30f);
            library_back_scale_ = std::clamp(old * factor, 1.0f, 3.4f);
            // Keep the same printed region under the viewer's centre.
            library_back_pan_x_ *= library_back_scale_ / old;
            library_back_pan_y_ *= library_back_scale_ / old;
            const float limit_x = std::max(0.0f, (500.0f * library_back_scale_ - 700.0f) * 0.5f);
            const float limit_y = std::max(0.0f, (807.0f * library_back_scale_ - 807.0f) * 0.5f);
            library_back_pan_x_ = std::clamp(library_back_pan_x_, -limit_x, limit_x);
            library_back_pan_y_ = std::clamp(library_back_pan_y_, -limit_y, limit_y);
            if (old != library_back_scale_)
                cue(Cue::focus);
        } else if (key == Key::left || key == Key::right ||
                   key == Key::up || key == Key::down) {
            // D-pad and the radio input's left-stick repeat share these keys.
            // Move the VIEW across the image, not the game selection below.
            constexpr float step = 68.0f;
            if (key == Key::left) library_back_pan_x_ += step;
            if (key == Key::right) library_back_pan_x_ -= step;
            if (key == Key::up) library_back_pan_y_ += step;
            if (key == Key::down) library_back_pan_y_ -= step;
            const float limit_x = std::max(0.0f, (500.0f * library_back_scale_ - 700.0f) * 0.5f);
            const float limit_y = std::max(0.0f, (807.0f * library_back_scale_ - 807.0f) * 0.5f);
            library_back_pan_x_ = std::clamp(library_back_pan_x_, -limit_x, limit_x);
            library_back_pan_y_ = std::clamp(library_back_pan_y_, -limit_y, limit_y);
        }
        return; // Circle alone closes; Cross cannot accidentally launch a game.
    }
    if (key != Key::left && key != Key::right && key != Key::cross && key != Key::options)
        clear_confirmation();
    const int count = static_cast<int>(games_.size());
    const Game *game = library_.selected >= 0 && library_.selected < count ?
        &games_[static_cast<std::size_t>(library_.selected)] : nullptr;
    switch (key)
    {
    case Key::circle:
        if (library_back_focused_) {
            library_back_focused_ = false;
            cue(Cue::back);
            return;
        }
        open(Screen::home, false);
        return;
    case Key::up:
        if (library_back_focused_) {
            library_back_focused_ = false;
            cue(Cue::focus);
            return;
        }
        top_nav_focus_ = 1;
        cue(Cue::focus);
        return;
    case Key::down:
        if (game != nullptr) {
            library_back_focused_ = true;
            cue(Cue::focus);
        }
        return;
    case Key::l1:
    case Key::r1:
        if (library_.page(key == Key::r1 ? 1 : -1))
        {
            message_.clear();
            refresh_selected_game();
            mode_.snap(selected_docked_ ? 0.0f : 1.0f);
            cue(Cue::page);
        }
        return;
    case Key::left:
    case Key::right:
        library_back_focused_ = false;
        if (library_.move(key == Key::right ? 1 : -1))
        {
            message_.clear();
            refresh_selected_game();
            mode_.snap(selected_docked_ ? 0.0f : 1.0f);
            cue(Cue::focus);
        }
        return;
    case Key::square:
    {
        // The Mods switch: all of the game's mods on or off at once. Their own switches (Game
        // settings > Mods) keep their state behind it.
        if (game == nullptr || game->title_id == 0 || game->mods == 0)
        {
            if (game != nullptr)
                cue(Cue::error);
            return;
        }
        Game &chosen = games_[static_cast<std::size_t>(library_.selected)];
        const bool saved = services_.set_mods_enabled(chosen.title_id, !chosen.mods_enabled);
        if (saved)
            count_mods(chosen, services_.mods(chosen.title_id));
        say(saved ? tr("Saved for this game. Applies on next launch.") :
                    tr("Could not save. Please try again."),
            !saved);
        cue(saved ? Cue::toggle : Cue::error);
        return;
    }
    case Key::triangle:
        if (game == nullptr)
            return;
        if (game->title_id == 0)
        {
            say(tr("This game's settings cannot be saved (no title ID)."), true);
            cue(Cue::error);
            return;
        }
        game_settings_ = services_.game_settings(game->title_id);
        game_docked_ = selected_docked_;
        import_source_ = services_.save_transfer_available() ?
                             services_.save_import_source(game->title_id) : SaveSource::none;
        import_armed_ = false;
        mods_ = services_.mods(game->title_id);
        count_mods(games_[static_cast<std::size_t>(library_.selected)], mods_);
        open_modal(Modal::game);
        game_rows_.visible = kDialogRowsShown;
        game_rows_.pitch = kDialogRowPitch;
        game_rows_.reset(dialog_rows(Modal::game), 0);
        return;
    case Key::options:
        if (game == nullptr || !home_.setup_ready)
        {
            cue(Cue::error);
            return;
        }
        services_.arm_safe_launch();
        say(tr("Safe launch: OpenGL, Handheld, 1x, 60 Hz, 1080p and mods off for this launch only."));
        launch(game->file, game->name, game->cover);
        return;
    case Key::cross:
        if (game != nullptr && library_back_focused_) {
            library_back_zoom_ = true;
            library_back_scale_ = 1.0f;
            library_back_pan_x_ = 0.0f;
            library_back_pan_y_ = 0.0f;
            cue(Cue::open);
            return;
        }
        if (game == nullptr || !home_.setup_ready)
        {
            cue(Cue::error);
            return;
        }
        launch(game->file, game->name, game->cover);
        return;
    default:
        return;
    }
}

void Launcher::draw_library(Canvas &c)
{
    gfx::DrawList &list = c.list;
    const int count = static_cast<int>(games_.size());
    draw_top_nav(c, 1, top_nav_focus_, top_nav_focus_ >= 0 ? 1.0f : 0.0f);
    text_shrink(c, tr("Your games"), 72.0f, baseline(142.0f, 38.0f, theme::kHeading),
                theme::kHeading, theme::kTitle, 980.0f);
    text_shrink(c, tr("Select a game to begin"), 72.0f, baseline(176.0f, 24.0f, 18.0f),
                18.0f, theme::kMeta, 1200.0f);
    text(c, list_position(count > 0 ? library_.selected + 1 : 0, count), 1848.0f,
         baseline(150.0f, 32.0f, theme::kSmall), theme::kSmall, theme::kLimePale, Align::right);

    // Five authentic portrait flat covers on a continuous shelf; no square
    // ROM thumbnails or 3D prefab images. The launcher handles depth alone.
    constexpr float rail_x = 72.0f, rail_y = 204.0f, rail_w = 1776.0f;
    constexpr float shelf_y = 551.0f;
    constexpr int slots = 5;
    constexpr float gap = 20.0f;
    constexpr float card_w = (rail_w - gap * (slots - 1)) / float(slots);
    constexpr float sleeve_h = 346.0f;
    list.shadow({rail_x + 3.0f, shelf_y, rail_w - 6.0f, 20.0f}, 9.0f,
                25.0f, theme::kScrim.with_alpha(0.65f));
    list.gradient_rect({rail_x, shelf_y, rail_w, 7.0f}, 3.0f,
                       theme::kPanelEdge.with_alpha(0.23f),
                       theme::kFocusCore.with_alpha(0.48f));
    if (!games_loaded_) {
        // First-ever discovery is pending. A zero-length interim vector
        // must never masquerade as an empty user ROM collection.
        text(c, tr("Loading game library..."), 960.0f,
             baseline(240.0f, 190.0f, theme::kText24), theme::kText24,
             theme::kCopy, Align::center);
    } else if (count == 0) {
        text(c, tr("No ROM files found."), 960.0f, baseline(240.0f, 190.0f, theme::kText24),
             theme::kText24, theme::kCopy, Align::center);
    } else {
        const int first = std::clamp(library_.selected - slots / 2, 0, std::max(0, count - slots));
        const int last = std::min(count, first + slots);
        for (int index = first; index < last; ++index) {
            const int slot = index - first;
            const Game& game = games_[static_cast<std::size_t>(index)];
            const bool selected = index == library_.selected;
            // Every case has the same retail silhouette. A decoded source
            // with a different aspect is contained INSIDE that case instead
            // of changing the jacket's height, width or anchor.
            const float sleeve_w = sleeve_h * kCaseShellAspect;
            const float x = rail_x + float(slot) * (card_w + gap) +
                            (card_w - sleeve_w) * 0.5f;
            const Rect sleeve{x, rail_y, sleeve_w, sleeve_h};
            // Focus changes the glow, not the dimensions of this case.
            list.push_transform(1.0f, x + sleeve_w * 0.5f,
                                rail_y + sleeve_h * 0.5f, 0.0f, 0.0f);
            list.shadow({x - 5.0f, rail_y - 4.0f, sleeve_w + 10.0f, sleeve_h + 13.0f},
                        8.0f, selected ? 30.0f : 17.0f,
                        theme::kScrim.with_alpha(0.72f));
            if (selected)
                list.shadow({x - 5.0f, rail_y - 4.0f, sleeve_w + 10.0f, sleeve_h + 9.0f},
                            8.0f, 28.0f, theme::kLime.with_alpha(0.30f));
            flat_retail_sleeve(c, game, sleeve, false, 0.24f);
            if (selected)
                list.bordered_rect(sleeve, 2.0f, theme::kGlass.with_alpha(0.0f),
                                   2.2f, theme::kFocusCore.with_alpha(0.93f));
            list.pop_transform();
            text_shrink(c, game.name, x + sleeve_w * 0.5f,
                        baseline(rail_y + sleeve_h + 6.0f, 24.0f, 16.0f),
                        16.0f, selected ? theme::kTitle : theme::kMeta,
                        card_w - 12.0f, Align::center);
        }
    }

    // ---- selected game: one clean detail surface, no hidden left/right setting changes ----
    const Game* game = count > 0 ? &games_[static_cast<std::size_t>(library_.selected)] : nullptr;
    // Give the large cover row, its captions and the details panel three
    // distinct bands instead of letting the bottom of the jackets touch glass.
    const Rect detail{72.0f, 620.0f, 1776.0f, 276.0f};
    glass(c, detail, 28.0f, theme::kGlass.with_alpha(0.66f),
          theme::kPanelEdge.with_alpha(0.58f), 0.9f);
    const float shown = tween::clamp01(detail_.value);
    list.push_opacity(shown);
    list.push_transform(1.0f, 0.0f, 0.0f, 0.0f, (1.0f - shown) * 10.0f * motion());

    if (game != nullptr)
    {
        // Actual rear retail scan, never the old panoramic screenshot.
        // Cross on this jacket opens a full-screen, aspect-preserving preview.
        // Rear detail has the exact same physical proportions as the
        // front shelf and the 3D launcher, regardless of retail scan.
        constexpr float rear_h = 247.0f;
        constexpr float rear_w = rear_h * kCaseShellAspect;
        const Rect art{280.0f - rear_w, 882.0f - rear_h, rear_w, rear_h};
        flat_retail_sleeve(c, *game, art, true, 0.60f);
        // The focus ring is UI feedback only. No white plastic bezel
        // is drawn around an unfocused square-corner paper cover.
        if (library_back_focused_)
            list.bordered_rect(art, 5.0f, theme::kGlass.with_alpha(0.0f),
                               2.5f, theme::kFocusCore);
        if (library_back_focused_)
            text_shrink(c, tr("Enlarge cover"), art.x + art.w * 0.5f,
                        baseline(880.0f, 16.0f, 13.0f), 15.0f,
                        theme::kLimePale, 224.0f, Align::center);
        // A two-line title previously overlapped the publisher/date and intro
        // (e.g. Breath of the Wild in French). Keep one readable, scaled line.
        text_shrink(c, game->name, 337.0f, baseline(633.0f, 52.0f, 40.0f),
                    40.0f, theme::kTitle, 1420.0f);

        std::string identity;
        if (!game->publisher.empty()) identity = game->publisher;
        else if (!game->developer.empty()) identity = game->developer;
        if (!game->release_date.empty()) {
            if (!identity.empty()) identity += "  ·  ";
            identity += library_date(game->release_date, services_.language_region(prefs_.language));
        }
        if (!game->categories.empty()) {
            if (!identity.empty()) identity += "  ·  ";
            identity += library_genres(game->categories);
        }
        if (!identity.empty())
            text_shrink(c, identity, 337.0f, baseline(687.0f, 24.0f, 17.0f), 17.0f,
                        theme::kLimePale, 1420.0f);

        if (!game->intro.empty())
            text_block(c, game->intro, 337.0f, baseline(711.0f, 24.0f, 18.0f), 18.0f, 25.0f,
                       theme::kCopy, 1420.0f, 2, kShrink);

        const std::string addons = addons_line(game->addons, game->mods, game->mods_on, true);
        const std::string mode = selected_docked_ ? tr("Docked") : tr("Handheld");
        const std::array<std::string, 5> chips{
            library_format(game->format),
            library_size(game->size),
            mode,
            game->language.empty() ? std::string{tr("Unknown")} : game->language,
            addons,
        };
        float chip_x = 337.0f;
        for (const auto& chip : chips)
        {
            const float w = std::clamp(text_width(c, chip, 15.0f) + 26.0f, 82.0f, 220.0f);
            list.bordered_rect({chip_x, 759.0f, w, 34.0f}, 17.0f,
                               theme::kPanel.with_alpha(0.54f), 1.0f,
                               theme::kPanelEdge.with_alpha(0.45f));
            text_shrink(c, chip, chip_x + w * 0.5f, baseline(759.0f, 34.0f, 15.0f), 15.0f,
                        theme::kLimePale, w - 18.0f, Align::center);
            chip_x += w + 9.0f;
            if (chip_x > 1760.0f) break;
        }

        // Nlib gameplay strip: three real screenshots at most; loaded lazily by Textures.
        constexpr float shot_y = 803.0f;
        constexpr float shot_h = 82.0f;
        constexpr float shot_w = 154.0f;
        constexpr float shot_gap = 12.0f;
        const int shot_count = std::min<int>(3, static_cast<int>(game->screenshots.size()));
        int shown_screens = 0;
        for (int i = 0; i < shot_count; ++i) {
            const std::string& path = game->screenshots[static_cast<std::size_t>(i)];
            const Cover image = c.textures.cover(path, shot_w);
            // Never reserve a blank, bordered thumbnail for an unreadable file.
            if (image.missing) continue;
            const Rect shot{337.0f + float(shown_screens) * (shot_w + shot_gap),
                            shot_y, shot_w, shot_h};
            cover_crop(c, path, shot, 12.0f, 0.18f);
            if (image.texture == 0)
                text_shrink(c, tr("Loading artwork"), shot.x + shot.w * 0.5f,
                            baseline(shot.y + 29.0f, 25.0f, 13.0f), 13.0f,
                            theme::kMuted, shot.w - 12.0f, Align::center);
            list.bordered_rect(shot, 12.0f, theme::kPanel.with_alpha(0.0f), 1.0f,
                               shown_screens == 0 ? theme::kLime.with_alpha(0.72f) :
                                                    theme::kPanelEdge.with_alpha(0.46f));
            ++shown_screens;
        }
        if (shown_screens == 0)
            text_shrink(c, tr("No screenshots available"), 337.0f,
                        baseline(shot_y + 20.0f, 32.0f, 16.0f), 16.0f,
                        theme::kMuted, 480.0f);

        if (game->mods > 0)
        {
            const float on = tween::clamp01(mods_switch_.value);
            toggle(c, 1792.0f, 778.0f, on);
            text_shrink(c, tr("Mods"), 1668.0f, baseline(759.0f, 40.0f, 18.0f),
                        18.0f, gfx::mix(theme::kMeta, theme::kLimePale, on), 100.0f, Align::right);
        }
    }
    else
    {
        text(c, tr("Select a game"), detail.x + detail.w * 0.5f,
             baseline(detail.y, detail.h, theme::kText24), theme::kText24, theme::kMeta, Align::center);
    }
    list.pop_transform();
    list.pop_opacity();

    static constexpr Hint kHints[] = {
        {Pad::leftright, TR("Browse games")}, {Pad::cross, TR("Launch game")},
        {Pad::triangle, TR("Game settings")}, {Pad::square, TR("Mods")},
        {Pad::options, TR("Safe launch")}, {Pad::circle, TR("Back")}};
    if (library_back_zoom_) {
        // An actual controller-operable overlay, not a static screenshot.
        list.rounded_rect({0.0f, 0.0f, 1920.0f, 1080.0f}, 0.0f,
                          theme::kScrim.with_alpha(0.96f));
        if (game != nullptr) {
            text_shrink(c, game->name, 960.0f, baseline(54.0f, 52.0f, 35.0f),
                        35.0f, theme::kTitle, 1580.0f, Align::center);
            // Tall portrait matching the printed paper: no wide 670px
            // stretched-looking pane in the full-screen back-cover popup.
            const Rect enlarged{960.0f - 807.0f * kCaseShellAspect * 0.5f,
                                111.0f, 807.0f * kCaseShellAspect, 807.0f};
            // Stable 700x807 viewport. Scale the original sleeve uniformly,
            // then pan beneath a screen-fixed clip; never scale X/Y separately.
            const Rect viewer{610.0f, 111.0f, 700.0f, 807.0f};
            list.push_clip(viewer);
            list.push_transform(library_back_scale_, 960.0f, 514.5f,
                                library_back_pan_x_, library_back_pan_y_);
            flat_retail_sleeve(c, *game, enlarged, true, 0.92f,
                               library_back_scale_);
            list.pop_transform();
            list.pop_clip();
            text_shrink(c, std::to_string(static_cast<int>(library_back_scale_ * 100.0f + 0.5f)) + "%",
                        1340.0f, baseline(140.0f, 34.0f, 20.0f),
                        20.0f, theme::kLimePale, 110.0f, Align::left);
        }
        static constexpr Hint kZoomHints[] = {
            {Pad::circle, TR("Close")}, {Pad::l2, TR("Zoom out")},
            {Pad::r2, TR("Zoom in")}, {Pad::dpad, TR("Move cover")}};
        draw_footer(c, kZoomHints, 4);
    } else if (library_back_focused_) {
        static constexpr Hint kBackHints[] = {{Pad::cross, TR("Enlarge cover")},
                                             {Pad::updown, TR("Browse games")},
                                             {Pad::circle, TR("Back")}};
        draw_footer(c, kBackHints, 3);
    } else {
        // A lone text instruction below the details panel looked like
        // misplaced metadata. The Down key still focuses the rear cover.
        draw_footer(c, kHints, 6);
    }
}

void Launcher::press_game(Key key)
{
    // The async ROM scan can replace the library during a Triangle dialog.
    if (library_.selected < 0 ||
        static_cast<std::size_t>(library_.selected) >= games_.size()) {
        close_modal();
        cue(Cue::error);
        return;
    }
    Game &game = games_[static_cast<std::size_t>(library_.selected)];
    const bool mode_confirmation =
        option_ == row_mode && (key == Key::left || key == Key::right || key == Key::cross);
    if (key != Key::triangle && !mode_confirmation)
        clear_confirmation();
    if (key == Key::triangle && option_ >= row_renderer && option_ <= row_controls)
    {
        if (!confirm_action(Confirmation::game_overrides))
            return;
        const GameSettings reset{};
        const bool saved = services_.set_game_settings(game.title_id, reset);
        if (saved) {
            game_settings_ = reset;
            home_settings_cache_.erase(game.title_id);
            game_docked_ = services_.docked(game.title_id);
            game.docked = game_docked_;
            selected_docked_ = game_docked_;
            if (scan_.valid()) docked_refresh_after_scan_ = true;
        }
        say(saved ? tr("Game overrides reset to global defaults.") :
                    tr("Could not save. Please try again."),
            !saved);
        cue(saved ? Cue::saved : Cue::error);
        return;
    }
    switch (key)
    {
    case Key::circle:
        close_modal();
        selected_docked_ = game_docked_;
        return;
    case Key::up:
    case Key::down:
    case Key::l1:
    case Key::r1:
        if (game_rows_.move(key == Key::down || key == Key::r1 ? 1 : -1))
        {
            option_ = game_rows_.selected;
            message_.clear();
            import_armed_ = false;
            cue(Cue::focus);
        }
        return;
    case Key::square:
        if (option_ != row_save)
            return;
        break;
    case Key::left:
    case Key::right:
    case Key::cross:
        break;
    default:
        return;
    }
    if (option_ == row_controls)
    {
        if (key == Key::cross) {
            // Cross opens the full button-by-button editor; arrows set a
            // standard title-only profile as on PC emulators.
            open_mapping(true);
            return;
        }
        if (key == Key::left || key == Key::right) {
            GameSettings next = game_settings_;
            // -1 = inherit global; 0 = PlayStation fixed; 1 = Nintendo
            // physical positions. Cycling to a base profile discards only
            // this title's old custom mapping; all global settings stay.
            constexpr std::array profiles{-1, 0, 1};
            const int index = next.controller_layout < 0 ? 0 :
                next.controller_layout == 0 ? 1 : 2;
            const int delta = key == Key::right ? 1 : 2;
            next.controller_layout = profiles[static_cast<std::size_t>((index + delta) % 3)];
            next.own_mapping = false;
            next.mapping = next.controller_layout >= 0 ?
                Eden::BaseMappingForLayout(next.controller_layout) : prefs_.mapping;
            const bool saved = services_.set_game_settings(game.title_id, next);
            if (saved) {
                game_settings_ = next;
                home_settings_cache_.erase(game.title_id);
            }
            say(saved ? tr("Saved for this game. Applies on next launch.") :
                        tr("Could not save. Please try again."), !saved);
            cue(saved ? Cue::toggle : Cue::error);
        }
        return;
    }
    if (option_ == row_mods)
    {
        // The game's mods have their own list. It is read again: mods may have been copied in
        // since this dialog opened.
        if (key != Key::cross)
            return;
        mods_ = services_.mods(game.title_id);
        count_mods(game, mods_);
        mod_rows_.visible = kDialogRowsShown;
        mod_rows_.pitch = kDialogRowPitch;
        mod_rows_.reset(static_cast<int>(mods_.size()), 0);
        modal_ = modal_shown_ = Modal::mods;
        message_.clear();
        cue(Cue::open);
        return;
    }
    if (option_ == row_save)
    {
        // Save data: Square copies the game's save out, Cross (twice) copies one in.
        std::string result;
        if (key == Key::square)
        {
            import_armed_ = false;
            const bool exported = services_.save_export(game.title_id, &result);
            say(result, !exported);
            cue(exported ? Cue::saved : Cue::error);
        }
        else if (key != Key::cross)
        {
            cue(Cue::error);
        }
        else if (import_source_ != SaveSource::none && !import_armed_)
        {
            // Importing replaces the save in use, so it asks first.
            import_armed_ = true;
            say(tr("Press again to replace this game's save. The current one is backed up."), true);
            cue(Cue::notify);
        }
        else
        {
            // With nothing to import the answer says where a save has to be put.
            import_armed_ = false;
            const bool imported = services_.save_import(game.title_id, &result);
            say(result, !imported && import_source_ != SaveSource::none);
            cue(imported ? Cue::saved : import_source_ != SaveSource::none ? Cue::error : Cue::notify);
        }
        return;
    }
    const int step = key == Key::left ? -1 : 1;
    bool saved = false;
    if (option_ == row_mode)
    {
        if (!confirm_action(Confirmation::console_mode))
            return;
        GameSettings next = game_settings_;
        next.console_mode = game_docked_ ? 0 : 1;
        RefreshVideoProfile(next, prefs_, game.title_id);
        saved = services_.set_game_settings(game.title_id, next);
        if (saved) {
            game_settings_ = next;
            home_settings_cache_.erase(game.title_id);
            game_docked_ = next.console_mode == 1;
            game.docked = game_docked_;
            if (scan_.valid()) docked_refresh_after_scan_ = true;
        }
    }
    else
    {
        // Default (-1), then each value.
        const auto cycle = [step](int value, int count)
        { return (value + 1 + step + count + 1) % (count + 1) - 1; };
        GameSettings next = game_settings_;
        if (option_ == row_renderer)
        {
            next.renderer = cycle(next.renderer, 2);
            RefreshVideoProfile(next, prefs_, game.title_id);
        }
        if (option_ == row_performance)
        {
            int preset = -1;
            if (next.performance_profile == kCustomVideoProfile)
                preset = step > 0 ? -1 : 3;
            else
                preset = cycle(next.performance_profile, 4);
            if (preset >= 0) {
                ApplyVideoPreset(next, preset, game.title_id);
            } else {
                // Returning the preset to Default also returns the settings the preset owns to
                // the global values; otherwise "Default" would silently keep old overrides.
                next.performance_profile = -1;
                next.console_mode = -1;
                next.renderer = -1;
                next.output = -1;
                next.resolution = -1;
                next.filter = -1;
                next.fsr_sharpness = -1;
                next.anti_aliasing = -1;
                next.refresh = -1;
            }
        }
        if (option_ == row_output)
        {
            next.output = cycle(next.output, 3);
            RefreshVideoProfile(next, prefs_, game.title_id);
        }
        if (option_ == row_resolution)
        {
            next.resolution =
                cycle(next.resolution, static_cast<int>(services_.resolution_labels().size()));
            RefreshVideoProfile(next, prefs_, game.title_id);
        }
        if (option_ == row_filter)
        {
            next.filter = cycle(next.filter, static_cast<int>(services_.filter_labels().size()));
            RefreshVideoProfile(next, prefs_, game.title_id);
        }
        if (option_ == row_fsr_sharpness) {
            const int current = next.fsr_sharpness >= 0 ? next.fsr_sharpness : prefs_.fsr_sharpness;
            next.fsr_sharpness = std::clamp(current + 5 * step, 0, 100);
            RefreshVideoProfile(next, prefs_, game.title_id);
        }
        if (option_ == row_anti_aliasing)
        {
            next.anti_aliasing = cycle(next.anti_aliasing, static_cast<int>(services_.anti_aliasing_labels().size()));
            RefreshVideoProfile(next, prefs_, game.title_id);
        }
        if (option_ == row_refresh)
        {
            next.refresh = cycle(next.refresh, 2);
            RefreshVideoProfile(next, prefs_, game.title_id);
        }
        saved = services_.set_game_settings(game.title_id, next);
        if (saved) {
            game_settings_ = next;
            home_settings_cache_.erase(game.title_id);
            game_docked_ = next.console_mode >= 0 ? next.console_mode == 1 : services_.docked(game.title_id);
            game.docked = game_docked_;
            if (scan_.valid()) docked_refresh_after_scan_ = true;
        }
    }
    // 120 Hz is a request: the display has the last word.
    const bool fast = saved && option_ == row_refresh &&
                      (game_settings_.refresh >= 0 ? game_settings_.refresh : prefs_.refresh) == 1;
    say(fast ? tr("Saved. A display that cannot show 120 Hz stays at 60 Hz.") :
        saved ? tr("Saved for this game. Applies on next launch.") : tr("Could not save. Please try again."),
        !saved);
    cue(saved ? Cue::toggle : Cue::error);
}

void Launcher::draw_game(Canvas &c, float open)
{
    gfx::DrawList &list = c.list;
    list.push_opacity(open);
    list.push_transform(1.0f - 0.03f * (1.0f - open) * motion(), 960.0f, 540.0f, 0.0f,
                        (1.0f - open) * 26.0f * motion());
    glass(c, kDialog, 26.0f, theme::kPanel.with_alpha(0.97f), theme::kPanelEdge.with_alpha(0.66f),
          1.6f);
    text_shrink(c, tr("Game settings"), 592.0f, baseline(218.0f, 62.0f, theme::kDisplay),
                theme::kDisplay, theme::kTitle, 736.0f);
    const Game *game = library_.selected >= 0 &&
        static_cast<std::size_t>(library_.selected) < games_.size() ?
        &games_[static_cast<std::size_t>(library_.selected)] : nullptr;
    text_fit(c, game != nullptr ? game->name : std::string{}, 592.0f,
             baseline(291.0f, 32.0f, theme::kSmall), theme::kSmall, Color::rgb(0xc5c1d2), 736.0f);

    static constexpr const char *kRenderers[] = {"OpenGL", "Vulkan"};
    const auto &resolutions = services_.resolution_labels();
    // A resolution's short name is how its label starts: "0.5x (faster, softer)" is "0.5x".
    const auto short_resolution = [](const std::string &label)
    { return label.substr(0, label.find(' ')); };
    const auto &filters = services_.filter_labels();
    const auto &anti_aliasing = services_.anti_aliasing_labels();
    static constexpr const char *kOutputs[] = {"1080p", "1440p", "2160p"};
    const auto pick = [](const std::vector<std::string> &values, int index) -> std::string
    {
        return index >= 0 && index < static_cast<int>(values.size()) ?
                   values[static_cast<std::size_t>(index)] : std::string{"-"};
    };
    const auto percentage = [](int value) {
        return fill(tr("{0}%"), {std::to_string(value)});
    };
    const std::uint64_t title_id = game != nullptr ? game->title_id : 0;
    const bool authored_global = prefs_.performance_profile >= 0 &&
                                 prefs_.performance_profile < kAuthoredVideoProfiles;
    const auto& base_profile = VideoPresetForTitle(title_id,
        authored_global ? prefs_.performance_profile : 1);
    const int base_renderer = authored_global ? base_profile.renderer : prefs_.renderer;
    const int base_output = authored_global ? base_profile.output : prefs_.output;
    const int base_resolution = authored_global ? base_profile.resolution : prefs_.resolution;
    const int base_filter = authored_global ? base_profile.filter : prefs_.filter;
    const int base_fsr = authored_global ? base_profile.fsr_sharpness : prefs_.fsr_sharpness;
    const int base_aa = authored_global ? base_profile.anti_aliasing : prefs_.anti_aliasing;
    const int base_refresh = authored_global ? base_profile.refresh : prefs_.refresh;
    const std::string values[] = {
        game_docked_ ? tr("Docked") : tr("Handheld"),
        game_settings_.renderer >= 0 ? kRenderers[game_settings_.renderer] :
            fill(tr("Default ({0})"), {kRenderers[base_renderer != 0 ? 1 : 0]}),
        game_settings_.performance_profile >= 0 ?
            services_.performance_profile_labels()[static_cast<std::size_t>(game_settings_.performance_profile)] :
            fill(tr("Default ({0})"), {services_.performance_profile_labels()[static_cast<std::size_t>(std::clamp(prefs_.performance_profile, 0, kCustomVideoProfile))]}),
        game_settings_.output >= 0 ? kOutputs[game_settings_.output] :
            fill(tr("Default ({0})"), {kOutputs[std::clamp(base_output, 0, 2)]}),
        game_settings_.resolution >= 0 ? pick(resolutions, game_settings_.resolution) :
            fill(tr("Default ({0})"), {short_resolution(pick(resolutions, base_resolution))}),
        game_settings_.filter >= 0 ? pick(filters, game_settings_.filter) :
            fill(tr("Default ({0})"), {pick(filters, base_filter)}),
        game_settings_.fsr_sharpness >= 0 ? percentage(game_settings_.fsr_sharpness) :
            fill(tr("Default ({0})"), {percentage(base_fsr)}),
        game_settings_.anti_aliasing >= 0 ? pick(anti_aliasing, game_settings_.anti_aliasing) :
            fill(tr("Default ({0})"), {pick(anti_aliasing, base_aa)}),
        game_settings_.refresh >= 0 ? hertz(game_settings_.refresh) :
            fill(tr("Default ({0})"), {hertz(base_refresh)}),
        game_settings_.own_mapping ?
            controller_profile_name(game_settings_.controller_layout >= 0 ?
                                        game_settings_.controller_layout : prefs_.controller_layout,
                                    game_settings_.mapping) :
        game_settings_.controller_layout >= 0 ?
            controller_profile_name(game_settings_.controller_layout,
                                    Eden::BaseMappingForLayout(game_settings_.controller_layout)) :
            fill(tr("Global ({0})"),
                 {controller_profile_name(prefs_.controller_layout, prefs_.mapping)}),
        // With the game's Mods switch off (the Library's), none of them is on.
        mods_.empty() ? std::string{tr("No mods")} :
        game != nullptr && !game->mods_enabled ? std::string{tr("Off")} :
            fill(tr("{0} of {1} on"),
                 {std::to_string(std::count_if(mods_.begin(), mods_.end(),
                                               [](const Mod &mod) { return mod.enabled; })),
                  std::to_string(mods_.size())}),
        import_source_ == SaveSource::ryujinx ? tr("Ryujinx save found") :
        import_source_ == SaveSource::folder ? tr("Save folder found") : tr("Nothing to import"),
    };
    static constexpr const char *kLabels[] = {
        TR("Console mode"), TR("Renderer"), TR("Video preset"), TR("TV output"),
        TR("Resolution"), TR("Upscaling filter"), TR("FSR sharpness"), TR("Anti-aliasing"),
        TR("Refresh rate"), TR("Button mapping"), TR("Mods"), TR("Save data")};
    // Five rows show; the list scrolls to the others.
    list.push_clip({kDialogWindow.x - 24.0f, kDialogWindow.y - 6.0f, kDialogWindow.w + 48.0f,
                    kDialogWindow.h + 12.0f});
    const auto row_top = [&](int row)
    { return kDialogRowsTop + static_cast<float>(row) * kDialogRowPitch - game_rows_.scroll(); };
    for (int row = game_rows_.first_row(); row <= game_rows_.last_row(); ++row)
    {
        list.push_opacity(game_rows_.row_alpha(row, kDialogRowHeight));
        plate_rest(c, kRowPlate, {592.0f, row_top(row), 736.0f, kDialogRowHeight});
        list.pop_opacity();
    }
    plate_focus(c, kRowPlate,
                {592.0f, kDialogRowsTop + game_rows_.cursor() - game_rows_.scroll(), 736.0f,
                 kDialogRowHeight},
                1.0f);
    for (int row = game_rows_.first_row(); row <= game_rows_.last_row(); ++row)
    {
        const float top = row_top(row);
        const float focus = row == option_ ? 1.0f : 0.0f;
        list.push_opacity(game_rows_.row_alpha(row, kDialogRowHeight));
        // The value first: the row's name takes what it leaves. Mods and Save data say what is
        // there; the others are choices.
        const bool there = row == row_mods ? !mods_.empty() && (game == nullptr || game->mods_enabled) :
                                             import_source_ != SaveSource::none;
        const float taken =
            row >= row_mods ?
                text_shrink(c, values[row], 1292.0f, baseline(top, kDialogRowHeight, theme::kSmall),
                            theme::kSmall, there ? theme::kLimePale : theme::kMeta, 320.0f,
                            Align::right) :
                chooser(c, values[row], 1296.0f, baseline(top, kDialogRowHeight, theme::kText24),
                        focus, theme::kLimePale);
        text_shrink(c, tr(kLabels[row]), 628.0f, baseline(top, kDialogRowHeight, theme::kText24),
                    theme::kText24, theme::kValue, 664.0f - taken - 28.0f);
        list.pop_opacity();
    }
    list.pop_clip();
    scrollbar(c, game_rows_, 1340.0f, kDialogWindow.y, kDialogWindow.h);

    if (!message_.empty())
    {
        // Up to two lines: what Save data answers is longer than a "Saved".
        notice_block(c, message_, 592.0f, kDialogHints - 6.0f, theme::kSmall, 26.0f,
                     message_warning_ ? theme::kWarning : theme::kLimePale, 736.0f, 2,
                     message_warning_);
    }
    else if (option_ == row_save)
    {
        static constexpr Hint kTransfer[] = {{Pad::cross, TR("Import")},
                                             {Pad::square, TR("Export a copy")},
                                             {Pad::circle, TR("Back")}};
        draw_hints(c, kTransfer, 3, 592.0f, kDialogHints, theme::kCopy, 736.0f);
    }
    else if (option_ == row_controls)
    {
        text_shrink(c, tr("Left/right: Global, PlayStation or Switch for this game; Cross: edit individual buttons."),
                    592.0f, baseline(kDialogHints - 35.0f, 22.0f, 16.0f), 16.0f,
                    theme::kMeta, 736.0f);
        static constexpr Hint kControls[] = {
            {Pad::leftright, TR("Change")}, {Pad::cross, TR("Open")},
            {Pad::circle, TR("Back")}};
        draw_hints(c, kControls, 3, 592.0f, kDialogHints + 12.0f, theme::kCopy, 736.0f);
    }
    else if (option_ == row_mods)
    {
        static constexpr Hint kOpen[] = {{Pad::cross, TR("Open")}, {Pad::circle, TR("Back")}};
        draw_hints(c, kOpen, 2, 592.0f, kDialogHints, theme::kCopy, 736.0f);
    }
    else
    {
        // One description per editable game row. The former seven-entry table
        // was read with option_ up to row_controls (index 9), causing an
        // out-of-bounds read / SIGSEGV when scrolling to the bottom.
        static constexpr std::array<const char*, row_mods> kGameAbout = {{
            TR("Docked can improve graphics but may cost performance; Handheld is lighter for demanding games."),
            TR("Vulkan is recommended on PS5. Use OpenGL only as a fallback for a title with Vulkan issues."),
            TR("Minimum, Recommended, High and Ultra apply the title-aware Encore profile. Manual changes become Custom for this game."),
            TR("Final app output size. Choose 1080p for lower memory use, 1440p for balance, or 2160p for maximum output detail."),
            TR("Resolution follows the selected title-aware profile. Lower it for performance or memory; raise it only when the title has headroom."),
            TR("Bilinear is the lightest default. AMD FSR is useful when rendering below the TV output size."),
            TR("FSR sharpness changes detail recovery only when AMD FSR is selected. Lower it if the picture looks grainy or over-sharpened."),
            TR("Anti-aliasing smooths jagged edges. None is fastest; FXAA is light; SMAA prioritizes image quality."),
            TR("60 Hz is the safe default. Use 120 Hz only with a compatible display or high-FPS patch."),
            TR("Open the per-game DualSense mapping. Global uses Settings > Controls; Custom overrides it only for this game."),
        }};
        static_assert(kGameAbout.size() == static_cast<std::size_t>(row_mods));
        if (option_ >= row_mode && option_ < static_cast<int>(kGameAbout.size()))
            text_shrink(c, tr(kGameAbout[static_cast<std::size_t>(option_)]), 592.0f,
                        baseline(kDialogHints - 34.0f, 24.0f, 18.0f), 18.0f,
                        theme::kMeta, 736.0f);
        static constexpr Hint kHints[] = {
            {Pad::updown, TR("Select")}, {Pad::leftright, TR("Change")},
            {Pad::triangle, TR("Reset overrides")}, {Pad::circle, TR("Back")}};
        draw_hints(c, kHints, 4, 592.0f, kDialogHints + 12.0f, theme::kCopy, 736.0f);
    }
    list.pop_transform();
    list.pop_opacity();
}

// ---------------------------------------------------------------- a game's mods

void Launcher::press_mods(Key key)
{
    Game &game = games_[static_cast<std::size_t>(library_.selected)];
    switch (key)
    {
    case Key::circle:
        // Back to the game's settings, on its Mods row.
        modal_ = modal_shown_ = Modal::game;
        message_.clear();
        cue(Cue::back);
        return;
    case Key::up:
    case Key::down:
    case Key::l1:
    case Key::r1:
        if (mod_rows_.move(key == Key::down || key == Key::r1 ? 1 : -1))
        {
            message_.clear();
            cue(Cue::focus);
        }
        return;
    case Key::square:
    {
        // With no mods yet: the folder they go in, named after the game's ID, is made on request.
        if (!mods_.empty())
            return;
        const bool made = services_.make_mods_folder(game.title_id);
        say(made ? fill(tr("Created {0}. Copy each mod's folder into it."),
                        {services_.mods_folder(game.title_id)}) :
                   tr("Could not create the folder. Check that the game files folder can be written."),
            !made);
        cue(made ? Cue::saved : Cue::error);
        return;
    }
    case Key::cross:
    case Key::left:
    case Key::right:
    {
        if (mods_.empty())
            return;
        Mod &mod = mods_[static_cast<std::size_t>(mod_rows_.selected)];
        // With the game's Mods switch off (the Library's), choosing a mod turns the switch on and
        // that mod with it: nobody switches a mod in a list that is switched off.
        const bool revive = !game.mods_enabled;
        const bool enabled = revive || !mod.enabled;
        const bool saved = (!revive || services_.set_mods_enabled(game.title_id, true)) &&
                           services_.set_mod_enabled(game.title_id, mod.name, enabled);
        if (saved)
            mod.enabled = enabled;
        count_mods(game, mods_);
        say(saved ? tr("Saved for this game. Applies on next launch.") :
                    tr("Could not save. Please try again."),
            !saved);
        cue(saved ? Cue::toggle : Cue::error);
        return;
    }
    default:
        return;
    }
}

void Launcher::draw_mods(Canvas &c, float open)
{
    gfx::DrawList &list = c.list;
    list.push_opacity(open);
    list.push_transform(1.0f - 0.03f * (1.0f - open) * motion(), 960.0f, 540.0f, 0.0f,
                        (1.0f - open) * 26.0f * motion());
    glass(c, kDialog, 26.0f, theme::kPanel.with_alpha(0.97f), theme::kPanelEdge.with_alpha(0.66f),
          1.6f);
    text_shrink(c, tr("Mods"), 592.0f, baseline(218.0f, 62.0f, theme::kDisplay), theme::kDisplay,
                theme::kTitle, 736.0f);
    const Game *game = games_.empty() ? nullptr : &games_[static_cast<std::size_t>(library_.selected)];
    text_fit(c, game != nullptr ? game->name : std::string{}, 592.0f,
             baseline(291.0f, 32.0f, theme::kSmall), theme::kSmall, Color::rgb(0xc5c1d2), 736.0f);

    if (mods_.empty())
    {
        text_block(c,
                   fill(tr("No mods for this game yet. Copy each mod's folder to {0}, next to roms/."),
                        {game != nullptr ? services_.mods_folder(game->title_id) : std::string{}}),
                   592.0f, baseline(364.0f, 40.0f, theme::kText24), theme::kText24, 40.0f,
                   theme::kBody, 736.0f, 5, kShrink);
    }
    else
    {
        list.push_clip({kDialogWindow.x - 24.0f, kDialogWindow.y - 6.0f, kDialogWindow.w + 48.0f,
                        kDialogWindow.h + 12.0f});
        const auto row_top = [&](int row)
        { return kDialogRowsTop + static_cast<float>(row) * kDialogRowPitch - mod_rows_.scroll(); };
        for (int row = mod_rows_.first_row(); row <= mod_rows_.last_row(); ++row)
        {
            list.push_opacity(mod_rows_.row_alpha(row, kDialogRowHeight));
            plate_rest(c, kRowPlate, {592.0f, row_top(row), 736.0f, kDialogRowHeight});
            list.pop_opacity();
        }
        plate_focus(c, kRowPlate,
                    {592.0f, kDialogRowsTop + mod_rows_.cursor() - mod_rows_.scroll(), 736.0f,
                     kDialogRowHeight},
                    1.0f);
        // With the game's Mods switch off (the Library's) no mod is used: their own switches keep
        // their state, drawn faint.
        const bool live = game == nullptr || game->mods_enabled;
        for (int row = mod_rows_.first_row(); row <= mod_rows_.last_row(); ++row)
        {
            const Mod &mod = mods_[static_cast<std::size_t>(row)];
            const float top = row_top(row);
            list.push_opacity(mod_rows_.row_alpha(row, kDialogRowHeight));
            // Its name as the player's folder has it, what it changes under it, its switch.
            text_fit(c, mod.name, 628.0f, baseline(top + 14.0f, 38.0f, theme::kText24),
                     theme::kText24, mod.enabled && live ? theme::kValue : theme::kMeta, 560.0f);
            text_shrink(c, mod.kind, 628.0f, baseline(top + 52.0f, 28.0f, theme::kSmall),
                        theme::kSmall, theme::kMeta, 560.0f);
            list.push_opacity(live ? 1.0f : 0.4f);
            toggle(c, 1292.0f, top + kDialogRowHeight * 0.5f, mod.enabled ? 1.0f : 0.0f);
            list.pop_opacity();
            list.pop_opacity();
        }
        list.pop_clip();
        scrollbar(c, mod_rows_, 1340.0f, kDialogWindow.y, kDialogWindow.h);
    }

    if (!message_.empty())
    {
        notice_block(c, message_, 592.0f, kDialogHints - 6.0f, theme::kSmall, 26.0f,
                     message_warning_ ? theme::kWarning : theme::kLimePale, 736.0f, 2,
                     message_warning_);
    }
    else if (mods_.empty())
    {
        static constexpr Hint kEmpty[] = {{Pad::square, TR("Create the folder")},
                                          {Pad::circle, TR("Back")}};
        draw_hints(c, kEmpty, 2, 592.0f, kDialogHints, theme::kCopy, 736.0f);
    }
    else
    {
        static constexpr Hint kHints[] = {{Pad::updown, TR("Select")},
                                          {Pad::cross, TR("Turn on or off")},
                                          {Pad::circle, TR("Back")}};
        draw_hints(c, kHints, 3, 592.0f, kDialogHints, theme::kCopy, 736.0f);
    }
    list.pop_transform();
    list.pop_opacity();
}

} // namespace pe::ui
