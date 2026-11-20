"""Версионируемый тренд свободного места без интерполяции пропусков."""

from __future__ import annotations

from copy import deepcopy
from typing import Dict, Optional


_VERSION = 1
_WINDOW_LIMIT = 8
_MIN_DECLINE_CYCLES = 3
_MIN_STEP_DROP = 0.005


class HardwareStorageTrend:
    """Runtime-only окно; не хранит абсолютные байты, пути или исходы записи."""

    def __init__(self):
        self.window = []
        self.latest = self._empty()

    @staticmethod
    def _empty(reason="no_observation") -> Dict:
        return {
            "version": _VERSION,
            "window_size": 0,
            "decline_cycles": 0,
            "drop": None,
            "reason": reason,
        }

    def observe(self, cycle: int, free_ratio: Optional[float]) -> Dict:
        if free_ratio is None:
            self.window = []
            self.latest = self._empty("channel_unavailable")
            return deepcopy(self.latest)

        reason = "insufficient_sustained_decline"
        if self.window and cycle != self.window[-1][0] + 1:
            self.window = []
            reason = "noncontiguous_observation"
        self.window.append((cycle, free_ratio))
        self.window = self.window[-_WINDOW_LIMIT:]

        decline_cycles = 0
        for index in range(len(self.window) - 1, 0, -1):
            step_drop = self.window[index - 1][1] - self.window[index][1]
            if step_drop < _MIN_STEP_DROP - 1e-12:
                break
            decline_cycles += 1

        confirmed_drop = None
        if decline_cycles >= _MIN_DECLINE_CYCLES:
            start_index = len(self.window) - decline_cycles - 1
            confirmed_drop = self.window[start_index][1] - free_ratio
            reason = "sustained_decline"
        elif decline_cycles == 0 and reason != "noncontiguous_observation":
            reason = "no_sustained_decline"

        self.latest = {
            "version": _VERSION,
            "window_size": len(self.window),
            "decline_cycles": decline_cycles,
            "drop": confirmed_drop,
            "reason": reason,
        }
        return deepcopy(self.latest)

    def status(self) -> Dict:
        return deepcopy(self.latest)


__all__ = ["HardwareStorageTrend"]
