#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""P2.2: source-extracted Vulkan retire ownership under allocation failure.

Compile actual Image/View retirement methods. The host substitutes tiny Vulkan
owners and a throwing vector allocator to prove synchronisation occurs before
any moved resource can be destroyed. No PS5 build or GPU simulation claim.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "vendor/encore-active/eden-vulkan/vk_texture_cache_cost.cpp").read_text()

def method(first: str, following: str) -> str:
    assert source.count(first) == 1, ("runtime owner changed", first)
    following_text = source.split(first, 1)[1]
    assert following in following_text, ("runtime boundary changed", following)
    return first + following_text.split(following, 1)[0]

image_method = method(
    "void TextureCacheRuntime::RetireGpuImage(Image&& image) {",
    "\nvoid TextureCacheRuntime::RetireGpuImageView(",
)
view_method = method(
    "void TextureCacheRuntime::RetireGpuImageView(ImageView&& view) {",
    "\n#endif",
)
for name, extracted in (
    ("pending_retired_images", image_method),
    ("pending_retired_views", view_method),
):
    assert extracted.index(name + ".reserve(") < extracted.index(name + ".push_back("), (
        "throwing queue growth happens after Vulkan transfer", name)
    assert "scheduler.Finish();" in extracted

cpp = r"""
#include <algorithm>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <new>
#include <utility>
#include <vector>
using u64 = std::uint64_t;
struct State {
    bool gpu_busy = true;
    int premature_destructions = 0;
    int gpu_drains = 0;
};
struct Owner {
    State* state = nullptr;
    explicit Owner(State& s) noexcept : state(&s) {}
    Owner(const Owner&) = delete;
    Owner& operator=(const Owner&) = delete;
    Owner(Owner&& old) noexcept : state(std::exchange(old.state, nullptr)) {}
    ~Owner() {
        if (state && state->gpu_busy) ++state->premature_destructions;
    }
};
struct Image : Owner {
    explicit Image(State& s) : Owner(s) {}
    Image(Image&&) noexcept = default;
    static inline bool fail_new = false;
    static void* operator new(std::size_t n) {
        if (fail_new) { fail_new = false; throw std::bad_alloc(); }
        return ::operator new(n);
    }
    static void operator delete(void* p) noexcept { ::operator delete(p); }
};
struct ImageView : Owner {
    explicit ImageView(State& s) : Owner(s) {}
    ImageView(ImageView&&) noexcept = default;
    static inline bool fail_new = false;
    static void* operator new(std::size_t n) {
        if (fail_new) { fail_new = false; throw std::bad_alloc(); }
        return ::operator new(n);
    }
    static void operator delete(void* p) noexcept { ::operator delete(p); }
};
struct AllocFailure {
    static inline bool next = false;
    static inline int vector_allocations = 0;
};
template<class T> struct ThrowAllocator {
    using value_type = T;
    ThrowAllocator() noexcept = default;
    template<class U> ThrowAllocator(const ThrowAllocator<U>&) noexcept {}
    T* allocate(std::size_t n) {
        if (AllocFailure::next) {
            AllocFailure::next = false;
            throw std::bad_alloc();
        }
        ++AllocFailure::vector_allocations;
        return std::allocator<T>{}.allocate(n);
    }
    void deallocate(T* ptr, std::size_t n) noexcept {
        std::allocator<T>{}.deallocate(ptr, n);
    }
    template<class U> bool operator==(const ThrowAllocator<U>&) const noexcept {
        return true;
    }
};
struct Scheduler {
    State* state;
    u64 CurrentTick() const noexcept { return 42; }
    void Finish() { state->gpu_busy = false; ++state->gpu_drains; }
};
template<class T> struct Retired {
    u64 tick{};
    u64 frame{};
    std::unique_ptr<T> resource;
};
struct TextureCacheRuntime {
    explicit TextureCacheRuntime(State& s) : scheduler{&s} {}
    Scheduler scheduler;
    u64 gpu_retire_frame = 13;
    std::vector<Retired<Image>, ThrowAllocator<Retired<Image>>> pending_retired_images;
    std::vector<Retired<ImageView>, ThrowAllocator<Retired<ImageView>>> pending_retired_views;
    void RetireGpuImage(Image&& image);
    void RetireGpuImageView(ImageView&& view);
};
""" + image_method + "\n" + view_method + r"""
int main() {
    // Throw from vector growth; old push_back(make_unique(move(owner)))
    // destroyed the moved owner before the catch had drained the GPU.
    {
        State state;
        TextureCacheRuntime cache(state);
        Image image(state);
        AllocFailure::next = true;
        bool rejected = false;
        try { cache.RetireGpuImage(std::move(image)); }
        catch (const std::bad_alloc&) { rejected = true; }
        assert(rejected && state.gpu_drains == 1);
        assert(state.premature_destructions == 0);
        assert(cache.pending_retired_images.empty());
    }
    {
        State state;
        TextureCacheRuntime cache(state);
        ImageView view(state);
        AllocFailure::next = true;
        bool rejected = false;
        try { cache.RetireGpuImageView(std::move(view)); }
        catch (const std::bad_alloc&) { rejected = true; }
        assert(rejected && state.gpu_drains == 1);
        assert(state.premature_destructions == 0);
        assert(cache.pending_retired_views.empty());
    }
    // Also protect allocation of the unique_ptr owner after vector reserve.
    {
        State state;
        TextureCacheRuntime cache(state);
        Image image(state);
        Image::fail_new = true;
        bool rejected = false;
        try { cache.RetireGpuImage(std::move(image)); }
        catch (const std::bad_alloc&) { rejected = true; }
        assert(rejected && state.gpu_drains == 1);
        assert(state.premature_destructions == 0);
    }
    {
        State state;
        TextureCacheRuntime cache(state);
        ImageView view(state);
        ImageView::fail_new = true;
        bool rejected = false;
        try { cache.RetireGpuImageView(std::move(view)); }
        catch (const std::bad_alloc&) { rejected = true; }
        assert(rejected && state.gpu_drains == 1);
        assert(state.premature_destructions == 0);
    }
    // Ordinary ownership remains pending until completion; no forced wait.
    {
        State state;
        TextureCacheRuntime cache(state);
        Image image(state);
        ImageView view(state);
        cache.RetireGpuImage(std::move(image));
        cache.RetireGpuImageView(std::move(view));
        assert(state.gpu_drains == 0);
        assert(cache.pending_retired_images.size() == 1);
        assert(cache.pending_retired_views.size() == 1);
        assert(cache.pending_retired_images[0].tick == 42);
        assert(cache.pending_retired_images[0].frame == 13);
        cache.scheduler.Finish();
        cache.pending_retired_views.clear();
        cache.pending_retired_images.clear();
        assert(state.premature_destructions == 0);
    }
    // Texture churn must amortize vector growth. The 128 Vulkan owners
    // are distinct allocations; count ONLY the retirement queue's allocator.
    // A reserve(size() + 1) regression does 128 full relocations here.
    {
        State state;
        TextureCacheRuntime cache(state);
        const int before = AllocFailure::vector_allocations;
        for (int i = 0; i < 128; ++i) {
            Image image(state);
            cache.RetireGpuImage(std::move(image));
        }
        assert(cache.pending_retired_images.size() == 128);
        assert(AllocFailure::vector_allocations - before <= 5);
        assert(state.gpu_drains == 0);
        cache.scheduler.Finish();
        cache.pending_retired_images.clear();
        assert(state.premature_destructions == 0);
    }
    {
        State state;
        TextureCacheRuntime cache(state);
        const int before = AllocFailure::vector_allocations;
        for (int i = 0; i < 128; ++i) {
            ImageView view(state);
            cache.RetireGpuImageView(std::move(view));
        }
        assert(cache.pending_retired_views.size() == 128);
        assert(AllocFailure::vector_allocations - before <= 5);
        assert(state.gpu_drains == 0);
        cache.scheduler.Finish();
        cache.pending_retired_views.clear();
        assert(state.premature_destructions == 0);
    }
    // An allocation failure while growing a NONEMPTY queue must retain all
    // earlier GPU owners and drain before the caller's new owner can die.
    {
        State state;
        TextureCacheRuntime cache(state);
        for (int i = 0; i < 8; ++i) {
            Image image(state);
            cache.RetireGpuImage(std::move(image));
        }
        AllocFailure::next = true;
        Image ninth(state);
        bool rejected = false;
        try { cache.RetireGpuImage(std::move(ninth)); }
        catch (const std::bad_alloc&) { rejected = true; }
        assert(rejected && state.gpu_drains == 1);
        assert(cache.pending_retired_images.size() == 8);
        assert(state.premature_destructions == 0);
    }
    {
        State state;
        TextureCacheRuntime cache(state);
        for (int i = 0; i < 8; ++i) {
            ImageView view(state);
            cache.RetireGpuImageView(std::move(view));
        }
        AllocFailure::next = true;
        ImageView ninth(state);
        bool rejected = false;
        try { cache.RetireGpuImageView(std::move(ninth)); }
        catch (const std::bad_alloc&) { rejected = true; }
        assert(rejected && state.gpu_drains == 1);
        assert(cache.pending_retired_views.size() == 8);
        assert(state.premature_destructions == 0);
    }
    std::puts("P2_2_GPU_RETIRE_ALLOCATION_FAILURE_PASS");
}
""";

compilers = list(dict.fromkeys(
    c for name in ("clang++", "g++") if (c := shutil.which(name))))
assert compilers, "host C++20 compiler required"
with tempfile.TemporaryDirectory(prefix="encore-gpu-retire-oom-") as temp:
    temp = Path(temp)
    path = temp / "gpu-retire.cpp"
    path.write_text(cpp)
    for compiler in compilers:
        for opt in ("-O0", "-O2"):
            executable = temp / (Path(compiler).name + opt)
            built = subprocess.run(
                [compiler, "-std=c++20", opt, "-Wall", "-Wextra", "-Werror",
                 "-fsanitize=undefined", "-fno-sanitize-recover=all",
                 str(path), "-o", str(executable)],
                capture_output=True, text=True, timeout=60)
            assert built.returncode == 0, (compiler, opt, built.stderr[-4000:])
            ran = subprocess.run(
                [str(executable)], capture_output=True, text=True, timeout=20)
            assert ran.returncode == 0, (compiler, opt, ran.stderr[-4000:])
            assert "P2_2_GPU_RETIRE_ALLOCATION_FAILURE_PASS" in ran.stdout
            print("P2_2_GPU_RETIRE_ALLOCATION_FAILURE_PASS",
                  Path(compiler).name, opt)
