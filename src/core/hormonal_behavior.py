"""Ограниченный поведенческий advisor личной гормональной проекции.

Модуль только читает per-life уровни и профиль. Он не создаёт кандидатов, цели,
награды или события и не меняет гормональное состояние. Единственный эффект —
одна ограниченная поправка strength уже предложенных кандидатов.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List

from src.core.agent_body import HEAVY_ACTIONS


_CHANNELS = ("dopamine", "oxytocin", "cortisol")
_DOPAMINE_ACTIONS = frozenset(
    {
        "explore",
        "synthesis",
        "hypothesis",
        "web_search",
        "create_draft",
        "draw",
        "compose_music",
    }
)
_MAX_CONTRIBUTION = 0.10
_FULL_EVIDENCE_EPISODES = 20


def _finite_unit(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and 0.0 <= float(value) <= 1.0
    )


def _empty_projection() -> Dict:
    return {
        "signals": {name: 0.0 for name in _CHANNELS},
        "evidence": {name: 0.0 for name in _CHANNELS},
    }


def _channel_signal(system, name: str) -> tuple[float, float]:
    levels = getattr(system, "hormones", None)
    profile = getattr(system, "profile", None)
    values = getattr(profile, "values", None)
    if not isinstance(levels, dict) or not isinstance(values, dict):
        return 0.0, 0.0
    personal = values.get(name)
    if not isinstance(personal, dict):
        return 0.0, 0.0

    level = levels.get(name)
    baseline = personal.get("baseline")
    sample_count = personal.get("sample_count")
    if (
        not _finite_unit(level)
        or not _finite_unit(baseline)
        or isinstance(sample_count, bool)
        or not isinstance(sample_count, int)
        or sample_count < 0
    ):
        return 0.0, 0.0

    evidence = min(1.0, sample_count / _FULL_EVIDENCE_EPISODES)
    if evidence == 0.0:
        return 0.0, 0.0
    delta = float(level) - float(baseline)
    denominator = 1.0 - float(baseline) if delta >= 0.0 else float(baseline)
    if denominator <= 0.0:
        return 0.0, evidence
    excursion = max(-1.0, min(1.0, delta / denominator))
    return excursion * evidence, evidence


def projection_signals(system) -> Dict:
    """Вернуть непрерывные сигналы от личного baseline и силу доказательств."""
    if system is None:
        return _empty_projection()
    projection = _empty_projection()
    for name in _CHANNELS:
        signal, evidence = _channel_signal(system, name)
        projection["signals"][name] = signal
        projection["evidence"][name] = evidence
    return projection


def _neutral_report(reason: str) -> Dict:
    return {
        "mode": "advisor",
        "active": False,
        "reason": reason,
        **_empty_projection(),
        "adjustments": [],
    }


def apply_hormonal_advice(
    candidates: List[Dict],
    system,
    normalize_action: Callable,
    *,
    hardware_advisor_active: bool = False,
) -> Dict:
    """Применить не более одной поправки ±10 % к подходящим кандидатам.

    При активном advisor 4A тяжёлые кандидаты полностью остаются ему: это
    исключает вторую скидку кортизола и компенсацию собственной нагрузки
    дофамином. Все изменения вычисляются до первой записи в candidates.
    """
    if system is None:
        return _neutral_report("no_hormonal_system")
    projection = projection_signals(system)
    signals = projection["signals"]
    pending = []
    adjustments = []

    for input_index, candidate in enumerate(candidates):
        action = normalize_action(candidate.get("action"))
        before = candidate.get("strength", 0.5)
        if (
            isinstance(before, bool)
            or not isinstance(before, (int, float))
            or not math.isfinite(float(before))
            or float(before) <= 0.0
        ):
            continue
        heavy = action in HEAVY_ACTIONS
        if heavy and hardware_advisor_active:
            continue

        contribution = 0.0
        if action in _DOPAMINE_ACTIONS:
            contribution += _MAX_CONTRIBUTION * signals["dopamine"]
        if action == "communicate":
            contribution += _MAX_CONTRIBUTION * max(0.0, signals["oxytocin"])
        if heavy:
            contribution -= _MAX_CONTRIBUTION * max(0.0, signals["cortisol"])
        contribution = max(-_MAX_CONTRIBUTION, min(_MAX_CONTRIBUTION, contribution))
        if abs(contribution) < 1e-12:
            continue

        after = float(before) * (1.0 + contribution)
        pending.append((candidate, after))
        adjustments.append(
            {
                "input_index": input_index,
                "action": str(candidate.get("action") or "unknown"),
                "source": str(candidate.get("source") or "unknown"),
                "before_strength": float(before),
                "after_strength": after,
                "contribution": contribution,
            }
        )

    # Применяем только после полного расчёта: ошибка нормализации или чтения
    # кандидата не оставляет частично изменённый список.
    for candidate, after in pending:
        candidate["strength"] = after
    return {
        "mode": "advisor",
        "active": bool(pending),
        "reason": "applied"
        if pending
        else "neutral_projection"
        if all(value == 0.0 for value in signals.values())
        else "no_matching_candidates",
        **projection,
        "adjustments": adjustments,
    }


__all__ = ["apply_hormonal_advice", "projection_signals"]
