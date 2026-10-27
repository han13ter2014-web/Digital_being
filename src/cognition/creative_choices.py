"""Варианты творческого занятия для существующего арбитра."""

from src.cognition.creative_catalog import catalog_for
from src.cognition.creative_draft import LIMIT, MAX_DRAFTS, draft_available


def creative_choices(agent, candidate):
    catalog = catalog_for(agent)
    params = dict(candidate.get("params") or {})
    if "draft_mode" in params or "draft_id" in params:
        return [candidate]
    strength = float(candidate.get("strength", 0.5))
    choices = []
    for state in catalog.values():
        if state.get("status", "active") != "active":
            continue
        if state["revision"] < LIMIT:
            choices.append({**candidate, "params": {**params, "draft_mode": "continue",
                            "draft_id": state["id"], "reason": "Продолжить доступный собственный черновик"}})
        elif state == getattr(agent, "_creative_draft", None):
            choices.append({**candidate, "strength": strength * 0.8,
                            "params": {**params, "draft_mode": "leave", "draft_id": state["id"],
                                       "reason": "Достигнут лимит редакций; оставить текст как есть"}})
    if len(catalog) < MAX_DRAFTS and draft_available(None):
        choices.append({**candidate, "strength": strength if not choices else strength * 0.8,
                        "params": {**params, "draft_mode": "new", "reason": "Начать другую текстовую композицию"}})
    return choices
