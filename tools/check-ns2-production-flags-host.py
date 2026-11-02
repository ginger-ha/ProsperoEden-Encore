#!/usr/bin/env python3
"""Source-only gate for migrating NS2 research switches into the shared engine.

No build, shell activation, or claim of title compatibility. A human must
review every new/removed switch against the roadmap and the real source owner.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CMAKE = (ROOT / "headless/CMakeLists.txt").read_text()
DOC = (ROOT / "docs/NS1_NS2_PRODUCTION_FLAG_MIGRATION.md").read_text()
ROADMAP = (ROOT / "docs/ROADMAP_NS1_NS2_UNIFIED.md").read_text()
README = (ROOT / "README.md").read_text()
OPT = re.compile(
    r'option\(\s*(EDEN_NS2_[A-Z0-9_]*EXPERIMENTAL)\s*"[^"]+"\s+(ON|OFF)\s*\)'
)
flags = dict(OPT.findall(CMAKE))
all_source_flags = set(re.findall(r'\bEDEN_NS2_[A-Z0-9_]*EXPERIMENTAL\b', CMAKE))
assert len(flags) == 22, ("Unreviewed number of NS2 research gates", len(flags))
assert len(flags) == len(set(flags))  # duplicate names would be merged by dict
assert all_source_flags == set(flags), sorted(all_source_flags - set(flags))
assert set(flags.values()) == {"OFF"}, "Research flags must not be enabled by default"

documented = re.findall(r'`(EDEN_NS2_[A-Z0-9_]*EXPERIMENTAL)`', DOC)
assert len(documented) == len(set(documented)) == len(flags), (
    "Missing, duplicated or obsolete migration checklist owners", documented
)
assert set(documented) == set(flags), (
    "Every NS2 research feature needs a migration/removal contract",
    sorted(set(flags) - set(documented)),
    sorted(set(documented) - set(flags)),
)
assert "https://github.com/niakw/ProsperoEden-Encore/issues/15" in README
assert "ROADMAP_NS1_NS2_UNIFIED.md" in README
assert "NS1/NS2" in ROADMAP
assert "if: ${{ false }}" in (
    ROOT / ".github/workflows/build-040-zbic.yml"
).read_text()
assert "if: ${{ false }}" in (
    ROOT / ".github/workflows/ns2-native-ps5-research.yml"
).read_text()
print(f"EDEN_NS1_NS2_RESEARCH_GATE_INVENTORY_PASS reviewed={len(flags)}"
      " defaults_off=1 release_builds_frozen=1 roadmap_linked=1")
