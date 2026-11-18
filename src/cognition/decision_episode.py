"""Наблюдаемый контракт выбора: ожидание отдельно, итог отдельно.

Эпизод описывает уже выбранное намерение и не участвует в арбитраже. До
исполнения фиксируются критерий и baseline; после него меняются только
``satisfaction`` и рекомендательное ``resolution``. Никакое поле не завершает
GoalSubsystem и не повышает силу continuation.
"""

from copy import deepcopy
import math


VERSION = 1
CRITERIA = {
    "explore": "new_topic_evidence",
    "play": "play_step",
    "create_draft": "draft_revision",
    "draw": "art_revision",
    "compose_music": "music_revision",
    "rest": "body_recovery",
    "deep_rest": "body_recovery",
    "ask_user": "question_queued",
}
EXPECTED_EVIDENCE = {
    "new_topic_evidence": "новый observation/testimony по теме намерения",
    "play_step": "подтверждённый игровой ход или результат партии",
    "draft_revision": "новая редакция черновика, кроме leave",
    "art_revision": "новая редакция рисунка, кроме leave",
    "music_revision": "новая редакция мелодии, кроме leave",
    "body_recovery": "подтверждённое восстановление тела или консолидация",
    "question_queued": "вопрос фактически поставлен в очередь пользователя",
    "none": "отдельный проверяемый критерий не задан",
}
ACTIVITY_ATTRS = {
    "create_draft": "_creative_draft",
    "draw": "_art_work",
    "compose_music": "_music_work",
}
CREATIVE_FORMS = {
    "create_draft": "text",
    "draw": "art",
    "compose_music": "music",
}
CREATIVE_OPERATIONS = {"new", "continue", "leave"}
SATISFACTIONS = {"pending", "satisfied", "not_applicable"}
RESOLUTIONS = {"none", "continue", "wait", "let_go"}


def _normalized_action(agent, action):
    normalize = getattr(agent, "_normalize_action", None)
    return normalize(action) if callable(normalize) else str(action or "")


def _activity_baseline(agent, action):
    attr = ACTIVITY_ATTRS.get(action)
    if attr is None:
        return {}
    state = getattr(agent, attr, None)
    if not isinstance(state, dict):
        return {"id": None, "revision": 0, "status": None}
    revision = state.get("revision", 0)
    return {
        "id": state.get("id") if isinstance(state.get("id"), str) else None,
        "revision": revision if type(revision) is int and revision >= 0 else 0,
        "status": state.get("status") if isinstance(state.get("status"), str) else None,
    }


def _rest_baseline(agent):
    from config.simulation_config import LR_CONFIG

    energy = getattr(agent, "energy", 0.0)
    maximum = getattr(LR_CONFIG, "ENERGY_MAX", 200)
    return {
        "energy": float(energy) if isinstance(energy, (int, float)) else 0.0,
        "max_energy": float(maximum) if isinstance(maximum, (int, float)) else 200.0,
    }


def _creative_intention(agent, action, selection, entry):
    """Снять намерение с реальной работы, не выбирая и не изменяя её."""
    form = CREATIVE_FORMS.get(action)
    if form is None:
        return None
    params = selection.get("params", {}) if isinstance(selection, dict) else {}
    if not isinstance(params, dict):
        params = {}
    state = getattr(agent, ACTIVITY_ATTRS[action], None)
    if not isinstance(state, dict):
        state = None
    operation = "continue"

    if action == "create_draft":
        requested = params.get("draft_mode", "continue")
        if requested in CREATIVE_OPERATIONS:
            operation = requested
        identifier = params.get("draft_id")
        if operation == "new":
            state = None
        elif isinstance(identifier, str):
            catalog = getattr(agent, "_creative_catalog", {})
            selected = catalog.get(identifier) if isinstance(catalog, dict) else None
            if isinstance(selected, dict):
                state = selected
            elif not isinstance(state, dict) or state.get("id") != identifier:
                state = {"id": identifier, "revision": 0, "status": None}
    else:
        if action == "draw":
            from src.cognition.local_art import ART_LIMIT as revision_limit
        else:
            from src.cognition.local_music import MUSIC_LIMIT as revision_limit
        if state is not None and (
            state.get("status", "active") == "left"
            or state.get("revision", 0) >= revision_limit
        ):
            operation = "new"
            state = None

    if state is None and operation == "continue":
        operation = "new"
    revision = state.get("revision", 0) if state is not None else 0
    status = state.get("status") if state is not None else None
    return {
        "schema_version": 1,
        "form": form,
        "operation": operation,
        "work_id": state.get("id") if state is not None else None,
        "revision": revision if type(revision) is int and revision >= 0 else 0,
        "status": status if isinstance(status, str) else None,
        "reason": entry.get("reason", ""),
    }


def begin_decision_episode(agent, entry, selection=None):
    """Создать ожидание до ``act()``; существующую запись не переписывать."""
    if entry.get("decision_episode") is not None:
        return entry["decision_episode"]
    # ``begin_intention`` уже разобрал selection.params; goal_id сохраняется в
    # самом entry на раннем этапе проводки, поэтому здесь читаем только его.
    action = _normalized_action(agent, entry.get("action"))
    criterion = CRITERIA.get(action, "none")
    baseline = (
        _rest_baseline(agent)
        if criterion == "body_recovery"
        else _activity_baseline(agent, action)
    )
    episode = {
        "version": VERSION,
        "intention_id": entry["id"],
        "action": entry["action"],
        "target": entry.get("target"),
        "source": entry["source"],
        "goal_id": entry.get("goal_id"),
        "reason": entry.get("reason", ""),
        "expected_evidence": EXPECTED_EVIDENCE[criterion],
        "criterion": criterion,
        "baseline": deepcopy(baseline),
        "satisfaction": "not_applicable" if criterion == "none" else "pending",
        "resolution": "none",
    }
    creative = _creative_intention(agent, action, selection, entry)
    if creative is not None:
        episode["creative_intention"] = creative
    entry["decision_episode"] = episode
    return episode


def _confirmed(outcome):
    if outcome is None:
        return False
    if isinstance(outcome, dict):
        return outcome.get("confirmed_result") is True
    return getattr(outcome, "confirmed_result", False) is True


def _revision_advanced(before, after):
    if not isinstance(after, dict) or after.get("status") == "left":
        return False
    revision = after.get("revision")
    if type(revision) is not int or revision < 1:
        return False
    if not isinstance(before, dict):
        return True
    previous = before.get("revision", 0)
    if type(previous) is not int:
        return False
    if before.get("id") != after.get("id"):
        return True
    return revision > previous


def _satisfied(agent, entry, outcome, before, after):
    episode = entry["decision_episode"]
    criterion = episode["criterion"]
    if criterion == "new_topic_evidence":
        return (entry.get("evidence_goal") or {}).get("status") == "satisfied"
    if criterion in {"play_step", "question_queued"}:
        return _confirmed(outcome)
    if criterion in {"draft_revision", "art_revision", "music_revision"}:
        return _revision_advanced(before, after)
    if criterion == "body_recovery":
        return _confirmed(outcome)
    return False


def finish_decision_episode(
    agent, entry, outcome=None, activity_before=None, activity_after=None
):
    """Сверить фактический итог, не изменяя ожидание и не отдавая команд."""
    episode = entry.get("decision_episode")
    if not isinstance(episode, dict):
        return None
    criterion = episode["criterion"]
    status = entry.get("status")
    if criterion == "none":
        episode["satisfaction"] = "not_applicable"
        episode["resolution"] = "none"
        return episode
    if status != "performed":
        episode["satisfaction"] = "pending"
        episode["resolution"] = "none"
        return episode
    if outcome is None:
        # Terminal Effector result подтверждает исполнение, но без адаптера не
        # доказывает новую редакцию или иной специальный замысел.
        episode["satisfaction"] = "not_applicable"
        episode["resolution"] = "none"
        return episode

    if criterion == "body_recovery" and not _confirmed(outcome):
        baseline = episode["baseline"]
        if baseline["energy"] >= baseline["max_energy"]:
            episode["satisfaction"] = "not_applicable"
            episode["resolution"] = "none"
            return episode

    satisfied = _satisfied(agent, entry, outcome, activity_before, activity_after)
    episode["satisfaction"] = "satisfied" if satisfied else "pending"
    if satisfied:
        episode["resolution"] = "wait" if criterion == "question_queued" else "let_go"
    elif criterion == "question_queued" or criterion == "body_recovery":
        episode["resolution"] = "wait"
    elif (
        criterion in {"draft_revision", "art_revision", "music_revision"}
        and isinstance(activity_after, dict)
        and activity_after.get("status") == "left"
    ):
        episode["resolution"] = "let_go"
    else:
        episode["resolution"] = "continue"
    return episode


def _finite_number(value):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _validate_creative_intention(intention, entry):
    path = "intention_history.decision_episode.creative_intention"
    if not isinstance(intention, dict):
        raise ValueError(f"{path}: нужен словарь")
    if (
        type(intention.get("schema_version")) is not int
        or intention["schema_version"] != 1
    ):
        raise ValueError(f"{path}.schema_version")
    action = {"creative_act": "create_draft"}.get(
        entry.get("action"), entry.get("action")
    )
    expected_form = CREATIVE_FORMS.get(action)
    if expected_form is None or intention.get("form") != expected_form:
        raise ValueError(f"{path}.form")
    if intention.get("operation") not in CREATIVE_OPERATIONS:
        raise ValueError(f"{path}.operation")
    work_id = intention.get("work_id")
    if work_id is not None and not isinstance(work_id, str):
        raise ValueError(f"{path}.work_id")
    revision = intention.get("revision")
    if type(revision) is not int or revision < 0:
        raise ValueError(f"{path}.revision")
    if intention.get("status") not in {None, "active", "left"}:
        raise ValueError(f"{path}.status")
    if not isinstance(intention.get("reason"), str):
        raise ValueError(f"{path}.reason")
    if intention["reason"] != entry.get("reason", ""):
        raise ValueError(f"{path}.reason: не совпадает с намерением")
    if intention["operation"] == "new" and (
        work_id is not None or revision != 0 or intention.get("status") is not None
    ):
        raise ValueError(
            f"{path}.operation: новая работа не принимает старое состояние"
        )


def validate_decision_episode(episode, entry):
    """Проверить границы checkpoint и тождество контракта с намерением."""
    path = "intention_history.decision_episode"
    if not isinstance(episode, dict):
        raise ValueError(f"{path}: нужен словарь")
    if type(episode.get("version")) is not int or episode["version"] != VERSION:
        raise ValueError(f"{path}.version")
    for field in (
        "intention_id",
        "action",
        "source",
        "reason",
        "expected_evidence",
    ):
        if not isinstance(episode.get(field), str):
            raise ValueError(f"{path}.{field}: нужна строка")
    if episode.get("intention_id") != entry.get("id"):
        raise ValueError(f"{path}.intention_id: не совпадает с намерением")
    for field in ("action", "source", "reason", "target"):
        if episode.get(field) != entry.get(field):
            raise ValueError(f"{path}.{field}: не совпадает с намерением")
    goal_id = episode.get("goal_id")
    if (
        goal_id is not None
        and not isinstance(goal_id, str)
        and type(goal_id) is not int
    ):
        raise ValueError(f"{path}.goal_id")
    criterion = episode.get("criterion")
    if criterion not in set(CRITERIA.values()) | {"none"}:
        raise ValueError(f"{path}.criterion")
    if not isinstance(episode.get("baseline"), dict):
        raise ValueError(f"{path}.baseline: нужен словарь")
    baseline = episode["baseline"]
    if criterion in {"draft_revision", "art_revision", "music_revision"}:
        revision = baseline.get("revision")
        if type(revision) is not int or revision < 0:
            raise ValueError(f"{path}.baseline.revision")
        for field in ("id", "status"):
            if baseline.get(field) is not None and not isinstance(
                baseline.get(field), str
            ):
                raise ValueError(f"{path}.baseline.{field}")
    if criterion == "body_recovery":
        if not _finite_number(baseline.get("energy")):
            raise ValueError(f"{path}.baseline.energy")
        if (
            not _finite_number(baseline.get("max_energy"))
            or baseline["max_energy"] <= 0
        ):
            raise ValueError(f"{path}.baseline.max_energy")
    # Поле additive: старые decision episodes без него остаются валидными.
    if episode.get("creative_intention") is not None:
        _validate_creative_intention(episode["creative_intention"], entry)
    satisfaction = episode.get("satisfaction")
    if satisfaction not in SATISFACTIONS:
        raise ValueError(f"{path}.satisfaction")
    if episode.get("resolution") not in RESOLUTIONS:
        raise ValueError(f"{path}.resolution")
    if satisfaction == "satisfied" and entry.get("status") != "performed":
        raise ValueError(f"{path}.satisfaction: исполнение не подтверждено")
    if criterion == "none":
        if satisfaction != "not_applicable":
            raise ValueError(f"{path}.satisfaction: критерий не задан")
        if episode.get("resolution") != "none":
            raise ValueError(f"{path}.resolution: критерий не задан")
