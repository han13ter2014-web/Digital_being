"""Варианты творческого занятия для существующего арбитра."""

from src.cognition.creative_catalog import catalog_for
from src.cognition.creative_draft import (
    MAX_DRAFTS,
    draft_available,
    draft_has_external_changes,
)
from src.core.activity_workspace import workspace_for


def creative_choices(agent, candidate):
    catalog = catalog_for(agent)
    params = dict(candidate.get("params") or {})
    workspace = workspace_for(agent)
    if "draft_mode" in params or "draft_id" in params:
        selected = catalog.get(params.get("draft_id"))
        if (
            params.get("draft_mode", "continue") == "continue"
            and selected is not None
            and draft_has_external_changes(selected, workspace=workspace)
        ):
            return []
        return [candidate]
    strength = float(candidate.get("strength", 0.5))
    choices = []
    for state in catalog.values():
        if state.get("status", "active") != "active":
            continue
        if draft_has_external_changes(state, workspace=workspace):
            continue
        choices.append(
            {
                **candidate,
                "params": {
                    **params,
                    "draft_mode": "continue",
                    "draft_id": state["id"],
                    "reason": "Продолжить доступный собственный черновик",
                },
            }
        )
    if len(catalog) < MAX_DRAFTS and draft_available(None, workspace=workspace):
        choices.append(
            {
                **candidate,
                "strength": strength if not choices else strength * 0.8,
                "params": {
                    **params,
                    "draft_mode": "new",
                    "reason": "Начать другую текстовую композицию",
                },
            }
        )
    return choices
