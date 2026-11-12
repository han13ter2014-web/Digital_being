"""Read-only verifier первого batch этапа 6."""

import hashlib
import json
from uuid import uuid4

import pytest

from src.memory.checkpoint_store import SQLiteCheckpointStore
from src.memory.checkpoint_verifier import verify_checkpoint_batch
from tools.manual.verify_stage6_checkpoints import main


def _hashes(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _batch(tmp_path, cycles=(1, 2)):
    data = tmp_path / "data"
    life_id = str(uuid4())
    checkpoints = data / "checkpoints" / life_id
    checkpoints.mkdir(parents=True)
    (data / "active_profile.json").write_text(
        json.dumps({"name": "TestLife", "life_id": life_id}), encoding="utf-8"
    )
    store = SQLiteCheckpointStore(data / "lives" / life_id / "life.sqlite3")
    states = {}
    for cycle in cycles:
        state = {
            "schema_version": 1,
            "life_id": life_id,
            "name": "TestLife",
            "cycle_count": cycle,
            "energy": 100,
            "goals": [{"id": cycle, "title": f"goal-{cycle}"}],
            "saved_at": f"2026-11-10T18:0{cycle}:00+00:00",
        }
        states[cycle] = state
        (checkpoints / f"{life_id}_cycle_{cycle}.json").write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8"
        )
        store.save(state, life_id, cycle, saved_at=state["saved_at"])
    return data, life_id, states


def test_exact_batch_matches_without_changing_sources(tmp_path):
    data, life_id, _ = _batch(tmp_path)
    before = _hashes(data)

    report = verify_checkpoint_batch(data, life_id, expected_count=2)

    assert report["ok"] is True, report["errors"]
    assert report["legacy_count"] == 2
    assert report["database"]["snapshot_count"] == 2
    assert report["database"]["opened_read_only"] is True
    assert report["database"]["query_only"] == 1
    assert report["database"]["user_version"] == 1
    assert report["database"]["wal_bytes"] == 0
    assert report["database"]["integrity_check"] == ["ok"]
    assert [entry["matched"] for entry in report["entries"]] == [True, True]
    assert all(len(entry["snapshot_root_sha256"]) == 64 for entry in report["entries"])
    assert report["deletion_authorized"] is False
    assert _hashes(data) == before


def test_state_and_timestamp_mismatches_fail_closed(tmp_path):
    data, life_id, states = _batch(tmp_path, cycles=(1,))
    path = data / "checkpoints" / life_id / f"{life_id}_cycle_1.json"
    changed = dict(states[1], energy=99, saved_at="2026-11-11T00:00:00+00:00")
    path.write_text(json.dumps(changed), encoding="utf-8")

    report = verify_checkpoint_batch(data, life_id, expected_count=1)

    assert report["ok"] is False
    entry = report["entries"][0]
    assert entry["matched"] is False
    assert "полное состояние не совпадает" in entry["errors"]
    assert "saved_at не совпадает" in entry["errors"]
    assert entry["differences"]
    assert report["deletion_authorized"] is False


def test_missing_snapshot_and_unexpected_file_fail_closed(tmp_path):
    data, life_id, _ = _batch(tmp_path)
    (data / "checkpoints" / life_id / f"{life_id}_cycle_2.json").unlink()
    (data / "checkpoints" / life_id / "notes.txt").write_text("keep", encoding="utf-8")

    report = verify_checkpoint_batch(data, life_id, expected_count=2)

    assert report["ok"] is False
    assert report["legacy_count"] == 1
    assert report["unexpected_entries"] == [f"checkpoints/{life_id}/notes.txt"]
    missing = next(entry for entry in report["entries"] if entry["cycle"] == 2)
    assert "legacy-файл отсутствует" in missing["errors"]


def test_duplicate_sqlite_cycle_is_reported_with_snapshot_details(tmp_path):
    data, life_id, states = _batch(tmp_path, cycles=(1,))
    store = SQLiteCheckpointStore(data / "lives" / life_id / "life.sqlite3")
    duplicate_id = store.save(
        states[1], life_id, 1, saved_at="2026-11-11T00:00:00+00:00"
    )
    before = _hashes(data)

    report = verify_checkpoint_batch(data, life_id, expected_count=1)

    assert report["ok"] is False
    duplicate = report["database"]["duplicate_snapshots"][0]
    assert duplicate["cycle"] == 1
    assert duplicate["snapshot_id"] == duplicate_id
    assert duplicate["saved_at"] == "2026-11-11T00:00:00+00:00"
    assert len(duplicate["snapshot_root_sha256"]) == 64
    assert _hashes(data) == before


def test_nonempty_wal_blocks_immutable_read_without_touching_data(tmp_path):
    data, life_id, _ = _batch(tmp_path)
    wal = data / "lives" / life_id / "life.sqlite3-wal"
    wal.write_bytes(b"nonempty-wal-requires-a-controlled-backup")
    before = _hashes(data)

    report = verify_checkpoint_batch(data, life_id, expected_count=2)

    assert report["ok"] is False
    assert report["database"]["opened_read_only"] is False
    assert report["database"]["wal_bytes"] == wal.stat().st_size
    assert any("WAL непуст" in error for error in report["errors"])
    assert _hashes(data) == before


def test_cli_writes_manifest_outside_data_and_never_authorizes_deletion(tmp_path):
    data, life_id, _ = _batch(tmp_path)
    before = _hashes(data)
    output = tmp_path / "result" / "manifest.json"

    assert (
        main(
            [
                "--data-root",
                str(data),
                "--life-id",
                life_id,
                "--expected-count",
                "2",
                "--output",
                str(output),
            ]
        )
        == 0
    )

    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["ok"] is True
    assert manifest["source_data"]["unchanged"] is True
    assert manifest["source_data"]["changed_paths"] == []
    assert manifest["deleted_paths"] == []
    assert manifest["autonomous_ticks"] == 0
    assert manifest["deletion_authorized"] is False
    assert _hashes(data) == before
    with pytest.raises(FileExistsError):
        main(
            [
                "--data-root",
                str(data),
                "--life-id",
                life_id,
                "--output",
                str(output),
            ]
        )


def test_cli_refuses_to_write_manifest_into_data(tmp_path):
    data, life_id, _ = _batch(tmp_path)

    with pytest.raises(ValueError, match="внутрь data"):
        main(
            [
                "--data-root",
                str(data),
                "--life-id",
                life_id,
                "--output",
                str(data / "manifest.json"),
            ]
        )
