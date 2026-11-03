#!/usr/bin/env python3
"""Verify the shipping GPU worker and headers against actual native CMake copies.

The previous GPU synthesis in the non-native else branch was unreachable.
The four tracked Encore files, not a reconstructed generator, are authority.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'vendor/sources/eden'
TARGET = ROOT / 'vendor/encore-active/eden-gpu'
CMAKE_SOURCE = ROOT / 'headless/CMakeLists.txt'


def expected_files() -> dict[str, bytes]:
    names = (
        'gpu_thread_quiet.cpp', 'gpu_thread_dev.cpp',
        'include/video_core/gpu_thread.h', 'include/common/bounded_threadsafe_queue.h',
    )
    present = {str(p.relative_to(TARGET)) for p in TARGET.rglob('*') if p.is_file()}
    assert present == set(names), (present - set(names), set(names) - present)
    result = {name: (TARGET / name).read_bytes() for name in names}
    queue = result['include/common/bounded_threadsafe_queue.h']
    assert b'union Slot {' in queue
    assert b'std::array<Slot, Capacity> m_data;' in queue
    assert queue.count(
        b'std::construct_at(std::addressof(m_data[pos].value)') == 2
    assert queue.count(
        b'std::destroy_at(std::addressof(m_data[pos].value));') == 1
    assert queue.count(
        b'std::destroy_at(std::addressof(m_data[cursor % Capacity].value));') == 1
    assert b'std::destroy_at(std::addressof(m_data[pos]));' not in queue
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--materialize', action='store_true')
    args = parser.parse_args()
    generated = expected_files()
    if args.materialize:
        print('Sources maintained in encore-active: no regeneration permitted.')
    present = {str(p.relative_to(TARGET)): p for p in TARGET.rglob('*') if p.is_file()}
    assert present.keys() == generated.keys(), (generated.keys() - present.keys(), present.keys() - generated.keys())
    for relative, content in generated.items():
        assert present[relative].read_bytes() == content, f'R345 maintained GPU source mismatch: {relative}'
    assert b'SPSCQueue<CommandDataContainer, 256>' in generated['include/video_core/gpu_thread.h']
    assert b'EmplaceWaitWithStopToken' in generated['include/common/bounded_threadsafe_queue.h']
    assert b'DiagnosticTimer' in generated['gpu_thread_dev.cpp']
    assert b'DiagnosticTimer' not in generated['gpu_thread_quiet.cpp']
    # The historical headless/native_gpu_thread.inc was already byte-identical
    # to the common tail of both maintained full compilation units. It must
    # never return as a parallel third implementation of the native worker.
    marker = b'#include <memory>\\n'.replace(b'\\n', b'\n')
    quiet, dev = (generated[f'gpu_thread_{kind}.cpp'] for kind in ('quiet', 'dev'))
    assert quiet.count(marker) == dev.count(marker) == 1
    native_quiet = quiet[quiet.index(marker):]
    native_dev = dev[dev.index(marker):]
    assert native_quiet == native_dev, 'GPU worker lifecycle differs across maintained variants'
    assert native_quiet.count(b'void ThreadManager::StartThread(') == 1
    assert native_quiet.count(b'void ThreadManager::Stop()') == 1
    assert b'pthread_join(thread, nullptr)' in native_quiet
    assert not (ROOT / 'headless/native_gpu_thread.inc').exists(), 'obsolete duplicate GPU worker reintroduced'
    cmake = CMAKE_SOURCE.read_text()
    assert 'vendor/encore-active/eden-gpu' in cmake
    assert cmake.count('configure_file("${EDEN_ACTIVE_GPU}/') == 3
    assert 'EDEN_GPU_WORKER_VARIANT "gpu_thread_dev.cpp"' in cmake
    assert 'EDEN_GPU_WORKER_VARIANT "gpu_thread_quiet.cpp"' in cmake
    assert 'write_derived("${PORT_BUILD_DIR}/gpu_thread.cpp"' not in cmake
    assert 'write_derived("${PORT_BUILD_DIR}/include/common/bounded_threadsafe_queue.h"' not in cmake
    # Execute the real PS5 CMake path in script mode, not merely a source-text
    # assertion: the resulting compiler inputs must match both committed
    # variants, and none may require the historical replacement pipeline.
    marker='    if(PS5_NATIVE)\n        set(EDEN_ACTIVE_GPU'
    after='    else()\n    # PS5 GPU queue is already copied from the complete eden-gpu source above.'
    assert cmake.count(marker)==cmake.count(after)==1
    native=cmake[cmake.index(marker):cmake.index(after,cmake.index(marker))]+'    endif()\n'
    with tempfile.TemporaryDirectory(prefix='eden-gpu-cmake-contract-') as d:
        work=Path(d)
        for profile in ('dev','quiet'):
            build=work/profile
            build.mkdir()
            script=work/f'{profile}.cmake'
            script.write_text(f'cmake_minimum_required(VERSION 3.25)\n'
                              f'set(PORT_ROOT "{ROOT.as_posix()}")\n'
                              f'set(PORT_BUILD_DIR "{build.as_posix()}")\n'
                              f'set(PS5_NATIVE ON)\n'
                              f'set(EDEN_DEV_PROFILE {"ON" if profile=="dev" else "OFF"})\n'
                              f'set(video_sources "gpu_thread.cpp")\n'
                              f'set(gpu_source "original")\n'+native)
            subprocess.run(['cmake','-P',str(script)],cwd=ROOT,check=True,timeout=30)
            assert (build/'gpu_thread.cpp').read_bytes()==generated[f'gpu_thread_{profile}.cpp']
            for name in ('include/video_core/gpu_thread.h', 'include/common/bounded_threadsafe_queue.h'):
                assert (build/name).read_bytes()==generated[name], (profile,name)
    print('VENDORED_GPU_CMAKE_NATIVE_BRANCH_OK direct source copies for dev/quiet')
    print('VENDORED_GPU_THREAD_EQUIVALENT_OK', len(generated),
          'bounded 256-slot FIFO, stop-aware worker, dev/quiet source variants')


if __name__ == '__main__':
    main()
