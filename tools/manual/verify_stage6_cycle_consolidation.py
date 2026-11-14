"""Read-only one-to-many manifest для legacy cycle и нескольких SQL snapshots."""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.checkpoint_migrations import migrate_state  # noqa: E402
from src.core.checkpoint_serializer import CheckpointSerializer  # noqa: E402
from src.core.checkpoint_validation import validate_checkpoint_state  # noqa: E402
from src.core.life_identity import validate_life_id  # noqa: E402
from src.memory.checkpoint_store import SQLiteCheckpointStore  # noqa: E402
from src.memory.checkpoint_verifier import _file_hash, _read_meta, _state_hash  # noqa: E402
from tools.manual.verify_stage6_checkpoint_history import (  # noqa: E402
    _active_migration_roots,
    _connect_read_only,
)
from tools.manual.verify_stage6_checkpoints import (  # noqa: E402
    _inventory,
    _outside_data,
    _write_manifest,
)


def _changed_top_level(left, right):
    if not isinstance(left, dict) or not isinstance(right, dict):
        return []
    return [
        key for key in sorted(set(left) | set(right))
        if key not in left or key not in right or left[key] != right[key]
    ]


def verify_cycle_consolidation(
    data_root, life_id: str, *, cycle=10553, snapshot_ids=(20, 21, 22)
) -> dict:
    """Доказать one-to-many соответствие, не разрешая удаление."""
    data_root = Path(data_root).resolve()
    life_id = validate_life_id(life_id)
    snapshot_ids = tuple(snapshot_ids)
    if (
        len(snapshot_ids) < 2
        or len(set(snapshot_ids)) != len(snapshot_ids)
        or any(isinstance(value, bool) or not isinstance(value, int) or value < 1
               for value in snapshot_ids)
        or isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 0
    ):
        raise ValueError("Нужны уникальные snapshot IDs и неотрицательный cycle")
    legacy_snapshot_id = snapshot_ids[0]
    errors = []
    legacy_path = (
        data_root / "checkpoints" / life_id / f"{life_id}_cycle_{cycle}.json"
    )
    legacy = {
        "path": legacy_path.relative_to(data_root).as_posix(),
        "bytes": None,
        "sha256": None,
        "state_sha256": None,
        "saved_at": None,
        "expected_snapshot_id": legacy_snapshot_id,
        "errors": [],
    }
    try:
        if not legacy_path.is_file() or legacy_path.is_symlink():
            raise ValueError("legacy-файл отсутствует или является ссылкой")
        pattern = re.compile(re.escape(life_id) + r"_cycle_([0-9]+)[.]json")
        same_cycle_files = [
            path.name for path in legacy_path.parent.iterdir()
            if pattern.fullmatch(path.name)
            and int(pattern.fullmatch(path.name).group(1)) == cycle
        ]
        if sorted(same_cycle_files) != [legacy_path.name]:
            raise ValueError(f"Неожиданный набор legacy-файлов цикла: {same_cycle_files}")
        legacy["bytes"] = legacy_path.stat().st_size
        legacy["sha256"] = _file_hash(legacy_path)
        state = CheckpointSerializer().load(str(legacy_path))
        if state is None:
            raise ValueError("пустой legacy-файл")
        validate_checkpoint_state(state)
        if state.get("life_id") not in (None, life_id):
            raise ValueError("legacy life_id не совпадает")
        if state.get("cycle_count") != cycle:
            raise ValueError("legacy cycle_count не совпадает")
        legacy["state"] = state
        legacy["state_sha256"] = _state_hash(state)
        legacy["saved_at"] = state.get("saved_at")
    except Exception as exc:
        legacy["errors"].append(str(exc))
        errors.append(f"legacy: {exc}")

    migration_id = None
    migration_roots = None
    database_path = data_root / "lives" / life_id / "life.sqlite3"
    try:
        migration_id, migration_roots = _active_migration_roots(database_path)
    except Exception as exc:
        errors.append(f"migration run: {exc}")

    database = {
        "path": str(database_path),
        "opened_read_only": False,
        "query_only": None,
        "wal_bytes": None,
        "integrity_check": [],
        "foreign_key_violations": [],
        "storage_schema_version": None,
        "latest_snapshot_id": None,
    }
    snapshots = []
    try:
        connection, wal_bytes = _connect_read_only(database_path)
        database["wal_bytes"] = wal_bytes
        with closing(connection) as owned:
            database["opened_read_only"] = True
            database["query_only"] = owned.execute("PRAGMA query_only").fetchone()[0]
            database["integrity_check"] = [
                row[0] for row in owned.execute("PRAGMA integrity_check")
            ]
            database["foreign_key_violations"] = [
                list(row) for row in owned.execute("PRAGMA foreign_key_check")
            ]
            if database["integrity_check"] != ["ok"]:
                errors.append("SQLite integrity_check не пройден")
            if database["foreign_key_violations"]:
                errors.append("SQLite foreign_key_check содержит нарушения")
            meta = _read_meta(owned)
            database["storage_schema_version"] = meta.get("storage_schema_version")
            latest_row = owned.execute("SELECT MAX(id) FROM snapshots").fetchone()[0]
            database["latest_snapshot_id"] = latest_row
            if latest_row != snapshot_ids[-1] or meta.get("latest_snapshot_id") != latest_row:
                errors.append(
                    f"latest snapshot не совпадает с последним ожидаемым ID {snapshot_ids[-1]}"
                )

            rows = owned.execute(
                "SELECT id, agent_name, cycle, saved_at, manifest FROM snapshots "
                "WHERE cycle=? ORDER BY id", (cycle,)
            ).fetchall()
            actual_ids = [int(row["id"]) for row in rows]
            if actual_ids != list(snapshot_ids):
                errors.append(
                    f"Snapshots цикла {cycle}: ожидались {list(snapshot_ids)}, "
                    f"фактически {actual_ids}"
                )
            decoder = SQLiteCheckpointStore.__new__(SQLiteCheckpointStore)
            decoder.path = database_path
            for row in rows:
                snapshot_id = int(row["id"])
                record = {
                    "snapshot_id": snapshot_id,
                    "role": (
                        "legacy_source" if snapshot_id == legacy_snapshot_id
                        else "sql_only_additional_in_first_batch"
                    ),
                    "cycle": int(row["cycle"]),
                    "saved_at": row["saved_at"],
                    "snapshot_root_sha256": None,
                    "migration_root_sha256": (
                        migration_roots.get(str(snapshot_id))
                        if migration_roots is not None else None
                    ),
                    "sqlite_state_sha256": None,
                    "verified": False,
                    "errors": [],
                }

                def fail(message):
                    record["errors"].append(message)
                    errors.append(f"snapshot={snapshot_id}: {message}")

                try:
                    if row["agent_name"] != life_id:
                        raise ValueError("agent_name не совпадает с UUID")
                    root = decoder._manifest_root(row["manifest"])
                    record["snapshot_root_sha256"] = root
                    state = migrate_state(decoder._decode(
                        owned, root, set(), expected="dict"
                    ))
                    validate_checkpoint_state(state)
                    if state.get("life_id") not in (None, life_id):
                        raise ValueError("state life_id не совпадает")
                    if state.get("cycle_count") != cycle:
                        raise ValueError("state cycle_count не совпадает")
                    if state.get("saved_at") != row["saved_at"]:
                        raise ValueError("state.saved_at не совпадает с metadata")
                    record["state"] = state
                    record["sqlite_state_sha256"] = _state_hash(state)
                except Exception as exc:
                    fail(str(exc))

                if snapshot_id == legacy_snapshot_id:
                    if "state" not in legacy or record.get("state") != legacy["state"]:
                        fail("полное состояние не совпадает с legacy")
                    if record["sqlite_state_sha256"] != legacy["state_sha256"]:
                        fail("канонический SHA-256 не совпадает с legacy")
                    if row["saved_at"] != legacy["saved_at"]:
                        fail("saved_at не совпадает с legacy")
                    if (
                        migration_roots is not None
                        and record["migration_root_sha256"] is None
                    ):
                        fail("исходный snapshot отсутствует в migration run")
                else:
                    if record.get("state") == legacy.get("state"):
                        fail("дополнительный snapshot не отличается от legacy")
                    if (
                        migration_roots is not None
                        and str(snapshot_id) in migration_roots
                    ):
                        fail("дополнительный snapshot неожиданно присутствует в migration run")
                if (
                    migration_roots is not None
                    and record["migration_root_sha256"] is not None
                    and record["snapshot_root_sha256"] != record["migration_root_sha256"]
                ):
                    fail("корневой хеш не совпадает с migration run")
                record["verified"] = not record["errors"]
                snapshots.append(record)
    except Exception as exc:
        errors.append(f"SQLite: {exc}")

    roots = [item["snapshot_root_sha256"] for item in snapshots]
    state_hashes = [item["sqlite_state_sha256"] for item in snapshots]
    if len(set(roots)) != len(roots) or None in roots:
        errors.append("Корневые хеши snapshots не уникальны или отсутствуют")
    if len(set(state_hashes)) != len(state_hashes) or None in state_hashes:
        errors.append("SHA-256 состояний snapshots не уникальны или отсутствуют")
    try:
        timestamps = [
            datetime.fromisoformat(item["saved_at"]) for item in snapshots
        ]
        if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
            errors.append("saved_at snapshots не образуют строго возрастающую последовательность")
    except Exception as exc:
        errors.append(f"Не удалось проверить хронологию saved_at: {exc}")

    transitions = []
    for left, right in zip(snapshots, snapshots[1:]):
        transitions.append({
            "from_snapshot_id": left["snapshot_id"],
            "to_snapshot_id": right["snapshot_id"],
            "changed_top_level_keys": _changed_top_level(
                left.get("state"), right.get("state")
            ),
        })
    for item in snapshots:
        item.pop("state", None)
    legacy.pop("state", None)

    return {
        "manifest_schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "life_id": life_id,
        "cycle": cycle,
        "migration_run_id": migration_id,
        "legacy": legacy,
        "database": database,
        "expected_snapshot_ids": list(snapshot_ids),
        "snapshots": snapshots,
        "state_transitions": transitions,
        "consolidation": {
            "legacy_snapshot_id": legacy_snapshot_id,
            "sql_only_additional_snapshot_ids": list(snapshot_ids[1:]),
            "one_to_many_verified": not errors,
            "sql_only_scope": (
                "Нет отдельного legacy JSON в первом checkpoint batch; "
                "это не утверждение об отсутствии явных exports."
            ),
        },
        "ok": not errors,
        "errors": errors,
        "deletion_authorized": False,
        "note": (
            "One-to-many сверка объясняет только cycle 10553 и не снимает "
            "остальные gates этапа 6; удаление требует отдельного разрешения."
        ),
    }


def _snapshot_ids(value):
    try:
        result = tuple(int(item) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Ожидаются ID через запятую") from exc
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only consolidated manifest для cycle 10553"
    )
    parser.add_argument("--data-root", type=Path, default=ROOT / "data")
    parser.add_argument("--life-id")
    parser.add_argument("--cycle", type=int, default=10553)
    parser.add_argument("--snapshot-ids", type=_snapshot_ids, default=(20, 21, 22))
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "tmp" / "stage6_cycle_10553_consolidated_manifest.json",
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

    before = _inventory(data_root)
    report = verify_cycle_consolidation(
        data_root, life_id, cycle=args.cycle, snapshot_ids=args.snapshot_ids
    )
    after = _inventory(data_root)
    changed = [
        path for path in sorted(set(before["files"]) | set(after["files"]))
        if before["files"].get(path) != after["files"].get(path)
    ]
    comparison_ok = report["ok"]
    report["source_data"] = {
        "before": {key: value for key, value in before.items() if key != "files"},
        "after": {key: value for key, value in after.items() if key != "files"},
        "unchanged": before == after,
        "changed_paths": changed,
    }
    report["ok"] = comparison_ok and not changed
    report["autonomous_ticks"] = 0
    report["deleted_paths"] = []
    _write_manifest(output, report)
    print(json.dumps({
        "ok": report["ok"],
        "comparison_ok": comparison_ok,
        "manifest": str(output),
        "cycle": report["cycle"],
        "consolidation": report["consolidation"],
        "source_data_unchanged": report["source_data"]["unchanged"],
        "deletion_authorized": False,
        "errors": report["errors"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
