"""Пограничные случаи обнаружения истории до создания агента."""

import pytest

from src.app.active_profile import active_name, remember_active_name
from src.app.bootstrap import RecoveryRequiredError


def test_single_broken_json_selects_history_not_new_life(tmp_path):
    directory = tmp_path / "checkpoints"
    directory.mkdir()
    (directory / "Old_cycle_9.json.gz").write_bytes(b"broken")
    # Разбор и валидация снимка принадлежат create_agent, не поиску имени.
    assert active_name(tmp_path, "Alpha") == "Old"


def test_existing_pointer_wins_over_unrelated_legacy_profile(tmp_path):
    directory = tmp_path / "checkpoints"
    directory.mkdir()
    for name in ("Selected", "Other"):
        (directory / f"{name}_cycle_1.json").write_text("{}", encoding="utf-8")
    remember_active_name(tmp_path, "Selected")
    assert active_name(tmp_path, "Alpha") == "Selected"


def test_unknown_sqlite_schema_does_not_create_new_life(tmp_path):
    import sqlite3

    directory = tmp_path / "checkpoints"
    directory.mkdir()
    with sqlite3.connect(directory / "life.sqlite3") as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(RecoveryRequiredError):
        active_name(tmp_path, "Alpha")
