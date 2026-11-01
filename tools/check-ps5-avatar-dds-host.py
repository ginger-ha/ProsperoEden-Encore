#!/usr/bin/env python3
"""Host-only source-derived check of the active-user DDS avatar fallback."""
import os
import pathlib
import struct
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
HEADER = ROOT / "headless/prosperoeden/pe/gfx/image.cpp"
SERVICE = (ROOT / "headless/prosperoeden/eden_services.cpp").read_text()
assert HEADER.exists()
assert 'sceUserServiceGetForegroundUser(&user_id)' in SERVICE
assert 'avatar128.dds' in SERVICE
assert 'bool IsDecodableAvatarFile(const std::string& path)' in SERVICE
assert 'stbi_info(path.c_str(), &width, &height, &channels)' in SERVICE
assert 'pe::gfx::load_avatar_dds(path, &decoded)' in SERVICE
profile_selection = SERVICE.split('std::string EdenServices::profile_avatar()', 1)[1].split('unsigned EdenServices::controllers()', 1)[0]
assert profile_selection.count('IsDecodableAvatarFile(') == 4
assert 'IsReadableAvatarFile(' not in profile_selection
assert 'status=png_decode_failed fallback=dds' in SERVICE
assert 'load_avatar_dds(resolved, image)' in SERVICE

# The native profile is resolved periodically, with image-source revision
# tracking for profile switches and the optional NiakPS5 ownership stage.
launcher_cpp = (ROOT / "headless/prosperoeden/pe/ui/launcher.cpp").read_text()
launcher_hpp = (ROOT / "headless/prosperoeden/pe/ui/launcher.hpp").read_text()
assert "profile_avatar_refresh_elapsed_ >= 5.0f" in launcher_cpp
assert "textures_.invalidate(profile_avatar_path_)" in launcher_cpp
assert "probe.inode" in launcher_cpp and "probe.mtime" in launcher_cpp
assert "avatar_owner_marker_matches" in SERVICE
assert "ProfileAvatarProbe" in launcher_hpp
def dds(w, h, payload, fmt, masks=(0, 0, 0, 0)):
    header = bytearray(128)
    struct.pack_into('<I', header, 0, 0x20534444)
    struct.pack_into('<I', header, 4, 124)
    struct.pack_into('<I', header, 8, 0x1007)
    struct.pack_into('<II', header, 12, h, w)
    struct.pack_into('<I', header, 76, 32)
    struct.pack_into('<I', header, 84, fmt)
    struct.pack_into('<I', header, 88, 32 if fmt == 0 else 0)
    for idx, value in enumerate(masks):
        struct.pack_into('<I', header, 92 + idx * 4, value)
    return bytes(header) + payload

with tempfile.TemporaryDirectory(prefix="encore-avatar-") as tmp:
    p = pathlib.Path(tmp)
    red = struct.pack('<HHI', 0xf800, 0x001f, 0)
    (p / 'bc1.dds').write_bytes(dds(4, 4, red, 0x31545844))
    (p / 'bc2.dds').write_bytes(dds(4, 4, bytes([255]) * 8 + red, 0x33545844))
    (p / 'bc3.dds').write_bytes(dds(4, 4, bytes([255, 0]) + bytes([0]) * 6 + red, 0x35545844))
    (p / 'bgra.dds').write_bytes(dds(2, 2, bytes([0, 0, 255, 255]) * 4, 0,
                                  (0x00ff0000, 0x0000ff00, 0x000000ff, 0xff000000)))
    (p / 'truncated.dds').write_bytes(dds(4, 4, b'', 0x31545844))
    (p / 'oversized.dds').write_bytes(dds(1024, 4, red, 0x31545844))
    cpp = p / 'fixture.cpp'
    cpp.write_text(r'''
#include "pe/gfx/image.hpp"
#include <cassert>
int main(int argc, char** argv) {
    assert(argc == 7);
    for (int i = 1; i <= 4; ++i) {
        pe::gfx::Image image;
        assert(pe::gfx::load_avatar_dds(argv[i], &image));
        assert(image.width == (i == 4 ? 2 : 4));
        assert(image.height == (i == 4 ? 2 : 4));
        assert(image.rgba[0] == 255);
        assert(image.rgba[1] == 0 && image.rgba[2] == 0);
        assert(image.rgba[3] == 255);
    }
    for (int i = 5; i <= 6; ++i) {
        pe::gfx::Image image;
        assert(!pe::gfx::load_avatar_dds(argv[i], &image));
        assert(image.empty());
    }
}
''')
    binary = p / 'fixture'
    subprocess.run(['g++', '-std=c++20', '-O1', '-g', '-Wall', '-Wextra',
                    '-I', str(ROOT / 'headless/prosperoeden'), str(cpp), str(ROOT / 'headless/prosperoeden/pe/gfx/image.cpp'),
                    '-o', str(binary)], check=True)
    env = dict(os.environ)
    subprocess.run([str(binary), *[str(p / n) for n in
                    ('bc1.dds', 'bc2.dds', 'bc3.dds', 'bgra.dds',
                     'truncated.dds', 'oversized.dds')]], check=True, env=env)
print('AVATAR_DDS_HOST_OK formats=BC1,BC2,BC3,BGRA invalid=2')


# Compile the real, read-only marker parser and exercise same-user, other-user,
# corrupt marker, format mismatch and symlink denial without a PS5.
with tempfile.TemporaryDirectory(prefix="encore-avatar-owner-") as tmp:
    p = pathlib.Path(tmp)
    marker = p / "owner.txt"
    marker.write_text("0x12345678 png\n")
    fixture = p / "marker.cpp"
    fixture.write_text(r"""
#include "ps5_profile_avatar_staging.hpp"
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <unistd.h>
int main(int argc, char** argv) {
    assert(argc == 4);
    auto match = [](const char* p, std::uint32_t user, const char* type) {
        return pe::ps5::avatar_owner_marker_matches(p, user, type);
    };
    assert(match(argv[1], 0x12345678u, "png"));
    assert(!match(argv[1], 0x12345679u, "png"));
    assert(!match(argv[1], 0x12345678u, "dds"));
    assert(!match(argv[2], 0x12345678u, "png"));
    assert(!match(argv[3], 0x12345678u, "png"));
}
""")
    corrupt = p / "owner-corrupt.txt"
    corrupt.write_text("0x12345678 png\ntrailer")
    symlink = p / "owner-link.txt"
    symlink.symlink_to(marker)
    binary = p / "marker-test"
    subprocess.run(["g++", "-std=c++20", "-Wall", "-Wextra", "-Werror",
                    "-I", str(ROOT / "headless/prosperoeden"), str(fixture),
                    "-o", str(binary)], check=True)
    subprocess.run([str(binary), str(marker), str(symlink), str(corrupt)], check=True)
