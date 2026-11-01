#!/usr/bin/env python3
"""Guard the PS5-only VFS file-budget backport against pinned source drift.

The native build lowers the file descriptor LRU cap without changing Eden's
eviction/reopen behavior. This is a source/selection guard, not a PS5 boot test.
"""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
original = (root / "vendor/sources/eden/src/core/file_sys/vfs/vfs_real.cpp").read_text()
cmake = (root / "headless/CMakeLists.txt").read_text()
old = "constexpr size_t MaxOpenFiles = 8192;"
new = "constexpr size_t MaxOpenFiles = 128;"
assert original.count(old) == 1
assert new not in original, "pinned Switch 1 core must remain unmodified"
adapted = original.replace(old, new)
assert adapted.count(new) == 1 and old not in adapted
start = "std::unique_lock<std::mutex> RealVfsFilesystem::RefreshReference("
end = "RealVfsFile::RealVfsFile("
assert original.count(start) == 1 and original.count(end) >= 1
# Everything after the file-budget constant, including LRU and reopen, is
# intentionally identical to the maintained upstream implementation.
assert adapted.replace(new, old) == original
for key in (
    'set(EDEN_VFS_PINNED "${PORT_ROOT}/vendor/sources/eden/src/core/file_sys/vfs/vfs_real.cpp")',
    'set(EDEN_VFS_LIMIT_OLD "constexpr size_t MaxOpenFiles = 8192;")',
    'set(EDEN_VFS_LIMIT_NEW "constexpr size_t MaxOpenFiles = 128;")',
    'write_derived("${PORT_BUILD_DIR}/vfs_real_ps5.cpp" "${eden_vfs_bounded}")',
    'list(FIND eden_vfs_core_sources "file_sys/vfs/vfs_real.cpp" eden_vfs_owner)',
    'list(REMOVE_ITEM eden_vfs_core_sources "file_sys/vfs/vfs_real.cpp")',
    'list(APPEND eden_vfs_core_sources "${PORT_BUILD_DIR}/vfs_real_ps5.cpp")',
):
    assert cmake.count(key) == 1, key
assert cmake.index("if(PS5_NATIVE)\n    set(EDEN_VFS_PINNED") < cmake.index(
    "list(APPEND eden_vfs_core_sources")
print("PS5_VFS_FILE_BUDGET_PASS original=8192 native=128 lru=unchanged pinned_source=unchanged")
