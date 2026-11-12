"""Межпроцессная эксклюзивность writer-блокировки профиля."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

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
