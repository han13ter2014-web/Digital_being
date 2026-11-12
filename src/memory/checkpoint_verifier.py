"""Read-only сверка legacy JSON-чекпоинтов со снимками SQLite.

Модуль не создаёт ``LifeDatabase``/``SQLiteCheckpointStore``: их конструкторы
могут изменить схему. При пустом WAL используются URI ``mode=ro&immutable=1``,
``query_only`` и read-only decoder content-addressed формата. Непустой WAL
блокирует проверку: immutable-чтение не должно игнорировать транзакции.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from src.core.checkpoint_migrations import migrate_state
from src.core.checkpoint_serializer import CheckpointSerializer
from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.life_identity import validate_life_id
from src.memory.checkpoint_store import SQLiteCheckpointStore


def _canonical(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _state_hash(state) -> str:
    return hashlib.sha256(_canonical(state).encode("utf-8")).hexdigest()


def _differences(legacy, restored, path="$", limit=20) -> list[str]:
    """Короткая диагностика без копирования полного состояния в манифест."""
    if limit <= 0:
        return []
    if type(legacy) is not type(restored):
        return [f"{path}: тип {type(legacy).__name__} != {type(restored).__name__}"]
    if isinstance(legacy, dict):
        result = []
        for key in sorted(set(legacy) | set(restored)):
            if key not in legacy:
                result.append(f"{path}.{key}: отсутствует в legacy")
            elif key not in restored:
                result.append(f"{path}.{key}: отсутствует в SQLite")
            else:
                result.extend(_differences(
                    legacy[key], restored[key], f"{path}.{key}", limit - len(result)
                ))
            if len(result) >= limit:
                return result[:limit]
        return result
    if isinstance(legacy, list):
        result = []
        if len(legacy) != len(restored):
            result.append(f"{path}: длина {len(legacy)} != {len(restored)}")
        for index, (left, right) in enumerate(zip(legacy, restored)):
            result.extend(_differences(
                left, right, f"{path}[{index}]", limit - len(result)
            ))
            if len(result) >= limit:
                break
        return result[:limit]
    return [] if legacy == restored else [f"{path}: {legacy!r} != {restored!r}"]


def _read_meta(connection) -> dict:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if exists is None:
        return {}
    result = {}
    for key in ("life_id", "storage_schema_version", "latest_snapshot_id"):
        row = connection.execute(
            "SELECT value_json FROM meta WHERE key=?", (key,)
        ).fetchone()
        if row is not None:
            result[key] = json.loads(row[0])
    return result


def verify_checkpoint_batch(data_root, life_id: str, *, expected_count=None) -> dict:
    """Сверить строго один каталог UUID, ничего в нём не изменяя.

    ``ok`` означает только успешную поснимочную сверку. Поле
    ``deletion_authorized`` всегда ложно: остальные gates и отдельное разрешение
    владельца этот инструмент не заменяет.
    """
    data_root = Path(data_root).resolve()
    life_id = validate_life_id(life_id)
    if expected_count is not None:
        if isinstance(expected_count, bool) or not isinstance(expected_count, int):
            raise TypeError("expected_count должен быть целым")
        if expected_count < 0:
            raise ValueError("expected_count не может быть отрицательным")

    checkpoint_dir = data_root / "checkpoints" / life_id
    database_path = data_root / "lives" / life_id / "life.sqlite3"
    pattern = re.compile(re.escape(life_id) + r"_cycle_([0-9]+)[.]json")
    errors: list[str] = []
    unexpected: list[str] = []
    files: dict[int, dict] = {}

    if not checkpoint_dir.is_dir():
        errors.append(f"Каталог чекпоинтов не найден: {checkpoint_dir}")
    else:
        for path in sorted(checkpoint_dir.iterdir()):
            relative = path.relative_to(data_root).as_posix()
            match = pattern.fullmatch(path.name)
            if path.is_symlink() or not path.is_file() or match is None:
                unexpected.append(relative)
                errors.append(f"Неожиданный элемент в первом batch: {relative}")
                continue
            cycle = int(match.group(1))
            record = {
                "path": path,
                "relative_path": relative,
                "bytes": path.stat().st_size,
                "sha256": _file_hash(path),
                "errors": [],
            }
            try:
                state = CheckpointSerializer().load(str(path))
                if state is None:
                    raise ValueError("пустой чекпоинт")
                validate_checkpoint_state(state)
                if state.get("life_id") not in (None, life_id):
                    raise ValueError("life_id не совпадает с активным UUID")
                state_cycle = state.get("cycle_count")
                if (
                    isinstance(state_cycle, bool)
                    or not isinstance(state_cycle, int)
                    or state_cycle != cycle
                ):
                    raise ValueError(
                        f"cycle_count={state_cycle!r}, имя файла содержит cycle={cycle}"
                    )
                record["state"] = state
                record["saved_at"] = state.get("saved_at") or datetime.fromtimestamp(
                    path.stat().st_mtime, timezone.utc
                ).isoformat()
                record["state_sha256"] = _state_hash(state)
            except Exception as exc:
                record["errors"].append(f"legacy: {exc}")
            if cycle in files:
                errors.append(f"Повторяющийся legacy cycle={cycle}")
                unexpected.append(relative)
            else:
                files[cycle] = record

    database = {
        "path": str(database_path),
        "opened_read_only": False,
        "query_only": None,
        "user_version": None,
        "integrity_check": [],
        "foreign_key_violations": [],
        "snapshot_count": 0,
        "latest_snapshot_id": None,
        "meta": {},
        "verified_migration_run": None,
        "wal_bytes": None,
        "duplicate_snapshots": [],
    }
    rows: dict[int, dict] = {}
    snapshot_hashes: dict[str, str] = {}
    if not database_path.is_file():
        errors.append(f"База жизни не найдена: {database_path}")
    else:
        try:
            wal_path = Path(str(database_path) + "-wal")
            database["wal_bytes"] = wal_path.stat().st_size if wal_path.exists() else 0
            if database["wal_bytes"]:
                raise ValueError(
                    "WAL непуст: immutable-чтение могло бы игнорировать транзакции; "
                    "нужен остановленный writer и новый проверенный backup"
                )
            uri = database_path.as_uri() + "?mode=ro&immutable=1"
            with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA busy_timeout=30000")
                connection.execute("PRAGMA query_only=ON")
                database["opened_read_only"] = True
                database["query_only"] = connection.execute(
                    "PRAGMA query_only"
                ).fetchone()[0]
                database["user_version"] = connection.execute(
                    "PRAGMA user_version"
                ).fetchone()[0]
                database["integrity_check"] = [
                    row[0] for row in connection.execute("PRAGMA integrity_check")
                ]
                database["foreign_key_violations"] = [
                    list(row) for row in connection.execute("PRAGMA foreign_key_check")
                ]
                if database["integrity_check"] != ["ok"]:
                    errors.append("SQLite integrity_check не пройден")
                if database["foreign_key_violations"]:
                    errors.append("SQLite foreign_key_check содержит нарушения")

                decoder = SQLiteCheckpointStore.__new__(SQLiteCheckpointStore)
                decoder.path = database_path
                snapshot_rows = connection.execute(
                    "SELECT id, agent_name, cycle, saved_at, manifest "
                    "FROM snapshots ORDER BY id"
                ).fetchall()
                database["snapshot_count"] = len(snapshot_rows)
                database["latest_snapshot_id"] = (
                    int(snapshot_rows[-1]["id"]) if snapshot_rows else None
                )
                owners = sorted({row["agent_name"] for row in snapshot_rows})
                if owners != [life_id]:
                    errors.append(f"Владельцы snapshots не совпадают с UUID: {owners}")
                for row in snapshot_rows:
                    cycle = int(row["cycle"])
                    record = {
                        "snapshot_id": int(row["id"]),
                        "agent_name": row["agent_name"],
                        "saved_at": row["saved_at"],
                        "errors": [],
                    }
                    try:
                        root = decoder._manifest_root(row["manifest"])
                        record["root_sha256"] = root
                        snapshot_hashes[str(row["id"])] = root
                        state = migrate_state(decoder._decode(
                            connection, root, set(), expected="dict"
                        ))
                        validate_checkpoint_state(state)
                        record["state"] = state
                        record["state_sha256"] = _state_hash(state)
                    except Exception as exc:
                        record["errors"].append(f"SQLite: {exc}")
                    if cycle in rows:
                        errors.append(f"Повторяющийся SQLite cycle={cycle}")
                        database["duplicate_snapshots"].append({
                            "cycle": cycle,
                            "snapshot_id": record["snapshot_id"],
                            "saved_at": record["saved_at"],
                            "snapshot_root_sha256": record.get("root_sha256"),
                            "sqlite_state_sha256": record.get("state_sha256"),
                            "errors": record["errors"],
                        })
                    else:
                        rows[cycle] = record

                database["meta"] = _read_meta(connection)
                meta = database["meta"]
                if meta.get("life_id") not in (None, life_id):
                    errors.append("meta.life_id не совпадает с активным UUID")
                latest = meta.get("latest_snapshot_id")
                if latest is not None and latest != database["latest_snapshot_id"]:
                    errors.append(
                        f"meta.latest_snapshot_id={latest}, "
                        f"фактический={database['latest_snapshot_id']}"
                    )
                migration_table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='migration_runs'"
                ).fetchone()
                if migration_table is not None:
                    migration = connection.execute(
                        "SELECT id, status, hashes_json FROM migration_runs "
                        "WHERE status='verified' ORDER BY finished_at DESC, id DESC LIMIT 1"
                    ).fetchone()
                    if migration is not None:
                        recorded = json.loads(migration["hashes_json"])
                        common = set(recorded) & set(snapshot_hashes)
                        database["verified_migration_run"] = {
                            "id": migration["id"],
                            "status": migration["status"],
                            "snapshot_hashes_match": recorded == snapshot_hashes,
                            "matching_snapshot_ids": sorted(
                                int(key) for key in common
                                if recorded[key] == snapshot_hashes[key]
                            ),
                            "changed_snapshot_ids": sorted(
                                int(key) for key in common
                                if recorded[key] != snapshot_hashes[key]
                            ),
                            "missing_snapshot_ids": sorted(
                                int(key) for key in set(recorded) - set(snapshot_hashes)
                            ),
                            "additional_snapshot_ids": sorted(
                                int(key) for key in set(snapshot_hashes) - set(recorded)
                            ),
                        }
                        if recorded != snapshot_hashes:
                            errors.append(
                                "Корневые хеши не совпадают с последним verified migration run"
                            )
        except Exception as exc:
            errors.append(f"Не удалось проверить SQLite read-only: {exc}")

    entries = []
    for cycle in sorted(set(files) | set(rows)):
        legacy = files.get(cycle)
        restored = rows.get(cycle)
        entry = {
            "cycle": cycle,
            "legacy_path": legacy["relative_path"] if legacy else None,
            "legacy_bytes": legacy["bytes"] if legacy else None,
            "legacy_sha256": legacy["sha256"] if legacy else None,
            "legacy_state_sha256": legacy.get("state_sha256") if legacy else None,
            "snapshot_id": restored["snapshot_id"] if restored else None,
            "snapshot_root_sha256": restored.get("root_sha256") if restored else None,
            "sqlite_state_sha256": restored.get("state_sha256") if restored else None,
            "legacy_saved_at": legacy.get("saved_at") if legacy else None,
            "sqlite_saved_at": restored["saved_at"] if restored else None,
            "matched": False,
            "errors": [],
            "differences": [],
        }
        if legacy is None:
            entry["errors"].append("legacy-файл отсутствует")
        if restored is None:
            entry["errors"].append("SQLite snapshot отсутствует")
        if legacy is not None:
            entry["errors"].extend(legacy["errors"])
        if restored is not None:
            entry["errors"].extend(restored["errors"])
        if (
            legacy is not None
            and restored is not None
            and "state" in legacy
            and "state" in restored
        ):
            if legacy["state"] != restored["state"]:
                entry["errors"].append("полное состояние не совпадает")
                entry["differences"] = _differences(
                    legacy["state"], restored["state"]
                )
            if legacy["state_sha256"] != restored["state_sha256"]:
                entry["errors"].append("канонический SHA-256 состояния не совпадает")
            if legacy["saved_at"] != restored["saved_at"]:
                entry["errors"].append("saved_at не совпадает")
        entry["matched"] = not entry["errors"]
        for error in entry["errors"]:
            errors.append(f"cycle={cycle}: {error}")
        entries.append(entry)

    if expected_count is not None and len(files) != expected_count:
        errors.append(f"Ожидалось {expected_count} legacy-файлов, найдено {len(files)}")
    if expected_count is not None and database["snapshot_count"] != expected_count:
        errors.append(
            f"Ожидалось {expected_count} snapshots, найдено {database['snapshot_count']}"
        )
    if len(files) != database["snapshot_count"]:
        errors.append(
            f"Число legacy-файлов ({len(files)}) и snapshots "
            f"({database['snapshot_count']}) не совпадает"
        )

    return {
        "manifest_schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "life_id": life_id,
        "checkpoint_directory": str(checkpoint_dir),
        "expected_count": expected_count,
        "legacy_count": len(files),
        "unexpected_entries": unexpected,
        "database": database,
        "entries": entries,
        "ok": not errors,
        "errors": errors,
        "deletion_authorized": False,
        "candidate_only": True,
        "note": (
            "Даже ok=true не разрешает удаление: требуются остальные gates этапа 6 "
            "и отдельное разрешение владельца на точный манифест."
        ),
    }


__all__ = ["verify_checkpoint_batch"]
