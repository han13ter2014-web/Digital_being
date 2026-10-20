"""
MetricsCollector — сбор и хранение метрик Digital Being (Этап 3.6).

Архитектурное решение:
- Метрики хранятся как time-series (список {ts, value}) для построения графиков.
- Несколько «каналов» (cycles, energy, intelligence, completed_goals,
  concepts_count, rss_mb) — каждый со своей историей.
- Хранилище потокобезопасно (RLock).
- Экспорт в JSON для дашборда (графики рисуются в Chart.js на клиенте).
- Опциональная персистентность в data/metrics/ (NDJSON — компактный формат).

Использование:
    from src.metrics.metrics_collector import MetricsCollector
    mc = MetricsCollector()
    mc.record("energy", 150, cycle=1)
    mc.record("energy", 145, cycle=2)
    history = mc.get_history("energy", last_n=100)
    snapshot = mc.snapshot()

Подключение к DigitalBeing (Этап 3.6):
    # в DigitalBeing.__init__():
    self.metrics = MetricsCollector()
    # в tick_soul / evolve:
    self.metrics.record("energy", self.energy, cycle=self.cycle_count)
    self.metrics.record("intelligence", self.intelligence, cycle=self.cycle_count)
"""

import json
import logging
import os
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from src.core.paths import data_path


logger = logging.getLogger(__name__)


# ============================================================
# Каналы по умолчанию — основные метрики агента
# ============================================================

DEFAULT_CHANNELS = (
    "energy",
    "intelligence",
    "cycle_count",
    "completed_goals",
    "concepts_count",
    "rss_mb",
    "subsystems_active",
    "thoughts_per_minute",
    "actions_per_minute",
)


class MetricsCollector:
    """Сборщик метрик с time-series историей.

    Особенности:
    - Один канал — один deque (cap=maxlen).
    - record(channel, value) — быстрая O(1) запись.
    - get_history(channel, last_n) — последние N точек.
    - snapshot() — все каналы для дашборда.
    - export_json() — для сохранения на диск.
    """

    # Дефолтные лимиты для каждого канала.
    DEFAULT_CAPACITY = 720  # ~12 минут при тике раз в секунду

    def __init__(self, maxlen_per_channel: int = DEFAULT_CAPACITY,
                 persist_dir: Optional[str] = None,
                 agent_name: str = "unknown") -> None:
        self._lock = threading.RLock()
        self._maxlen = maxlen_per_channel
        self._channels: Dict[str, Deque[Dict[str, Any]]] = {}
        self._channels_max: Dict[str, float] = {}
        self._channels_min: Dict[str, float] = {}
        self._persist_dir = persist_dir
        self._agent_name = agent_name
        # Счётчики rate (per minute)
        self._counters: Dict[str, List[float]] = {}
        self._counters_window_sec: float = 60.0

        # Инициализируем дефолтные каналы
        for ch in DEFAULT_CHANNELS:
            self._channels[ch] = deque(maxlen=self._maxlen)
            self._channels_max[ch] = float("-inf")
            self._channels_min[ch] = float("inf")
            self._counters[ch] = []

    # ----------------------------------------------------------------
    # Запись метрик
    # ----------------------------------------------------------------

    def record(self, channel: str, value: float, *,
               cycle: Optional[int] = None,
               meta: Optional[Dict[str, Any]] = None) -> None:
        """Записать точку в канал. Создаёт канал при первом использовании.

        Args:
            channel: имя метрики (energy, intelligence, ...).
            value: числовое значение.
            cycle: номер цикла (опционально).
            meta: дополнительные поля для дашборда.
        """
        ts = time.time()
        entry: Dict[str, Any] = {
            "ts": ts,
            "value": float(value),
        }
        if cycle is not None:
            entry["cycle"] = int(cycle)
        if meta:
            entry["meta"] = meta

        with self._lock:
            if channel not in self._channels:
                self._channels[channel] = deque(maxlen=self._maxlen)
                self._channels_max[channel] = float("-inf")
                self._channels_min[channel] = float("inf")
                self._counters[channel] = []
            self._channels[channel].append(entry)
            # min/max
            if value > self._channels_max[channel]:
                self._channels_max[channel] = float(value)
            if value < self._channels_min[channel]:
                self._channels_min[channel] = float(value)

    def increment(self, channel: str, amount: float = 1.0, *,
                  cycle: Optional[int] = None) -> None:
        """Записать инкремент (rate-counter). Используется для подсчёта
        событий за минуту."""
        self.record(channel, amount, cycle=cycle)
        with self._lock:
            self._counters.setdefault(channel, []).append(time.time())
            # Очищаем старые точки
            cutoff = time.time() - self._counters_window_sec
            self._counters[channel] = [t for t in self._counters[channel] if t >= cutoff]

    # ----------------------------------------------------------------
    # Чтение
    # ----------------------------------------------------------------

    def get_history(self, channel: str, last_n: Optional[int] = None) -> List[Dict[str, Any]]:
        """Возвращает последние N точек канала (или все)."""
        with self._lock:
            ch = self._channels.get(channel)
            if ch is None:
                return []
            items = list(ch)
        if last_n is not None:
            return items[-last_n:]
        return items

    def get_current(self, channel: str) -> Optional[float]:
        """Последнее значение канала."""
        with self._lock:
            ch = self._channels.get(channel)
            if ch is None or not ch:
                return None
            return ch[-1]["value"]

    def get_rate(self, channel: str) -> float:
        """Возвращает количество событий в канале за последние 60 секунд."""
        with self._lock:
            events = self._counters.get(channel, [])
            if not events:
                return 0.0
            cutoff = time.time() - self._counters_window_sec
            return float(sum(1 for t in events if t >= cutoff))

    def get_stats(self, channel: str) -> Dict[str, Any]:
        """Статистика канала: count, min, max, avg, last."""
        with self._lock:
            ch = self._channels.get(channel)
            if ch is None or not ch:
                return {"channel": channel, "count": 0}
            values = [e["value"] for e in ch]
        return {
            "channel": channel,
            "count": len(values),
            "min": self._channels_min.get(channel),
            "max": self._channels_max.get(channel),
            "avg": sum(values) / len(values) if values else 0,
            "last": values[-1] if values else None,
            "rate_per_min": self.get_rate(channel),
        }

    # ----------------------------------------------------------------
    # Снимок для дашборда
    # ----------------------------------------------------------------

    def snapshot(self, last_n: int = 100) -> Dict[str, Any]:
        """Возвращает снимок всех каналов для дашборда / графиков."""
        with self._lock:
            channel_names = sorted(self._channels.keys())
        return {
            "agent_name": self._agent_name,
            "channels": {
                ch: {
                    "stats": self.get_stats(ch),
                    "history": self.get_history(ch, last_n=last_n),
                }
                for ch in channel_names
            },
            "captured_at": time.time(),
        }

    def list_channels(self) -> List[str]:
        with self._lock:
            return sorted(self._channels.keys())

    # ----------------------------------------------------------------
    # Персистентность (NDJSON)
    # ----------------------------------------------------------------

    def export_json(self, path: Optional[str] = None) -> str:
        """Сохраняет снимок в JSON-файл. Возвращает путь."""
        snap = self.snapshot(last_n=self._maxlen)
        path = path or os.path.join(
            self._persist_dir or data_path("metrics"),
            f"{self._agent_name}_metrics_{int(time.time())}.json",
        )
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=2)
            return path
        except Exception as e:
            logger.warning(f"[metrics] ошибка экспорта: {e}")
            return ""

    def append_ndjson(self, path: str, channel: str, value: float,
                       cycle: Optional[int] = None) -> bool:
        """Дописывает одну точку в NDJSON-файл (быстрая персистентность)."""
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            entry = {
                "ts": time.time(),
                "channel": channel,
                "value": value,
            }
            if cycle is not None:
                entry["cycle"] = cycle
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return True
        except Exception as e:
            logger.debug(f"[metrics] ndjson append ошибка: {e}")
            return False

    # ----------------------------------------------------------------
    # Утилиты для тестов
    # ----------------------------------------------------------------

    def clear(self) -> None:
        """Очистить все каналы (только для тестов)."""
        with self._lock:
            for ch in list(self._channels.keys()):
                self._channels[ch].clear()
                self._channels_max[ch] = float("-inf")
                self._channels_min[ch] = float("inf")
                self._counters[ch] = []


__all__ = ["MetricsCollector", "DEFAULT_CHANNELS"]