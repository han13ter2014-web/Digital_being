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


def _episode_status(episode: Dict[str, Any]) -> str:
    metadata = episode.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("status"):
        return status_label(metadata["status"])
    if episode.get("error"):
        return "ошибка"
    return "выполнено" if episode.get("ok") else "не выполнено"


def episode_title(episode: Dict[str, Any]) -> str:
    """Короткий заголовок события только из action и target."""
    action = action_label(episode.get("action"))
    args = episode.get("args") or {}
    target = args.get("target") if isinstance(args, dict) else None
    return f"{action} «{target}»" if target else action


def episode_rows(episode: Dict[str, Any]) -> List[Row]:
    """Детали одного эпизода для карточки дневника."""
    rows: List[Row] = [("Событие", episode_title(episode)),
                       ("Статус", _episode_status(episode))]
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
    episodes = ((snapshot.get("diary") or {}).get("episodes") or [])
    return [episode for episode in episodes if isinstance(episode, dict)]


def draft_rows(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    creative = ((snapshot.get("activities") or {}).get("creative") or {})
    drafts = creative.get("drafts") or []
    return [draft for draft in drafts if isinstance(draft, dict)]


def draft_detail(draft: Dict[str, Any]) -> List[Row]:
    rows: List[Row] = [("Тема", str(draft.get("theme") or "—")),
                       ("Статус", str(draft.get("status") or "активен")),
                       ("Редакция", str(draft.get("revision", 1)))]
    if draft.get("leave_reason"):
        rows.append(("Почему оставлен", str(draft["leave_reason"])))
    if draft.get("sha256"):
        rows.append(("SHA-256", str(draft["sha256"])))
    return rows


def game_detail(snapshot: Dict[str, Any]) -> List[Row]:
    game = (snapshot.get("activities") or {}).get("game")
    if not isinstance(game, dict):
        return [("Партия", "ещё не начиналась")]
    board = game.get("board")
    rows = [("Партия", str(game.get("round", 1))),
            ("Ходов", str(game.get("turns", 0))),
            ("Результат", _RESULT.get(game.get("result"), "идёт"))]
    if isinstance(board, list) and len(board) == 9:
        rows.append(("Поле", " ".join(str(cell) for cell in board)))
    return rows


def rows_text(rows: List[Row]) -> str:
    return "\n".join(f"{label}: {value}" for label, value in rows)
