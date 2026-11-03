// ProsperoEden - The launcher's textures: its own art and lazily loaded covers.
// Copyright (C) 2026 BlackBearReloaded
// SPDX-License-Identifier: GPL-3.0-or-later

#include "pe/ui/textures.hpp"

#include "pe/ui/dualsense_mask_asset.hpp"
#include "pe/core/log.hpp"

#include <algorithm>
#include <chrono>
#include <future>
#include <string_view>
#include <utility>

namespace pe::ui
{

namespace
{

constexpr std::size_t kMaxCovers = 160;
constexpr std::size_t kMaxTextureReclaimsPerFrame = 2;
// Nlib replaces images by atomic rename. Multiple invalidations can leave
// stale decode requests in the FIFO. Never drain an unbounded number of
// invalid keys in one held-D-pad UI frame; finish the backlog next frame.
constexpr std::size_t kMaxCoverQueueLookupsPerFrame = 24;
// Profile avatars are UI-critical and often arrive after NiakPS5's broker
// creates its staged image. Give their small decode priority over a library
// full of 16:9 screenshots. The decoder still runs off the GL/UI thread.
bool IsProfileAvatarImage(std::string_view path)
{
    return path.find("/system_data/priv/cache/profile/") != std::string_view::npos ||
           path.find("/NiakPS5/assets/niak-profile.") != std::string_view::npos;
}

} // namespace

Textures::~Textures()
{
    release();
}

std::uint32_t Textures::create(const gfx::Image &image)
{
    return image.empty() ? 0 : batch_.create_texture(image.width, image.height, image.rgba.data());
}

void Textures::clear_case_pages()
{
    for (const auto texture : case_pages_)
        batch_.delete_texture(texture);
    case_pages_.clear();
}

std::uint32_t Textures::render_case_page(const gfx::DrawList& drawing,
                                          const gfx::Font* font,
                                          std::uint32_t font_texture,
                                          int width, int height,
                                          std::uint32_t existing)
{
    // A single title owns at most two live pages (front/back). Refreshing
    // existing ink must never allocate a third page or change its GL ID.
    if (width <= 0 || width > 1024 || height <= 0 || height > 1536 ||
        drawing.instances().empty())
        return 0;
    const bool refresh = existing != 0;
    if (refresh) {
        if (std::find(case_pages_.begin(), case_pages_.end(), existing) ==
            case_pages_.end()) return 0;
    } else if (case_pages_.size() >= 2) {
        return 0;
    }
    const std::uint32_t ink = refresh ? existing :
        batch_.create_texture(width, height, nullptr);
    if (!ink) return 0;
    GLint old_fbo = 0;
    GLint old_viewport[4]{};
    GLfloat old_clear[4]{};
    const GLboolean old_scissor = glIsEnabled(GL_SCISSOR_TEST);
    glGetIntegerv(GL_FRAMEBUFFER_BINDING, &old_fbo);
    glGetIntegerv(GL_VIEWPORT, old_viewport);
    glGetFloatv(GL_COLOR_CLEAR_VALUE, old_clear);
    GLuint framebuffer = 0;
    glGenFramebuffers(1, &framebuffer);
    if (!framebuffer) {
        if (!refresh) batch_.delete_texture(ink);
        return 0;
    }
    glBindFramebuffer(GL_FRAMEBUFFER, framebuffer);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                           GL_TEXTURE_2D, ink, 0);
    const bool complete = glCheckFramebufferStatus(GL_FRAMEBUFFER) ==
                          GL_FRAMEBUFFER_COMPLETE;
    if (complete) {
        // Render only the paper ink. The original launcher still owns the
        // shared 3D transparent shell, rounded plastic and red physical spine.
        glDisable(GL_SCISSOR_TEST);
        glViewport(0, 0, width, height);
        // Printed jacket paper is ONE fully opaque sheet, even at the
        // outermost top/bottom texels and under missing async media.
        // Clearing to transparent allowed the shell/background to show
        // through GL's interpolated edges during the 3D rotation.
        glClearColor(17.0f / 255.0f, 34.0f / 255.0f,
                     53.0f / 255.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        if (font && font_texture)
            batch_.sync_font_texture(font_texture, *font);
        batch_.draw(drawing, gfx::Viewport{}, width, height);
    }
    glBindFramebuffer(GL_FRAMEBUFFER, static_cast<GLuint>(old_fbo));
    glViewport(old_viewport[0], old_viewport[1],
               old_viewport[2], old_viewport[3]);
    glClearColor(old_clear[0], old_clear[1], old_clear[2], old_clear[3]);
    if (old_scissor) glEnable(GL_SCISSOR_TEST);
    else glDisable(GL_SCISSOR_TEST);
    glDeleteFramebuffers(1, &framebuffer);
    if (!complete) {
        if (!refresh) batch_.delete_texture(ink);
        return 0;
    }
    if (!refresh) case_pages_.push_back(ink);
    return ink;
}

bool Textures::load_art(const std::string &directory)
{
    const auto load = [&](const char *name, std::uint32_t *texture)
    {
        gfx::Image image;
        if (!gfx::load_tga(directory + "/" + name, &image))
        {
            sys::log("art %s could not be read", name);
            return false;
        }
        *texture = create(image);
        return *texture != 0;
    };
    // The package generates this from assets/encore-background.jpg. It is launcher-only and is
    // released before a game starts, so it does not consume gameplay VRAM.
    (void)load("art/backdrop.tga", &backdrop_);
    const bool brand = load("art/brand.tga", &brand_);
    // Exact fixed components are optional assets; the painter retains a
    // clean metadata-only fallback when they are absent.
    (void)load("art/switch-logo.tga", &switch_logo_);
    (void)load("art/switch-rear-footer.tga", &switch_rear_footer_);
    // Licensed DualSense artwork is a compact 144x100 mask embedded in the
    // launcher. Decode it ONCE before any frame; no SVG parser, PNG I/O or
    // texture upload inside navigation/gameplay. Fall back to the old local
    // controller TGA if an asset revision is ever malformed.
    gfx::Image pad_image;
    pad_image.width = art::kDualSenseWidth;
    pad_image.height = art::kDualSenseHeight;
    constexpr std::size_t kPixels =
        static_cast<std::size_t>(art::kDualSenseWidth) * art::kDualSenseHeight;
    pad_image.rgba.resize(kPixels * 4u);
    std::size_t pixel = 0;
    bool valid = true;
    for (std::size_t i = 0; i < art::kDualSenseRunsCount; i += 2) {
        const std::size_t length = art::kDualSenseAlphaRuns[i];
        const auto level = art::kDualSenseAlphaRuns[i + 1];
        if (length == 0 || level > 3 || length > kPixels - pixel) {
            valid = false;
            break;
        }
        for (std::size_t n = 0; n < length; ++n, ++pixel) {
            auto* color = pad_image.rgba.data() + pixel * 4u;
            color[0] = color[1] = color[2] = 255;
            // The supplied outline uses predominantly alpha level 1
            // (85/255). On Eden's near-black TV panels this looks BLACK,
            // even when the RGB tint is white. Preserve transparent pixels
            // but render nonzero outline samples as opaque white.
            color[3] = level == 0 ? 0 : (level == 1 ? 240 : 255);
        }
    }
    if (valid && pixel == kPixels)
        controller_ = create(pad_image);
    if (!controller_)
        (void)load("art/controller.tga", &controller_);
    return brand;
}

void Textures::release()
{
    clear_case_pages();
    // The worker only reads/decompresses CPU-side bytes. Its lifetime must
    // end before the Services reference backing it can be destroyed.
    if (decode_.valid()) {
        decode_.wait();
        try { (void)decode_.get(); } catch (...) {}
    }
    for (std::uint32_t *texture : {&backdrop_, &backdrop_blur_, &brand_, &controller_,
                                   &switch_logo_, &switch_rear_footer_})
    {
        batch_.delete_texture(*texture);
        *texture = 0;
    }
    for (auto &[key, entry] : covers_)
        batch_.delete_texture(entry.texture);
    covers_.clear();
    // A context is still current during release; drain the bounded-per-frame
    // invalidation backlog before destroying it to prevent orphaned GL IDs.
    for (const std::uint32_t texture : pending_deletes_)
        batch_.delete_texture(texture);
    pending_deletes_.clear();
    queue_.clear();
}

Cover Textures::cover(const std::string &path, float size)
{
    if (path.empty())
        return {0, 0.0f, true, 1.0f};
    // A 1920px Nlib screenshot used as a 300px library tile must not
    // upload the full 8 MiB RGBA image on the GL/UI thread. Quantize
    // requested physical pixels into stable power-of-two buckets, retaining
    // the unscaled source for the 1920px Home Hero.
    const float pixels = std::clamp(size * output_scale_, 1.0f, 2048.0f);
    int target_pixels = 64;
    while (target_pixels < pixels && target_pixels < 2048)
        target_pixels *= 2;
    const std::string key = path + '#' + std::to_string(target_pixels);
    auto it = covers_.find(key);
    if (it == covers_.end())
    {
        Entry entry;
        entry.path = path;
        entry.target_pixels = target_pixels;
        entry.generation = ++next_generation_;
        it = covers_.emplace(key, std::move(entry)).first;
        if (IsProfileAvatarImage(path)) queue_.push_front(key);
        else queue_.push_back(key);
    }
    it->second.used = frame_;
    // Calculate age only for visible/queried covers, not every cached entry.
    float age = it->second.loaded
        ? static_cast<float>(uptime_seconds_ - it->second.loaded_at_seconds)
        : 0.0f;
    // Nlib downloads arrive by atomic rename. Poll a missing *visible* cover
    // once after 450 ms (instead of freezing its placeholder for three seconds),
    // then back off to 1.5 / 3 s if it is truly absent. No per-frame stat().
    const float retry_after = it->second.failed_loads <= 1 ? 0.45f :
                              it->second.failed_loads == 2 ? 1.5f : 3.0f;
    if (it->second.loaded && it->second.texture == 0 &&
        age >= retry_after) {
        it->second.loaded = false;
        it->second.loaded_at_seconds = uptime_seconds_;
        age = 0.0f;
        if (IsProfileAvatarImage(path)) queue_.push_front(key);
        else queue_.push_back(key);
    }
    // Preserve a previously confirmed missing state while its next decode
    // is queued. Otherwise a failed official scan briefly hides its composed
    // sleeve on every retry, before the eventual successful upload.
    const bool missing = it->second.texture == 0 &&
                         (it->second.loaded || it->second.failed_loads != 0);
    return {it->second.texture, age, missing,
            it->second.aspect};
}

void Textures::invalidate(const std::string &path)
{
    if (path.empty()) return;
    // The Nlib atomic rename invalidates every size bucket of this path.
    // Also purge its pending decode requests now: otherwise repeated media
    // refreshes can leave hundreds of dead FIFO entries, and the bounded
    // 24-lookups/frame decoder delays newly visible covers behind them.
    // The '#' boundary prevents removing a different path with the same prefix.
    const auto is_queued_variant = [&](const std::string& key) {
        return key.size() > path.size() &&
               key.compare(0, path.size(), path) == 0 &&
               key[path.size()] == '#';
    };
    queue_.erase(std::remove_if(queue_.begin(), queue_.end(),
                                is_queued_variant), queue_.end());
    for (auto it = covers_.begin(); it != covers_.end(); )
    {
        if (it->second.path == path) {
            if (it->second.texture != 0)
                pending_deletes_.push_back(it->second.texture);
            it = covers_.erase(it);
        } else {
            ++it;
        }
    }
}

void Textures::pump(float dt, int budget)
{
    ++frame_;
    uptime_seconds_ += static_cast<double>(dt);
    // Nlib can replace a banner, icon and three screenshots at once.
    // Invalidation itself performs zero GL calls; retire at most two of
    // their old textures here, spreading driver cleanup across frames.
    std::size_t deleted_this_frame = 0;
    while (deleted_this_frame < kMaxTextureReclaimsPerFrame &&
           !pending_deletes_.empty()) {
        batch_.delete_texture(pending_deletes_.front());
        pending_deletes_.pop_front();
        ++deleted_this_frame;
    }
    // Cache-wide age updates removed: elapsed time is computed lazily.

    // Decoding a 1920x1080 Nlib JPEG/TGA and generating downsized copies on
    // the UI thread caused visible menu repeat/scroll stalls (>100 ms).
    // Only the GL texture upload stays on the owner thread. Handle *at most
    // one* completed upload this frame and prefetch the next image afterwards.
    if (decode_.valid() &&
        decode_.wait_for(std::chrono::seconds(0)) == std::future_status::ready)
    {
        try {
            DecodedCover result = decode_.get();
            const auto it = covers_.find(result.key);
            if (it != covers_.end() &&
                it->second.generation == result.generation) {
                Entry &entry = it->second;
                entry.loaded = true;
                entry.loaded_at_seconds = uptime_seconds_;
                const bool profile_avatar = IsProfileAvatarImage(entry.path);
                const bool retail_case =
                    entry.path.find("/box-front-") != std::string::npos ||
                    entry.path.find("/box-back-") != std::string::npos ||
                    entry.path.find("/box-spine-") != std::string::npos;
                if (!result.ok || result.image.empty()) {
                    entry.failed_loads = std::min(entry.failed_loads + 1u, 4u);
                    if (retail_case)
                        sys::log("EDEN_CASE_TEXTURE status=decode-failed path=%s attempt=%u",
                                 entry.path.c_str(), entry.failed_loads);
                    if (profile_avatar)
                        sys::log("EDEN_PROFILE_AVATAR_TEXTURE status=decode_failed attempt=%u",
                                 entry.failed_loads);
                } else {
                    entry.failed_loads = 0;
                    entry.aspect = static_cast<float>(result.image.width) /
                                   static_cast<float>(result.image.height);
                    entry.texture = create(result.image);
                    if (entry.texture == 0)
                        entry.failed_loads = std::min(entry.failed_loads + 1u, 4u);
                    if (retail_case)
                        sys::log("EDEN_CASE_TEXTURE status=%s path=%s width=%d height=%d texture=%u",
                                 entry.texture ? "ready" : "upload-failed",
                                 entry.path.c_str(), result.image.width,
                                 result.image.height, entry.texture);
                    if (profile_avatar)
                        sys::log("EDEN_PROFILE_AVATAR_TEXTURE status=%s width=%d height=%d",
                                 entry.texture ? "ready" : "upload_failed",
                                 result.image.width, result.image.height);
                }
            }
        } catch (const std::exception& error) {
            sys::log("cover decode failed: %s", error.what());
        } catch (...) {
            sys::log("cover decode failed: unknown error");
        }
        // A consumed future is invalid. The next queued image can start now.
    }

    if (budget > 0 && !decode_.valid()) {
        std::size_t inspected = 0;
        while (!queue_.empty() && inspected < kMaxCoverQueueLookupsPerFrame) {
            ++inspected;
            std::string key = std::move(queue_.front());
            queue_.pop_front();
            const auto it = covers_.find(key);
            if (it == covers_.end() || it->second.loaded) continue;
            const std::string path = it->second.path;
            const int target_pixels = it->second.target_pixels;
            const auto generation = it->second.generation;
            try {
                decode_ = std::async(std::launch::async,
                    [this, key = std::move(key), path, target_pixels, generation]() mutable {
                        DecodedCover decoded;
                        decoded.key = std::move(key);
                        decoded.generation = generation;
                        try {
                            decoded.ok = services_.load_image(path, &decoded.image);
                            if (decoded.ok) {
                                // Keep the largest dimension near the actual
                                // rendering footprint. This scaling is CPU-side
                                // on the decode worker, never in the UI frame.
                                // The 3/2 threshold avoids uploading a 960px
                                // image for a 512px tile while respecting the
                                // original Hero resolution at 2048px.
                                while (decoded.image.width > 1 &&
                                       decoded.image.height > 1 &&
                                       std::max(decoded.image.width, decoded.image.height) >
                                           target_pixels * 3 / 2)
                                    decoded.image = gfx::halve(decoded.image);
                            }
                        } catch (...) {
                            decoded.image = {};
                            decoded.ok = false; // normal retry/backoff on bad media
                        }
                        return decoded;
                    });
            } catch (const std::exception& error) {
                sys::log("cover queue failed: %s", error.what());
                it->second.loaded = true;
                it->second.loaded_at_seconds = uptime_seconds_;
                it->second.failed_loads = std::min(it->second.failed_loads + 1u, 4u);
            }
            break;
        }
    }

    if (covers_.size() > kMaxCovers)
    {
        // Avoid building and sorting a temporary vector every UI frame.
        // Evict at most two stale, completed covers per update: a bounded
        // number of GL deletes and no heap allocation in this hot path.
        for (std::size_t reclaimed = 0;
             deleted_this_frame + reclaimed < kMaxTextureReclaimsPerFrame &&
             covers_.size() > kMaxCovers * 3 / 4; ++reclaimed)
        {
            auto oldest = covers_.end();
            for (auto it = covers_.begin(); it != covers_.end(); ++it)
            {
                // Never evict in-flight decodes or the last two frames'
                // visible covers, even under a large collection pressure.
                if (!it->second.loaded || it->second.used + 2 >= frame_)
                    continue;
                if (oldest == covers_.end() ||
                    it->second.used < oldest->second.used)
                    oldest = it;
            }
            if (oldest == covers_.end())
                break;
            batch_.delete_texture(oldest->second.texture);
            covers_.erase(oldest);
        }
    }
}

} // namespace pe::ui
