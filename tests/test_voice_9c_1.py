"""9C-1: явный push-to-talk и редактируемый предпросмотр без автодоставки."""

import json
from types import SimpleNamespace

import pytest

from src.core.event_bus import Events
from src.metrics.voice import STTResult
from src.metrics.voice_input import PushToTalkSession, VoiceInputService
from src.ui.main_window import MainWindow
from src.ui.web_dashboard import (
    DASHBOARD_HTML,
    VOICE_KEY,
    handle_voice_status,
    handle_voice_transcribe,
)


class _FakeCapture:
    def __init__(self, audio=b"recorded-wav"):
        self.audio = audio
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def stop(self):
        return self.audio

    def cancel(self):
        self.cancelled = True


class _FakeVoiceInput:
    def __init__(self, *, enabled=True):
        self.enabled = enabled
        self.calls = []

    def transcribe_bytes(self, data, *, suffix=".wav"):
        self.calls.append((data, suffix))
        return STTResult(
            text="Голосовая реплика",
            confidence=0.37,
            confidence_basis="fake",
            engine="fake-stt",
        )


def test_push_to_talk_starts_stops_and_preserves_result():
    service = _FakeVoiceInput()
    capture = _FakeCapture()
    session = PushToTalkSession(service, capture_factory=lambda: capture)

    session.start()
    assert session.recording is True
    assert capture.started is True

    result = session.stop()

    assert session.recording is False
    assert service.calls == [(b"recorded-wav", ".wav")]
    assert result.text == "Голосовая реплика"
    assert result.confidence == pytest.approx(0.37)


def test_push_to_talk_cancel_discards_audio_without_transcription():
    service = _FakeVoiceInput()
    capture = _FakeCapture()
    session = PushToTalkSession(service, capture_factory=lambda: capture)

    session.start()
    session.cancel()

    assert session.recording is False
    assert capture.cancelled is True
    assert service.calls == []


def test_push_to_talk_requires_available_stt_before_capture():
    capture = _FakeCapture()
    session = PushToTalkSession(
        _FakeVoiceInput(enabled=False), capture_factory=lambda: capture
    )

    with pytest.raises(PermissionError):
        session.start()
    assert capture.started is False


def test_voice_input_service_rejects_empty_audio():
    service = VoiceInputService(SimpleNamespace(stt_enabled=True))

    with pytest.raises(ValueError, match="пуст"):
        service.transcribe_bytes(b"")


def test_voice_input_service_passes_memory_stream_without_audio_file():
    expected = STTResult(
        text="Поток", confidence=None, confidence_basis=None, engine="fake-stt"
    )

    class Router:
        stt_enabled = True

        def status(self):
            return {"available_stt": ["fake-stt"]}

        def transcribe_file(self, stream):
            assert stream.read() == b"wav-in-memory"
            return expected

    result = VoiceInputService(Router()).transcribe_bytes(b"wav-in-memory")

    assert result is expected


class _Var:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


class _Label:
    def __init__(self):
        self.value = ""

    def configure(self, *, text):
        self.value = text


class _RecordingBus:
    def __init__(self):
        self.published = []

    def subscribe(self, *args, **kwargs):
        return None

    def publish_sync(self, event, data=None, **kwargs):
        self.published.append((event, data))
        return True


def test_tk_voice_result_is_editable_preview_and_not_sent(monkeypatch):
    monkeypatch.setattr("src.ui.main_window.i18n.load_saved_language", lambda: "ru")
    bus = _RecordingBus()
    window = MainWindow(bus, "Alpha", voice_input=_FakeVoiceInput())
    window._input_var = _Var()
    window._voice_status_label = _Label()

    window._apply_voice_result(
        STTResult(
            text="Нужно проверить перед отправкой",
            confidence=0.41,
            confidence_basis="fake",
            engine="fake-stt",
        )
    )

    assert window._input_var.value == "Нужно проверить перед отправкой"
    assert "41%" in window._voice_status_label.value
    assert not [item for item in bus.published if item[0] == Events.USER_MESSAGE]


def test_tk_cancelled_session_result_does_not_replace_draft(monkeypatch):
    monkeypatch.setattr("src.ui.main_window.i18n.load_saved_language", lambda: "ru")
    window = MainWindow(_RecordingBus(), "Alpha", voice_input=_FakeVoiceInput())
    window._input_var = _Var()
    window._input_var.set("Черновик пользователя")
    session = SimpleNamespace(cancel=lambda: None)
    window._voice_session = session

    window._cancel_voice()
    window._handle_incoming(
        "__voice_result__",
        (
            session,
            STTResult(
                text="Поздний результат",
                confidence=None,
                confidence_basis=None,
                engine="fake-stt",
            ),
        ),
    )

    assert window._input_var.value == "Черновик пользователя"


def _voice_request(service, body=b"audio", content_type="audio/webm"):
    async def read():
        return body

    return SimpleNamespace(
        app={VOICE_KEY: service},
        headers={"Content-Type": content_type},
        read=read,
    )


async def test_web_voice_transcription_returns_preview_without_core_event():
    service = _FakeVoiceInput()

    response = await handle_voice_transcribe(_voice_request(service))
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["text"] == "Голосовая реплика"
    assert payload["confidence"] == pytest.approx(0.37)
    assert payload["confidence_basis"] == "fake"
    assert service.calls == [(b"audio", ".webm")]


async def test_web_voice_status_and_transcription_honour_permission():
    disabled = _FakeVoiceInput(enabled=False)

    status_response = await handle_voice_status(_voice_request(disabled))
    response = await handle_voice_transcribe(_voice_request(disabled))

    assert json.loads(status_response.text)["enabled"] is False
    assert response.status == 403
    assert disabled.calls == []


def test_web_has_push_to_talk_controls_and_editable_preview_target():
    assert 'id="voice-record"' in DASHBOARD_HTML
    assert 'id="voice-status"' in DASHBOARD_HTML
    assert "getUserMedia" in DASHBOARD_HTML
    assert "$('dialogue-input').value=result.text" in DASHBOARD_HTML
