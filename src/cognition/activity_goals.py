"""Конкретное неисследовательское дело не получает учебного прогресса."""

from copy import deepcopy

ACTIVITIES = {"play": "play", "create_draft": "create_draft", "creative_act": "create_draft",
              "draw": "draw", "compose_music": "compose_music"}

CRITERIA = {"play": "play_round", "create_draft": "draft_revision", "draw": "art_revision",
            "compose_music": "music_revision"}


def attach_activity(agent, goal_id, generated):
    goal = next(g for g in agent.goals if g["id"] == goal_id)
    goal["motivation_origin"] = deepcopy({key: generated[key] for key in
        ("source", "need", "drive", "priority", "action_hint", "type", "metadata") if key in generated})
    action = ACTIVITIES.get(generated.get("action_hint"))
    if action:
        goal["activity"] = {"action": action, "criterion": CRITERIA[action]}


def activity_candidate(agent):
    goal = getattr(agent, "active_goal", None)
    if not goal or not isinstance(goal.get("activity"), dict):
        return None
    action = goal["activity"].get("action")
    if action not in {"play", "create_draft", "draw", "compose_music"}:
        return None
    return {"action": action, "source": "own_activity", "strength": 0.4,
            "params": {"activity_goal_id": goal["id"], "reason": goal["title"]}}


def record_activity_step(agent, intention, action, before, after):
    goal_id = (intention.get("params") or {}).get("activity_goal_id")
    goal = next((g for g in agent.goals if g["id"] == goal_id), None)
    if not goal or goal.get("status") != "active" or goal.get("activity", {}).get("action") != action:
        return
    if after is None or before == after:
        return
    if action == "create_draft" and after.get("status") == "left":
        return
    if action == "draw" and after.get("status") == "left":
        return
    if action == "compose_music" and after.get("status") == "left":
        return
    # Факт шага не равен выполнению всего дела и не выдаёт награду за знание.
    goal["activity"]["last_step"] = {"cycle": agent.cycle_count,
                                     "artifact": deepcopy(after)}
    goal["activity"]["steps"] = goal["activity"].get("steps", 0) + 1
    criterion = goal["activity"].get("criterion")
    satisfied = ((action == "play" and criterion == "play_round" and after.get("result") is not None)
                 or (action == "play" and criterion == "play_turn")
                 or (action == "create_draft" and criterion == "draft_revision")
                 or (action == "draw" and criterion == "art_revision")
                 or (action == "compose_music" and criterion == "music_revision"))
    if satisfied:
        goal["activity"]["satisfied_at"] = agent.cycle_count
        agent.complete_goal(goal_id)
