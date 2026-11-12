"""Явный JSON-экспорт не становится вторым источником истины."""

import json
from uuid import uuid4

import pytest

from src.memory.life_database import LifeDatabase
from tools.manual.export_life_snapshot import export_snapshot


def test_export_latest_snapshot_contains_identity_and_hashes(tmp_path):
    life_id = str(uuid4())
    database = LifeDatabase(tmp_path / "lives" / life_id / "life.sqlite3", life_id)
    database.save_checkpoint({"life_id": life_id, "cycle_count": 4}, 4)
    latest = database.save_checkpoint(
        {
            "life_id": life_id,
            "schema_version": 12,
            "cycle_count": 5,
        },
        5,
    )
    output = tmp_path / "exports" / "latest.json"

    report = export_snapshot(tmp_path, life_id, output)
    exported = json.loads(output.read_text(encoding="utf-8"))

    assert report["snapshot_id"] == latest
    assert exported["life_id"] == life_id
    assert exported["schema_version"] == 12
    assert exported["storage_schema_version"] == LifeDatabase.SCHEMA_VERSION
    assert exported["cycle_count"] == 5
    assert exported["export_manifest"]["state_sha256"] == report["state_sha256"]
    assert (
        exported["export_manifest"]["snapshot_root_sha256"]
        == report["snapshot_root_sha256"]
    )
    with pytest.raises(FileExistsError):
        export_snapshot(tmp_path, life_id, output)
