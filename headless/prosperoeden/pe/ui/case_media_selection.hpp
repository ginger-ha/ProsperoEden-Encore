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
    // Collect at most three independent Nlib fallbacks during the same scan.
    // Indexed scene roles always take precedence, even when encountered later.
    // No second screenshot traversal or per-frame dynamic allocation.
    std::array<const std::string*, 3> fallback{nullptr, nullptr, nullptr};
    constexpr std::array<std::string_view, 3> kSceneMarkers{
        "/box-scene-1-", "/box-scene-2-", "/box-scene-3-"};
    for (const auto& image : screenshots) {
        const auto marker = image.find("/box-scene-");
        if (marker != std::string::npos) {
            // Malformed indexed names must not silently become gameplay art.
            const auto role_at = marker + sizeof("/box-scene-") - 1;
            if (role_at >= image.size()) continue;
            const auto role = image[role_at];
            if (role < '1' || role > '3') continue;
            const auto category = static_cast<std::size_t>(role - '1');
            if (selected[category] ||
                image.compare(marker, kSceneMarkers[category].size(),
                              kSceneMarkers[category]) != 0 ||
                image == cover || is_front(image) || !usable(image))
                continue;
            selected[category] = &image;
            continue;
        }
        if (image.empty() || image == cover || is_front(image)) continue;
        bool duplicate = false;
        for (const auto* existing : fallback) {
            if (existing && *existing == image) {
                duplicate = true;
                break;
            }
        }
        if (duplicate) continue;
        for (auto& slot : fallback) {
            if (!slot) {
                if (usable(image)) slot = &image;
                break;
            }
        }
    }
    // Preserve reserved fanart/title/gameplay slots, then fill gaps with
    // independent captures in their original order.
    std::size_t next_slot = 0;
    for (const auto* candidate : fallback) {
        if (!candidate) break;
        while (next_slot < selected.size() && selected[next_slot]) ++next_slot;
        if (next_slot == selected.size()) break;
        selected[next_slot++] = candidate;
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
