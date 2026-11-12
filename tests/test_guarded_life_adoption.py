"""Guarded adoption исполняется только на временных v1-жизнях."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


from src.memory.checkpoint_store import SQLiteCheckpointStore
from src.memory.life_database import LifeDatabase
from src.memory.profile_backup import create_backup, restore_backup
from tools.manual.adopt_life_artifacts import main


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema(path: Path):
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
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


def _life(tmp_path: Path):
    data = tmp_path / "data"
    life_id = str(uuid4())
    life_dir = data / "lives" / life_id
    life_dir.mkdir(parents=True)
    (data / "active_profile.json").write_text(
        json.dumps({"life_id": life_id, "name": "TestLife"}), encoding="utf-8"
    )
    database = life_dir / "life.sqlite3"
    store = SQLiteCheckpointStore(database)
    state = {
        "life_id": life_id,
        "name": "TestLife",
        "cycle_count": 7,
        "goals": [{"id": "goal-1", "title": "Сохраниться"}],
    }
    snapshot_id = store.save(state, life_id, 7, saved_at="2026-11-11T00:00:00+00:00")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE meta("
            "key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        for key, value in (
            ("life_id", life_id),
            ("storage_kind", "life"),
            ("storage_schema_version", 1),
            ("latest_snapshot_id", snapshot_id),
        ):
            connection.execute(
                "INSERT INTO meta VALUES (?, ?, datetime('now'))",
                (key, json.dumps(value)),
            )
        connection.execute("PRAGMA user_version=1")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    creative = data / "delamain" / "workspace" / "creative"
    (creative / "notes").mkdir(parents=True)
    (creative / "a.txt").write_text("первый", encoding="utf-8")
    (creative / "notes" / "b.txt").write_text("второй", encoding="utf-8")
    proposals = data / "architecture_proposals"
    proposals.mkdir()
    proposal = {
        "id": "prop_test",
        "type": "config_change",
        "title": "Проверка",
        "description": "Описание",
        "code_snippet": "",
        "status": "pending",
        "created_at": "2026-11-11T00:00:00+00:00",
        "cycle": 7,
        "extra": {"preserved": True},
    }
    (proposals / "prop_test.json").write_text(
        json.dumps(proposal, ensure_ascii=False), encoding="utf-8"
    )
    backup = tmp_path / "pre-backup"
    create_backup(data, backup)
    return data, life_id, backup


def _args(data: Path, life_id: str, output: Path):
    return [
        "--life-id",
        life_id,
        "--data-dir",
        str(data),
        "--output",
        str(output),
    ]


def _dry_run(tmp_path: Path, data: Path, life_id: str, backup: Path):
    output = tmp_path / "manifest.json"
    code = main(_args(data, life_id, output) + ["--pre-backup", str(backup)])
    assert code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["ok"] is True
    return output, report, _hash(output)


def _execute(tmp_path: Path, data: Path, life_id: str, backup: Path, manifest, digest):
    output = tmp_path / "execution.json"
    code = main(
        _args(data, life_id, output)
        + [
            "--execute-live",
            "--pre-backup",
            str(backup),
            "--manifest",
            str(manifest),
            "--manifest-sha256",
            digest,
        ]
    )
    return code, output


def test_dry_run_has_no_side_effects_and_manifest_is_exact(tmp_path, capsys):
    data, life_id, backup = _life(tmp_path)
    protected = [
        data / "active_profile.json",
        data / "lives" / life_id / "life.sqlite3",
    ]
    protected.extend(
        sorted((data / "delamain" / "workspace" / "creative").rglob("*.txt"))
    )
    protected.append(data / "architecture_proposals" / "prop_test.json")
    before = {path: _hash(path) for path in protected}

    manifest, report, digest = _dry_run(tmp_path, data, life_id, backup)
    capsys.readouterr()

    assert report["mode"] == "dry-run"
    assert report["expected_counts"] == {
        "creative": 2,
        "architecture_proposal": 1,
        "total": 3,
    }
    assert len(digest) == 64
    assert {path: _hash(path) for path in protected} == before
    assert _schema(data / "lives" / life_id / "life.sqlite3")[0] == 1
    assert not (data / "lives" / life_id / "artifacts").exists()
    assert manifest.parent != data


def test_successful_v1_v3_adoption_backup_restore_and_reopen(tmp_path, capsys):
    data, life_id, backup = _life(tmp_path)
    manifest, before, digest = _dry_run(tmp_path, data, life_id, backup)
    originals = {
        item["source_relative_path"]: item["sha256"]
        for item in before["expected_artifacts"]
    }

    code, output = _execute(tmp_path, data, life_id, backup, manifest, digest)
    capsys.readouterr()
    report = json.loads(output.read_text(encoding="utf-8"))

    assert code == 0, (
        report.get("manifest_mismatches", report["errors"]),
        report.get("preflight_changed_paths"),
    )
    assert report["ok"] is True
    assert report["execution_started"] is True
    assert report["unexpected_changed_paths"] == []
    assert report["protected_mismatches"] == []
    assert report["proposal_roundtrip"] is True
    assert report["verify_artifacts"] == {"ok": True, "checked": 3, "problems": []}
    assert report["after_database"]["snapshots"] == before["database"]["snapshots"]
    assert report["autonomous_ticks"] == 0
    assert report["deleted_paths"] == []
    assert report["deletion_authorized"] is False

    database_path = data / "lives" / life_id / "life.sqlite3"
    version, _tables, meta = _schema(database_path)
    assert version == 3 and meta["storage_schema_version"] == 3
    database = LifeDatabase(database_path, life_id)
    assert database.checkpoints.load(meta["latest_snapshot_id"])["goals"] == [
        {"id": "goal-1", "title": "Сохраниться"}
    ]
    for relative, digest_before in originals.items():
        assert _hash(data / relative) == digest_before

    post_backup = tmp_path / "post-backup"
    restored = tmp_path / "restored"
    create_backup(data, post_backup)
    restore_backup(post_backup, restored)
    restored_db = restored / "lives" / life_id / "life.sqlite3"
    assert _schema(restored_db)[0] == 3
    assert (
        restored_db.read_bytes()
        == (post_backup / "lives" / life_id / "life.sqlite3").read_bytes()
    )
    reopened = LifeDatabase(restored_db, life_id)
    assert reopened.verify_artifacts() == {"ok": True, "checked": 3, "problems": []}


def test_empty_active_database_sidecars_do_not_invalidate_manifest(tmp_path, capsys):
    data, life_id, backup = _life(tmp_path)
    manifest, before, digest = _dry_run(tmp_path, data, life_id, backup)
    database = data / "lives" / life_id / "life.sqlite3"
    sidecars = {
        f"lives/{life_id}/life.sqlite3-wal",
        f"lives/{life_id}/life.sqlite3-shm",
    }
    assert sidecars.isdisjoint(before["data_file_hashes"])
    Path(str(database) + "-wal").write_bytes(b"")
    shm = Path(str(database) + "-shm")
    if not shm.exists():
        shm.write_bytes(b"")

    code, output = _execute(tmp_path, data, life_id, backup, manifest, digest)
    capsys.readouterr()
    report = json.loads(output.read_text(encoding="utf-8"))

    assert code == 0, report.get("errors")
    assert report["execution_started"] is True
    assert report["protected_mismatches"] == []
    assert report["unexpected_changed_paths"] == []


def test_nonempty_wal_after_dry_run_blocks_execution(tmp_path, capsys):
    data, life_id, backup = _life(tmp_path)
    manifest, _report, digest = _dry_run(tmp_path, data, life_id, backup)
    database = data / "lives" / life_id / "life.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            "INSERT INTO meta VALUES ('wal_after_dry_run', '1', datetime('now'))"
        )
        connection.commit()
        assert Path(str(database) + "-wal").stat().st_size > 0

        code, output = _execute(tmp_path, data, life_id, backup, manifest, digest)
        capsys.readouterr()
        report = json.loads(output.read_text(encoding="utf-8"))

        assert code == 1
        assert not report.get("execution_started", False)
        assert "WAL непуст" in " ".join(report["errors"])
        assert _schema(database)[0] == 1


def test_wrong_manifest_hash_blocks_before_any_write(tmp_path, capsys):
    data, life_id, backup = _life(tmp_path)
    manifest, _report, _digest = _dry_run(tmp_path, data, life_id, backup)
    database = data / "lives" / life_id / "life.sqlite3"
    before = database.read_bytes()

    code, output = _execute(tmp_path, data, life_id, backup, manifest, "0" * 64)
    capsys.readouterr()
    report = json.loads(output.read_text(encoding="utf-8"))

    assert code == 1 and report["execution_started"] is False
    assert database.read_bytes() == before
    assert _schema(database)[0] == 1
    assert not (data / "lives" / life_id / "artifacts").exists()


def test_unexpected_new_legacy_file_blocks_execution(tmp_path, capsys):
    data, life_id, backup = _life(tmp_path)
    manifest, _report, digest = _dry_run(tmp_path, data, life_id, backup)
    extra = data / "delamain" / "workspace" / "creative" / "unexpected.txt"
    extra.write_text("новый", encoding="utf-8")
    database = data / "lives" / life_id / "life.sqlite3"
    before = database.read_bytes()

    code, output = _execute(tmp_path, data, life_id, backup, manifest, digest)
    capsys.readouterr()
    report = json.loads(output.read_text(encoding="utf-8"))

    assert code == 1 and report["execution_started"] is False
    assert database.read_bytes() == before
    assert not (data / "lives" / life_id / "artifacts").exists()


def test_existing_target_and_invalid_proposal_fail_dry_run_without_migration(tmp_path):
    data, life_id, backup = _life(tmp_path)
    target = data / "lives" / life_id / "artifacts" / "creative" / "a.txt"
    target.parent.mkdir(parents=True)
    target.write_text("чужое содержимое", encoding="utf-8")
    (data / "architecture_proposals" / "broken.json").write_text("[]", encoding="utf-8")
    database = data / "lives" / life_id / "life.sqlite3"
    before = database.read_bytes()

    code = main(
        _args(data, life_id, tmp_path / "blocked.json")
        + [
            "--pre-backup",
            str(backup),
        ]
    )

    assert code == 1
    assert database.read_bytes() == before
    assert _schema(database)[0] == 1
    assert target.read_text(encoding="utf-8") == "чужое содержимое"


def test_nonempty_wal_blocks_dry_run(tmp_path):
    data, life_id, backup = _life(tmp_path)
    database = data / "lives" / life_id / "life.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            "INSERT INTO meta VALUES ('uncommitted_to_checkpoint', '1', datetime('now'))"
        )
        connection.commit()
        assert Path(str(database) + "-wal").stat().st_size > 0

        code = main(
            _args(data, life_id, tmp_path / "wal.json")
            + [
                "--pre-backup",
                str(backup),
            ]
        )

        assert code == 1
        assert _schema(database)[0] == 1


def test_partial_creative_error_stops_without_proposal_or_retry(
    tmp_path, monkeypatch, capsys
):
    data, life_id, backup = _life(tmp_path)
    manifest, _report, digest = _dry_run(tmp_path, data, life_id, backup)
    from src.core import activity_workspace

    original_copy = activity_workspace.shutil.copy2
    calls = {"count": 0}

    def fail_second(source, target):
        calls["count"] += 1
        if calls["count"] == 2:
            raise PermissionError("injected partial copy failure")
        return original_copy(source, target)

    monkeypatch.setattr(activity_workspace.shutil, "copy2", fail_second)
    code, output = _execute(tmp_path, data, life_id, backup, manifest, digest)
    capsys.readouterr()
    report = json.loads(output.read_text(encoding="utf-8"))

    assert code == 1
    assert report["execution_started"] is True, (
        report.get("manifest_mismatches", report["errors"]),
        report.get("preflight_changed_paths"),
    )
    assert report["creative"]["errors"]
    assert "proposals" not in report
    assert report["ok"] is False
    assert report["deletion_authorized"] is False
    assert report["after_database"]["user_version"] == 3
    assert report["after_database"]["architecture_proposal_count"] == 0

    monkeypatch.setattr(activity_workspace.shutil, "copy2", original_copy)
    retry_output = tmp_path / "retry.json"
    retry = main(
        _args(data, life_id, retry_output)
        + [
            "--execute-live",
            "--pre-backup",
            str(backup),
            "--manifest",
            str(manifest),
            "--manifest-sha256",
            digest,
        ]
    )
    capsys.readouterr()
    retry_report = json.loads(retry_output.read_text(encoding="utf-8"))
    assert retry == 1
    assert retry_report["execution_started"] is False


def test_verify_artifacts_failure_is_fatal_even_with_zero_api_errors(
    tmp_path, monkeypatch, capsys
):
    data, life_id, backup = _life(tmp_path)
    manifest, _report, digest = _dry_run(tmp_path, data, life_id, backup)
    monkeypatch.setattr(
        LifeDatabase,
        "verify_artifacts",
        lambda self: {"ok": False, "checked": 3, "problems": [{"problem": "injected"}]},
    )

    code, output = _execute(tmp_path, data, life_id, backup, manifest, digest)
    capsys.readouterr()
    report = json.loads(output.read_text(encoding="utf-8"))

    assert code == 1
    assert "creative" in report, {
        "errors": report.get("errors"),
        "execution_started": report.get("execution_started"),
        "manifest_mismatches": report.get("manifest_mismatches"),
        "preflight_changed_paths": report.get("preflight_changed_paths"),
    }
    assert report["creative"]["errors"] == []
    assert report["proposals"]["errors"] == []
    assert report["ok"] is False
    assert "verify_artifacts не пройден" in report["errors"]


def test_existing_output_is_not_overwritten(tmp_path, capsys):
    data, life_id, _backup = _life(tmp_path)
    output = tmp_path / "existing.json"
    output.write_text("keep-me", encoding="utf-8")
    database = data / "lives" / life_id / "life.sqlite3"
    before = database.read_bytes()

    code = main(_args(data, life_id, output))
    capsys.readouterr()

    assert code == 1
    assert output.read_text(encoding="utf-8") == "keep-me"
    assert database.read_bytes() == before
    assert _schema(database)[0] == 1
