"""One-to-many сверка одного legacy cycle и нескольких SQL snapshots."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from src.memory.life_database import LifeDatabase
from tools.manual.verify_stage6_cycle_consolidation import (
    main,
    verify_cycle_consolidation,
)


def _hashes(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def _case(tmp_path):
    data = tmp_path / "data"
    life_id = str(uuid4())
    checkpoints = data / "checkpoints" / life_id
    checkpoints.mkdir(parents=True)
    (data / "active_profile.json").write_text(
        json.dumps({"name": "TestLife", "life_id": life_id}), encoding="utf-8"
    )
    database = LifeDatabase(data / "lives" / life_id / "life.sqlite3", life_id)
    states = []
    snapshot_ids = []
    for index, energy in enumerate((100, 99, 98), 1):
        state = {
            "schema_version": 1,
            "life_id": life_id,
            "name": "TestLife",
            "cycle_count": 10553,
            "energy": energy,
            "goals": [],
            "saved_at": f"2026-11-10T23:0{index}:00+00:00",
        }
        states.append(state)
        snapshot_ids.append(database.save_checkpoint(
            state, 10553, saved_at=state["saved_at"]
        ))
    (checkpoints / f"{life_id}_cycle_10553.json").write_text(
        json.dumps(states[0]), encoding="utf-8"
    )
    with database.connect(readonly=True) as connection:
        root = json.loads(connection.execute(
            "SELECT manifest FROM snapshots WHERE id=?", (snapshot_ids[0],)
        ).fetchone()[0])["root"]
    with database.write() as connection:
        connection.execute(
            "INSERT INTO migration_runs"
            "(id, started_at, finished_at, source_manifest_json, counts_json, "
            "hashes_json, status) VALUES ('migration', 'start', 'finish', '{}', '{}', "
            "?, 'verified')",
            (json.dumps({str(snapshot_ids[0]): root}),),
        )
    # Подготовка тестовой базы завершена: read-only verifier допускает только пустой WAL.
    with database.connect() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return data, life_id, states, snapshot_ids


def test_one_to_many_manifest_maps_legacy_and_sql_only_snapshots(tmp_path):
    data, life_id, _, snapshot_ids = _case(tmp_path)
    before = _hashes(data)

    report = verify_cycle_consolidation(
        data, life_id, snapshot_ids=snapshot_ids
    )

    assert report["ok"] is True, report["errors"]
    assert report["consolidation"]["legacy_snapshot_id"] == snapshot_ids[0]
    assert report["consolidation"]["sql_only_additional_snapshot_ids"] == snapshot_ids[1:]
    assert report["consolidation"]["one_to_many_verified"] is True
    assert [item["verified"] for item in report["snapshots"]] == [True, True, True]
    assert report["snapshots"][0]["snapshot_root_sha256"] == (
        report["snapshots"][0]["migration_root_sha256"]
    )
    assert all(
        item["migration_root_sha256"] is None for item in report["snapshots"][1:]
    )
    assert report["state_transitions"][0]["changed_top_level_keys"] == [
        "energy", "saved_at"
    ]
    assert report["deletion_authorized"] is False
    assert _hashes(data) == before


def test_legacy_must_match_the_designated_original_snapshot(tmp_path):
    data, life_id, states, snapshot_ids = _case(tmp_path)
    path = data / "checkpoints" / life_id / f"{life_id}_cycle_10553.json"
    path.write_text(json.dumps(states[1]), encoding="utf-8")

    report = verify_cycle_consolidation(
        data, life_id, snapshot_ids=snapshot_ids
    )

    assert report["ok"] is False
    assert report["snapshots"][0]["verified"] is False
    assert any("полное состояние" in error for error in report["errors"])
    assert report["deletion_authorized"] is False


def test_consolidation_cli_preserves_data_and_does_not_delete(tmp_path):
    data, life_id, _, snapshot_ids = _case(tmp_path)
    before = _hashes(data)
    output = tmp_path / "evidence" / "consolidated.json"
    ids = ",".join(str(value) for value in snapshot_ids)

    assert main([
        "--data-root", str(data),
        "--life-id", life_id,
        "--snapshot-ids", ids,
        "--output", str(output),
    ]) == 0

    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["ok"] is True
    assert manifest["source_data"]["unchanged"] is True
    assert manifest["deleted_paths"] == []
    assert manifest["autonomous_ticks"] == 0
    assert manifest["deletion_authorized"] is False
    assert _hashes(data) == before
