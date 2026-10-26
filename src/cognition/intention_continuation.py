"""Продолжение последней конкретной попытки — предложение, не обязательство."""

ACTIONS = frozenset({"explore", "decomposition", "synthesis", "ask_user"})


def continuation_candidate(agent):
    history = getattr(agent, "_intention_history", [])
    # Более поздняя попытка той же темы определяет её состояние; другие
    # занятия, включая отдых, не стирают отложенную тему.
    from src.cognition.intention_evidence import finish_evidence_goal

    for entry in history:
        if (entry.get("evidence_goal") or {}).get("status") == "pending":
            finish_evidence_goal(agent, entry)
    seen = set()
    for entry in reversed(history):
        target = entry.get("target")
        action = agent._normalize_action(entry.get("action"))
        if not target or action not in ACTIONS:
            continue
        key = (action, target)
        if key in seen:
            continue
        seen.add(key)
        outcome = entry.get("outcome") or {}
        evidence_goal = entry.get("evidence_goal")
        if evidence_goal is not None:
            if evidence_goal["status"] == "satisfied":
                continue
            from src.cognition.method_feedback import information_context

            context = information_context(agent)
            if any(previous.get("continuation_of")
                   and agent._normalize_action(previous.get("action")) == action
                   and previous.get("target") == target
                   and (previous.get("evidence_goal") or {}).get("status") == "pending"
                   and (previous.get("evidence_goal") or {}).get("information_context") == context
                   for previous in history):
                continue
        elif entry.get("status") == "performed" and outcome.get("had_effect"):
            continue
        if entry.get("status") not in {"performed", "interrupted", "denied", "unobserved", "error"}:
            continue
        if entry.get("cycle", 0) >= agent.cycle_count:
            continue
        if agent.loop_closer.is_stuck(action):
            continue
        candidate = {"source": "intention_continuation", "action": action, "strength": 0.4,
                     "params": {"topic": target, "reason": entry.get("reason", ""),
                                "continuation_of": entry["id"]}}
        if agent._is_candidate_available(candidate):
            return candidate
    return None
