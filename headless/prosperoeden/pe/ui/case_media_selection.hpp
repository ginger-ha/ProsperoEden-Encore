// Eden Encore — deterministic selection for procedurally composed case art.
// Only real, already-cached media is eligible. No external source fetches,
// guessed screenshots, duplicates or allocated copies in the draw loop.
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <array>
#include <string>
#include <string_view>
#include <vector>

namespace pe::ui::case_media {

// The front uses an edge-to-edge source: hero, first usable screenshot,
// finally the icon. All cases preserve the source's aspect via cover UVs.
inline const std::string* FrontPaper(
    const std::string& featured, const std::string& cover,
    const std::vector<std::string>& screenshots) noexcept
{
    if (!featured.empty()) return &featured;
    for (const auto& shot : screenshots)
        if (!shot.empty()) return &shot;
    return cover.empty() ? nullptr : &cover;
}

// Skip only confirmed missing image sources, never a pending async decode.
// Both NS1 and NS2 share this full-paper fallback with no fabricated media.
template <typename Usable>
inline const std::string* FrontPaperAvailable(
    const std::string& featured, const std::string& cover,
    const std::vector<std::string>& screenshots, Usable&& usable)
{
    if (!featured.empty() && usable(featured)) return &featured;
    for (const auto& shot : screenshots)
        if (!shot.empty() && usable(shot)) return &shot;
    return !cover.empty() && usable(cover) ? &cover : nullptr;
}

// Front: choose the first genuine alternate scene, not a duplicate of
// the feature image. Fall back to an independent cached app icon/poster.
inline const std::string* FrontAlternate(
    const std::string& featured, const std::string& cover,
    const std::vector<std::string>& screenshots) noexcept
{
    for (const auto& shot : screenshots) {
        if (!shot.empty() && shot != featured)
            return &shot;
    }
    return !cover.empty() && cover != featured ? &cover : nullptr;
}

// Rear source priorities: LaunchBox fanart, game-title screenshot, gameplay.
// Missing categories use distinct Nlib screenshots; the cover/front is never
// injected as a floating square. Results reference owned game metadata.
template <typename Usable>
inline std::array<const std::string*, 3> BackScenes(
    const std::string& featured, const std::string& cover,
    const std::vector<std::string>& screenshots, Usable&& usable)
{
    std::array<const std::string*, 3> selected{nullptr, nullptr, nullptr};
    // If there is no Hero, the front uses the first cached screenshot.
    // Exclude that *actual* front paper too: previously the same image
    // could be copied onto the rear panel as an independent scene.
    // The hero may exist as a file but fail decoding. Exclude the image
    // actually admitted as front paper, not the raw first filename. The
    // caller may supply the original hero or an already-resolved fallback.
    const std::string* const front =
        FrontPaperAvailable(featured, cover, screenshots, usable);
    const auto is_front = [&](const std::string& image) {
        return front && *front == image;
    };
    const auto accept = [&](const std::string& image) {
        if (image.empty() || image == cover || is_front(image) || !usable(image)) return;
        for (const auto* existing : selected)
            if (existing && *existing == image) return;
        for (auto& entry : selected)
            if (!entry) { entry = &image; return; }
    };
    // These canonical local filenames are built by EnsureRetailCase; unlike
    // arbitrary Nlib screenshots they identify three actual media categories.
    // Category matching must not allocate three temporary strings per draw.
    // Keep indexed media in its OWN slot even when other categories are absent:
    // [0] fanart full-paper backdrop, [1] title capture, [2] gameplay.
    constexpr std::array<std::string_view, 3> kSceneMarkers{
        "/box-scene-1-", "/box-scene-2-", "/box-scene-3-"};
    for (std::size_t category = 0; category < kSceneMarkers.size(); ++category) {
        for (const auto& image : screenshots) {
            if (image.find(kSceneMarkers[category]) == std::string::npos ||
                image == cover || is_front(image) || !usable(image)) continue;
            selected[category] = &image;
            break;
        }
    }
    // Existing Nlib captures can fill missing roles, but an indexed game-title
    // screenshot must never masquerade as fanart merely because fanart failed.
    for (const auto& image : screenshots) {
        if (image.find("/box-scene-") != std::string::npos) continue;
        accept(image);
    }
    return selected;
}

// The ordinary source-only selector retains its original three-argument API.
// The renderer may additionally reject confirmed-bad asynchronous images
// without temporary vectors, changing the back's category mapping or
// triggering a network fetch.
inline std::array<const std::string*, 3> BackScenes(
    const std::string& featured, const std::string& cover,
    const std::vector<std::string>& screenshots) noexcept
{
    return BackScenes(featured, cover, screenshots,
                      [](const std::string&) noexcept { return true; });
}

// One-shot fallback after a short media warm-up is allowed only for a NEW
// page. Never rebake an existing provisional page with still-missing artwork;
// doing so would both waste GPU work and permanently hide the late image.
inline bool PageInputReady(bool existing_page, bool inputs_ready,
                           float launch_seconds) noexcept
{
    return inputs_ready || (!existing_page && launch_seconds >= 4.0f);
}

} // namespace pe::ui::case_media
