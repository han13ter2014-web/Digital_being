"""Ограниченные поведенческие советчики собственной аппаратной нагрузки.

Советчики читают уже накопленный per-life опыт, но не создают действия, цели,
награды или эндокринные события. Разрешены два раздельных эффекта: 4A ослабляет
уже предложенные тяжёлые кандидаты после устойчивой свежей own_load, а 6B
ограниченно усиливает существующий телесный deep_rest после серии 5 + 5.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List

from src.core.agent_body import HEAVY_ACTIONS


_OWN_LOAD_THRESHOLD = 0.85
_REQUIRED_CYCLES = 5
_MAX_STRENGTH_REDUCTION = 0.25


def _finite_unit(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and 0.0 <= float(value) <= 1.0
    )


def _cycle(entry: Dict) -> int | None:
    value = entry.get("cycle")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _confirmed_own_state(entry: Dict) -> Dict | None:
    states = entry.get("states")
    if not isinstance(states, dict):
        return None
    state = states.get("own_load")
    if not isinstance(state, dict):
        return None
    if (
        state.get("origin") != "own"
        or state.get("reason") != "observed_process_load"
        or state.get("confidence") != 1.0
        or not _finite_unit(state.get("value"))
        or float(state["value"]) < _OWN_LOAD_THRESHOLD
    ):
        return None
    return state


def _inactive(reason: str) -> Dict:
    return {
        "active": False,
        "reason": reason,
        "factor": 1.0,
        "duration_cycles": 0,
        "risk": None,
        "experienced": None,
        "confidence": 0.0,
    }


def own_load_advice(observer) -> Dict:
    """Вернуть совет только по непрерывной серии полных own_load-наблюдений."""
    if observer is None:
        return _inactive("no_observer")
    observation = getattr(observer, "latest_observation", None)
    history = getattr(observer, "history", None)
    if not isinstance(observation, dict) or not isinstance(history, list):
        return _inactive("insufficient_sustained_own_load")
    channels = observation.get("channels")
    if not isinstance(channels, dict) or any(
        not isinstance(channels.get(name), dict)
        or channels[name].get("status") != "available"
        for name in ("process_cpu", "process_rss_ratio")
    ):
        return _inactive("waiting_for_fresh_process_channels")

    confirmed: List[Dict] = []
    expected_cycle = _cycle(observation)
    if expected_cycle is None:
        return _inactive("insufficient_sustained_own_load")
    for entry in reversed(history):
        if not isinstance(entry, dict) or _cycle(entry) != expected_cycle:
            break
        state = _confirmed_own_state(entry)
        if state is None:
            break
        confirmed.append(state)
        expected_cycle -= 1
    if len(confirmed) < _REQUIRED_CYCLES:
        return _inactive("insufficient_sustained_own_load")

    personal = getattr(observer, "personal", None)
    experiences = getattr(personal, "latest_experience", None)
    experience = experiences.get("own_load") if isinstance(experiences, dict) else None
    if not isinstance(experience, dict):
        return _inactive("personal_experience_unavailable")
    risk = experience.get("risk")
    experienced = experience.get("experienced")
    if (
        not _finite_unit(risk)
        or not _finite_unit(experienced)
        or float(risk) < _OWN_LOAD_THRESHOLD
    ):
        return _inactive("personal_experience_unavailable")

    current = confirmed[0]
    confidence = float(current["confidence"])
    factor = 1.0 - _MAX_STRENGTH_REDUCTION * float(experienced) * confidence
    return {
        "active": True,
        "reason": "sustained_own_load",
        "factor": factor,
        "duration_cycles": len(confirmed),
        "risk": float(risk),
        "experienced": float(experienced),
        "confidence": confidence,
    }


def apply_own_load_advice(
    candidates: List[Dict], observer, normalize_action: Callable
) -> Dict:
    """Ослабить только существующие тяжёлые кандидаты; состав не меняется."""
    advice = own_load_advice(observer)
    report = {"mode": "advisor", **advice, "adjustments": []}
    if not advice["active"]:
        return report

    pending = []
    for input_index, candidate in enumerate(candidates):
        action = normalize_action(candidate.get("action"))
        if action not in HEAVY_ACTIONS:
            continue
        before = candidate.get("strength", 0.5)
        if (
            isinstance(before, bool)
            or not isinstance(before, (int, float))
            or not math.isfinite(float(before))
            or float(before) <= 0.0
        ):
            continue
        after = float(before) * advice["factor"]
        pending.append((candidate, after))
        report["adjustments"].append(
            {
                "input_index": input_index,
                "action": str(candidate.get("action") or "unknown"),
                "source": str(candidate.get("source") or "unknown"),
                "before_strength": float(before),
                "after_strength": after,
                "factor": advice["factor"],
            }
        )
    # Применяем только после полного расчёта: ошибка нормализации не оставляет
    # частично изменённый список кандидатов.
    for candidate, after in pending:
        candidate["strength"] = after
    return report


def _neutral_recovery_evidence(reason: str) -> Dict:
    return {
        "eligible": False,
        "reason": reason,
        "strain_cycles": 0,
        "recovery_cycles": 0,
        "max_recovery_risk": None,
        "recovery": 0.0,
        "factor": 1.0,
    }


def _own_risk(entry: Dict) -> float | None:
    """Прочитать полное собственное наблюдение без вывода атрибуции."""
    states = entry.get("states")
    if not isinstance(states, dict):
        return None
    state = states.get("own_load")
    if not isinstance(state, dict):
        return None
    if (
        state.get("origin") != "own"
        or state.get("reason") != "observed_process_load"
        or state.get("confidence") != 1.0
        or not _finite_unit(state.get("value"))
    ):
        return None
    return float(state["value"])


def own_recovery_evidence(observer) -> Dict:
    """Доказать однократный переход 5 высоких + 5 низких own_load-циклов.

    Функция только читает существующую историю. Общее hardware recovery не
    используется: оно может быть вызвано внешней или смешанной нагрузкой.
    """
    if observer is None:
        return _neutral_recovery_evidence("no_observer")
    observation = getattr(observer, "latest_observation", None)
    history = getattr(observer, "history", None)
    if not isinstance(observation, dict) or not isinstance(history, list):
        return _neutral_recovery_evidence("insufficient_recovery_history")
    channels = observation.get("channels")
    if not isinstance(channels, dict) or any(
        not isinstance(channels.get(name), dict)
        or channels[name].get("status") != "available"
        for name in ("process_cpu", "process_rss_ratio")
    ):
        return _neutral_recovery_evidence("waiting_for_fresh_process_channels")

    expected_cycle = _cycle(observation)
    if expected_cycle is None:
        return _neutral_recovery_evidence("insufficient_recovery_history")
    risks: List[float] = []
    for entry in reversed(history):
        if not isinstance(entry, dict) or _cycle(entry) != expected_cycle:
            break
        risk = _own_risk(entry)
        if risk is None:
            return _neutral_recovery_evidence("invalid_own_recovery_evidence")
        risks.append(risk)
        expected_cycle -= 1
        if len(risks) == 10:
            break
    if len(risks) < 10:
        return _neutral_recovery_evidence("insufficient_recovery_history")

    recovery_risks = risks[:5]
    strain_risks = risks[5:]
    if any(value > 0.60 for value in recovery_risks) or any(
        value < 0.85 for value in strain_risks
    ):
        return _neutral_recovery_evidence("no_new_own_recovery_transition")

    max_recovery_risk = max(recovery_risks)
    recovery = 1.0 - max_recovery_risk
    return {
        "eligible": True,
        "reason": "confirmed_own_recovery_transition",
        "strain_cycles": 5,
        "recovery_cycles": 5,
        "max_recovery_risk": max_recovery_risk,
        "recovery": recovery,
        "factor": 1.0 + 0.10 * recovery,
    }


def own_recovery_behavior_report(observer, mode: str = "shadow") -> Dict:
    """Вернуть диагностику без доступа к кандидатам и их изменения."""
    mode = str(mode)
    evidence = own_recovery_evidence(observer)
    if mode == "shadow":
        reason = "shadow_only" if evidence["eligible"] else evidence["reason"]
    elif mode == "advisor":
        reason = "advisor_requires_candidates"
    else:
        reason = "unsupported_mode"
    return {
        "mode": mode,
        "active": False,
        **evidence,
        "reason": reason,
        "adjustments": [],
    }


def apply_own_recovery_advice(
    candidates: List[Dict], observer, normalize_action: Callable
) -> Dict:
    """Усилить только существующий телесный deep_rest не более чем до 1.1."""
    evidence = own_recovery_evidence(observer)
    report = {
        "mode": "advisor",
        "active": False,
        **evidence,
        "adjustments": [],
    }
    if not evidence["eligible"]:
        return report

    cycle = _cycle(getattr(observer, "latest_observation", None))
    if (
        cycle is not None
        and getattr(observer, "_recovery_advisor_applied_cycle", None) == cycle
    ):
        report["reason"] = "duplicate_cycle"
        return report

    pending = []
    for input_index, candidate in enumerate(candidates):
        action = normalize_action(candidate.get("action"))
        params = candidate.get("params")
        if (
            action != "deep_rest"
            or candidate.get("source") != "embodiment"
            or not isinstance(params, dict)
            or params.get("reason") not in {"tired", "low_energy", "resting"}
        ):
            continue
        before = candidate.get("strength", 0.5)
        if (
            isinstance(before, bool)
            or not isinstance(before, (int, float))
            or not math.isfinite(float(before))
            or not 0.0 < float(before) <= 1.0
        ):
            continue
        after = min(1.1, float(before) * evidence["factor"])
        pending.append((candidate, after))
        report["adjustments"].append(
            {
                "input_index": input_index,
                "action": str(candidate.get("action") or "unknown"),
                "source": str(candidate.get("source") or "unknown"),
                "before_strength": float(before),
                "after_strength": after,
                "factor": evidence["factor"],
            }
        )
    if not pending:
        report["reason"] = "no_matching_candidates"
        return report

    # Сначала полный расчёт и runtime-дедупликация, затем одна атомарная серия
    # записей. Отметка не входит в checkpoint и не создаёт новой схемы.
    if cycle is not None:
        setattr(observer, "_recovery_advisor_applied_cycle", cycle)
    for candidate, after in pending:
        candidate["strength"] = after
    report["active"] = True
    report["reason"] = "applied"
    return report


__all__ = [
    "apply_own_load_advice",
    "apply_own_recovery_advice",
    "own_load_advice",
    "own_recovery_behavior_report",
    "own_recovery_evidence",
]
