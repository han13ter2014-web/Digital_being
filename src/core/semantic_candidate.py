"""Ограниченные речевые кандидаты и доказуемый возврат к baseline.

R3 не генерирует новые факты и не подменяет активный Composer. Кандидат принимается
только при точном совпадении текста и метаданных с детерминированным allowlist,
построенным из frozen ``SemanticResponsePlan``. Любое другое содержимое даёт abstain.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from src.core.semantic_response_plan import EvidenceRef, SemanticResponsePlan

_TEXT_MAX_LEN = 4000
_REALIZATION_ID_MAX_LEN = 80
_MAX_CLAIMS = 16
_MAX_REFERENCES = 8
_CLAIM = re.compile(r"[a-z_]+(?:\.[a-z_]+)*(?::[a-z_]+)?\Z")
_REALIZATION_ID = re.compile(r"[a-z0-9_.:-]+\Z")
_EVIDENCE_KINDS = frozenset({"intention", "state"})

_ACTION_NAMES = {
    "draw": "рисование",
    "compose_music": "сочинение мелодии",
    "listen_music": "прослушивание музыки",
    "create_draft": "работа над черновиком",
    "explore": "исследование темы",
    "reflect": "размышление",
    "web_search": "поиск в интернете",
    "read_news": "чтение новостей",
    "set_own_goal": "постановка собственной цели",
    "play": "игра",
    "rest": "отдых",
    "deep_rest": "глубокий отдых",
}


def _bounded_text(value, path: str, limit: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{path}: expected a bounded nonempty string")


@dataclass(frozen=True)
class SemanticCandidate:
    """Текст и весь проверяемый набор заявленных фактов кандидата."""

    text: str
    realization_id: str
    claims: tuple[str, ...]
    used_evidence_refs: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        _bounded_text(self.text, "text", _TEXT_MAX_LEN)
        _bounded_text(self.realization_id, "realization_id", _REALIZATION_ID_MAX_LEN)
        if not _REALIZATION_ID.fullmatch(self.realization_id):
            raise ValueError("realization_id: expected a machine-readable identifier")
        if not isinstance(self.claims, tuple) or len(self.claims) > _MAX_CLAIMS:
            raise ValueError("claims: expected a bounded tuple")
        if len(set(self.claims)) != len(self.claims):
            raise ValueError("claims: duplicates")
        for claim in self.claims:
            if not isinstance(claim, str) or not _CLAIM.fullmatch(claim):
                raise ValueError("claims: expected machine-readable claims")
        if (
            not isinstance(self.used_evidence_refs, tuple)
            or len(self.used_evidence_refs) > _MAX_REFERENCES
        ):
            raise ValueError("used_evidence_refs: expected a bounded tuple")
        if len(set(self.used_evidence_refs)) != len(self.used_evidence_refs):
            raise ValueError("used_evidence_refs: duplicates")
        for reference in self.used_evidence_refs:
            if not isinstance(reference, EvidenceRef):
                raise ValueError("used_evidence_refs: expected EvidenceRef items")
            if reference.kind not in _EVIDENCE_KINDS:
                raise ValueError("used_evidence_refs.kind: unsupported")
            _bounded_text(reference.id, "used_evidence_refs.id", 160)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "realization_id": self.realization_id,
            "claims": list(self.claims),
            "used_evidence_refs": [
                reference.to_dict() for reference in self.used_evidence_refs
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> SemanticCandidate:
        if not isinstance(data, dict):
            raise ValueError("semantic_candidate: expected a dictionary")
        fields = {"text", "realization_id", "claims", "used_evidence_refs"}
        unknown = set(data) - fields
        if unknown:
            raise ValueError(f"semantic_candidate: unknown fields {sorted(unknown)}")
        claims = data.get("claims")
        references = data.get("used_evidence_refs")
        if not isinstance(claims, list) or not isinstance(references, list):
            raise ValueError("claims and used_evidence_refs: expected lists")
        try:
            return cls(
                text=data.get("text"),
                realization_id=data.get("realization_id"),
                claims=tuple(claims),
                used_evidence_refs=tuple(
                    EvidenceRef(**reference) for reference in references
                ),
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"semantic_candidate: invalid data: {error}") from error


@dataclass(frozen=True)
class SemanticCandidateDecision:
    """Результат gate: принятый кандидат либо точный baseline с причиной."""

    accepted: bool
    text: str
    realization_id: str
    reason: str | None = None

    @property
    def abstained(self) -> bool:
        return not self.accepted


def _baseline(plan: SemanticResponsePlan) -> SemanticCandidate:
    # Baseline уже построен существующим Composer. Пустые metadata не приписывают
    # ему дополнительные claims; точный объект всё равно входит в allowlist.
    return SemanticCandidate(
        text=plan.baseline_text,
        realization_id="baseline",
        claims=(),
        used_evidence_refs=(),
    )


def _activity_alternative(plan: SemanticResponsePlan) -> SemanticCandidate | None:
    activity = plan.activity
    if activity is None:
        return None
    if activity.status == "current":
        action_name = _ACTION_NAMES.get(activity.kind)
        if action_name is None:
            return None
        return SemanticCandidate(
            text=f"Моё текущее занятие — {action_name}.",
            realization_id="ru.activity.current.v1",
            claims=(f"activity.current:{activity.kind}",),
            used_evidence_refs=plan.evidence_refs,
        )

    completed = plan.last_completed_action
    claims = ["activity.none"]
    if completed is None:
        return SemanticCandidate(
            text="Сейчас у меня нет активного действия.",
            realization_id="ru.activity.none.v1",
            claims=tuple(claims),
            used_evidence_refs=(),
        )
    action_name = _ACTION_NAMES.get(completed.kind)
    if action_name is None:
        return None
    claims.append(f"activity.completed:{completed.kind}")
    return SemanticCandidate(
        text=(
            "Сейчас у меня нет активного действия. "
            f"Последнее завершённое действие — {action_name}."
        ),
        realization_id="ru.activity.completed.v1",
        claims=tuple(claims),
        used_evidence_refs=plan.evidence_refs,
    )


def _state_alternative(plan: SemanticResponsePlan) -> SemanticCandidate | None:
    if plan.intent != "ASK_SELF_STATE":
        return None
    parts = ["Спасибо за вопрос."]
    claims = []
    references = []
    if plan.energy is not None:
        parts.append(f"Сейчас мой уровень энергии — {plan.energy:.2f}.")
        claims.append("state.energy")
        references.extend(
            reference for reference in plan.evidence_refs if reference.kind == "state"
        )
    completed = plan.last_completed_action
    action_name = _ACTION_NAMES.get(completed.kind) if completed is not None else None
    if action_name is not None:
        parts.append(f"Последнее завершённое действие — {action_name}.")
        claims.append(f"activity.completed:{completed.kind}")
        references.extend(
            reference
            for reference in plan.evidence_refs
            if reference.kind == "intention"
        )
    if len(parts) == 1:
        return None
    return SemanticCandidate(
        text=" ".join(parts),
        realization_id="ru.state.v1",
        claims=tuple(claims),
        used_evidence_refs=tuple(references),
    )


def candidate_space(plan: SemanticResponsePlan) -> tuple[SemanticCandidate, ...]:
    """Построить конечный allowlist; для неподдерживаемого языка он пуст."""
    if not isinstance(plan, SemanticResponsePlan):
        raise ValueError("plan: expected SemanticResponsePlan")
    if plan.language != "ru":
        return ()
    alternative = (
        _activity_alternative(plan)
        if plan.intent == "ASK_SELF_ACTIVITY"
        else _state_alternative(plan)
    )
    if alternative is None:
        return (_baseline(plan),)
    return (_baseline(plan), alternative)


def _abstain(plan: SemanticResponsePlan, reason: str) -> SemanticCandidateDecision:
    return SemanticCandidateDecision(
        accepted=False,
        text=plan.baseline_text,
        realization_id="baseline",
        reason=reason,
    )


def validate_semantic_candidate(plan, candidate) -> SemanticCandidateDecision:
    """Принять только точный allowlist-объект; иначе один раз вернуть baseline."""
    if not isinstance(plan, SemanticResponsePlan):
        raise ValueError("plan: expected SemanticResponsePlan")
    if plan.language != "ru":
        return _abstain(plan, "unsupported_language")
    if isinstance(candidate, dict):
        try:
            candidate = SemanticCandidate.from_dict(candidate)
        except ValueError:
            return _abstain(plan, "malformed_candidate")
    if not isinstance(candidate, SemanticCandidate):
        return _abstain(plan, "malformed_candidate")

    if not set(candidate.claims) <= set(plan.allowed_claims) and candidate.claims:
        return _abstain(plan, "unsupported_claims")
    if (
        not set(candidate.used_evidence_refs) <= set(plan.evidence_refs)
        and candidate.used_evidence_refs
    ):
        return _abstain(plan, "unsupported_evidence")

    for allowed in candidate_space(plan):
        if candidate == allowed:
            return SemanticCandidateDecision(
                accepted=True,
                text=allowed.text,
                realization_id=allowed.realization_id,
            )
    if candidate.realization_id == "baseline":
        return _abstain(plan, "baseline_mismatch")
    return _abstain(plan, "outside_candidate_space")
