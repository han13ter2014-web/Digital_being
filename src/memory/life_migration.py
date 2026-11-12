"""Не destructive-миграция существующих хранилищ в базу одной жизни.

Функция создаёт только новый файл в ``destination_root``. Источники открываются
read-only либо читаются как файлы; неоднозначные строки Delamain не угадываются.
"""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from src.core.checkpoint_migrations import migrate_state
from src.core.checkpoint_serializer import CheckpointSerializer
from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.life_guard import LifeRequest, VALID_STATES
from src.core.life_identity import validate_life_id
from src.memory.checkpoint_store import SQLiteCheckpointStore
from src.memory.life_database import LifeDatabase
from src.memory.long_term_memory import MemoryTrace


DELAMAIN_TABLES = {
    "episodes": "episodes",
    "facts": "facts",
    "self_model": "self_model",
    "goals": "execution_goals",
    "skills": "skills",
    "approvals": "approvals",
}


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False, default=str,
    )


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_object(value):
    try:
        result = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return result if isinstance(result, dict) else {}


def _read_only(path):
    connection = sqlite3.connect(
        Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=30
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    return connection


def _snapshot_sort_key(record):
    return record["cycle"], record["source_order"]


def _read_snapshots(source_root, life_id):
    folder = Path(source_root) / "checkpoints" / life_id
    records = []
    sources = []
    serializer = CheckpointSerializer()
    pattern = re.compile(r".+_cycle_([0-9]+)[.]json(?:[.]gz)?$")
    paths = sorted(
        (path for path in folder.glob("*") if pattern.fullmatch(path.name)),
        key=lambda path: int(pattern.fullmatch(path.name).group(1)),
    ) if folder.is_dir() else []
    for path in paths:
        state = serializer.load(str(path))
        if state is None:
            raise ValueError(f"Пустой исходный снимок: {path}")
        match = pattern.fullmatch(path.name)
        records.append({
            "state": state,
            "cycle": int(match.group(1)),
            "saved_at": state.get("saved_at") or datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).isoformat(),
            "source": str(path),
            "source_order": len(records),
        })
        sources.append(path)

    database_path = folder / "life.sqlite3"
    if database_path.is_file():
        # Не создаём SQLiteCheckpointStore на источнике: его конструктор мог бы
        # инициализировать схему. Здесь используются только read-only decode.
        decoder = SQLiteCheckpointStore.__new__(SQLiteCheckpointStore)
        decoder.path = database_path
        with closing(_read_only(database_path)) as connection:
            rows = connection.execute(
                "SELECT id, cycle, saved_at, manifest FROM snapshots "
                "WHERE agent_name = ? ORDER BY id", (life_id,)
            ).fetchall()
            for row in rows:
                root = decoder._manifest_root(row["manifest"])
                state = migrate_state(decoder._decode(
                    connection, root, set(), expected="dict"
                ))
                records.append({
                    "state": state,
                    "cycle": int(row["cycle"]),
                    "saved_at": row["saved_at"],
                    "source": f"{database_path}#snapshot={row['id']}",
                    "source_order": len(records),
                })
        sources.append(database_path)

    records.sort(key=_snapshot_sort_key)
    if not records:
        raise ValueError("Для выбранной жизни не найдены снимки")
    names = set()
    intentions = set()
    for record in records:
        state = record["state"]
        if state.get("life_id") not in (None, life_id):
            raise ValueError(f"Снимок другой жизни: {record['source']}")
        validate_checkpoint_state(state)
        if isinstance(state.get("name"), str) and state["name"].strip():
            names.add(state["name"])
        for entry in state.get("intention_history") or []:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                intentions.add(entry["id"])
    return records, sources, names, intentions


def _read_memory(source_root, life_id, quarantine):
    path = Path(source_root) / "memory" / f"{life_id}_long_term.json"
    if not path.is_file():
        return [], [], {}, []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("LongTermMemory: ожидался JSON-объект")
    traces = {}

    for store, section in (("short_term", "short_term"), ("long_term", "long_term")):
        values = data.get(section, {})
        if not isinstance(values, dict):
            raise ValueError(f"LongTermMemory.{section}: ожидался объект")
        for trace_id, raw in values.items():
            trace = MemoryTrace.from_dict(raw)
            key = str(trace_id)
            if not key or key in traces:
                raise ValueError(f"LongTermMemory: повторяющийся ID {key!r}")
            traces[key] = {"trace": trace, "store": store, "episode_order": None}

    episodic = data.get("episodic", [])
    if not isinstance(episodic, list):
        raise ValueError("LongTermMemory.episodic: ожидался список")
    for order, raw in enumerate(episodic):
        trace = MemoryTrace.from_dict(raw)
        candidates = [
            key for key, item in traces.items()
            if item["trace"].to_dict() == trace.to_dict()
        ]
        if len(candidates) > 1:
            raise ValueError("Неоднозначная связь эпизода со следом памяти")
        if candidates:
            key = candidates[0]
        else:
            # Эпизод может пережить удаление из short-term: он остаётся
            # самостоятельным следом, а не выдумывается как consolidated.
            key = f"episodic_{order}_{hashlib.sha256(_canonical(raw).encode()).hexdigest()[:16]}"
            traces[key] = {"trace": trace, "store": "episodic", "episode_order": None}
        if traces[key]["episode_order"] is not None:
            raise ValueError(f"Повторный эпизодический след: {key}")
        traces[key]["episode_order"] = order

    rows = []
    for trace_id, item in traces.items():
        trace = item["trace"]
        rows.append({
            "id": trace_id,
            "store": item["store"],
            "content": trace.content,
            "importance": trace.importance,
            "created_at": trace.created_at.isoformat(),
            "last_accessed": trace.last_accessed.isoformat(),
            "access_count": trace.access_count,
            "context": trace.context,
            "is_episodic": int(item["episode_order"] is not None),
            "episode_order": item["episode_order"],
            "metadata_json": "{}",
        })
    links = []
    for trace_id, item in traces.items():
        for related in sorted(item["trace"].associations):
            if related == trace_id:
                quarantine.append({"store": "memory_links", "id": trace_id,
                                   "reason": "self_link"})
            elif related not in traces:
                quarantine.append({"store": "memory_links", "id": trace_id,
                                   "reason": f"missing_target:{related}"})
            else:
                links.append({"trace_id": trace_id, "related_trace_id": related})
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("LongTermMemory.metadata: ожидался объект")
    return rows, links, metadata, [path]


def _row_identity(table, row):
    for key in ("id", "key", "name"):
        if key in row:
            return str(row[key])
    return None


def _read_delamain(source_root, life_id, intention_ids, quarantine):
    path = Path(source_root) / "delamain" / "delamain.sqlite3"
    result = {target: [] for target in DELAMAIN_TABLES.values()}
    sources = []
    skipped_other = 0
    if not path.is_file():
        return result, sources, skipped_other
    sources.append(path)
    with closing(_read_only(path)) as connection:
        existing = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for source_table, target_table in DELAMAIN_TABLES.items():
            if source_table not in existing:
                continue
            rows = [dict(row) for row in connection.execute(
                f"SELECT * FROM {source_table} ORDER BY rowid"
            )]
            for row in rows:
                metadata = _json_object(row.get("meta_json"))
                if source_table == "self_model":
                    metadata = _json_object(row.get("value_json"))
                owner = metadata.get("life_id")
                try:
                    valid_owner = validate_life_id(owner) if owner is not None else None
                except (ValueError, TypeError):
                    valid_owner = None
                if valid_owner == life_id:
                    result[target_table].append(row)
                    continue
                if valid_owner is not None:
                    skipped_other += 1
                    continue
                legacy_episode = (
                    source_table == "episodes" and row.get("task_id") in intention_ids
                )
                biography_marker = (
                    source_table == "self_model"
                    and row.get("key") == f"biography.process_run:{life_id}"
                )
                if legacy_episode or biography_marker:
                    result[target_table].append(row)
                else:
                    quarantine.append({
                        "store": f"delamain.{source_table}",
                        "id": _row_identity(source_table, row),
                        "reason": "life_id_missing_or_ambiguous",
                    })
    return result, sources, skipped_other


def _read_life_guard(source_root, agent_names, quarantine):
    root = Path(source_root)
    status = None
    requests = []
    events = []
    sources = []
    state_path = root / "life_state.json"
    if state_path.is_file():
        sources.append(state_path)
        data = json.loads(state_path.read_text(encoding="utf-8"))
        if data.get("agent_name") in agent_names and data.get("state") in VALID_STATES:
            status = {
                "id": 1,
                "state": data["state"],
                "display_name": data["agent_name"],
                "reason": str(data.get("reason") or ""),
                "changed_at": str(data.get("changed_at") or ""),
                "seed_folder": data.get("seed_folder"),
            }
        else:
            quarantine.append({"store": "life_state", "id": None,
                               "reason": "agent_mismatch_or_invalid_state"})
    requests_path = root / "life_requests.json"
    if requests_path.is_file():
        sources.append(requests_path)
        data = json.loads(requests_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("life_requests: ожидался объект")
        for request_id, raw in data.items():
            request = LifeRequest.from_dict(raw)
            if request.request_id != str(request_id):
                raise ValueError("life_requests: ключ и request_id различаются")
            if request.agent_name not in agent_names:
                quarantine.append({"store": "life_requests", "id": request_id,
                                   "reason": "unknown_agent"})
                continue
            requests.append({
                "request_id": request.request_id,
                "kind": request.kind,
                "agent_name": request.agent_name,
                "reason": request.reason,
                "created_at": request.created_at,
                "expires_at": request.expires_at,
                "confirmed": int(request.confirmed),
                "confirmed_at": request.confirmed_at,
            })
    events_path = root / "life_events.log"
    if events_path.is_file():
        sources.append(events_path)
        for line_number, line in enumerate(
            events_path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError(f"life_events:{line_number}: ожидался объект")
            if data.get("agent") not in agent_names:
                quarantine.append({"store": "life_events", "id": line_number,
                                   "reason": "unknown_agent"})
                continue
            events.append({
                "ts": str(data.get("ts") or ""),
                "event": str(data.get("event") or ""),
                "payload_json": _canonical(data),
            })
    return status, requests, events, sources


def _read_metrics(source_root, life_id, agent_names):
    root = Path(source_root) / "metrics"
    rows = []
    sources = []
    if not root.is_dir():
        return rows, sources
    prefixes = tuple(f"{name}_" for name in agent_names) + (f"{life_id}_",)
    for path in sorted(root.iterdir()):
        if path.suffix not in (".ndjson", ".jsonl") or not path.name.startswith(prefixes):
            continue
        sources.append(path)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            data = json.loads(line)
            if not isinstance(data, dict) or "channel" not in data or "value" not in data:
                raise ValueError(f"metrics:{path.name}:{line_number}: неверная точка")
            cycle = data.get("cycle")
            if cycle is not None and (isinstance(cycle, bool) or not isinstance(cycle, int)):
                raise ValueError(f"metrics:{path.name}:{line_number}: неверный cycle")
            rows.append({
                "ts": str(data.get("ts") or ""),
                "cycle": cycle,
                "name": str(data["channel"]),
                "value_json": _canonical(data["value"]),
                "metadata_json": _canonical({
                    key: value for key, value in data.items()
                    if key not in {"ts", "cycle", "channel", "value"}
                }),
            })
    return rows, sources


def _insert(connection, table, row):
    columns = list(row)
    placeholders = ",".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        tuple(row[column] for column in columns),
    )


def _table_rows(connection, table):
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]


def _hashes(paths, source_root):
    root = Path(source_root).resolve()
    result = {}
    for path in sorted(set(Path(item).resolve() for item in paths)):
        try:
            key = str(path.relative_to(root))
        except ValueError:
            key = str(path)
        result[key] = _file_hash(path)
    return result


def migrate_life_to_sqlite(source_root, life_id, destination_root):
    """Создать и проверить новую базу жизни, не изменяя исходные данные."""
    life_id = validate_life_id(life_id)
    source_root = Path(source_root).resolve()
    destination_root = Path(destination_root).resolve()
    database_path = destination_root / "lives" / life_id / "life.sqlite3"
    if database_path.exists():
        raise FileExistsError(f"Целевая база уже существует: {database_path}")

    quarantine = []
    snapshots, sources, agent_names, intention_ids = _read_snapshots(source_root, life_id)
    memory, memory_links, memory_meta, paths = _read_memory(source_root, life_id, quarantine)
    sources.extend(paths)
    delamain, paths, skipped_other = _read_delamain(
        source_root, life_id, intention_ids, quarantine
    )
    sources.extend(paths)
    life_status, life_requests, life_events, paths = _read_life_guard(
        source_root, agent_names, quarantine
    )
    sources.extend(paths)
    metrics, paths = _read_metrics(source_root, life_id, agent_names)
    sources.extend(paths)
    hashes_before = _hashes(sources, source_root)

    database = LifeDatabase(database_path, life_id)
    migration_id = uuid4().hex
    source_manifest = {
        "source_root": str(source_root),
        "files": hashes_before,
        "snapshot_sources": [record["source"] for record in snapshots],
    }
    with database.write() as connection:
        connection.execute(
            "INSERT INTO migration_runs(id, started_at, source_manifest_json, status) "
            "VALUES (?, ?, ?, 'running')",
            (migration_id, datetime.now(timezone.utc).isoformat(), _canonical(source_manifest)),
        )

    try:
        snapshot_ids = []
        for record in snapshots:
            snapshot_id = database.checkpoints.save(
                record["state"], life_id, record["cycle"],
                max_checkpoints=1000000, saved_at=record["saved_at"],
            )
            snapshot_ids.append(snapshot_id)
        database.set_meta("latest_snapshot_id", snapshot_ids[-1])

        with database.write() as connection:
            for row in memory:
                _insert(connection, "memory_traces", row)
            for row in memory_links:
                _insert(connection, "memory_links", row)
            for table, rows in delamain.items():
                for row in rows:
                    _insert(connection, table, row)
            if delamain["facts"]:
                try:
                    connection.execute(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(key, value)"
                    )
                except sqlite3.OperationalError:
                    pass
                else:
                    for row in delamain["facts"]:
                        connection.execute(
                            "INSERT INTO facts_fts(rowid, key, value) VALUES (?, ?, ?)",
                            (row["id"], row["key"], row["value"]),
                        )
            if life_status is not None:
                _insert(connection, "life_status", life_status)
            for row in life_requests:
                _insert(connection, "life_requests", row)
            for row in life_events:
                _insert(connection, "life_events", row)
            for row in metrics:
                _insert(connection, "metric_samples", row)
            for key, value in memory_meta.items():
                if key != "saved_at":
                    database.set_meta(f"long_term_memory.{key}", value, connection)

        snapshot_hashes = {}
        with closing(database.connect(readonly=True)) as connection:
            for record, snapshot_id in zip(snapshots, snapshot_ids):
                restored = database.checkpoints.load(snapshot_id)
                if restored != record["state"]:
                    raise ValueError(f"Snapshot mismatch: {record['source']}")
                row = connection.execute(
                    "SELECT cycle, saved_at, manifest FROM snapshots WHERE id=?",
                    (snapshot_id,),
                ).fetchone()
                if row["cycle"] != record["cycle"] or row["saved_at"] != record["saved_at"]:
                    raise ValueError(f"Snapshot metadata mismatch: {record['source']}")
                snapshot_hashes[str(snapshot_id)] = json.loads(row["manifest"])["root"]
                for table, expected in delamain.items():
                    if _table_rows(connection, table) != expected:
                        raise ValueError(f"Delamain table mismatch: {table}")
                if _table_rows(connection, "memory_traces") != memory:
                    raise ValueError("Memory trace mismatch")
                if _table_rows(connection, "memory_links") != memory_links:
                    raise ValueError("Memory link mismatch")
                if len(_table_rows(connection, "life_requests")) != len(life_requests):
                    raise ValueError("LifeGuard request count mismatch")
                if len(_table_rows(connection, "life_events")) != len(life_events):
                    raise ValueError("LifeGuard event count mismatch")
                if len(_table_rows(connection, "metric_samples")) != len(metrics):
                    raise ValueError("Metric count mismatch")

        verification = database.verify()
        if not verification["ok"]:
            raise ValueError(f"SQLite verification failed: {verification}")
        hashes_after = _hashes(sources, source_root)
        if hashes_after != hashes_before:
            raise RuntimeError("Исходные файлы изменились во время read-only миграции")

        counts = {
            "snapshots": len(snapshot_ids),
            "memory_traces": len(memory),
            "memory_links": len(memory_links),
            "life_requests": len(life_requests),
            "life_events": len(life_events),
            "metric_samples": len(metrics),
            "quarantined": len(quarantine),
            "skipped_other_life": skipped_other,
            **{f"delamain_{table}": len(rows) for table, rows in delamain.items()},
        }
        report = {
            "migration_id": migration_id,
            "life_id": life_id,
            "agent_names": sorted(agent_names),
            "database": str(database_path),
            "latest_snapshot_id": snapshot_ids[-1],
            "counts": counts,
            "quarantine": quarantine,
            "snapshot_hashes": snapshot_hashes,
            "source_files_unchanged": True,
            "verification": verification,
        }
        with database.write() as connection:
            connection.execute(
                "UPDATE migration_runs SET finished_at=?, counts_json=?, hashes_json=?, "
                "status='verified' WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), _canonical(counts),
                 _canonical(snapshot_hashes), migration_id),
            )
        return report
    except BaseException as exc:
        with database.write() as connection:
            connection.execute(
                "UPDATE migration_runs SET finished_at=?, status='failed', error=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), str(exc), migration_id),
            )
        raise


__all__ = ["migrate_life_to_sqlite"]
