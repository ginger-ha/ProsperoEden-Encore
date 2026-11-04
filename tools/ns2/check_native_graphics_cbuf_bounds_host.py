#!/usr/bin/env python3
"""P2.4 real NS2 graphics CBUF 64-KiB window and mapped 49-bit VA preflight."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
OWNER=ROOT/'vendor/encore-active/ns2-runtime/ampere/video_core/native_shader_capture.cpp'
HEADER=ROOT/'vendor/encore-active/ns2-runtime/ampere/video_core/native_graphics_cbuf_bounds.h'
TEST=ROOT/'tools/ns2/test_native_graphics_cbuf_bounds.cpp'
source=OWNER.read_text()
assert source.count('NativeGraphicsCbufWordAdmissible(')==1
assert source.index('NativeGraphicsCbufWordAdmissible(') < source.index('IsFullyMappedRange(address, sizeof(u32))')
assert 'cbuf.enabled, cbuf.address, cbuf.size, offset' in source
assert HEADER.is_file()
env=dict(os.environ)
sdk=Path('/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk')
if sdk.exists(): env['SDKROOT']=str(sdk)
with tempfile.TemporaryDirectory(prefix='encore-graphics-cbuf-') as temp:
    compilers=list(dict.fromkeys(filter(None,(shutil.which('clang++'),shutil.which('g++')))))
    assert compilers
    for compiler in compilers:
        for opt in (0,2):
            exe=Path(temp)/f'{Path(compiler).name}-{opt}'
            args=[compiler,'-std=c++20',f'-O{opt}','-Wall','-Wextra',
                  '-Werror','-pedantic','-fsanitize=undefined',
                  '-fno-sanitize-recover=all',
                  '-I'+str(HEADER.parents[1]),str(TEST),'-o',str(exe)]
            built=subprocess.run(args,capture_output=True,text=True,env=env,timeout=45)
            assert built.returncode==0,(compiler,built.stderr[-3000:])
            run=subprocess.run([str(exe)],capture_output=True,text=True,env=env,timeout=15)
            assert run.returncode==0,(compiler,run.stderr[-2000:])
            print('P2_4_AMPERE_GRAPHICS_CBUF_49BIT_WINDOW_PASS',Path(compiler).name,
                  f'O{opt}', '64KiB=bounded', 'NS1=unchanged',flush=True)
