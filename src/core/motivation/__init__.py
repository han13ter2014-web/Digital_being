"""Мотивация: потребности, драйвы и цели агента.

Единая точка сборки — :func:`create_motivation_system`, который
возвращает ``UnifiedMotivationSystem``. Модуль импортируется из
``src.core.agent``; до появления этого файла пакет работал как
namespace-пакет, что мешало упаковке (PyInstaller) и проверкам импорта.
"""

from src.core.motivation.unified_motivation import (  # noqa: F401
    UnifiedMotivationSystem,
    create_motivation_system,
)

__all__ = ["UnifiedMotivationSystem", "create_motivation_system"]
