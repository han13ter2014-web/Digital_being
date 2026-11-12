"""Комплект резервирования включает подтверждённый WAL и проверяется до восстановления."""

import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.memory.life_database import LifeDatabase
from src.memory.profile_backup import create_backup, restore_backup, verify_backup


def test_live_wal_backup_and_restore(tmp_path):
    profile = tmp_path / "profile"
    (profile / "delamain").mkdir(parents=True)
    database = profile / "delamain" / "memory.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE events(value TEXT)")
        connection.execute("INSERT INTO events VALUES ('remembered')")
        connection.commit()
        (profile / "life_state.json").write_text('{"state":"alive"}')
        (profile / "access_settings.json").write_text('{"network": false}')
        backup = tmp_path / "backup"
        create_backup(profile, backup)
        manifest = verify_backup(backup)
        assert any(item["sqlite"] for item in manifest["files"])
        assert not list(backup.rglob("*-wal"))
        restored = tmp_path / "restored"
        restore_backup(backup, restored)
        with sqlite3.connect(restored / "delamain" / "memory.sqlite3") as conn:
            assert conn.execute("SELECT value FROM events").fetchall() == [
                ("remembered",)
            ]
        assert (restored / "life_state.json").is_file()
        # Выбор доступов — часть профиля: после восстановления не должен
        # молча вернуться к умолчаниям.
        assert (restored / "access_settings.json").read_text() == '{"network": false}'
    finally:
        connection.close()


def test_empty_wal_backup_preserves_source_file_set(tmp_path):
    profile = tmp_path / "profile"
    life_id = str(uuid4())
    life_dir = profile / "lives" / life_id
    life_dir.mkdir(parents=True)
    database = life_dir / "life.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE events(value TEXT)")
        connection.execute("INSERT INTO events VALUES ('remembered')")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    wal = Path(str(database) + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    before = {
        path.relative_to(profile).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in profile.rglob("*")
        if path.is_file()
    }

    create_backup(profile, tmp_path / "backup")

    after = {
        path.relative_to(profile).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in profile.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_corruption_rejected_before_destination_created(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "knowledge_base.json").write_text("{}")
    backup = tmp_path / "backup"
    create_backup(profile, backup)
    (backup / "knowledge_base.json").write_text("corrupt")
    destination = tmp_path / "restored"
    with pytest.raises(ValueError):
        restore_backup(backup, destination)
    assert not destination.exists()


def test_copy_failure_never_publishes_partial_backup(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "knowledge_base.json").write_text("{}")
    with patch(
        "src.memory.profile_backup.shutil.copy2", side_effect=PermissionError("blocked")
    ):
        with pytest.raises(PermissionError):
            create_backup(profile, tmp_path / "backup")
    assert not (tmp_path / "backup").exists()
    assert not list(tmp_path.glob(".*.tmp"))


def test_existing_profile_never_overwritten(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "knowledge_base.json").write_text("{}")
    backup = tmp_path / "backup"
    create_backup(profile, backup)
    with pytest.raises(ValueError):
        restore_backup(backup, profile)
    assert (profile / "knowledge_base.json").read_text() == "{}"


def test_architecture_proposals_are_included_in_backup_and_restore(tmp_path):
    profile = tmp_path / "profile"
    proposals = profile / "architecture_proposals"
    proposals.mkdir(parents=True)
    proposal = proposals / "prop_test.json"
    proposal.write_text('{"id":"prop_test","status":"pending"}', encoding="utf-8")

    backup = tmp_path / "backup"
    create_backup(profile, backup)
    manifest = verify_backup(backup)
    entry = next(
        item
        for item in manifest["files"]
        if item["path"] == "architecture_proposals/prop_test.json"
    )
    assert entry["sha256"] == hashlib.sha256(proposal.read_bytes()).hexdigest()

    restored = tmp_path / "restored"
    restore_backup(backup, restored)
    assert (restored / "architecture_proposals" / "prop_test.json").read_bytes() == (
        proposal.read_bytes()
    )


def _schema(path):
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        meta = {
            row[0]: json.loads(row[1])
            for row in connection.execute("SELECT key, value_json FROM meta")
        }
    return version, tables, meta


def test_restore_v1_does_not_migrate_schema(tmp_path):
    profile = tmp_path / "profile"
    life_id = str(uuid4())
    life_dir = profile / "lives" / life_id
    life_dir.mkdir(parents=True)
    database = life_dir / "life.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE meta(key TEXT PRIMARY KEY, value_json TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO meta VALUES ('life_id', ?)", (json.dumps(life_id),)
        )
        connection.execute("INSERT INTO meta VALUES ('storage_schema_version', '1')")
        connection.execute("PRAGMA user_version=1")
    expected_schema = _schema(database)

    backup = tmp_path / "backup"
    restored = tmp_path / "restored"
    create_backup(profile, backup)
    restore_backup(backup, restored)

    restored_db = restored / "lives" / life_id / "life.sqlite3"
    assert _schema(restored_db) == expected_schema
    assert "artifacts" not in expected_schema[1]
    assert (
        restored_db.read_bytes()
        == (backup / "lives" / life_id / "life.sqlite3").read_bytes()
    )
    assert LifeDatabase.verify_artifacts_readonly(restored_db) == {
        "ok": True,
        "checked": 0,
        "problems": [],
    }


def test_restore_v3_verifies_artifacts_without_writing_database(tmp_path):
    profile = tmp_path / "profile"
    life_id = str(uuid4())
    database = LifeDatabase(profile / "lives" / life_id / "life.sqlite3", life_id)
    source = profile / "architecture_proposals" / "prop_test.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"id":"prop_test"}', encoding="utf-8")
    database.register_artifact(
        source,
        kind="architecture_proposal",
        relative_path="artifacts/architecture_proposals/prop_test.json",
    )

    backup = tmp_path / "backup"
    restored = tmp_path / "restored"
    create_backup(profile, backup)
    restore_backup(backup, restored)

    backup_db = backup / "lives" / life_id / "life.sqlite3"
    restored_db = restored / "lives" / life_id / "life.sqlite3"
    assert _schema(restored_db) == _schema(backup_db)
    assert restored_db.read_bytes() == backup_db.read_bytes()
    assert LifeDatabase.verify_artifacts_readonly(restored_db) == {
        "ok": True,
        "checked": 1,
        "problems": [],
    }
