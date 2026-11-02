#!/usr/bin/env python3
"""Build a Switch 1 + Switch 2 flat-box and scene index from Metadata.zip.

The large archive is processed on a build host, NEVER by the console. Only
normalized game names and safe CDN image basenames are packaged, no art assets.
"""
import argparse
import io
import pathlib
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

SOURCE = "https://gamesdb.launchbox-app.com/Metadata.zip"
IMAGE_FILE = re.compile(r"^(?:r2_)?[0-9a-fA-F-]{36}\.(?:jpg|jpeg|png)$")

# Original physical European front supplied by the user for this exact
# LaunchBox DatabaseID. Keep this in the media INDEX, never in the renderer.
# Current LaunchBox Box - Front (Europe) is an independent fallback. Both
# precede lower-priority regions regardless of resolution.
EUROPE_FRONT_PINS = {
    "79189": (
        "9524e5f7-ccc8-4ce6-a581-03f82c51825e.jpg",
        "a8bcb4cc-a3b0-4cf0-82f3-cb10dd18b27c.jpg",
    ),
}

def normalize(value):
    out = []
    space = False
    for char in value:
        if "A" <= char <= "Z":
            char = char.lower()
        if "a" <= char <= "z" or "0" <= char <= "9":
            out.append(char)
            space = False
        elif out and not space:
            out.append(" ")
            space = True
    return "".join(out).strip()

def rank(region):
    # User locale first; leave the rest as fallbacks, including a single
    # foreign-region scan. A front and back are ranked independently.
    return {"france": 7, "europe": 6, "world": 5,
            "united kingdom": 4, "germany": 4, "belgium": 4,
            "north america": 3, "united states": 3, "canada": 3,
            "italy": 2, "spain": 2}.get(region.casefold().strip(), 1)

def candidates(items, limit=6):
    # Keep alternate images, do not collapse each side to one filename.
    # A region-preferred first choice may only have a tiny CDN thumbnail,
    # so the console is allowed to try the following candidate.
    seen = set()
    result = []
    for _, filename in sorted(items, key=lambda item: (-item[0], item[1])):
        if filename not in seen:
            result.append(filename)
            seen.add(filename)
        if len(result) >= limit:
            break
    return ";".join(result) if result else "-"

# Region metadata is packaged with every image so the console can choose a
# language-appropriate jacket at runtime (including after language changes).
# Keep both EU/FR and North-American editions; do not hardwire French globally.
REGIONS = {
    "france": "fr", "europe": "eu", "world": "world",
    "north america": "us", "united states": "us", "usa": "us",
    "united kingdom": "uk", "england": "uk",
    "canada": "ca", "germany": "de", "belgium": "eu",
    "italy": "it", "spain": "es", "portugal": "pt",
    "australia": "au", "japan": "jp", "brazil": "br",
    "mexico": "mx", "asia": "asia", "korea": "kr",
}
REGION_ORDER = ("fr", "eu", "us", "uk", "ca", "world", "de",
                "es", "it", "pt", "au", "jp", "br", "mx", "asia", "kr", "other")

def region_code(name):
    return REGIONS.get(name.casefold().strip(), "other")

def regional_candidates(items, limit=12):
    # Preserve independent front/back/spine region variants. Cap two sources
    # per region and the total so the on-device index stays small and bounded.
    grouped = {}
    for region, filename in items:
        group = grouped.setdefault(region, [])
        if filename not in group:
            group.append(filename)
    choices = []
    # First cover every available region, then offer its alternate scan.
    # Otherwise two French/European images may displace a Japanese/US face.
    for variant in range(2):
        for region in REGION_ORDER:
            group = grouped.get(region, ())
            if len(group) > variant:
                choices.append(f"{region}:{group[variant]}")
                if len(choices) == limit:
                    return ";".join(choices)
    return ";".join(choices) if choices else "-"

def parse(source):
    games, aliases, images = {}, {}, {}
    iterator = ET.iterparse(source, events=("start", "end"))
    _, root = next(iterator)
    for event, element in iterator:
        if event != "end":
            continue
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "Game":
            if element.findtext("Platform", "") in ("Nintendo Switch", "Nintendo Switch 2"):
                gid = element.findtext("DatabaseID", "")
                if gid.isdecimal():
                    games[gid] = element.findtext("Name", "")
        elif tag == "GameAlternateName":
            gid = element.findtext("DatabaseID", "")
            if gid in games:
                aliases.setdefault(gid, []).append(element.findtext("AlternateName", ""))
        elif tag == "GameImage":
            gid = element.findtext("DatabaseID", "")
            kind = element.findtext("Type", "")
            filename = element.findtext("FileName", "")
            if (gid in games and kind in ("Box - Front", "Box - Back", "Box - Spine",
                                 "Screenshot - Gameplay", "Fanart - Background",
                                 "Screenshot - Game Title")
                    and IMAGE_FILE.fullmatch(filename)):
                images.setdefault(gid, {}).setdefault(kind, []).append(
                    (region_code(element.findtext("Region", "")), filename))
        if tag in ("Game", "GameAlternateName", "GameImage"):
            element.clear()
            root.clear()
    names = {}
    for gid, name in games.items():
        if gid not in images:
            continue
        for label in (name, *aliases.get(gid, ())):
            key = normalize(label)
            if key:
                names.setdefault(key, set()).add(gid)
    lines = ["# Eden Encore retail case index v7 (NS1+NS2, front, back, spine, fanart, game title, gameplay)\n"]
    for key, matching in sorted(names.items()):
        if len(matching) != 1:
            continue  # avoid colliding editions / ambiguous matching
        media = images[next(iter(matching))]
        front = list(media.get("Box - Front", []))
        if next(iter(matching)) in EUROPE_FRONT_PINS:
            pinned = EUROPE_FRONT_PINS[next(iter(matching))]
            front = [("eu", filename) for filename in pinned] + front
        back = media.get("Box - Back", [])
        spine = media.get("Box - Spine", [])
        # Three independently addressable visual categories for a missing back.
        # No longer discard Game Title artwork when fanart also exists.
        fanart = regional_candidates(media.get("Fanart - Background", []))
        title_screen = regional_candidates(media.get("Screenshot - Game Title", []))
        gameplay = regional_candidates(media.get("Screenshot - Gameplay", []))
        if front or back or spine or any(
                v != "-" for v in (fanart, title_screen, gameplay)):
            lines.append(f"{key}\t{regional_candidates(front)}\t{regional_candidates(back)}"
                         f"\t{regional_candidates(spine)}\t{fanart}"
                         f"\t{title_screen}\t{gameplay}\n")
    return "".join(lines)

def build(archive_path):
    with zipfile.ZipFile(archive_path) as archive:
        xml = [item for item in archive.infolist()
               if pathlib.PurePosixPath(item.filename).name.lower() == "metadata.xml"]
        if len(xml) != 1 or xml[0].file_size > 2 * 1024**3:
            raise ValueError("metadata archive missing or oversized")
        with archive.open(xml[0]) as handle:
            return parse(handle)

def download(target):
    request = urllib.request.Request(SOURCE, headers={"User-Agent": "EdenEncore-IndexBuilder/1.0"})
    with urllib.request.urlopen(request, timeout=40) as response, target.open("wb") as output:
        total = 0
        while block := response.read(1024 * 1024):
            total += len(block)
            if total > 220 * 1024 * 1024:
                raise ValueError("metadata archive exceeded 220 MiB")
            output.write(block)

def self_test():
    sample = """<LaunchBox>
    <Game><DatabaseID>1</DatabaseID><Platform>Nintendo Switch</Platform><Name>Example: Journey</Name></Game>
    <Game><DatabaseID>2</DatabaseID><Platform>Sony Playstation 5</Platform><Name>Example: Journey</Name></Game>
    <Game><DatabaseID>5</DatabaseID><Platform>Nintendo Switch 2</Platform><Name>Example: Next Gen</Name></Game>
    <Game><DatabaseID>3</DatabaseID><Platform>Nintendo Switch</Platform><Name>Ambiguous</Name></Game>
    <Game><DatabaseID>4</DatabaseID><Platform>Nintendo Switch</Platform><Name>Ambiguous</Name></Game>
    <GameImage><DatabaseID>1</DatabaseID><Type>Box - Front</Type><Region>World</Region><FileName>11111111-1111-1111-1111-111111111111.jpg</FileName></GameImage>
    <GameImage><DatabaseID>1</DatabaseID><Type>Box - Front</Type><Region>Europe</Region><FileName>22222222-2222-2222-2222-222222222222.png</FileName></GameImage>
    <GameImage><DatabaseID>1</DatabaseID><Type>Box - Back</Type><Region>France</Region><FileName>33333333-3333-3333-3333-333333333333.jpg</FileName></GameImage>
    <GameImage><DatabaseID>1</DatabaseID><Type>Box - Spine</Type><Region>Europe</Region><FileName>77777777-7777-7777-7777-777777777777.png</FileName></GameImage>
    <GameImage><DatabaseID>1</DatabaseID><Type>Screenshot - Gameplay</Type><Region>World</Region><FileName>88888888-8888-8888-8888-888888888888.jpg</FileName></GameImage>
    <GameImage><DatabaseID>1</DatabaseID><Type>Screenshot - Gameplay</Type><Region>World</Region><FileName>99999999-9999-9999-9999-999999999999.jpg</FileName></GameImage>
    <GameImage><DatabaseID>1</DatabaseID><Type>Fanart - Background</Type><Region>World</Region><FileName>aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.png</FileName></GameImage>
    <GameImage><DatabaseID>1</DatabaseID><Type>Screenshot - Game Title</Type><Region>World</Region><FileName>bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.jpg</FileName></GameImage>
    <GameImage><DatabaseID>2</DatabaseID><Type>Box - Back</Type><FileName>44444444-4444-4444-4444-444444444444.jpg</FileName></GameImage>
    <GameImage><DatabaseID>5</DatabaseID><Type>Box - Front</Type><Region>Europe</Region><FileName>r2_22222222-2222-2222-2222-222222222222.png</FileName></GameImage>
    <GameImage><DatabaseID>5</DatabaseID><Type>Box - Back</Type><Region>North America</Region><FileName>r2_33333333-3333-3333-3333-333333333333.jpg</FileName></GameImage>
    <GameImage><DatabaseID>5</DatabaseID><Type>Box - Spine</Type><Region>North America</Region><FileName>r2_77777777-7777-7777-7777-777777777777.jpg</FileName></GameImage>
    <GameImage><DatabaseID>5</DatabaseID><Type>Fanart - Background</Type><Region>World</Region><FileName>r2_aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.png</FileName></GameImage>
    <GameImage><DatabaseID>3</DatabaseID><Type>Box - Back</Type><FileName>55555555-5555-5555-5555-555555555555.jpg</FileName></GameImage>
    <GameImage><DatabaseID>4</DatabaseID><Type>Box - Back</Type><FileName>66666666-6666-6666-6666-666666666666.jpg</FileName></GameImage>
    <GameAlternateName><DatabaseID>1</DatabaseID><AlternateName>Example Voyage</AlternateName></GameAlternateName>
    </LaunchBox>"""
    result = parse(io.BytesIO(sample.encode()))
    assert "example journey\t" in result and "eu:22222222" in result
    assert "world:11111111" in result
    assert "example voyage\t" in result and "eu:22222222" in result
    assert "fr:33333333-3333-3333-3333-333333333333.jpg" in result
    assert "ambiguous\t" not in result and "44444444" not in result
    assert "example next gen\t" in result
    ns2 = next(row.split("\t") for row in result.splitlines()
               if row.startswith("example next gen\t"))
    assert ns2[1].startswith("eu:r2_22222222"), ns2
    assert ns2[2].startswith("us:r2_33333333"), ns2
    assert ns2[3].startswith("us:r2_77777777"), ns2
    assert ns2[4].startswith("world:r2_aaaaaaaa"), ns2
    assert "eu:77777777-7777-7777-7777-777777777777.png" in result
    fields = next(row.split("\t") for row in result.splitlines()
                  if row.startswith("example journey\t"))
    assert len(fields) == 7, fields
    assert fields[4].startswith("world:aaaaaaaa"), fields
    assert fields[5].startswith("world:bbbbbbbb"), fields
    assert fields[6].startswith("world:88888888"), fields
    assert "99999999" in fields[6], fields
    assert "Box - 3D" not in result
    assert candidates([(7, "f" * 36 + ".jpg"), (1, "0" * 36 + ".png")]).count(";") == 1
    assert candidates([(1, "a" * 36 + ".jpg")]) == "a" * 36 + ".jpg"
    assert rank("France") > rank("Europe") > rank("World") > rank("Japan")
    assert regional_candidates([("eu", EUROPE_FRONT_PINS["79189"][0]),
                                ("us", "0" * 36 + ".jpg")]).startswith(
        "eu:9524e5f7-ccc8-4ce6-a581-03f82c51825e.jpg")
    assert "us:" in regional_candidates([("eu", EUROPE_FRONT_PINS["79189"][0]),
                                         ("us", "0" * 36 + ".jpg")])
    assert normalize("EA SPORTS FC 27!") == "ea sports fc 27"
    print("PASS NS1+NS2 regional case index, independent front/back/spine, collision guards")

def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--download", action="store_true")
    cli.add_argument("--zip", type=pathlib.Path)
    cli.add_argument("--output", type=pathlib.Path)
    cli.add_argument("--self-test", action="store_true")
    args = cli.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.output:
        cli.error("--output is required")
    archive = args.zip or pathlib.Path("/tmp/encore-metadata.zip")
    if args.download:
        download(archive)
    result = build(archive)
    # The packaged index reports each actual LaunchBox media category, not
    # just the total number of matching Switch title names.
    rows = [row.split("\t") for row in result.splitlines()
            if row and not row.startswith("#")]
    coverage = tuple(sum(len(row) == 7 and row[col] != "-"
                         for row in rows) for col in (4, 5, 6))
    print("EDEN_CASE_INDEX_MEDIA fanart={} game_title={} gameplay={} titles={}".format(
        *coverage, len(rows)), flush=True)
    if result.count("\n") < 20:
        raise ValueError("No usable game data; index not installed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pending = args.output.with_suffix(".tmp")
    pending.write_text(result, encoding="utf-8")
    pending.replace(args.output)
    print(f"Retail case index: {result.count(chr(10)) - 1} names, {len(result)} bytes")

if __name__ == "__main__":
    main()
