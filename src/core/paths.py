"""Пути к изменяемым данным проекта.

Все записи (логи, база знаний, чекпоинты, память, метрики) идут через
:func:`data_path`. По умолчанию это ``data/`` относительно текущей папки,
как и раньше, но переменная окружения ``DIGITAL_BEING_DATA_DIR``
перенаправляет их в другую папку.

Это использует ``tests/conftest.py``: тесты работают во временной папке и
не трогают ``data/`` рабочей копии.

Чтение неизменяемых ресурсов (``data/initial_knowledge.json``,
``data/i18n/*.json``) остаётся по пути от корня проекта — их тесты не
меняют.
"""

from __future__ import annotations

import os

DATA_DIR_ENV = "DIGITAL_BEING_DATA_DIR"

# Корень проекта: .../src/core/paths.py -> .../src/core -> .../src -> ...
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def project_root() -> str:
    """Абсолютный путь к корню проекта."""
    return PROJECT_ROOT


def data_dir() -> str:
    """Папка изменяемых данных (учитывает ``DIGITAL_BEING_DATA_DIR``)."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return os.path.abspath(override)
    return "data"


def data_path(*parts: str) -> str:
    """Путь внутри папки данных, например ``data_path("logs", "agent_log.txt")``."""
    return os.path.join(data_dir(), *parts)


def ensure_data_dir() -> str:
    """Создаёт папку данных (если нужно) и возвращает её путь."""
    path = data_dir()
    os.makedirs(path, exist_ok=True)
    return path


__all__ = [
    "DATA_DIR_ENV",
    "PROJECT_ROOT",
    "project_root",
    "data_dir",
    "data_path",
    "ensure_data_dir",
]
