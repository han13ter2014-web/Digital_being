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
            if path.is_dir():
                from src.core.life_identity import validate_life_id

                try:
                    validate_life_id(path.name)
                except ValueError:
                    continue
                # Namespace UUID сам по себе является свидетельством истории:
                # не разрешаем тихую новую жизнь без указателя выбора.
                raise RecoveryRequiredError(
                    "Найден UUID-профиль без указателя активной жизни; "
                    "нужно восстановить active_profile.json из резервной копии"
                )
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


def legacy_lives(root):
    """Описать старые жизни без изменения данных.

    Нужно человеку для выбора: имя, номера циклов, число снимков и время
    последнего изменения. Ничего не пишет и не выбирает за человека.
    """
    directory = Path(root) / "checkpoints"
    if not directory.exists():
        return []
    lives = {}

    def entry(name):
        return lives.setdefault(
            name,
            {"name": name, "cycles": 0, "checkpoints": 0, "modified": 0.0},
        )

    for path in directory.iterdir():
        if path.is_dir():
            continue
        match = re.fullmatch(r"(.+)_cycle_([0-9]+)\.json(?:\.gz)?", path.name)
        if not match:
            continue
        item = entry(match.group(1))
        item["cycles"] = max(item["cycles"], int(match.group(2)))
        item["checkpoints"] += 1
        item["modified"] = max(item["modified"], path.stat().st_mtime)

    database = directory / "life.sqlite3"
    if database.exists():
        with closing(
            sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        ) as connection:
            for name, cycle, count in connection.execute(
                "SELECT agent_name, MAX(cycle), COUNT(*) FROM snapshots "
                "GROUP BY agent_name"
            ):
                item = entry(str(name))
                item["cycles"] = max(item["cycles"], int(cycle or 0))
                item["checkpoints"] += int(count)

    return sorted(
        lives.values(),
        key=lambda item: (item["cycles"], item["modified"]),
        reverse=True,
    )
