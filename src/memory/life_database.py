"""Схема и безопасные соединения базы одной цифровой жизни.

Полные снимки продолжает обслуживать ``SQLiteCheckpointStore``. Этот класс
добавляет остальные таблицы и проверяет, что существующая база принадлежит
именно указанному UUID. Рабочий backend здесь пока не переключается.
"""

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import threading
from uuid import uuid4

from src.core.life_identity import validate_life_id
from src.memory.checkpoint_store import SQLiteCheckpointStore


SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL,
        checksum TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS migration_runs (
        id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        source_manifest_json TEXT NOT NULL,
        counts_json TEXT NOT NULL DEFAULT '{}',
        hashes_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL,
        error TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS memory_traces (
        id TEXT PRIMARY KEY,
        store TEXT NOT NULL CHECK(store IN ('short_term', 'long_term', 'episodic')),
        content TEXT NOT NULL,
        importance REAL NOT NULL,
        created_at TEXT NOT NULL,
        last_accessed TEXT NOT NULL,
        access_count INTEGER NOT NULL,
        context TEXT NOT NULL,
        is_episodic INTEGER NOT NULL CHECK(is_episodic IN (0, 1)),
        episode_order INTEGER,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE INDEX IF NOT EXISTS idx_memory_traces_store
       ON memory_traces(store, last_accessed)""",
    """CREATE INDEX IF NOT EXISTS idx_memory_traces_episodes
       ON memory_traces(is_episodic, episode_order)""",
    """CREATE INDEX IF NOT EXISTS idx_memory_traces_importance
       ON memory_traces(importance, created_at)""",
    """CREATE TABLE IF NOT EXISTS memory_links (
        trace_id TEXT NOT NULL REFERENCES memory_traces(id) ON DELETE CASCADE,
        related_trace_id TEXT NOT NULL REFERENCES memory_traces(id) ON DELETE CASCADE,
        PRIMARY KEY(trace_id, related_trace_id),
        CHECK(trace_id <> related_trace_id)
    )""",
    """CREATE TABLE IF NOT EXISTS episodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        task_id TEXT NOT NULL,
        task TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL,
        args_json TEXT NOT NULL,
        ok INTEGER NOT NULL,
        output_json TEXT,
        error TEXT,
        meta_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE INDEX IF NOT EXISTS idx_episodes_task ON episodes(task_id, id)""",
    """CREATE INDEX IF NOT EXISTS idx_episodes_ts ON episodes(ts)""",
    """CREATE TABLE IF NOT EXISTS facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT '',
        confidence REAL NOT NULL DEFAULT 0.5,
        meta_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_key_value ON facts(key, value)""",
    """CREATE TABLE IF NOT EXISTS self_model (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS execution_goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        success_predicate TEXT NOT NULL DEFAULT '',
        priority REAL NOT NULL DEFAULT 0.5,
        meta_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE INDEX IF NOT EXISTS idx_execution_goals_status
       ON execution_goals(status, priority DESC)""",
    """CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        plan_json TEXT NOT NULL,
        success_count INTEGER NOT NULL DEFAULT 0,
        failure_count INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        decided_at TEXT,
        consumed_at TEXT,
        task_id TEXT NOT NULL,
        goal_id INTEGER,
        title TEXT NOT NULL DEFAULT '',
        task TEXT NOT NULL DEFAULT '',
        plan_json TEXT NOT NULL,
        dangerous_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'pending',
        reason TEXT,
        meta_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, created_at)""",
    """CREATE INDEX IF NOT EXISTS idx_approvals_goal ON approvals(goal_id, status)""",
    """CREATE TABLE IF NOT EXISTS life_status (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        state TEXT NOT NULL CHECK(state IN ('alive', 'dormant', 'terminated')),
        display_name TEXT NOT NULL,
        reason TEXT NOT NULL,
        changed_at TEXT NOT NULL,
        seed_folder TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS life_requests (
        request_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        agent_name TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL,
        confirmed INTEGER NOT NULL CHECK(confirmed IN (0, 1)),
        confirmed_at REAL
    )""",
    """CREATE INDEX IF NOT EXISTS idx_life_requests_pending
       ON life_requests(confirmed, expires_at)""",
    """CREATE TABLE IF NOT EXISTS life_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        event TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS artifacts (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        relative_path TEXT NOT NULL UNIQUE,
        sha256 TEXT NOT NULL,
        bytes INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS metric_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        cycle INTEGER,
        name TEXT NOT NULL,
        value_json TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE INDEX IF NOT EXISTS idx_metric_samples_name
       ON metric_samples(name, cycle, id)""",
    """CREATE TABLE IF NOT EXISTS dialogue_cycles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        cycle INTEGER NOT NULL,
        tick INTEGER NOT NULL,
        agent_name TEXT NOT NULL,
        payload_json TEXT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS idx_dialogue_cycles_cycle
       ON dialogue_cycles(cycle, id)""",
    """CREATE TABLE IF NOT EXISTS architecture_proposals (
        id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        code_snippet TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending', 'approved', 'rejected', 'implemented')),
        created_at TEXT NOT NULL,
        cycle INTEGER NOT NULL DEFAULT 0,
        decided_at TEXT,
        decision_note TEXT,
        payload_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS idx_architecture_proposals_status
       ON architecture_proposals(status, created_at)""",
)

SCHEMA_CHECKSUM = hashlib.sha256(
    "\n".join(SCHEMA_STATEMENTS).encode("utf-8")
).hexdigest()


class LifeDatabase:
    """База ``life.sqlite3``, привязанная к одному неизменяемому ``life_id``."""

    SCHEMA_VERSION = 3
    # Внешние артефакты получают slug-каталог по своему виду.
    _KIND_SLUG_RE = re.compile(r"[^a-z0-9_-]+")

    def __init__(self, path, life_id: str):
        self.path = Path(path)
        self.life_id = validate_life_id(life_id)
        self._write_lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._preflight_identity()
        # Сохраняем проверенный алгоритм content-addressed snapshots.
        self.checkpoints = SQLiteCheckpointStore(
            self.path, schema_version=self.SCHEMA_VERSION
        )
        with self.write() as connection:
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at, checksum) "
                "VALUES (?, datetime('now'), ?)",
                (self.SCHEMA_VERSION, SCHEMA_CHECKSUM),
            )
            row = connection.execute(
                "SELECT value_json FROM meta WHERE key = 'life_id'"
            ).fetchone()
            if row is not None and json.loads(row[0]) != self.life_id:
                raise ValueError("База принадлежит другой жизни")
            for key, value in (
                ("life_id", self.life_id),
                ("storage_kind", "life"),
                ("storage_schema_version", self.SCHEMA_VERSION),
            ):
                connection.execute(
                    "INSERT OR IGNORE INTO meta(key, value_json, updated_at) "
                    "VALUES (?, ?, datetime('now'))",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
            self.set_meta("storage_schema_version", self.SCHEMA_VERSION, connection)
            connection.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")

    def _preflight_identity(self) -> None:
        """Не создавать новые таблицы в базе, уже принадлежащей другой жизни."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        with closing(self.connect(readonly=True)) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
            ).fetchone()
            if table is None:
                snapshots = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='snapshots'"
                ).fetchone()
                if snapshots is not None:
                    owners = {
                        row[0] for row in connection.execute(
                            "SELECT DISTINCT agent_name FROM snapshots"
                        )
                    }
                    if owners and owners != {self.life_id}:
                        raise ValueError("База снимков принадлежит другой жизни")
                return
            row = connection.execute(
                "SELECT value_json FROM meta WHERE key='life_id'"
            ).fetchone()
            if row is not None and json.loads(row[0]) != self.life_id:
                raise ValueError("База принадлежит другой жизни")

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            connection = sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30
            )
        else:
            connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        if not readonly:
            connection.execute("PRAGMA synchronous=FULL")
        return connection

    @contextmanager
    def write(self):
        """Одна логическая запись = одна атомарная транзакция."""
        with self._write_lock, closing(self.connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def set_meta(self, key: str, value, connection=None) -> None:
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if connection is not None:
            connection.execute(
                "INSERT INTO meta(key, value_json, updated_at) VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
                "updated_at=excluded.updated_at",
                (str(key), payload),
            )
            return
        with self.write() as owned:
            self.set_meta(key, value, owned)

    def get_meta(self, key: str, default=None):
        with closing(self.connect(readonly=True)) as connection:
            row = connection.execute(
                "SELECT value_json FROM meta WHERE key = ?", (str(key),)
            ).fetchone()
        return default if row is None else json.loads(row[0])

    # ------------------------------------------------------------------
    # Реестр внешних артефактов (этап 5C)
    # ------------------------------------------------------------------

    @property
    def life_dir(self) -> Path:
        return self.path.parent

    @property
    def artifacts_dir(self) -> Path:
        return self.life_dir / "artifacts"

    @staticmethod
    def safe_relative_path(value) -> Path:
        """Относительный путь внутри каталога жизни; любой выход запрещён."""
        candidate = Path(value)
        if candidate.is_absolute() or candidate.drive or candidate.root:
            raise ValueError(f"Путь артефакта должен быть относительным: {value!r}")
        parts = candidate.parts
        if not parts or ".." in parts:
            raise ValueError(f"Путь артефакта выходит из каталога жизни: {value!r}")
        return candidate

    @classmethod
    def _kind_slug(cls, kind: str) -> str:
        slug = cls._KIND_SLUG_RE.sub("_", str(kind).strip().lower()).strip("_")
        return slug or "misc"

    @staticmethod
    def _digest_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    _ARTIFACT_COLUMNS = (
        "id, kind, relative_path, sha256, bytes, created_at, metadata_json"
    )

    @classmethod
    def _artifact_dict(cls, row) -> dict:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "relative_path": row["relative_path"],
            "sha256": row["sha256"],
            "bytes": row["bytes"],
            "created_at": row["created_at"],
            "metadata": json.loads(row["metadata_json"]),
        }

    def _upsert_artifact(
        self, connection, *, kind, relative_path, sha256, size,
        metadata, artifact_id=None, update=False,
    ) -> dict:
        row = connection.execute(
            f"SELECT {self._ARTIFACT_COLUMNS} FROM artifacts WHERE relative_path = ?",
            (relative_path,),
        ).fetchone()
        payload = json.dumps(metadata or {}, ensure_ascii=False, allow_nan=False)
        if row is None:
            identifier = artifact_id or f"art_{uuid4().hex}"
            connection.execute(
                "INSERT INTO artifacts"
                "(id, kind, relative_path, sha256, bytes, created_at, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier, str(kind), relative_path, sha256, int(size),
                    datetime.now(timezone.utc).isoformat(), payload,
                ),
            )
        elif row["sha256"] == sha256 and row["bytes"] == int(size):
            return self._artifact_dict(row)
        elif not update:
            raise ValueError(f"Путь уже занят другим содержимым: {relative_path}")
        else:
            connection.execute(
                "UPDATE artifacts SET kind = ?, sha256 = ?, bytes = ?, "
                "metadata_json = ? WHERE relative_path = ?",
                (str(kind), sha256, int(size), payload, relative_path),
            )
        row = connection.execute(
            f"SELECT {self._ARTIFACT_COLUMNS} FROM artifacts WHERE relative_path = ?",
            (relative_path,),
        ).fetchone()
        return self._artifact_dict(row)

    def register_artifact(
        self, source, *, kind, relative_path=None, metadata=None,
        artifact_id=None, update=False, connection=None,
    ) -> dict:
        """Зарегистрировать файл за этой жизнью: владелец, путь, SHA-256, размер.

        Файл из внешнего каталога копируется в ``artifacts/`` каталога жизни;
        файл внутри каталога жизни учитывается на месте. Оригинал не
        изменяется и не удаляется. ``update=True`` разрешает перерегистрацию
        новой редакции файла с тем же путём; по умолчанию чужое содержимое
        по занятому пути — ошибка.
        """
        source = Path(source)
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Артефакт должен быть существующим файлом: {source}")
        life_dir = self.life_dir.resolve()
        resolved = source.resolve()
        if relative_path is None:
            if resolved.is_relative_to(life_dir):
                rel = resolved.relative_to(life_dir)
            else:
                rel = Path("artifacts") / self._kind_slug(kind) / source.name
        else:
            rel = self.safe_relative_path(relative_path)
        target = life_dir / rel
        if resolved != target:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.is_symlink() or not target.is_file():
                    raise ValueError(f"Путь занят не файлом: {rel}")
                if self._digest_file(target) != self._digest_file(resolved):
                    if not update:
                        raise ValueError(
                            f"В каталоге жизни уже лежит другой файл: {rel}"
                        )
                    shutil.copy2(resolved, target)
            else:
                shutil.copy2(resolved, target)
        kwargs = dict(
            kind=kind, relative_path=rel.as_posix(),
            sha256=self._digest_file(target), size=target.stat().st_size,
            metadata=metadata, artifact_id=artifact_id, update=update,
        )
        if connection is not None:
            return self._upsert_artifact(connection, **kwargs)
        with self.write() as owned:
            return self._upsert_artifact(owned, **kwargs)

    def write_artifact(
        self, relative_path, data, *, kind, metadata=None,
        artifact_id=None, connection=None,
    ) -> dict:
        """Атомарно записать экспорт внутрь каталога жизни и зарегистрировать.

        Экспорт — производная от источника истины, поэтому всегда
        перезаписывается целиком, а строка реестра получает актуальные
        хеш и размер.
        """
        rel = self.safe_relative_path(relative_path)
        if rel.as_posix() == self.path.name:
            raise ValueError("Путь артефакта совпадает с базой жизни")
        target = self.life_dir / rel
        payload = bytes(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".artifact-", suffix=".tmp", dir=str(target.parent)
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
        kwargs = dict(
            kind=kind, relative_path=rel.as_posix(),
            sha256=self._digest_file(target), size=target.stat().st_size,
            metadata=metadata, artifact_id=artifact_id, update=True,
        )
        if connection is not None:
            return self._upsert_artifact(connection, **kwargs)
        with self.write() as owned:
            return self._upsert_artifact(owned, **kwargs)

    def list_artifacts(self, kind=None) -> list:
        query = f"SELECT {self._ARTIFACT_COLUMNS} FROM artifacts"
        params = ()
        if kind is not None:
            query += " WHERE kind = ?"
            params = (str(kind),)
        query += " ORDER BY created_at, id"
        with closing(self.connect(readonly=True)) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._artifact_dict(row) for row in rows]

    def get_artifact(self, artifact_id):
        with closing(self.connect(readonly=True)) as connection:
            row = connection.execute(
                f"SELECT {self._ARTIFACT_COLUMNS} FROM artifacts WHERE id = ?",
                (str(artifact_id),),
            ).fetchone()
        return None if row is None else self._artifact_dict(row)

    @classmethod
    def _verify_artifact_rows(cls, life_dir: Path, rows: list) -> dict:
        problems = []
        for row in rows:
            problem = None
            try:
                rel = cls.safe_relative_path(row["relative_path"])
            except ValueError:
                problem = "unsafe_path"
            else:
                path = life_dir / rel
                if path.is_symlink() or not path.is_file():
                    problem = "missing"
                elif (
                    path.stat().st_size != row["bytes"]
                    or cls._digest_file(path) != row["sha256"]
                ):
                    problem = "hash_mismatch"
            if problem is not None:
                problems.append({
                    "id": row["id"],
                    "relative_path": row["relative_path"],
                    "problem": problem,
                })
        return {"ok": not problems, "checked": len(rows), "problems": problems}

    @classmethod
    def verify_artifacts_readonly(cls, path) -> dict:
        """Проверить реестр без создания схемы и без изменения SQLite."""
        path = Path(path)
        with closing(sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro", uri=True
        )) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='artifacts'"
            ).fetchone()
            rows = [] if table is None else connection.execute(
                f"SELECT {cls._ARTIFACT_COLUMNS} FROM artifacts "
                "ORDER BY created_at, id"
            ).fetchall()
        artifacts = [cls._artifact_dict(row) for row in rows]
        return cls._verify_artifact_rows(path.parent, artifacts)

    def verify_artifacts(self) -> dict:
        """Сверить реестр с файлами: существование, размер и SHA-256."""
        return self._verify_artifact_rows(self.life_dir, self.list_artifacts())

    def append_dialogue_cycle(self, record, *, max_entries: int = 5000) -> int:
        """Атомарно добавить полный след цикла и удалить старые сверх лимита."""
        if not isinstance(record, dict):
            raise TypeError("Запись диалогового цикла должна быть словарём")
        limit = int(max_entries)
        if limit < 1:
            raise ValueError("Лимит диалогового журнала должен быть положительным")
        payload = json.dumps(record, ensure_ascii=False, allow_nan=False)
        with self.write() as connection:
            cursor = connection.execute(
                "INSERT INTO dialogue_cycles"
                "(ts, cycle, tick, agent_name, payload_json) VALUES (?, ?, ?, ?, ?)",
                (
                    str(record["timestamp"]),
                    int(record["cycle"]),
                    int(record["tick"]),
                    str(record["agent_name"]),
                    payload,
                ),
            )
            connection.execute(
                "DELETE FROM dialogue_cycles WHERE id NOT IN "
                "(SELECT id FROM dialogue_cycles ORDER BY id DESC LIMIT ?)",
                (limit,),
            )
            return int(cursor.lastrowid)

    def save_checkpoint(
        self, state, cycle_count: int, max_checkpoints: int = 20, *, saved_at=None
    ) -> int:
        """Снимок и указатель последнего снимка фиксируются одной транзакцией."""
        with self.write() as connection:
            snapshot_id = self.checkpoints.save(
                state, self.life_id, cycle_count,
                max_checkpoints=max_checkpoints, saved_at=saved_at,
                connection=connection,
            )
            self.set_meta("latest_snapshot_id", snapshot_id, connection)
            return snapshot_id

    def verify(self) -> dict:
        with closing(self.connect(readonly=True)) as connection:
            integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
            foreign_keys = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
            journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        return {
            "ok": integrity == ["ok"] and not foreign_keys and version == self.SCHEMA_VERSION,
            "integrity_check": integrity,
            "foreign_key_check": foreign_keys,
            "journal_mode": journal,
            "schema_version": version,
            "life_id": self.get_meta("life_id"),
        }
