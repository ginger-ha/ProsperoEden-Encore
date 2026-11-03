#!/usr/bin/env python3
"""Compile the actual metadata cache registry and stress parallel readers.

The fully pinned Eden NCA scanner requires the native dependency checkout,
so this is a host-source concurrency test, NOT a complete SDK build.
"""
from __future__ import annotations
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "headless/metadata_bridge.cpp").read_text()
marker = "namespace {\nstruct AddOns {"
start = source.index(marker)
end = source.index("\nvoid eden_scan_addons(", start)
registry_source = source[start:end]
assert "std::mutex& ScannedAddOnsMutex()" in registry_source
assert "std::mutex& ScanAddOnsJobMutex()" in registry_source

scan = source.split("void eden_scan_addons(", 1)[1].split("\nint eden_game_glyph_display_version(", 1)[0]
glyphs = source.split("int eden_game_glyph_display_version(", 1)[1].split("\nint eden_game_language(", 1)[0]
languages = source.split("int eden_game_language(", 1)[1].split("\nint eden_game_addons(", 1)[0]
addons = source.split("int eden_game_addons(", 1)[1].split("\nnamespace {", 1)[0]
assert "const std::lock_guard scan_job_guard{ScanAddOnsJobMutex()};" in scan
assert "AddOnScanTransaction publication(scanned);" in scan
assert "publication.Commit();" in scan
assert "ScannedAddOns().clear();" not in scan
assert "ScannedAddOns().swap(candidate_);" in registry_source
assert "UpdatesScanCompleted() = true;" in registry_source
assert "~AddOnScanTransaction()" in registry_source
assert "const std::lock_guard lock{ScannedAddOnsMutex()};" in glyphs
assert "const std::lock_guard lock{ScannedAddOnsMutex()};" in languages
assert "const std::lock_guard lock{ScannedAddOnsMutex()};" in addons
assert glyphs.find("ScannedAddOnsMutex()") < glyphs.find("entries.find(")
assert addons.find("ScannedAddOnsMutex()") < addons.find("scanned.find(")

fixture = """
#include <atomic>
#include <cassert>
#include <cstdint>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <utility>
#include <vector>
""" + registry_source + """
int main() {
    std::atomic<bool> start{false};
    std::atomic<bool> stop{false};
    std::atomic<unsigned> good_reads{0};
    auto reader = [&] {
        while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
        while (!stop.load(std::memory_order_acquire)) {
            const std::lock_guard lock{ScannedAddOnsMutex()};
            if (!UpdatesScanCompleted()) continue;
            const auto& entries = ScannedAddOns();
            assert(entries.size() == 1);
            const auto& state = entries.begin()->second;
            assert(state.update_present);
            assert(state.update.size() >= 2);
            assert(state.update[0] == 'v');
            ++good_reads;
        }
    };
    std::thread readers[3] = {
        std::thread(reader), std::thread(reader), std::thread(reader)
    };
    std::thread writer([&] {
        start.store(true, std::memory_order_release);
        for (unsigned i = 1; i <= 3000; ++i) {
            const std::lock_guard scan_job_guard{ScanAddOnsJobMutex()};
            // Keep the last complete snapshot visible until publication.
            // Every 73rd scan simulates a failed provider read: the old
            // map remains allocated but completion is invalidated, so
            // readers never consume stale or partially prepared entries.
            std::map<std::uint64_t, AddOns> pending;
            AddOns entry{};
            entry.update_present = true;
            entry.update = "v" + std::to_string(i);
            pending.emplace(i, std::move(entry));
            {
                AddOnScanTransaction publication(pending);
                if (i % 73 != 0) {
                    publication.Commit();
                } else {
                    const std::lock_guard lock{ScannedAddOnsMutex()};
                    assert(ScannedAddOns().size() == 1);
                    assert(ScannedAddOns().begin()->first == i - 1);
                }
            }
            if ((i & 31) == 0) std::this_thread::yield();
        }
        stop.store(true, std::memory_order_release);
    });
    writer.join();
    for (auto& thread : readers) thread.join();
    assert(good_reads.load() > 0);
    // The latest successful scan is authoritative and complete.
    const std::lock_guard lock{ScannedAddOnsMutex()};
    assert(UpdatesScanCompleted());
    assert(ScannedAddOns().size() == 1);
    assert(ScannedAddOns().begin()->first == 3000);
}
"""
compiler = next((x for x in ("clang++-18", "clang++", "g++") if shutil.which(x)), None)
if not compiler:
    raise SystemExit("C++20 compiler unavailable")
with tempfile.TemporaryDirectory(prefix="eden-addon-scan-stress-") as work:
    root = Path(work)
    cpp = root / "concurrent_metadata.cpp"
    out = root / "concurrent_metadata"
    cpp.write_text(fixture)
    subprocess.run([compiler, "-std=c++20", "-O2", "-pthread", "-Wall", "-Wextra",
                    "-Werror", str(cpp), "-o", str(out)], check=True)
    subprocess.run([str(out)], check=True)
print("PASS real C++ update registry: lock protected readers, serial scans, snapshot publication under 3 concurrent readers")
print("NOTE native NCA provider and PS5 SDK compilation still unqualified")
