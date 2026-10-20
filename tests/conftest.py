"""
conftest.py — общая конфигурация для pytest.

Обеспечивает:
1. Корректный sys.path (для импорта src/, config/).
2. Настройку coverage по умолчанию (если установлен pytest-cov).
3. Фикстуры для headless-запуска (без блокирующих input/print).
"""
import sys
import os
from pathlib import Path

# Добавляем корень проекта в sys.path, чтобы импорты src/ и config/ работали
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Окружение: подавляем блокирующие GUI-вызовы в тестах
os.environ.setdefault("DIGITAL_BEING_TEST_MODE", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


# === Coverage defaults ===
# Если pytest-cov установлен и запускается без явного --cov, можно
# включить базовый отчёт через переменную окружения.
def pytest_configure(config):
    """Регистрируем custom markers и опционально включаем coverage."""
    # Маркер для тестов, требующих внешние сервисы (Wikipedia, HTTP)
    config.addinivalue_line(
        "markers",
        "network: тесты, требующие доступа к сети (отключаются в CI)",
    )


def pytest_addoption(parser):
    """Добавляем --cov-on флаг для быстрого включения coverage."""
    parser.addoption(
        "--cov-on",
        action="store_true",
        default=False,
        help="Включить coverage-отчёт для src/ (требует pytest-cov).",
    )


def pytest_collection_modifyitems(config, items):
    """
    Пропускаем network-тесты по умолчанию, если не передан --run-network.
    Запускать с -m "network" чтобы форсировать.
    """
    if config.getoption("-m", default="") and "network" in config.getoption("-m"):
        return
    skip_network = pytest.mark.skip(reason="network test (use -m network to run)")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)


# Используем pytest через config, но чтобы не делать import в начале,
# подключаем маркер в pytest_configure (выше). Это исключает хардкод.
import pytest  # noqa: E402  (импортируем после установки sys.path)