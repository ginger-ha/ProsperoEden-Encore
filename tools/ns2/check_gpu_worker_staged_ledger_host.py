#!/usr/bin/env python3
"""P1.2/P4.2 actual 211/214 ledger node lifetime and GMMU commit ordering."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
OWNER=ROOT/'vendor/encore-active/ns2-runtime/gpu_session/core/hle/service/am/service/gpu_worker.cpp'
HEADER=ROOT/'vendor/encore-active/ns2-runtime/hle/core/hle/service/am/service/gpu_worker_protocol.h'
source=OWNER.read_text()
assert source.count('m_mappings.PrepareMapped(*request, staged_ledger)')==1
assert source.count('m_mappings.PrepareSparse(')==1
assert source.count('m_mappings.CommitPrepared(staged_ledger)')==2
normal=source.split('void IGpuWorker::NormalMapGpuMemory4K(',1)[1].split(
    'void IGpuWorker::NormalModifyGpuMemory4K(',1)[0]
sparse=source.split('void IGpuWorker::CreateSparseRegion(',1)[1].split(
    'void IGpuWorker::DestroySparseRegion(',1)[0]
for owner in (normal,sparse):
    assert owner.index('m_mappings.Prepare')<owner.index('m_mappings.CommitPrepared(')
    assert 'm_mappings.RecordMapped(' not in owner
    assert 'm_mappings.RecordSparse(' not in owner
assert normal.index('m_mappings.PrepareMapped(')<normal.index('as->MapNative4K(')
assert normal.index('as->MapNative4K(')<normal.index('m_mappings.CommitPrepared(')
assert sparse.index('m_mappings.PrepareSparse(')<sparse.index('as->ReserveNativeSparse4K(')
assert sparse.index('as->ReserveNativeSparse4K(')<sparse.index('m_mappings.CommitPrepared(')
assert 'mappings.merge(pending);' in HEADER.read_text()
assert 'catch (const std::bad_alloc&)' in HEADER.read_text()
env=dict(os.environ)
sdk=Path('/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk')
if sdk.exists():env['SDKROOT']=str(sdk)
compilers=list(dict.fromkeys(filter(None,(shutil.which('clang++'),shutil.which('g++')))))
assert compilers
with tempfile.TemporaryDirectory(prefix='encore-gpu-worker-ledger-') as temp:
    for compiler in compilers:
        for opt in (0,2):
            exe=Path(temp)/f'{Path(compiler).name}-{opt}'
            cmd=[compiler,'-std=c++20',f'-O{opt}','-Wall','-Wextra',
                 '-Werror','-pedantic','-fsanitize=undefined',
                 '-fno-sanitize-recover=all',
                 '-I'+str(ROOT/'vendor/encore-active/ns2-runtime/hle'),
                 '-I'+str(ROOT/'vendor/encore-active/ns2-runtime/nvdrv'),
                 '-I'+str(ROOT/'vendor/sources/eden/src'),
                 str(ROOT/'tools/ns2/test_gpu_worker_staged_ledger.cpp'),
                 '-o',str(exe)]
            built=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=50)
            assert built.returncode==0,(compiler,built.stderr[-3500:])
            run=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=25)
            assert run.returncode==0,(compiler,run.stderr[-3500:])
            print('P1_2_GPU_WORKER_STAGED_LEDGER_PASS',Path(compiler).name,
                  f'O{opt}', '211=atomic','214=atomic','NS1=untouched',flush=True)
