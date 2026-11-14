"""Конкретное неисследовательское дело не получает учебного прогресса."""

from copy import deepcopy

ACTIVITIES = {
    "play": "play",
    "create_draft": "create_draft",
    "creative_act": "create_draft",
    "draw": "draw",
    "compose_music": "compose_music",
}

CRITERIA = {
    "play": "play_round",
    "create_draft": "draft_revision",
    "draw": "art_revision",
    "compose_music": "music_revision",
}


def goal_work_key(goal):
    """Тождество работы: предмет + канонический способ, а не формулировка.

    «Картирование: X» и «Открыть новую область: X» обе означают explore(X)
    и не должны занимать две позиции очереди. Другой способ (например,
    синтез X) остаётся самостоятельной целью. Для целей без action_hint
    сохраняется прежняя дедупликация по названию.
    """
    from src.core.agent_act import classify_decision
    from src.memory.knowledge_quality import normalize_concept_name

    title = str(goal.get("title") or "").strip()
    origin = goal.get("motivation_origin")
    if not isinstance(origin, dict):
        origin = goal
    action = origin.get("action_hint")
    if not action or ":" not in title:
        return ("title", title.casefold())
    subject = normalize_concept_name(title.split(":", 1)[1].strip())
    if not subject:
        return ("title", title.casefold())
    return ("work", classify_decision(str(action)), subject.casefold())


def activate_next_pending_goal(goals):
    """Активирует новую работу, а старые дубли завершённых целей пропускает.

    Дубль не считается выполненным: награда и ``completed_goals`` здесь не
    меняются. Общая функция нужна обоим путям активации — GoalSubsystem и
    legacy fallback — чтобы их правила не расходились.
    """
    completed = {
        goal_work_key(goal): goal.get("id")
        for goal in goals
        if goal.get("status") == "completed"
    }
    for goal in goals:
        if goal.get("status") != "pending":
            continue
        duplicate_of = completed.get(goal_work_key(goal))
        if duplicate_of is not None:
            goal["status"] = "duplicate"
            goal["duplicate_of"] = duplicate_of
            continue
        goal["status"] = "active"
        return goal
    return None


def attach_activity(agent, goal_id, generated):
    goal = next(g for g in agent.goals if g["id"] == goal_id)
    goal["motivation_origin"] = deepcopy(
        {
            key: generated[key]
            for key in (
                "source",
                "need",
                "drive",
                "priority",
                "action_hint",
                "type",
                "metadata",
                "retry_reason",
            )
            if key in generated
        }
    )
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
    return {
        "action": action,
        "source": "own_activity",
        "strength": 0.4,
        "params": {"activity_goal_id": goal["id"], "reason": goal["title"]},
    }


def active_goal_candidate(agent):
    """Предлагает следующий шаг активной когнитивной цели арбитру.

    Это не отдельный исполнитель и не обход арбитра: используется сохранённый
    ``action_hint``, а доступность, тело и выход из тупика работают как у
    остальных кандидатов. Для карты выбирается ещё не засчитанный сосед по
    ментальному графу, иначе «Картирование: X» бесконечно повторяет сам X.
    """
    goal = getattr(agent, "active_goal", None)
    if not isinstance(goal, dict) or isinstance(goal.get("activity"), dict):
        return None
    origin = goal.get("motivation_origin")
    if not isinstance(origin, dict):
        return None
    action = origin.get("action_hint")
    title = str(goal.get("title") or "").strip()
    if not action or ":" not in title:
        return None

    from src.core.agent_act import classify_decision

    if classify_decision(str(action)) == "default":
        return None
    subject = title.split(":", 1)[1].strip()
    if not subject:
        return None
    target = subject

    if origin.get("type") == "mapping":
        progress = getattr(agent, "_goal_progress", {}).get(goal.get("id"), {})
        matched = {
            str(item).strip().lower()
            for item in (progress.get("matched_concepts") or [])
        }
        try:
            related = (
                agent.mental_models.find_related_concepts(subject, max_distance=1) or []
            )
        except (AttributeError, TypeError):
            related = []
        nodes = sorted(
            (node for node in related if getattr(node, "name", None)),
            key=lambda node: (
                float(getattr(node, "confidence", 0.0) or 0.0),
                str(node.name),
            ),
        )
        for node in nodes:
            name = str(node.name).strip()
            if (
                name.lower() not in matched
                and name != subject
                and agent._is_learnable(name)
                and agent._is_meaningful_topic(name)
                and not agent._is_meta_topic(name)
            ):
                target = name
                break

    try:
        priority = float(origin.get("priority", 0.4) or 0.4)
    except (TypeError, ValueError):
        priority = 0.4
    return {
        "action": action,
        "source": "active_goal",
        "strength": min(0.75, max(0.35, priority + 0.15)),
        "params": {
            "concept": target,
            "goal_id": goal.get("id"),
            "reason": title,
        },
    }


def record_activity_step(agent, intention, action, before, after):
    goal_id = (intention.get("params") or {}).get("activity_goal_id")
    goal = next((g for g in agent.goals if g["id"] == goal_id), None)
    if (
        not goal
        or goal.get("status") != "active"
        or goal.get("activity", {}).get("action") != action
    ):
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
    goal["activity"]["last_step"] = {
        "cycle": agent.cycle_count,
        "artifact": deepcopy(after),
    }
    goal["activity"]["steps"] = goal["activity"].get("steps", 0) + 1
    criterion = goal["activity"].get("criterion")
    satisfied = (
        (
            action == "play"
            and criterion == "play_round"
            and after.get("result") is not None
        )
        or (action == "play" and criterion == "play_turn")
        or (action == "create_draft" and criterion == "draft_revision")
        or (action == "draw" and criterion == "art_revision")
        or (action == "compose_music" and criterion == "music_revision")
    )
    if satisfied:
        goal["activity"]["satisfied_at"] = agent.cycle_count
        agent.complete_goal(goal_id)
