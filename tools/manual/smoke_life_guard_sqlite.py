"""Проверка LifeGuard на временной копии живой базы без автономных тиков."""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.life_guard import (  # noqa: E402
    KIND_DREAM,
    STATE_ALIVE,
    STATE_DORMANT,
    LifeGuard,
    get_policy,
)


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    data = ROOT / "data"
    profile = json.loads((data / "active_profile.json").read_text(encoding="utf-8"))
    life_id = profile["life_id"]
    source = data / "lives" / life_id / "life.sqlite3"
    legacy = [data / name for name in (
        "life_state.json", "life_requests.json", "life_events.log",
    )]
    tracked = [source, *(path for path in legacy if path.exists())]
    before = {str(path): digest(path) for path in tracked}

    with tempfile.TemporaryDirectory(prefix="life_guard_sqlite_") as temporary:
        root = Path(temporary)
        target = root / "lives" / life_id / "life.sqlite3"
        target.parent.mkdir(parents=True)
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst)
        with closing(sqlite3.connect(target)) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

        previous = os.environ.get("DIGITAL_BEING_DATA_DIR")
        os.environ["DIGITAL_BEING_DATA_DIR"] = str(root)
        try:
            clock = Clock()
            guard = LifeGuard(
                agent_name=profile["name"], life_id=life_id, clock=clock,
                snapshot_root=str(root / "snapshots"),
            )
            assert guard.load_state() == STATE_ALIVE
            request = guard.request(KIND_DREAM, reason="smoke на временной копии")
            clock.now += get_policy(KIND_DREAM).cooldown_sec + 0.1
            guard.confirm(request.request_id, profile["name"])
            result = guard.execute_confirmed(request.request_id, seed_folder="smoke-seed")
            assert result["state"] == STATE_DORMANT

            reopened = LifeGuard(agent_name=profile["name"], life_id=life_id)
            assert reopened.load_state() == STATE_DORMANT
            assert reopened.state_details()["seed_folder"] == "smoke-seed"
            assert reopened.get_request(request.request_id) is None
            events = [item["event"] for item in reopened.recent_events()]
            assert events[-4:] == ["requested", "confirmed", "state_changed", "executed"]
            assert not any((root / name).exists() for name in (
                "life_state.json", "life_requests.json", "life_events.log",
            ))
        finally:
            if previous is None:
                os.environ.pop("DIGITAL_BEING_DATA_DIR", None)
            else:
                os.environ["DIGITAL_BEING_DATA_DIR"] = previous

    after = {str(path): digest(path) for path in tracked}
    assert before == after, "Исходные файлы изменились"
    print(json.dumps({
        "ok": True,
        "life_id": life_id,
        "copy_state_after_reopen": STATE_DORMANT,
        "source_files_unchanged": True,
        "autonomous_ticks": 0,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
