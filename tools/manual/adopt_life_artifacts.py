"""Dry-run и контролируемый учёт legacy-артефактов за UUID жизни.

По умолчанию выполняется только read-only preflight: SQLite открывается через
``mode=ro&immutable=1`` при пустом WAL, создаётся манифест вне ``data/``.
Для записи обязательны ``--execute-live``, проверенный pre-backup, манифест и
его SHA-256. Оригиналы не изменяются и не удаляются; runner/тики не запускаются.
"""

from __future__ import annotations

import argparse
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.life_identity import validate_life_id  # noqa: E402
from src.core.subsystems.architecture_proposal import ArchitectureProposal  # noqa: E402
from src.memory.checkpoint_store import SQLiteCheckpointStore  # noqa: E402
from src.memory.checkpoint_verifier import _file_hash, _read_meta, _state_hash  # noqa: E402
from src.memory.profile_backup import verify_backup  # noqa: E402
from tools.manual.verify_stage6_checkpoints import _inventory  # noqa: E402

KIND = "life_artifact_adoption"
VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summary(inventory: dict) -> dict:
    return {key: value for key, value in inventory.items() if key != "files"}


def _fingerprint_without_sidecars(
    inventory: dict, data_root: Path, life_id: str,
) -> dict:
    """Исключить только transient WAL/SHM активной БД из сравнения манифестов."""
    database = f"lives/{life_id}/life.sqlite3"
    excluded = {database + "-wal", database + "-shm"}
    files = {
        path: digest for path, digest in inventory["files"].items()
        if path not in excluded
    }
    combined = hashlib.sha256()
    for relative, content_hash in files.items():
        combined.update(relative.encode("utf-8"))
        combined.update(b"\0")
        combined.update(content_hash.encode("ascii"))
        combined.update(b"\n")
    return {
        "files": files,
        "file_count": len(files),
        "bytes": sum((data_root / path).stat().st_size for path in files),
        "aggregate_sha256": combined.hexdigest(),
    }


def _json_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _outside_data(output: Path, data_root: Path) -> None:
    if output.resolve().is_relative_to(data_root.resolve()):
        raise ValueError(f"Отчёт нельзя записывать внутрь data/: {output}")


def _write_json(output: Path, report: dict) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _inspect_database(path: Path, life_id: str) -> dict:
    """Строгое read-only чтение без конструкторов, меняющих схему."""
    path = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"База жизни не найдена или является ссылкой: {path}")
    wal = Path(str(path) + "-wal")
    wal_bytes = wal.stat().st_size if wal.exists() else 0
    if wal_bytes:
        raise ValueError(
            "WAL непуст: остановите writers и используйте согласованный backup; "
            "immutable-чтение запрещено"
        )
    with closing(sqlite3.connect(
        path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=30
    )) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        foreign_keys = [list(row) for row in connection.execute(
            "PRAGMA foreign_key_check"
        )]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = sorted(row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ))
        meta = _read_meta(connection)
        artifact_count = 0
        if "artifacts" in tables:
            artifact_count = connection.execute(
                "SELECT COUNT(*) FROM artifacts"
            ).fetchone()[0]
        proposal_count = 0
        if "architecture_proposals" in tables:
            proposal_count = connection.execute(
                "SELECT COUNT(*) FROM architecture_proposals"
            ).fetchone()[0]
        snapshot_rows = connection.execute(
            "SELECT id, agent_name, cycle, saved_at, manifest "
            "FROM snapshots ORDER BY id"
        ).fetchall()
        decoder = SQLiteCheckpointStore.__new__(SQLiteCheckpointStore)
        decoder.path = path
        snapshots = []
        for row in snapshot_rows:
            root = decoder._manifest_root(row["manifest"])
            state = decoder._decode(connection, root, set(), expected="dict")
            snapshots.append({
                "snapshot_id": int(row["id"]),
                "agent_name": row["agent_name"],
                "cycle": int(row["cycle"]),
                "saved_at": row["saved_at"],
                "root_sha256": root,
                "state_sha256": _state_hash(state),
            })
        latest = snapshots[-1]["snapshot_id"] if snapshots else None
        return {
            "path": str(path),
            "opened_read_only": True,
            "query_only": connection.execute("PRAGMA query_only").fetchone()[0],
            "wal_bytes": wal_bytes,
            "user_version": version,
            "storage_schema_version": meta.get("storage_schema_version"),
            "life_id": meta.get("life_id"),
            "latest_snapshot_id": latest,
            "meta_latest_snapshot_id": meta.get("latest_snapshot_id"),
            "integrity_check": integrity,
            "foreign_key_check": foreign_keys,
            "tables": tables,
            "artifact_count": artifact_count,
            "architecture_proposal_count": proposal_count,
            "snapshot_count": len(snapshots),
            "snapshots": snapshots,
        }


def _database_errors(database: dict, life_id: str) -> list[str]:
    errors = []
    if database["integrity_check"] != ["ok"]:
        errors.append("SQLite integrity_check не пройден")
    if database["foreign_key_check"]:
        errors.append("SQLite foreign_key_check содержит нарушения")
    if database["life_id"] != life_id:
        errors.append("meta.life_id не совпадает с запрошенным UUID")
    if database["latest_snapshot_id"] != database["meta_latest_snapshot_id"]:
        errors.append("meta.latest_snapshot_id не совпадает с последним snapshot")
    owners = sorted({item["agent_name"] for item in database["snapshots"]})
    if owners not in ([], [life_id]):
        errors.append(f"Владельцы snapshots не совпадают с UUID: {owners}")
    return errors


def _source_root(path: Path, data_root: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(data_root):
        raise ValueError(f"{label} должен находиться внутри data/: {resolved}")
    if path.is_symlink() or not resolved.is_dir():
        raise ValueError(f"{label} не найден или является ссылкой: {resolved}")
    return resolved


def _artifact_record(
    source: Path, *, source_root: Path, data_root: Path, life_dir: Path,
    kind: str, target_relative: Path,
) -> dict:
    relative = target_relative.as_posix()
    target = life_dir / target_relative
    if target.exists() or target.is_symlink():
        raise ValueError(f"Целевой путь уже существует: {target}")
    return {
        "kind": kind,
        "source_path": str(source),
        "source_relative_path": source.relative_to(data_root).as_posix(),
        "source_name": source.relative_to(source_root).as_posix(),
        "relative_path": relative,
        "target_path": str(target),
        "bytes": source.stat().st_size,
        "sha256": _file_hash(source),
    }


def _collect_sources(
    data_root: Path, life_dir: Path, creative_root: Path, proposals_dir: Path,
) -> tuple[list[dict], dict, list[str]]:
    errors: list[str] = []
    artifacts: list[dict] = []
    proposals: dict[str, dict] = {}
    for path in sorted(creative_root.rglob("*")):
        if path.is_symlink():
            errors.append(f"Symlink в creative запрещён: {path}")
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            errors.append(f"Неожиданный элемент creative: {path}")
            continue
        try:
            relative = Path("artifacts") / "creative" / path.relative_to(creative_root)
            artifacts.append(_artifact_record(
                path, source_root=creative_root, data_root=data_root,
                life_dir=life_dir, kind="creative", target_relative=relative,
            ))
        except Exception as exc:
            errors.append(str(exc))

    normalizer = object.__new__(ArchitectureProposal)
    for path in sorted(proposals_dir.iterdir()):
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            errors.append(f"Неожиданный элемент предложений: {path}")
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"Предложение должно быть словарём: {path}")
            if not raw.get("created_at"):
                raise ValueError(f"Для guarded import нужен created_at: {path}")
            normalized = normalizer._normalize(raw, path.stem)
            proposal_id = normalized["id"]
            if proposal_id in proposals:
                raise ValueError(f"Повторяющийся id предложения: {proposal_id}")
            relative = ArchitectureProposal.EXPORT_DIR / path.name
            record = _artifact_record(
                path, source_root=proposals_dir, data_root=data_root,
                life_dir=life_dir, kind="architecture_proposal",
                target_relative=relative,
            )
            record["normalized"] = normalized
            proposals[proposal_id] = record
            artifacts.append(record)
        except Exception as exc:
            errors.append(str(exc))
    return artifacts, proposals, errors


def _backup_evidence(
    backup: Path, data_root: Path, life_id: str,
    expected_artifacts: list[dict], live_database: dict,
) -> tuple[dict, list[str]]:
    errors: list[str] = []
    manifest = verify_backup(backup)
    entries = {item["path"]: item for item in manifest["files"]}
    required = {
        "active_profile.json",
        f"lives/{life_id}/life.sqlite3",
        *(item["source_relative_path"] for item in expected_artifacts),
    }
    missing = sorted(required - set(entries))
    if missing:
        errors.append(f"Pre-backup не содержит обязательные файлы: {missing}")
    for item in expected_artifacts:
        entry = entries.get(item["source_relative_path"])
        if entry is not None and entry["sha256"] != item["sha256"]:
            errors.append(f"Pre-backup hash mismatch: {item['source_relative_path']}")
    backup_database = backup / "lives" / life_id / "life.sqlite3"
    if backup_database.is_file():
        inspected = _inspect_database(backup_database, life_id)
        if inspected["user_version"] != live_database["user_version"]:
            errors.append("Схема backup не совпадает с активной базой")
        if inspected["snapshots"] != live_database["snapshots"]:
            errors.append("Snapshots backup не совпадают с активной базой")
        if inspected["meta_latest_snapshot_id"] != live_database[
            "meta_latest_snapshot_id"
        ]:
            errors.append("latest_snapshot_id backup не совпадает с активной базой")
    evidence = {
        "path": str(backup.resolve()),
        "manifest_sha256": _json_hash(backup / "manifest.json"),
        "file_count": len(manifest["files"]),
        "verified": True,
        "required_files_present": not missing,
    }
    return evidence, errors


def _preflight(
    data_root: Path, life_id: str, creative_root: Path | None,
    proposals_dir: Path | None, pre_backup: Path | None,
) -> tuple[dict, dict]:
    life_id = validate_life_id(life_id)
    data_root = data_root.resolve()
    errors: list[str] = []
    profile_path = data_root / "active_profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if profile.get("life_id") != life_id:
        errors.append("active_profile.json содержит другой UUID")
    if not profile.get("name"):
        errors.append("active_profile.json не содержит имя жизни")
    life_dir = data_root / "lives" / life_id
    creative_root = _source_root(
        creative_root or data_root / "delamain" / "workspace" / "creative",
        data_root, "Creative-корень",
    )
    proposals_dir = _source_root(
        proposals_dir or data_root / "architecture_proposals",
        data_root, "Каталог предложений",
    )
    database = _inspect_database(life_dir / "life.sqlite3", life_id)
    errors.extend(_database_errors(database, life_id))
    if database["user_version"] != 1 or database["storage_schema_version"] != 1:
        errors.append("Guarded adoption допускается только из storage schema v1")
    if database["artifact_count"] != 0:
        errors.append("Исходный реестр artifacts должен быть пуст")
    if database["architecture_proposal_count"] != 0:
        errors.append("Исходная таблица architecture_proposals должна быть пуста")
    expected_artifacts, proposals, source_errors = _collect_sources(
        data_root, life_dir, creative_root, proposals_dir,
    )
    errors.extend(source_errors)
    backup_evidence = None
    if pre_backup is not None:
        backup_evidence, backup_errors = _backup_evidence(
            pre_backup.resolve(), data_root, life_id, expected_artifacts, database,
        )
        errors.extend(backup_errors)
    protected = {"active_profile.json": _file_hash(profile_path)}
    protected.update({
        item["source_relative_path"]: item["sha256"] for item in expected_artifacts
    })
    # Только после закрытия SQLite-соединений: пустые WAL/SHM могут исчезнуть.
    inventory = _inventory(data_root)
    wal = Path(str(life_dir / "life.sqlite3") + "-wal")
    if wal.is_file() and wal.stat().st_size:
        errors.append("WAL стал непустым во время preflight; execution запрещён")
    fingerprint = _fingerprint_without_sidecars(inventory, data_root, life_id)
    manifest = {
        "kind": KIND,
        "version": VERSION,
        "mode": "dry-run",
        "created_at": _now(),
        "ok": not errors,
        "life_id": life_id,
        "profile_name": profile.get("name"),
        "data_root": str(data_root),
        "creative_root": str(creative_root),
        "proposals_dir": str(proposals_dir),
        "database": database,
        "expected_artifacts": expected_artifacts,
        "expected_counts": {
            "creative": sum(item["kind"] == "creative" for item in expected_artifacts),
            "architecture_proposal": len(proposals),
            "total": len(expected_artifacts),
        },
        "protected_files": protected,
        "pre_backup": backup_evidence,
        "data_fingerprint": _summary(fingerprint),
        "data_file_hashes": fingerprint["files"],
        "autonomous_ticks": 0,
        "deleted_paths": [],
        "deletion_authorized": False,
        "errors": errors,
    }
    return manifest, inventory


def _comparable(manifest: dict) -> dict:
    value = deepcopy(manifest)
    for key in ("created_at", "mode", "ok", "errors"):
        value.pop(key, None)
    return value


def _checkpoint_wal(path: Path) -> None:
    with closing(sqlite3.connect(str(path), timeout=30)) as connection:
        connection.execute("PRAGMA busy_timeout=30000")
        busy, log, checkpointed = connection.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)"
        ).fetchone()
    if busy or log != checkpointed:
        raise RuntimeError(
            f"WAL checkpoint не завершён: busy={busy}, log={log}, "
            f"checkpointed={checkpointed}"
        )


def _changed_paths(before: dict, after: dict) -> list[str]:
    return [
        path for path in sorted(set(before["files"]) | set(after["files"]))
        if before["files"].get(path) != after["files"].get(path)
    ]


def _execute(
    manifest_path: Path, expected_hash: str, data_root: Path, life_id: str,
    creative_root: Path | None, proposals_dir: Path | None, pre_backup: Path,
) -> dict:
    approved = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_hash = _json_hash(manifest_path)
    report = {
        "kind": KIND,
        "version": VERSION,
        "mode": "execute-live",
        "created_at": _now(),
        "ok": False,
        "life_id": life_id,
        "approved_manifest": str(manifest_path.resolve()),
        "approved_manifest_sha256": actual_hash,
        "execution_started": False,
        "autonomous_ticks": 0,
        "deleted_paths": [],
        "deletion_authorized": False,
        "errors": [],
    }
    if actual_hash.lower() != expected_hash.lower():
        report["errors"].append("SHA-256 утверждённого манифеста не совпал")
        return report
    if approved.get("kind") != KIND or approved.get("version") != VERSION:
        report["errors"].append("Неподдерживаемый тип манифеста")
        return report
    if not approved.get("ok") or approved.get("mode") != "dry-run":
        report["errors"].append("Манифест dry-run не является успешным")
        return report
    current, before_inventory = _preflight(
        data_root, life_id, creative_root, proposals_dir, pre_backup,
    )
    report["before"] = current
    if current["errors"]:
        report["errors"].extend(current["errors"])
        return report
    if _comparable(current) != _comparable(approved):
        approved_keys = _comparable(approved)
        current_keys = _comparable(current)
        changed = sorted(
            key for key in set(approved_keys) | set(current_keys)
            if approved_keys.get(key) != current_keys.get(key)
        )
        report["manifest_mismatches"] = {
            key: {"approved": approved_keys.get(key), "current": current_keys.get(key)}
            for key in changed if key != "data_file_hashes"
        }
        approved_files = approved.get("data_file_hashes", {})
        current_files = current.get("data_file_hashes", {})
        report["preflight_changed_paths"] = [
            path for path in sorted(set(approved_files) | set(current_files))
            if approved_files.get(path) != current_files.get(path)
        ]
        report["errors"].append(f"Текущий preflight отличается от манифеста: {changed}")
        return report

    data_root = data_root.resolve()
    life_dir = data_root / "lives" / life_id
    database_path = life_dir / "life.sqlite3"
    previous_data = os.environ.get("DIGITAL_BEING_DATA_DIR")
    try:
        os.environ["DIGITAL_BEING_DATA_DIR"] = str(data_root)
        from src.core.activity_workspace import ActivityWorkspace
        from src.core.subsystems.will_registry import WillRegistry

        report["execution_started"] = True
        workspace = ActivityWorkspace.for_life(life_id)
        creative = workspace.adopt_legacy_root(str(current["creative_root"]))
        report["creative"] = creative
        if creative["errors"]:
            report["errors"].extend(creative["errors"])
        else:
            proposals_api = ArchitectureProposal(
                registry=WillRegistry(agent_name="legacy_adoption"),
                proposals_dir=str(current["proposals_dir"]), life_id=life_id,
            )
            imported = proposals_api.import_legacy()
            report["proposals"] = imported
            if imported["errors"]:
                report["errors"].extend(imported["errors"])

        database = workspace.database
        _checkpoint_wal(database_path)
        post_database = _inspect_database(database_path, life_id)
        report["after_database"] = post_database
        report["database_errors"] = _database_errors(post_database, life_id)
        report["errors"].extend(report["database_errors"])
        if post_database["user_version"] != 3 or post_database[
            "storage_schema_version"
        ] != 3:
            report["errors"].append("Итоговая схема не является v3")
        if post_database["snapshots"] != current["database"]["snapshots"]:
            report["errors"].append("Snapshots изменились во время adoption")
        if post_database["meta_latest_snapshot_id"] != current["database"][
            "meta_latest_snapshot_id"
        ]:
            report["errors"].append("latest_snapshot_id изменился во время adoption")

        artifact_rows = database.list_artifacts()
        artifacts_verification = database.verify_artifacts()
        report["verify_artifacts"] = artifacts_verification
        if not artifacts_verification["ok"]:
            report["errors"].append("verify_artifacts не пройден")
        actual_artifacts = {item["relative_path"]: item for item in artifact_rows}
        expected_artifacts = {
            item["relative_path"]: item for item in current["expected_artifacts"]
        }
        if set(actual_artifacts) != set(expected_artifacts):
            report["errors"].append("Набор зарегистрированных путей не совпал")
        for relative, expected in expected_artifacts.items():
            actual = actual_artifacts.get(relative)
            if actual is None:
                continue
            for key in ("kind", "bytes", "sha256"):
                if actual[key] != expected[key]:
                    report["errors"].append(f"Artifact {relative}: mismatch {key}")

        with closing(database.connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT id, payload_json FROM architecture_proposals ORDER BY id"
            ).fetchall()
        actual_proposals = {
            row["id"]: json.loads(row["payload_json"]) for row in rows
        }
        expected_proposals = {
            item["normalized"]["id"]: item["normalized"]
            for item in current["expected_artifacts"]
            if item["kind"] == "architecture_proposal"
        }
        if actual_proposals != expected_proposals:
            report["errors"].append("SQL-содержимое предложений не совпало")
        report["proposal_roundtrip"] = actual_proposals == expected_proposals
    except Exception as exc:
        report["errors"].append(f"Execution: {type(exc).__name__}: {exc}")
    finally:
        if previous_data is None:
            os.environ.pop("DIGITAL_BEING_DATA_DIR", None)
        else:
            os.environ["DIGITAL_BEING_DATA_DIR"] = previous_data

    after_inventory = _inventory(data_root)
    changed = _changed_paths(before_inventory, after_inventory)
    database_relative = f"lives/{life_id}/life.sqlite3"
    expected_paths = {
        f"lives/{life_id}/{item['relative_path']}"
        for item in current["expected_artifacts"]
    }
    unexpected = [
        path for path in changed
        if path not in expected_paths
        and path != database_relative
        and not path.startswith(database_relative + "-")
    ]
    protected_mismatches = [
        path for path, digest in current["protected_files"].items()
        if after_inventory["files"].get(path) != digest
    ]
    if unexpected:
        report["errors"].append(f"Неожиданные изменения data/: {unexpected}")
    if protected_mismatches:
        report["errors"].append(f"Legacy-оригиналы изменились: {protected_mismatches}")
    report["after_fingerprint"] = _summary(after_inventory)
    report["changed_paths"] = changed
    report["unexpected_changed_paths"] = unexpected
    report["protected_mismatches"] = protected_mismatches
    report["ok"] = report["execution_started"] and not report["errors"]
    return report


def _default_output(mode: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return ROOT / "tmp" / f"adoption_{mode}_{stamp}.json"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--life-id", required=True, help="UUID жизни")
    parser.add_argument("--data-dir", help="Корень данных; по умолчанию data")
    parser.add_argument("--creative-root", help="Legacy creative-корень внутри data")
    parser.add_argument("--proposals-dir", help="Legacy-предложения внутри data")
    parser.add_argument("--execute-live", action="store_true", help="Разрешить запись")
    parser.add_argument("--pre-backup", type=Path, help="Проверенный pre-change backup")
    parser.add_argument("--manifest", type=Path, help="Утверждённый dry-run манифест")
    parser.add_argument("--manifest-sha256", help="SHA-256 файла манифеста")
    parser.add_argument("--output", type=Path, help="Новый отчёт строго вне data/")
    args = parser.parse_args(argv)
    if args.execute_live:
        missing = [
            name for name in ("pre_backup", "manifest", "manifest_sha256")
            if getattr(args, name) is None
        ]
        if missing:
            parser.error(f"Для --execute-live нужны: {', '.join(missing)}")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    data_root = Path(args.data_dir).resolve() if args.data_dir else (ROOT / "data")
    output = (args.output or _default_output(
        "execute" if args.execute_live else "dry_run"
    )).resolve()
    _outside_data(output, data_root)
    creative_root = Path(args.creative_root) if args.creative_root else None
    proposals_dir = Path(args.proposals_dir) if args.proposals_dir else None
    report_written = False
    try:
        if args.execute_live:
            report = _execute(
                args.manifest.resolve(), args.manifest_sha256, data_root,
                args.life_id, creative_root, proposals_dir, args.pre_backup.resolve(),
            )
        else:
            report, _inventory_before = _preflight(
                data_root, args.life_id, creative_root, proposals_dir,
                args.pre_backup.resolve() if args.pre_backup else None,
            )
        _write_json(output, report)
        report_written = True
    except Exception as exc:
        report = {
            "kind": KIND,
            "version": VERSION,
            "mode": "execute-live" if args.execute_live else "dry-run",
            "created_at": _now(),
            "ok": False,
            "life_id": args.life_id,
            "autonomous_ticks": 0,
            "deleted_paths": [],
            "deletion_authorized": False,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
        if not output.exists():
            _write_json(output, report)
            report_written = True
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.execute_live and report_written:
        print(json.dumps({
            "manifest": str(output), "manifest_sha256": _json_hash(output),
        }, ensure_ascii=False))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
