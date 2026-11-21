"""История творческих форм и явные связи продолжения конкретных работ."""

from src.cognition.decision_episode import CREATIVE_FORMS, creative_intention


def _creative_entries(agent):
    history = getattr(agent, "_intention_history", [])
    if not isinstance(history, list):
        return []
    entries = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        episode = entry.get("decision_episode")
        intention = (
            episode.get("creative_intention") if isinstance(episode, dict) else None
        )
        if isinstance(intention, dict) and intention.get("form") in set(
            CREATIVE_FORMS.values()
        ):
            entries.append((entry, intention))
    return entries


def _continuation_for(entries, form, work_id):
    """Найти подтверждённое намерение именно этой работы, не просто формы."""
    for entry, intention in reversed(entries):
        if intention.get("form") != form or entry.get("status") != "performed":
            continue
        episode = entry.get("decision_episode") or {}
        result = episode.get("creative_result")
        if isinstance(result, dict):
            if result.get("work_id") == work_id:
                return entry.get("id")
        elif intention.get("work_id") == work_id:
            # Совместимость с записями P3-C-0, у которых ещё не было результата.
            return entry.get("id")
    return None


def with_creative_history(agent, candidates):
    """Дополнить кандидатов историей, не меняя работы, файлы или их силу."""
    entries = _creative_entries(agent)
    latest = {}
    for entry, intention in entries:
        # Только подтверждённая работа обновляет recency формы. Ошибка,
        # отказ или прерванное намерение не должны отодвигать форму в
        # ротации, будто творческий акт действительно состоялся.
        if entry.get("status") != "performed":
            continue
        episode = entry.get("decision_episode") or {}
        result = episode.get("creative_result")
        if isinstance(result, dict) and result.get("form") == intention["form"]:
            latest[intention["form"]] = entry

    decorated = []
    for candidate in candidates:
        action = agent._normalize_action(candidate.get("action"))
        snapshot = creative_intention(agent, action, candidate, {"reason": ""})
        if snapshot is None:
            decorated.append(candidate)
            continue
        params = dict(candidate.get("params") or {})
        form = snapshot["form"]
        operation = snapshot["operation"]
        work_id = snapshot["work_id"]
        last = latest.get(form)
        last_cycle = last.get("cycle") if isinstance(last, dict) else None
        if type(last_cycle) is not int or last_cycle < 0:
            last_cycle = None
        continuation_of = None
        if operation == "continue" and work_id is not None:
            continuation_of = _continuation_for(entries, form, work_id)
        params.update(
            {
                "creative_form": form,
                "creative_operation": operation,
                "creative_work_id": work_id,
                "creative_last_cycle": last_cycle,
                "continuation_of": continuation_of,
            }
        )
        decorated.append({**candidate, "params": params})
    return decorated
