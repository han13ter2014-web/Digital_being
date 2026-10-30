"""Проверка UUID выбранного профиля без изменения сохранённых данных."""

import json
from pathlib import Path

from src.core.life_identity import validate_life_id


def selected_life_id(root):
    from src.app.bootstrap import RecoveryRequiredError

    path = Path(root) / "active_profile.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "life_id" not in data:
            return None
        return validate_life_id(data["life_id"])
    except (OSError, ValueError, TypeError) as exc:
        raise RecoveryRequiredError("Повреждена идентичность профиля; запуск остановлен") from exc
