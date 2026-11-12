"""Этап 4: 500 автономных циклов временной жизни и сбои SQLite.

Работает только в отдельном ``tmp/sqlite_long_run_*``. JSON остаётся основным
backend, живой ``data/`` и активный профиль не изменяются.
"""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CYCLES = 500
RESTART_CYCLES = {125, 250, 375}


def _file_hash(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _state_hash(state):
    payload = json.dumps(
        state, ensure_ascii=True, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_size(path):
    path = Path(path)
    return path.stat().st_size if path.exists() else 0


def _finish(agent):
    registry = getattr(agent, "plugin_registry", None) if agent is not None else None
    if registry is not None:
        registry.teardown_all()


def _check_rollback(database):
    key = "probe_rollback"
    database.set_meta(key, "before")
    try:
        with database.write() as connection:
            database.set_meta(key, "must_not_commit", connection)
            raise RuntimeError("Искусственное исключение до commit")
    except RuntimeError as error:
        assert str(error) == "Искусственное исключение до commit"
    assert database.get_meta(key) == "before"
    return {"passed": True, "value_after_exception": database.get_meta(key)}


def _check_lock_timeout(database):
    holder = database.connect()
    contender = None
    started = time.monotonic()
    try:
        holder.execute("BEGIN IMMEDIATE")
        holder.execute(
            "INSERT INTO meta(key, value_json, updated_at) "
            "VALUES ('probe_lock', 'true', datetime('now'))"
        )
        contender = database.connect()
        contender.execute("PRAGMA busy_timeout=100")
        try:
            contender.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as error:
            elapsed_ms = (time.monotonic() - started) * 1000
            assert "locked" in str(error).lower(), str(error)
            assert elapsed_ms >= 50, elapsed_ms
            return {
                "passed": True,
                "error": str(error),
                "elapsed_ms": round(elapsed_ms, 1),
                "configured_busy_timeout_ms": 100,
            }
        raise AssertionError("Запись при удерживаемой блокировке неожиданно удалась")
    finally:
        if contender is not None:
            contender.rollback()
            contender.close()
        holder.rollback()
        holder.close()


def _check_wal_maintenance(database):
    wal_path = Path(str(database.path) + "-wal")
    size_before = _file_size(wal_path)
    with closing(database.connect()) as connection:
        checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    size_after = _file_size(wal_path)
    assert size_after == 0, size_after
    verification = database.verify()
    assert verification["ok"] is True, verification
    return {
        "checkpoint_result": list(checkpoint),
        "wal_bytes_before": size_before,
        "wal_bytes_after": size_after,
        "verification": verification,
    }


def main():
    temporary_parent = ROOT / "tmp"
    temporary_parent.mkdir(exist_ok=True)
    live_profile = ROOT / "data" / "active_profile.json"
    live_profile_before = _file_hash(live_profile)

    with tempfile.TemporaryDirectory(prefix="sqlite_long_run_", dir=temporary_parent) as isolated:
        data_root = Path(isolated) / "data"
        os.environ["DIGITAL_BEING_DATA_DIR"] = str(data_root)
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        os.environ["VOICE_CONSOLE_QUIET"] = "1"
        for name in (
            "DIGITAL_BEING_TELEGRAM_TOKEN", "DIGITAL_BEING_TELEGRAM_CHAT_ID",
            "DIGITAL_BEING_DISCORD_WEBHOOK_URL",
        ):
            os.environ.pop(name, None)

        from config.simulation_config import SIM_CONFIG
        from src.core.agent import DigitalBeing
        from src.core.checkpoint_serializer import (
            CheckpointSerializer, apply_state_to_agent,
        )
        from src.memory.life_database import LifeDatabase

        SIM_CONFIG.CHECKPOINT_BACKEND = "json"
        SIM_CONFIG.CHECKPOINT_SQLITE_MIRROR = True
        SIM_CONFIG.CHECKPOINT_INTERVAL = 10
        SIM_CONFIG.SAVE_ON_EVOLUTION = False
        SIM_CONFIG.MAX_CHECKPOINTS = 1000

        agent = DigitalBeing("SQLiteLongRunProbe", profile_managed=True)
        agent.web_searcher.toggle(False)
        life_id = agent.life_id
        mirror_path = data_root / "lives" / life_id / "life.sqlite3"
        wal_path = Path(str(mirror_path) + "-wal")
        database = None
        stop_reader = threading.Event()
        writing = threading.Event()
        reader_errors = []
        reader_stats = {"reads": 0, "reads_during_writes": 0, "max_snapshot_id": 0}
        records = []
        restarts = []
        max_wal_bytes = 0

        def read_shadow():
            while not stop_reader.is_set():
                if database is None:
                    stop_reader.wait(0.005)
                    continue
                try:
                    write_seen = writing.is_set()
                    snapshot_id = database.checkpoints.latest(life_id)
                    if snapshot_id is not None:
                        state = database.checkpoints.load(snapshot_id)
                        assert state["life_id"] == life_id
                        assert state["cycle_count"] <= CYCLES
                        _state_hash(state)
                        reader_stats["reads"] += 1
                        reader_stats["max_snapshot_id"] = max(
                            reader_stats["max_snapshot_id"], snapshot_id
                        )
                        if write_seen or writing.is_set():
                            reader_stats["reads_during_writes"] += 1
                except BaseException as error:  # передать любой сбой основному потоку
                    reader_errors.append(f"{type(error).__name__}: {error}")
                    stop_reader.set()
                    return
                stop_reader.wait(0.005)

        reader = threading.Thread(target=read_shadow, name="sqlite-shadow-reader", daemon=True)
        try:
            for cycle in range(1, CYCLES + 1):
                agent.autonomous_tick()
                agent.evolve()
                agent.cycle_count += 1
                assert agent.cycle_count == cycle

                writing.set()
                try:
                    primary_path = agent.save_state()
                finally:
                    writing.clear()
                if primary_path is not None:
                    if database is None:
                        database = LifeDatabase(mirror_path, life_id)
                        reader.start()
                    primary_state = CheckpointSerializer().load(primary_path)
                    snapshot_id = database.get_meta("latest_snapshot_id")
                    mirror_state = database.checkpoints.load(snapshot_id)
                    assert primary_state == mirror_state
                    assert primary_state["cycle_count"] == cycle
                    assert _state_hash(primary_state) == _state_hash(mirror_state)
                    records.append({
                        "cycle": cycle,
                        "snapshot_id": snapshot_id,
                        "sha256": _state_hash(primary_state),
                    })
                max_wal_bytes = max(max_wal_bytes, _file_size(wal_path))

                if cycle in RESTART_CYCLES:
                    writing.set()
                    try:
                        primary_path = agent.save_state(force=True)
                    finally:
                        writing.clear()
                    primary_state = CheckpointSerializer().load(primary_path)
                    snapshot_id = database.get_meta("latest_snapshot_id")
                    mirror_state = database.checkpoints.load(snapshot_id)
                    assert primary_state == mirror_state
                    records.append({
                        "cycle": cycle,
                        "snapshot_id": snapshot_id,
                        "sha256": _state_hash(primary_state),
                        "restart_save": True,
                    })
                    _finish(agent)
                    reborn = DigitalBeing("SQLiteLongRunReborn", profile_managed=True)
                    reborn.web_searcher.toggle(False)
                    apply_state_to_agent(reborn, mirror_state)
                    assert reborn.cycle_count == cycle
                    assert reborn.life_id == life_id
                    assert reborn.name == "SQLiteLongRunProbe"
                    assert reborn.goals == agent.goals
                    assert reborn.knowledge_base == agent.knowledge_base
                    agent = reborn
                    restarts.append({"after_cycle": cycle, "snapshot_id": snapshot_id})
                max_wal_bytes = max(max_wal_bytes, _file_size(wal_path))

            stop_reader.set()
            reader.join(timeout=30)
            assert not reader.is_alive(), "Теневой читатель не остановился"
            assert not reader_errors, reader_errors
            assert reader_stats["reads"] > 0
            assert reader_stats["reads_during_writes"] > 0, reader_stats
            assert len(records) == 53, len(records)
            assert len(restarts) == 3

            rollback = _check_rollback(database)
            lock_database = LifeDatabase(
                data_root / "lives" / "lock-probe" / "life.sqlite3", str(uuid.uuid4())
            )
            lock_timeout = _check_lock_timeout(lock_database)
            reclaimed_blobs = database.checkpoints.gc()
            wal_maintenance = _check_wal_maintenance(database)
            verification = database.verify()
            assert verification["ok"] is True
            assert _file_hash(live_profile) == live_profile_before

            json_files = sorted(
                (data_root / "checkpoints" / life_id).glob("*_cycle_*.json")
            )
            with closing(sqlite3.connect(mirror_path)) as connection:
                snapshot_count = connection.execute(
                    "SELECT COUNT(*) FROM snapshots WHERE agent_name=?", (life_id,)
                ).fetchone()[0]
            assert snapshot_count == len(records)
            report = {
                "life_id": life_id,
                "primary_backend": "json",
                "cycles_completed": CYCLES,
                "restarts": restarts,
                "snapshots_written_and_verified": len(records),
                "json_files_after_run": len(json_files),
                "sqlite_snapshots_after_run": snapshot_count,
                "all_roundtrips_equal": True,
                "shadow_reader": reader_stats,
                "rollback": rollback,
                "lock_timeout": lock_timeout,
                "maintenance": {
                    **wal_maintenance,
                    "unreachable_blobs_reclaimed": reclaimed_blobs,
                    "max_wal_bytes_observed": max_wal_bytes,
                    "database_bytes": _file_size(mirror_path),
                },
                "verification": verification,
                "live_active_profile_unchanged": True,
                "temporary_lives_removed_on_exit": True,
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            stop_reader.set()
            if reader.is_alive():
                reader.join(timeout=30)
            _finish(agent)
            from src.core.buffered_logger import flush_logs
            flush_logs()
            if reader_errors:
                raise AssertionError(f"Ошибки теневого чтения: {reader_errors}")


if __name__ == "__main__":
    main()
