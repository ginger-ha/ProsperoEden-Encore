#!/usr/bin/env python3
"""Compile *actual* in-game glyph override selector and preference persistence.

Host-only C++20 with nlohmann/json.hpp; never builds the PS5 app or GUI.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# A single existing encore-overrides sync must also bring in the visual
# catalogue; two independent manual procedures would go stale quickly.
video_sync = (ROOT / "tools" / "sync-encore-overrides.py").read_text()
assert '"sync-glyph-overrides.py"' in video_sync
assert '"--source", str(source)' in video_sync
# We cannot compile the complete pinned game container/NACP bridge without
# the console-port dependency checkout. Protect its real source integration:
# base games read control.nacp, updates are distinguished from missing scans,
# and the launch path never requires a manually entered EdiZon Build ID.
metadata_cpp = (ROOT / "headless" / "metadata_bridge.cpp").read_text()
metadata_h = (ROOT / "headless" / "metadata_bridge.h").read_text()
main_cpp = (ROOT / "headless" / "main.cpp").read_text()
assert "ReadGlyphDisplayVersion(" in metadata_cpp
assert "raw.version_string" in metadata_cpp
assert "UpdatesScanCompleted()" in metadata_cpp
assert "update_present = true" in metadata_cpp
# The global store may be absent while collocated update/DLC roots exist.
# Only an absent (not unreadable) global directory lets an empty scan
# publish a complete snapshot; the mixed-root scan must keep this guard.
assert "if (add_on_roots.empty()) {" in metadata_cpp
assert "const bool global_exists = std::filesystem::exists(updates_dir, error);" in metadata_cpp
assert "if (!error && !global_exists) publication.Commit();" in metadata_cpp
assert "const FileSys::ExternalContentProvider provider(std::move(add_on_roots));" in metadata_cpp
assert "const std::lock_guard scan_job_guard{ScanAddOnsJobMutex()};" in metadata_cpp
assert "ScannedAddOns().swap(candidate_);" in metadata_cpp
assert "AddOnScanTransaction publication(scanned);" in metadata_cpp
assert "ScannedAddOns().clear();" not in metadata_cpp
assert "const std::lock_guard lock{ScannedAddOnsMutex()};" in metadata_cpp
# The metadata reader handles XCI/XCZ and NSP/NSZ through the shared,
# case-normalized format selector, not a hard-coded XCI-only condition.
assert 'Eden::IsPackageFile(extension) && !Eden::IsCardImageFile(extension)' in metadata_cpp
assert 'OpenControlRomFs(file, Eden::IsCardImageFile(extension))' in metadata_cpp
assert "eden_game_glyph_display_version(" in metadata_cpp
assert "eden_game_glyph_display_version(" in metadata_h
assert "eden_game_glyph_display_version(" in main_cpp
assert "eden_game_addons(title, glyph_update_version" not in main_cpp
assert "NeedsGameVersion(" in main_cpp
assert "const bool all_mods_enabled = Eden::LoadModsEnabled(title)" in main_cpp
assert (main_cpp.find("if (Eden::GlyphOverrides::NeedsGameVersion(") <
        main_cpp.find("(void)eden_game_glyph_display_version("))
CXX = next((item for item in ("clang++-18", "clang++", "g++") if shutil.which(item)), None)
if not CXX:
    raise SystemExit("missing host C++20 compiler")
TEST = r"""
#include "glyph_overrides_runtime.h"
#include "glyph_version.h"
#include "settings_store.h"
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using Eden::GlyphOverrides::Catalogue;
using Eden::GlyphOverrides::State;
using Eden::GlyphOverrides::Style;
static constexpr std::uint64_t GAME = 0x0100C49025D3E000ull;

void put(const fs::path& path, const std::string& value) {
    fs::create_directories(path.parent_path());
    std::ofstream out(path);
    assert(bool(out));
    out << value;
}
std::string catalogue(std::string_view version = "v1.2.0") {
    return R"({"schema_version":2,"revision":7,"titles":[{"title_id":"0100C49025D3E000","update_version":")"
        + std::string(version) + R"("}]})";
}
std::string evidence = R"({"schema":2,"title_id":"0100C49025D3E000",
    "update_version":"v1.2.0",
    "rights":"Original artist-owned PlayStation art",
    "files":[{"romfs_path":"ui/controller.bntx",
              "replacement":"files/controller.bntx",
              "original_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
              "replacement_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]})";
int main(int argc, char** argv) {
    assert(argc == 2);
    // The exact C++ helper used by the native NACP bridge must accept
    // base-game display versions (including a full 16-byte field), but
    // reject unreadable control data without inventing a Build ID.
    std::array<char, 16> nacp{};
    nacp[0] = '1'; nacp[1] = '.'; nacp[2] = '2'; nacp[3] = '.'; nacp[4] = '0';
    assert(Eden::GlyphVersion::FromNacp(nacp) == "1.2.0");
    nacp[0] = '\x01';
    assert(Eden::GlyphVersion::FromNacp(nacp).empty());
    nacp.fill('A');
    assert(Eden::GlyphVersion::FromNacp(nacp) == std::string(16, 'A'));
    nacp.fill('\0');
    assert(Eden::GlyphVersion::FromNacp(nacp).empty());
    // Independent SHA-256 vectors: empty, split update and million 'a'.
    Eden::GlyphIntegrity::Sha256 empty_hash;
    assert(empty_hash.FinishHex() ==
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    Eden::GlyphIntegrity::Sha256 abc;
    abc.Update("a", 1);
    abc.Update("bc", 2);
    assert(abc.FinishHex() ==
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    Eden::GlyphIntegrity::Sha256 million;
    const std::string block(1000, 'a');
    for (int i = 0; i < 1000; ++i) million.Update(block.data(), block.size());
    assert(million.FinishHex() ==
        "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
    // The launch integrity scanner must reject oversized or cumulatively
    // oversized graphic packs BEFORE hashing gigabytes of user-supplied data.
    using Eden::GlyphOverrides::FitsGraphicPackBudget;
    constexpr std::uintmax_t mib = 1024ull * 1024ull;
    static_assert(FitsGraphicPackBudget(0, 128 * mib));
    static_assert(!FitsGraphicPackBudget(0, 128 * mib + 1));
    static_assert(FitsGraphicPackBudget(384 * mib, 128 * mib));
    static_assert(!FitsGraphicPackBudget(384 * mib + 1, 128 * mib));
    static_assert(!FitsGraphicPackBudget(512 * mib, 1));
    static_assert(!FitsGraphicPackBudget(~std::uintmax_t{0}, 1));
    const fs::path base = argv[1];
    // ReadBounded MUST enforce the bound while reading, not only by a
    // preliminary file_size(). This also covers the exact boundary and
    // symlink attempts before external JSON reaches the parser.
    const fs::path bounded_json = base / "bounded" / "manifest.json";
    std::string bounded_data;
    put(bounded_json, std::string(4096, 'z'));
    assert(Eden::GlyphOverrides::ReadBounded(bounded_json, 4096, &bounded_data));
    assert(bounded_data.size() == 4096);
    assert(!Eden::GlyphOverrides::ReadBounded(bounded_json, 4095, &bounded_data));
    put(bounded_json, std::string(4097, 'z'));
    assert(!Eden::GlyphOverrides::ReadBounded(bounded_json, 4096, &bounded_data));
    const fs::path symlinked_json = base / "bounded" / "manifest-link.json";
    fs::create_symlink(bounded_json, symlinked_json);
    assert(!Eden::GlyphOverrides::ReadBounded(symlinked_json, 8192, &bounded_data));
    put(bounded_json, "");
    assert(Eden::GlyphOverrides::ReadBounded(bounded_json, 4096, &bounded_data));
    assert(bounded_data.empty());

    const fs::path million_file = base / "sha-test" / "million-a.bin";
    put(million_file, std::string(1000000, 'a'));
    assert(Eden::GlyphIntegrity::FileSha256(million_file) ==
           std::optional<std::string>(
            "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"));
    assert(!Eden::GlyphIntegrity::FileSha256(million_file, 999999));
    const fs::path mods = base / "mods";
    const fs::path title = mods / "0100c49025d3e000"; // existing LOWERCASE
    const fs::path pack = title / "Eden Encore PS Glyphs";
    const fs::path catalogue_path = base / "encore-glyph-overrides.json";
    const fs::path preferences = base / "prosperoeden.json";
    const auto atlas = pack / "romfs" / "ui" / "controller.bntx";
    const std::string original_asset = "synthetic user-owned PS atlas";
    put(atlas, original_asset);
    const auto actual_sha = Eden::GlyphIntegrity::FileSha256(atlas);
    assert(actual_sha && actual_sha->size() == 64);
    assert(!Eden::GlyphIntegrity::FileSha256(atlas, original_asset.size() - 1));
    const auto placeholder = std::string(64, 'b');
    const auto digest_at = evidence.find(placeholder);
    assert(digest_at != std::string::npos);
    evidence.replace(digest_at, placeholder.size(), *actual_sha);
    put(pack / "eden-glyph-pack.json", evidence);
    put(catalogue_path, catalogue());
    const auto default_built_in = Eden::GlyphOverrides::LoadCatalogue(base / "missing-catalogue.json");
    assert(default_built_in.valid &&
           default_built_in.revision == Eden::GlyphOverridesGenerated::kRevision &&
           default_built_in.rules.empty());
    Catalogue data = Eden::GlyphOverrides::LoadCatalogue(catalogue_path);
    assert(data.valid && data.revision == 7 && data.rules.size() == 1);
    put(catalogue_path, R"({"schema_version":2,"revision":0,"titles":[]})");
    const auto stale = Eden::GlyphOverrides::LoadCatalogue(catalogue_path);
    assert(stale.valid && stale.revision == default_built_in.revision);
    // Equal revisions are not updates. A conflicting local JSON cannot
    // silently impersonate the committed catalogue at the same revision.
    put(catalogue_path,
        R"({"schema_version":2,"revision":2,"titles":[{"title_id":"0100C49025D3E000","update_version":"v1.2.0"}]})");
    const auto equal_revision = Eden::GlyphOverrides::LoadCatalogue(catalogue_path);
    assert(equal_revision.valid && equal_revision.rules.empty());
    put(catalogue_path, catalogue());
    auto mods_found = Eden::Mods::List(mods.string(), GAME);
    // Real source C++ chooses whether loading/decrypting base game NACP is
    // necessary. No rule means no extra metadata reads for ordinary games.
    using Eden::GlyphOverrides::NeedsGameVersion;
    assert(!NeedsGameVersion(default_built_in, GAME, Style::PlayStation, mods_found));
    assert(NeedsGameVersion(data, GAME, Style::PlayStation, mods_found));
    assert(!NeedsGameVersion(data, GAME, Style::Nintendo, mods_found));
    assert(!NeedsGameVersion(data, 0x0100DEAD00000000ull, Style::PlayStation, mods_found));
    assert(!NeedsGameVersion(data, GAME, Style::PlayStation, {}));
    assert(mods_found.size() == 1 &&
           mods_found[0].name == "Eden Encore PS Glyphs" &&
           (mods_found[0].kinds & Eden::Mods::kFiles));
    const auto select = [&](const Catalogue& cat, std::string_view version, Style style) {
        return Eden::GlyphOverrides::Select(cat, GAME, version, style,
                                            mods.string(), mods_found);
    };
    assert(select(data, "v1.2.0", Style::PlayStation) == State::Enabled);
    // Ambiguous case-colliding graphic mods cannot be enabled together:
    // the ordinary Eden loader could otherwise overwrite the correct
    // atlas with a second mod in an unpredictable order.
    // Two case-colliding Title IDs in the same mods root cannot provide
    // deterministic artwork selection in the ordinary Eden patch manager.
    const auto title_duplicate = mods / "0100C49025D3E000";
    if (fs::create_directory(title_duplicate)) {
        // A case-sensitive volume permits two distinct Title ID entries;
        // the selector must fail closed until ambiguity is removed.
        assert(select(data, "v1.2.0", Style::PlayStation) == State::EvidenceMismatch);
        fs::remove(title_duplicate);
    } else {
        // Default macOS APFS may treat both spellings as one directory.
        // NEVER remove the uppercase alias: it is the actual lowercase
        // directory containing our staged graphics.
        assert(fs::equivalent(title_duplicate, title));
    }
    assert(select(data, "v1.2.0", Style::PlayStation) == State::Enabled);
    auto duplicate_mods = mods_found;
    duplicate_mods.push_back({"eden encore ps glyphs", Eden::Mods::kFiles});
    assert(Eden::GlyphOverrides::Select(data, GAME, "v1.2.0",
        Style::PlayStation, mods.string(), duplicate_mods) == State::EvidenceMismatch);
    auto wrongly_capitalized = mods_found;
    wrongly_capitalized.front().name = "eden encore ps glyphs";
    assert(Eden::GlyphOverrides::Select(data, GAME, "v1.2.0",
        Style::PlayStation, mods.string(), wrongly_capitalized) == State::EvidenceMismatch);

    // Title-directory symlinks may be followed by general mod discovery,
    // but verified in-game artwork packs must refuse that location.
    const auto symlink_root = base / "symlink-mods";
    fs::create_directories(symlink_root);
    fs::create_directory_symlink(title, symlink_root / "0100C49025D3E000");
    const auto symlink_mods = Eden::Mods::List(symlink_root.string(), GAME);
    assert(symlink_mods.size() == 1);
    assert(Eden::GlyphOverrides::Select(data, GAME, "v1.2.0",
        Style::PlayStation, symlink_root.string(), symlink_mods) == State::EvidenceMismatch);

    put(atlas, "synthetic-user-owned PS atlas");
    assert(select(data, "v1.2.0", Style::PlayStation) == State::EvidenceMismatch);
    put(atlas, original_asset);
    assert(select(data, "v1.2.0", Style::PlayStation) == State::Enabled);
    assert(select(data, "v1.2.0", Style::Nintendo) == State::Disabled);
    assert(select(data, "", Style::PlayStation) == State::UnknownVersion);
    assert(select(data, "v1.2.1", Style::PlayStation) == State::VersionMismatch);
    assert(Eden::GlyphOverrides::Select(data, 0x0100DEAD00000000ull, "v1.2.0",
           Style::PlayStation, mods.string(), {}) == State::Unsupported);
    assert(Eden::GlyphOverrides::Select(data, GAME, "v1.2.0",
           Style::PlayStation, mods.string(), {}) == State::MissingMod);
    auto unknown = data;
    unknown.valid = false;
    assert(select(unknown, "v1.2.0", Style::PlayStation) == State::Unsupported);

    auto rejected = [&](const std::string& body) {
        Catalogue bad;
        assert(!Eden::GlyphOverrides::ParseCatalogue(body, &bad));
    };
    rejected(R"({"schema_version":1,"revision":7,"titles":[]})");
    rejected(R"({"schema_version":2,"revision":7,"titles":[
      {"title_id":"NOTHEX","update_version":"v1"}]})");
    rejected(R"({"schema_version":2,"revision":7,"titles":[
      {"title_id":"0100C49025D3E000","update_version":"v1"},
      {"title_id":"0100C49025D3E000","update_version":"v1"}]})");

    // Correct game ID but a tampered / missing pack is NOT admitted.
    put(pack / "eden-glyph-pack.json",
        R"({"schema":2,"title_id":"0100DEAD00000000","update_version":"v1.2.0","rights":"ok","files":[{"romfs_path":"ui/controller.bntx"}]})");
    assert(select(data, "v1.2.0", Style::PlayStation) == State::EvidenceMismatch);
    put(pack / "eden-glyph-pack.json", evidence);
    fs::remove(pack / "romfs" / "ui" / "controller.bntx");
    assert(select(data, "v1.2.0", Style::PlayStation) == State::EvidenceMismatch);
    put(atlas, original_asset);
    assert(select(data, "v1.2.0", Style::PlayStation) == State::Enabled);
    // Case-insensitive duplicate overlays and file/directory overlaps
    // must fail even if every individual replacement digest is valid.
    // This is particularly important across APFS and Linux mounts.
    auto ambiguous_pack = nlohmann::json::parse(evidence);
    ambiguous_pack["files"].push_back(ambiguous_pack["files"][0]);
    put(pack / "eden-glyph-pack.json", ambiguous_pack.dump());
    assert(select(data, "v1.2.0", Style::PlayStation) == State::EvidenceMismatch);
    ambiguous_pack["files"][1]["romfs_path"] = "UI/CONTROLLER.BNTX";
    put(pack / "eden-glyph-pack.json", ambiguous_pack.dump());
    assert(select(data, "v1.2.0", Style::PlayStation) == State::EvidenceMismatch);
    ambiguous_pack["files"][1]["romfs_path"] = "ui/controller.bntx/child";
    put(pack / "eden-glyph-pack.json", ambiguous_pack.dump());
    assert(select(data, "v1.2.0", Style::PlayStation) == State::EvidenceMismatch);
    ambiguous_pack = nlohmann::json::parse(evidence);
    ambiguous_pack["files"][0]["romfs_path"] = "ui//controller.bntx";
    put(pack / "eden-glyph-pack.json", ambiguous_pack.dump());
    assert(select(data, "v1.2.0", Style::PlayStation) == State::EvidenceMismatch);
    put(pack / "eden-glyph-pack.json", evidence);
    assert(select(data, "v1.2.0", Style::PlayStation) == State::Enabled);
    auto mismatched_evidence = evidence;
    const std::string known_version = "\"update_version\":\"v1.2.0\"";
    auto version_at = mismatched_evidence.find(known_version);
    assert(version_at != std::string::npos);
    mismatched_evidence.replace(version_at, known_version.size(),
                                "\"update_version\":\"v1.3.0\"");
    put(pack / "eden-glyph-pack.json", mismatched_evidence);
    assert(select(data, "v1.2.0", Style::PlayStation) == State::EvidenceMismatch);
    put(pack / "eden-glyph-pack.json", evidence);
    // Even if a graphics file exists, a parent-directory symlink must
    // never turn a title's RomFS replacement into an arbitrary host path.
    fs::remove(pack / "romfs" / "ui" / "controller.bntx");
    fs::remove(pack / "romfs" / "ui");
    const fs::path external = base / "external-not-mod";
    put(external / "controller.bntx", "unsafe external graphic file");
    fs::create_directory_symlink(external, pack / "romfs" / "ui");
    assert(select(data, "v1.2.0", Style::PlayStation) == State::EvidenceMismatch);
    fs::remove(pack / "romfs" / "ui");
    put(atlas, original_asset);
    assert(select(data, "v1.2.0", Style::PlayStation) == State::Enabled);

    // Stored artist preference never silently modifies effective button mapping.
    assert(Eden::LoadInGamePlayStationGlyphs(GAME, preferences.string()));
    const auto original_mapping = Eden::LoadPreferences(preferences.string()).mapping;
    assert(Eden::SaveInGameButtonGlyphs(0, false, preferences.string()));
    assert(!Eden::LoadInGamePlayStationGlyphs(GAME, preferences.string()));
    assert(Eden::SaveInGameButtonGlyphs(GAME, true, preferences.string()));
    assert(Eden::LoadInGamePlayStationGlyphs(GAME, preferences.string()));
    assert(!Eden::LoadInGamePlayStationGlyphs(0x0100DEAD00000000ull, preferences.string()));
    assert(Eden::SaveInGameButtonGlyphs(GAME, false, preferences.string()));
    assert(!Eden::LoadInGamePlayStationGlyphs(GAME, preferences.string()));
    assert(Eden::LoadPreferences(preferences.string()).mapping == original_mapping);

    std::cout << "PASS real C++ in-game glyph override catalogue: title/update gate, separate artwork style, disabled original fallback, mod/evidence safety\n";
}
""";
with tempfile.TemporaryDirectory(prefix="eden-glyph-override-runtime-") as temp:
    root = Path(temp)
    source = root / "glyph_override_check.cpp"
    exe = root / "glyph_override_check"
    source.write_text(TEST)
    subprocess.run([CXX, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "headless"), str(source), "-o", str(exe)], check=True)
    subprocess.run([str(exe), str(root / "fixtures")], check=True)

print("IN-GAME button art: only source mock catalogue; no PS5 glyph resources rendered")
