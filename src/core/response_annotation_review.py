"""Ручная разметка ответов только над явной sandbox-копией данных.

Тексты доступны лишь в оперативной памяти окна. В журнал попадают проверенные
человеком метки без текстов, target/work_id и evidence reference IDs. Модуль не
подключается к AgentRunner, не меняет ответы и не запускает обучение.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from src.core.life_identity import validate_life_id
from src.core.response_annotation import (
    AnnotationError,
    AnnotationRevision,
    ResponseAnnotationJournal,
    SELF_INTENTS,
)
from src.core.response_experience_journal import (
    EVENT_KINDS,
    JOURNAL_SCHEMA_VERSION,
    SEGMENT_EXCLUSION,
    SEGMENT_JOURNAL_SCHEMA_VERSION,
    SEGMENT_WRITER_CONTRACT_VERSION,
    WRITER_CONTRACT_VERSION,
    event_hash,
)
from src.core.semantic_response_plan import SemanticResponsePlan

_SUPPORTED_RESPONSE_WRITERS = {
    JOURNAL_SCHEMA_VERSION: WRITER_CONTRACT_VERSION,
    SEGMENT_JOURNAL_SCHEMA_VERSION: SEGMENT_WRITER_CONTRACT_VERSION,
}
_SUPPORTED_RESPONSE_EVENT_KINDS = EVENT_KINDS | {SEGMENT_EXCLUSION}


class ReviewError(RuntimeError):
    """Ожидаемая ошибка sandbox-границы или исходных данных разметки."""


@dataclass(frozen=True)
class ReviewCandidate:
    life_id: str
    profile_id: str
    response_id: str
    episode_id: str
    delivery_sequence: int
    source_delivery_event_hash: str
    input_text: str
    response_text: str
    suggested_intent: str
    suggested_plan: dict | None


@dataclass(frozen=True)
class ReviewCandidateBatch:
    candidates: tuple[ReviewCandidate, ...]
    skipped: dict[str, int]


def _sandbox_path(
    sandbox_root: str | Path,
    value: str | Path,
    *,
    label: str,
    must_exist: bool,
) -> Path:
    try:
        root = Path(sandbox_root).resolve(strict=True)
    except OSError as error:
        raise ReviewError("sandbox root does not exist") from error
    if not root.is_dir():
        raise ReviewError("sandbox root must be a directory")
    try:
        path = Path(value).resolve(strict=must_exist)
        path.relative_to(root)
    except (OSError, ValueError) as error:
        raise ReviewError(f"{label} must stay inside the sandbox") from error
    if path == root:
        raise ReviewError(f"{label} must be a file inside the sandbox")
    return path


def _response_row(row: sqlite3.Row) -> dict:
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


def _read_response_events(path: Path, life_id: str) -> list[dict]:
    """Проверить исходный журнал через SQLite read-only, без writer-событий."""
    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro", uri=True, check_same_thread=False
        )
    except sqlite3.Error as error:
        raise ReviewError("cannot open the response journal read-only") from error
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        if integrity != ["ok"]:
            raise ReviewError("response journal SQLite integrity failed")
        head = connection.execute("SELECT * FROM head WHERE id=1").fetchone()
        if head is None:
            raise ReviewError("response journal head is missing")
        rows = connection.execute("SELECT * FROM events ORDER BY event_sequence")
        previous = "0" * 64
        events = []
        for expected, row in enumerate(rows, 1):
            event = _response_row(row)
            if event["event_sequence"] != expected:
                raise ReviewError("response journal sequence mismatch")
            if event["previous_hash"] != previous:
                raise ReviewError("response journal hash chain mismatch")
            if event["event_hash"] != event_hash(event):
                raise ReviewError("response journal event hash mismatch")
            if event["event_kind"] not in _SUPPORTED_RESPONSE_EVENT_KINDS:
                raise ReviewError("response journal event kind is unsupported")
            writer_contract = _SUPPORTED_RESPONSE_WRITERS.get(
                event["journal_schema_version"]
            )
            if writer_contract is None:
                raise ReviewError("response journal schema is unsupported")
            if event["writer_contract_version"] != writer_contract:
                raise ReviewError("response journal writer contract is unsupported")
            if event["life_id"] != life_id:
                raise ReviewError("response journal life mismatch")
            if event["emission_status"] != "committed":
                raise ReviewError("response journal emission is not committed")
            if not isinstance(event["payload"], dict):
                raise ReviewError("response journal payload is invalid")
            events.append(event)
            previous = event["event_hash"]
        if head["sequence"] != len(events) or head["event_hash"] != previous:
            raise ReviewError("response journal head mismatch")
        return events
    except sqlite3.Error as error:
        raise ReviewError("cannot read the response journal") from error
    finally:
        connection.close()


def _sanitized_plan(semantic: SemanticResponsePlan) -> dict:
    activity = None
    if semantic.activity is not None:
        activity = {
            "status": semantic.activity.status,
            "kind": semantic.activity.kind,
            "started_cycle": semantic.activity.started_cycle,
        }
    completed = None
    if semantic.last_completed_action is not None:
        completed = {
            "kind": semantic.last_completed_action.kind,
            "cycle": semantic.last_completed_action.cycle,
        }
    return {
        "schema_version": semantic.schema_version,
        "language": semantic.language,
        "activity": activity,
        "last_completed_action": completed,
        "energy": semantic.energy,
        "allowed_claims": list(semantic.allowed_claims),
    }


def load_review_candidates(
    snapshot_path: str | Path,
    response_journal_path: str | Path,
    *,
    life_id: str,
) -> ReviewCandidateBatch:
    """Соединить snapshot и delivery без какой-либо записи в исходники."""
    life_id = validate_life_id(life_id)
    try:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReviewError("cannot read the sandbox snapshot") from error
    if not isinstance(snapshot, dict) or snapshot.get("life_id") != life_id:
        raise ReviewError("snapshot life mismatch")
    events = _read_response_events(Path(response_journal_path), life_id)
    deliveries: dict[tuple[str, str], list[dict]] = {}
    for event in events:
        if event["event_kind"] == "delivery":
            key = (event["profile_id"], event["response_id"])
            deliveries.setdefault(key, []).append(event)

    experience = snapshot.get("response_experience")
    records = experience.get("responses") if isinstance(experience, dict) else None
    if not isinstance(records, list):
        raise ReviewError("snapshot response_experience.responses is missing")
    matched_snapshot_keys = set()
    candidates = []
    skipped: Counter[str] = Counter()
    for record in records:
        try:
            if not isinstance(record, dict):
                raise ValueError("response record is not a dictionary")
            response_id = record["response_id"]
            plan = record["plan"]
            profile_id = plan["state"]["profile_id"]
            key = (profile_id, response_id)
            found = deliveries.get(key, [])
            if len(found) != 1:
                skipped["ambiguous_delivery" if found else "missing_delivery"] += 1
                continue
            delivery = found[0]
            input_text = plan["observed_input"]
            response_text = plan["realization"]["base_text"]
            if not isinstance(input_text, str) or not isinstance(response_text, str):
                raise ValueError("response texts must be strings")
            if not input_text.strip():
                skipped["missing_input"] += 1
                matched_snapshot_keys.add(key)
                continue
            semantic_data = plan.get("semantic_response_plan")
            if semantic_data is None:
                suggested_intent = "UNKNOWN_OR_OTHER"
                suggested_plan = None
            else:
                semantic = SemanticResponsePlan.from_dict(semantic_data)
                if (
                    semantic.response_id != response_id
                    or semantic.baseline_text != response_text
                ):
                    raise ValueError("semantic plan provenance mismatch")
                suggested_intent = semantic.intent
                suggested_plan = _sanitized_plan(semantic)
            candidate = ReviewCandidate(
                life_id=life_id,
                profile_id=profile_id,
                response_id=response_id,
                episode_id=delivery["episode_id"],
                delivery_sequence=delivery["event_sequence"],
                source_delivery_event_hash=delivery["event_hash"],
                input_text=input_text,
                response_text=response_text,
                suggested_intent=suggested_intent,
                suggested_plan=suggested_plan,
            )
        except (KeyError, TypeError, ValueError):
            skipped["invalid_snapshot_record"] += 1
            continue
        candidates.append(candidate)
        matched_snapshot_keys.add((candidate.profile_id, candidate.response_id))
    for key in deliveries:
        if key not in matched_snapshot_keys:
            skipped["missing_snapshot"] += 1
    candidates.sort(key=lambda item: item.delivery_sequence)
    return ReviewCandidateBatch(tuple(candidates), dict(sorted(skipped.items())))


def _revision_from_label(event: dict) -> AnnotationRevision:
    return AnnotationRevision.from_dict(
        {
            "annotation_id": event["event_id"],
            "life_id": event["life_id"],
            "profile_id": event["profile_id"],
            "response_id": event["response_id"],
            "episode_id": event["episode_id"],
            "delivery_sequence": event["delivery_sequence"],
            "source_delivery_event_hash": event["source_delivery_event_hash"],
            "revision": event["revision"],
            "supersedes_event_hash": event["supersedes_event_hash"],
            **event["payload"],
        }
    )


class AnnotationReviewSession:
    """Навигация и append-only запись человеческих решений по одной жизни."""

    def __init__(
        self,
        candidates,
        journal: ResponseAnnotationJournal,
        *,
        annotator_id: str = "owner",
    ) -> None:
        self.candidates = tuple(candidates)
        self.journal = journal
        self.annotator_id = annotator_id
        self.position = 0
        self._labels = {}
        for candidate in self.candidates:
            key = (candidate.profile_id, candidate.response_id)
            if candidate.life_id != journal.life_id:
                raise AnnotationError("candidate life mismatch")
            label = self._latest_labels().get(key)
            if label is not None:
                self._labels[key] = label
        unannotated = [
            index
            for index, candidate in enumerate(self.candidates)
            if (candidate.profile_id, candidate.response_id) not in self._labels
        ]
        if unannotated:
            self.position = unannotated[0]

    def _latest_labels(self) -> dict:
        return {
            (event["profile_id"], event["response_id"]): event
            for event in self.journal.labels()
        }

    @property
    def current(self) -> ReviewCandidate:
        if not self.candidates:
            raise AnnotationError("no review candidates")
        return self.candidates[self.position]

    @property
    def current_label(self) -> dict | None:
        current = self.current
        label = self._labels.get((current.profile_id, current.response_id))
        return deepcopy(label)

    def draft(self) -> dict:
        label = self.current_label
        if label is None:
            return {
                "intent": self.current.suggested_intent,
                "intent_review": "confirmed",
                "intent_uncertainties": (),
                "semantic_plan": deepcopy(self.current.suggested_plan),
                "plan_review": (
                    "confirmed"
                    if self.current.suggested_plan is not None
                    else "not_applicable"
                ),
                "plan_uncertainties": (),
            }
        revision = _revision_from_label(label)
        return {
            "intent": revision.intent,
            "intent_review": revision.intent_review,
            "intent_uncertainties": revision.intent_uncertainties,
            "semantic_plan": deepcopy(revision.semantic_plan),
            "plan_review": revision.plan_review,
            "plan_uncertainties": revision.plan_uncertainties,
        }

    def progress(self) -> dict:
        resolved_intent = 0
        resolved_plan = 0
        for label in self._labels.values():
            revision = _revision_from_label(label)
            resolved_intent += int(
                revision.intent_review in {"confirmed", "corrected"}
                and revision.intent is not None
                and not revision.intent_uncertainties
            )
            resolved_plan += int(
                revision.plan_review in {"confirmed", "corrected"}
                and revision.semantic_plan is not None
                and not revision.plan_uncertainties
            )
        annotated = len(self._labels)
        return {
            "total": len(self.candidates),
            "annotated": annotated,
            "resolved_intent": resolved_intent,
            "resolved_plan": resolved_plan,
            "remaining": len(self.candidates) - annotated,
        }

    def go_to(self, index: int) -> None:
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError("candidate index must be an integer")
        if not 0 <= index < len(self.candidates):
            raise IndexError("candidate index out of range")
        self.position = index

    def next(self) -> None:
        if self.position + 1 < len(self.candidates):
            self.position += 1

    def previous(self) -> None:
        if self.position > 0:
            self.position -= 1

    def _record(
        self,
        *,
        intent_review: str,
        intent: str | None,
        intent_uncertainties,
        plan_review: str,
        semantic_plan,
        plan_uncertainties,
    ) -> dict:
        if self.journal.connection is None:
            raise AnnotationError("review session is closed")
        current = self.current
        previous = self.current_label
        revision = 1 if previous is None else previous["revision"] + 1
        annotation = AnnotationRevision(
            annotation_id=f"annotation:{uuid4().hex}",
            life_id=current.life_id,
            profile_id=current.profile_id,
            response_id=current.response_id,
            episode_id=current.episode_id,
            delivery_sequence=current.delivery_sequence,
            source_delivery_event_hash=current.source_delivery_event_hash,
            revision=revision,
            supersedes_event_hash=None if previous is None else previous["event_hash"],
            annotator_id=self.annotator_id,
            intent_review=intent_review,
            intent=intent,
            intent_uncertainties=tuple(intent_uncertainties),
            plan_review=plan_review,
            semantic_plan=deepcopy(semantic_plan),
            plan_uncertainties=tuple(plan_uncertainties),
        )
        event = self.journal.record(annotation)
        self._labels[(current.profile_id, current.response_id)] = deepcopy(event)
        return event

    def confirm_current(self) -> dict:
        draft = self.draft()
        previous = self.current_label
        intent = draft["intent"]
        intent_review = (
            "abstained"
            if intent is None
            else "confirmed"
            if previous is None
            else "corrected"
        )
        plan_review = draft["plan_review"]
        if previous is not None and plan_review == "confirmed":
            plan_review = "corrected"
        return self._record(
            intent_review=intent_review,
            intent=intent,
            intent_uncertainties=draft["intent_uncertainties"],
            plan_review=plan_review,
            semantic_plan=draft["semantic_plan"],
            plan_uncertainties=draft["plan_uncertainties"],
        )

    def correct_current(
        self,
        intent: str,
        *,
        semantic_plan=None,
        intent_uncertainties=(),
        plan_review: str | None = None,
        plan_uncertainties=(),
    ) -> dict:
        if plan_review is None:
            plan_review = "corrected" if intent in SELF_INTENTS else "not_applicable"
        return self._record(
            intent_review="corrected",
            intent=intent,
            intent_uncertainties=intent_uncertainties,
            plan_review=plan_review,
            semantic_plan=semantic_plan,
            plan_uncertainties=plan_uncertainties,
        )

    def abstain_current(self) -> dict:
        return self._record(
            intent_review="abstained",
            intent=None,
            intent_uncertainties=("input_meaning",),
            plan_review="not_applicable",
            semantic_plan=None,
            plan_uncertainties=(),
        )

    def abstain_current_plan(self) -> dict:
        draft = self.draft()
        if draft["intent"] not in SELF_INTENTS:
            raise AnnotationError("plan abstention requires a resolved self intent")
        return self._record(
            intent_review="corrected",
            intent=draft["intent"],
            intent_uncertainties=draft["intent_uncertainties"],
            plan_review="abstained",
            semantic_plan=None,
            plan_uncertainties=("plan_facts",),
        )

    def close(self) -> None:
        self.journal.close()


def open_review_session(
    *,
    sandbox_root: str | Path,
    snapshot_path: str | Path,
    response_journal_path: str | Path,
    annotation_journal_path: str | Path,
    life_id: str,
    annotator_id: str = "owner",
) -> AnnotationReviewSession:
    """Открыть только явные sandbox-пути; исходники проверяются до записи."""
    life_id = validate_life_id(life_id)
    snapshot = _sandbox_path(
        sandbox_root, snapshot_path, label="snapshot", must_exist=True
    )
    responses = _sandbox_path(
        sandbox_root, response_journal_path, label="response journal", must_exist=True
    )
    annotations = _sandbox_path(
        sandbox_root,
        annotation_journal_path,
        label="annotation journal",
        must_exist=False,
    )
    batch = load_review_candidates(snapshot, responses, life_id=life_id)
    journal = ResponseAnnotationJournal(annotations, life_id)
    return AnnotationReviewSession(batch.candidates, journal, annotator_id=annotator_id)
