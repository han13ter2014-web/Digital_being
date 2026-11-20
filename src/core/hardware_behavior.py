"""Ограниченные поведенческие советчики собственной аппаратной нагрузки.

Советчики читают уже накопленный per-life опыт, но не создают действия, цели,
награды или эндокринные события. Разрешены четыре раздельных эффекта: 4A ослабляет
уже предложенные тяжёлые кандидаты после устойчивой свежей own_load, 7B делает
это после подтверждённой physical-перегрузки в общем с 4A бюджете, 8B ослабляет
только разрешённые творческие кандидаты после storage-риска, а 6B ограниченно
усиливает существующий телесный deep_rest после серии 5 + 5.
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


def _neutral_physical_evidence(reason: str) -> Dict:
    return {
        "eligible": False,
        "reason": reason,
        "duration_cycles": 0,
        "risk": None,
        "experienced": None,
        "confidence": 0.0,
        "factor": 1.0,
    }


def _current_physical_risk(observation: Dict) -> float | None:
    """Текущий нагрев/power limit; GPU utilization сюда не входит."""
    channels = observation.get("channels")
    if not isinstance(channels, dict):
        return None
    risks = []
    for name in ("gpu_temperature", "cpu_temperature", "gpu_power"):
        channel = channels.get(name)
        if not isinstance(channel, dict) or channel.get("status") != "available":
            continue
        value = channel.get("value")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            continue
        value = float(value)
        if name == "gpu_power":
            if not 0.0 <= value <= 2.0:
                continue
            risk = value
        else:
            if not 0.0 <= value <= 150.0:
                continue
            risk = (value - 60.0) / 40.0
        risks.append(min(1.0, max(0.0, risk)))
    return max(risks) if risks else None


def _physical_history_state(entry: Dict) -> Dict | None:
    states = entry.get("states")
    if not isinstance(states, dict):
        return None
    state = states.get("physical_strain")
    if (
        not isinstance(state, dict)
        or state.get("origin") != "unknown"
        or state.get("reason") != "observed_physical_channels"
        or not _finite_unit(state.get("value"))
        or float(state["value"]) < _OWN_LOAD_THRESHOLD
        or not _finite_unit(state.get("confidence"))
        or float(state["confidence"]) <= 0.0
    ):
        return None
    return state


def physical_strain_evidence(observer) -> Dict:
    """Прочитать существующий physical-опыт без доступа к кандидатам."""
    if observer is None:
        return _neutral_physical_evidence("no_observer")
    observation = getattr(observer, "latest_observation", None)
    history = getattr(observer, "history", None)
    if not isinstance(observation, dict) or not isinstance(history, list):
        return _neutral_physical_evidence("insufficient_physical_evidence")
    current_risk = _current_physical_risk(observation)
    if current_risk is None:
        return _neutral_physical_evidence("waiting_for_fresh_physical_channels")
    if current_risk < _OWN_LOAD_THRESHOLD:
        return _neutral_physical_evidence("insufficient_sustained_physical_strain")

    current = _physical_history_state({"states": getattr(observer, "states", None)})
    slow_states = getattr(observer, "slow_states", None)
    slow = slow_states.get("physical") if isinstance(slow_states, dict) else None
    duration = slow.get("sustained_cycles") if isinstance(slow, dict) else None
    if (
        current is None
        or not isinstance(slow, dict)
        or slow.get("strain_active") is not True
        or isinstance(duration, bool)
        or not isinstance(duration, int)
        or duration < _REQUIRED_CYCLES
    ):
        return _neutral_physical_evidence("insufficient_sustained_physical_strain")

    expected_cycle = _cycle(observation)
    if expected_cycle is None:
        return _neutral_physical_evidence("insufficient_physical_evidence")
    confirmed = 0
    for entry in reversed(history):
        if not isinstance(entry, dict) or _cycle(entry) != expected_cycle:
            return _neutral_physical_evidence("noncontiguous_physical_evidence")
        if _physical_history_state(entry) is None:
            return _neutral_physical_evidence("insufficient_sustained_physical_strain")
        confirmed += 1
        if confirmed == _REQUIRED_CYCLES:
            break
        expected_cycle -= 1
    if confirmed < _REQUIRED_CYCLES:
        return _neutral_physical_evidence("insufficient_sustained_physical_strain")

    domain_personal = getattr(observer, "domain_personal", None)
    domains = getattr(domain_personal, "domains", None)
    domain = domains.get("physical") if isinstance(domains, dict) else None
    episode = domain.get("current_episode") if isinstance(domain, dict) else None
    experience = domain.get("latest") if isinstance(domain, dict) else None
    if (
        not isinstance(episode, dict)
        or not isinstance(episode.get("strain_cycle"), int)
        or isinstance(episode.get("strain_cycle"), bool)
        or episode.get("fresh_high_cycles", 0) < _REQUIRED_CYCLES
        or not isinstance(experience, dict)
        or experience.get("freshness") != "fresh"
        or experience.get("reason") != "observed_physical_channels"
        or not _finite_unit(experience.get("risk"))
        or not _finite_unit(experience.get("experienced"))
        or float(experience["risk"]) < _OWN_LOAD_THRESHOLD
    ):
        return _neutral_physical_evidence("physical_experience_unavailable")

    risk = float(experience["risk"])
    experienced = float(experience["experienced"])
    confidence = float(current["confidence"])
    return {
        "eligible": True,
        "reason": "confirmed_physical_strain",
        "duration_cycles": duration,
        "risk": risk,
        "experienced": experienced,
        "confidence": confidence,
        "factor": 1.0 - _MAX_STRENGTH_REDUCTION * experienced * confidence,
    }


def physical_strain_behavior_report(observer, mode: str = "shadow") -> Dict:
    """Sanitized shadow-отчёт без доступа к кандидатам и их изменения."""
    mode = str(mode)
    evidence = physical_strain_evidence(observer)
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


def apply_physical_strain_advice(
    candidates: List[Dict],
    observer,
    normalize_action: Callable,
    *,
    input_strengths: List | None = None,
) -> Dict:
    """Ослабить тяжёлые кандидаты в общем с 4A бюджете не более 25 %."""
    evidence = physical_strain_evidence(observer)
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
        and getattr(observer, "_physical_advisor_applied_cycle", None) == cycle
    ):
        report["reason"] = "duplicate_cycle"
        return report

    if input_strengths is None:
        originals = [candidate.get("strength", 0.5) for candidate in candidates]
    else:
        if len(input_strengths) != len(candidates):
            raise ValueError("physical advisor input strength count mismatch")
        originals = list(input_strengths)

    pending = []
    matched = False
    for input_index, (candidate, original) in enumerate(zip(candidates, originals)):
        action = normalize_action(candidate.get("action"))
        if action not in HEAVY_ACTIONS:
            continue
        before = candidate.get("strength", 0.5)
        if (
            isinstance(original, bool)
            or not isinstance(original, (int, float))
            or not math.isfinite(float(original))
            or float(original) <= 0.0
            or isinstance(before, bool)
            or not isinstance(before, (int, float))
            or not math.isfinite(float(before))
            or float(before) <= 0.0
        ):
            continue
        matched = True
        original = float(original)
        before = float(before)
        # 4A уже мог изменить current strength. Считаем от исходной силы и
        # выбираем только более сильную одну скидку, а не произведение двух.
        target = max(original * 0.75, original * evidence["factor"])
        after = max(original * 0.75, min(before, target))
        if after >= before:
            continue
        pending.append((candidate, after))
        report["adjustments"].append(
            {
                "input_index": input_index,
                "action": str(candidate.get("action") or "unknown"),
                "source": str(candidate.get("source") or "unknown"),
                "before_strength": original,
                "after_strength": after,
                "factor": evidence["factor"],
            }
        )
    if not pending:
        report["reason"] = (
            "shared_budget_already_applied" if matched else "no_matching_candidates"
        )
        return report

    # Сначала полный расчёт и runtime-дедупликация, затем одна серия записей.
    # Отметка не входит в checkpoint и не создаёт новой схемы.
    if cycle is not None:
        setattr(observer, "_physical_advisor_applied_cycle", cycle)
    for candidate, after in pending:
        candidate["strength"] = after
    report["active"] = True
    report["reason"] = "applied"
    return report


def _neutral_storage_evidence(reason: str) -> Dict:
    return {
        "eligible": False,
        "reason": reason,
        "duration_cycles": 0,
        "risk": None,
        "experienced": None,
        "confidence": 0.0,
        "factor": 1.0,
    }


def _storage_history_state(entry: Dict) -> Dict | None:
    states = entry.get("states")
    if not isinstance(states, dict):
        return None
    state = states.get("storage_risk")
    if (
        not isinstance(state, dict)
        or state.get("origin") != "unknown"
        or state.get("reason") != "observed_data_storage"
        or not _finite_unit(state.get("value"))
        or float(state["value"]) < _OWN_LOAD_THRESHOLD
        or not _finite_unit(state.get("confidence"))
        or float(state["confidence"]) <= 0.0
    ):
        return None
    return state


def _relevant_root_storage_evidence(observer, root_id) -> Dict:
    """Доказательства дополнительного root без заимствования опыта data."""
    observations = getattr(observer, "latest_relevant_root_observations", None)
    root = observations.get(root_id) if isinstance(observations, dict) else None
    if not isinstance(root, dict):
        return _neutral_storage_evidence("root_not_observed")
    channel = root.get("channel")
    if (
        not isinstance(channel, dict)
        or channel.get("status") != "available"
        or not _finite_unit(channel.get("value"))
    ):
        return _neutral_storage_evidence("waiting_for_fresh_storage_channel")

    current = root.get("risk")
    if (
        not isinstance(current, dict)
        or current.get("origin") != "unknown"
        or current.get("reason") != "observed_relevant_root_storage"
        or not _finite_unit(current.get("value"))
        or float(current["value"]) < _OWN_LOAD_THRESHOLD
        or not _finite_unit(current.get("confidence"))
        or float(current["confidence"]) <= 0.0
    ):
        return _neutral_storage_evidence("insufficient_sustained_storage_risk")

    experiences = getattr(observer, "relevant_root_experiences", None)
    root_experience = (
        experiences.get(root_id) if isinstance(experiences, dict) else None
    )
    slow = getattr(root_experience, "slow_state", None)
    duration = slow.get("sustained_cycles") if isinstance(slow, dict) else None
    if (
        not isinstance(slow, dict)
        or slow.get("strain_active") is not True
        or isinstance(duration, bool)
        or not isinstance(duration, int)
        or duration < _REQUIRED_CYCLES
    ):
        return _neutral_storage_evidence("insufficient_sustained_storage_risk")

    domain = root.get("experience")
    episode = domain.get("current_episode") if isinstance(domain, dict) else None
    experience = domain.get("latest") if isinstance(domain, dict) else None
    if (
        not isinstance(episode, dict)
        or not isinstance(episode.get("strain_cycle"), int)
        or isinstance(episode.get("strain_cycle"), bool)
        or episode.get("fresh_high_cycles", 0) < _REQUIRED_CYCLES
        or not isinstance(experience, dict)
        or experience.get("freshness") != "fresh"
        or experience.get("reason") != "observed_relevant_root_storage"
        or not _finite_unit(experience.get("risk"))
        or not _finite_unit(experience.get("experienced"))
        or float(experience["risk"]) < _OWN_LOAD_THRESHOLD
    ):
        return _neutral_storage_evidence("storage_experience_unavailable")

    experienced = float(experience["experienced"])
    confidence = float(current["confidence"])
    return {
        "eligible": True,
        "reason": "confirmed_storage_risk",
        "duration_cycles": duration,
        "risk": float(experience["risk"]),
        "experienced": experienced,
        "confidence": confidence,
        "factor": 1.0 - _MAX_STRENGTH_REDUCTION * experienced * confidence,
    }


def storage_risk_evidence(observer, root_id: str = "data") -> Dict:
    """Подтверждённый опыт одного root без доступа к кандидатам."""
    if root_id != "data":
        return _relevant_root_storage_evidence(observer, root_id)
    if observer is None:
        return _neutral_storage_evidence("no_observer")
    observation = getattr(observer, "latest_observation", None)
    history = getattr(observer, "history", None)
    if not isinstance(observation, dict) or not isinstance(history, list):
        return _neutral_storage_evidence("insufficient_storage_evidence")
    channels = observation.get("channels")
    storage = channels.get("data_storage") if isinstance(channels, dict) else None
    if (
        not isinstance(storage, dict)
        or storage.get("status") != "available"
        or not _finite_unit(storage.get("value"))
    ):
        return _neutral_storage_evidence("waiting_for_fresh_storage_channel")

    current = _storage_history_state({"states": getattr(observer, "states", None)})
    if current is None:
        return _neutral_storage_evidence("insufficient_sustained_storage_risk")
    expected_cycle = _cycle(observation)
    if expected_cycle is None:
        return _neutral_storage_evidence("insufficient_storage_evidence")

    # Непрерывность истории проверяется до локальных счётчиков: после разрыва
    # они уже сброшены, но sanitized-причина должна сохранить сам разрыв.
    confirmed = 0
    for entry in reversed(history):
        if not isinstance(entry, dict) or _cycle(entry) != expected_cycle:
            return _neutral_storage_evidence("noncontiguous_storage_evidence")
        if _storage_history_state(entry) is None:
            return _neutral_storage_evidence("insufficient_sustained_storage_risk")
        confirmed += 1
        if confirmed == _REQUIRED_CYCLES:
            break
        expected_cycle -= 1
    if confirmed < _REQUIRED_CYCLES:
        return _neutral_storage_evidence("insufficient_sustained_storage_risk")

    slow_states = getattr(observer, "slow_states", None)
    slow = slow_states.get("storage") if isinstance(slow_states, dict) else None
    duration = slow.get("sustained_cycles") if isinstance(slow, dict) else None
    if (
        not isinstance(slow, dict)
        or slow.get("strain_active") is not True
        or isinstance(duration, bool)
        or not isinstance(duration, int)
        or duration < _REQUIRED_CYCLES
    ):
        return _neutral_storage_evidence("insufficient_sustained_storage_risk")

    domain_personal = getattr(observer, "domain_personal", None)
    domains = getattr(domain_personal, "domains", None)
    domain = domains.get("storage") if isinstance(domains, dict) else None
    episode = domain.get("current_episode") if isinstance(domain, dict) else None
    experience = domain.get("latest") if isinstance(domain, dict) else None
    if (
        not isinstance(episode, dict)
        or not isinstance(episode.get("strain_cycle"), int)
        or isinstance(episode.get("strain_cycle"), bool)
        or episode.get("fresh_high_cycles", 0) < _REQUIRED_CYCLES
        or not isinstance(experience, dict)
        or experience.get("freshness") != "fresh"
        or experience.get("reason") != "observed_data_storage"
        or not _finite_unit(experience.get("risk"))
        or not _finite_unit(experience.get("experienced"))
        or float(experience["risk"]) < _OWN_LOAD_THRESHOLD
    ):
        return _neutral_storage_evidence("storage_experience_unavailable")

    experienced = float(experience["experienced"])
    confidence = float(current["confidence"])
    return {
        "eligible": True,
        "reason": "confirmed_storage_risk",
        "duration_cycles": duration,
        "risk": float(experience["risk"]),
        "experienced": experienced,
        "confidence": confidence,
        "factor": 1.0 - _MAX_STRENGTH_REDUCTION * experienced * confidence,
    }


def storage_risk_behavior_report(observer, mode: str = "shadow") -> Dict:
    """Sanitized shadow-отчёт; advisor без кандидатов ничего не изменяет."""
    mode = str(mode)
    evidence = storage_risk_evidence(observer)
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


def apply_storage_risk_advice(
    candidates: List[Dict],
    observer,
    normalize_action: Callable,
    *,
    input_strengths: List | None = None,
) -> Dict:
    """Ослабить кандидаты только с доказанным записывающим путём в data."""
    # Инвентарь 8B/11A доказывает data только для перечисленных ниже кандидатов.
    # Наблюдаемый additional root не становится их write path автоматически.
    evidence = storage_risk_evidence(observer, root_id="data")
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
        and getattr(observer, "_storage_advisor_applied_cycle", None) == cycle
    ):
        report["reason"] = "duplicate_cycle"
        return report

    if input_strengths is None:
        originals = [candidate.get("strength", 0.5) for candidate in candidates]
    else:
        if len(input_strengths) != len(candidates):
            raise ValueError("storage advisor input strength count mismatch")
        originals = list(input_strengths)

    pending = []
    budget_limited = False
    for input_index, (candidate, original) in enumerate(zip(candidates, originals)):
        action = normalize_action(candidate.get("action"))
        if action == "create_draft":
            params = candidate.get("params") or {}
            if not isinstance(params, dict) or params.get(
                "draft_mode", "continue"
            ) not in {"new", "continue"}:
                continue
        elif action not in {"draw", "compose_music"}:
            continue
        before = candidate.get("strength", 0.5)
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0.0
            for value in (original, before)
        ):
            continue
        original = float(original)
        before = float(before)
        # Прежняя поправка и новая выбирают одну более сильную скидку от
        # исходной силы; коэффициенты не перемножаются ниже общих 75 %.
        target = max(original * 0.75, original * evidence["factor"])
        after = max(original * 0.75, min(before, target))
        if after >= before:
            budget_limited = True
            continue
        pending.append((candidate, after))
        report["adjustments"].append(
            {
                "input_index": input_index,
                "action": str(candidate.get("action") or "unknown"),
                "source": str(candidate.get("source") or "unknown"),
                "before_strength": original,
                "after_strength": after,
                "factor": evidence["factor"],
            }
        )
    if not pending:
        report["reason"] = (
            "shared_budget_already_applied"
            if budget_limited
            else "no_matching_candidates"
        )
        return report

    # Полный расчёт предшествует runtime-отметке и всем мутациям. Отметка
    # дедупликации остаётся только в процессе и не входит в checkpoint.
    if cycle is not None:
        setattr(observer, "_storage_advisor_applied_cycle", cycle)
    for candidate, after in pending:
        candidate["strength"] = after
    report["active"] = True
    report["reason"] = "applied"
    return report


__all__ = [
    "apply_own_load_advice",
    "apply_own_recovery_advice",
    "apply_physical_strain_advice",
    "apply_storage_risk_advice",
    "own_load_advice",
    "own_recovery_behavior_report",
    "own_recovery_evidence",
    "physical_strain_behavior_report",
    "physical_strain_evidence",
    "storage_risk_behavior_report",
    "storage_risk_evidence",
]
