"""Указатель выбранной жизни: отображаемое имя не должно сбрасывать восстановление."""

import json
import os
from pathlib import Path
import tempfile

from src.app.legacy_profile import discover_legacy_name


def remember_active_name(root, name, life_id=None):
    """Атомарно запомнить имя после успешного сохранения чекпоинта."""
    destination = Path(root) / "active_profile.json"
    payload = {"name": name}
    if life_id is not None:
        from src.core.life_identity import validate_life_id

        payload["life_id"] = validate_life_id(life_id)
    serialized = json.dumps(payload, ensure_ascii=False)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".active_profile-", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(serialized, encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def active_name(root, default):
    """Прочитать указатель; повреждение не означает разрешение новой жизни."""
    from src.app.bootstrap import RecoveryRequiredError

    path = Path(root) / "active_profile.json"
    if not path.exists():
        return discover_legacy_name(root, default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload["name"]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("пустое имя профиля")
        from src.app.bootstrap import checkpoint_candidates

        if not checkpoint_candidates(
            payload.get("life_id") or value, str(Path(root) / "checkpoints")
        ):
            raise RecoveryRequiredError(
                "Для выбранной жизни не найден чекпоинт; новая жизнь не создана"
            )
        return value
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RecoveryRequiredError(
            "Не удалось прочитать выбранный профиль; данные не заменены"
        ) from exc
