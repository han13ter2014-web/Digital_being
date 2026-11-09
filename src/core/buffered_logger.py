"""
Буферизированное логирование для ИИ агента.

Логи собираются в буфер и пишутся на диск только при заполнении буфера.
Это полностью изолировано от внутренней жизни агента.

Оптимизация (Шаг 3): гарантированная запись буфера при завершении процесса
через atexit — даже при KeyboardInterrupt, SystemExit, SIGTERM (кроме -9).
"""

import os
import atexit
import sys
import threading
from datetime import datetime

from src.core.paths import data_path


# «Харднинг-1» (k16-21): защита создания глобального логгера — race в
# get_logger() при первом вызове из двух потоков давал бы два инстанса
# и два независимых буфера (потери и дубли записи).
_GET_LOGGER_LOCK = threading.Lock()


class BufferedLogger:
    """Буферизированный логгер для записей действий агента.

    Ротация: когда файл вырастает до ``max_bytes``, он переименовывается
    в ``agent_log.txt.1``, старые сдвигаются, самый старый удаляется.
    Без этого лог за 4 месяца вырос до 420 МБ (см. docs/BASELINE.md).
    """

    def __init__(self, log_file=None, buffer_size=10,
                 max_bytes=10 * 1024 * 1024, backup_count=3):
        self.log_file = log_file or data_path("logs", "agent_log.txt")
        self.buffer_size = buffer_size
        self.buffer = []
        self.max_bytes = max_bytes
        self.backup_count = backup_count

        # k16-23: счётчик тихих потерь — сколько строк журнала потеряно
        # при ошибках записи в flush(). Увеличивается под локом, читается
        # без лока (чтение int атомарно). Автоматически не сбрасывается.
        self.silent_losses = 0

        # «Харднинг-1» (k16-21): один RLock на инстанс. RLock, а не Lock:
        # log() держит лок при append и вызывает flush() из-под него
        # (авто-flush по переполнении) — на обычном Lock это взаимная
        # блокировка. Раньше append в log() и check-then-act в flush()
        # шли без синхронизации — при concurrent-писателях (runner-
        # потоки, tray) возможны были дубли/потери строк и перемежение
        # чанков.
        self._lock = threading.RLock()

        # Гарантирует что директория существует
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        # Шаг 3: гарантированный flush при выходе
        # atexit сработает при нормальном завершении и большинстве исключений.
        try:
            atexit.register(self.flush)
        except Exception:
            pass
    
    def log(self, message: str):
        """Добавляет запись в буфер. Когда буфер полон - пишет на диск."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"

        with self._lock:
            self.buffer.append(log_entry)

            # Когда буфер полон - flush (лок отпущен перед I/O: см. flush)
            if len(self.buffer) >= self.buffer_size:
                self.flush()

    def _rotate_if_needed(self) -> None:
        """Сдвигает файлы лога, если текущий достиг ``max_bytes``.

        Ошибки файловой системы не должны ломать жизнь агента,
        поэтому любые сбои здесь проглатываются осознанно.
        """
        if not self.max_bytes or not os.path.exists(self.log_file):
            return
        try:
            if os.path.getsize(self.log_file) < self.max_bytes:
                return

            if self.backup_count <= 0:
                # Ротация отключена — просто начинаем файл заново.
                open(self.log_file, 'w', encoding='utf-8').close()
                return

            oldest = f"{self.log_file}.{self.backup_count}"
            if os.path.exists(oldest):
                os.remove(oldest)

            for i in range(self.backup_count - 1, 0, -1):
                src = f"{self.log_file}.{i}"
                if os.path.exists(src):
                    os.replace(src, f"{self.log_file}.{i + 1}")

            os.replace(self.log_file, f"{self.log_file}.1")
        except OSError:
            # Диск занят/нет прав — пишем дальше в текущий файл.
            pass

    def flush(self):
        """Записывает весь буфер на диск и очищает его.

        Вся последовательность «снять чанк → писать в файл» — под одним
        локом. Иначе два flush() параллельно: чанки меняются местами
        (порядок событий в автобиографии ломается), а на Windows два
        open(append)-хендла имеют независимые указатели и перекрывают
        байты друг друга — строки теряются молча. Reentrant-вызов из
        log() безопасен: RLock, не Lock.

        k16-23: при ошибке записи чанк теряется осознанно (как и раньше),
        но потеря наблюдаема — счётчик ``silent_losses`` на инстансе и
        одна строка в stderr. Сам логгер в себя не пишет: рекурсия и
        повторная ошибка ни к чему.
        """
        with self._lock:
            if not self.buffer:
                return
            chunk, self.buffer = self.buffer, []
            try:
                self._rotate_if_needed()
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.writelines(chunk)
            except Exception as e:
                # Если не удалось записать - теряем чанк осознанно
                # (чтобы agent не зависал на ошибках диска), как и раньше.
                # k16-23: но теперь потеря наблюдаема (см. docstring).
                self.silent_losses += len(chunk)
                detail = " ".join(str(e).split())
                suffix = f": {detail}" if detail else ""
                try:
                    print(
                        f"buffered_logger: потерян чанк из {len(chunk)} строк"
                        f" при flush: {type(e).__name__}{suffix}",
                        file=sys.stderr,
                    )
                except Exception:
                    # stderr может быть закрыт или отсутствовать (pythonw,
                    # teardown) — печать не должна уронить flush, чтобы
                    # swallow-семантика сохранялась целиком.
                    pass
    
    def flush_immediate(self, message: str):
        """Мгновенная запись (для важных событий).

        k16-27: ошибка записи не молчит — счётчик ``silent_losses``
        и одна строка в stderr (семантика и формат общие с k16-23
        для flush()); единица потерь здесь — одна строка, не чанк.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"

        # «Харднинг-1» (k16-21): под тем же локом, что буфер — иначе
        # немедленная строка может вклиниться МЕЖДУ чанком буфера и
        # записью, ломая порядок событий в автобиографии.
        with self._lock:
            try:
                self._rotate_if_needed()
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(log_entry)
            except Exception as e:
                # Если не удалось записать - теряем строку осознанно,
                # как и раньше, но теперь потеря наблюдаема.
                self.silent_losses += 1
                detail = " ".join(str(e).split())
                suffix = f": {detail}" if detail else ""
                try:
                    print(
                        f"buffered_logger: потеряна строка"
                        f" при flush_immediate: {type(e).__name__}{suffix}",
                        file=sys.stderr,
                    )
                except Exception:
                    # stderr может быть закрыт или отсутствовать (pythonw,
                    # teardown) — печать не должна уронить
                    # flush_immediate, чтобы swallow-семантика
                    # сохранялась целиком.
                    pass
    
    def __del__(self):
        """Гарантирует что буфер будет записан при удалении."""
        self.flush()


# Глобальный логгер (используется везде)
_logger = None

def get_logger(buffer_size=10) -> BufferedLogger:
    """Получает или создает глобальный логгер.

    «Харднинг-1» (k16-21): создание под глобальным локом — race при
    первом одновременном вызове давал бы два инстанса и два буфера.
    """
    global _logger
    if _logger is None:
        with _GET_LOGGER_LOCK:
            if _logger is None:  # double-check: другой поток успел первым
                _logger = BufferedLogger(buffer_size=buffer_size)
    return _logger


def log(message: str, buffer_size=10):
    """Удобная функция для логирования."""
    logger = get_logger(buffer_size)
    logger.log(message)


def flush_logs():
    """Гарантирует запись всех логов на диск."""
    global _logger
    if _logger is not None:
        _logger.flush()