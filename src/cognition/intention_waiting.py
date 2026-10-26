"""Ожидание новых условий независимо от вытеснения журнала попыток."""

from copy import deepcopy
import json


def waiting_key(action, target):
    return json.dumps([action, target], ensure_ascii=False)


def remember_wait(agent, entry):
    goal = entry.get("evidence_goal")
    if not goal or not entry.get("continuation_of") or entry.get("status") not in {"performed", "unobserved"}:
        return
    states = getattr(agent, "_waiting_intentions", None)
    if states is None:
        states = agent._waiting_intentions = {}
    key = waiting_key(agent._normalize_action(entry["action"]), entry["target"])
    states[key] = deepcopy(entry)


def reconcile_waits(agent):
    from src.cognition.intention_evidence import evidence_sources

    for entry in getattr(agent, "_waiting_intentions", {}).values():
        goal = entry["evidence_goal"]
        new = sorted(set(evidence_sources(agent, entry["target"])) - set(goal["baseline_sources"]))
        if new:
            goal["new_sources"] = new
            goal["status"] = "satisfied"


def validate_waits(states):
    from src.cognition.intention_history import validate_history

    if not isinstance(states, dict):
        raise ValueError("waiting_intentions: нужен словарь")
    for key, entry in states.items():
        validate_history([entry])
        if not entry.get("target") or not isinstance(entry.get("evidence_goal"), dict):
            raise ValueError("waiting_intentions: нет темы или критерия")
        if key != waiting_key("explore", entry["target"]):
            raise ValueError("waiting_intentions: несовместимый ключ")
