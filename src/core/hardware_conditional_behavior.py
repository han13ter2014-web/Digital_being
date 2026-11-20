"""11B/11C: shadow-оценка и ограниченный advisor условной записи."""

from __future__ import annotations

import math
from typing import Dict

from src.core.hardware_behavior import storage_risk_evidence


_MIN_SAMPLES = 5
_MIN_WRITES = 1
_MAX_STRENGTH_REDUCTION = 0.25


def _empty_write_evidence() -> Dict:
    return {
        "sample_count": 0,
        "write_count": 0,
        "failed_count": 0,
        "write_ratio": 0.0,
    }


def _report(
    mode: str,
    *,
    reason: str,
    eligible: bool = False,
    profile_class=None,
    write_evidence=None,
    risk=None,
    experienced=None,
    confidence: float = 0.0,
    factor: float = 1.0,
) -> Dict:
    return {
        "mode": mode,
        "active": False,
        "eligible": eligible,
        "reason": reason,
        "profile_class": profile_class,
        "write_evidence": deepcopy_safe(write_evidence or _empty_write_evidence()),
        "risk": risk,
        "experienced": experienced,
        "confidence": confidence,
        "factor": factor,
        "adjustments": [],
    }


def deepcopy_safe(value: Dict) -> Dict:
    """DTO строится заново из чисел; внешние ссылки не возвращаются."""
    return {
        "sample_count": int(value["sample_count"]),
        "write_count": int(value["write_count"]),
        "failed_count": int(value["failed_count"]),
        "write_ratio": float(value["write_ratio"]),
    }


def _valid_strength(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) > 0.0
    )


def _observation_cycle(observer) -> int | None:
    observation = getattr(observer, "latest_observation", None)
    cycle = observation.get("cycle") if isinstance(observation, dict) else None
    return cycle if not isinstance(cycle, bool) and isinstance(cycle, int) else None


def _conditional_write_report(
    candidates,
    observer,
    mode: str,
    *,
    profile_managed: bool,
    normalize_action,
):
    """Собрать доказательства и выбрать первый существующий кандидат."""
    if mode not in {"shadow", "advisor"}:
        return _report(mode, reason="unsupported_mode"), None

    storage = storage_risk_evidence(observer)
    if not storage["eligible"]:
        return _report(mode, reason="no_storage_evidence"), None

    selected = None
    selected_index = None
    for input_index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        try:
            action = (
                normalize_action(candidate.get("action"))
                if callable(normalize_action)
                else str(candidate.get("action") or "").strip().lower()
            )
        except Exception:
            continue
        if action in {"web_search", "explore"}:
            selected = action
            selected_index = input_index
            break
    if selected is None:
        return _report(mode, reason="no_matching_candidates"), None

    conditional = getattr(observer, "conditional_writes", None)
    evidence_method = getattr(conditional, "evidence", None)
    if not callable(evidence_method):
        return _report(mode, reason="profile_not_advisor_eligible"), None
    evidence = evidence_method(selected, managed=profile_managed)
    profile_class = evidence["profile_class"]
    if profile_managed:
        return (
            _report(
                mode,
                reason="profile_not_advisor_eligible",
                profile_class=profile_class,
                write_evidence=evidence,
            ),
            None,
        )
    if evidence["sample_count"] < _MIN_SAMPLES or evidence["write_count"] < _MIN_WRITES:
        return (
            _report(
                mode,
                reason="insufficient_conditional_write_experience",
                profile_class=profile_class,
                write_evidence=evidence,
            ),
            None,
        )

    # Прошлый write не обещает текущий: его доля только уменьшает вклад storage.
    factor = 1.0 - (
        _MAX_STRENGTH_REDUCTION
        * float(storage["experienced"])
        * float(storage["confidence"])
        * float(evidence["write_ratio"])
    )
    factor = max(1.0 - _MAX_STRENGTH_REDUCTION, min(1.0, factor))
    return (
        _report(
            mode,
            reason="shadow_only" if mode == "shadow" else "confirmed_conditional_write",
            eligible=True,
            profile_class=profile_class,
            write_evidence=evidence,
            risk=storage["risk"],
            experienced=storage["experienced"],
            confidence=storage["confidence"],
            factor=factor,
        ),
        selected_index,
    )


def conditional_write_behavior_report(
    candidates,
    observer,
    mode: str = "shadow",
    *,
    profile_managed: bool = False,
    normalize_action=None,
) -> Dict:
    """Sanitized shadow-отчёт; advisor применяется отдельной функцией."""
    return _conditional_write_report(
        candidates,
        observer,
        str(mode),
        profile_managed=profile_managed,
        normalize_action=normalize_action,
    )[0]


def apply_conditional_write_advice(
    candidates,
    observer,
    normalize_action,
    *,
    profile_managed: bool = False,
    input_strengths=None,
) -> Dict:
    """Снизить первый доказанный кандидат в общем с 4A/7B бюджете до 25 %."""
    report, selected_index = _conditional_write_report(
        candidates,
        observer,
        "advisor",
        profile_managed=profile_managed,
        normalize_action=normalize_action,
    )
    if not report["eligible"]:
        return report

    cycle = _observation_cycle(observer)
    if (
        cycle is not None
        and getattr(observer, "_conditional_write_advisor_applied_cycle", None) == cycle
    ):
        report["reason"] = "duplicate_cycle"
        return report

    if input_strengths is None:
        originals = [candidate.get("strength", 0.5) for candidate in candidates]
    else:
        if len(input_strengths) != len(candidates):
            raise ValueError("conditional advisor input strength count mismatch")
        originals = list(input_strengths)

    candidate = candidates[selected_index]
    original = originals[selected_index]
    before = candidate.get("strength", 0.5)
    if not _valid_strength(original) or not _valid_strength(before):
        report["reason"] = "invalid_strength"
        return report

    original = float(original)
    before = float(before)
    target = max(original * 0.75, original * report["factor"])
    after = max(original * 0.75, min(before, target))
    if after >= before:
        report["reason"] = "shared_budget_already_applied"
        return report

    adjustment = {
        "input_index": selected_index,
        "action": str(candidate.get("action") or "unknown"),
        "source": str(candidate.get("source") or "unknown"),
        "before_strength": original,
        "after_strength": after,
        "factor": report["factor"],
    }
    # Расчёт и runtime-дедупликация предшествуют единственной мутации. Отметка
    # не входит в checkpoint и не меняет его схему.
    if cycle is not None:
        setattr(observer, "_conditional_write_advisor_applied_cycle", cycle)
    candidate["strength"] = after
    report["active"] = True
    report["reason"] = "applied"
    report["adjustments"].append(adjustment)
    return report


__all__ = ["apply_conditional_write_advice", "conditional_write_behavior_report"]
