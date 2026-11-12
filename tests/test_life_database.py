"""База жизни: идентичность, транзакции и перенос времени снимков."""

from contextlib import closing
import sqlite3
from uuid import uuid4

import pytest

from src.memory.life_database import LifeDatabase


def test_schema_reopen_and_snapshot_timestamp_roundtrip(tmp_path):
    life_id = str(uuid4())
    path = tmp_path / "lives" / life_id / "life.sqlite3"
    database = LifeDatabase(path, life_id)
    saved_at = "2026-11-10T18:00:00+00:00"
    snapshot = database.checkpoints.save(
        {"life_id": life_id, "cycle_count": 7},
        life_id,
        7,
        saved_at=saved_at,
    )

    reopened = LifeDatabase(path, life_id)
    assert reopened.checkpoints.load(snapshot)["cycle_count"] == 7
    with closing(sqlite3.connect(path)) as connection:
        assert (
            connection.execute(
                "SELECT saved_at FROM snapshots WHERE id = ?", (snapshot,)
            ).fetchone()[0]
            == saved_at
        )
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    with closing(reopened.connect()) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
    assert reopened.get_meta("life_id") == life_id
    assert reopened.verify()["ok"] is True


def test_existing_database_cannot_be_rebound_to_another_life(tmp_path):
    path = tmp_path / "life.sqlite3"
    database = LifeDatabase(path, str(uuid4()))
    database.set_meta("kept", {"value": 1})

    with pytest.raises(ValueError, match="другой жизни"):
        LifeDatabase(path, str(uuid4()))
    assert LifeDatabase(path, database.life_id).get_meta("kept") == {"value": 1}


def test_failed_transaction_rolls_back_all_changes(tmp_path):
    database = LifeDatabase(tmp_path / "life.sqlite3", str(uuid4()))

    with pytest.raises(RuntimeError, match="injected"):
        with database.write() as connection:
            connection.execute(
                "INSERT INTO life_status VALUES (1, 'alive', 'test', '', 'now', NULL)"
            )
            database.set_meta("partial", True, connection)
            raise RuntimeError("injected")

    with closing(database.connect(readonly=True)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM life_status").fetchone()[0] == 0
    assert database.get_meta("partial") is None


def test_checkpoint_and_latest_pointer_are_atomic(tmp_path, monkeypatch):
    database = LifeDatabase(tmp_path / "life.sqlite3", str(uuid4()))
    first = database.save_checkpoint({"cycle_count": 1}, 1)
    assert database.get_meta("latest_snapshot_id") == first

    def fail_pointer(*args, **kwargs):
        raise RuntimeError("injected pointer failure")

    monkeypatch.setattr(database, "set_meta", fail_pointer)
    with pytest.raises(RuntimeError, match="injected pointer failure"):
        database.save_checkpoint({"cycle_count": 2}, 2)
    with closing(database.connect(readonly=True)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1


def test_legacy_snapshot_database_cannot_be_silently_rebound(tmp_path):
    from src.memory.checkpoint_store import SQLiteCheckpointStore

    path = tmp_path / "legacy.sqlite3"
    SQLiteCheckpointStore(path).save({"value": 1}, "another-name", 1)

    with pytest.raises(ValueError, match="другой жизни"):
        LifeDatabase(path, str(uuid4()))


def test_v1_database_migrates_dialogue_schema_without_losing_state(tmp_path):
    from src.core.life_guard import LifeGuard, STATE_DORMANT
    from src.memory.checkpoint_store import SQLiteCheckpointStore

    life_id = str(uuid4())
    path = tmp_path / "life.sqlite3"
    state = {"life_id": life_id, "cycle_count": 9}
    snapshot = SQLiteCheckpointStore(path).save(state, life_id, 9)

    migrated = LifeDatabase(path, life_id)
    assert migrated.checkpoints.load(snapshot) == state
    assert migrated.get_meta("storage_schema_version") == LifeDatabase.SCHEMA_VERSION
    LifeGuard(agent_name="Test", database=migrated).set_state(
        STATE_DORMANT, reason="migration test", seed_folder="seed"
    )

    reopened = LifeDatabase(path, life_id)
    with closing(reopened.connect(readonly=True)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (
            LifeDatabase.SCHEMA_VERSION
        )
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dialogue_cycles'"
            ).fetchone()[0]
            == 1
        )
    assert reopened.checkpoints.load(snapshot) == state
    assert LifeGuard(agent_name="Test", database=reopened).load_state() == STATE_DORMANT
