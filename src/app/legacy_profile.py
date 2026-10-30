"""Read-only обнаружение старых жизней без указателя активного профиля."""

import re
import sqlite3
from contextlib import closing
from pathlib import Path


def discover_legacy_name(root, default):
    """Выбрать единственную старую жизнь; неоднозначность требует человека."""
    from src.app.bootstrap import RecoveryRequiredError

    directory = Path(root) / "checkpoints"
    names = set()
    if not directory.exists():
        return default
    try:
        for path in directory.iterdir():
            match = re.fullmatch(r"(.+)_cycle_([0-9]+)\.json(?:\.gz)?", path.name)
            if path.is_file() and match:
                names.add(match.group(1))
        database = directory / "life.sqlite3"
        if database.exists():
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version != 1:
                    raise ValueError("неподдерживаемый формат истории")
                for (name,) in connection.execute("SELECT DISTINCT agent_name FROM snapshots"):
                    if not isinstance(name, str) or not name.strip():
                        raise ValueError("некорректное имя сохранённой жизни")
                    names.add(name)
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise RecoveryRequiredError(
            "Не удалось прочитать старый профиль; новая жизнь не создана"
        ) from exc
    if len(names) > 1:
        raise RecoveryRequiredError(
            "Найдено несколько сохранённых жизней. Нужен явный выбор через --name; "
            "данные не изменены. Профиль: " + str(Path(root).resolve())
        )
    return next(iter(names)) if names else default
