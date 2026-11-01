#!/usr/bin/env python3
"""Verify NSZ/XCZ source owners and standard Library extensions."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
pinned=root/"vendor/sources/eden/src/core"
active=root/"vendor/encore-active/eden-core/src/core"
pairs=[
 ("file_sys/submission_package.cpp","0ea323492b914f05d45548cf90b912e00e610431","Ncz::Open"),
 ("file_sys/card_image.cpp","593c561689f1790b8c8ab673f3dd44d3d790f553","Ncz::Open"),
 ("loader/loader.cpp","90e23ccc11fb03672b22d169210dec6554e67f71","extension == \"xcz\""),
 ("loader/nsp.cpp","cfc908b4ef6e1b02636d88815aa5469052575784","\".ncz\""),
 ("file_sys/registered_cache.cpp","ce851e4d38ba752c626f51e29bae4d2303dbd39c","extension == \"nsz\""),
]
# Each maintained owner must match its immutable pinned counterpart with
# exactly one reviewed replacement: no hidden unrelated source edits.
expected_deltas = [["file_sys/submission_package.cpp","                auto next_file = pfs->GetFile(fmt::format(\"{}.nca\", id_string));","                auto next_file = pfs->GetFile(fmt::format(\"{}.nca\", id_string));\n                if (next_file == nullptr)\n                    next_file = ::Eden::Ncz::Open(pfs->GetFile(fmt::format(\"{}.ncz\", id_string)));",1],["file_sys/card_image.cpp","    for (const VirtualFile& partition_file : partition->GetFiles()) {\n        if (partition_file->GetExtension() != \"nca\") {","    for (const VirtualFile& listed_file : partition->GetFiles()) {\n        const VirtualFile partition_file =\n            listed_file->GetExtension() == \"ncz\" ? ::Eden::Ncz::Open(listed_file) : listed_file;\n        if (partition_file == nullptr || partition_file->GetExtension() != \"nca\") {",1],["loader/loader.cpp","    else if (extension == \"xci\")\n        return FileType::XCI;\n    else if (extension == \"nsp\")\n        return FileType::NSP;","    else if (extension == \"xci\" || extension == \"xcz\")\n        return FileType::XCI;\n    else if (extension == \"nsp\" || extension == \"nsz\")\n        return FileType::NSP;",0],["loader/nsp.cpp","        if (name.size() >= 4 && name.substr(name.size() - 4) == \".nca\") {","        if (name.size() >= 4 &&\n            (name.substr(name.size() - 4) == \".nca\" || name.substr(name.size() - 4) == \".ncz\")) {",0],["file_sys/registered_cache.cpp","        if (extension == \"nsp\") {\n            ProcessNSP(file);\n        } else if (extension == \"xci\") {\n            ProcessXCI(file);","        if (extension == \"nsp\" || extension == \"nsz\") {\n            ProcessNSP(file);\n        } else if (extension == \"xci\" || extension == \"xcz\") {\n            ProcessXCI(file);",0]]
assert {rel for rel, *_ in expected_deltas} == {rel for rel, *_ in pairs}

for rel,sha,marker in pairs:
    raw=(pinned/rel).read_bytes()
    digest=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    assert digest==sha,("Pinned Eden changed",rel)
    text=(active/rel).read_text()
    old, new, header = next((a,b,c) for item,a,b,c in expected_deltas if item==rel)
    assert raw.decode().count(old)==1,("pinned source changed",rel)
    expected=raw.decode().replace(old,new)
    if rel=="loader/loader.cpp":
        # Preserve the existing NAX delta and reconstruct both reviewed
        # ExeFS-main identification changes exactly; no audit waiver.
        nax_before='    else if (extension == "nca")\\n        return FileType::NCA;'
        nax_after=nax_before+'\\n    else if (extension == "nax")\\n        return FileType::NAX;'
        assert expected.count(nax_before)==1
        expected=expected.replace(nax_before,nax_after)
        old_head="FileType IdentifyFile(FileSys::VirtualFile file) {\n    if (const auto nsp_type = IdentifyFileLoader<AppLoader_NSP>(file)) {"
        new_head="FileType IdentifyFile(FileSys::VirtualFile file) {\n    // An ExeFS/main with its owning directory must use the directory loader.\n    // Generic NSO detection otherwise loses main.npdm identity and skips rtld/sdk.\n    // The directory validator keeps standalone NSOs on the NSO loader.\n    if (file->GetName() == \"main\") {\n        if (const auto romdir_type =\n                IdentifyFileLoader<AppLoader_DeconstructedRomDirectory>(file))\n            return *romdir_type;\n    }\n    if (const auto nsp_type = IdentifyFileLoader<AppLoader_NSP>(file)) {"
        old_tail="    } else if (const auto romdir_type =\n                   IdentifyFileLoader<AppLoader_DeconstructedRomDirectory>(file)) {\n        return *romdir_type;\n    } else {\n        return FileType::Unknown;\n    }"
        new_tail="    } else {\n        return FileType::Unknown;\n    }"
        assert expected.count(old_head)==1 and expected.count(old_tail)==1
        expected=expected.replace(old_head,new_head).replace(old_tail,new_tail)
    if rel == "file_sys/registered_cache.cpp":
        # Reviewed second delta: when add-on providers scan an extracted
        # title folder, never enumerate potentially enormous romfs/exefs
        # directory trees looking for packaged NSP/XCI files.
        original='    for (const auto& subdir : dir->GetSubdirectories()) {\n        ScanDirectory(subdir);\n    }'
        guarded=('    for (const auto& subdir : dir->GetSubdirectories()) {\n'
                 '        // Package scanning may start at a mixed extracted-title add-on root.\n'
                 '        // Never recursively enumerate large unpacked RomFS/ExeFS payloads:\n'
                 '        // extracted overlays have their own loader route, while packaged\n'
                 '        // updates/DLC are identified from NSP/XCI metadata here.\n'
                 '        const auto name = Common::ToLower(subdir->GetName());\n'
                 '        if (name == "romfs" || name == "exefs")\n'
                 '            continue;\n'
                 '        ScanDirectory(subdir);\n'
                 '    }')
        assert expected.count(original) == 1, "expected pinned external scanner changed"
        expected = expected.replace(original, guarded)
    if header:
        expected=expected.replace('#include <memory>', '#include <memory>\n#include "ncz_vfs.h"')
        if '#include "ncz_vfs.h"' not in expected:
            expected='#include "ncz_vfs.h"\n'+expected
    assert text==expected,("unreviewed source change",rel)
    assert marker in text,rel
    print("NCZ_SOURCE_OWNER_PASS",rel)
cmake=(root/"headless/CMakeLists.txt").read_text()
segment=cmake.split("# NSZ/XCZ: select reviewed full C++ source owners",1)[1].split("# Extracted AOC:",1)[0]
assert "write_derived" not in segment
assert segment.count("list(REMOVE_ITEM core_sources")==1
assert "ncz.cpp" in cmake.split("# Extracted AOC:",1)[1].split("# The guest title is the owner",1)[0]
aoc_segment=cmake.split("# Extracted AOC:",1)[1].split('list(APPEND core_sources "${EDEN_PORT_DIR}/ncz.cpp")',1)[0]
assert "write_derived" not in aoc_segment
assert aoc_segment.count("list(REMOVE_ITEM core_sources")==1
for rel in ("file_sys/romfs_factory.cpp", "hle/service/aoc/addon_content_manager.cpp"):
    assert '"' + rel + '"' in aoc_segment
for rel,_,_ in pairs: assert '"'+rel+'"' in segment
for path in ["headless/main.cpp","headless/settings_store.h",
             "headless/prosperoeden/eden_services.cpp"]:
    data=(root/path).read_text()
    assert (".nsz" in data or "IsGameFile" in data) and (".xcz" in data or "IsGameFile" in data),path
# The metadata bridge intentionally delegates extension matching to the
# central case-insensitive package/card predicates; demanding a literal
# '.nsz' token would reject the *correct* implementation.
metadata_source=(root/"headless/metadata_bridge.cpp").read_text()
assert "Eden::IsPackageFile(path)" in metadata_source
assert "Eden::IsCardImageFile(path)" in metadata_source
main=(root/"headless/main.cpp").read_text()
assert "Eden::Ncz::SetUnpackFolder(" in main
assert "Eden::Ncz::SetUnpackAllowed(true);" in main
assert main.count("Eden::Ncz::SetUnpackAllowed(false);")>=2
# The game format matrix must be wired through every end-user entrypoint,
# not only the file picker. Direct inputs do NOT get NSP/XCI metadata parsing.
library=(root/"headless/prosperoeden/eden_services.cpp").read_text()
# The TV scanner also accepts validated ExeFS folders, so it must use
# ValidRomFilename rather than the old extension-only IsGameFile gate.
assert "if (!Eden::ValidRomFilename(file)) continue;" in library
assert "Eden::FindDeconstructedGameMain(entry.path())" in library
assert 'format != "NSP" && format != "XCI"' not in library
assert "game.format = format;" in library
formats=(".nsp",".xci",".nsz",".xcz",".nro",".nso",".nca",".nax",".kip")
counter=library.split("const int regular = CountFiles(",1)[1].split(");",1)[0]
assert "const int extracted = CountExeFsFolders(roms_path);" in library
exefs_counter = library.split("int CountExeFsFolders(", 1)[1].split("unsigned int HashPath(", 1)[0]
assert "ListEntries(directory, true, ok)" in exefs_counter
assert "info.games = regular < 0 || extracted < 0 ? -1 : regular + extracted;" in library
for extension in formats:
    assert '"'+extension+'"' in counter, ("format missing from folder count",extension)
metadata=(root/"headless/metadata_bridge.cpp").read_text()
assert "if (!Eden::IsPackageFile(path) && !Eden::IsCardImageFile(path)) return 0;" in metadata
loader=(active/"loader/loader.cpp").read_text()
assert 'extension == "nax"' in loader
assert 'extension == "nsz"' in loader and 'extension == "xcz"' in loader
cpp=r"""
#include <cassert>
#include "game_files.h"
int main() {
    for(auto name:{"game.nsp","game.xci","game.nsz","game.xcz","GAME.NSP","GAME.XCI","GAME.NSZ","GAME.XCZ",
                   "program.nro","program.nso","program.nca","program.nax","program.kip",
                   "PROGRAM.NRO","PROGRAM.NSO","PROGRAM.NCA","PROGRAM.NAX","PROGRAM.KIP"})
        assert(Eden::IsGameFile(name));
    for(auto name:{"","game.zstd","game.zbic","game.lz4","game.ncz","game.nsp.bak","main"})
        assert(!Eden::IsGameFile(name));
    assert(Eden::IsPackageFile("game.NSZ"));
    assert(Eden::IsCardImageFile("game.XCZ"));
    assert(Eden::IsDirectLoaderFile("game.KIP"));
}
"""
compiler=shutil.which("clang++") or shutil.which("g++") or shutil.which("c++")
assert compiler
with tempfile.TemporaryDirectory() as d:
    path=Path(d)/"game.cpp"
    path.write_text(cpp)
    exe=Path(d)/"check"
    result=subprocess.run([compiler,"-std=c++20","-O2","-Wall","-Wextra","-Werror",
                           "-I"+str(root/"headless"),str(path),"-o",str(exe)],
                          capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stderr
    subprocess.run([str(exe)],check=True,timeout=12)
assert "O_NOFOLLOW" in (root/"headless/ncz.h").read_text()
assert "O_CREAT | O_EXCL" in (root/"headless/ncz.h").read_text()
assert "find_first_of" in (root/"headless/ncz.cpp").read_text()
print("NCZ_FORMATS_AND_SELECTION_PASS")
