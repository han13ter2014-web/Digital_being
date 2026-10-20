"""
Watchdog — защита компьютера пользователя от деградации ресурсов.

Этичный «иммунитет» для хоста:
- Мониторит RSS процесса и CPU% (опционально через psutil).
- Если RSS > порога → инициирует «здоровую забывчивость» (LR_CONFIG.RSS_FORGET_RATIO).
- Если цикл «жизни» превысил порог — пропускает тяжёлые ветки (soul tick, will tick, communication tick).
- Backpressure: ограничивает размер pending_questions и генерацию новых стимулов.

Это НЕ цензура воли — это забота о «теле» (ресурсах), чтобы цифровая жизнь
могла продолжаться бесконечно, не превращая компьютер в кирпич.
"""

import os
import time
import threading
from typing import Callable, Dict, List, Optional

try:
    import psutil  # опциональная зависимость
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


class Watchdog:
    """Наблюдатель за здоровьем системы."""

    def __init__(self,
                 max_rss_mb: float = 500.0,
                 max_cycle_seconds: float = 30.0,
                 check_interval_cycles: int = 25):
        """
        Args:
            max_rss_mb: Мягкий предел RSS в МБ. При превышении — забывание.
            max_cycle_seconds: Если цикл дольше этого — пропускаем тяжёлые ветки.
            check_interval_cycles: Как часто проверять здоровье (в циклах).
        """
        self.max_rss_mb = float(max_rss_mb)
        self.max_cycle_seconds = float(max_cycle_seconds)
        self.check_interval_cycles = max(1, int(check_interval_cycles))

        # Состояние
        self._cycle_count = 0
        self._last_cycle_started: Optional[float] = None
        self._last_heavy_tick_cycle: int = 0
        self._skip_heavy_this_cycle: bool = False
        self._alerts: List[Dict] = []
        self._lock = threading.Lock()

        # Метрики
        self._peak_rss_mb: float = 0.0
        self._current_rss_mb: float = 0.0
        self._forced_forget_count: int = 0

    # ============================================================
    # Цикл
    # ============================================================

    def on_cycle_start(self) -> None:
        """Вызывается в начале каждого цикла."""
        self._cycle_count += 1
        self._last_cycle_started = time.monotonic()
        self._skip_heavy_this_cycle = False

    def on_cycle_end(self) -> None:
        """Вызывается в конце каждого цикла. Проверяет зависания."""
        if self._last_cycle_started is None:
            return
        elapsed = time.monotonic() - self._last_cycle_started
        if elapsed > self.max_cycle_seconds:
            # Цикл был слишком долгим — следующий пропускаем тяжёлое.
            self._skip_heavy_this_cycle = True
            self._emit_alert(
                "slow_cycle",
                f"Цикл #{self._cycle_count} занял {elapsed:.1f}с "
                f"(>{self.max_cycle_seconds}с). Следующие тяжёлые ветки пропущены.",
            )
        self._last_cycle_started = None

    # ============================================================
    # Управление тяжёлыми ветками
    # ============================================================

    def should_run_heavy_tick(self) -> bool:
        """Решает, запускать ли тяжёлый «тик» (soul, will, communication).

        Возвращает True, если:
        - Цикл не помечен как «пропустить тяжёлое».
        - Прошло достаточно циклов с последнего тяжёлого тика.
        """
        if self._skip_heavy_this_cycle:
            return False
        # Разрежение: минимум 1 цикл между тяжёлыми тиками.
        return (self._cycle_count - self._last_heavy_tick_cycle) >= 1

    def mark_heavy_tick_done(self) -> None:
        """Помечает, что тяжёлый тик только что выполнился."""
        self._last_heavy_tick_cycle = self._cycle_count

    # ============================================================
    # Мониторинг ресурсов
    # ============================================================

    def get_rss_mb(self) -> float:
        """Возвращает RSS текущего процесса в МБ (0 если psutil недоступен)."""
        if not _HAS_PSUTIL:
            return 0.0
        try:
            process = psutil.Process(os.getpid())
            rss_bytes = process.memory_info().rss
            rss_mb = rss_bytes / (1024 * 1024)
            self._current_rss_mb = rss_mb
            if rss_mb > self._peak_rss_mb:
                self._peak_rss_mb = rss_mb
            return rss_mb
        except Exception:
            return 0.0

    def get_cpu_percent(self) -> float:
        """Возвращает CPU% процесса (0 если недоступно)."""
        if not _HAS_PSUTIL:
            return 0.0
        try:
            process = psutil.Process(os.getpid())
            return float(process.cpu_percent(interval=None))
        except Exception:
            return 0.0

    def should_force_forget(self) -> bool:
        """Решает, нужно ли принудительное забывание (RSS > max_rss_mb)."""
        if not _HAS_PSUTIL:
            return False
        # Проверяем не каждый цикл — только раз в check_interval_cycles
        if self._cycle_count % self.check_interval_cycles != 0:
            return False
        rss = self.get_rss_mb()
        return rss > self.max_rss_mb

    def mark_forced_forget(self, count: int) -> None:
        """Записать, что было принудительно забыто N концепций."""
        self._forced_forget_count += count
        self._emit_alert(
            "memory_pressure",
            f"RSS > {self.max_rss_mb}МБ. Принудительно забыто {count} концепций.",
        )

    # ============================================================
    # Backpressure
    # ============================================================

    def can_enqueue_question(self, pending_count: int, max_pending: int) -> bool:
        """Можно ли поставить в очередь новый вопрос к пользователю?"""
        return pending_count < max_pending

    def should_throttle_stimuli(self) -> bool:
        """Решает, стоит ли пропустить генерацию стимулов (когда много pending)."""
        if not _HAS_PSUTIL:
            return False
        # Если RSS > 80% порога — замедляемся
        rss = self.get_rss_mb()
        return rss > (self.max_rss_mb * 0.8)

    # ============================================================
    # Статистика и алерты
    # ============================================================

    def _emit_alert(self, kind: str, message: str) -> None:
        """Регистрирует событие для последующего просмотра."""
        with self._lock:
            self._alerts.append({
                "cycle": self._cycle_count,
                "kind": kind,
                "message": message,
            })
            # Храним только последние 100 алертов
            if len(self._alerts) > 100:
                self._alerts = self._alerts[-100:]

    def get_alerts(self, n: int = 10) -> List[Dict]:
        """Возвращает последние N алертов."""
        with self._lock:
            return list(self._alerts[-n:])

    def get_status(self) -> Dict:
        """Возвращает статус watchdog для дашборда."""
        return {
            "psutil_available": _HAS_PSUTIL,
            "current_rss_mb": round(self._current_rss_mb, 1),
            "peak_rss_mb": round(self._peak_rss_mb, 1),
            "max_rss_mb": self.max_rss_mb,
            "forced_forget_count": self._forced_forget_count,
            "alerts_count": len(self._alerts),
            "cycle_count": self._cycle_count,
            "skip_heavy": self._skip_heavy_this_cycle,
        }


# Глобальный экземпляр watchdog (создаётся лениво)
_watchdog: Optional[Watchdog] = None


def get_watchdog(max_rss_mb: float = 500.0,
                 max_cycle_seconds: float = 30.0,
                 check_interval_cycles: int = 25) -> Watchdog:
    """Получает или создаёт глобальный watchdog."""
    global _watchdog
    if _watchdog is None:
        _watchdog = Watchdog(
            max_rss_mb=max_rss_mb,
            max_cycle_seconds=max_cycle_seconds,
            check_interval_cycles=check_interval_cycles,
        )
    return _watchdog