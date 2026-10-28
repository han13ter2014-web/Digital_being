"""Оценка угасания интереса без автоматического удаления намерения."""

MIN_STALE_ATTEMPTS = 3


def fading_assessment(agent, entry):
    if not isinstance(entry, dict) or entry.get("resolution"):
        return {"eligible": False, "reason": "resolved"}
    goal = entry.get("evidence_goal") or {}
    if goal.get("status") == "satisfied":
        return {"eligible": False, "reason": "satisfied"}
    history = getattr(agent, "_intention_history", [])
    stale = [item for item in history
             if item.get("target") == entry.get("target")
             and item.get("action") == entry.get("action")
             and item.get("status") in {"performed", "unobserved"}
             and (item.get("evidence_goal") or {}).get("status") == "pending"]
    if len(stale) < MIN_STALE_ATTEMPTS:
        return {"eligible": False, "reason": "not_enough_stale_attempts", "attempts": len(stale)}
    # Это рекомендация освобождения внимания, не мутация state.
    return {"eligible": True, "reason": "repeated_without_new_evidence", "attempts": len(stale),
            "suggested_resolution": "forgotten"}
