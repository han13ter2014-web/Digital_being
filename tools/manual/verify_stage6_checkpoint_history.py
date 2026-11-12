"""Read-only поиск исходных snapshots в проверенных backup-комплектах."""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.checkpoint_migrations import migrate_state
from src.core.checkpoint_serializer import CheckpointSerializer
from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.life_identity import validate_life_id
from src.memory.checkpoint_store import SQLiteCheckpointStore
from src.memory.checkpoint_verifier import _file_hash, _state_hash
from src.memory.profile_backup import verify_backup
from tools.manual.verify_stage6_checkpoints import (
    _inventory,
    _outside_data,
    _write_manifest,
)


def _connect_read_only(path: Path):
    wal = Path(str(path) + "-wal")
    wal_bytes = wal.stat().st_size if wal.exists() else 0
    if wal_bytes:
        raise ValueError(f"WAL непуст, immutable-чтение запрещено: {path}")
    connection = sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True, timeout=30
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA query_only=ON")
    return connection, wal_bytes


def _active_migration_roots(path: Path):
    if not path.is_file():
        return None, None
    with closing(_connect_read_only(path)[0]) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='migration_runs'"
        ).fetchone()
        if table is None:
            return None, None
        row = connection.execute(
            "SELECT id, hashes_json FROM migration_runs "
            "WHERE status='verified' ORDER BY finished_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None, None
        return row["id"], json.loads(row["hashes_json"])


def _load_legacy(data_root: Path, life_id: str, targets: dict[int, int]):
    result = {}
    for snapshot_id, cycle in sorted(targets.items()):
        path = (
            data_root / "checkpoints" / life_id / f"{life_id}_cycle_{cycle}.json"
        )
        record = {
            "cycle": cycle,
            "path": path.relative_to(data_root).as_posix(),
            "bytes": None,
            "sha256": None,
            "state_sha256": None,
            "saved_at": None,
            "errors": [],
        }
        try:
            if not path.is_file() or path.is_symlink():
                raise ValueError("активный legacy-файл отсутствует или является ссылкой")
            record["bytes"] = path.stat().st_size
            record["sha256"] = _file_hash(path)
            state = CheckpointSerializer().load(str(path))
            if state is None:
                raise ValueError("пустой legacy-файл")
            validate_checkpoint_state(state)
            if state.get("life_id") not in (None, life_id):
                raise ValueError("life_id не совпадает")
            if state.get("cycle_count") != cycle:
                raise ValueError("cycle_count не совпадает с именем файла")
            record["state"] = state
            record["state_sha256"] = _state_hash(state)
            record["saved_at"] = state.get("saved_at")
        except Exception as exc:
            record["errors"].append(str(exc))
        result[snapshot_id] = record
    return result


def verify_history(data_root, life_id: str, targets: dict[int, int]) -> dict:
    """Сверить выбранные ID во всех backup; не восстанавливать и не изменять их."""
    data_root = Path(data_root).resolve()
    life_id = validate_life_id(life_id)
    if not targets or any(
        isinstance(key, bool) or not isinstance(key, int) or key < 1
        or isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 0
        for key, cycle in targets.items()
    ):
        raise ValueError("targets должен быть непустым отображением snapshot ID -> cycle")

    errors = []
    legacy = _load_legacy(data_root, life_id, targets)
    for snapshot_id, record in legacy.items():
        for error in record["errors"]:
            errors.append(f"snapshot={snapshot_id}: активный legacy: {error}")

    migration_id = None
    expected_roots = None
    try:
        migration_id, expected_roots = _active_migration_roots(
            data_root / "lives" / life_id / "life.sqlite3"
        )
    except Exception as exc:
        errors.append(f"Не удалось прочитать migration run активной базы: {exc}")

    backups = []
    snapshots_root = data_root / "snapshots"
    manifests = sorted(snapshots_root.glob("*/manifest.json")) if snapshots_root.is_dir() else []
    if not manifests:
        errors.append(f"Резервные комплекты не найдены: {snapshots_root}")

    for manifest_path in manifests:
        backup_root = manifest_path.parent
        backup = {
            "name": backup_root.name,
            "path": str(backup_root),
            "manifest_verified": False,
            "manifest_file_count": 0,
            "profile_life_id_matches": False,
            "database_present": False,
            "integrity_check": [],
            "foreign_key_violations": [],
            "wal_bytes": None,
            "legacy_files": {},
            "snapshots": [],
            "errors": [],
        }
        try:
            manifest = verify_backup(backup_root)
            backup["manifest_verified"] = True
            backup["manifest_file_count"] = len(manifest["files"])
            profile_path = backup_root / "active_profile.json"
            if profile_path.is_file():
                profile = json.loads(profile_path.read_text(encoding="utf-8"))
                backup["profile_life_id_matches"] = profile.get("life_id") == life_id
            if not backup["profile_life_id_matches"]:
                raise ValueError("active_profile резервной копии принадлежит другой жизни")

            for snapshot_id, active in legacy.items():
                backup_path = backup_root / active["path"]
                item = {
                    "present": backup_path.is_file() and not backup_path.is_symlink(),
                    "sha256": None,
                    "matches_active_legacy": False,
                }
                if item["present"]:
                    item["sha256"] = _file_hash(backup_path)
                    item["matches_active_legacy"] = item["sha256"] == active["sha256"]
                backup["legacy_files"][str(snapshot_id)] = item
                if not item["matches_active_legacy"]:
                    message = f"snapshot={snapshot_id}: backup legacy не совпадает с активным"
                    backup["errors"].append(message)
                    errors.append(f"backup={backup_root.name}: {message}")

            database_path = backup_root / "lives" / life_id / "life.sqlite3"
            backup["database_present"] = database_path.is_file()
            if database_path.is_file():
                connection, wal_bytes = _connect_read_only(database_path)
                backup["wal_bytes"] = wal_bytes
                with closing(connection) as owned:
                    backup["integrity_check"] = [
                        row[0] for row in owned.execute("PRAGMA integrity_check")
                    ]
                    backup["foreign_key_violations"] = [
                        list(row) for row in owned.execute("PRAGMA foreign_key_check")
                    ]
                    if backup["integrity_check"] != ["ok"]:
                        raise ValueError("integrity_check резервной SQLite не пройден")
                    if backup["foreign_key_violations"]:
                        raise ValueError("foreign_key_check резервной SQLite содержит нарушения")
                    rows = owned.execute(
                        "SELECT id, agent_name, cycle, saved_at, manifest "
                        "FROM snapshots ORDER BY id"
                    ).fetchall()
                    by_id = {int(row["id"]): row for row in rows}
                    decoder = SQLiteCheckpointStore.__new__(SQLiteCheckpointStore)
                    decoder.path = database_path
                    for snapshot_id, active in legacy.items():
                        expected_cycle = active["cycle"]
                        row = by_id.get(snapshot_id)
                        same_cycle_ids = [
                            int(item["id"]) for item in rows
                            if int(item["cycle"]) == expected_cycle
                        ]
                        entry = {
                            "snapshot_id": snapshot_id,
                            "expected_cycle": expected_cycle,
                            "found": row is not None,
                            "same_cycle_snapshot_ids": same_cycle_ids,
                            "actual_cycle": int(row["cycle"]) if row is not None else None,
                            "saved_at": row["saved_at"] if row is not None else None,
                            "snapshot_root_sha256": None,
                            "migration_root_sha256": (
                                expected_roots.get(str(snapshot_id))
                                if expected_roots is not None else None
                            ),
                            "sqlite_state_sha256": None,
                            "legacy_state_sha256": active["state_sha256"],
                            "matched": False,
                            "errors": list(active["errors"]),
                        }
                        if row is None:
                            entry["errors"].append("snapshot ID отсутствует в этом backup")
                        else:
                            try:
                                if row["agent_name"] != life_id:
                                    raise ValueError("agent_name не совпадает с UUID")
                                if int(row["cycle"]) != expected_cycle:
                                    raise ValueError("cycle snapshot не совпадает с ожидаемым")
                                root = decoder._manifest_root(row["manifest"])
                                entry["snapshot_root_sha256"] = root
                                state = migrate_state(decoder._decode(
                                    owned, root, set(), expected="dict"
                                ))
                                validate_checkpoint_state(state)
                                entry["sqlite_state_sha256"] = _state_hash(state)
                                if "state" not in active or state != active["state"]:
                                    raise ValueError("полное состояние не совпадает с legacy")
                                if entry["sqlite_state_sha256"] != active["state_sha256"]:
                                    raise ValueError("канонический SHA-256 состояния не совпадает")
                                if row["saved_at"] != active["saved_at"]:
                                    raise ValueError("saved_at не совпадает с legacy")
                                if (
                                    entry["migration_root_sha256"] is not None
                                    and root != entry["migration_root_sha256"]
                                ):
                                    raise ValueError("корневой хеш не совпадает с migration run")
                                if not backup["legacy_files"][str(snapshot_id)]["matches_active_legacy"]:
                                    raise ValueError("legacy в backup не совпадает с активным")
                            except Exception as exc:
                                entry["errors"].append(str(exc))
                        entry["matched"] = not entry["errors"]
                        for error in entry["errors"]:
                            if error != "snapshot ID отсутствует в этом backup":
                                errors.append(
                                    f"backup={backup_root.name} snapshot={snapshot_id}: {error}"
                                )
                        backup["snapshots"].append(entry)
        except Exception as exc:
            backup["errors"].append(str(exc))
            errors.append(f"backup={backup_root.name}: {exc}")
        backups.append(backup)

    target_results = []
    for snapshot_id in sorted(targets):
        verified_in = [
            backup["name"] for backup in backups
            if any(
                entry["snapshot_id"] == snapshot_id and entry["matched"]
                for entry in backup["snapshots"]
            )
        ]
        if not verified_in:
            errors.append(f"snapshot={snapshot_id}: ни один backup не подтвердил полное совпадение")
        target_results.append({
            "snapshot_id": snapshot_id,
            "cycle": targets[snapshot_id],
            "verified_in": verified_in,
            "verified": bool(verified_in),
        })

    return {
        "manifest_schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "life_id": life_id,
        "migration_run_id": migration_id,
        "backup_count": len(backups),
        "backups": backups,
        "targets": target_results,
        "ok": not errors,
        "errors": errors,
        "restored_backup": False,
        "deletion_authorized": False,
        "note": (
            "Подтверждение исторических snapshots не разрешает удаление: "
            "остальные gates и отдельное разрешение владельца остаются обязательными."
        ),
    }


def _target(value: str):
    try:
        snapshot_id, cycle = value.split(":", 1)
        return int(snapshot_id), int(cycle)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Ожидается SNAPSHOT_ID:CYCLE") from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only сверка исходных snapshots ID 1–2 в backup-комплектах"
    )
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--life-id")
    parser.add_argument("--target", action="append", type=_target)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "tmp" / "stage6_checkpoint_history_manifest.json",
    )
    args = parser.parse_args(argv)
    data_root = args.data_root.resolve()
    output = args.output.resolve()
    _outside_data(output, data_root)
    if output.exists():
        raise FileExistsError(f"Манифест уже существует: {output}")
    life_id = args.life_id
    if not life_id:
        profile = json.loads((data_root / "active_profile.json").read_text(encoding="utf-8"))
        life_id = profile["life_id"]
    targets = dict(args.target or [(1, 9472), (2, 9532)])
    if len(targets) != len(args.target or [(1, 9472), (2, 9532)]):
        raise ValueError("Повторный snapshot ID в --target")

    before = _inventory(data_root)
    report = verify_history(data_root, life_id, targets)
    after = _inventory(data_root)
    changed = [
        path for path in sorted(set(before["files"]) | set(after["files"]))
        if before["files"].get(path) != after["files"].get(path)
    ]
    history_ok = report["ok"]
    report["source_data"] = {
        "before": {key: value for key, value in before.items() if key != "files"},
        "after": {key: value for key, value in after.items() if key != "files"},
        "unchanged": before == after,
        "changed_paths": changed,
    }
    report["ok"] = history_ok and not changed
    report["autonomous_ticks"] = 0
    report["deleted_paths"] = []
    _write_manifest(output, report)
    print(json.dumps({
        "ok": report["ok"],
        "history_ok": history_ok,
        "manifest": str(output),
        "backup_count": report["backup_count"],
        "targets": report["targets"],
        "source_data_unchanged": report["source_data"]["unchanged"],
        "deletion_authorized": False,
        "errors": report["errors"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
