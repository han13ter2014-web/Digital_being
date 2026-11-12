"""Связь выбора действия с InternalSimulator и фактическим ActionOutcome."""

from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from config.simulation_config import LR_CONFIG, SIM_CONFIG
from src.cognition.intention_payload import intention_target
from src.core.buffered_logger import get_logger


SUPPORTED_ACTIONS = frozenset(
    {
        "explore",
        "decomposition",
        "synthesis",
        "hypothesis",
        "web_search",
    }
)


def _mode(agent, mode=None) -> str:
    value = mode or getattr(SIM_CONFIG, "INTERNAL_SIMULATION_MODE", "shadow")
    return value if value in {"off", "shadow", "advisor"} else "shadow"


def _context(agent, action: str, target: str) -> dict:
    searcher = getattr(agent, "web_searcher", None)
    try:
        web_enabled = bool(searcher is not None and searcher.is_enabled)
    except Exception:
        web_enabled = False
    maximum = float(getattr(LR_CONFIG, "ENERGY_MAX", 200.0) or 1.0)
    ratio = float(getattr(agent, "energy", 0.0) or 0.0) / maximum
    low_ratio = float(getattr(LR_CONFIG, "LOW_ENERGY_RATIO", 0.25))
    return {
        "action": action,
        "target": str(target or ""),
        "web_enabled": web_enabled,
        "energy_band": "low" if ratio <= low_ratio else "normal",
    }


def _neutral_prediction(action: str, target: str, error: str = "") -> dict:
    result = {
        "prediction_id": str(uuid4()),
        "schema_version": 1,
        "action": action,
        "target": target,
        "context_key": "",
        "status": "unavailable",
        "predicted_effect_probability": None,
        "confidence": 0.0,
        "sample_size": 0,
        "predicted_outcome": "прогноз недоступен",
        "adjustment": 0.0,
    }
    if error:
        result["error"] = error[:500]
    return result


def predict_candidates(agent, candidates, *, mode=None) -> tuple[list[dict], dict]:
    """Добавляет прогнозы в копии кандидатов, не меняя их силу."""
    selected_mode = _mode(agent, mode)
    diagnostics = {
        "mode": selected_mode,
        "supported_actions": sorted(SUPPORTED_ACTIONS),
        "predicted": 0,
        "unavailable": 0,
        "errors": [],
    }
    copies = deepcopy(list(candidates))
    if selected_mode == "off":
        return copies, diagnostics
    simulator = getattr(agent, "internal_simulator", None)
    for candidate in copies:
        action = agent._normalize_action(candidate.get("action"))
        if action not in SUPPORTED_ACTIONS:
            continue
        target = ""
        try:
            target = intention_target(candidate) or ""
            if not target and action == "decomposition":
                # Обработчик выбирает тему внутри act(); прогноз обязан
                # использовать ту же тему до выполнения, иначе фактический
                # опыт никогда не совпадёт с пустым контекстом прогноза.
                picker = getattr(agent, "_pick_decomposable_target", None)
                if callable(picker):
                    target = str(picker(remember=False) or "")
            context = _context(agent, action, target)
            prediction = simulator.simulate_outcome(
                action,
                {
                    "web_enabled": context["web_enabled"],
                    "energy_band": context["energy_band"],
                },
                context,
            ).to_dict()
            candidate["simulation"] = prediction
            diagnostics[
                "predicted" if prediction["status"] == "predicted" else "unavailable"
            ] += 1
        except Exception as exc:
            get_logger().log(f"[INTERNAL_SIMULATION] Prediction error: {exc}")
            candidate["simulation"] = _neutral_prediction(
                action, target if "target" in locals() else "", str(exc)
            )
            diagnostics["unavailable"] += 1
            diagnostics["errors"].append(str(exc)[:500])
    return copies, diagnostics


def learn_from_selected_action(
    agent, selection, intention_entry, outcome
) -> dict | None:
    """Сохраняет выполненный исход и сравнивает его с выбранным прогнозом."""
    if _mode(agent) == "off" or outcome is None:
        return None
    if str(outcome.reason or "").startswith("denied:"):
        cancel_selected_prediction(agent, intention_entry, outcome.reason)
        return None
    action = agent._normalize_action(outcome.action or selection.get("action"))
    if action not in SUPPORTED_ACTIONS:
        return None
    simulator = getattr(agent, "internal_simulator", None)
    if simulator is None:
        return None
    target = str(intention_entry.get("target") or outcome.topic or "")
    context = _context(agent, action, target)
    prediction = intention_entry.get("simulation") or selection.get("simulation") or {}
    prediction_id = (
        prediction.get("prediction_id")
        if prediction.get("status") == "predicted"
        else None
    )
    learned = simulator.learn_from_outcome(
        action,
        context,
        outcome.summary,
        bool(outcome.had_effect),
        prediction_id=prediction_id,
        target=target,
        context_key=prediction.get("context_key") or None,
        actual_delta=outcome.delta.as_dict(),
        intention_id=intention_entry.get("id"),
        confidence=float(prediction.get("confidence", 0.5) or 0.0),
    )
    report = {
        "action": action,
        "target": target,
        "had_effect": bool(outcome.had_effect),
        "actual_delta": outcome.delta.as_dict(),
        "real_event_stored": not learned["duplicate"],
    }
    feedback = learned.get("prediction")
    if feedback:
        report.update(feedback)
        if isinstance(intention_entry.get("simulation"), dict):
            intention_entry["simulation"].update(deepcopy(feedback))
            intention_entry["simulation"]["status"] = "resolved"
    return report


def cancel_selected_prediction(agent, intention_entry, reason) -> None:
    """Отказ или сбой исполнения не становятся опытом неэффективности."""
    prediction = intention_entry.get("simulation")
    if not isinstance(prediction, dict) or prediction.get("status") != "predicted":
        return
    simulator = getattr(agent, "internal_simulator", None)
    if simulator is not None and prediction.get("prediction_id"):
        simulator.cancel_prediction(prediction["prediction_id"], str(reason))
    prediction["status"] = "cancelled"
    prediction["cancel_reason"] = str(reason)


__all__ = [
    "SUPPORTED_ACTIONS",
    "predict_candidates",
    "learn_from_selected_action",
    "cancel_selected_prediction",
]
