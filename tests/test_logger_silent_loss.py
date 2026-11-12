"""Наблюдаемость тихих потерь BufferedLogger.

При IO-ошибке записи чанка в flush() логгер обязан:
- выдать ровно одну строку в stderr (свой формат, без [LABEL]-стиля);
- увеличить silent_losses ровно на размер чанка (в строках);
- сохранить работоспособность: буфер очищен, следующий flush пишет нормально.

IO-ошибка имитируется подменой open() в модуле buffered_logger на
фейковый хендл с падающим write()/writelines(): типы _io иммутабельны,
патчить io.TextIOWrapper.write напрямую нельзя.
"""

import src.core.buffered_logger as buffered_logger_module
from src.core.buffered_logger import BufferedLogger


class _BrokenFile:
    """Фейковый файловый хендл: любая запись падает OSError."""

    def write(self, data):
        raise OSError(28, "No space left on device")

    def writelines(self, lines):
        raise OSError(28, "No space left on device")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _make_logger(tmp_path) -> BufferedLogger:
    # Явный log_file во временную папку: живые data/ не трогаем.
    return BufferedLogger(log_file=str(tmp_path / "agent_log.txt"), buffer_size=10)


def test_flush_io_error_one_stderr_line_and_counter(tmp_path, monkeypatch, capsys):
    """IO-ошибка при flush: одна строка в stderr, счётчик = размер чанка."""
    logger = _make_logger(tmp_path)
    for i in range(3):
        logger.log(f"строка {i}")

    monkeypatch.setattr(
        buffered_logger_module,
        "open",
        lambda *args, **kwargs: _BrokenFile(),
        raising=False,
    )
    logger.flush()

    # Счётчик вырос ровно на размер чанка (3 строки), буфер очищен —
    # swallow-семантика прежняя, flush исключение не пробросил.
    assert logger.silent_losses == 3
    assert logger.buffer == []

    err_lines = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    assert len(err_lines) == 1  # ровно одна строка в stderr
    assert err_lines[0].startswith("buffered_logger:")
    assert "потерян чанк из 3 строк" in err_lines[0]
    assert "OSError" in err_lines[0]


def test_next_flush_after_io_error_writes_normally(tmp_path, monkeypatch, capsys):
    """После IO-ошибки буфер и продолжение работы не пострадали."""
    logger = _make_logger(tmp_path)
    for i in range(3):
        logger.log(f"потеряно {i}")
    monkeypatch.setattr(
        buffered_logger_module,
        "open",
        lambda *args, **kwargs: _BrokenFile(),
        raising=False,
    )
    logger.flush()
    assert logger.silent_losses == 3

    monkeypatch.undo()  # запись снова работает
    for i in range(2):
        logger.log(f"выжило {i}")
    logger.flush()

    # Счётчик НЕ сбросился автоматически.
    assert logger.silent_losses == 3
    # Проглоченный чанк не появился на диске, следующий flush пишет норм.
    with open(logger.log_file, encoding="utf-8") as f:
        content = f.read()
    assert "потеряно" not in content
    assert content.count("выжило") == 2
    # Второй (успешный) flush не добавил строк в stderr.
    err_lines = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    assert len(err_lines) == 1
