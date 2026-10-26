"""Неудачный способ не отменяет желание; новая информация допускает повтор."""

import hashlib
import json


def information_context(agent):
    # Не используем счётчики встреч, уверенность, время и состояние тела:
    # повтор собственной записи и отдых не являются новым источником.
    data = {
        "knowledge": getattr(agent, "knowledge_base", {}),
        "definitions": getattr(agent, "_known_definitions", {}),
        "web_enabled": bool(getattr(getattr(agent, "web_searcher", None), "is_enabled", False)),
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def prepare_candidates(agent, candidates):
    context = information_context(agent)
    previous = getattr(agent, "_method_information_context", None)
    released = []
    if previous is not None and previous != context:
        for action in agent.loop_closer.stuck_actions():
            if agent.loop_closer.is_productive(action) and not agent.loop_closer.denied_streak(action):
                agent.loop_closer.reset(action)
                released.append(action)
    agent._method_information_context = context
    allowed, deferred = [], []
    for candidate in candidates:
        action = agent._normalize_action(candidate.get("action"))
        if agent.loop_closer.is_stuck(action):
            deferred.append({"action": candidate.get("action"), "normalized_action": action,
                             "source": candidate.get("source"),
                             "reason": "denied" if agent.loop_closer.denied_streak(action) else "no_effect",
                             "streak": agent.loop_closer.no_effect_streak(action)})
        else:
            allowed.append(candidate)
    return allowed, {"deferred": deferred, "released": released,
                     "release_reason": "new_information_context" if released else None}
