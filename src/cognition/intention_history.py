"""Ограниченная история выбранных попыток; не подтверждение достижения цели."""

from copy import deepcopy
from uuid import uuid4

LIMIT = 200


def begin_intention(agent, selection):
    from src.cognition.intention_payload import intention_target

    history = getattr(agent, "_intention_history", None)
    if history is None:
        history = agent._intention_history = []
    params = selection.get("params") or {}
    entry = {"id": str(uuid4()), "cycle": agent.cycle_count,
             "action": str(selection.get("action") or ""),
             "source": str(selection.get("source") or "unknown"),
             "target": intention_target(selection),
             "reason": str(params.get("reason") or selection.get("reasoning") or ""),
             "continuation_of": params.get("continuation_of"),
             "status": "started", "outcome": None}
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
        entry["status"] = "denied" if outcome.reason.startswith("denied:") else "performed"


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
            if not isinstance(goal, dict) or goal.get("kind") != "new_topic_evidence" or goal.get("status") not in {"pending", "satisfied"}:
                raise ValueError("intention_history.evidence_goal")
            for field in ("baseline_sources", "new_sources"):
                if not isinstance(goal.get(field), list) or any(not isinstance(source, str) for source in goal[field]):
                    raise ValueError(f"intention_history.evidence_goal.{field}")
        if entry.get("continuation_of") is not None and not isinstance(entry["continuation_of"], str):
            raise ValueError("intention_history.continuation_of")
        if entry.get("target") is not None and not isinstance(entry["target"], str):
            raise ValueError("intention_history.target")
        if entry.get("status") not in {"started", "interrupted", "performed", "denied", "error", "unobserved"}:
            raise ValueError("intention_history.status")
        if entry.get("outcome") is not None and not isinstance(entry["outcome"], dict):
            raise ValueError("intention_history.outcome")


def restore_history(history):
    validate_history(history)
    result = deepcopy(history)
    for entry in result:
        if entry["status"] == "started":
            entry["status"] = "interrupted"
    return result
