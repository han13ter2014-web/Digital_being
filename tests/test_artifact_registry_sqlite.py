"""Реестр артефактов этапа 5C: копирование, хеши, безопасный путь, проверка."""

from contextlib import closing
import hashlib
import sqlite3
from uuid import uuid4

import pytest

from src.memory.life_database import LifeDatabase


def _database(tmp_path):
    life_id = str(uuid4())
    return LifeDatabase(tmp_path / "lives" / life_id / "life.sqlite3", life_id)


def _file(tmp_path, name, content: bytes):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_external_file_is_copied_and_original_kept(tmp_path):
    database = _database(tmp_path)
    source = _file(tmp_path / "outside", "painting.svg", b"<svg />")
    original = source.read_bytes()

    row = database.register_artifact(
        source, kind="creative", metadata={"activity": "art"}
    )

    assert row["kind"] == "creative"
    assert row["bytes"] == len(original)
    assert row["sha256"] == hashlib.sha256(original).hexdigest()
    assert row["metadata"] == {"activity": "art"}
    assert row["relative_path"] == "artifacts/creative/painting.svg"
    stored = database.life_dir / row["relative_path"]
    assert stored.read_bytes() == original
    assert source.read_bytes() == original
    assert database.list_artifacts("creative")[0]["id"] == row["id"]
    assert database.get_artifact(row["id"]) == row
    assert database.verify_artifacts() == {"ok": True, "checked": 1, "problems": []}


def test_file_inside_life_dir_is_registered_in_place(tmp_path):
    database = _database(tmp_path)
    inner = database.life_dir / "exports" / "final.json"
    inner.parent.mkdir(parents=True)
    inner.write_bytes(b"{}")

    row = database.register_artifact(inner, kind="export")

    assert row["relative_path"] == "exports/final.json"
    copies = [path for path in database.artifacts_dir.rglob("*") if path.is_file()]
    assert copies == []
    assert database.verify_artifacts()["ok"] is True


def test_unsafe_relative_paths_are_rejected(tmp_path):
    database = _database(tmp_path)
    source = _file(tmp_path, "x.txt", b"x")
    for bad in ("../x.txt", "/abs/x.txt", "a/../../x.txt", "."):
        with pytest.raises(ValueError):
            database.register_artifact(source, kind="creative", relative_path=bad)
    assert database.list_artifacts() == []


def test_same_path_conflicts_without_update_flag(tmp_path):
    database = _database(tmp_path)
    first = _file(tmp_path, "first", b"v1")
    row = database.register_artifact(first, kind="creative")

    twin = _file(tmp_path / "twin", "first", b"v1")
    again = database.register_artifact(twin, kind="creative")
    assert again["id"] == row["id"]

    other = _file(tmp_path / "other", "first", b"v2")
    with pytest.raises(ValueError, match="уже лежит другой файл"):
        database.register_artifact(other, kind="creative")


def test_update_flag_rewrites_registered_content(tmp_path):
    database = _database(tmp_path)
    source = _file(tmp_path, "work.txt", b"rev1")
    database.register_artifact(source, kind="creative")
    revised = _file(tmp_path, "work2", b"rev2")

    row = database.register_artifact(
        revised,
        kind="creative",
        relative_path="artifacts/creative/work.txt",
        update=True,
        metadata={"revision": 2},
    )

    assert row["sha256"] == hashlib.sha256(b"rev2").hexdigest()
    assert row["metadata"] == {"revision": 2}
    stored = database.life_dir / "artifacts" / "creative" / "work.txt"
    assert stored.read_bytes() == b"rev2"


def test_verify_detects_tampering_and_missing_files(tmp_path):
    database = _database(tmp_path)
    row = database.register_artifact(_file(tmp_path, "a.txt", b"aaaa"), kind="creative")
    stored = database.life_dir / row["relative_path"]
    stored.write_bytes(b"bbbb")
    report = database.verify_artifacts()
    assert report["ok"] is False
    assert report["problems"] == [
        {
            "id": row["id"],
            "relative_path": row["relative_path"],
            "problem": "hash_mismatch",
        }
    ]

    stored.unlink()
    report = database.verify_artifacts()
    assert report["ok"] is False
    assert report["problems"][0]["problem"] == "missing"


def test_write_artifact_exports_and_refreshes_registration(tmp_path):
    database = _database(tmp_path)
    row = database.write_artifact(
        "artifacts/architecture_proposals/prop_x.json",
        b'{"status": "pending"}',
        kind="architecture_proposal",
        metadata={"proposal_id": "prop_x"},
    )
    target = database.life_dir / "artifacts" / "architecture_proposals" / "prop_x.json"
    assert target.read_bytes() == b'{"status": "pending"}'
    assert row["sha256"] == hashlib.sha256(b'{"status": "pending"}').hexdigest()

    updated = database.write_artifact(
        "artifacts/architecture_proposals/prop_x.json",
        b'{"status": "approved"}',
        kind="architecture_proposal",
        metadata={"proposal_id": "prop_x"},
    )
    assert updated["id"] == row["id"]
    assert updated["sha256"] == hashlib.sha256(b'{"status": "approved"}').hexdigest()
    assert database.verify_artifacts()["ok"] is True


def test_write_artifact_refuses_database_path(tmp_path):
    database = _database(tmp_path)
    with pytest.raises(ValueError, match="базой жизни"):
        database.write_artifact("life.sqlite3", b"x", kind="export")


def test_v2_database_gains_new_tables_without_losing_state(tmp_path):
    from src.memory.checkpoint_store import SQLiteCheckpointStore

    life_id = str(uuid4())
    path = tmp_path / "life.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=2")
    state = {"life_id": life_id, "cycle_count": 3}
    store = SQLiteCheckpointStore(path)
    snapshot = store.save(state, life_id, 3)

    migrated = LifeDatabase(path, life_id)
    assert migrated.get_meta("storage_schema_version") == LifeDatabase.SCHEMA_VERSION
    with closing(migrated.connect(readonly=True)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == (
            LifeDatabase.SCHEMA_VERSION
        )
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {"dialogue_cycles", "architecture_proposals", "artifacts"} <= tables
    assert migrated.checkpoints.load(snapshot) == state
    assert migrated.verify()["ok"] is True
