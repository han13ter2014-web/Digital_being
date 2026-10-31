"""Комплект резервирования включает подтверждённый WAL и проверяется до восстановления."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

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
            assert conn.execute("SELECT value FROM events").fetchall() == [("remembered",)]
        assert (restored / "life_state.json").is_file()
        # Выбор доступов — часть профиля: после восстановления не должен
        # молча вернуться к умолчаниям.
        assert (restored / "access_settings.json").read_text() == '{"network": false}'
    finally:
        connection.close()


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
    with patch("src.memory.profile_backup.shutil.copy2", side_effect=PermissionError("blocked")):
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
