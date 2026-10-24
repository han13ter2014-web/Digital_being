"""Окружение приложения: пути, логи, кодировка консоли.

Раньше всё это жило в начале ``main_tray.py`` (около 100 строк), а
``main.py`` вообще не знал про ``APPDATA``, ``_MEIPASS`` и ротацию
логов. Из-за этого консольный и трей-режимы по-разному находили данные:
в собранном ``.exe`` консольный режим писал бы в папку, доступную
только для чтения.

Здесь один источник правды. Вызывается один раз при старте.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler

# Имя файла лога сохранено прежним: на него ссылаются документация и
# smoke-тест трея.
LOG_FILENAME = "tray_agent.log"

# Подпапки данных, которые нужны приложению.
DATA_SUBDIRS = (
    "checkpoints",
    "logs",
    "mind",
    "memory",
    "nursery",
    "evolution",
    "cooperation",
    "architecture_proposals",
    "metrics",
    "snapshots",
)


@dataclass(frozen=True)
class AppEnv:
    """Куда приложение смотрит за ресурсами и куда пишет данные."""

    base_dir: str
    user_data_dir: str
    data_root: str
    log_file: str
    frozen: bool

    def as_dict(self) -> dict:
        return {
            "base_dir": self.base_dir,
            "user_data_dir": self.user_data_dir,
            "data_root": self.data_root,
            "log_file": self.log_file,
            "frozen": self.frozen,
        }


def resolve_base_dir() -> tuple[str, bool]:
    """Папка ресурсов и признак «собрано PyInstaller».

    В onefile-сборке ресурсы лежат во временной папке ``_MEIPASS``, а в
    исходниках — в корне проекта.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return str(sys._MEIPASS), True
    return os.path.dirname(os.path.abspath(sys.argv[0])) or os.getcwd(), False


def resolve_user_data_dir(frozen: bool, base_dir: str) -> str:
    """Папка для изменяемых данных.

    В установленной программе писать рядом с ``.exe`` нельзя: в
    ``Program Files`` у обычного пользователя нет прав (WinError 5).
    Поэтому на Windows — ``%APPDATA%\\DigitalBeing``, на Unix — XDG.
    Из исходников пишем в корень проекта, как раньше.
    """
    if not frozen:
        return base_dir

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return os.path.join(appdata, "DigitalBeing")
        return os.path.expanduser("~/DigitalBeing")

    xdg = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return os.path.join(xdg, "digitalbeing")


def _configure_console_encoding(logger: logging.Logger) -> None:
    """Перевести консоль в UTF-8, не подменяя объект потока.

    Используем ``reconfigure``: он меняет кодировку у существующего
    потока. Раньше создавалась новая обёртка ``TextIOWrapper``, и это
    ломало вывод:

    * при перенаправлении в файл текст уходил в буфер обёртки, которая
      никогда не сбрасывалась;
    * при перехвате вывода (тесты, IDE) обёртка подменяла объект
      перехвата, и записанное терялось.

    ``reconfigure`` сохраняет объект, поэтому и консоль, и файл, и
    перехват получают UTF-8 без побочных эффектов. Если поток не
    поддерживает переконфигурацию (например, объект перехвата в тестах),
    просто оставляем как есть.
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        if getattr(stream, "encoding", None) == "utf-8":
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.debug(
                "Не удалось перевести %s в UTF-8: %s", stream_name, exc
            )


def _configure_logging(
    data_root: str, logger: logging.Logger, *, console: bool = True
) -> str:
    """Логи в файл с ротацией плюс (необязательно) консоль.

    Args:
        console: писать ли в stdout. В режиме машиночитаемого отчёта
            stdout принадлежит JSON, и логи туда попадать не должны.
    """
    log_dir = os.path.join(data_root, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, LOG_FILENAME)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Не дублируем хэндлеры при повторном вызове (тесты, повторный старт).
    # Помечаем свои хэндлеры, чтобы не снимать чужие (например, pytest).
    for handler in list(root.handlers):
        if getattr(handler, "_digital_being", False):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    file_handler._digital_being = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    if console and sys.stdout is not None:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler._digital_being = True  # type: ignore[attr-defined]
        stream_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            )
        )
        root.addHandler(stream_handler)

    logger.debug("Лог-файл: %s", log_file)
    return log_file


def setup_environment(*, chdir: bool = True, console: bool = True) -> AppEnv:
    """Готовит окружение и возвращает пути.

    Args:
        chdir: перейти в папку ресурсов. Нужно для относительных путей
            к ``config/`` и для совместимости с прежним поведением.
        console: писать ли логи в stdout. Выключается, когда stdout нужен
            под машиночитаемый вывод (``--maturity-json``).
    """
    base_dir, frozen = resolve_base_dir()
    user_data_dir = resolve_user_data_dir(frozen, base_dir)

    if chdir:
        try:
            os.chdir(base_dir)
        except OSError:
            pass

    # DIGITAL_BEING_DATA_DIR перенаправляет изменяемые данные (тесты,
    # отдельный профиль) и указывает прямо на папку data.
    override = os.environ.get("DIGITAL_BEING_DATA_DIR")
    data_root = (
        os.path.abspath(override)
        if override
        else os.path.join(user_data_dir, "data")
    )

    logger = logging.getLogger("app.env")
    _configure_console_encoding(logger)

    for sub in DATA_SUBDIRS:
        os.makedirs(os.path.join(data_root, sub), exist_ok=True)

    log_file = _configure_logging(data_root, logger, console=console)

    env = AppEnv(
        base_dir=base_dir,
        user_data_dir=user_data_dir,
        data_root=data_root,
        log_file=log_file,
        frozen=frozen,
    )

    logger.info("Пользовательские данные: %s", user_data_dir)
    logger.info("Папка данных: %s", data_root)
    logger.info("Ресурсы приложения: %s", base_dir)
    return env


__all__ = [
    "LOG_FILENAME",
    "DATA_SUBDIRS",
    "AppEnv",
    "resolve_base_dir",
    "resolve_user_data_dir",
    "setup_environment",
]