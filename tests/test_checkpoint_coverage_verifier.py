"""Сводный coverage manifest по 20 legacy и snapshots ID 1–22."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from tools.manual.verify_stage6_checkpoint_coverage import (
    ALLOWED_ACTIVE_ERRORS,
    build_coverage,
    main,
)
from tools.manual.verify_stage6_checkpoints import _inventory


CYCLES = [
    9472, 9532, 9592, 9652, 9712, 9772, 9832, 9892, 9952, 10012,
    10072, 10132, 10192, 10252, 10312, 10372, 10432, 10492, 10552, 10553,
]


def _hash(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def _fingerprint(data):
    inventory = _inventory(data)
    return {
        key: inventory[key] for key in ("file_count", "bytes", "aggregate_sha256")
    }, inventory


def _evidence(tmp_path):
    data = tmp_path / "data"
    life_id = str(uuid4())
    checkpoints = data / "checkpoints" / life_id
    checkpoints.mkdir(parents=True)
    (data / "active_profile.json").write_text(
        json.dumps({"name": "TestLife", "life_id": life_id}), encoding="utf-8"
    )
    entries = []
    for index, cycle in enumerate(CYCLES, 1):
        path = checkpoints / f"{life_id}_cycle_{cycle}.json"
        path.write_text(json.dumps({"cycle": cycle}), encoding="utf-8")
        matched = index > 2
        entries.append({
            "cycle": cycle,
            "legacy_path": path.relative_to(data).as_posix(),
            "legacy_bytes": path.stat().st_size,
            "legacy_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "legacy_state_sha256": _hash(f"state-{index}"),
            "snapshot_id": index if matched else None,
            "snapshot_root_sha256": _hash(f"root-{index}") if matched else None,
            "sqlite_state_sha256": _hash(f"state-{index}") if matched else None,
            "matched": matched,
            "errors": [] if matched else ["SQLite snapshot отсутствует"],
        })
    fingerprint, before = _fingerprint(data)
    common = {
        "life_id": life_id,
        "deletion_authorized": False,
        "deleted_paths": [],
        "source_data": {"after": fingerprint, "unchanged": True},
    }
    migration = "migration-test"
    active = {
        **common,
        "ok": False,
        "errors": list(ALLOWED_ACTIVE_ERRORS.elements()),
        "expected_count": 20,
        "legacy_count": 20,
        "unexpected_entries": [],
        "database": {
            "snapshot_count": 20,
            "latest_snapshot_id": 22,
            "integrity_check": ["ok"],
            "foreign_key_violations": [],
            "verified_migration_run": {"id": migration},
        },
        "entries": entries,
    }
    history_entries = []
    for snapshot_id in (1, 2):
        legacy = entries[snapshot_id - 1]
        history_entries.append({
            "snapshot_id": snapshot_id,
            "matched": True,
            "snapshot_root_sha256": _hash(f"root-{snapshot_id}"),
            "migration_root_sha256": _hash(f"root-{snapshot_id}"),
            "sqlite_state_sha256": legacy["legacy_state_sha256"],
        })
    history = {
        **common,
        "ok": True,
        "errors": [],
        "migration_run_id": migration,
        "restored_backup": False,
        "backups": [{
            "name": "sqlite_verified",
            "manifest_verified": True,
            "snapshots": history_entries,
        }],
        "targets": [
            {
                "snapshot_id": snapshot_id,
                "cycle": CYCLES[snapshot_id - 1],
                "verified": True,
                "verified_in": ["sqlite_verified"],
            }
            for snapshot_id in (1, 2)
        ],
    }
    legacy_10553 = entries[-1]
    consolidation_snapshots = [{
        "snapshot_id": 20,
        "role": "legacy_source",
        "verified": True,
        "snapshot_root_sha256": legacy_10553["snapshot_root_sha256"],
        "sqlite_state_sha256": legacy_10553["sqlite_state_sha256"],
        "migration_root_sha256": legacy_10553["snapshot_root_sha256"],
    }]
    for snapshot_id in (21, 22):
        consolidation_snapshots.append({
            "snapshot_id": snapshot_id,
            "role": "sql_only_additional_in_first_batch",
            "verified": True,
            "snapshot_root_sha256": _hash(f"root-{snapshot_id}"),
            "sqlite_state_sha256": _hash(f"state-{snapshot_id}"),
            "migration_root_sha256": None,
        })
    consolidation = {
        **common,
        "ok": True,
        "errors": [],
        "migration_run_id": migration,
        "cycle": 10553,
        "expected_snapshot_ids": [20, 21, 22],
        "legacy": {
            "expected_snapshot_id": 20,
            "sha256": legacy_10553["legacy_sha256"],
            "state_sha256": legacy_10553["legacy_state_sha256"],
        },
        "snapshots": consolidation_snapshots,
        "consolidation": {"one_to_many_verified": True},
    }
    paths = {}
    for name, report in (
        ("active", active), ("history", history), ("consolidation", consolidation)
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        paths[name] = path
    return data, life_id, paths, before


def test_coverage_combines_all_legacy_and_snapshot_ids(tmp_path):
    data, life_id, paths, before = _evidence(tmp_path)

    report = build_coverage(
        data, life_id, paths["active"], paths["history"],
        paths["consolidation"], current_inventory=before,
    )

    assert report["ok"] is True, report["errors"]
    assert report["summary"]["legacy_total"] == 20
    assert report["summary"]["legacy_covered_by_active"] == 18
    assert report["summary"]["legacy_covered_by_backup"] == 2
    assert report["summary"]["snapshot_total"] == 22
    assert [item["snapshot_id"] for item in report["snapshot_coverage"]] == list(range(1, 23))
    assert report["fresh_sql_decode"] is False
    assert report["deletion_authorized"] is False


def test_changed_current_legacy_invalidates_coverage(tmp_path):
    data, life_id, paths, _ = _evidence(tmp_path)
    path = data / "checkpoints" / life_id / f"{life_id}_cycle_9472.json"
    path.write_text("changed", encoding="utf-8")

    report = build_coverage(
        data, life_id, paths["active"], paths["history"], paths["consolidation"]
    )

    assert report["ok"] is False
    assert any("fingerprint" in error for error in report["errors"])
    assert any("текущий legacy" in error for error in report["errors"])
    assert report["deletion_authorized"] is False


def test_inconsistent_backup_hash_fails_closed(tmp_path):
    data, life_id, paths, before = _evidence(tmp_path)
    history = json.loads(paths["history"].read_text(encoding="utf-8"))
    history["backups"][0]["snapshots"][0]["snapshot_root_sha256"] = _hash("wrong")
    paths["history"].write_text(json.dumps(history), encoding="utf-8")

    report = build_coverage(
        data, life_id, paths["active"], paths["history"],
        paths["consolidation"], current_inventory=before,
    )

    assert report["ok"] is False
    assert any("migration root" in error for error in report["errors"])


def test_coverage_cli_preserves_data_and_records_remaining_gates(tmp_path):
    data, life_id, paths, before = _evidence(tmp_path)
    output = tmp_path / "evidence" / "coverage.json"

    assert main([
        "--data-root", str(data),
        "--life-id", life_id,
        "--active-report", str(paths["active"]),
        "--history-report", str(paths["history"]),
        "--consolidation-report", str(paths["consolidation"]),
        "--output", str(output),
    ]) == 0

    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["ok"] is True
    assert manifest["source_data"]["unchanged"] is True
    assert manifest["deleted_paths"] == []
    assert manifest["autonomous_ticks"] == 0
    assert manifest["remaining_gates"]
    assert manifest["deletion_authorized"] is False
