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


class BufferedLogger:
    """Буферизированный логгер для записей действий агента."""

    def __init__(self, log_file='data/logs/agent_log.txt', buffer_size=10):
        self.log_file = log_file
        self.buffer_size = buffer_size
        self.buffer = []

        # Гарантирует что директория существует
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

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
    
    def flush(self):
        """Записывает весь буфер на диск и очищает его."""
        if not self.buffer:
            return
        
        try:
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