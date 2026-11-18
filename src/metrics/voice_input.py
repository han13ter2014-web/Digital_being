"""Локальный push-to-talk ввод без автоматической доставки текста в Core."""

from __future__ import annotations

import io
import threading
import wave
from typing import Any, Callable, Optional

from src.metrics.voice import STTResult


class VoiceInputService:
    """Передать аудио разрешённому STT, не сохраняя запись на диск."""

    MAX_AUDIO_BYTES = 10 * 1024 * 1024
    SUPPORTED_SUFFIXES = frozenset({".wav", ".webm", ".ogg", ".flac", ".mp3", ".m4a"})

    def __init__(self, router: Any, *, max_audio_bytes: int = MAX_AUDIO_BYTES) -> None:
        self._router = router
        self._max_audio_bytes = int(max_audio_bytes)

    @property
    def enabled(self) -> bool:
        if self._router is None or not getattr(self._router, "stt_enabled", False):
            return False
        return bool(self._router.status().get("available_stt"))

    def transcribe_bytes(self, data: bytes, *, suffix: str = ".wav") -> STTResult:
        if not isinstance(data, bytes) or not data:
            raise ValueError("аудиозапись пуста")
        if len(data) > self._max_audio_bytes:
            raise ValueError("аудиозапись превышает допустимый размер")
        normalized_suffix = str(suffix).lower()
        if normalized_suffix not in self.SUPPORTED_SUFFIXES:
            raise ValueError("неподдерживаемый формат аудио")
        if not self.enabled:
            raise PermissionError("STT выключен или локальный движок недоступен")

        result = self._router.transcribe_file(io.BytesIO(data))
        if result is None:
            raise ValueError("речь не распознана")
        return result


class SounddeviceCapture:
    """Запись только между start/stop; зависимости загружаются при start."""

    def __init__(self, *, sample_rate: int = 16_000) -> None:
        self._sample_rate = int(sample_rate)
        self._stream = None
        self._chunks = []
        self._lock = threading.Lock()

    def start(self) -> None:
        import numpy as np  # type: ignore
        import sounddevice as sd  # type: ignore

        self._np = np
        with self._lock:
            self._chunks = []

        def append_audio(indata, frames, time_info, status) -> None:
            del frames, time_info, status
            with self._lock:
                self._chunks.append(indata.copy().tobytes())

        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            callback=append_audio,
        )
        self._stream.start()

    def stop(self) -> bytes:
        self._close_stream()
        with self._lock:
            raw = b"".join(self._chunks)
            self._chunks = []
        if not raw:
            return b""
        samples = self._np.frombuffer(raw, dtype="float32")
        pcm = (self._np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(self._sample_rate)
            output.writeframes(pcm.tobytes())
        return buffer.getvalue()

    def cancel(self) -> None:
        self._close_stream()
        with self._lock:
            self._chunks = []

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()


class PushToTalkSession:
    """Одна явная запись: stop распознаёт её, cancel безвозвратно отбрасывает."""

    def __init__(
        self,
        voice_input: Any,
        *,
        capture_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._voice_input = voice_input
        self._capture_factory = capture_factory or SounddeviceCapture
        self._capture = None
        self._state = "idle"

    @property
    def recording(self) -> bool:
        return self._state == "recording"

    def start(self) -> None:
        if self._state != "idle":
            raise RuntimeError("запись уже начата или завершена")
        if not self._voice_input.enabled:
            raise PermissionError("STT выключен или локальный движок недоступен")
        capture = self._capture_factory()
        capture.start()
        self._capture = capture
        self._state = "recording"

    def stop(self) -> STTResult:
        if not self.recording or self._capture is None:
            raise RuntimeError("запись не начата")
        self._state = "processing"
        try:
            audio = self._capture.stop()
            result = self._voice_input.transcribe_bytes(audio, suffix=".wav")
        except Exception:
            self._state = "error"
            raise
        self._state = "done"
        return result

    def cancel(self) -> None:
        capture, self._capture = self._capture, None
        if capture is not None:
            capture.cancel()
        self._state = "cancelled"


__all__ = ["VoiceInputService", "SounddeviceCapture", "PushToTalkSession"]
