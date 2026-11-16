"""Текущая редакция черновика из проверяемого внутреннего материала."""

from copy import deepcopy
import hashlib
import json
from uuid import uuid4

from src.core.activity_workspace import ActivityWorkspace
from src.cognition.creative_context import (
    fallback_creative_context,
    validate_creative_context,
)


MAX_DRAFTS = 32


def validate_draft(state):
    if not isinstance(state, dict):
        raise ValueError("creative_draft: нужен словарь")
    identifier = state.get("id")
    if (
        not isinstance(identifier, str)
        or len(identifier) != 32
        or any(ch not in "0123456789abcdef" for ch in identifier)
    ):
        raise ValueError("creative_draft.id")
    if type(state.get("revision")) is not int or state["revision"] < 1:
        raise ValueError("creative_draft.revision")
    if state.get("status", "active") not in {"active", "left"}:
        raise ValueError("creative_draft.status")
    if state.get("status") == "left" and (
        not isinstance(state.get("leave_reason"), str)
        or not state["leave_reason"].strip()
    ):
        raise ValueError("creative_draft.leave_reason")
    for key in ("theme", "sha256"):
        if not isinstance(state.get(key), str) or not state[key]:
            raise ValueError(f"creative_draft.{key}")
    for key in ("origin_context", "creative_context"):
        if key in state and state[key] is not None:
            validate_creative_context(state[key])


def leave_draft(state, reason):
    validate_draft(state)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Нужна причина оставить черновик")
    if state.get("status") == "left":
        return dict(state)
    return {**state, "status": "left", "leave_reason": reason.strip()[:1000]}


def draft_available(state=None, workspace=None):
    if state is not None:
        validate_draft(state)
        if state.get("status", "active") == "active":
            return True
    workspace = workspace or ActivityWorkspace()
    return len(workspace.list()) < MAX_DRAFTS


def _single_line(value, limit=500):
    return " ".join(str(value).split())[:limit].strip()


def _choice_digest(context, revision):
    payload = json.dumps(
        {"context": context, "revision": revision},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).digest()


def _emotional_form(context):
    components = context["emotions"]
    if not components:
        return "neutral"
    total = sum(item["weight"] for item in components)
    if total <= 0:
        return "neutral"
    valence = sum(item["valence"] * item["weight"] for item in components) / total
    arousal = sum(item["arousal"] * item["weight"] for item in components) / total
    if valence <= -0.2:
        return "strained"
    if arousal >= 0.65:
        return "surge"
    if valence >= 0.35:
        return "warm"
    return "neutral"


def compose_line(context, revision=1):
    """Одна воспроизводимая строка из эмоций, памяти и реальных мыслей."""
    validate_creative_context(context)
    if type(revision) is not int or revision < 1:
        raise ValueError("creative_draft.revision")
    digest = _choice_digest(context, revision)
    theme = _single_line(context["theme"], 160)
    forms = {
        "neutral": (
            "{theme} оставляет место для следующей строки{material}.",
            "Между словами остаётся {theme}{material}.",
        ),
        "warm": (
            "В теме «{theme}» остаётся тёплый след{material}.",
            "{theme} приближается к желанному берегу{material}.",
        ),
        "strained": (
            "{theme} звучит приглушённо{material}.",
            "В теме «{theme}» остаётся нерешённая тяжесть{material}.",
        ),
        "surge": (
            "{theme} меняет очертания быстрее ожидания{material}.",
            "Тема «{theme}» разрывает привычный ритм{material}.",
        ),
    }
    templates = forms[_emotional_form(context)]
    template = templates[int.from_bytes(digest[:8], "big") % len(templates)]
    material_items = [("память", item["content"]) for item in context["memories"]] + [
        ("мысль", item["text"]) for item in context["thoughts"]
    ]
    material = ""
    if material_items:
        kind, text = material_items[
            int.from_bytes(digest[8:16], "big") % len(material_items)
        ]
        material = f"; {kind}: «{_single_line(text, 400)}»"
    return template.format(theme=theme.capitalize(), material=material)


def _bounded_content(previous, line, theme, limit):
    """Хранить текущую редакцию, а не бесконечный журнал всех версий.

    При исчерпании файловой квоты самые старые строки уходят из видимого
    черновика. Работа остаётся открытой; origin/current context и номер
    редакции продолжают сохраняться в состоянии.
    """
    header = f"Черновик: {theme}\n\n"
    body = previous[len(header) :] if previous.startswith(header) else previous
    lines = [item for item in body.splitlines() if item.strip()]
    lines.append(line)
    content = header + "\n".join(lines)
    while len(content.encode("utf-8")) > limit and len(lines) > 1:
        lines.pop(0)
        content = header + "\n".join(lines)
    if len(content.encode("utf-8")) > limit:
        raise ValueError("Строка черновика превышает файловую квоту")
    return content


def draft_step(state=None, *, workspace=None, context=None, theme=None):
    workspace = workspace or ActivityWorkspace()
    sandbox = workspace.sandbox
    if state is not None:
        validate_draft(state)
    if context is None:
        context = fallback_creative_context(
            theme or (state.get("theme") if state is not None else "тишина")
        )
    else:
        validate_creative_context(context)
    if state is not None and state.get("status", "active") == "active":
        if context["theme"] != state["theme"]:
            raise ValueError("Тема существующей работы не должна меняться")

    if state is None or state.get("status") == "left":
        # Квота ограничивает только создание новых текстов, не продолжение.
        if sum(1 for _ in sandbox.root.glob("*.txt")) >= MAX_DRAFTS:
            raise ValueError(
                "Рабочая область черновиков заполнена; новые файлы не создаются"
            )
        identifier = uuid4().hex
        theme = context["theme"]
        previous = ""
        revision = 1
        origin_context = deepcopy(context)
    else:
        identifier, theme = state["id"], state["theme"]
        # Прежняя редакция может остаться в общем корне до перехода (5C):
        # копируем её в каталог жизни, оригинал не трогаем.
        workspace.ensure_from_legacy(f"{identifier}.txt")
        previous = sandbox.read_text(f"{identifier}.txt")
        if hashlib.sha256(previous.encode("utf-8")).hexdigest() != state["sha256"]:
            raise ValueError(
                "Черновик изменён извне; автоматическая перезапись отменена"
            )
        revision = state["revision"] + 1
        origin_context = deepcopy(state.get("origin_context"))

    line = compose_line(context, revision)
    content = _bounded_content(previous, line, theme, sandbox.max_file_bytes)
    workspace.write(
        f"{identifier}.txt",
        content,
        overwrite=bool(previous),
        kind="creative",
        metadata={"activity": "draft", "work_id": identifier, "revision": revision},
    )
    if sandbox.read_text(f"{identifier}.txt") != content:
        raise IOError("Не совпало обратное чтение черновика")
    updated = {
        "id": identifier,
        "theme": theme,
        "revision": revision,
        "status": "active",
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "creative_context": deepcopy(context),
    }
    if origin_context is not None:
        updated["origin_context"] = origin_context
    validate_draft(updated)
    return updated
