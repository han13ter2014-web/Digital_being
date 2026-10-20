"""
conftest.py — общая конфигурация для pytest.

Обеспечивает:
1. Корректный sys.path (для импорта src/, config/).
2. Настройку coverage по умолчанию (если установлен pytest-cov).
3. Фикстуры для headless-запуска (без блокирующих input/print).
"""
import sys
import os
import shutil
import tempfile
from pathlib import Path

# Добавляем корень проекта в sys.path, чтобы импорты src/ и config/ работали
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Окружение: подавляем блокирующие GUI-вызовы в тестах
os.environ.setdefault("DIGITAL_BEING_TEST_MODE", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# === Изоляция данных (этап 3) ===
# Все изменяемые данные (KB, логи, чекпоинты, память, метрики) идут через
# src.core.paths и уважают DIGITAL_BEING_DATA_DIR. Тесты пишут во временную
# папку и не трогают data/ рабочей копии.
_DATA_ENV = "DIGITAL_BEING_DATA_DIR"
_SESSION_DATA_DIR = None


def _use_isolated_data_dir():
    """Направляет данные тестов во временную папку (один раз на сессию)."""
    global _SESSION_DATA_DIR
    # Если пользователь явно задал папку — не переопределяем.
    if os.environ.get(_DATA_ENV):
        return

    path = tempfile.mkdtemp(prefix="db_test_data_")
    _SESSION_DATA_DIR = path
    os.environ[_DATA_ENV] = path
    for sub in (
        "checkpoints", "logs", "mind", "memory", "nursery", "evolution",
        "cooperation", "architecture_proposals", "metrics",
    ):
        os.makedirs(os.path.join(path, sub), exist_ok=True)


_use_isolated_data_dir()


def pytest_sessionfinish(session, exitstatus):
    """Удаляет временную папку данных после прогона."""
    if _SESSION_DATA_DIR:
        shutil.rmtree(_SESSION_DATA_DIR, ignore_errors=True)


# === Контроль утечек в data/ рабочей копии ===
_REPO_DATA_DIR = PROJECT_ROOT / "data"
_IGNORED_DATA_DIRS = {"logs"}  # логи может писать живой агент пользователя


def _repo_data_manifest():
    """Снимок файлов data/: {относительный путь: (размер, mtime_ns)}."""
    manifest = {}
    if not _REPO_DATA_DIR.exists():
        return manifest
    for path in _REPO_DATA_DIR.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(_REPO_DATA_DIR)
        if rel.parts and rel.parts[0] in _IGNORED_DATA_DIRS:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        manifest[str(rel)] = (stat.st_size, stat.st_mtime_ns)
    return manifest


_REPO_DATA_BEFORE = _repo_data_manifest()


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Предупреждает, если тесты всё-таки изменили data/ рабочей копии."""
    after = _repo_data_manifest()
    changed = sorted(
        key for key, value in after.items()
        if _REPO_DATA_BEFORE.get(key) != value
    )
    removed = sorted(set(_REPO_DATA_BEFORE) - set(after))
    if changed or removed:
        terminalreporter.write_line(
            "WARNING: тесты изменили data/ рабочей копии: "
            + ", ".join(changed + [f"-{key}" for key in removed])
        )


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