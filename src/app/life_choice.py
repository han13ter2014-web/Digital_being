"""Выбор старой жизни при первом запуске после обновления.

Логика отделена от Tk: решение можно проверить без окна. Главное правило —
ничего не выбирать за человека, если в профиле несколько жизней.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def describe_life(item: dict) -> str:
    """Одна строка для выбора: имя, циклы, снимки, время изменения."""
    name = str(item.get("name") or "?")
    cycles = int(item.get("cycles") or 0)
    checkpoints = int(item.get("checkpoints") or 0)
    modified = item.get("modified") or 0
    try:
        when = datetime.fromtimestamp(float(modified)).strftime("%d.%m.%Y %H:%M")
    except (OSError, OverflowError, TypeError, ValueError):
        when = "время неизвестно"
    words = _cycles_word(cycles)
    return f"{name} — {cycles} {words}, снимков: {checkpoints}, изменено {when}"


def _cycles_word(count: int) -> str:
    tail = count % 100
    if 11 <= tail <= 14:
        return "циклов"
    tail = count % 10
    if tail == 1:
        return "цикл"
    if 2 <= tail <= 4:
        return "цикла"
    return "циклов"


def resolve_startup_name(
    *,
    name=None,
    new=False,
    seed=None,
    no_restore=False,
    data_root,
    default_name,
    interactive,
    ask=None,
):
    """Имя жизни для запуска.

    ``ask`` показывает человеку список и возвращает выбранное имя (или None).
    Без окна или при повреждённом указателе запуск останавливается: новая
    жизнь не создаётся вместо старой.
    """
    if name or new or seed or no_restore:
        return name or default_name

    from src.app.active_profile import active_name
    from src.app.bootstrap import RecoveryRequiredError
    from src.app.legacy_profile import legacy_lives

    try:
        return active_name(data_root, default_name)
    except RecoveryRequiredError:
        pointer = Path(data_root) / "active_profile.json"
        if pointer.exists() or not interactive or ask is None:
            raise
        lives = legacy_lives(data_root)
        if len(lives) < 2:
            raise
        chosen = ask(lives)
        if not chosen:
            raise
        known = {str(item.get("name")) for item in lives}
        if str(chosen) not in known:
            raise RecoveryRequiredError(
                "Выбранная жизнь не найдена; данные не изменены"
            )
        return str(chosen)


__all__ = ["describe_life", "resolve_startup_name"]
