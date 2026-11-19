"""Ограниченный поведенческий советчик собственной аппаратной нагрузки.

Советчик читает уже накопленный per-life опыт, но не создаёт действия, цели,
награды или эндокринные события. Единственный разрешённый эффект — уменьшить
силу уже предложенных тяжёлых кандидатов после устойчивой свежей own_load.
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


__all__ = ["apply_own_load_advice", "own_load_advice"]
