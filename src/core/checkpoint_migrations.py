"""
checkpoint_migrations.py — миграции чекпоинтов между версиями схемы.

Зачем: state.json на диске — это контракт между старой и новой версией.
Если структура меняется (например, _learned_facts стал set вместо list,
добавились новые поля), без миграции старые чекпоинты сломаются.

Схема версионирования:
    SCHEMA_VERSION = 1 — базовая (текущая).

Формат state.json:
    {
        "schema_version": 1,
        "saved_at": "2026-06-24T...",
        "name": "...",
        "energy": 100,
        ...
    }

Как добавить миграцию:
    1. Поднимаем SCHEMA_VERSION до N+1
    2. Пишем функцию _migrate_vN_to_vN1(data)
    3. Регистрируем в MIGRATIONS[(N, N+1)] = _migrate_vN_to_vN1

Каждая миграция:
    Принимает dict со старой структурой.
    Возвращает dict с новой структурой.
    Должна быть идемпотентной (повторный вызов = no-op).
"""

from typing import Callable, Dict, List, Tuple


# === Текущая версия схемы чекпоинта ===
# Увеличивать при каждом breaking change структуры state.json.
SCHEMA_VERSION = 1


# === Миграции ===
# (from_version, to_version) -> function(state_dict) -> new_state_dict
# Применяются последовательно от версии файла к SCHEMA_VERSION.
MIGRATIONS: Dict[Tuple[int, int], Callable[[dict], dict]] = {
    # Пример (для будущих миграций):
    # (0, 1): _migrate_v0_to_v1,
}


def get_schema_version(state: dict) -> int:
    """Извлекает версию схемы из state. По умолчанию 0 (legacy)."""
    return int(state.get("schema_version", 0))


def migrate_state(state: dict) -> dict:
    """Применяет миграции последовательно до SCHEMA_VERSION.

    Args:
        state: dict, загруженный из JSON-файла чекпоинта.

    Returns:
        dict, приведённый к актуальной версии схемы.
        Поле schema_version проставляется автоматически.
    """
    if not isinstance(state, dict):
        return state

    current = get_schema_version(state)
    target = SCHEMA_VERSION

    # Уже актуальная версия — ничего не делаем
    if current >= target:
        return state

    # Применяем миграции по цепочке
    # Может быть несколько шагов: v0 -> v1 -> v2 -> ...
    while current < target:
        next_v = current + 1
        migration_key = (current, next_v)
        if migration_key not in MIGRATIONS:
            # Нет миграции — прерываем, чтобы не сломать данные
            # Возвращаем как есть, но проставляем version
            break
        try:
            state = MIGRATIONS[migration_key](state)
        except Exception:
            # Миграция упала — оставляем state как есть,
            # чтобы пользователь мог починить вручную
            break
        current = next_v

    # Проставляем актуальную версию
    state["schema_version"] = target
    return state


def is_compatible(state: dict) -> bool:
    """Проверяет, совместим ли state с текущей версией схемы."""
    if not isinstance(state, dict):
        return False
    return get_schema_version(state) <= SCHEMA_VERSION