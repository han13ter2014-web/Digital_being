"""Неизменяемый смысловой план для узких ответов о состоянии и занятии.

R1 только фиксирует проверенные факты и уже построенный baseline-текст. Модуль
не выбирает действия, не создаёт работы и не подключается к доставке ответов.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re

SCHEMA_VERSION = 1
INTENTS = frozenset({"ASK_SELF_STATE", "ASK_SELF_ACTIVITY"})
LANGUAGES = frozenset({"ru", "en", "zh"})
_EVIDENCE_KINDS = frozenset({"intention", "state"})
_CLAIM = re.compile(r"[a-z_]+(?:\.[a-z_]+)*(?::[a-z_]+)?\Z")


@dataclass(frozen=True)
class EvidenceRef:
    kind: str
    id: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "id": self.id}


@dataclass(frozen=True)
class ActivityFact:
    status: str
    kind: str | None = None
    work_id: str | None = None
    started_cycle: int | None = None
    target: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "kind": self.kind,
            "work_id": self.work_id,
            "started_cycle": self.started_cycle,
            "target": self.target,
        }


@dataclass(frozen=True)
class CompletedActionFact:
    kind: str
    cycle: int
    target: str | None = None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "cycle": self.cycle, "target": self.target}


def _text(value, path: str, limit: int = 160) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{path}: expected a bounded nonempty string")


def _optional_text(value, path: str, limit: int = 500) -> None:
    if value is not None:
        _text(value, path, limit)


def _cycle(value, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{path}: expected a nonnegative integer")


@dataclass(frozen=True)
class SemanticResponsePlan:
    response_id: str
    cycle: int
    language: str
    intent: str
    activity: ActivityFact | None
    last_completed_action: CompletedActionFact | None
    energy: float | None
    evidence_refs: tuple[EvidenceRef, ...]
    allowed_claims: tuple[str, ...]
    baseline_text: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _text(self.response_id, "response_id")
        _cycle(self.cycle, "cycle")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("schema_version: unsupported")
        if self.language not in LANGUAGES:
            raise ValueError("language: unsupported")
        if self.intent not in INTENTS:
            raise ValueError("intent: unsupported")
        _text(self.baseline_text, "baseline_text", 4000)
        if self.intent == "ASK_SELF_ACTIVITY" and self.activity is None:
            raise ValueError("activity: required for ASK_SELF_ACTIVITY")
        if self.intent == "ASK_SELF_STATE" and self.activity is not None:
            raise ValueError("activity: not allowed for ASK_SELF_STATE")
        if self.activity is not None:
            self._validate_activity(self.activity)
        if self.last_completed_action is not None:
            completed = self.last_completed_action
            _text(completed.kind, "last_completed_action.kind")
            _cycle(completed.cycle, "last_completed_action.cycle")
            _optional_text(completed.target, "last_completed_action.target")
        if self.energy is not None and (
            isinstance(self.energy, bool)
            or not isinstance(self.energy, (int, float))
            or not math.isfinite(self.energy)
            or self.energy < 0
        ):
            raise ValueError("energy: expected a finite nonnegative number or None")
        if not isinstance(self.evidence_refs, tuple) or len(self.evidence_refs) > 8:
            raise ValueError("evidence_refs: expected a bounded tuple")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence_refs: duplicates")
        for reference in self.evidence_refs:
            if reference.kind not in _EVIDENCE_KINDS:
                raise ValueError("evidence_refs.kind: unsupported")
            _text(reference.id, "evidence_refs.id")
        if not isinstance(self.allowed_claims, tuple) or len(self.allowed_claims) > 16:
            raise ValueError("allowed_claims: expected a bounded tuple")
        if len(set(self.allowed_claims)) != len(self.allowed_claims):
            raise ValueError("allowed_claims: duplicates")
        for claim in self.allowed_claims:
            if not isinstance(claim, str) or not _CLAIM.fullmatch(claim):
                raise ValueError("allowed_claims: expected machine-readable claims")

    @staticmethod
    def _validate_activity(activity: ActivityFact) -> None:
        if activity.status not in {"current", "none"}:
            raise ValueError("activity.status: unsupported")
        if activity.status == "none":
            if any(
                value is not None
                for value in (
                    activity.kind,
                    activity.work_id,
                    activity.started_cycle,
                    activity.target,
                )
            ):
                raise ValueError("activity: none cannot carry action facts")
            return
        _text(activity.kind, "activity.kind")
        if activity.started_cycle is None:
            raise ValueError("activity.started_cycle: required for current activity")
        _cycle(activity.started_cycle, "activity.started_cycle")
        _optional_text(activity.work_id, "activity.work_id")
        _optional_text(activity.target, "activity.target")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "response_id": self.response_id,
            "cycle": self.cycle,
            "language": self.language,
            "intent": self.intent,
            "activity": self.activity.to_dict() if self.activity else None,
            "last_completed_action": (
                self.last_completed_action.to_dict()
                if self.last_completed_action
                else None
            ),
            "energy": self.energy,
            "evidence_refs": [item.to_dict() for item in self.evidence_refs],
            "allowed_claims": list(self.allowed_claims),
            "baseline_text": self.baseline_text,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SemanticResponsePlan:
        if not isinstance(data, dict):
            raise ValueError("semantic_response_plan: expected a dictionary")
        fields = {
            "schema_version",
            "response_id",
            "cycle",
            "language",
            "intent",
            "activity",
            "last_completed_action",
            "energy",
            "evidence_refs",
            "allowed_claims",
            "baseline_text",
        }
        unknown = set(data) - fields
        if unknown:
            raise ValueError(
                f"semantic_response_plan: unknown fields {sorted(unknown)}"
            )
        activity = data.get("activity")
        completed = data.get("last_completed_action")
        references = data.get("evidence_refs")
        claims = data.get("allowed_claims")
        if activity is not None and not isinstance(activity, dict):
            raise ValueError("activity: expected a dictionary or None")
        if completed is not None and not isinstance(completed, dict):
            raise ValueError("last_completed_action: expected a dictionary or None")
        if not isinstance(references, list) or not isinstance(claims, list):
            raise ValueError("evidence_refs and allowed_claims: expected lists")
        try:
            return cls(
                schema_version=data.get("schema_version"),
                response_id=data.get("response_id"),
                cycle=data.get("cycle"),
                language=data.get("language"),
                intent=data.get("intent"),
                activity=ActivityFact(**activity) if activity is not None else None,
                last_completed_action=(
                    CompletedActionFact(**completed) if completed is not None else None
                ),
                energy=data.get("energy"),
                evidence_refs=tuple(EvidenceRef(**item) for item in references),
                allowed_claims=tuple(claims),
                baseline_text=data.get("baseline_text"),
            )
        except TypeError as error:
            raise ValueError(
                f"semantic_response_plan: invalid nested data: {error}"
            ) from error


def _latest_entry(agent, status: str):
    history = getattr(agent, "_intention_history", None)
    entries = history if isinstance(history, list) else []
    for entry in reversed(entries):
        if not isinstance(entry, dict) or entry.get("status") != status:
            continue
        action = entry.get("action")
        cycle = entry.get("cycle")
        identifier = entry.get("id")
        if (
            not isinstance(action, str)
            or not action.strip()
            or isinstance(cycle, bool)
            or not isinstance(cycle, int)
            or cycle < 0
            or not isinstance(identifier, str)
            or not identifier.strip()
        ):
            continue
        return entry
    return None


def _target(entry) -> str | None:
    target = entry.get("target")
    if isinstance(target, str) and target.strip():
        return target[:500]
    return None


def _verified_work_id(agent, entry) -> str | None:
    episode = entry.get("decision_episode")
    intention = episode.get("creative_intention") if isinstance(episode, dict) else None
    work_id = intention.get("work_id") if isinstance(intention, dict) else None
    if not isinstance(work_id, str) or not work_id:
        return None
    catalog_name = {
        "draw": "_art_catalog",
        "compose_music": "_music_catalog",
        "create_draft": "_creative_catalog",
    }.get(entry.get("action"))
    catalog = getattr(agent, catalog_name, None) if catalog_name else None
    work = catalog.get(work_id) if isinstance(catalog, dict) else None
    return work_id if isinstance(work, dict) else None


def _completed_fact(entry) -> CompletedActionFact | None:
    if entry is None:
        return None
    return CompletedActionFact(
        kind=entry["action"], cycle=entry["cycle"], target=_target(entry)
    )


def build_self_activity_plan(
    agent, *, response_id: str, baseline_text: str, language: str = "ru"
) -> SemanticResponsePlan:
    """Построить activity-план, не смешивая текущее и завершённое действие."""
    current = _latest_entry(agent, "started")
    completed = None if current is not None else _latest_entry(agent, "performed")
    refs = []
    claims = []
    if current is None:
        activity = ActivityFact(status="none")
        claims.append("activity.none")
    else:
        activity = ActivityFact(
            status="current",
            kind=current["action"],
            work_id=_verified_work_id(agent, current),
            started_cycle=current["cycle"],
            target=_target(current),
        )
        refs.append(EvidenceRef(kind="intention", id=current["id"]))
        claims.append(f"activity.current:{current['action']}")
        if activity.target is not None:
            claims.append("activity.target")
    completed_fact = _completed_fact(completed)
    if completed_fact is not None:
        refs.append(EvidenceRef(kind="intention", id=completed["id"]))
        claims.append(f"activity.completed:{completed_fact.kind}")
        if completed_fact.target is not None:
            claims.append("activity.completed_target")
    return SemanticResponsePlan(
        response_id=response_id,
        cycle=agent.cycle_count,
        language=language,
        intent="ASK_SELF_ACTIVITY",
        activity=activity,
        last_completed_action=completed_fact,
        # Для activity энергия не разрешена как лишний факт ответа.
        energy=None,
        evidence_refs=tuple(refs),
        allowed_claims=tuple(claims),
        baseline_text=baseline_text,
    )


def build_self_state_plan(
    agent, *, response_id: str, baseline_text: str, language: str = "ru"
) -> SemanticResponsePlan:
    """Передать наблюдаемую энергию и прошлый исход без вывода переживаний."""
    refs = []
    claims = []
    energy = getattr(agent, "energy", None)
    if (
        isinstance(energy, (int, float))
        and not isinstance(energy, bool)
        and math.isfinite(energy)
        and energy >= 0
    ):
        energy = float(energy)
        refs.append(EvidenceRef(kind="state", id="energy"))
        claims.append("state.energy")
    else:
        energy = None
    completed = _latest_entry(agent, "performed")
    completed_fact = _completed_fact(completed)
    if completed_fact is not None:
        refs.append(EvidenceRef(kind="intention", id=completed["id"]))
        claims.append(f"activity.completed:{completed_fact.kind}")
        if completed_fact.target is not None:
            claims.append("activity.completed_target")
    return SemanticResponsePlan(
        response_id=response_id,
        cycle=agent.cycle_count,
        language=language,
        intent="ASK_SELF_STATE",
        activity=None,
        last_completed_action=completed_fact,
        energy=energy,
        evidence_refs=tuple(refs),
        allowed_claims=tuple(claims),
        baseline_text=baseline_text,
    )
