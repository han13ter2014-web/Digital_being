"""Независимая человеческая разметка смысловых ответов для R2-PREP.

Модуль содержит только DTO, append-only per-life журнал и read-only projection.
Он не создаёт ответы, не обучает модель и не подключается к жизненному циклу.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading

from src.core.life_identity import validate_life_id
from src.core.response_shadow_inventory import (
    assess_readiness,
    inventory_events,
    temporal_split,
)

SCHEMA_VERSION = 1
JOURNAL_SCHEMA_VERSION = 1
ANNOTATION_CONTRACT_VERSION = "human_semantic_annotation_v1"
ANNOTATION_INTENTS = frozenset(
    {"ASK_SELF_STATE", "ASK_SELF_ACTIVITY", "UNKNOWN_OR_OTHER"}
)
SELF_INTENTS = frozenset({"ASK_SELF_STATE", "ASK_SELF_ACTIVITY"})
INTENT_REVIEWS = frozenset({"confirmed", "corrected", "abstained"})
PLAN_REVIEWS = frozenset({"confirmed", "corrected", "abstained", "not_applicable"})
UNCERTAINTIES = frozenset(
    {
        "input_meaning",
        "source_provenance",
        "state_facts",
        "activity_facts",
        "plan_facts",
    }
)
LANGUAGES = frozenset({"ru", "en", "zh"})
BUSY_TIMEOUT_MS = 250
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_CLAIM = re.compile(r"[a-z_]+(?:\.[a-z_]+)*(?::[a-z_]+)?\Z")
_PLAN_FIELDS = frozenset(
    {
        "schema_version",
        "language",
        "activity",
        "last_completed_action",
        "energy",
        "allowed_claims",
    }
)


class AnnotationError(RuntimeError):
    """Ожидаемая ошибка записи или целостности журнала разметки."""


class AnnotationCorruption(AnnotationError):
    """Сохранённая история не прошла проверку целостности."""


def _canonical(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _event_hash(event: dict) -> str:
    material = {key: value for key, value in event.items() if key != "event_hash"}
    return hashlib.sha256(_canonical(material).encode("utf-8")).hexdigest()


def _text(value, path: str, limit: int = 160) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{path}: expected a bounded nonempty string")


def _sequence(value, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{path}: expected an integer >= 1")


def _cycle(value, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{path}: expected a nonnegative integer")


def _valid_hash(value) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _uncertainties(value, path: str) -> None:
    if not isinstance(value, tuple) or len(value) > len(UNCERTAINTIES):
        raise ValueError(f"{path}: expected a bounded tuple")
    if len(set(value)) != len(value) or any(
        item not in UNCERTAINTIES for item in value
    ):
        raise ValueError(f"{path}: unsupported or duplicate uncertainty")


def _validate_plan(plan, intent: str) -> None:
    if not isinstance(plan, dict):
        raise ValueError("semantic_plan: expected a dictionary")
    unknown = set(plan) - _PLAN_FIELDS
    if unknown:
        raise ValueError(f"semantic_plan: unknown fields {sorted(unknown)}")
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("semantic_plan.schema_version: unsupported")
    if plan.get("language") not in LANGUAGES:
        raise ValueError("semantic_plan.language: unsupported")

    activity = plan.get("activity")
    if intent == "ASK_SELF_STATE" and activity is not None:
        raise ValueError("semantic_plan.activity: not allowed for ASK_SELF_STATE")
    if intent == "ASK_SELF_ACTIVITY" and activity is None:
        raise ValueError("semantic_plan.activity: required for ASK_SELF_ACTIVITY")
    if activity is not None:
        if not isinstance(activity, dict) or set(activity) != {
            "status",
            "kind",
            "started_cycle",
        }:
            raise ValueError("semantic_plan.activity: invalid fields")
        if activity.get("status") not in {"current", "none"}:
            raise ValueError("semantic_plan.activity.status: unsupported")
        if activity["status"] == "none":
            if (
                activity.get("kind") is not None
                or activity.get("started_cycle") is not None
            ):
                raise ValueError(
                    "semantic_plan.activity: none cannot carry action facts"
                )
        else:
            _text(activity.get("kind"), "semantic_plan.activity.kind")
            _cycle(
                activity.get("started_cycle"), "semantic_plan.activity.started_cycle"
            )

    completed = plan.get("last_completed_action")
    if completed is not None:
        if not isinstance(completed, dict) or set(completed) != {"kind", "cycle"}:
            raise ValueError("semantic_plan.last_completed_action: invalid fields")
        _text(completed.get("kind"), "semantic_plan.last_completed_action.kind")
        _cycle(completed.get("cycle"), "semantic_plan.last_completed_action.cycle")

    energy = plan.get("energy")
    if energy is not None and (
        isinstance(energy, bool)
        or not isinstance(energy, (int, float))
        or not math.isfinite(energy)
        or energy < 0
    ):
        raise ValueError("semantic_plan.energy: expected a finite nonnegative number")
    claims = plan.get("allowed_claims")
    if not isinstance(claims, (list, tuple)) or len(claims) > 16:
        raise ValueError("semantic_plan.allowed_claims: expected a bounded sequence")
    if len(set(claims)) != len(claims):
        raise ValueError("semantic_plan.allowed_claims: duplicates")
    for claim in claims:
        if not isinstance(claim, str) or not _CLAIM.fullmatch(claim):
            raise ValueError("semantic_plan.allowed_claims: invalid machine claim")


@dataclass(frozen=True)
class AnnotationRevision:
    annotation_id: str
    life_id: str
    profile_id: str
    response_id: str
    episode_id: str
    delivery_sequence: int
    source_delivery_event_hash: str
    revision: int
    annotator_id: str
    intent_review: str
    intent: str | None
    plan_review: str
    supersedes_event_hash: str | None = None
    label_source: str = "human_review"
    intent_uncertainties: tuple[str, ...] = ()
    semantic_plan: dict | None = None
    plan_uncertainties: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("schema_version: unsupported")
        validate_life_id(self.life_id)
        for field, value, limit in (
            ("annotation_id", self.annotation_id, 160),
            ("profile_id", self.profile_id, 160),
            ("response_id", self.response_id, 160),
            ("episode_id", self.episode_id, 160),
            ("annotator_id", self.annotator_id, 80),
        ):
            _text(value, field, limit)
        _sequence(self.delivery_sequence, "delivery_sequence")
        _sequence(self.revision, "revision")
        if not _valid_hash(self.source_delivery_event_hash):
            raise ValueError("source_delivery_event_hash: expected SHA-256 hex")
        if self.revision == 1:
            if self.supersedes_event_hash is not None:
                raise ValueError("supersedes_event_hash: not allowed for revision 1")
        elif not _valid_hash(self.supersedes_event_hash):
            raise ValueError("supersedes_event_hash: required after revision 1")
        if self.label_source != "human_review":
            raise ValueError("label_source: independent human_review is required")
        if self.intent_review not in INTENT_REVIEWS:
            raise ValueError("intent_review: unsupported")
        if self.plan_review not in PLAN_REVIEWS:
            raise ValueError("plan_review: unsupported")
        _uncertainties(self.intent_uncertainties, "intent_uncertainties")
        _uncertainties(self.plan_uncertainties, "plan_uncertainties")

        if self.intent_review == "abstained":
            if self.intent is not None or not self.intent_uncertainties:
                raise ValueError("intent abstention requires None and uncertainty")
            if self.plan_review != "not_applicable" or self.semantic_plan is not None:
                raise ValueError("intent abstention requires not_applicable plan")
        elif self.intent not in ANNOTATION_INTENTS:
            raise ValueError("intent: unsupported for a non-abstained revision")

        if self.intent in SELF_INTENTS:
            if self.plan_review == "not_applicable":
                raise ValueError("plan_review: self intents require plan review")
            if self.plan_review == "abstained":
                if self.semantic_plan is not None or not self.plan_uncertainties:
                    raise ValueError("plan abstention requires None and uncertainty")
            else:
                _validate_plan(self.semantic_plan, self.intent)
        else:
            if self.plan_review != "not_applicable" or self.semantic_plan is not None:
                raise ValueError(
                    "UNKNOWN_OR_OTHER requires not_applicable semantic_plan"
                )
            if self.plan_uncertainties:
                raise ValueError("plan_uncertainties: not allowed without a plan")

        object.__setattr__(self, "semantic_plan", deepcopy(self.semantic_plan))

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "annotation_id": self.annotation_id,
            "life_id": self.life_id,
            "profile_id": self.profile_id,
            "response_id": self.response_id,
            "episode_id": self.episode_id,
            "delivery_sequence": self.delivery_sequence,
            "source_delivery_event_hash": self.source_delivery_event_hash,
            "revision": self.revision,
            "supersedes_event_hash": self.supersedes_event_hash,
            "annotator_id": self.annotator_id,
            "label_source": self.label_source,
            "intent_review": self.intent_review,
            "intent": self.intent,
            "intent_uncertainties": list(self.intent_uncertainties),
            "plan_review": self.plan_review,
            "semantic_plan": deepcopy(self.semantic_plan),
            "plan_uncertainties": list(self.plan_uncertainties),
        }

    @classmethod
    def from_dict(cls, data: dict) -> AnnotationRevision:
        if not isinstance(data, dict):
            raise ValueError("annotation_revision: expected a dictionary")
        fields = set(cls.__dataclass_fields__)
        unknown = set(data) - fields
        if unknown:
            raise ValueError(f"annotation_revision: unknown fields {sorted(unknown)}")
        intent_uncertainties = data.get("intent_uncertainties", [])
        plan_uncertainties = data.get("plan_uncertainties", [])
        if not isinstance(intent_uncertainties, list) or not isinstance(
            plan_uncertainties, list
        ):
            raise ValueError("annotation_revision: uncertainties must be lists")
        try:
            return cls(
                schema_version=data.get("schema_version"),
                annotation_id=data.get("annotation_id"),
                life_id=data.get("life_id"),
                profile_id=data.get("profile_id"),
                response_id=data.get("response_id"),
                episode_id=data.get("episode_id"),
                delivery_sequence=data.get("delivery_sequence"),
                source_delivery_event_hash=data.get("source_delivery_event_hash"),
                revision=data.get("revision"),
                supersedes_event_hash=data.get("supersedes_event_hash"),
                annotator_id=data.get("annotator_id"),
                label_source=data.get("label_source"),
                intent_review=data.get("intent_review"),
                intent=data.get("intent"),
                intent_uncertainties=tuple(intent_uncertainties),
                plan_review=data.get("plan_review"),
                semantic_plan=deepcopy(data.get("semantic_plan")),
                plan_uncertainties=tuple(plan_uncertainties),
            )
        except TypeError as error:
            raise ValueError(f"annotation_revision: invalid data: {error}") from error


def _payload(revision: AnnotationRevision) -> dict:
    data = revision.to_dict()
    return {
        key: deepcopy(data[key])
        for key in (
            "schema_version",
            "annotator_id",
            "label_source",
            "intent_review",
            "intent",
            "intent_uncertainties",
            "plan_review",
            "semantic_plan",
            "plan_uncertainties",
        )
    }


def _revision_from_event(event: dict) -> AnnotationRevision:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("annotation event: missing payload")
    return AnnotationRevision(
        annotation_id=event.get("event_id"),
        life_id=event.get("life_id"),
        profile_id=event.get("profile_id"),
        response_id=event.get("response_id"),
        episode_id=event.get("episode_id"),
        delivery_sequence=event.get("delivery_sequence"),
        source_delivery_event_hash=event.get("source_delivery_event_hash"),
        revision=event.get("revision"),
        supersedes_event_hash=event.get("supersedes_event_hash"),
        annotator_id=payload.get("annotator_id"),
        label_source=payload.get("label_source"),
        intent_review=payload.get("intent_review"),
        intent=payload.get("intent"),
        intent_uncertainties=tuple(payload.get("intent_uncertainties", ())),
        plan_review=payload.get("plan_review"),
        semantic_plan=deepcopy(payload.get("semantic_plan")),
        plan_uncertainties=tuple(payload.get("plan_uncertainties", ())),
        schema_version=payload.get("schema_version"),
    )


def _same_source(left: dict, right: AnnotationRevision) -> bool:
    return all(
        left[field] == value
        for field, value in (
            ("episode_id", right.episode_id),
            ("delivery_sequence", right.delivery_sequence),
            ("source_delivery_event_hash", right.source_delivery_event_hash),
        )
    )


class ResponseAnnotationJournal:
    """Синхронный append-only SQLite без активных runtime-подключений."""

    def __init__(self, path: str | Path, life_id: str) -> None:
        self.life_id = validate_life_id(life_id)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        fresh = not self.path.exists()
        self.connection = sqlite3.connect(
            self.path,
            timeout=BUSY_TIMEOUT_MS / 1000,
            check_same_thread=False,
            isolation_level=None,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._schema()
        if fresh:
            self.connection.execute(
                "INSERT INTO head(id, sequence, event_hash) VALUES(1, 0, ?)",
                ("0" * 64,),
            )
        else:
            self._verify()

    def _schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS head(
                id INTEGER PRIMARY KEY CHECK(id=1),
                sequence INTEGER NOT NULL,
                event_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events(
                event_id TEXT PRIMARY KEY,
                event_sequence INTEGER UNIQUE NOT NULL,
                event_kind TEXT NOT NULL,
                journal_schema_version INTEGER NOT NULL,
                annotation_contract_version TEXT NOT NULL,
                life_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                response_id TEXT NOT NULL,
                episode_id TEXT NOT NULL,
                delivery_sequence INTEGER NOT NULL,
                source_delivery_event_hash TEXT NOT NULL,
                revision INTEGER NOT NULL,
                supersedes_event_hash TEXT,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS annotations_response
                ON events(life_id, profile_id, response_id, event_sequence);
            CREATE TRIGGER IF NOT EXISTS events_append_only_update
                BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT, 'events_append_only'); END;
            CREATE TRIGGER IF NOT EXISTS events_append_only_delete
                BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT, 'events_append_only'); END;
            """
        )

    def _head(self):
        row = self.connection.execute("SELECT * FROM head WHERE id=1").fetchone()
        if row is None:
            raise AnnotationCorruption("missing_head")
        return row

    @staticmethod
    def _row_event(row) -> dict:
        return {
            "event_id": row["event_id"],
            "event_sequence": row["event_sequence"],
            "event_kind": row["event_kind"],
            "journal_schema_version": row["journal_schema_version"],
            "annotation_contract_version": row["annotation_contract_version"],
            "life_id": row["life_id"],
            "profile_id": row["profile_id"],
            "response_id": row["response_id"],
            "episode_id": row["episode_id"],
            "delivery_sequence": row["delivery_sequence"],
            "source_delivery_event_hash": row["source_delivery_event_hash"],
            "revision": row["revision"],
            "supersedes_event_hash": row["supersedes_event_hash"],
            "previous_hash": row["previous_hash"],
            "event_hash": row["event_hash"],
            "payload": json.loads(row["payload"]),
        }

    @staticmethod
    def _check_revision(previous: dict | None, revision: AnnotationRevision) -> None:
        if previous is None:
            if revision.revision != 1:
                raise AnnotationError("revision must start at 1")
            return
        if revision.revision != previous["revision"] + 1:
            raise AnnotationError("revision must immediately follow the current head")
        if revision.supersedes_event_hash != previous["event_hash"]:
            raise AnnotationError("supersedes_event_hash does not match current head")
        if not _same_source(previous, revision):
            raise AnnotationError("revision cannot rewrite delivery provenance")

    def _verify(self) -> None:
        try:
            integrity = [
                row[0] for row in self.connection.execute("PRAGMA integrity_check")
            ]
            if integrity != ["ok"]:
                raise AnnotationCorruption("sqlite_integrity")
            rows = self.connection.execute(
                "SELECT * FROM events ORDER BY event_sequence"
            ).fetchall()
            previous_hash = "0" * 64
            heads = {}
            for expected, row in enumerate(rows, 1):
                event = self._row_event(row)
                if event["event_sequence"] != expected:
                    raise AnnotationCorruption("sequence_mismatch")
                if event["previous_hash"] != previous_hash:
                    raise AnnotationCorruption("hash_chain_mismatch")
                if event["event_hash"] != _event_hash(event):
                    raise AnnotationCorruption("event_hash_mismatch")
                if event["event_kind"] != "annotation":
                    raise AnnotationCorruption("unknown_event_kind")
                if event["journal_schema_version"] != JOURNAL_SCHEMA_VERSION:
                    raise AnnotationCorruption("unsupported_journal_schema")
                if event["annotation_contract_version"] != ANNOTATION_CONTRACT_VERSION:
                    raise AnnotationCorruption("unsupported_annotation_contract")
                if event["life_id"] != self.life_id:
                    raise AnnotationCorruption("life_mismatch")
                revision = _revision_from_event(event)
                key = (event["profile_id"], event["response_id"])
                self._check_revision(heads.get(key), revision)
                heads[key] = event
                previous_hash = event["event_hash"]
            head = self._head()
            if head["sequence"] != len(rows) or head["event_hash"] != previous_hash:
                raise AnnotationCorruption("head_mismatch")
        except AnnotationCorruption:
            raise
        except (AnnotationError, ValueError, TypeError, sqlite3.Error) as error:
            raise AnnotationCorruption(str(error)) from error

    def record(self, revision: AnnotationRevision) -> dict:
        if not isinstance(revision, AnnotationRevision):
            raise AnnotationError("expected AnnotationRevision")
        if revision.life_id != self.life_id:
            raise AnnotationError("annotation life mismatch")
        with self._lock:
            if self.connection is None:
                raise AnnotationError("journal_closed")
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                existing = self.connection.execute(
                    "SELECT * FROM events WHERE event_id=?", (revision.annotation_id,)
                ).fetchone()
                if existing is not None:
                    event = self._row_event(existing)
                    if _revision_from_event(event) != revision:
                        raise AnnotationError("annotation_id conflict")
                    self.connection.execute("COMMIT")
                    return deepcopy(event)

                previous_row = self.connection.execute(
                    "SELECT * FROM events WHERE life_id=? AND profile_id=?"
                    " AND response_id=? ORDER BY event_sequence DESC LIMIT 1",
                    (self.life_id, revision.profile_id, revision.response_id),
                ).fetchone()
                previous = self._row_event(previous_row) if previous_row else None
                self._check_revision(previous, revision)
                head = self._head()
                event = {
                    "event_id": revision.annotation_id,
                    "event_sequence": head["sequence"] + 1,
                    "event_kind": "annotation",
                    "journal_schema_version": JOURNAL_SCHEMA_VERSION,
                    "annotation_contract_version": ANNOTATION_CONTRACT_VERSION,
                    "life_id": self.life_id,
                    "profile_id": revision.profile_id,
                    "response_id": revision.response_id,
                    "episode_id": revision.episode_id,
                    "delivery_sequence": revision.delivery_sequence,
                    "source_delivery_event_hash": revision.source_delivery_event_hash,
                    "revision": revision.revision,
                    "supersedes_event_hash": revision.supersedes_event_hash,
                    "previous_hash": head["event_hash"],
                    "payload": _payload(revision),
                }
                event["event_hash"] = _event_hash(event)
                self.connection.execute(
                    "INSERT INTO events(event_id, event_sequence, event_kind,"
                    " journal_schema_version, annotation_contract_version, life_id,"
                    " profile_id, response_id, episode_id, delivery_sequence,"
                    " source_delivery_event_hash, revision, supersedes_event_hash,"
                    " previous_hash, event_hash, payload)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        event["event_id"],
                        event["event_sequence"],
                        event["event_kind"],
                        event["journal_schema_version"],
                        event["annotation_contract_version"],
                        event["life_id"],
                        event["profile_id"],
                        event["response_id"],
                        event["episode_id"],
                        event["delivery_sequence"],
                        event["source_delivery_event_hash"],
                        event["revision"],
                        event["supersedes_event_hash"],
                        event["previous_hash"],
                        event["event_hash"],
                        _canonical(event["payload"]),
                    ),
                )
                self.connection.execute(
                    "UPDATE head SET sequence=?, event_hash=? WHERE id=1",
                    (event["event_sequence"], event["event_hash"]),
                )
                self.connection.execute("COMMIT")
                return deepcopy(event)
            except Exception as error:
                try:
                    self.connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                if isinstance(error, AnnotationError):
                    raise
                raise AnnotationError(type(error).__name__) from error

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

    def labels(self, *, annotation_before_sequence: int | None = None) -> list[dict]:
        if annotation_before_sequence is not None:
            _sequence(annotation_before_sequence, "annotation_before_sequence")
        latest = {}
        for event in self.events():
            if (
                annotation_before_sequence is not None
                and event["event_sequence"] >= annotation_before_sequence
            ):
                continue
            key = (event["profile_id"], event["response_id"])
            latest[key] = event
        return sorted(
            (deepcopy(event) for event in latest.values()),
            key=lambda event: (
                event["delivery_sequence"],
                event["event_sequence"],
                event["response_id"],
            ),
        )

    def close(self) -> None:
        with self._lock:
            if self.connection is None:
                return
            connection = self.connection
            try:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                connection.close()
                self.connection = None


def _annotation_events(events, life_id: str) -> list[dict]:
    if not isinstance(events, (list, tuple)):
        raise ValueError("annotation_events: expected a sequence")
    result = []
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("annotation event: expected a dictionary")
        if event.get("life_id") != life_id:
            raise ValueError("annotation projection cannot cross lives")
        result.append(event)
    return sorted(result, key=lambda event: event.get("event_sequence", -1))


def _delivery_groups(response_events) -> dict:
    groups = {}
    for event in response_events:
        if event.get("event_kind") != "delivery":
            continue
        key = (event.get("profile_id"), event.get("response_id"))
        groups.setdefault(key, []).append(event)
    return groups


def _matching_delivery(groups: dict, event: dict):
    key = (event.get("profile_id"), event.get("response_id"))
    deliveries = groups.get(key, [])
    if len(deliveries) != 1:
        return None
    delivery = deliveries[0]
    revision = _revision_from_event(event)
    if (
        delivery.get("episode_id") != revision.episode_id
        or delivery.get("event_sequence") != revision.delivery_sequence
        or delivery.get("event_hash") != revision.source_delivery_event_hash
    ):
        return None
    return delivery


def _valid_annotation_chains(events: list[dict]) -> set[int]:
    valid = set()
    heads = {}
    invalid_keys = set()
    for event in events:
        key = (event.get("profile_id"), event.get("response_id"))
        try:
            _sequence(event.get("event_sequence"), "event_sequence")
            if event.get("event_kind") != "annotation":
                raise ValueError("unsupported annotation event")
            revision = _revision_from_event(event)
            previous = heads.get(key)
            ResponseAnnotationJournal._check_revision(previous, revision)
            if previous is not None and not _same_source(previous, revision):
                raise ValueError("revision provenance changed")
            heads[key] = event
            valid.add(id(event))
        except (AnnotationError, ValueError, TypeError):
            invalid_keys.add(key)
    return {
        id(event)
        for event in events
        if id(event) in valid
        and (event.get("profile_id"), event.get("response_id")) not in invalid_keys
    }


def _empty_coverage() -> dict:
    return {
        "deliveries": 0,
        "annotated": 0,
        "unannotated_deliveries": 0,
        "resolved_intent_labels": 0,
        "resolved_semantic_plan_labels": 0,
        "uncertain_intent_labels": 0,
        "uncertain_semantic_plan_labels": 0,
        "intent_abstentions": 0,
        "plan_abstentions": 0,
        "intent_class_counts": {name: 0 for name in sorted(ANNOTATION_INTENTS)},
        "provenance_gaps": 0,
        "late_revisions_excluded": 0,
    }


def _sample(event: dict, delivery: dict) -> dict:
    revision = _revision_from_event(event)
    eligible_intent = (
        revision.intent_review in {"confirmed", "corrected"}
        and revision.intent is not None
        and not revision.intent_uncertainties
    )
    eligible_plan = (
        revision.plan_review in {"confirmed", "corrected"}
        and revision.semantic_plan is not None
        and not revision.plan_uncertainties
    )
    return {
        "life_id": revision.life_id,
        "profile_id": revision.profile_id,
        "response_id": revision.response_id,
        "episode_id": revision.episode_id,
        "delivery_sequence": delivery["event_sequence"],
        "source_delivery_event_hash": revision.source_delivery_event_hash,
        "annotation_sequence": event["event_sequence"],
        "annotation_event_hash": event["event_hash"],
        "revision": revision.revision,
        "intent_review": revision.intent_review,
        "intent": revision.intent,
        "intent_uncertainties": list(revision.intent_uncertainties),
        "plan_review": revision.plan_review,
        "semantic_plan": deepcopy(revision.semantic_plan),
        "plan_uncertainties": list(revision.plan_uncertainties),
        "eligible_intent": eligible_intent,
        "eligible_semantic_plan": eligible_plan,
    }


def _update_coverage(coverage: dict, sample: dict) -> None:
    coverage["annotated"] += 1
    coverage["resolved_intent_labels"] += int(sample["eligible_intent"])
    coverage["resolved_semantic_plan_labels"] += int(sample["eligible_semantic_plan"])
    coverage["uncertain_intent_labels"] += int(
        sample["intent_review"] in {"confirmed", "corrected"}
        and bool(sample["intent_uncertainties"])
    )
    coverage["uncertain_semantic_plan_labels"] += int(
        sample["plan_review"] in {"confirmed", "corrected"}
        and bool(sample["plan_uncertainties"])
    )
    coverage["intent_abstentions"] += int(sample["intent_review"] == "abstained")
    coverage["plan_abstentions"] += int(sample["plan_review"] == "abstained")
    if sample["eligible_intent"]:
        coverage["intent_class_counts"][sample["intent"]] += 1


def _total_coverage(partitions: dict, orphan_gaps: int) -> dict:
    total = _empty_coverage()
    for coverage in partitions.values():
        for key, value in coverage.items():
            if key == "intent_class_counts":
                for intent, count in value.items():
                    total[key][intent] += count
            else:
                total[key] += value
    total["provenance_gaps"] += orphan_gaps
    total["unannotated_deliveries"] = total["deliveries"] - total["annotated"]
    return total


def prepare_r2_dataset(response_events, annotation_events, *, life_id: str) -> dict:
    """Соединить delivery и человеческие метки без записи или обучения."""
    validate_life_id(life_id)
    inventory = inventory_events(response_events, life_id=life_id)
    base_split = temporal_split(response_events, life_id=life_id)
    annotations = _annotation_events(annotation_events, life_id)
    groups = _delivery_groups(response_events)
    valid_chains = _valid_annotation_chains(annotations)
    partitions = ("train", "validation", "held_out")
    episode_partitions = {
        episode: partition
        for partition in partitions
        for episode in base_split[partition]
    }
    next_sequence = (
        max((event.get("event_sequence", 0) for event in annotations), default=0) + 1
    )
    matched = []
    invalid_gaps = Counter()
    orphan_gaps = 0
    for event in annotations:
        partition = episode_partitions.get(event.get("episode_id"))
        if id(event) not in valid_chains:
            if partition is None:
                orphan_gaps += 1
            else:
                invalid_gaps[partition] += 1
            continue
        delivery = _matching_delivery(groups, event)
        if delivery is None or partition is None:
            if partition is None:
                orphan_gaps += 1
            else:
                invalid_gaps[partition] += 1
            continue
        matched.append((event, delivery, partition))

    later = [
        event["event_sequence"]
        for event, _, partition in matched
        if partition in {"validation", "held_out"}
    ]
    held_out_annotations = [
        event["event_sequence"]
        for event, _, partition in matched
        if partition == "held_out"
    ]
    cutoffs = {
        "train": min(later, default=next_sequence),
        "validation": min(held_out_annotations, default=next_sequence),
        "held_out": next_sequence,
    }
    split = {
        **base_split,
        "train_annotation_before_sequence": cutoffs["train"],
        "validation_annotation_before_sequence": cutoffs["validation"],
        "held_out_annotation_before_sequence": cutoffs["held_out"],
    }

    samples = {}
    coverage = {}
    for partition in partitions:
        partition_deliveries = [
            event
            for event in response_events
            if event.get("event_kind") == "delivery"
            and event.get("episode_id") in set(base_split[partition])
        ]
        candidates = [item for item in matched if item[2] == partition]
        latest = {}
        for event, delivery, _ in candidates:
            if event["event_sequence"] < cutoffs[partition]:
                key = (event["profile_id"], event["response_id"])
                latest[key] = (event, delivery)
        partition_samples = [
            _sample(event, delivery)
            for event, delivery in sorted(
                latest.values(), key=lambda item: item[0]["event_sequence"]
            )
        ]
        partition_samples.sort(key=lambda item: item["delivery_sequence"])
        partition_coverage = _empty_coverage()
        partition_coverage["deliveries"] = len(partition_deliveries)
        partition_coverage["provenance_gaps"] = invalid_gaps[partition]
        partition_coverage["late_revisions_excluded"] = sum(
            event["event_sequence"] >= cutoffs[partition] for event, _, _ in candidates
        )
        for sample in partition_samples:
            _update_coverage(partition_coverage, sample)
        partition_coverage["unannotated_deliveries"] = len(partition_deliveries) - len(
            partition_samples
        )
        samples[partition] = partition_samples
        coverage[partition] = partition_coverage

    total = _total_coverage(coverage, orphan_gaps)
    readiness = assess_readiness(
        inventory,
        base_split,
        response_events,
        life_id=life_id,
        confirmed_intent_labels=total["resolved_intent_labels"],
        semantic_plan_labels=total["resolved_semantic_plan_labels"],
    )
    missing = readiness["missing"]

    def add_missing(reason: str) -> None:
        if reason not in missing:
            missing.append(reason)

    if total["provenance_gaps"]:
        add_missing("annotation_provenance")
    if any(
        coverage[partition]["resolved_intent_labels"] == 0 for partition in partitions
    ):
        add_missing("intent_temporal_coverage")
    if any(
        coverage[partition]["resolved_semantic_plan_labels"] == 0
        for partition in partitions
    ):
        add_missing("semantic_plan_temporal_coverage")
    if any(count == 0 for count in coverage["train"]["intent_class_counts"].values()):
        add_missing("intent_class_coverage")
    readiness["status"] = "insufficient_data" if missing else "ready_for_r2_review"
    readiness["training_allowed"] = not missing
    readiness["annotation_coverage"] = deepcopy(total)
    return {
        "life_id": life_id,
        "split": split,
        "samples": samples,
        "coverage": {"total": total, **coverage},
        "readiness": readiness,
    }
