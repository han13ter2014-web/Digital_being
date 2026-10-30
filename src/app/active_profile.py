"""Указатель выбранной жизни: отображаемое имя не должно сбрасывать восстановление."""

import json
import os
from pathlib import Path


def remember_active_name(root, name):
    """Атомарно запомнить имя после успешного сохранения чекпоинта."""
    destination = Path(root) / "active_profile.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps({"name": name}, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, destination)


def active_name(root, default):
    """Прочитать указатель; повреждение не означает разрешение новой жизни."""
    from src.app.bootstrap import RecoveryRequiredError

    path = Path(root) / "active_profile.json"
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))["name"]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("пустое имя профиля")
        from src.app.bootstrap import checkpoint_candidates

        if not checkpoint_candidates(value, str(Path(root) / "checkpoints")):
            raise RecoveryRequiredError(
                "Для выбранной жизни не найден чекпоинт; новая жизнь не создана"
            )
        return value
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RecoveryRequiredError("Не удалось прочитать выбранный профиль; данные не заменены") from exc
