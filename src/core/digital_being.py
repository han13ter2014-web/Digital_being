"""
DEPRECATED: этот файл — legacy-обёртка, которая импортировала
`Agent` из src.core.agent и `Memory` из src.memory.memory — оба эти
модуля в актуальной версии отсутствуют или переименованы.

Шаг 6 дедупликации: вся функциональность уже интегрирована в
`src.core.agent.DigitalBeing`. Используйте его напрямую.

Этот файл оставлен как shim — обратная совместимость с примерами,
которые могут ссылаться на него. При попытке импорта выбрасывает
предупреждение и направляет к актуальному классу.
"""

import warnings as _warnings


def __getattr__(name):
    """Перехватывает любой импорт из этого модуля и предупреждает."""
    if name == "DigitalBeing":
        _warnings.warn(
            "src.core.digital_being устарел. Импортируйте "
            "DigitalBeing из src.core.agent напрямую.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Проксируем к актуальному классу
        from src.core.agent import DigitalBeing as _ActualDigitalBeing
        return _ActualDigitalBeing

    raise AttributeError(
        f"src.core.digital_being больше не предоставляет '{name}'. "
        f"Используйте src.core.agent."
    )


__all__: list = []