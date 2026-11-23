"""Выключенный по умолчанию prospective journal фактических ответов.

Журнал только наблюдает уже подтверждённые локальные переходы. Он не содержит
сырых текстов, не обучает модель и не участвует в выборе или доставке ответа.
Каждая жизнь получает отдельный append-only SQLite с проверяемой hash-chain.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4

from src.core.life_identity import validate_life_id
from src.core.paths import data_path

JOURNAL_SCHEMA_VERSION = 1
SEGMENT_JOURNAL_SCHEMA_VERSION = 2
FEATURE_CONTRACT_VERSION = "pj_structured_v1"
WRITER_CONTRACT_VERSION = "pj_i_production_v1"
SEGMENT_WRITER_CONTRACT_VERSION = "cs_i_segment_v1"
RESPONSE_JOURNAL_ENV = "DIGITAL_BEING_RESPONSE_JOURNAL"
RESPONSE_JOURNAL_SEGMENT_ENV = "DIGITAL_BEING_RESPONSE_JOURNAL_SEGMENT"
RESPONSE_JOURNAL_SEGMENT_ID_ENV = "DIGITAL_BEING_RESPONSE_JOURNAL_SEGMENT_ID"
RESPONSE_JOURNAL_ARCHIVE_HASH_ENV = "DIGITAL_BEING_RESPONSE_JOURNAL_ARCHIVE_HASH"
JOURNAL_FILENAME = "response_experience_events.sqlite3"
SEGMENT_EXCLUSION = "segment_exclusion"

DEFAULT_MAX_EVENTS = 250_000
DEFAULT_MAX_PAYLOAD_BYTES = 16 * 1024
DEFAULT_MAX_STORAGE_BYTES = 64 * 1024 * 1024
BUSY_TIMEOUT_MS = 250

OBSERVED_OUTCOMES = frozenset(
    {
        "answer",
        "follow_up",
        "unclassified_reply",
        "ordinary_reply",
        "explicit_support",
        "explicit_opposition",
    }
)
EVENT_KINDS = frozenset(
    {
        "delivery",
        "outcome",
        "expired",
        "record_pruned",
        "journal_started",
        "journal_stopped",
        "journal_gap",
    }
)
INTENTIONS = frozenset(
    {
        "acknowledge_uncertainty",
        "social_acknowledgement",
        "acknowledge_feedback",
        "clarify",
        "answer_from_existing_state",
    }
)
CONTEXTS = frozenset(
    {
        "unknown_reply",
        "unknown_listen",
        "social_reply",
        "dialogue_learning",
        "dialogue_feedback",
    }
)
SOURCES = frozenset({"core", "agent_runner", "deterministic_core", "local", "unknown"})
EXPECTATIONS = frozenset(
    {
        "explicit_feedback_or_relevant_reply",
        "answer_or_feedback",
        "continuation_or_support",
    }
)
LANGUAGES = frozenset({"ru", "en", "zh", "mixed", "unknown"})
LANGUAGE_SOURCES = frozenset(
    {"profile_preference", "stable_dialogue", "limited_detector", "legacy_default"}
)
REFERENCE_KINDS = frozenset({"state", "concept", "episode", "affect", "dialogue_act"})


class JournalError(RuntimeError):
    """Ожидаемая ошибка writer; жизненный цикл продолжается без неё."""


class JournalCorruption(JournalError):
    """Журнал нельзя считать проверенным; история не исправляется."""


class JournalCapacity(JournalError):
    """Достигнут замороженный бюджет событий, payload или хранилища."""


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def event_hash(event: dict) -> str:
    material = {key: value for key, value in event.items() if key != "event_hash"}
    return hashlib.sha256(canonical(material).encode("utf-8")).hexdigest()


def disabled_journal_status() -> dict:
    return {
        "enabled": False,
        "status": "disabled",
        "open": False,
        "event_sequence": 0,
        "event_count": 0,
        "gap_count": 0,
        "dropped_events": 0,
        "storage_bytes": 0,
        "last_error": None,
    }


def _enum(value, allowed, *, missing="missing"):
    if value is None:
        return missing
    return value if value in allowed else "other"


def _length_bucket(text: str) -> str:
    length = len(text)
    if length == 0:
        return "0"
    if length <= 40:
        return "1-40"
    if length <= 160:
        return "41-160"
    if length <= 500:
        return "161-500"
    return "501+"


def _count_bucket(value: int) -> str:
    if value == 0:
        return "0"
    if value <= 2:
        return "1-2"
    if value <= 4:
        return "3-4"
    if value <= 8:
        return "5-8"
    return "9+"


def _confidence_bucket(value) -> str:
    if value is None:
        return "missing"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "other"
    if not math.isfinite(value):
        return "other"
    if value >= 1.0:
        return "1.00"
    if value >= 0.75:
        return "0.75-0.99"
    if value >= 0.50:
        return "0.50-0.74"
    if value >= 0.25:
        return "0.25-0.49"
    return "0.00-0.24"


def safe_features(record: dict, *, repeat_origin: str | None) -> dict:
    """Преобразовать запись в frozen whitelist, исключив текст и reference IDs."""
    plan = record["plan"]
    realization = plan["realization"]
    language = plan.get("language_context") or {}
    borrowed = plan.get("borrowed") or {}
    references = plan.get("references") or []
    reference_counts = Counter(
        item.get("kind") if item.get("kind") in REFERENCE_KINDS else "other"
        for item in references
    )
    components = [
        item if item in {"deterministic_reply", "borrowed_expression"} else "other"
        for item in plan.get("components", [])
    ]
    uncertainties = set(record.get("uncertainties") or [])
    return {
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "intention": _enum(plan.get("intention"), INTENTIONS, missing="other"),
        "context": _enum(plan.get("context"), CONTEXTS, missing="other"),
        "source": _enum(plan.get("source"), SOURCES, missing="other"),
        "expected_reaction": _enum(
            record.get("expected_reaction"), EXPECTATIONS, missing="other"
        ),
        "uncertainty_input_meaning": "input_meaning" in uncertainties,
        "uncertainty_borrowed_expression_fit": (
            "borrowed_expression_fit" in uncertainties
        ),
        "language_missing": not bool(language),
        "input_language": _enum(language.get("input_language"), LANGUAGES),
        "dialogue_language": _enum(language.get("dialogue_language"), LANGUAGES),
        "response_language": _enum(
            language.get("response_language", "ru"), LANGUAGES, missing="other"
        ),
        "language_source": _enum(language.get("source"), LANGUAGE_SOURCES),
        "language_confidence_bucket": _confidence_bucket(language.get("confidence")),
        "realization_kind": _enum(
            realization.get("kind"),
            {"fixed_template", "borrowed_prefix"},
            missing="other",
        ),
        "realization_rule_id": _enum(
            realization.get("rule_id"), {"en_deterministic_v1", "zh_deterministic_v1"}
        ),
        "realization_act": _enum(
            realization.get("act"), {"answer", "follow_up", "social", "unknown"}
        ),
        "realization_fallback_policy": _enum(
            realization.get("fallback_policy", "none"), {"none", "base_text", "ru"}
        ),
        "components": components,
        "borrowed_present": bool(borrowed),
        "borrowed_context": _enum(borrowed.get("context"), CONTEXTS),
        "borrowed_level": _enum(borrowed.get("level"), {"situational", "habit"}),
        "borrowed_language": _enum(borrowed.get("language_id"), LANGUAGES),
        "reference_count_bucket": _count_bucket(len(references)),
        "reference_kind_counts": {
            key: _count_bucket(value) for key, value in sorted(reference_counts.items())
        },
        "provenance_verified": bool(plan.get("provenance_verified")),
        "input_length_bucket": _length_bucket(plan.get("observed_input", "")),
        "realization_length_bucket": _length_bucket(realization.get("base_text", "")),
        "repeat_in_retained_window": repeat_origin is not None,
        "realization_origin_response_id": repeat_origin,
        "repeat_evidence_scope": "retained_window",
    }


def _validate_segment_options(
    segment_id, boundary_cycle, archive_manifest_hash, preexisting
):
    if segment_id is None:
        if preexisting or archive_manifest_hash is not None or boundary_cycle != 0:
            raise ValueError("segment options require segment_id")
        return set()
    if (
        not isinstance(segment_id, str)
        or not segment_id.strip()
        or len(segment_id) > 160
    ):
        raise ValueError("segment_id: expected a bounded nonempty string")
    if (
        isinstance(boundary_cycle, bool)
        or not isinstance(boundary_cycle, int)
        or boundary_cycle < 0
    ):
        raise ValueError("boundary_cycle: expected a nonnegative integer")
    if (
        not isinstance(archive_manifest_hash, str)
        or len(archive_manifest_hash) != 64
        or any(
            character not in "0123456789abcdef" for character in archive_manifest_hash
        )
    ):
        raise ValueError("archive_manifest_hash: expected SHA-256 hex")
    exclusions = set()
    for item in preexisting:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError("segment exclusions: expected profile/response pairs")
        profile_id, response_id = item
        if any(
            not isinstance(value, str) or not value or len(value) > 160
            for value in (profile_id, response_id)
        ):
            raise ValueError("segment exclusions: invalid technical ID")
        exclusions.add((profile_id, response_id))
    return exclusions


class ResponseExperienceJournal:
    """Синхронный fail-open writer без фоновых задач и сетевых вызовов."""

    connection: sqlite3.Connection | None
    degradation_reason: str | None
    last_error: str | None
    segment_id: str | None
    archive_manifest_hash: str | None

    def __init__(
        self,
        path: str | Path,
        life_id: str,
        *,
        max_events: int | None = DEFAULT_MAX_EVENTS,
        max_payload_bytes: int | None = DEFAULT_MAX_PAYLOAD_BYTES,
        max_storage_bytes: int | None = DEFAULT_MAX_STORAGE_BYTES,
        segment_id: str | None = None,
        boundary_cycle: int = 0,
        archive_manifest_hash: str | None = None,
        preexisting=(),
    ) -> None:
        self._initialize_state(path, life_id)
        self.segment_id = segment_id
        self.boundary_cycle = boundary_cycle
        self.archive_manifest_hash = archive_manifest_hash
        self._segment_exclusions = _validate_segment_options(
            segment_id, boundary_cycle, archive_manifest_hash, preexisting
        )
        if segment_id is not None:
            self.journal_schema_version = SEGMENT_JOURNAL_SCHEMA_VERSION
            self.writer_contract_version = SEGMENT_WRITER_CONTRACT_VERSION
            self.allowed_event_kinds = EVENT_KINDS | {SEGMENT_EXCLUSION}
        self.max_events = max_events
        self.max_payload_bytes = max_payload_bytes
        self.max_storage_bytes = max_storage_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fresh = not self.path.exists()
        self.connection = sqlite3.connect(
            self.path,
            timeout=BUSY_TIMEOUT_MS / 1000,
            check_same_thread=False,
            isolation_level=None,
        )
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute("PRAGMA foreign_keys=ON")
            self._schema()
            previous_unclean = False
            previous_degraded = False
            previous_reason = None
            if fresh:
                self.connection.execute(
                    "INSERT INTO head(id, sequence, event_hash, next_turn,"
                    " clean_shutdown, status, degradation_reason)"
                    " VALUES(1, 0, ?, 1, 0, 'active', NULL)",
                    ("0" * 64,),
                )
            else:
                self._verify()
                if self.segment_id is not None:
                    first = self.connection.execute(
                        "SELECT payload FROM events WHERE event_sequence=1"
                    ).fetchone()
                    segment_payload = json.loads(first["payload"]) if first else {}
                    if segment_payload.get("segment_id") != self.segment_id:
                        raise JournalCorruption("segment_mismatch")
                    self._segment_exclusions = {
                        (row["profile_id"], row["response_id"])
                        for row in self.connection.execute(
                            "SELECT profile_id, response_id FROM events"
                            " WHERE event_kind=?",
                            (SEGMENT_EXCLUSION,),
                        )
                    }
            active_writers = self._register_writer()
            head = self._head()
            if not fresh:
                previous_unclean = (
                    not bool(head["clean_shutdown"]) and not active_writers
                )
                previous_degraded = head["status"] in {"degraded", "quarantine"}
                previous_reason = head["degradation_reason"]
                self._last_sequence = head["sequence"]
                self._last_event_hash = head["event_hash"]
                if previous_unclean or previous_degraded:
                    self.status = "degraded"
                    self.degradation_reason = (
                        "previous_shutdown_unclean"
                        if previous_unclean
                        else previous_reason
                    )
            previous_sequence = self._head()["sequence"]
            previous_hash = self._head()["event_hash"]
            started_payload = {
                "clean_start": fresh,
                "previous_shutdown_unclean": previous_unclean,
                "previous_writer_degraded": previous_degraded,
                "previous_sequence": previous_sequence,
                "previous_hash": previous_hash,
            }
            if self.segment_id is not None:
                started_payload.update(
                    {
                        "segment_id": self.segment_id,
                        "boundary_cycle": self.boundary_cycle,
                        "archive_manifest_hash": self.archive_manifest_hash,
                        "segment_reason": "owner_approved_clean_collection",
                    }
                )
            self._safe_append(
                "journal_started",
                event_id=f"started:{uuid4().hex}",
                payload=started_payload,
            )
            if fresh and self.segment_id is not None:
                for profile_id, response_id in sorted(self._segment_exclusions):
                    self._safe_append(
                        SEGMENT_EXCLUSION,
                        event_id=(
                            f"segment-exclusion:{self.segment_id}:"
                            f"{profile_id}:{response_id}"
                        ),
                        profile_id=profile_id,
                        response_id=response_id,
                        payload={
                            "segment_id": self.segment_id,
                            "reason": "pre_segment_response",
                        },
                    )
            if previous_unclean:
                self._append_gap("previous_shutdown_unclean", completeness="unverified")
            if previous_degraded:
                self._append_gap(
                    "previous_writer_degraded",
                    completeness="unverified",
                    previous_reason=previous_reason,
                )
        except Exception:
            self.connection.close()
            self.connection = None
            raise

    def _initialize_state(self, path: str | Path, life_id: str) -> None:
        self.path = Path(path)
        self.life_id = validate_life_id(life_id)
        self.max_events = DEFAULT_MAX_EVENTS
        self.max_payload_bytes = DEFAULT_MAX_PAYLOAD_BYTES
        self.max_storage_bytes = DEFAULT_MAX_STORAGE_BYTES
        self.status = "active"
        self.degradation_reason = None
        self.last_error = None
        self.dropped_events = 0
        self.fail_next_append = False
        self.connection = None
        self.writer_id = f"writer:{uuid4().hex}"
        self._last_sequence = 0
        self._last_event_hash = "0" * 64
        self._lock = threading.RLock()
        self.segment_id = None
        self.boundary_cycle = 0
        self.archive_manifest_hash = None
        self._segment_exclusions = set()
        self.journal_schema_version = JOURNAL_SCHEMA_VERSION
        self.writer_contract_version = WRITER_CONTRACT_VERSION
        self.allowed_event_kinds = EVENT_KINDS

    @classmethod
    def unavailable(cls, path: str | Path, life_id: str, error: Exception):
        instance = cls.__new__(cls)
        instance._initialize_state(path, life_id)
        instance.status = (
            "quarantine" if isinstance(error, JournalCorruption) else "degraded"
        )
        instance.degradation_reason = instance._error_reason(error)
        instance.last_error = instance.degradation_reason
        return instance

    @staticmethod
    def _error_reason(error: Exception) -> str:
        if isinstance(error, JournalError):
            return str(error)[:120]
        return type(error).__name__[:120]

    def _require_connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise JournalError("writer_unavailable")
        return self.connection

    def _schema(self) -> None:
        self._require_connection().executescript(
            """
            CREATE TABLE IF NOT EXISTS head(
                id INTEGER PRIMARY KEY CHECK(id=1),
                sequence INTEGER NOT NULL,
                event_hash TEXT NOT NULL,
                next_turn INTEGER NOT NULL,
                clean_shutdown INTEGER NOT NULL,
                status TEXT NOT NULL,
                degradation_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS events(
                event_id TEXT PRIMARY KEY,
                event_sequence INTEGER UNIQUE NOT NULL,
                event_kind TEXT NOT NULL,
                journal_schema_version INTEGER NOT NULL,
                feature_contract_version TEXT NOT NULL,
                writer_contract_version TEXT NOT NULL,
                life_id TEXT NOT NULL,
                profile_id TEXT,
                cycle INTEGER,
                turn_id TEXT,
                episode_id TEXT,
                response_id TEXT,
                emission_status TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_response
                ON events(life_id, profile_id, response_id, event_kind);
            CREATE TRIGGER IF NOT EXISTS events_append_only_update
                BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT, 'events_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS events_append_only_delete
                BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT, 'events_append_only'); END;
            CREATE TABLE IF NOT EXISTS writer_leases(
                writer_id TEXT PRIMARY KEY,
                process_id INTEGER NOT NULL
            );
            """
        )

    @staticmethod
    def _process_alive(process_id: int) -> bool:
        if process_id == os.getpid():
            return True
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _prune_writer_leases(self) -> int:
        connection = self._require_connection()
        rows = connection.execute(
            "SELECT writer_id, process_id FROM writer_leases"
        ).fetchall()
        active = 0
        for row in rows:
            if self._process_alive(row["process_id"]):
                active += 1
            else:
                connection.execute(
                    "DELETE FROM writer_leases WHERE writer_id=?", (row["writer_id"],)
                )
        return active

    def _register_writer(self) -> int:
        connection = self._require_connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            active = self._prune_writer_leases()
            connection.execute(
                "INSERT INTO writer_leases(writer_id, process_id) VALUES(?, ?)",
                (self.writer_id, os.getpid()),
            )
            connection.execute("COMMIT")
            return active
        except Exception:
            connection.execute("ROLLBACK")
            raise

    def _unregister_writer(self) -> None:
        connection = self._require_connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "DELETE FROM writer_leases WHERE writer_id=?", (self.writer_id,)
            )
            active = self._prune_writer_leases()
            connection.execute(
                "UPDATE head SET clean_shutdown=?, status=?, degradation_reason=?"
                " WHERE id=1",
                (0 if active else 1, self.status, self.degradation_reason),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise

    def _head(self):
        connection = self._require_connection()
        row = connection.execute("SELECT * FROM head WHERE id=1").fetchone()
        if row is None:
            raise JournalCorruption("missing_head")
        return row

    @staticmethod
    def _row_event(row) -> dict:
        return {
            "event_id": row["event_id"],
            "event_sequence": row["event_sequence"],
            "event_kind": row["event_kind"],
            "journal_schema_version": row["journal_schema_version"],
            "feature_contract_version": row["feature_contract_version"],
            "writer_contract_version": row["writer_contract_version"],
            "life_id": row["life_id"],
            "profile_id": row["profile_id"],
            "cycle": row["cycle"],
            "turn_id": row["turn_id"],
            "episode_id": row["episode_id"],
            "response_id": row["response_id"],
            "emission_status": row["emission_status"],
            "previous_hash": row["previous_hash"],
            "event_hash": row["event_hash"],
            "payload": json.loads(row["payload"]),
        }

    def _verify(self) -> None:
        connection = self._require_connection()
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise JournalCorruption("sqlite_integrity")
        rows = connection.execute(
            "SELECT * FROM events ORDER BY event_sequence"
        ).fetchall()
        head = self._head()
        previous = "0" * 64
        for expected, row in enumerate(rows, 1):
            event = self._row_event(row)
            if event["event_sequence"] != expected:
                raise JournalCorruption("sequence_mismatch")
            if event["previous_hash"] != previous:
                raise JournalCorruption("hash_chain_mismatch")
            if event["event_hash"] != event_hash(event):
                raise JournalCorruption("event_hash_mismatch")
            if event["event_kind"] not in self.allowed_event_kinds:
                raise JournalCorruption("unknown_event_kind")
            if event["journal_schema_version"] != self.journal_schema_version:
                raise JournalCorruption("unsupported_journal_schema")
            if event["writer_contract_version"] != self.writer_contract_version:
                raise JournalCorruption("unsupported_writer_contract")
            if event["life_id"] != self.life_id:
                raise JournalCorruption("life_mismatch")
            if event["emission_status"] != "committed":
                raise JournalCorruption("unsupported_emission_status")
            previous = event["event_hash"]
        if head["sequence"] != len(rows) or head["event_hash"] != previous:
            raise JournalCorruption("head_mismatch")
        if head["next_turn"] < 1:
            raise JournalCorruption("turn_head_mismatch")

    def _storage_bytes(self) -> int:
        total = self.path.stat().st_size if self.path.exists() else 0
        wal = Path(f"{self.path}-wal")
        if wal.exists():
            total += wal.stat().st_size
        return total

    def _append(
        self,
        event_kind: str,
        *,
        event_id: str,
        profile_id: str | None = None,
        cycle: int | None = None,
        turn_id: str | None = None,
        episode_id: str | None = None,
        response_id: str | None = None,
        payload: dict | None = None,
    ) -> dict:
        with self._lock:
            if self.connection is None:
                raise JournalError("writer_unavailable")
            if event_kind not in self.allowed_event_kinds:
                raise JournalError("unsupported_event_kind")
            if self.fail_next_append:
                self.fail_next_append = False
                raise JournalError("injected_append_failure")
            clean_payload = deepcopy(payload or {})
            encoded_payload = canonical(clean_payload)
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                existing = self.connection.execute(
                    "SELECT * FROM events WHERE event_id=?", (event_id,)
                ).fetchone()
                if existing is not None:
                    event = self._row_event(existing)
                    identity = (
                        "event_kind",
                        "life_id",
                        "profile_id",
                        "cycle",
                        "turn_id",
                        "episode_id",
                        "response_id",
                    )
                    if (
                        any(
                            event[key] != value
                            for key, value in zip(
                                identity,
                                (
                                    event_kind,
                                    self.life_id,
                                    profile_id,
                                    cycle,
                                    turn_id,
                                    episode_id,
                                    response_id,
                                ),
                            )
                        )
                        or event["payload"] != clean_payload
                    ):
                        raise JournalError("event_id_conflict")
                    self.connection.execute("COMMIT")
                    return event
                head = self._head()
                is_gap = event_kind == "journal_gap"
                if self.max_events is not None:
                    # Один последний slot резервируется для видимого capacity gap.
                    limit = self.max_events if is_gap else self.max_events - 1
                    if head["sequence"] >= limit:
                        raise JournalCapacity("hard_event_budget")
                if (
                    self.max_payload_bytes is not None
                    and len(encoded_payload.encode("utf-8")) > self.max_payload_bytes
                ):
                    raise JournalCapacity("hard_payload_budget")
                if (
                    self.max_storage_bytes is not None
                    and self._storage_bytes() >= self.max_storage_bytes
                ):
                    raise JournalCapacity("hard_storage_budget")
                event = {
                    "event_id": event_id,
                    "event_sequence": head["sequence"] + 1,
                    "event_kind": event_kind,
                    "journal_schema_version": self.journal_schema_version,
                    "feature_contract_version": FEATURE_CONTRACT_VERSION,
                    "writer_contract_version": self.writer_contract_version,
                    "life_id": self.life_id,
                    "profile_id": profile_id,
                    "cycle": cycle,
                    "turn_id": turn_id,
                    "episode_id": episode_id,
                    "response_id": response_id,
                    "emission_status": "committed",
                    "previous_hash": head["event_hash"],
                    "payload": clean_payload,
                }
                event["event_hash"] = event_hash(event)
                self.connection.execute(
                    "INSERT INTO events(event_id, event_sequence, event_kind,"
                    " journal_schema_version, feature_contract_version,"
                    " writer_contract_version, life_id, profile_id, cycle, turn_id,"
                    " episode_id, response_id, emission_status, previous_hash,"
                    " event_hash, payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        event["event_id"],
                        event["event_sequence"],
                        event["event_kind"],
                        event["journal_schema_version"],
                        event["feature_contract_version"],
                        event["writer_contract_version"],
                        event["life_id"],
                        event["profile_id"],
                        event["cycle"],
                        event["turn_id"],
                        event["episode_id"],
                        event["response_id"],
                        event["emission_status"],
                        event["previous_hash"],
                        event["event_hash"],
                        encoded_payload,
                    ),
                )
                self.connection.execute(
                    "UPDATE head SET sequence=?, event_hash=?, clean_shutdown=0,"
                    " status=?, degradation_reason=? WHERE id=1",
                    (
                        event["event_sequence"],
                        event["event_hash"],
                        self.status,
                        self.degradation_reason,
                    ),
                )
                self.connection.execute("COMMIT")
                self._last_sequence = event["event_sequence"]
                self._last_event_hash = event["event_hash"]
                return event
            except Exception:
                self.connection.execute("ROLLBACK")
                raise

    def _persist_status(self) -> None:
        if self.connection is None:
            return
        try:
            self.connection.execute(
                "UPDATE head SET status=?, degradation_reason=? WHERE id=1",
                (self.status, self.degradation_reason),
            )
        except sqlite3.Error:
            # Следующий restart повторит проверку; ошибка не пробрасывается в жизнь.
            pass

    def _safe_append(self, event_kind: str, **kwargs):
        try:
            return self._append(event_kind, **kwargs)
        except (JournalError, sqlite3.Error, OSError, TypeError, ValueError) as error:
            self.dropped_events += 1
            self.status = (
                "quarantine" if isinstance(error, JournalCorruption) else "degraded"
            )
            self.degradation_reason = self._error_reason(error)
            self.last_error = self.degradation_reason
            self._persist_status()
            if event_kind != "journal_gap":
                self._append_gap(self.degradation_reason, completeness="unverified")
            return None

    def _append_gap(self, reason: str, **payload):
        return self._safe_append(
            "journal_gap",
            event_id=f"gap:{uuid4().hex}",
            payload={"reason": reason, **payload},
        )

    def begin_turn(self) -> str | None:
        """Выделить monotonic ID входа; ошибка не отменяет обработку входа."""
        with self._lock:
            if self.connection is None:
                return None
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                number = self._head()["next_turn"]
                self.connection.execute(
                    "UPDATE head SET next_turn=? WHERE id=1", (number + 1,)
                )
                self.connection.execute("COMMIT")
                return f"turn-{number}"
            except (JournalError, sqlite3.Error, OSError) as error:
                try:
                    self.connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                self.status = "degraded"
                self.degradation_reason = self._error_reason(error)
                self.last_error = self.degradation_reason
                self._persist_status()
                self._append_gap("turn_allocation_failed", completeness="unverified")
                return None

    def _delivery(self, profile_id: str, response_id: str):
        if self.connection is None:
            return None
        return self.connection.execute(
            "SELECT * FROM events WHERE life_id=? AND profile_id=? AND response_id=?"
            " AND event_kind='delivery'",
            (self.life_id, profile_id, response_id),
        ).fetchone()

    @staticmethod
    def _repeat_origin(experience, record: dict) -> str | None:
        response_id = record["response_id"]
        realization = record["plan"]["realization"].get("text")
        for old_id, old in experience.responses.items():
            if old_id == response_id:
                continue
            if old["plan"]["realization"].get("text") == realization:
                return old_id
        return None

    def record_delivery(
        self,
        experience,
        record: dict,
        *,
        cycle: int,
        turn_id: str | None,
    ) -> dict | None:
        """Записать уже подтверждённую AgentRunner локальную доставку."""
        try:
            profile_id = record["plan"]["state"]["profile_id"]
            response_id = record["response_id"]
            repeat_origin = self._repeat_origin(experience, record)
        except (KeyError, TypeError) as error:
            self.status = "degraded"
            self.degradation_reason = self._error_reason(error)
            self.last_error = self.degradation_reason
            self._append_gap("invalid_delivery_record", completeness="unverified")
            return None
        return self._safe_append(
            "delivery",
            event_id=f"delivery:{self.life_id}:{profile_id}:{response_id}",
            profile_id=profile_id,
            cycle=cycle,
            turn_id=turn_id,
            episode_id=f"episode:{self.life_id}:{profile_id}:{response_id}",
            response_id=response_id,
            payload={
                "local_delivery_confirmed": True,
                "delivery_cycle": cycle,
                "features": safe_features(record, repeat_origin=repeat_origin),
            },
        )

    def record_transition(
        self,
        transition_kind: str,
        record: dict,
        *,
        cycle: int,
        turn_id: str | None,
    ) -> dict | None:
        """Наблюдать фактический outcome/expiry/pruning без изменения записи."""
        if transition_kind not in {"outcome", "expired", "record_pruned"}:
            return None
        with self._lock:
            try:
                profile_id = record["plan"]["state"]["profile_id"]
                response_id = record["response_id"]
                delivery = self._delivery(profile_id, response_id)
            except (KeyError, TypeError, sqlite3.Error) as error:
                self.status = "degraded"
                self.degradation_reason = self._error_reason(error)
                self.last_error = self.degradation_reason
                self._append_gap("invalid_transition_record", completeness="unverified")
                return None
            if (
                delivery is None
                and (profile_id, response_id) in self._segment_exclusions
            ):
                return None
            if delivery is None and transition_kind != "record_pruned":
                self._append_gap(
                    "orphan_outcome",
                    completeness="unverified",
                    orphan_response_id=response_id,
                )
                return None
            if transition_kind == "record_pruned":
                return self._safe_append(
                    transition_kind,
                    event_id=f"pruned:{self.life_id}:{profile_id}:{response_id}",
                    profile_id=profile_id,
                    cycle=cycle,
                    turn_id=turn_id,
                    episode_id=delivery["episode_id"] if delivery else None,
                    response_id=response_id,
                    payload={
                        "delivery_sequence": (
                            delivery["event_sequence"] if delivery else None
                        ),
                        "origin_unavailable": delivery is None,
                    },
                )
            expired = transition_kind == "expired"
            return self._safe_append(
                transition_kind,
                event_id=f"{transition_kind}:{self.life_id}:{profile_id}:{response_id}",
                profile_id=profile_id,
                cycle=cycle,
                turn_id=turn_id,
                episode_id=delivery["episode_id"],
                response_id=response_id,
                payload={
                    "delivery_sequence": delivery["event_sequence"],
                    "outcome_cycle": cycle,
                    "observation_turn_id": turn_id,
                    "observed_outcome": (
                        "no_observed_reaction" if expired else record["outcome"]
                    ),
                    "observation_kind": (
                        "ttl_expired"
                        if expired
                        else "explicit_feedback"
                        if str(record["outcome"]).startswith("explicit_")
                        else "ordinary_reply"
                    ),
                },
            )

    def note_core_restore(self, *, cycle: int) -> dict | None:
        return self._safe_append(
            "journal_gap",
            event_id=f"gap:{uuid4().hex}",
            cycle=cycle,
            payload={"reason": "core_restore_divergence", "completeness": "unverified"},
        )

    def events(self) -> list[dict]:
        with self._lock:
            if self.connection is None:
                return []
            return [
                self._row_event(row)
                for row in self.connection.execute(
                    "SELECT * FROM events ORDER BY event_sequence"
                )
            ]

    def samples(self, *, outcome_before_sequence: int | None = None) -> list[dict]:
        """Read-only временная доступность исходов для будущего inventory."""
        events = self.events()
        samples = []
        for delivery in events:
            if delivery["event_kind"] != "delivery":
                continue
            outcomes = [
                event
                for event in events
                if event["event_kind"] == "outcome"
                and event["response_id"] == delivery["response_id"]
                and event["profile_id"] == delivery["profile_id"]
            ]
            if len(outcomes) != 1:
                continue
            outcome = outcomes[0]
            if outcome["payload"]["observed_outcome"] not in OBSERVED_OUTCOMES:
                continue
            if (
                outcome_before_sequence is not None
                and outcome["event_sequence"] >= outcome_before_sequence
            ):
                continue
            samples.append(
                {
                    "features": deepcopy(delivery["payload"]["features"]),
                    "response_id": delivery["response_id"],
                    "episode_id": delivery["episode_id"],
                    "delivery_sequence": delivery["event_sequence"],
                    "outcome": outcome["payload"]["observed_outcome"],
                    "outcome_sequence": outcome["event_sequence"],
                }
            )
        return samples

    def get_status(self) -> dict:
        with self._lock:
            gap_count = 0
            if self.connection is not None:
                try:
                    gap_count = self.connection.execute(
                        "SELECT COUNT(*) FROM events WHERE event_kind='journal_gap'"
                    ).fetchone()[0]
                except sqlite3.Error:
                    self.status = "degraded"
                    self.last_error = "status_query_failed"
            return {
                "enabled": True,
                "status": self.status,
                "open": self.connection is not None,
                "event_sequence": self._last_sequence,
                "event_count": self._last_sequence,
                "gap_count": gap_count,
                "dropped_events": self.dropped_events,
                "storage_bytes": self._storage_bytes(),
                "last_error": self.last_error,
            }

    def close(self) -> None:
        with self._lock:
            if self.connection is None:
                return
            connection = self.connection
            if self.status != "quarantine":
                self._safe_append("journal_stopped", event_id=f"stopped:{uuid4().hex}")
                try:
                    self._unregister_writer()
                    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error as error:
                    self.status = "degraded"
                    self.last_error = self._error_reason(error)
            try:
                connection.close()
            finally:
                self.connection = None

    def integrity_after_close(self) -> list[str]:
        connection = sqlite3.connect(self.path)
        try:
            return [row[0] for row in connection.execute("PRAGMA integrity_check")]
        finally:
            connection.close()


def open_response_experience_journal(agent) -> ResponseExperienceJournal | None:
    """Открыть writer только по явному feature flag; default не создаёт файлов."""
    if os.environ.get(RESPONSE_JOURNAL_ENV) != "1":
        return None
    life_id = validate_life_id(agent.life_id)
    path = Path(data_path("lives", life_id, JOURNAL_FILENAME))
    options = {}
    if os.environ.get(RESPONSE_JOURNAL_SEGMENT_ENV) == "1":
        experience = agent.response_experience
        options = {
            "segment_id": os.environ.get(RESPONSE_JOURNAL_SEGMENT_ID_ENV, ""),
            "boundary_cycle": agent.cycle_count,
            "archive_manifest_hash": os.environ.get(
                RESPONSE_JOURNAL_ARCHIVE_HASH_ENV, ""
            ),
            "preexisting": {
                (record["plan"]["state"]["profile_id"], response_id)
                for response_id, record in experience.responses.items()
            },
        }
    try:
        return ResponseExperienceJournal(path, life_id, **options)
    except Exception as error:
        # Optional observer никогда не отменяет создание/остановку жизни.
        return ResponseExperienceJournal.unavailable(path, life_id, error)
