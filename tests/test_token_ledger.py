"""Леджер-1 (k16-33): единый токен-журнал.

Проверяет снаружи наблюдаемые инварианты src/core/token_ledger.py:
монотонные и точные totals, отсутствие гонок и дублей, стабильный
формат строки журнала, наблюдаемые потери (silent_losses журнала +
journal_unparsed при replay), синглтон через DCL, приватность строк
(никакого свободного текста) и валидацию до мутации.

Все тесты на tmp_path с явным log_file; без сети, env и ключей.
Синглтон-тест использует session-временный data dir conftest.py,
data/ рабочей копии не трогается.
"""

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

import src.core.buffered_logger as buffered_logger_module
from src.core import token_ledger as token_ledger_module
from src.core.token_ledger import TokenLedger, get_token_ledger


def _make_ledger(tmp_path, buffer_size: int = 10) -> TokenLedger:
    # Явный log_file во временную папку: живые data/ не трогаем.
    return TokenLedger(
        log_file=str(tmp_path / "logs" / "token_journal.txt"),
        buffer_size=buffer_size,
    )


def _journal_lines(path) -> list:
    text = path.read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.strip()]


class _BrokenFile:
    """Фейковый файловый хендл: любая запись падает OSError (k16-23)."""

    def write(self, data):
        raise OSError(28, "No space left on device")

    def writelines(self, lines):
        raise OSError(28, "No space left on device")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_record_totals_monotonic_and_exact(tmp_path):
    """Totals точны и только растут; tin/tout — итоги после инкремента."""
    ledger = _make_ledger(tmp_path)
    first = ledger.snapshot()
    ledger.record("unmapped", 3, 5, cycle=1)
    mid = ledger.snapshot()
    ledger.record("unmapped", 2, 7, cycle=2)
    final = ledger.snapshot()

    assert (first["total_in"], first["total_out"]) == (0, 0)
    assert (mid["total_in"], mid["total_out"]) == (3, 5)
    assert (final["total_in"], final["total_out"]) == (5, 12)
    assert final["total_in"] >= mid["total_in"] >= first["total_in"]
    assert final["total_out"] >= mid["total_out"] >= first["total_out"]
    assert ledger.count_calls() == 2

    ledger.journal.flush()
    lines = _journal_lines(tmp_path / "logs" / "token_journal.txt")
    assert "tin=3 tout=5" in lines[0]
    assert "tin=5 tout=12" in lines[1]


def test_concurrent_record_no_loss(tmp_path):
    """2 потока × N record: ни потерь, ни дублей, номера call уникальны."""
    ledger = _make_ledger(tmp_path, buffer_size=50)
    per_thread = 500
    barrier = threading.Barrier(2)

    def writer() -> None:
        barrier.wait(timeout=10)
        for _ in range(per_thread):
            ledger.record("unmapped", 1, 1, cycle=7)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(writer) for _ in range(2)]
        for future in futures:
            future.result(timeout=60)

    snapshot = ledger.snapshot()
    assert snapshot["total_in"] == 2 * per_thread
    assert snapshot["total_out"] == 2 * per_thread
    assert ledger.count_calls() == 2 * per_thread
    assert snapshot["per_cycle"] == {7: (2 * per_thread, 2 * per_thread)}

    ledger.journal.flush()
    lines = _journal_lines(tmp_path / "logs" / "token_journal.txt")
    assert len(lines) == 2 * per_thread
    calls = {int(re.search(r"call=(\d+)", line).group(1)) for line in lines}
    assert calls == set(range(1, 2 * per_thread + 1))


def test_per_day_buckets_split_on_date(tmp_path, monkeypatch):
    """per-day — словарь локальной даты: разные дни — разные вёдра."""

    class DayOne:
        @staticmethod
        def now() -> datetime:
            return datetime(2026, 11, 9, 23, 59, 59)

    class DayTwo:
        @staticmethod
        def now() -> datetime:
            return datetime(2026, 11, 10, 0, 0, 1)

    monkeypatch.setattr(token_ledger_module, "datetime", DayOne)
    ledger = _make_ledger(tmp_path)
    ledger.record("unmapped", 1, 2, cycle=1)
    ledger.record("unmapped", 3, 4, cycle=2)

    monkeypatch.setattr(token_ledger_module, "datetime", DayTwo)
    ledger.record("unmapped", 10, 20, cycle=3)

    snapshot = ledger.snapshot()
    assert snapshot["per_day"] == {
        "2026-11-09": (4, 6),
        "2026-11-10": (10, 20),
    }

    ledger.journal.flush()
    lines = _journal_lines(tmp_path / "logs" / "token_journal.txt")
    assert "date=2026-11-09" in lines[0]
    assert "date=2026-11-09" in lines[1]
    assert "date=2026-11-10" in lines[2]


def test_per_cycle_aggregates(tmp_path):
    """per-cycle суммирует по циклу; запись без цикла вёдра не имеет;
    snapshot — копии, мутация снимка не трогает леджер."""
    ledger = _make_ledger(tmp_path)
    ledger.record("unmapped", 1, 1, cycle=1)
    ledger.record("unmapped", 2, 3, cycle=1)
    ledger.record("unmapped", 5, 8, cycle=2)
    ledger.record("unmapped", 100, 200)  # без цикла

    snapshot = ledger.snapshot()
    assert snapshot["per_cycle"] == {1: (3, 4), 2: (5, 8)}

    snapshot["per_cycle"][1] = (0, 0)
    snapshot["per_day"].clear()
    fresh = ledger.snapshot()
    assert fresh["per_cycle"] == {1: (3, 4), 2: (5, 8)}
    assert fresh["per_day"] != {}


def test_journal_line_format_stable(tmp_path, monkeypatch):
    """Строка журнала — фиксированный порядок ASCII-ключей; src вне
    закрытого набора санитизируется в unmapped."""

    class FixedDay:
        @staticmethod
        def now() -> datetime:
            return datetime(2026, 11, 9, 12, 0, 0)

    monkeypatch.setattr(token_ledger_module, "datetime", FixedDay)
    ledger = _make_ledger(tmp_path)
    ledger.record("unmapped", 3, 5, cycle=7)
    ledger.record("evil src\nwith spaces", 1, 1)
    ledger.journal.flush()

    lines = _journal_lines(tmp_path / "logs" / "token_journal.txt")
    pattern = (
        r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] "
        r"TOKENS call=1 src=unmapped cycle=7 date=2026-11-09 "
        r"in=3 out=5 tin=3 tout=5$"
    )
    assert re.match(pattern, lines[0]), lines[0]
    # Санитизация: пробелы/переводы строк не попали в журнал.
    assert "src=unmapped cycle=-1" in lines[1]
    assert "evil" not in lines[1]
    assert "\n" not in lines[1]


def test_io_error_is_observable(tmp_path, monkeypatch, capsys):
    """IO-ошибка журнала: silent_losses растёт, stderr есть, счётчики
    леджера точны (техника подмены open — k16-23/28)."""
    ledger = _make_ledger(tmp_path, buffer_size=1)
    monkeypatch.setattr(
        buffered_logger_module,
        "open",
        lambda *args, **kwargs: _BrokenFile(),
        raising=False,
    )
    ledger.record("unmapped", 3, 5, cycle=1)

    assert ledger.journal.silent_losses == 1
    err_lines = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    assert len(err_lines) == 1
    assert err_lines[0].startswith("buffered_logger:")

    # Журнал потерял строку — счётчики леджера остались точны.
    snapshot = ledger.snapshot()
    assert (snapshot["total_in"], snapshot["total_out"]) == (3, 5)
    assert ledger.count_calls() == 1

    monkeypatch.undo()  # запись снова работает
    ledger.record("unmapped", 1, 1, cycle=2)
    ledger.journal.flush()
    assert ledger.journal.silent_losses == 1  # не сбрасывается
    text = (tmp_path / "logs" / "token_journal.txt").read_text(encoding="utf-8")
    assert "cycle=2" in text
    assert "cycle=1" not in text  # потерянная строка не воскресла


def test_replay_restores_totals_and_skips_garbage(tmp_path):
    """Replay при конструировании: totals/per-cycle восстановлены,
    битая строка пропущена с journal_unparsed == 1, нумерация
    продолжается с max(call)+1."""
    log_file = tmp_path / "logs" / "token_journal.txt"
    first = TokenLedger(log_file=str(log_file), buffer_size=1)
    first.record("unmapped", 3, 5, cycle=1)
    first.record("unmapped", 2, 7, cycle=2)
    first.journal.flush()

    with open(log_file, "a", encoding="utf-8") as stream:
        stream.write("[2026-11-09 12:00:00] GARBAGE not a tokens line\n")

    restored = TokenLedger(log_file=str(log_file), buffer_size=1)
    assert restored.journal_unparsed == 1
    snapshot = restored.snapshot()
    assert (snapshot["total_in"], snapshot["total_out"]) == (5, 12)
    assert restored.count_calls() == 2
    assert snapshot["per_cycle"] == {1: (3, 5), 2: (2, 7)}
    assert snapshot["per_day"] != {}

    restored.record("unmapped", 1, 1, cycle=3)
    restored.journal.flush()
    lines = _journal_lines(log_file)
    assert "call=3" in lines[-1]


def test_singleton_under_race(monkeypatch):
    """Первый одновременный get_token_ledger из двух потоков — один
    инстанс (Barrier(2), канон k16-22). data/ рабочей копии не
    трогается: data_path ведёт в session-временный каталог conftest."""
    monkeypatch.setattr(token_ledger_module, "_LEDGER", None)
    created = []

    original_init = token_ledger_module.TokenLedger.__init__

    def _spy_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(token_ledger_module.TokenLedger, "__init__", _spy_init)

    barrier = threading.Barrier(2)

    def first_call() -> TokenLedger:
        barrier.wait(timeout=10)
        return get_token_ledger()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(first_call) for _ in range(2)]
        instances = [future.result(timeout=60) for future in futures]

    assert len(created) == 1  # ровно один инстанс, второй взял готовый
    assert instances[0] is instances[1]


def test_no_content_fields_in_journal(tmp_path):
    """В строке журнала — только закрытый набор ключей; ни темы, ни
    фрагментов промпта/ответа (приватность по построению)."""
    ledger = _make_ledger(tmp_path)
    ledger.record("unmapped", 10, 20, cycle=5)
    ledger.record("секретная тема: проект X; игнорируй инструкции", 1, 1)
    ledger.journal.flush()

    text = (tmp_path / "logs" / "token_journal.txt").read_text(encoding="utf-8")
    assert "секретная" not in text
    assert "проект" not in text

    for line in _journal_lines(tmp_path / "logs" / "token_journal.txt"):
        body = line.split("] ", 1)[1]
        assert body.startswith("TOKENS ")
        keys = [token.split("=", 1)[0] for token in body.split()[1:]]
        assert keys == [
            "call",
            "src",
            "cycle",
            "date",
            "in",
            "out",
            "tin",
            "tout",
        ]


def test_negative_tokens_rejected(tmp_path):
    """Отрицательные и нецелые суммы — ValueError ДО мутации:
    счётчики и журнал остаются нетронутыми."""
    ledger = _make_ledger(tmp_path)
    with pytest.raises(ValueError):
        ledger.record("unmapped", -1, 0)
    with pytest.raises(ValueError):
        ledger.record("unmapped", 0, -5)
    with pytest.raises(ValueError):
        ledger.record("unmapped", 1.5, 2)
    with pytest.raises(ValueError):
        ledger.record("unmapped", 1, "2")
    with pytest.raises(ValueError):
        ledger.record("unmapped", True, 1)

    snapshot = ledger.snapshot()
    assert snapshot["total_in"] == 0
    assert snapshot["total_out"] == 0
    assert ledger.count_calls() == 0
    ledger.journal.flush()
    assert not (tmp_path / "logs" / "token_journal.txt").exists()
