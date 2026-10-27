"""Небольшой шаблонный черновик — артефакт, не утверждение о мире."""

import hashlib
import random
from uuid import uuid4

from src.core.paths import data_path
from src.delamain.sandbox import Sandbox


LIMIT = 8
MAX_DRAFTS = 32


def validate_draft(state):
    if not isinstance(state, dict):
        raise ValueError("creative_draft: нужен словарь")
    identifier = state.get("id")
    if not isinstance(identifier, str) or len(identifier) != 32 or any(ch not in "0123456789abcdef" for ch in identifier):
        raise ValueError("creative_draft.id")
    if type(state.get("revision")) is not int or not 1 <= state["revision"] <= LIMIT:
        raise ValueError("creative_draft.revision")
    if state.get("status", "active") not in {"active", "left"}:
        raise ValueError("creative_draft.status")
    if state.get("status") == "left" and (not isinstance(state.get("leave_reason"), str) or not state["leave_reason"].strip()):
        raise ValueError("creative_draft.leave_reason")
    for key in ("theme", "sha256"):
        if not isinstance(state.get(key), str) or not state[key]:
            raise ValueError(f"creative_draft.{key}")


def leave_draft(state, reason):
    validate_draft(state)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Нужна причина оставить черновик")
    if state.get("status") == "left":
        return dict(state)
    return {**state, "status": "left", "leave_reason": reason.strip()[:1000]}


def draft_available(state=None):
    if state is not None:
        validate_draft(state)
        if state.get("status", "active") == "active" and state["revision"] < LIMIT:
            return True
    from pathlib import Path

    root = Path(data_path("delamain", "workspace", "creative"))
    return not root.exists() or sum(1 for _ in root.iterdir()) < MAX_DRAFTS


def draft_step(state=None):
    sandbox = Sandbox(data_path("delamain", "workspace", "creative"), max_file_bytes=8192)
    if state is not None:
        validate_draft(state)
    if state is None or state["revision"] >= LIMIT or state.get("status") == "left":
        # Консервативно считаем все записи, не удаляем старые тексты ради места.
        if sum(1 for _ in sandbox.root.iterdir()) >= MAX_DRAFTS:
            raise ValueError("Рабочая область черновиков заполнена; новые файлы не создаются")
        identifier = uuid4().hex
        theme = random.choice(["тишина", "дорога", "свет", "ожидание"])
        previous = ""
        revision = 1
    else:
        identifier, theme = state["id"], state["theme"]
        previous = sandbox.read_text(f"{identifier}.txt")
        if hashlib.sha256(previous.encode("utf-8")).hexdigest() != state["sha256"]:
            raise ValueError("Черновик изменён извне; автоматическая перезапись отменена")
        revision = state["revision"] + 1
    line = random.choice([f"{theme.capitalize()} оставляет место для следующей строки.",
                          f"Между словами остаётся {theme}.",
                          f"Я представляю, как {theme} меняет очертания."])
    content = (previous + "\n" if previous else f"Черновик: {theme}\n\n") + line
    sandbox.write_text(f"{identifier}.txt", content, overwrite=bool(previous))
    if sandbox.read_text(f"{identifier}.txt") != content:
        raise IOError("Не совпало обратное чтение черновика")
    return {"id": identifier, "theme": theme, "revision": revision, "status": "active",
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
