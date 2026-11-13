"""Межпроцессная эксклюзивность writer-блокировки профиля."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

import src.app.profile_lock as profile_lock_module
from src.app.profile_lock import ProfileWriterLock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHILD_SCRIPT = """
import sys
from src.app.profile_lock import ProfileWriterLock, ProfileWriterLockError
lock = ProfileWriterLock(sys.argv[1])
try:
    lock.acquire()
except ProfileWriterLockError as exc:
    print(str(exc))
    sys.exit(17)
lock.release()
"""


def _try_child(profile: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-c", CHILD_SCRIPT, str(profile)],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )


def test_lock_rejects_other_process_and_releases(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    holder = ProfileWriterLock(profile)
    holder.acquire()
    try:
        blocked = _try_child(profile)
        assert blocked.returncode == 17
        assert "уже используется" in blocked.stdout
    finally:
        holder.release()

    acquired_after_release = _try_child(profile)
    assert acquired_after_release.returncode == 0, acquired_after_release.stderr


def test_release_failure_does_not_leave_stale_process_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    holder = ProfileWriterLock(tmp_path / "profile")
    holder.acquire()
    handle = holder._handle
    key = holder._key
    original_unlock = ProfileWriterLock._unlock_and_close

    def fail_unlock(_handle) -> None:
        raise OSError("injected close failure")

    try:
        monkeypatch.setattr(
            ProfileWriterLock, "_unlock_and_close", staticmethod(fail_unlock)
        )
        with pytest.raises(OSError, match="injected close failure"):
            holder.release()

        with profile_lock_module._HELD_PATHS_GUARD:
            assert key not in profile_lock_module._HELD_PATHS
    finally:
        monkeypatch.setattr(
            ProfileWriterLock, "_unlock_and_close", staticmethod(original_unlock)
        )
        if handle is not None:
            original_unlock(handle)
        with profile_lock_module._HELD_PATHS_GUARD:
            profile_lock_module._HELD_PATHS.discard(key)
