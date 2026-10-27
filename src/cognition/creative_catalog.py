"""Каталог известных работ; не сканирует произвольные файлы как свои."""

from copy import deepcopy

from src.cognition.creative_draft import MAX_DRAFTS, draft_step, leave_draft, validate_draft, LIMIT


def validate_catalog(catalog):
    if not isinstance(catalog, dict) or len(catalog) > MAX_DRAFTS:
        raise ValueError("creative_catalog: недопустимый каталог")
    for identifier, state in catalog.items():
        validate_draft(state)
        if identifier != state["id"]:
            raise ValueError("creative_catalog: несовпадающий id")


def creative_request(intention):
    params = (intention or {}).get("params", {})
    mode = params.get("draft_mode", "continue")
    identifier = params.get("draft_id")
    if mode not in {"continue", "new", "leave"}:
        raise ValueError("Неизвестный draft_mode")
    if identifier is not None and (not isinstance(identifier, str) or len(identifier) != 32
                                   or any(ch not in "0123456789abcdef" for ch in identifier)):
        raise ValueError("Некорректный draft_id")
    if mode == "new" and identifier is not None:
        raise ValueError("Новая работа не принимает старый draft_id")
    reason = params.get("reason", "")
    if mode == "leave" and (not isinstance(reason, str) or not reason.strip()):
        raise ValueError("Нужна причина оставить работу")
    return mode, identifier, reason


def catalog_for(agent):
    catalog = deepcopy(getattr(agent, "_creative_catalog", {}))
    current = getattr(agent, "_creative_draft", None)
    if current is not None:
        validate_draft(current)
        catalog[current["id"]] = deepcopy(current)
    validate_catalog(catalog)
    return catalog


def perform_creative(agent, mode="continue", identifier=None, reason=""):
    catalog = catalog_for(agent)
    current = getattr(agent, "_creative_draft", None)
    if identifier is not None:
        if identifier not in catalog:
            raise ValueError("Работа отсутствует в собственном каталоге")
        selected = catalog[identifier]
    else:
        selected = current
    if mode == "leave":
        if selected is None:
            raise ValueError("Нет выбранной работы")
        updated = leave_draft(selected, reason)
    else:
        if mode == "new" and len(catalog) >= MAX_DRAFTS:
            raise ValueError("Каталог работ заполнен")
        if identifier is not None and (selected.get("status") == "left" or selected["revision"] >= LIMIT):
            raise ValueError("Выбранная работа оставлена или исчерпала лимит редакций")
        updated = draft_step(None if mode == "new" else selected)
    catalog[updated["id"]] = deepcopy(updated)
    validate_catalog(catalog)
    agent._creative_catalog = catalog
    agent._creative_draft = updated
    return updated
