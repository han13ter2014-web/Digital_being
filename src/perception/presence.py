"""Присутствие: орган, который замечает, что человек рядом.

Это восприятие, а не слежка. Орган отвечает на один вопрос: «человек
рядом и чем примерно занят?» — классом активности и фактом бездействия.
Никаких скриншотов, никаких заголовков окон и документов, ничего не
пишется на диск.

Граница честности жёсткая: пока человек сам не включил переключатель
«Присутствие» (access_control, ключ ``presence``), орган не делает ни
одного вызова к ОС — ``snapshot()`` честно отвечает «неизвестно».
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

STATE_UNKNOWN = "unknown"   # выключено или ОС не ответила
STATE_ACTIVE = "active"     # человек рядом и работает
STATE_QUIET = "quiet"       # рядом, но тихо (читает, думает, смотрит)
STATE_AWAY = "away"         # отошёл

NEAR_STATES = frozenset({STATE_ACTIVE, STATE_QUIET})


class PresenceSense:
    """Класс активности человека + секунды бездействия.

    Параметры инъектируются для тестов: ``app_reader()`` возвращает имя
    активного приложения (уже без заголовка документа) или None,
    ``idle_reader()`` — секунды бездействия или None. По умолчанию оба
    читают Windows через ctypes; на других платформах орган честно
    молчит (``unknown``).
    """

    AWAY_AFTER_SEC = 300.0     # 5 минут без ввода — отошёл
    ACTIVE_WITHIN_SEC = 60.0   # ввод в последнюю минуту — активен
    CACHE_SEC = 30.0           # пересчёт не чаще, чем раз в 30 с

    def __init__(self, enabled: bool = False, app_reader=None, idle_reader=None,
                 clock=time.monotonic) -> None:
        self.enabled = bool(enabled)
        self._app_reader = app_reader or self._windows_active_app
        self._idle_reader = idle_reader or self._windows_idle_seconds
        self._clock = clock
        self._cached: Optional[Dict[str, Any]] = None
        self._cached_at: Optional[float] = None

    # ---------------- публичное ----------------

    def snapshot(self, force: bool = False) -> Dict[str, Any]:
        """Снимок присутствия. Выключенный орган не трогает ОС вообще."""
        if not self.enabled:
            return {"state": STATE_UNKNOWN, "active_app": None,
                    "idle_seconds": None}
        now = self._clock()
        if (
            not force
            and self._cached is not None
            and self._cached_at is not None
            and now - self._cached_at < self.CACHE_SEC
        ):
            return dict(self._cached)
        app = self._app_reader()
        idle = self._idle_reader()
        snapshot = {
            "state": self._classify(app, idle),
            "active_app": app if app and app != "Unknown" else None,
            "idle_seconds": idle,
        }
        self._cached = dict(snapshot)
        self._cached_at = now
        return snapshot

    @staticmethod
    def is_near(snapshot: Dict[str, Any]) -> bool:
        """Человек рядом (активен или тих). «Отошёл» и «неизвестно» — нет."""
        return snapshot.get("state") in NEAR_STATES

    # ---------------- классификация ----------------

    def _classify(self, app: Optional[str], idle: Optional[float]) -> str:
        if idle is None:
            # ОС не сказала про бездействие — честно не знаем.
            return STATE_UNKNOWN
        if idle >= self.AWAY_AFTER_SEC:
            return STATE_AWAY
        if idle < self.ACTIVE_WITHIN_SEC:
            return STATE_ACTIVE
        return STATE_QUIET

    # ---------------- чтение ОС (Windows) ----------------

    @staticmethod
    def _windows_active_app() -> Optional[str]:
        """Имя активного приложения без заголовка документа.

        Как и ``ContextAwareness``: заголовок окна режется до части до
        разделителя — документ наружу не выходит.
        """
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return None
            buff = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value
            for separator in (" — ", " - "):
                if separator in title:
                    return title.split(separator)[0].strip() or None
            return title.strip() or None
        except Exception:
            return None

    @staticmethod
    def _windows_idle_seconds() -> Optional[float]:
        """Секунды с последнего ввода (GetLastInputInfo). None при ошибке."""
        try:
            import ctypes

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            info = LASTINPUTINFO()
            info.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
                return None
            # dwTime 32-битный, как и GetTickCount — переполнение
            # безопасно при беззнаковом вычитании.
            elapsed = (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
            return max(0.0, elapsed / 1000.0)
        except Exception:
            return None


__all__ = [
    "NEAR_STATES",
    "PresenceSense",
    "STATE_ACTIVE",
    "STATE_AWAY",
    "STATE_QUIET",
    "STATE_UNKNOWN",
]
