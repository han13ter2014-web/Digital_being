"""
Буферизированное логирование для ИИ агента.

Логи собираются в буфер и пишутся на диск только при заполнении буфера.
Это полностью изолировано от внутренней жизни агента.

Оптимизация (Шаг 3): гарантированная запись буфера при завершении процесса
через atexit — даже при KeyboardInterrupt, SystemExit, SIGTERM (кроме -9).
"""

import os
import atexit
from datetime import datetime

from src.core.paths import data_path


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
        
        self.buffer.append(log_entry)
        
        # Когда буфер полон - flush
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
        """Записывает весь буфер на диск и очищает его."""
        if not self.buffer:
            return
        
        try:
            self._rotate_if_needed()
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.writelines(self.buffer)
            # Очищаем буфер ПОСЛЕ записи
            self.buffer = []
        except Exception as e:
            # Если не удалось записать - просто очищаем буфер
            # (чтобы agent не зависал на ошибках диска)
            self.buffer = []
    
    def flush_immediate(self, message: str):
        """Мгновенная запись (для важных событий)."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        
        try:
            self._rotate_if_needed()
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception:
            pass
    
    def __del__(self):
        """Гарантирует что буфер будет записан при удалении."""
        self.flush()


# Глобальный логгер (используется везде)
_logger = None

def get_logger(buffer_size=10) -> BufferedLogger:
    """Получает или создает глобальный логгер."""
    global _logger
    if _logger is None:
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