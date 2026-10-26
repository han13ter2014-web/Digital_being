"""Разбор темы намерения без неявного преобразования объектов в строки."""


def intention_target(intention):
    if intention is None:
        return None
    if not isinstance(intention, dict):
        raise ValueError("intention должен быть словарём")
    params = intention.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("intention.params должен быть словарём")
    targets = []
    for key in ("topic", "concept", "target"):
        if key not in params:
            continue
        value = params[key]
        if not isinstance(value, str) or not value.strip() or len(value) > 1000:
            raise ValueError(f"intention.params.{key}: нужна непустая тема до 1000 символов")
        targets.append(value.strip())
    if len(set(targets)) > 1:
        raise ValueError("Конфликтующие темы намерения")
    return targets[0] if targets else None
