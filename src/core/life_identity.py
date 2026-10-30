"""Неизменяемая идентичность жизни, независимая от отображаемого имени."""

from uuid import UUID, uuid4


def new_life_id():
    return str(uuid4())


def validate_life_id(value):
    if not isinstance(value, str):
        raise ValueError("life_id: ожидается UUID-строка")
    try:
        identifier = UUID(value)
    except ValueError as exc:
        raise ValueError("life_id: некорректный UUID") from exc
    if str(identifier) != value:
        raise ValueError("life_id: требуется каноническая запись UUID")
    return value
