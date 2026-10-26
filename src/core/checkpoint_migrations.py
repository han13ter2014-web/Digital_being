"""Строгие миграции формата чекпоинтов."""

from copy import deepcopy
from typing import Callable, Dict, Tuple


SCHEMA_VERSION = 1
MIGRATIONS: Dict[Tuple[int, int], Callable[[dict], dict]] = {}


class CheckpointMigrationError(ValueError):
    """Состояние нельзя безопасно привести к текущей схеме."""


def get_schema_version(state: dict) -> int:
    if not isinstance(state, dict):
        raise CheckpointMigrationError("Состояние чекпоинта должно быть словарём")
    value = state.get("schema_version", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CheckpointMigrationError("schema_version должен быть неотрицательным целым")
    return value


def migrate_state(state: dict) -> dict:
    """Мигрировать копию; незавершённая цепочка никогда не маркируется текущей."""
    current = get_schema_version(state)
    if current > SCHEMA_VERSION:
        raise CheckpointMigrationError(
            f"Схема {current} новее поддерживаемой {SCHEMA_VERSION}"
        )
    migrated = deepcopy(state)
    while current < SCHEMA_VERSION:
        next_version = current + 1
        function = MIGRATIONS.get((current, next_version))
        if function is None:
            raise CheckpointMigrationError(
                f"Нет миграции schema {current} → {next_version}"
            )
        try:
            candidate = function(migrated)
        except Exception as exc:
            raise CheckpointMigrationError(
                f"Миграция schema {current} → {next_version} завершилась ошибкой: {exc}"
            ) from exc
        if not isinstance(candidate, dict):
            raise CheckpointMigrationError("Мигратор должен вернуть словарь")
        migrated = candidate
        actual = get_schema_version(migrated)
        if actual not in (current, next_version):
            raise CheckpointMigrationError(
                f"Мигратор вернул неожиданную schema_version {actual}"
            )
        current = next_version
        migrated["schema_version"] = current
    return migrated


def is_compatible(state: dict) -> bool:
    try:
        return get_schema_version(state) <= SCHEMA_VERSION
    except CheckpointMigrationError:
        return False
