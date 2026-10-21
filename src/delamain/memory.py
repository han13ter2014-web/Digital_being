"""SQLite-backed episodic and semantic memory for the local agent.

The store is deliberately simple and inspectable. It keeps:

* ``episodes`` — what the agent tried, with arguments and results;
* ``facts`` — small, explicit facts, searchable with SQLite FTS5;
* ``self_model`` — the agent's current description of itself;
* ``goals`` — durable goals and their status;
* ``skills`` — plans that worked or failed, for later reuse.

No external services and no model are required. If FTS5 is unavailable the
store transparently falls back to ``LIKE`` searches.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: Optional[str], default: Any = None) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class MemoryStore:
    """A small SQLite memory with explicit, typed operations."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._fts_enabled = False
        self._init_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS episodes (
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
            );
            CREATE INDEX IF NOT EXISTS idx_episodes_task
                ON episodes(task_id, id);
            CREATE INDEX IF NOT EXISTS idx_episodes_ts
                ON episodes(ts);

            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.5,
                meta_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_key_value
                ON facts(key, value);

            CREATE TABLE IF NOT EXISTS self_model (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                success_predicate TEXT NOT NULL DEFAULT '',
                priority REAL NOT NULL DEFAULT 0.5,
                meta_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_goals_status
                ON goals(status, priority DESC);

            CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                plan_json TEXT NOT NULL,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            """
        )

        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts "
                "USING fts5(key, value)"
            )
            self._fts_enabled = True
        except sqlite3.OperationalError:
            self._fts_enabled = False

        if self._fts_enabled:
            count = self._conn.execute(
                "SELECT COUNT(*) AS n FROM facts_fts"
            ).fetchone()["n"]
            if count == 0:
                rows = self._conn.execute(
                    "SELECT id, key, value FROM facts"
                ).fetchall()
                self._conn.executemany(
                    "INSERT INTO facts_fts(rowid, key, value) VALUES (?, ?, ?)",
                    [(row["id"], row["key"], row["value"]) for row in rows],
                )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Episodes
    # ------------------------------------------------------------------

    def record_episode(
        self,
        *,
        task_id: str,
        action: str,
        args: Optional[Dict[str, Any]] = None,
        ok: bool = True,
        output: Any = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        task: str = "",
    ) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO episodes
                (ts, task_id, task, action, args_json, ok, output_json, error, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utc_now_iso(),
                str(task_id),
                str(task or ""),
                str(action),
                _json(dict(args or {})),
                1 if ok else 0,
                _json(output) if output is not None else None,
                error,
                _json(dict(metadata or {})),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def recent_episodes(
        self,
        *,
        task_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        limit = max(0, int(limit))
        if limit == 0:
            return []
        if task_id is None:
            rows = self._conn.execute(
                "SELECT * FROM episodes ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM episodes WHERE task_id = ? ORDER BY id ASC LIMIT ?",
                (str(task_id), limit),
            ).fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "id": row["id"],
                    "ts": row["ts"],
                    "task_id": row["task_id"],
                    "task": row["task"],
                    "action": row["action"],
                    "args": _loads(row["args_json"], {}),
                    "ok": bool(row["ok"]),
                    "output": _loads(row["output_json"]),
                    "error": row["error"],
                    "metadata": _loads(row["meta_json"], {}),
                }
            )
        return result

    # ------------------------------------------------------------------
    # Facts (semantic memory)
    # ------------------------------------------------------------------

    def remember_fact(
        self,
        key: str,
        value: str,
        *,
        source: str = "",
        confidence: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        key = str(key).strip()
        value = str(value).strip()
        if not key:
            raise ValueError("fact key must not be empty")
        confidence = max(0.0, min(1.0, float(confidence)))
        now = _utc_now_iso()

        row = self._conn.execute(
            "SELECT id FROM facts WHERE key = ? AND value = ?", (key, value)
        ).fetchone()
        if row is None:
            cursor = self._conn.execute(
                """
                INSERT INTO facts (ts, key, value, source, confidence, meta_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now, key, value, str(source), confidence, _json(dict(metadata or {}))),
            )
            fact_id = int(cursor.lastrowid)
        else:
            fact_id = int(row["id"])
            self._conn.execute(
                """
                UPDATE facts
                SET ts = ?, source = ?, confidence = ?, meta_json = ?
                WHERE id = ?
                """,
                (now, str(source), confidence, _json(dict(metadata or {})), fact_id),
            )

        self._sync_fts(fact_id, key, value)
        self._conn.commit()
        return {
            "id": fact_id,
            "key": key,
            "value": value,
            "source": str(source),
            "confidence": confidence,
            "updated_at": now,
        }

    def _sync_fts(self, fact_id: int, key: str, value: str) -> None:
        if not self._fts_enabled:
            return
        self._conn.execute("DELETE FROM facts_fts WHERE rowid = ?", (fact_id,))
        self._conn.execute(
            "INSERT INTO facts_fts(rowid, key, value) VALUES (?, ?, ?)",
            (fact_id, key, value),
        )

    def recall_facts(self, query: str, *, limit: int = 10) -> List[Dict[str, Any]]:
        query = str(query).strip()
        limit = max(0, int(limit))
        if not query or limit == 0:
            return []

        rows: List[sqlite3.Row] = []
        if self._fts_enabled:
            terms = re.findall(r"[\w\-]+", query.casefold(), flags=re.UNICODE)
            if terms:
                fts_query = " OR ".join(f'"{term}"' for term in terms[:12])
                try:
                    rows = self._conn.execute(
                        """
                        SELECT f.*, bm25(facts_fts) AS search_rank
                        FROM facts_fts
                        JOIN facts AS f ON f.id = facts_fts.rowid
                        WHERE facts_fts MATCH ?
                        ORDER BY search_rank
                        LIMIT ?
                        """,
                        (fts_query, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []

        if not rows:
            like = f"%{query}%"
            rows = self._conn.execute(
                """
                SELECT * FROM facts
                WHERE key LIKE ? OR value LIKE ?
                ORDER BY confidence DESC, id DESC
                LIMIT ?
                """,
                (like, like, limit),
            ).fetchall()

        return [
            {
                "id": row["id"],
                "key": row["key"],
                "value": row["value"],
                "source": row["source"],
                "confidence": row["confidence"],
                "ts": row["ts"],
            }
            for row in rows
        ]

    def recent_facts(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        limit = max(0, int(limit))
        if limit == 0:
            return []
        rows = self._conn.execute(
            "SELECT * FROM facts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            {
                "id": row["id"],
                "key": row["key"],
                "value": row["value"],
                "source": row["source"],
                "confidence": row["confidence"],
                "ts": row["ts"],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Self-model
    # ------------------------------------------------------------------

    def set_self_model(self, key: str, value: Any) -> None:
        key = str(key).strip()
        if not key:
            raise ValueError("self-model key must not be empty")
        self._conn.execute(
            """
            INSERT INTO self_model (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_at = excluded.updated_at
            """,
            (key, _json(value), _utc_now_iso()),
        )
        self._conn.commit()

    def get_self_model(self, key: Optional[str] = None, default: Any = None) -> Any:
        if key is not None:
            row = self._conn.execute(
                "SELECT value_json FROM self_model WHERE key = ?", (str(key),)
            ).fetchone()
            return default if row is None else _loads(row["value_json"], default)
        rows = self._conn.execute(
            "SELECT key, value_json FROM self_model ORDER BY key"
        ).fetchall()
        return {row["key"]: _loads(row["value_json"]) for row in rows}

    # ------------------------------------------------------------------
    # Goals
    # ------------------------------------------------------------------

    def save_goal(
        self,
        title: str,
        *,
        status: str = "pending",
        success_predicate: str = "",
        priority: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        title = str(title).strip()
        if not title:
            raise ValueError("goal title must not be empty")
        now = _utc_now_iso()
        cursor = self._conn.execute(
            """
            INSERT INTO goals
                (created_at, updated_at, title, status, success_predicate, priority, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                title,
                str(status),
                str(success_predicate),
                max(0.0, min(1.0, float(priority))),
                _json(dict(metadata or {})),
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def update_goal_status(self, goal_id: int, status: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE goals SET status = ?, updated_at = ? WHERE id = ?",
            (str(status), _utc_now_iso(), int(goal_id)),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def update_goal(
        self,
        goal_id: int,
        *,
        status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        priority: Optional[float] = None,
        success_predicate: Optional[str] = None,
    ) -> bool:
        """Update a goal atomically, merging (not replacing) its metadata.

        ``update_goal_status`` is enough for simple transitions; this method
        exists for retry bookkeeping, where the subsystem adds attempts and a
        last-error field without losing the original command or plan.
        """

        goal_id = int(goal_id)
        row = self._conn.execute(
            "SELECT * FROM goals WHERE id = ?", (goal_id,)
        ).fetchone()
        if row is None:
            return False

        current_metadata = _loads(row["meta_json"], {})
        if not isinstance(current_metadata, dict):
            current_metadata = {}
        if metadata is not None:
            current_metadata.update(dict(metadata))

        new_status = row["status"] if status is None else str(status)
        new_predicate = (
            row["success_predicate"]
            if success_predicate is None
            else str(success_predicate)
        )
        new_priority = (
            row["priority"]
            if priority is None
            else max(0.0, min(1.0, float(priority)))
        )

        cursor = self._conn.execute(
            """
            UPDATE goals
            SET updated_at = ?, status = ?, success_predicate = ?,
                priority = ?, meta_json = ?
            WHERE id = ?
            """,
            (
                _utc_now_iso(),
                new_status,
                new_predicate,
                new_priority,
                _json(current_metadata),
                goal_id,
            ),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def list_goals(self, *, status: Optional[str] = None) -> List[Dict[str, Any]]:
        if status is None:
            rows = self._conn.execute(
                "SELECT * FROM goals ORDER BY priority DESC, id DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM goals WHERE status = ? ORDER BY priority DESC, id DESC",
                (str(status),),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "title": row["title"],
                "status": row["status"],
                "success_predicate": row["success_predicate"],
                "priority": row["priority"],
                "metadata": _loads(row["meta_json"], {}),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------

    def record_skill(
        self,
        name: str,
        plan: Any = None,
        *,
        success: bool = True,
    ) -> None:
        """Record a skill outcome, keeping the last known plan on failure.

        A failed attempt should increment ``failure_count`` but must not
        erase a plan that worked before. Passing ``plan=None`` therefore
        preserves the existing plan (or stores JSON ``null`` for a brand-new
        skill that has never succeeded).
        """

        name = str(name).strip()
        if not name:
            raise ValueError("skill name must not be empty")
        if plan is None:
            row = self._conn.execute(
                "SELECT plan_json FROM skills WHERE name = ?", (name,)
            ).fetchone()
            plan_json = row["plan_json"] if row is not None else _json(None)
        else:
            plan_json = _json(plan)

        increment_success = 1 if success else 0
        increment_failure = 0 if success else 1
        self._conn.execute(
            """
            INSERT INTO skills
                (name, plan_json, success_count, failure_count, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                plan_json = excluded.plan_json,
                success_count = skills.success_count + excluded.success_count,
                failure_count = skills.failure_count + excluded.failure_count,
                updated_at = excluded.updated_at
            """,
            (
                name,
                plan_json,
                increment_success,
                increment_failure,
                _utc_now_iso(),
            ),
        )
        self._conn.commit()

    def get_skill(self, name: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM skills WHERE name = ?", (str(name),)
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "plan": _loads(row["plan_json"]),
            "success_count": row["success_count"],
            "failure_count": row["failure_count"],
            "updated_at": row["updated_at"],
        }

    def list_skills(self, *, limit: int = 20) -> List[Dict[str, Any]]:
        limit = max(0, int(limit))
        if limit == 0:
            return []
        rows = self._conn.execute(
            """
            SELECT * FROM skills
            ORDER BY success_count DESC, updated_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "plan": _loads(row["plan_json"]),
                "success_count": row["success_count"],
                "failure_count": row["failure_count"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()
