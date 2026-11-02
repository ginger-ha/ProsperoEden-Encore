#!/usr/bin/env python3
"""Host compiler smoke for NS2 offline title identity + launcher integration."""
from pathlib import Path
import shutil
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
header=(root/"headless/ns2_title_catalog.h").read_text()
services=(root/"headless/prosperoeden/eden_services.cpp").read_text()
assert '#include "ns2_title_catalog.h"' in services
assert 'Eden::Ns2Catalog::Find(game.title_id)' in services
assert 'return FetchKnownNs2Front(title_id, cancel)' not in services
assert 'return 0u;' in services
assert 'https://gamesdb-images.launchbox.gg' in services
assert 'EDEN_NS2_TITLE_RESOLVED' in services
assert 'if (game.cover.empty() && !game.box_front.empty()) game.cover = game.box_front;' in services
assert 'base/exefs/icon.jpg' in services and 'exefs/icon.png' in services
assert 'IsSafeExtractedDirectory(parent)' in services
assert 'icon_' in services and 'std::memcmp(signature,' in services
assert 'IsSafeExtractedDirectory(ancestor)' in services
assert 'WriteJpegTga(*body, staged, true)' in services
assert 'std::rename(staged.c_str(), target.c_str())' in services
compiler=shutil.which("clang++") or shutil.which("g++")
if not compiler: raise SystemExit("No native C++20 compiler")
source=r"""
#include <cassert>
#include <cstdint>
#include <string_view>
#include "ns2_title_catalog.h"
int main() {
    using Eden::Ns2Catalog::Find;
    static_assert(Eden::Ns2Catalog::kTitles.size() == 18);
    const auto* mkw = Find(0x0400C3F00006E000ULL);
    const auto* dk = Find(0x040074A01BF12000ULL);
    assert(mkw && mkw->name == "Mario Kart World");
    assert(dk && dk->name == "Donkey Kong Bananza");
    assert(!Find(0x0100C49025D3E000ULL));
    for (const auto& item : Eden::Ns2Catalog::kTitles) {
        assert(!item.name.empty() && (item.id >> 56) == 4);
        if (!item.front_host.empty()) {
            assert(item.front_host.starts_with("https://"));
            assert(item.front_path.starts_with("/"));
        }
    }
    for (std::size_t i = 0; i < Eden::Ns2Catalog::kTitles.size(); ++i)
        for (std::size_t j = i+1; j < Eden::Ns2Catalog::kTitles.size(); ++j)
            assert(Eden::Ns2Catalog::kTitles[i].id != Eden::Ns2Catalog::kTitles[j].id);
}
"""
with tempfile.TemporaryDirectory(prefix="encore-ns2-catalog-") as tmp:
    cpp=Path(tmp)/"test.cpp"
    cpp.write_text(source)
    exe=Path(tmp)/"test"
    subprocess.run([compiler,"-std=c++20","-Wall","-Wextra","-Werror",
                    "-I",str(root/"headless"),str(cpp),"-o",str(exe)],
                   check=True,timeout=30)
    subprocess.run([str(exe)],check=True,timeout=10)
print("ENCORE_NS2_TITLE_CATALOG_HOST_PASS IDs=18 safety=1 launch_integration=1")
