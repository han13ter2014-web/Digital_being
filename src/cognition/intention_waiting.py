"""Ожидание новых условий независимо от вытеснения журнала попыток."""

from copy import deepcopy
import json


WAITING_LIMIT = 200


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
    previous = states.get(key)
    if previous and previous.get("resolution", {}).get("kind") in {"cancelled", "completed", "forgotten"}:
        return
    states[key] = deepcopy(entry)
    if len(states) > WAITING_LIMIT:
        oldest = next(iter(states))
        if oldest != key:
            del states[oldest]


def reconcile_waits(agent):
    from src.cognition.intention_evidence import evidence_sources

    for entry in getattr(agent, "_waiting_intentions", {}).values():
        if entry.get("resolution"):
            continue
        goal = entry["evidence_goal"]
        new = sorted(set(evidence_sources(agent, entry["target"])) - set(goal["baseline_sources"]))
        if new:
            goal["new_sources"] = new
            goal["status"] = "satisfied"


def start_new_intention(agent, action, target, *, reason):
    """Явно начать новую попытку, не оживляя старую запись."""
    if not isinstance(target, str) or not target.strip() or not isinstance(reason, str) or not reason.strip():
        raise ValueError("Нужны тема и причина нового намерения")
    key = waiting_key(agent._normalize_action(action), target.strip())
    old = getattr(agent, "_waiting_intentions", {}).get(key)
    if old is not None and not old.get("resolution"):
        raise ValueError("По этой теме уже есть активное намерение")
    from src.cognition.intention_history import begin_intention

    entry = begin_intention(agent, {"action": action, "source": "new_interest",
                                    "params": {"topic": target.strip(), "reason": reason.strip()}})
    entry["new_interest"] = True
    return entry


def resolve_wait(agent, action, target, *, kind, reason):
    if kind not in {"cancelled", "completed", "forgotten"} or not isinstance(reason, str) or not reason.strip():
        raise ValueError("Нужны вид решения и непустая причина")
    key = waiting_key(agent._normalize_action(action), target)
    entry = getattr(agent, "_waiting_intentions", {}).get(key)
    if entry is None:
        return {"status": "not_found"}
    if entry.get("resolution"):
        return {"status": "already_resolved", "resolution": deepcopy(entry["resolution"])}
    reconcile_waits(agent)
    if kind == "completed" and entry["evidence_goal"]["status"] != "satisfied":
        return {"status": "not_satisfied"}
    entry["resolution"] = {"kind": kind, "reason": reason.strip(), "cycle": agent.cycle_count}
    return {"status": kind, "resolution": deepcopy(entry["resolution"])}


def validate_waits(states):
    from src.cognition.intention_history import validate_history

    if not isinstance(states, dict) or len(states) > WAITING_LIMIT:
        raise ValueError("waiting_intentions: нужен ограниченный словарь")
    for key, entry in states.items():
        validate_history([entry])
        resolution = entry.get("resolution")
        if resolution is not None:
            if (not isinstance(resolution, dict)
                    or resolution.get("kind") not in {"cancelled", "completed", "forgotten"}
                    or not isinstance(resolution.get("reason"), str) or not resolution["reason"].strip()
                    or type(resolution.get("cycle")) is not int or resolution["cycle"] < 0):
                raise ValueError("waiting_intentions.resolution")
        if not entry.get("target") or not isinstance(entry.get("evidence_goal"), dict):
            raise ValueError("waiting_intentions: нет темы или критерия")
        if key != waiting_key("explore", entry["target"]):
            raise ValueError("waiting_intentions: несовместимый ключ")
