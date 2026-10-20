"""
settings.py — глобальные настройки Digital Being.

Используется для runtime-настроек, которые не относятся к симуляции (simulation_config)
или модулям воли (will_config). Здесь — пути, флаги логирования, имя агента по умолчанию.
"""

import os


class Settings:
    """Глобальные настройки проекта."""

    # === Идентификация агента по умолчанию ===
    DEFAULT_AGENT_NAME = os.environ.get("DIGITAL_BEING_NAME", "Alpha")

    # === Пути ===
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(BASE_DIR, "data")
    CHECKPOINT_DIR = os.path.join(DATA_DIR, "checkpoints")
    LOG_DIR = os.path.join(DATA_DIR, "logs")
    MENTAL_MODELS_PATH = os.path.join(DATA_DIR, "mind", "mental_models.json")
    KNOWLEDGE_BASE_PATH = os.path.join(DATA_DIR, "knowledge_base.json")
    NURSERY_DIR = os.path.join(DATA_DIR, "nursery")
    ARCHITECTURE_PROPOSALS_DIR = os.path.join(DATA_DIR, "architecture_proposals")

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