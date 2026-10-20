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

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional


logger = logging.getLogger(__name__)


# ============================================================
# Базовый класс VoiceEngine
# ============================================================

class VoiceEngine(ABC):
    """Базовый класс для голосовых движков."""

    name: str = "base"
    capabilities: Dict[str, bool] = {}

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._spoken_count = 0
        self._heard_count = 0
        self._error_count = 0
        self._lock = threading.Lock()

    # ----------------------------------------------------------------
    # TTS — text-to-speech
    # ----------------------------------------------------------------

    @abstractmethod
    def _synthesize(self, text: str, *, voice: Optional[str] = None,
                    rate: Optional[float] = None) -> bool:
        """Реализация синтеза речи. Возвращает True при успехе."""
        ...

    def speak(self, text: str, *, voice: Optional[str] = None,
              rate: Optional[float] = None, blocking: bool = False) -> bool:
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

    def _synthesize_safe(self, text: str, voice: Optional[str], rate: Optional[float]) -> None:
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
    def _listen(self, timeout: float = 5.0) -> Optional[str]:
        """Реализация распознавания речи. Возвращает распознанный текст."""
        ...

    def hear(self, timeout: float = 5.0, blocking: bool = True) -> Optional[str]:
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
    capabilities = {"tts": True, "stt": False}

    def __init__(self, *, enabled: bool = True, prefix: str = "🔊") -> None:
        super().__init__(enabled=enabled)
        self.prefix = prefix
        self._spoken_log: List[str] = []

    def _synthesize(self, text: str, *, voice: Optional[str] = None,
                    rate: Optional[float] = None) -> bool:
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

    def _listen(self, timeout: float = 5.0) -> Optional[str]:
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
    capabilities = {"tts": True, "stt": False}

    def __init__(self, *, enabled: bool = True, rate: int = 175,
                 voice_id: Optional[str] = None) -> None:
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

    def _synthesize(self, text: str, *, voice: Optional[str] = None,
                    rate: Optional[float] = None) -> bool:
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

    def _listen(self, timeout: float = 5.0) -> Optional[str]:
        return None

    def list_voices(self) -> List[Dict[str, str]]:
        """Список доступных голосов."""
        if not self._engine:
            return []
        try:
            voices = self._engine.getProperty("voices") or []
            return [{"id": v.id, "name": v.name, "lang": getattr(v, "languages", ["?"])[0]
                     if hasattr(v, "languages") else "?"} for v in voices]
        except Exception:
            return []


class WhisperSTTEngine(VoiceEngine):
    """STT-движок на базе faster-whisper (offline).

    Требует: pip install faster-whisper
    capabilities={stt: True, tts: False} — только распознавание.
    """

    name = "whisper"
    capabilities = {"tts": False, "stt": True}

    def __init__(self, *, enabled: bool = True,
                 model_size: str = "base") -> None:
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

    def _synthesize(self, text: str, *, voice: Optional[str] = None,
                    rate: Optional[float] = None) -> bool:
        return False  # Whisper — только STT

    def _listen(self, timeout: float = 5.0) -> Optional[str]:
        if not self._model:
            return None
        try:
            # Захватываем аудио с микрофона
            import sounddevice as sd  # type: ignore
            import numpy as np
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

            segments, info = self._model.transcribe(audio, beam_size=5)
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text or None
        except ImportError:
            logger.debug("[voice:whisper] sounddevice/numpy не установлены")
            return None
        except Exception as e:
            logger.warning(f"[voice:whisper] listen error: {e}")
            return None

    def transcribe_file(self, audio_path: str) -> Optional[str]:
        """Распознать аудиофайл (offline)."""
        if not self._model:
            return None
        try:
            segments, _ = self._model.transcribe(audio_path, beam_size=5)
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text or None
        except Exception as e:
            logger.warning(f"[voice:whisper] file error: {e}")
            return None


# ============================================================
# VoiceRouter — единая точка входа
# ============================================================

class VoiceRouter:
    """Маршрутизатор голосовых движков.

    - speak(text) → использует первый TTS-движок.
    - hear() → использует первый STT-движок.
    - status() → сводка по всем движкам.
    """

    def __init__(self) -> None:
        self._engines: List[VoiceEngine] = []
        self._lock = threading.RLock()

    def add(self, engine: VoiceEngine) -> None:
        with self._lock:
            self._engines.append(engine)

    def list_engines(self) -> List[str]:
        with self._lock:
            return [e.name for e in self._engines]

    def speak(self, text: str, **kwargs: Any) -> bool:
        """Озвучить текст — первый доступный TTS-движок."""
        with self._lock:
            engines = list(self._engines)
        for e in engines:
            if e.capabilities.get("tts"):
                return e.speak(text, **kwargs)
        return False

    def hear(self, timeout: float = 5.0, **kwargs: Any) -> Optional[str]:
        """Распознать речь — первый доступный STT-движок."""
        with self._lock:
            engines = list(self._engines)
        for e in engines:
            if e.capabilities.get("stt"):
                return e.hear(timeout=timeout, **kwargs)
        return None

    def status(self) -> Dict[str, Any]:
        with self._lock:
            engines = list(self._engines)
        return {
            "engines": [e.status() for e in engines],
            "available_tts": [e.name for e in engines if e.capabilities.get("tts")],
            "available_stt": [e.name for e in engines if e.capabilities.get("stt")],
        }


# ============================================================
# Удобная фабрика
# ============================================================

def create_default_router(*, allow_pyttsx3: bool = False,
                          allow_whisper: bool = False) -> VoiceRouter:
    """Создаёт VoiceRouter с доступными движками.

    По умолчанию — только ConsoleVoiceEngine (всегда работает).
    pyttsx3 по умолчанию ОТКЛЮЧЁН — его init() может зависнуть на Windows
    (SAPI5 инициализация через win32com). Включайте явно через:
        create_default_router(allow_pyttsx3=True)

    Опционально — whisper (если установлен и вы хотите STT).
    """
    router = VoiceRouter()
    router.add(ConsoleVoiceEngine())
    if allow_pyttsx3:
        try:
            router.add(PyttsxVoiceEngine())
        except Exception:
            pass
    if allow_whisper:
        router.add(WhisperSTTEngine())
    return router


__all__ = [
    "VoiceEngine",
    "ConsoleVoiceEngine",
    "PyttsxVoiceEngine",
    "WhisperSTTEngine",
    "VoiceRouter",
    "create_default_router",
]