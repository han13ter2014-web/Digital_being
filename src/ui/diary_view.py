"""Чистые форматтеры дневника и каталога занятий для оболочки v1.

Здесь нет Tk и нет доступа к агенту. На вход приходят только глубокие копии
из ``build_life_snapshot``; незаписанные причины и результаты не дополняются
догадками.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

Row = Tuple[str, str]

_ACTIONS = {
    "play": "партия",
    "create_draft": "творческий черновик",
    "explore": "исследование",
    "communicate": "общение",
    "rest": "отдых",
    "reflect": "размышление",
    "wait": "ожидание",
}
_STATUS = {
    "started": "начато",
    "performed": "выполнено",
    "denied": "отклонено",
    "error": "ошибка",
    "interrupted": "прервано",
    "unobserved": "исход не наблюдался",
}
_RESULT = {"X": "победа", "O": "поражение", "draw": "ничья", None: "идёт"}


def action_label(action: Any) -> str:
    value = str(action or "занятие")
    return _ACTIONS.get(value, value)


def status_label(status: Any) -> str:
    value = str(status or "неизвестно")
    return _STATUS.get(value, value)


def episode_status(episode: Dict[str, Any]) -> str:
    metadata = episode.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("status"):
        return status_label(metadata["status"])
    if episode.get("error"):
        return "ошибка"
    return "выполнено" if episode.get("ok") else "не выполнено"


def episode_title(episode: Dict[str, Any]) -> str:
    """Короткий заголовок события только из записанных полей эпизода."""
    metadata = episode.get("metadata") or {}
    output = episode.get("output") or {}
    if (
        isinstance(metadata, dict)
        and metadata.get("kind") == "biography_seam"
        and isinstance(output, dict)
        and output.get("text")
    ):
        return str(output["text"])
    action = action_label(episode.get("action"))
    args = episode.get("args") or {}
    target = args.get("target") if isinstance(args, dict) else None
    return f"{action} «{target}»" if target else action


def episode_time(episode: Dict[str, Any]) -> str:
    """Часы:минуты из записанного времени; времени нет — прочерк."""
    timestamp = str(episode.get("ts") or "")
    return timestamp[11:16] if len(timestamp) >= 16 else "—"


# Цвет плашки действия — ключ палитры, а не hex: цвета живут только в theme.py.
ACTION_COLOR_KEYS = {
    "play": "amber",
    "create_draft": "violet",
    "explore": "cyan",
    "communicate": "green",
    "reflect": "violet",
    "rest": "grey",
    "wait": "grey",
}


def action_color_key(action: Any) -> str:
    """Ключ цвета палитры для плашки действия; неизвестное — тихий серый."""
    return ACTION_COLOR_KEYS.get(str(action or ""), "grey")


def group_key(episode: Dict[str, Any]) -> Tuple[Any, ...]:
    """Ключ сходства эпизодов: действие, тема, статус, исход и ошибка.

    Серия узнаётся по содержанию, а не по номерам строк: окно истории
    сдвигается с каждым тиком, и привязка к конкретным записям теряла
    раскрытие серии.
    """
    args = episode.get("args")
    target = args.get("target") if isinstance(args, dict) else None
    metadata = episode.get("metadata")
    status = metadata.get("status") if isinstance(metadata, dict) else None
    return (
        str(episode.get("action")),
        str(target),
        str(status),
        str(episode.get("error") or ""),
        bool(episode.get("ok")),
    )


def group_diary_episodes(
    episodes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Свернуть подряд идущие одинаковые эпизоды в серии.

    Одинаковость — только по записанным полям: действие, тема, статус,
    исход и ошибка. Склеиваются только соседние записи: серия — это
    повтор подряд, а не «похожие события за день».
    """
    groups: List[Dict[str, Any]] = []
    for episode in episodes:
        key = group_key(episode)
        if groups and groups[-1]["key"] == key:
            groups[-1]["episodes"].append(episode)
        else:
            groups.append({"key": key, "episodes": [episode]})
    return groups


def episode_rows(episode: Dict[str, Any]) -> List[Row]:
    """Детали одного эпизода для карточки дневника."""
    rows: List[Row] = [
        ("Событие", episode_title(episode)),
        ("Статус", episode_status(episode)),
    ]
    timestamp = episode.get("ts")
    if timestamp:
        rows.append(("Время", str(timestamp)))
    task_id = episode.get("task_id")
    if task_id:
        rows.append(("ID намерения", str(task_id)))
    error = episode.get("error")
    if error:
        rows.append(("Ошибка", str(error)))
    output = episode.get("output")
    if isinstance(output, dict) and output:
        result = output.get("result") or output.get("status")
        if result is not None:
            rows.append(("Результат", str(result)))
    return rows


def diary_rows(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Эпизоды в порядке от новых к старым, уже пригодные для UI."""
    episodes = (snapshot.get("diary") or {}).get("episodes") or []
    return [episode for episode in episodes if isinstance(episode, dict)]


def draft_rows(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    creative = (snapshot.get("activities") or {}).get("creative") or {}
    drafts = creative.get("drafts") or []
    return [draft for draft in drafts if isinstance(draft, dict)]


_DRAFT_STATUS = {
    "active": "продолжается",
    "left": "оставлен",
}


def draft_detail(draft: Dict[str, Any]) -> List[Row]:
    """Объяснение работы человеческими словами, без служебного хеша."""
    theme = str(draft.get("theme") or "без названия")
    status = str(draft.get("status") or "active")
    revision = int(draft.get("revision", 1) or 1)
    rows: List[Row] = [
        ("Что это", f"Творческий текстовый черновик на тему «{theme}»"),
        (
            "О состоянии",
            "Работа, к которой Core может вернуться и продолжить её"
            if status == "active"
            else "Работа оставлена; сохранённая версия остаётся в каталоге",
        ),
        ("Состояние", _DRAFT_STATUS.get(status, status)),
        ("Редакция", f"{revision} из 8"),
    ]
    if draft.get("leave_reason"):
        reason = str(draft["leave_reason"])
        if "лимит" in reason.lower():
            reason = (
                f"Core достиг предела в {revision} редакций и сохранил текст как есть"
            )
        rows.append(("Почему", reason))
    if draft.get("sha256"):
        rows.append(("Файл", "сохранён; отпечаток файла записан"))
    return rows


def game_detail(snapshot: Dict[str, Any]) -> List[Row]:
    game = (snapshot.get("activities") or {}).get("game")
    if not isinstance(game, dict):
        return [("Партия", "ещё не начиналась")]
    board = game.get("board")
    rows = [
        ("Партия", str(game.get("round", 1))),
        ("Ходов", str(game.get("turns", 0))),
        ("Результат", _RESULT.get(game.get("result"), "идёт")),
    ]
    if isinstance(board, list) and len(board) == 9:
        rows.append(("Поле", " ".join(str(cell) for cell in board)))
    return rows


def rows_text(rows: List[Row]) -> str:
    return "\n".join(f"{label}: {value}" for label, value in rows)
