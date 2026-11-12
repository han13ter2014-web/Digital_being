"""Ограниченная история выбранных попыток; не подтверждение достижения цели."""

from copy import deepcopy
import math
from uuid import uuid4

LIMIT = 200
SIMULATION_STATUSES = {"predicted", "unavailable", "resolved", "cancelled"}


def begin_intention(agent, selection):
    from src.cognition.intention_payload import intention_target

    history = getattr(agent, "_intention_history", None)
    if history is None:
        history = agent._intention_history = []
    params = selection.get("params") or {}
    entry = {
        "id": str(uuid4()),
        "cycle": agent.cycle_count,
        "action": str(selection.get("action") or ""),
        "source": str(selection.get("source") or "unknown"),
        "target": intention_target(selection),
        "reason": str(params.get("reason") or selection.get("reasoning") or ""),
        "continuation_of": params.get("continuation_of"),
        "status": "started",
        "outcome": None,
    }
    if selection.get("simulation") is not None:
        entry["simulation"] = deepcopy(selection["simulation"])
    from src.cognition.intention_evidence import begin_evidence_goal

    begin_evidence_goal(agent, entry)
    history.append(entry)
    del history[:-LIMIT]
    return entry


def finish_intention(entry, outcome=None, error=None):
    if error is not None:
        entry["status"] = "error"
        entry["outcome"] = {"error": str(error)[:1000]}
    elif outcome is None:
        entry["status"] = "unobserved"
    else:
        entry["outcome"] = outcome.as_dict()
        entry["status"] = (
            "denied" if outcome.reason.startswith("denied:") else "performed"
        )


def _probability(value, path, *, nullable=False):
    if value is None and nullable:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.0 <= value <= 1.0
    ):
        raise ValueError(f"{path}: нужна конечная вероятность в [0, 1]")


def _validate_simulation(simulation):
    if not isinstance(simulation, dict):
        raise ValueError("intention_history.simulation: нужен словарь")
    for field in (
        "prediction_id",
        "action",
        "target",
        "context_key",
        "predicted_outcome",
    ):
        if not isinstance(simulation.get(field), str):
            raise ValueError(f"intention_history.simulation.{field}: нужна строка")
    if (
        type(simulation.get("schema_version")) is not int
        or simulation["schema_version"] < 1
    ):
        raise ValueError("intention_history.simulation.schema_version")
    if simulation.get("status") not in SIMULATION_STATUSES:
        raise ValueError("intention_history.simulation.status")
    _probability(
        simulation.get("predicted_effect_probability"),
        "intention_history.simulation.predicted_effect_probability",
        nullable=True,
    )
    _probability(
        simulation.get("confidence"), "intention_history.simulation.confidence"
    )
    if type(simulation.get("sample_size")) is not int or simulation["sample_size"] < 0:
        raise ValueError("intention_history.simulation.sample_size")
    adjustment = simulation.get("adjustment", 0.0)
    if (
        isinstance(adjustment, bool)
        or not isinstance(adjustment, (int, float))
        or not math.isfinite(adjustment)
    ):
        raise ValueError("intention_history.simulation.adjustment")
    if (
        simulation.get("had_effect") is not None
        and type(simulation["had_effect"]) is not bool
    ):
        raise ValueError("intention_history.simulation.had_effect")
    if (
        simulation.get("prediction_matched") is not None
        and type(simulation["prediction_matched"]) is not bool
    ):
        raise ValueError("intention_history.simulation.prediction_matched")
    if simulation.get("absolute_error") is not None:
        _probability(
            simulation["absolute_error"], "intention_history.simulation.absolute_error"
        )
    if simulation.get("actual_delta") is not None and not isinstance(
        simulation["actual_delta"], dict
    ):
        raise ValueError("intention_history.simulation.actual_delta")
    for field in ("intention_id", "cancel_reason"):
        if simulation.get(field) is not None and not isinstance(simulation[field], str):
            raise ValueError(f"intention_history.simulation.{field}")


def validate_history(history):
    if not isinstance(history, list) or len(history) > LIMIT:
        raise ValueError("intention_history: нужен ограниченный список")
    for entry in history:
        if not isinstance(entry, dict):
            raise ValueError("intention_history: некорректная запись")
        for key in ("id", "action", "source", "reason"):
            if not isinstance(entry.get(key), str):
                raise ValueError(f"intention_history.{key}: нужна строка")
        if type(entry.get("cycle")) is not int or entry["cycle"] < 0:
            raise ValueError("intention_history.cycle")
        goal = entry.get("evidence_goal")
        if goal is not None:
            if (
                not isinstance(goal, dict)
                or goal.get("kind") != "new_topic_evidence"
                or goal.get("status") not in {"pending", "satisfied"}
            ):
                raise ValueError("intention_history.evidence_goal")
            for field in ("baseline_sources", "new_sources"):
                if not isinstance(goal.get(field), list) or any(
                    not isinstance(source, str) for source in goal[field]
                ):
                    raise ValueError(f"intention_history.evidence_goal.{field}")
        if entry.get("continuation_of") is not None and not isinstance(
            entry["continuation_of"], str
        ):
            raise ValueError("intention_history.continuation_of")
        if entry.get("target") is not None and not isinstance(entry["target"], str):
            raise ValueError("intention_history.target")
        if entry.get("status") not in {
            "started",
            "interrupted",
            "performed",
            "denied",
            "error",
            "unobserved",
        }:
            raise ValueError("intention_history.status")
        if entry.get("outcome") is not None and not isinstance(entry["outcome"], dict):
            raise ValueError("intention_history.outcome")
        if entry.get("simulation") is not None:
            _validate_simulation(entry["simulation"])


def restore_history(history):
    validate_history(history)
    result = deepcopy(history)
    for entry in result:
        if entry["status"] == "started":
            entry["status"] = "interrupted"
            simulation = entry.get("simulation")
            if isinstance(simulation, dict) and simulation.get("status") == "predicted":
                simulation["status"] = "cancelled"
                simulation["cancel_reason"] = "interrupted"
    return result
