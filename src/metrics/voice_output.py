"""Явное управление звуковым выводом уже сформированных ответов."""

from __future__ import annotations

from typing import Any


class VoiceOutputService:
    """Отделить разрешение TTS, автоматический режим и ручной повтор.

    Сервис не создаёт текст и не меняет решения Core. Console fallback не
    считается звуковым выводом: для включения нужен фактически audible engine.
    """

    MAX_SPEECH_CHARS = 8_000

    def __init__(self, router: Any) -> None:
        self._router = router

    @property
    def enabled(self) -> bool:
        if self._router is None or not getattr(self._router, "tts_enabled", False):
            return False
        return bool(self._router.status().get("audible_tts"))

    @property
    def auto_enabled(self) -> bool:
        return bool(
            self._router is not None
            and getattr(self._router, "auto_speak_enabled", False)
        )

    def set_auto(self, enabled: bool) -> None:
        requested = bool(enabled)
        if requested and not self.enabled:
            raise PermissionError("звуковой TTS выключен или недоступен")
        self._router.set_auto_speak(requested)

    def speak(self, text: str, **kwargs: Any) -> bool:
        normalized = str(text).strip()
        if not normalized:
            raise ValueError("текст для озвучивания пуст")
        if len(normalized) > self.MAX_SPEECH_CHARS:
            raise ValueError(
                f"текст для озвучивания длиннее {self.MAX_SPEECH_CHARS} символов"
            )
        if not self.enabled:
            raise PermissionError("звуковой TTS выключен или недоступен")
        if not self._router.speak(normalized, **kwargs):
            raise RuntimeError("звуковой движок не принял ответ")
        return True


__all__ = ["VoiceOutputService"]
