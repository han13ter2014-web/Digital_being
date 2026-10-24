"""
settings.py — глобальные настройки Digital Being.

Используется для runtime-настроек, которые не относятся к симуляции (simulation_config)
или модулям воли (will_config). Здесь — пути, флаги логирования, имя агента по умолчанию.
"""

import os


def _data_dir() -> str:
    """Папка изменяемых данных с учётом окружения.

    Вычисляется при каждом обращении: ``DIGITAL_BEING_DATA_DIR`` может
    смениться в процессе (тесты, отдельный профиль, повторный запуск).
    """
    override = os.environ.get("DIGITAL_BEING_DATA_DIR")
    if override:
        return os.path.abspath(override)
    return os.path.join(_base_dir(), "data")


def _base_dir() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _SettingsMeta(type):
    """Пути как вычисляемые свойства класса.

    Раньше ``DATA_DIR`` и остальные пути вычислялись один раз при
    импорте модуля. Из-за этого первая же смена ``DIGITAL_BEING_DATA_DIR``
    (тест, второй профиль, повторный запуск в том же процессе) оставляла
    ``Settings`` с устаревшим путём, и данные уходили не туда.
    """

    @property
    def BASE_DIR(cls) -> str:
        return _base_dir()

    @property
    def DATA_DIR(cls) -> str:
        return _data_dir()

    @property
    def CHECKPOINT_DIR(cls) -> str:
        return os.path.join(_data_dir(), "checkpoints")

    @property
    def LOG_DIR(cls) -> str:
        return os.path.join(_data_dir(), "logs")

    @property
    def MENTAL_MODELS_PATH(cls) -> str:
        return os.path.join(_data_dir(), "mind", "mental_models.json")

    @property
    def KNOWLEDGE_BASE_PATH(cls) -> str:
        return os.path.join(_data_dir(), "knowledge_base.json")

    @property
    def NURSERY_DIR(cls) -> str:
        return os.path.join(_data_dir(), "nursery")

    @property
    def ARCHITECTURE_PROPOSALS_DIR(cls) -> str:
        return os.path.join(_data_dir(), "architecture_proposals")


class Settings(metaclass=_SettingsMeta):
    """Глобальные настройки проекта."""

    # === Идентификация агента по умолчанию ===
    DEFAULT_AGENT_NAME = os.environ.get("DIGITAL_BEING_NAME", "Alpha")

    # Пути — вычисляемые свойства (см. _SettingsMeta): они всегда
    # соответствуют текущему окружению.
    #
    # BASE_DIR       — корень проекта (ресурсы)
    # DATA_DIR       — изменяемые данные (учитывает DIGITAL_BEING_DATA_DIR)
    # CHECKPOINT_DIR, LOG_DIR, MENTAL_MODELS_PATH, KNOWLEDGE_BASE_PATH,
    # NURSERY_DIR, ARCHITECTURE_PROPOSALS_DIR — производные от DATA_DIR

    # === Логирование ===
    LOG_LEVEL = os.environ.get("DIGITAL_BEING_LOG_LEVEL", "INFO")
    LOG_JSON = os.environ.get("DIGITAL_BEING_LOG_JSON", "0") == "1"
    LOG_BUFFER_SIZE = 10  # дубль из SIM_CONFIG для удобства доступа

    # === Производительность ===
    GC_INTERVAL = 50  # подняли со старых 5 циклов — менее агрессивно для long-running
    CHECKPOINT_INTERVAL = 10

    # === Поведение по умолчанию ===
    INFINITE_ENERGY_DEFAULT = False
    AUTO_SAVE_MENTAL_MODELS = True

    # === Флаги окружения ===
    DEBUG = os.environ.get("DIGITAL_BEING_DEBUG", "0") == "1"
    DRY_RUN = os.environ.get("DIGITAL_BEING_DRY_RUN", "0") == "1"

    @classmethod
    def ensure_dirs(cls):
        """Создаёт все необходимые директории, если их нет."""
        for path in (
            cls.DATA_DIR,
            cls.CHECKPOINT_DIR,
            cls.LOG_DIR,
            cls.NURSERY_DIR,
            cls.ARCHITECTURE_PROPOSALS_DIR,
            os.path.dirname(cls.MENTAL_MODELS_PATH),
        ):
            os.makedirs(path, exist_ok=True)


SETTINGS = Settings()