"""Миграция не объявляется успешной по отсутствию ошибки чтения JSON."""

import pytest

from src.core import checkpoint_migrations as migrations
from src.core.checkpoint_migrations import CheckpointMigrationError, migrate_state


def test_current_schema_is_independent_idempotent_copy():
    original = {"schema_version": 1, "nested": {"values": [1, 2]}}
    migrated = migrate_state(original)
    assert migrated == original
    assert migrate_state(migrated) == migrated
    migrated["nested"]["values"].append(3)
    assert original["nested"]["values"] == [1, 2]


def test_missing_step_does_not_stamp_or_mutate():
    original = {"schema_version": 0, "nested": []}
    with pytest.raises(CheckpointMigrationError, match="0 → 1"):
        migrate_state(original)
    assert original == {"schema_version": 0, "nested": []}


def test_failed_migrator_cannot_mutate_input(monkeypatch):
    def broken(data):
        data["nested"].append("partial")
        raise RuntimeError("failed")

    monkeypatch.setitem(migrations.MIGRATIONS, (0, 1), broken)
    original = {"schema_version": 0, "nested": []}
    with pytest.raises(CheckpointMigrationError):
        migrate_state(original)
    assert original["nested"] == []
    assert original["schema_version"] == 0


def test_complete_chain_applied_in_order(monkeypatch):
    monkeypatch.setattr(migrations, "SCHEMA_VERSION", 2)
    monkeypatch.setitem(migrations.MIGRATIONS, (0, 1), lambda data: {**data, "first": True})
    monkeypatch.setitem(migrations.MIGRATIONS, (1, 2), lambda data: {**data, "second": data["first"]})
    original = {"schema_version": 0}
    assert migrate_state(original) == {"schema_version": 2, "first": True, "second": True}
    assert original == {"schema_version": 0}


@pytest.mark.parametrize("version", [True, -1, 1.5, "1", None, 999])
def test_invalid_or_future_version_rejected(version):
    with pytest.raises(CheckpointMigrationError):
        migrate_state({"schema_version": version})


def test_unknown_jump_rejected(monkeypatch):
    monkeypatch.setitem(migrations.MIGRATIONS, (0, 1), lambda data: {"schema_version": 88})
    with pytest.raises(CheckpointMigrationError):
        migrate_state({"schema_version": 0})
