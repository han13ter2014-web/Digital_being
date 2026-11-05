"""TICKET-7: логи и экспорты — явный UTF-8, чтение BOM-независимое.

Наблюдатели (2026-11-05): выгруженный лог `observation_formatted.txt`
оказался двойным перекодированием (UTF-8 → CP866 → UTF-16 без BOM),
кириллица нечитаема. Аудит записи в репозитории показал: все пути
уже пишут явный UTF-8 (`open(..., encoding="utf-8")`, байтовая
запись в Sandbox, RotatingFileHandler(encoding="utf-8") в
src/app/paths.py) — порча случилась на стороне экспорта наблюдателя
(PowerShell-редирект), а не в коде существа.

Эти тесты — регрессия требования тикета: запись/чтение кириллицы по
главным путям (BufferedLogger, Sandbox) и BOM-независимое чтение.
"""

import codecs

from src.core.buffered_logger import BufferedLogger
from src.delamain.sandbox import Sandbox

CYRILLIC = "Изучить основы Python — заметка существа о мире"


def test_buffered_logger_writes_utf8_cyrillic(tmp_path):
    """Свежий лог открывается как UTF-8 без ручной конвертации."""
    log_file = tmp_path / "agent_log.txt"
    logger = BufferedLogger(log_file=str(log_file), buffer_size=1)
    logger.log(CYRILLIC)  # buffer_size=1 — запись сразу на диск

    raw = log_file.read_bytes()
    # байты — валидный UTF-8 и содержат кириллицу как есть
    text = raw.decode("utf-8")
    assert CYRILLIC in text
    # локальная кодировка Windows не понадобилась: файл читается явно
    assert "Python" in text


def test_sandbox_roundtrip_cyrillic(tmp_path):
    sandbox = Sandbox(tmp_path)
    sandbox.write_text("заметка.txt", CYRILLIC)
    assert sandbox.read_text("заметка.txt") == CYRILLIC
    # на диске — честный UTF-8 без BOM
    raw = (tmp_path / "заметка.txt").read_bytes()
    assert not raw.startswith(codecs.BOM_UTF8)
    assert raw.decode("utf-8") == CYRILLIC


def test_sandbox_read_is_bom_tolerant(tmp_path):
    """Файл с UTF-8 BOM (экспорт Windows-инструмента) читается чисто."""
    target = tmp_path / "экспорт.txt"
    target.write_bytes(codecs.BOM_UTF8 + CYRILLIC.encode("utf-8"))

    sandbox = Sandbox(tmp_path)
    assert sandbox.read_text("экспорт.txt") == CYRILLIC


def test_sandbox_append_keeps_utf8(tmp_path):
    sandbox = Sandbox(tmp_path)
    sandbox.write_text("дневник.txt", "первая строка")
    sandbox.append_text("дневник.txt", "\nвторая строка — с буквой ё")

    text = (tmp_path / "дневник.txt").read_bytes().decode("utf-8")
    assert "с буквой ё" in text
