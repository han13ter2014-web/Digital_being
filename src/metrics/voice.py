"""
Voice — TTS/STT базовая структура (Этап 3.2).

Философское решение:
Digital Being — текстовое существо, и голос для него — это «переводчик»
между двумя модальностями. Не все агенты должны иметь голос (это требует
внешних моделей), но интерфейс должен быть готов.

Архитектура:
- Абстрактный VoiceEngine — базовый контракт.
- ConsoleVoiceEngine — печатает текст (fallback для тестов).
- PiperVoiceEngine / WhisperVoiceEngine — заглушки для будущих движков.
- VoiceRouter — выбирает движок и маршрутизирует.
- STT (speech-to-text) и TTS (text-to-speech) разделены.
- Если движок недоступен (нет модели / нет сети) — graceful fallback.

Зависимости (опциональные):
- pyttsx3 — офлайн TTS (Windows SAPI5, macOS say, Linux espeak).
- piper-tts / onnxruntime — быстрый offline TTS.
- vosk — offline STT.
- faster-whisper — STT через Whisper.
- sounddevice — воспроизведение аудио.

Если ни одна зависимость не установлена — используется ConsoleVoiceEngine,
который просто печатает текст в консоль. Это позволяет писать тесты
и запускать агента в headless-режиме без голоса.
"""

import logging
import math
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class STTResult:
    """Результат STT с измеренной оценкой, а не предполагаемой уверенностью.

    ``confidence`` остаётся ``None``, если движок не предоставил оценку.
    ``confidence_basis`` называет исходную метрику: это не утверждение о
    калиброванной вероятности правильности всей фразы.
    """

    text: str
    confidence: Optional[float]
    confidence_basis: Optional[str]
    engine: str
    model: Optional[str] = None


def _result_from_segments(
    segments: Iterable[Any], *, engine: str, model: Optional[str]
) -> Optional[STTResult]:
    """Собрать текст и прозрачную оценку из фактических segment-метрик."""
    rows = list(segments)
    text = " ".join(str(getattr(seg, "text", "")).strip() for seg in rows).strip()
    if not text:
        return None

    weighted_logprobs = []
    for segment in rows:
        value = getattr(segment, "avg_logprob", None)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        start = getattr(segment, "start", None)
        end = getattr(segment, "end", None)
        duration = (
            float(end) - float(start)
            if isinstance(start, (int, float)) and isinstance(end, (int, float))
            else 1.0
        )
        weighted_logprobs.append((float(value), max(duration, 0.0) or 1.0))

    if not weighted_logprobs:
        return STTResult(
            text=text,
            confidence=None,
            confidence_basis=None,
            engine=engine,
            model=model,
        )

    total_weight = sum(weight for _, weight in weighted_logprobs)
    average_logprob = sum(
        value * weight for value, weight in weighted_logprobs
    ) / total_weight
    confidence = min(1.0, max(0.0, math.exp(average_logprob)))
    return STTResult(
        text=text,
        confidence=confidence,
        confidence_basis="faster_whisper_avg_logprob_exp",
        engine=engine,
        model=model,
    )


# ============================================================
# Базовый класс VoiceEngine
# ============================================================


class VoiceEngine(ABC):
    """Базовый класс для голосовых движков."""

    name: str = "base"
    capabilities: Dict[str, bool] = {}

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.capabilities = dict(type(self).capabilities)
        self._spoken_count = 0
        self._heard_count = 0
        self._error_count = 0
        # ConsoleVoiceEngine повторно входит в lock из _synthesize().
        self._lock = threading.RLock()

    # ----------------------------------------------------------------
    # TTS — text-to-speech
    # ----------------------------------------------------------------

    @abstractmethod
    def _synthesize(
        self, text: str, *, voice: Optional[str] = None, rate: Optional[float] = None
    ) -> bool:
        """Реализация синтеза речи. Возвращает True при успехе."""
        ...

    def speak(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        rate: Optional[float] = None,
        blocking: bool = False,
    ) -> bool:
        """Озвучить текст. Не блокирует по умолчанию."""
        if not self.enabled or not self.capabilities.get("tts", False):
            return False
        with self._lock:
            try:
                if blocking:
                    return self._synthesize(text, voice=voice, rate=rate)
                # Асинхронная отправка в поток
                t = threading.Thread(
                    target=self._synthesize_safe,
                    args=(text, voice, rate),
                    daemon=True,
                )
                t.start()
                return True
            except Exception as e:
                self._error_count += 1
                logger.warning(f"[voice:{self.name}] speak error: {e}")
                return False

    def _synthesize_safe(
        self, text: str, voice: Optional[str], rate: Optional[float]
    ) -> None:
        try:
            if self._synthesize(text, voice=voice, rate=rate):
                self._spoken_count += 1
        except Exception as e:
            self._error_count += 1
            logger.debug(f"[voice:{self.name}] synth error: {e}")

    # ----------------------------------------------------------------
    # STT — speech-to-text
    # ----------------------------------------------------------------

    @abstractmethod
    def _listen(self, timeout: float = 5.0) -> Optional[STTResult]:
        """Распознать речь и сохранить фактические метрики движка."""
        ...

    def hear(
        self, timeout: float = 5.0, blocking: bool = True
    ) -> Optional[STTResult]:
        """Распознать речь с микрофона. По умолчанию блокирующий."""
        if not self.enabled or not self.capabilities.get("stt", False):
            return None
        try:
            result = self._listen(timeout=timeout)
            if result:
                self._heard_count += 1
            return result
        except Exception as e:
            self._error_count += 1
            logger.warning(f"[voice:{self.name}] hear error: {e}")
            return None

    def transcribe_file(self, audio: Any) -> Optional[STTResult]:
        """Распознать файл или binary stream, если движок это поддерживает."""
        return None

    # ----------------------------------------------------------------
    # Статус
    # ----------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "capabilities": dict(self.capabilities),
            "spoken_count": self._spoken_count,
            "heard_count": self._heard_count,
            "error_count": self._error_count,
        }


# ============================================================
# ConsoleVoiceEngine — fallback (только логирует)
# ============================================================


class ConsoleVoiceEngine(VoiceEngine):
    """Движок, который печатает текст в консоль.

    Используется как fallback когда нет TTS-движка и для тестов.
    """

    name = "console"
    capabilities = {"tts": True, "stt": False, "audible": False}

    def __init__(self, *, enabled: bool = True, prefix: str = "🔊") -> None:
        super().__init__(enabled=enabled)
        self.prefix = prefix
        self._spoken_log: List[str] = []

    def _synthesize(
        self, text: str, *, voice: Optional[str] = None, rate: Optional[float] = None
    ) -> bool:
        with self._lock:
            self._spoken_log.append(text)
        # Печатаем если явно не под pytest (через env).
        # Под pytest capsys перехватывает print() — и Thread не наследует
        # capsys, что может зависнуть на Windows.
        if os.environ.get("VOICE_CONSOLE_QUIET", "0") != "1":
            try:
                print(f"{self.prefix} {text}", flush=True)
            except Exception:
                pass
        return True

    def _listen(self, timeout: float = 5.0) -> Optional[STTResult]:
        return None  # Console не умеет слушать

    def get_log(self) -> List[str]:
        with self._lock:
            return list(self._spoken_log)


# ============================================================
# Заглушки для будущих движков
# ============================================================


class PyttsxVoiceEngine(VoiceEngine):
    """Движок на базе pyttsx3 (офлайн TTS).

    Требует: pip install pyttsx3
    Если pyttsx3 не установлен — capabilities={tts: False} и движок молчит.
    """

    name = "pyttsx3"
    capabilities = {"tts": True, "stt": False, "audible": True}

    def __init__(
        self, *, enabled: bool = True, rate: int = 175, voice_id: Optional[str] = None
    ) -> None:
        super().__init__(enabled=enabled)
        self._engine = None
        self._rate = rate
        self._voice_id = voice_id
        try:
            import pyttsx3  # type: ignore

            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", rate)
            if voice_id:
                self._engine.setProperty("voice", voice_id)
        except ImportError:
            self.capabilities["tts"] = False
            logger.debug("[voice:pyttsx3] модуль не установлен")
        except Exception as e:
            self.capabilities["tts"] = False
            logger.debug(f"[voice:pyttsx3] init failed: {e}")

    def _synthesize(
        self, text: str, *, voice: Optional[str] = None, rate: Optional[float] = None
    ) -> bool:
        if not self._engine:
            return False
        try:
            if rate is not None:
                self._engine.setProperty("rate", int(rate))
            if voice:
                self._engine.setProperty("voice", voice)
            self._engine.say(text)
            self._engine.runAndWait()
            return True
        except Exception as e:
            logger.warning(f"[voice:pyttsx3] synth error: {e}")
            return False

    def _listen(self, timeout: float = 5.0) -> Optional[STTResult]:
        return None

    def list_voices(self) -> List[Dict[str, str]]:
        """Список доступных голосов."""
        if not self._engine:
            return []
        try:
            voices = self._engine.getProperty("voices") or []
            return [
                {
                    "id": v.id,
                    "name": v.name,
                    "lang": getattr(v, "languages", ["?"])[0]
                    if hasattr(v, "languages")
                    else "?",
                }
                for v in voices
            ]
        except Exception:
            return []


class WhisperSTTEngine(VoiceEngine):
    """STT-движок на базе faster-whisper (offline).

    Требует: pip install faster-whisper
    capabilities={stt: True, tts: False} — только распознавание.
    """

    name = "whisper"
    capabilities = {"tts": False, "stt": True, "audible": False}

    def __init__(self, *, enabled: bool = True, model_size: str = "base") -> None:
        super().__init__(enabled=enabled)
        self._model = None
        self._model_size = model_size
        try:
            from faster_whisper import WhisperModel  # type: ignore

            self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
            logger.info(f"[voice:whisper] модель {model_size} загружена")
        except ImportError:
            self.capabilities["stt"] = False
            logger.debug("[voice:whisper] модуль не установлен")
        except Exception as e:
            self.capabilities["stt"] = False
            logger.warning(f"[voice:whisper] init failed: {e}")

    def _synthesize(
        self, text: str, *, voice: Optional[str] = None, rate: Optional[float] = None
    ) -> bool:
        return False  # Whisper — только STT

    def _listen(self, timeout: float = 5.0) -> Optional[STTResult]:
        if not self._model:
            return None
        try:
            # 9C-1 заменит фиксированное окно на явный push-to-talk адаптер.
            import sounddevice as sd  # type: ignore
            import numpy as np  # noqa: F401 — проверка наличия numpy для распознавания

            duration = min(timeout, 10.0)
            sample_rate = 16000
            audio = sd.rec(
                int(duration * sample_rate),
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
            )
            sd.wait()
            audio = audio.flatten()

            segments, _ = self._model.transcribe(audio, beam_size=5)
            return _result_from_segments(
                segments, engine=self.name, model=self._model_size
            )
        except ImportError:
            logger.debug("[voice:whisper] sounddevice/numpy не установлены")
            return None
        except Exception as e:
            logger.warning(f"[voice:whisper] listen error: {e}")
            return None

    def transcribe_file(self, audio_path: Any) -> Optional[STTResult]:
        """Распознать offline путь или binary stream с confidence."""
        if not self._model:
            return None
        try:
            segments, _ = self._model.transcribe(audio_path, beam_size=5)
            return _result_from_segments(
                segments, engine=self.name, model=self._model_size
            )
        except Exception as e:
            logger.warning(f"[voice:whisper] file error: {e}")
            return None


# ============================================================
# VoiceRouter — единая точка входа
# ============================================================


class VoiceRouter:
    """Маршрутизатор с независимыми разрешениями TTS и STT."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        tts_enabled: Optional[bool] = None,
        stt_enabled: Optional[bool] = None,
    ) -> None:
        self._engines: List[VoiceEngine] = []
        self._lock = threading.RLock()
        self.tts_enabled = bool(enabled if tts_enabled is None else tts_enabled)
        self.stt_enabled = bool(enabled if stt_enabled is None else stt_enabled)
        # Разрешение TTS не означает согласие на автоматическое озвучивание.
        self.auto_speak_enabled = False

    @property
    def enabled(self) -> bool:
        """Голосовой контур активен, если разрешён хотя бы один канал."""
        return self.tts_enabled or self.stt_enabled

    @enabled.setter
    def enabled(self, enabled: bool) -> None:
        """Сохранить совместимость прежнего публичного атрибута."""
        self.set_enabled(enabled)

    def _apply_permissions(self, engine: VoiceEngine) -> None:
        engine.enabled = bool(
            (self.tts_enabled and engine.capabilities.get("tts"))
            or (self.stt_enabled and engine.capabilities.get("stt"))
        )

    def set_enabled(self, enabled: bool) -> None:
        """Совместимый общий переключатель: меняет оба канала сразу."""
        with self._lock:
            self.tts_enabled = bool(enabled)
            self.stt_enabled = bool(enabled)
            for engine in self._engines:
                self._apply_permissions(engine)

    def set_tts_enabled(self, enabled: bool) -> None:
        with self._lock:
            self.tts_enabled = bool(enabled)
            for engine in self._engines:
                self._apply_permissions(engine)

    def set_stt_enabled(self, enabled: bool) -> None:
        with self._lock:
            self.stt_enabled = bool(enabled)
            for engine in self._engines:
                self._apply_permissions(engine)

    def add(self, engine: VoiceEngine) -> None:
        with self._lock:
            self._apply_permissions(engine)
            self._engines.append(engine)

    def list_engines(self) -> List[str]:
        with self._lock:
            return [e.name for e in self._engines]

    def set_auto_speak(self, enabled: bool) -> None:
        """Включить автоматический вывод только по явной команде владельца."""
        with self._lock:
            self.auto_speak_enabled = bool(enabled)

    def speak(self, text: str, **kwargs: Any) -> bool:
        if not self.tts_enabled:
            return False
        with self._lock:
            engines = list(self._engines)
        for engine in engines:
            if engine.enabled and engine.capabilities.get("tts"):
                return engine.speak(text, **kwargs)
        return False

    def speak_response(self, text: str, **kwargs: Any) -> bool:
        """Озвучить проверенный ответ только в включённом audible auto-режиме."""
        if not self.auto_speak_enabled or not self.status().get("audible_tts"):
            return False
        return self.speak(text, **kwargs)

    def hear(self, timeout: float = 5.0, **kwargs: Any) -> Optional[STTResult]:
        if not self.stt_enabled:
            return None
        with self._lock:
            engines = list(self._engines)
        for engine in engines:
            if engine.enabled and engine.capabilities.get("stt"):
                return engine.hear(timeout=timeout, **kwargs)
        return None

    def transcribe_file(self, audio: Any) -> Optional[STTResult]:
        """Распознать записанный ввод без обращения к микрофону."""
        if not self.stt_enabled:
            return None
        with self._lock:
            engines = list(self._engines)
        for engine in engines:
            if engine.enabled and engine.capabilities.get("stt"):
                return engine.transcribe_file(audio)
        return None

    def status(self) -> Dict[str, Any]:
        with self._lock:
            engines = list(self._engines)
            tts_enabled = self.tts_enabled
            stt_enabled = self.stt_enabled
        available_tts = [
            e.name
            for e in engines
            if tts_enabled and e.enabled and e.capabilities.get("tts")
        ]
        return {
            "enabled": tts_enabled or stt_enabled,
            "tts_enabled": tts_enabled,
            "stt_enabled": stt_enabled,
            "auto_speak": self.auto_speak_enabled,
            "engines": [e.status() for e in engines],
            "available_tts": available_tts,
            "available_stt": [
                e.name
                for e in engines
                if stt_enabled and e.enabled and e.capabilities.get("stt")
            ],
            "audible_tts": [
                e.name
                for e in engines
                if e.name in available_tts and e.capabilities.get("audible", False)
            ],
            "text_fallback": [
                e.name
                for e in engines
                if e.name in available_tts and not e.capabilities.get("audible", False)
            ],
        }


# ============================================================
# Удобная фабрика
# ============================================================


def create_default_router(
    *,
    allow_pyttsx3: bool = False,
    allow_whisper: bool = False,
    enabled: bool = False,
    tts_enabled: Optional[bool] = None,
    stt_enabled: Optional[bool] = None,
) -> VoiceRouter:
    """Создать только явно разрешённые движки и console-fallback."""
    router = VoiceRouter(
        enabled=enabled, tts_enabled=tts_enabled, stt_enabled=stt_enabled
    )
    if router.tts_enabled and allow_pyttsx3:
        try:
            router.add(PyttsxVoiceEngine(enabled=True))
        except Exception:
            pass
    if router.stt_enabled and allow_whisper:
        router.add(WhisperSTTEngine(enabled=True))
    router.add(ConsoleVoiceEngine(enabled=router.tts_enabled))
    return router


__all__ = [
    "STTResult",
    "VoiceEngine",
    "ConsoleVoiceEngine",
    "PyttsxVoiceEngine",
    "WhisperSTTEngine",
    "VoiceRouter",
    "create_default_router",
]
