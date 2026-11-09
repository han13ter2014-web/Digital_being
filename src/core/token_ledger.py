"""Единый токен-журнал (Леджер-1, k16-33).

Централизованный учёт потребления токенов: один журнал, один набор
счётчиков, наблюдаемые потери. Леджер — пассивный самописец: вызывающий
код сам сообщает дельты через ``record()``. Вне скоупа v1: перехват
LLM-вызовов, квоты/алерты, сетевые вызовы, чтение ключей, дашборды
(точки врезки — следующий тикет после карты k16-31).

Границы решения:

- журнал ведётся ДЕЛЕГИРОВАНИЕМ экземпляру ``BufferedLogger`` — леджер
  наследует RLock записи, ротацию, atexit-flush и silent_losses-
  конвенцию (k16-21/23/27), не изменяя сам BufferedLogger;
- единственный инстанс — :func:`get_token_ledger`: модульный Lock +
  double-checked создание, зеркально ``get_logger()`` (k16-21);
- источник истины — строки журнала (append). Счётчики в памяти
  восстанавливаются replay'ем журнала при конструировании; replay
  идемпотентен, потому что происходит только там. Битая строка
  пропускается с ``journal_unparsed += 1`` — тихих потерь нет по
  построению (IO-потери строк видны через ``journal.silent_losses``);
- replay читает только активный файл журнала: отротированные хвосты
  вне v1. Checkpoint-схема не затрагивается;
- без сети и без чтения env: модуль импортирует только stdlib,
  ``src.core.buffered_logger`` и ``src.core.paths``.

Формат строки журнала (префикс ``[YYYY-MM-DD HH:MM:SS]`` добавляет
BufferedLogger; тело — фиксированный порядок ASCII-ключей)::

    TOKENS call=<n> src=<метка> cycle=<n> date=<YYYY-MM-DD> \
in=<n> out=<n> tin=<n> tout=<n>

``cycle=-1`` — запись без цикла (``cycle=None``). ``tin``/``tout`` —
итоги после инкремента. В строку не может попасть свободный текст,
тема или фрагмент промпта/ответа: ключи закрыты, ``src`` санитизируется
в закрытый набор ``TOKEN_SOURCES``.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from src.core.buffered_logger import BufferedLogger
from src.core.paths import data_path

# Закрытый набор меток источников. "unmapped" — записи без привязки;
# "planner" — телеметрия OllamaPlanner (k16-36, врезка в _plan).
TOKEN_SOURCES = frozenset({"unmapped", "planner"})

# Тело строки журнала с префиксом BufferedLogger. Полный матч: всё,
# что не соответствует формату, при replay считается битой строкой.
_LINE_RE = re.compile(
    r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] "
    r"TOKENS call=(\d+) src=(\S+) cycle=(-?\d+) "
    r"date=(\d{4}-\d{2}-\d{2}) "
    r"in=(\d+) out=(\d+) tin=(\d+) tout=(\d+)$"
)

# Запись без цикла кодируется sentinel'ом, чтобы строка была валидной
# для replay (формат требует cycle=<n>).
_NO_CYCLE = -1


def _sanitize_src(src: object) -> str:
    """Метка источника из закрытого набора.

    Пробелы и переводы строк сворачиваются в ``_`` (санитизация
    формата); метка вне ``TOKEN_SOURCES`` заменяется на ``unmapped`` —
    в журнал не может попасть свободный текст.
    """
    label = re.sub(r"\s+", "_", str(src))
    return label if label in TOKEN_SOURCES else "unmapped"


def _validate_amount(name: str, value: int) -> None:
    """Сумма токенов — неотрицательный int (bool не считается)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value}")


class TokenLedger:
    """Единый журнал и счётчики потребления токенов.

    Собственный ``threading.RLock`` — на все мутации счётчиков; запись
    строк файла — под RLock делегированного BufferedLogger. Леджер не
    выбирает, что считать: он пассивно принимает дельты через
    :meth:`record` и честно их суммирует.
    """

    def __init__(self, log_file: Optional[str] = None, buffer_size: int = 10) -> None:
        self._lock = threading.RLock()
        self._journal = BufferedLogger(
            log_file=log_file or data_path("logs", "token_journal.txt"),
            buffer_size=buffer_size,
        )
        self._total_in = 0
        self._total_out = 0
        self._calls = 0
        self._per_cycle: Dict[int, Tuple[int, int]] = {}
        self._per_day: Dict[str, Tuple[int, int]] = {}
        # Битые строки журнала при replay: потеря видима, не молчит.
        self.journal_unparsed = 0
        self._replay()

    # === Запись ===

    def record(
        self, src: str, in_tokens: int, out_tokens: int, cycle: Optional[int] = None
    ) -> None:
        """Записать одно обращение: дельты токенов и метку источника.

        Валидация — ДО любой мутации: отрицательные и нецелые суммы
        отклоняются ValueError, счётчики и журнал остаются нетронутыми.
        """
        _validate_amount("in_tokens", in_tokens)
        _validate_amount("out_tokens", out_tokens)
        if cycle is not None and (
            isinstance(cycle, bool) or not isinstance(cycle, int)
        ):
            raise ValueError(
                f"cycle must be an int or None, got {type(cycle).__name__}"
            )
        label = _sanitize_src(src)
        date = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            self._total_in += in_tokens
            self._total_out += out_tokens
            self._calls += 1
            if cycle is not None:
                cycle_in, cycle_out = self._per_cycle.get(cycle, (0, 0))
                self._per_cycle[cycle] = (
                    cycle_in + in_tokens,
                    cycle_out + out_tokens,
                )
            day_in, day_out = self._per_day.get(date, (0, 0))
            self._per_day[date] = (day_in + in_tokens, day_out + out_tokens)
            body = (
                f"TOKENS call={self._calls} src={label} "
                f"cycle={cycle if cycle is not None else _NO_CYCLE} "
                f"date={date} "
                f"in={in_tokens} out={out_tokens} "
                f"tin={self._total_in} tout={self._total_out}"
            )
            self._journal.log(body)

    # === Чтение ===

    @property
    def journal(self) -> BufferedLogger:
        """Делегированный журнал: наблюдаемость потерь (silent_losses)
        и ротации. Запись — только через :meth:`record`."""
        return self._journal

    def count_calls(self) -> int:
        """Число записанных обращений (монотонно, не сбрасывается)."""
        with self._lock:
            return self._calls

    def snapshot(self) -> Dict[str, Any]:
        """Снимок счётчиков: копии, не живые структуры."""
        with self._lock:
            return {
                "calls": self._calls,
                "total_in": self._total_in,
                "total_out": self._total_out,
                "per_cycle": dict(self._per_cycle),
                "per_day": dict(self._per_day),
                "journal_unparsed": self.journal_unparsed,
            }

    # === Восстановление ===

    def _replay(self) -> None:
        """Переиграть журнал при конструировании.

        Totals/per-day/per-cycle восстанавливаются суммированием
        валидных строк; ``call`` продолжается с max+1, чтобы потерянная
        строка не дала дубликат номера. Битая строка пропускается
        с ``journal_unparsed += 1``. Вызывается один раз, из
        конструктора — идемпотентность по построению.
        """
        try:
            with open(self._journal.log_file, encoding="utf-8") as stream:
                lines = stream.read().splitlines()
        except FileNotFoundError:
            return
        except OSError:
            # Журнал не читается: потеря видима, как и битая строка.
            self.journal_unparsed += 1
            return
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            match = _LINE_RE.match(stripped)
            if match is None:
                self.journal_unparsed += 1
                continue
            call_n = int(match.group(1))
            cycle_n = int(match.group(3))
            date = match.group(4)
            in_n = int(match.group(5))
            out_n = int(match.group(6))
            self._calls = max(self._calls, call_n)
            self._total_in += in_n
            self._total_out += out_n
            if cycle_n != _NO_CYCLE:
                cycle_in, cycle_out = self._per_cycle.get(cycle_n, (0, 0))
                self._per_cycle[cycle_n] = (
                    cycle_in + in_n,
                    cycle_out + out_n,
                )
            day_in, day_out = self._per_day.get(date, (0, 0))
            self._per_day[date] = (day_in + in_n, day_out + out_n)


# Глобальный леджер (создаётся один раз, зеркально get_logger()).
_LEDGER: Optional[TokenLedger] = None

# DCL-лок создания: race при первом одновременном вызове давал бы два
# инстанса и два журнала (потери и дубли записи) — канон k16-21.
_GET_LEDGER_LOCK = threading.Lock()


def get_token_ledger() -> TokenLedger:
    """Единственный инстанс леджера (модульный Lock + double-check)."""
    global _LEDGER
    if _LEDGER is None:
        with _GET_LEDGER_LOCK:
            if _LEDGER is None:  # double-check: другой поток успел первым
                _LEDGER = TokenLedger()
    return _LEDGER


__all__ = ["TOKEN_SOURCES", "TokenLedger", "get_token_ledger"]
