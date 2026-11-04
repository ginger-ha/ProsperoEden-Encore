#!/usr/bin/env python3
"""P1.2/P2.7 syntax-check real GPU worker with ordered native headers; no PS5 build."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
roots=['vendor/encore-active/ns2-runtime/gpu_access_svc',
       'vendor/encore-active/ns2-runtime/nvdrv_as',
       'vendor/encore-active/ns2-runtime/gpu_session',
       'vendor/encore-active/ns2-runtime/hle',
       'vendor/encore-active/ns2-runtime/nvdrv',
       'vendor/sources/eden/src',
       'vendor/sources/fmt/include',
       'vendor/encore-active/ns2-helpers/include']
inc=['-I'+str(ROOT/r) for r in roots]
assert all((ROOT/r).exists() for r in roots)
if sys.platform=='darwin':
    caches=sorted((Path.home()/'.cache').glob('ps5-eden-*/source/.cache/cpm/boost/boost-*/libs'))
    assert caches, 'Modular Boost headers missing on local macOS audit'
    inc.extend('-I'+str(p) for p in sorted(caches[-1].rglob('include')) if (p/'boost').is_dir())
compiler=shutil.which('clang++') or shutil.which('g++')
assert compiler, 'C++20 compiler required'
args=[compiler,'-std=c++20','-fsyntax-only','-Wno-unused-parameter','-DFMT_HEADER_ONLY']
if sys.platform=='darwin':
    sdk=Path('/Library/Developer/CommandLineTools/SDKs/MacOSX27.0.sdk')
    assert sdk.exists(), 'C++20 std::jthread requires installed macOS SDK 27'
    args+=['-target','x86_64-apple-macosx15.0','-isysroot',str(sdk)]
owner=ROOT/'vendor/encore-active/ns2-runtime/gpu_session/core/hle/service/am/service/gpu_worker.cpp'
args+=inc+[str(owner)]
result=subprocess.run(args,env=dict(os.environ),capture_output=True,text=True,timeout=100)
if result.returncode:
    print(result.stderr[-5500:],file=sys.stderr)
    raise SystemExit(result.returncode)
print('P1_2_P2_7_REAL_GPU_WORKER_CPP20_SYNTAX_PASS overlays=3 PS5_build=OFF')
