"""Разрешения, которые человек включает и выключает сам.

Три вещи действительно меняют поведение Core:

* интернет-поиск — искать сведения в сети;
* Delamain — разбирать большую задачу на шаги;
* effector — выполнять действия в отдельной рабочей папке.

Выключение ничего не стирает: уже записанные знания и цели остаются.
Выбор человека сохраняется между запусками, иначе переключатель был бы
декорацией.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

ACCESS_FILE = "access_settings.json"

LABELS = {
    "network": "Интернет-поиск",
    "delamain": "Планирование задач",
    "effector": "Действия в рабочей папке",
}

HINTS = {
    "network": "искать сведения в интернете, когда своих знаний не хватает",
    "delamain": "разбирать большую задачу на выполнимые шаги",
    "effector": "создавать файлы только в отдельной рабочей папке профиля",
}

_KEYS = tuple(LABELS)


def _path(root) -> Path:
    return Path(root) / ACCESS_FILE


def load_saved(root) -> Dict[str, bool]:
    """Прочитать сохранённый выбор. Повреждённый файл не скрывает ошибку."""
    path = _path(root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(
            "Не удалось прочитать сохранённые разрешения; "
            "переключатели не применены"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("Файл разрешений повреждён; переключатели не применены")
    result: Dict[str, bool] = {}
    for key in _KEYS:
        if isinstance(payload.get(key), bool):
            result[key] = payload[key]
    return result


def _write_saved(root, values: Dict[str, bool]) -> None:
    path = _path(root)
    temporary = path.with_suffix(".tmp")
    payload = {key: bool(values[key]) for key in _KEYS if key in values}
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


def current_state(agent: Any) -> Dict[str, bool]:
    """Что включено сейчас на самом деле, а не что записано в файле."""
    network = getattr(getattr(agent, "web_searcher", None), "is_enabled", False)
    delamain = getattr(getattr(agent, "delamain", None), "enabled", False)
    effector = getattr(getattr(agent, "delamain_effector", None), "enabled", False)
    return {
        "network": bool(network),
        "delamain": bool(delamain),
        "effector": bool(effector),
    }


def apply_choice(agent: Any, key: str, enabled: bool) -> Dict[str, Any]:
    """Применить одно разрешение к живому Core.

    Returns:
        ``{"ok": bool, "error": Optional[str], "label": str}``.
        При ошибке состояние не считается изменённым.
    """
    if key not in LABELS:
        return {"ok": False, "error": "Неизвестное разрешение", "label": ""}
    label = LABELS[key]
    value = bool(enabled)

    if key == "network":
        searcher = getattr(agent, "web_searcher", None)
        if searcher is None:
            return {"ok": False, "label": label,
                    "error": "Интернет-поиск не подключён в этой сборке"}
        searcher.toggle(value)
        return {"ok": True, "error": None, "label": label}

    if key == "delamain":
        subsystem = getattr(agent, "delamain", None)
        if subsystem is None:
            return {"ok": False, "label": label,
                    "error": "Планирование задач не подключено в этой сборке"}
        if value:
            result = subsystem.enable()
            if not result.get("enabled"):
                return {"ok": False, "label": label,
                        "error": str(result.get("error") or "не удалось включить")}
        else:
            subsystem.disable()
        return {"ok": True, "error": None, "label": label}

    effector = getattr(agent, "delamain_effector", None)
    if effector is None:
        return {"ok": False, "label": label,
                "error": "Выполнение действий не подключено в этой сборке"}
    subsystem = getattr(agent, "delamain", None)
    if value and subsystem is not None and not getattr(subsystem, "enabled", False):
        # Действия исполняет тот же слой, что и планирование. Включать его
        # в одиночку значило бы показать разрешение, которое не работает.
        return {"ok": False, "label": label,
                "error": "сначала включите «Планирование задач»"}
    effector.enabled = value
    return {"ok": True, "error": None, "label": label}


def set_access(
    agent: Any, key: str, enabled: bool, *, root
) -> Dict[str, Any]:
    """Применить выбор и сохранить его только после успеха."""
    result = apply_choice(agent, key, enabled)
    if not result.get("ok"):
        return result
    try:
        saved = load_saved(root)
    except ValueError:
        saved = {}
    saved[key] = bool(enabled)
    try:
        _write_saved(root, saved)
    except OSError as exc:
        return {"ok": False, "label": result["label"],
                "error": f"Не удалось сохранить выбор: {exc}"}
    return result


def apply_saved(agent: Any, root) -> Dict[str, Any]:
    """Применить сохранённый выбор при запуске.

    Возвращает ``{"applied": [...], "error": Optional[str]}``. Ошибка
    чтения файла не мешает жизни: просто остаются настройки по умолчанию.
    """
    try:
        saved = load_saved(root)
    except ValueError as exc:
        return {"applied": [], "error": str(exc)}
    applied = []
    for key in _KEYS:
        if key not in saved:
            continue
        result = apply_choice(agent, key, saved[key])
        if result.get("ok"):
            applied.append(key)
    return {"applied": applied, "error": None}


def describe_error(result: Dict[str, Any]) -> str:
    """Человеческая фраза об отказе переключателя."""
    label = str(result.get("label") or "Разрешение")
    reason = str(result.get("error") or "не удалось изменить")
    return f"{label}: {reason}."


__all__ = [
    "ACCESS_FILE",
    "HINTS",
    "LABELS",
    "apply_choice",
    "apply_saved",
    "current_state",
    "describe_error",
    "load_saved",
    "set_access",
]
