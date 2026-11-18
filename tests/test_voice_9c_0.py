"""9C-0: голос выключен по умолчанию, разрешения и STT-результат честны."""

import math
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.metrics.voice import (
    ConsoleVoiceEngine,
    STTResult,
    VoiceEngine,
    VoiceRouter,
    WhisperSTTEngine,
)


def _clear_voice_permissions(monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_TEST_MODE", "1")
    monkeypatch.delenv("DIGITAL_BEING_VOICE_TTS", raising=False)
    monkeypatch.delenv("DIGITAL_BEING_VOICE_STT", raising=False)


def test_auxiliary_voice_is_disabled_by_default(monkeypatch):
    _clear_voice_permissions(monkeypatch)

    agent = DigitalBeing(name="Voice9C0Default")
    status = agent.voice_router.status()

    assert status["enabled"] is False
    assert status["tts_enabled"] is False
    assert status["stt_enabled"] is False
    assert status["available_tts"] == []
    assert status["available_stt"] == []
    assert agent.voice_router.speak("не озвучивать", blocking=True) is False
    assert agent.voice_router.hear() is None


def test_auxiliary_tts_permission_does_not_enable_stt(monkeypatch):
    _clear_voice_permissions(monkeypatch)
    monkeypatch.setenv("DIGITAL_BEING_VOICE_TTS", "1")

    agent = DigitalBeing(name="Voice9C0TTS")
    status = agent.voice_router.status()

    assert status["enabled"] is True
    assert status["tts_enabled"] is True
    assert status["stt_enabled"] is False
    assert status["available_tts"] == ["console"]
    assert status["available_stt"] == []
    assert agent.voice_router.speak("текстовый fallback", blocking=True) is True
    assert agent.voice_router.hear() is None


def test_auxiliary_stt_permission_does_not_enable_tts(monkeypatch):
    _clear_voice_permissions(monkeypatch)
    monkeypatch.setenv("DIGITAL_BEING_VOICE_STT", "1")

    agent = DigitalBeing(name="Voice9C0STT")
    status = agent.voice_router.status()

    assert status["enabled"] is True
    assert status["tts_enabled"] is False
    assert status["stt_enabled"] is True
    assert status["available_tts"] == []
    assert agent.voice_router.speak("не озвучивать", blocking=True) is False


def test_console_fallback_is_not_reported_as_audible_tts():
    router = VoiceRouter(enabled=True)
    router.add(ConsoleVoiceEngine())

    status = router.status()

    assert status["available_tts"] == ["console"]
    assert status["audible_tts"] == []
    assert status["text_fallback"] == ["console"]


def test_legacy_enabled_assignment_still_controls_both_channels():
    router = VoiceRouter()

    router.enabled = True
    assert router.tts_enabled is True
    assert router.stt_enabled is True

    router.enabled = False
    assert router.tts_enabled is False
    assert router.stt_enabled is False


class _FakeSTTEngine(VoiceEngine):
    name = "fake-stt"
    capabilities = {"tts": False, "stt": True, "audible": False}

    def _synthesize(self, text, *, voice=None, rate=None):
        return False

    def _listen(self, timeout=5.0):
        return STTResult(
            text="распознанная реплика",
            confidence=0.42,
            confidence_basis="fake",
            engine=self.name,
        )


def test_router_separate_channels_preserve_stt_result():
    router = VoiceRouter(tts_enabled=False, stt_enabled=True)
    router.add(_FakeSTTEngine())

    result = router.hear()

    assert isinstance(result, STTResult)
    assert result.text == "распознанная реплика"
    assert result.confidence == pytest.approx(0.42)
    assert router.speak("не озвучивать", blocking=True) is False


class _FakeWhisperModel:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, _audio_path, beam_size=5):
        assert beam_size == 5
        return iter(self._segments), SimpleNamespace()


def _whisper_with_model(model):
    engine = object.__new__(WhisperSTTEngine)
    VoiceEngine.__init__(engine)
    engine._model = model
    engine._model_size = "test"
    return engine


def test_whisper_file_result_contains_derived_confidence_and_basis():
    engine = _whisper_with_model(
        _FakeWhisperModel(
            [SimpleNamespace(text=" Привет. ", avg_logprob=-0.5, start=0.0, end=1.0)]
        )
    )

    result = engine.transcribe_file("fixture.wav")

    assert isinstance(result, STTResult)
    assert result.text == "Привет."
    assert result.confidence == pytest.approx(math.exp(-0.5))
    assert result.confidence_basis == "faster_whisper_avg_logprob_exp"
    assert result.engine == "whisper"
    assert result.model == "test"


def test_whisper_missing_confidence_remains_unknown():
    engine = _whisper_with_model(
        _FakeWhisperModel(
            [SimpleNamespace(text="Текст", avg_logprob=None, start=0.0, end=1.0)]
        )
    )

    result = engine.transcribe_file("fixture.wav")

    assert isinstance(result, STTResult)
    assert result.text == "Текст"
    assert result.confidence is None
    assert result.confidence_basis is None
