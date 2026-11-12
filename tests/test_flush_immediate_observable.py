"""Наблюдаемость потерь в flush_immediate().

Та же пара, что для flush(): одна строка в stderr и счётчик
silent_losses на инстансе. flush_immediate пишет ровно одну строку —
единица потерь здесь одна строка, не чанк.

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


def test_flush_immediate_io_error_one_stderr_line_and_counter(
    tmp_path, monkeypatch, capsys
):
    """IO-ошибка в flush_immediate: одна строка в stderr, счётчик +1."""
    logger = _make_logger(tmp_path)

    monkeypatch.setattr(
        buffered_logger_module,
        "open",
        lambda *args, **kwargs: _BrokenFile(),
        raising=False,
    )
    logger.flush_immediate("важное событие")

    # Ровно одна строка потерь на один вызов, буфер не при делах.
    assert logger.silent_losses == 1

    err_lines = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    assert len(err_lines) == 1  # ровно одна строка в stderr
    assert err_lines[0].startswith("buffered_logger:")
    assert "flush_immediate" in err_lines[0]
    assert "OSError" in err_lines[0]


def test_flush_immediate_stays_alive_after_io_error(tmp_path, monkeypatch, capsys):
    """После IO-ошибки последующие вызовы живы: пишут и считают дальше."""
    logger = _make_logger(tmp_path)
    monkeypatch.setattr(
        buffered_logger_module,
        "open",
        lambda *args, **kwargs: _BrokenFile(),
        raising=False,
    )
    logger.flush_immediate("потеряно")

    monkeypatch.undo()  # запись снова работает
    logger.flush_immediate("выжило")
    logger.flush_immediate("выжило тоже")

    # Счётчик не сбросился: потеря не забыта.
    assert logger.silent_losses == 1
    with open(logger.log_file, encoding="utf-8") as f:
        content = f.read()
    assert "потеряно" not in content  # проглоченная строка не на диске
    assert content.count("выжило") == 2  # последующие вызовы пишут норм
    # Успешные вызовы не пишут в stderr: одна строка от первого сбоя.
    err_lines = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    assert len(err_lines) == 1

    # Новый сбой после восстановления снова растит счётчик.
    monkeypatch.setattr(
        buffered_logger_module,
        "open",
        lambda *args, **kwargs: _BrokenFile(),
        raising=False,
    )
    logger.flush_immediate("снова потеряно")
    assert logger.silent_losses == 2
