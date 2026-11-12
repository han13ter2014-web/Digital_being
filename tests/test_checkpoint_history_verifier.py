"""Поиск исходных snapshots в резервных комплектах без восстановления."""

import hashlib
import json
from pathlib import Path
import shutil
from uuid import uuid4

from src.memory.checkpoint_store import SQLiteCheckpointStore
from src.memory.profile_backup import create_backup
from tools.manual.verify_stage6_checkpoint_history import main, verify_history


def _hashes(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _history(tmp_path):
    data = tmp_path / "data"
    life_id = str(uuid4())
    checkpoints = data / "checkpoints" / life_id
    checkpoints.mkdir(parents=True)
    profile = {"name": "TestLife", "life_id": life_id}
    (data / "active_profile.json").write_text(json.dumps(profile), encoding="utf-8")
    store = SQLiteCheckpointStore(data / "lives" / life_id / "life.sqlite3")
    states = {}
    for cycle in (9472, 9532):
        state = {
            "schema_version": 1,
            "life_id": life_id,
            "name": "TestLife",
            "cycle_count": cycle,
            "energy": 100,
            "goals": [],
            "saved_at": f"2026-11-08T22:{cycle % 60:02d}:00+00:00",
        }
        states[cycle] = state
        (checkpoints / f"{life_id}_cycle_{cycle}.json").write_text(
            json.dumps(state), encoding="utf-8"
        )
        store.save(state, life_id, cycle, saved_at=state["saved_at"])

    create_backup(data, data / "snapshots" / "sqlite_backup")
    json_source = tmp_path / "json_source"
    shutil.copytree(data / "checkpoints", json_source / "checkpoints")
    (json_source / "active_profile.json").write_text(json.dumps(profile), encoding="utf-8")
    create_backup(json_source, data / "snapshots" / "json_backup")
    return data, life_id, states


def test_history_matches_original_snapshots_in_verified_backup(tmp_path):
    data, life_id, _ = _history(tmp_path)
    before = _hashes(data)

    report = verify_history(data, life_id, {1: 9472, 2: 9532})

    assert report["ok"] is True, report["errors"]
    assert report["backup_count"] == 2
    assert [target["verified_in"] for target in report["targets"]] == [
        ["sqlite_backup"], ["sqlite_backup"]
    ]
    sqlite = next(backup for backup in report["backups"] if backup["name"] == "sqlite_backup")
    assert sqlite["manifest_verified"] is True
    assert sqlite["integrity_check"] == ["ok"]
    assert [entry["matched"] for entry in sqlite["snapshots"]] == [True, True]
    json_backup = next(backup for backup in report["backups"] if backup["name"] == "json_backup")
    assert json_backup["database_present"] is False
    assert report["restored_backup"] is False
    assert report["deletion_authorized"] is False
    assert _hashes(data) == before


def test_changed_active_legacy_fails_history_verification(tmp_path):
    data, life_id, states = _history(tmp_path)
    path = data / "checkpoints" / life_id / f"{life_id}_cycle_9472.json"
    path.write_text(json.dumps(dict(states[9472], energy=1)), encoding="utf-8")

    report = verify_history(data, life_id, {1: 9472, 2: 9532})

    assert report["ok"] is False
    assert report["targets"][0]["verified"] is False
    assert report["targets"][1]["verified"] is True
    assert any("полное состояние" in error for error in report["errors"])


def test_invalid_backup_manifest_fails_closed(tmp_path):
    data, life_id, _ = _history(tmp_path)
    path = data / "snapshots" / "json_backup" / "active_profile.json"
    path.write_text("{}", encoding="utf-8")

    report = verify_history(data, life_id, {1: 9472, 2: 9532})

    assert report["ok"] is False
    assert any("Контрольная сумма" in error for error in report["errors"])
    assert report["deletion_authorized"] is False


def test_history_cli_writes_evidence_without_deleting_or_restoring(tmp_path):
    data, life_id, _ = _history(tmp_path)
    before = _hashes(data)
    output = tmp_path / "evidence" / "history.json"

    assert main([
        "--data-root", str(data),
        "--life-id", life_id,
        "--target", "1:9472",
        "--target", "2:9532",
        "--output", str(output),
    ]) == 0

    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["ok"] is True
    assert manifest["source_data"]["unchanged"] is True
    assert manifest["restored_backup"] is False
    assert manifest["deleted_paths"] == []
    assert manifest["autonomous_ticks"] == 0
    assert manifest["deletion_authorized"] is False
    assert _hashes(data) == before
