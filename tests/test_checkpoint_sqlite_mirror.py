"""Этап 3: JSON остаётся основным, SQLite проверяется после каждой записи."""

import json
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest

from config.simulation_config import SIM_CONFIG
from src.core.checkpoint_migrations import SCHEMA_VERSION
from src.core.checkpoint_serializer import (
    CheckpointMirrorError,
    CheckpointSerializer,
)
from src.memory.checkpoint_store import SQLiteCheckpointStore
from src.memory.life_database import LifeDatabase


def _state(name, cycle, life_id):
    return {
        "schema_version": SCHEMA_VERSION,
        "life_id": life_id,
        "name": name,
        "cycle_count": cycle,
        "energy": 90.0,
        "knowledge_base": {"sqlite": "база", "cycle": cycle},
    }


def test_json_primary_and_sqlite_mirror_roundtrip(tmp_path):
    life_id = str(uuid4())
    mirror = tmp_path / "lives" / life_id / "life.sqlite3"
    serializer = CheckpointSerializer(
        checkpoint_dir=tmp_path / "checkpoints" / life_id,
        backend="json",
        sqlite_mirror_path=str(mirror),
        sqlite_mirror_life_id=life_id,
    )

    first_path = serializer.save(_state("Probe", 1, life_id), life_id, 1)
    second_path = serializer.save(_state("Probe", 2, life_id), life_id, 2)

    assert Path(first_path).suffix == ".json"
    assert Path(second_path).suffix == ".json"
    database = LifeDatabase(mirror, life_id)
    latest_id = database.get_meta("latest_snapshot_id")
    assert database.checkpoints.load(latest_id) == _state("Probe", 2, life_id)
    assert database.verify()["ok"] is True
    connection = sqlite3.connect(mirror)
    try:
        count = connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    finally:
        connection.close()
    assert count == 2


def test_mirror_mismatch_raises_but_preserves_primary_json(tmp_path, monkeypatch):
    life_id = str(uuid4())
    serializer = CheckpointSerializer(
        checkpoint_dir=tmp_path / "checkpoints",
        backend="json",
        sqlite_mirror_path=str(tmp_path / "life.sqlite3"),
        sqlite_mirror_life_id=life_id,
    )
    monkeypatch.setattr(
        SQLiteCheckpointStore, "load",
        lambda self, snapshot_id: {"unexpected": snapshot_id},
    )

    with pytest.raises(CheckpointMirrorError, match="не совпало"):
        serializer.save(_state("Probe", 3, life_id), life_id, 3)

    primary = tmp_path / "checkpoints" / f"{life_id}_cycle_3.json"
    assert json.loads(primary.read_text(encoding="utf-8"))["cycle_count"] == 3


def test_agent_mirror_uses_lives_path_and_keeps_json_backend(tmp_path, monkeypatch):
    from src.core.agent import DigitalBeing

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", "json")
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_SQLITE_MIRROR", True)
    agent = DigitalBeing("MirrorTestLife", profile_managed=True)
    agent.cycle_count = 7

    primary = agent.save_state(force=True)

    assert primary.endswith(".json")
    mirror = tmp_path / "data" / "lives" / agent.life_id / "life.sqlite3"
    assert mirror.is_file()
    database = LifeDatabase(mirror, agent.life_id)
    restored = database.checkpoints.load(database.get_meta("latest_snapshot_id"))
    assert restored["life_id"] == agent.life_id
    assert restored["cycle_count"] == 7


def test_mirror_requires_identity_and_json_backend(tmp_path):
    with pytest.raises(ValueError, match="путь и life_id"):
        CheckpointSerializer(checkpoint_dir=tmp_path, sqlite_mirror_path="x")
    with pytest.raises(ValueError, match="не нуждается"):
        CheckpointSerializer(
            checkpoint_dir=tmp_path,
            backend="sqlite",
            sqlite_mirror_path=str(tmp_path / "mirror.sqlite3"),
            sqlite_mirror_life_id=str(uuid4()),
        )
