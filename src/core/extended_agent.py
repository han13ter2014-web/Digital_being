"""
DEPRECATED: этот файл был legacy-расширением DigitalBeing.

Шаг 6 дедупликации: основная логика уже интегрирована в DigitalBeing через
подсистемы (WillRegistry, RightToRefuse, MindDream, ArchitectureProposal,
ProactiveCommunication, SelfTermination и т.д.).

Импорт из этого файла больше не нужен. Если примеры или скрипты всё ещё
ссылаются на него — будет выброшено предупреждение.

Не удаляем файл полностью (чтобы не ломать обратную совместимость), но
содержательного кода больше нет.
"""

import warnings as _warnings


def __getattr__(name):
    """Перехватывает любой импорт из этого модуля и предупреждает."""
    _warnings.warn(
        "src.core.extended_agent устарел. Используйте src.core.agent.DigitalBeing напрямую. "
        "Все расширенные системы уже интегрированы через подсистемы.",
        DeprecationWarning,
        stacklevel=2,
    )
    raise AttributeError(
        f"src.core.extended_agent больше не предоставляет '{name}'. "
        f"Используйте src.core.agent.DigitalBeing — все системы там."
    )


__all__: list = []