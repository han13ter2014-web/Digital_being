"""9C-2: явное управление звуковым выводом проверенных ответов."""

import json
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.event_bus import EventBus
from src.metrics.voice import ConsoleVoiceEngine, VoiceRouter
from src.metrics.voice_output import VoiceOutputService
from src.ui.main_window import MainWindow
from src.ui.web_dashboard import (
    DASHBOARD_HTML,
    STATE_KEY,
    VOICE_OUTPUT_KEY,
    SharedState,
    handle_voice_auto,
    handle_voice_speak,
    handle_voice_status,
)


def _audible_console(router: VoiceRouter) -> ConsoleVoiceEngine:
    engine = ConsoleVoiceEngine()
    engine.capabilities["audible"] = True
    router.add(engine)
    return engine


def test_autoplay_is_off_by_default_and_manual_replay_is_independent():
    router = VoiceRouter(tts_enabled=True)
    engine = _audible_console(router)
    output = VoiceOutputService(router)

    assert router.status()["auto_speak"] is False
    assert router.speak_response("Не озвучивать автоматически", blocking=True) is False
    assert engine.get_log() == []

    assert output.speak("Повторить по явной команде", blocking=True) is True
    assert engine.get_log() == ["Повторить по явной команде"]

    output.set_auto(True)
    assert router.speak_response("Проверенный ответ", blocking=True) is True
    assert engine.get_log()[-1] == "Проверенный ответ"


def test_console_fallback_is_not_accepted_as_audible_output():
    router = VoiceRouter(tts_enabled=True)
    engine = ConsoleVoiceEngine()
    router.add(engine)
    output = VoiceOutputService(router)

    assert output.enabled is False
    with pytest.raises(PermissionError, match="звуковой TTS"):
        output.speak("Только текст", blocking=True)
    with pytest.raises(PermissionError, match="звуковой TTS"):
        output.set_auto(True)
    assert router.speak_response("Только текст", blocking=True) is False
    assert engine.get_log() == []


def test_output_rejects_empty_and_overlong_text():
    router = VoiceRouter(tts_enabled=True)
    _audible_console(router)
    output = VoiceOutputService(router)

    with pytest.raises(ValueError, match="пуст"):
        output.speak("  ")
    with pytest.raises(ValueError, match="8000"):
        output.speak("я" * 8001)


async def test_core_autoplay_uses_checked_response_gate(monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_TEST_MODE", "1")
    agent = DigitalBeing(name="Voice9C2Core")
    runner = AgentRunner(agent, EventBus())
    router = VoiceRouter(tts_enabled=True)
    engine = _audible_console(router)
    agent.voice_router = router

    await runner._reply_to_user(
        "Первый проверенный ответ.", context="social_reply", source="test"
    )
    assert engine.get_log() == []

    router.set_auto_speak(True)
    await runner._reply_to_user(
        "Второй проверенный ответ.", context="social_reply", source="test"
    )
    assert engine.get_log() == ["Второй проверенный ответ."]


class _FakeOutput:
    def __init__(self):
        self.enabled = True
        self.auto_enabled = False
        self.calls = []

    def speak(self, text, **kwargs):
        self.calls.append(text)
        return True

    def set_auto(self, enabled):
        self.auto_enabled = bool(enabled)


class _RecordingBus:
    def subscribe(self, *args, **kwargs):
        return None


def test_tk_replays_only_published_agent_response(monkeypatch):
    monkeypatch.setattr("src.ui.main_window.i18n.load_saved_language", lambda: "ru")
    output = _FakeOutput()
    window = MainWindow(_RecordingBus(), "Alpha", voice_output=output)

    window._handle_incoming("agent_response", "Опубликованный ответ")
    window._handle_incoming("agent", "Автономная мысль не заменяет ответ")
    window._speak_latest_response()

    assert output.calls == ["Опубликованный ответ"]


def _json_request(state, output, payload):
    raw = json.dumps(payload).encode("utf-8")

    async def read(_size=-1):
        return raw

    return SimpleNamespace(
        app={STATE_KEY: state, VOICE_OUTPUT_KEY: output},
        content_type="application/json",
        content_length=len(raw),
        content=SimpleNamespace(read=read),
        headers={},
        url=SimpleNamespace(host="127.0.0.1"),
        scheme="http",
        host="127.0.0.1",
    )


def _state_with_responses():
    state = SharedState()
    state.push_event("user_message", {"text": "Реплика пользователя"})
    state.push_event("agent_message", {"content": "Ответ сущности"})
    state.push_event("agent_thought", {"text": "Внутренняя мысль"})
    return state


async def test_web_speak_uses_journal_sequence_not_client_text():
    state = _state_with_responses()
    output = _FakeOutput()

    response = await handle_voice_speak(
        _json_request(state, output, {"sequence": 2, "text": "Подменённый текст"})
    )
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["status"] == "started"
    assert output.calls == ["Ответ сущности"]


@pytest.mark.parametrize("sequence", [1, 3, 999])
async def test_web_speak_rejects_user_thought_and_unknown_events(sequence):
    state = _state_with_responses()
    output = _FakeOutput()

    response = await handle_voice_speak(
        _json_request(state, output, {"sequence": sequence})
    )

    assert response.status == 404
    assert output.calls == []


async def test_web_auto_toggle_and_status_reflect_actual_output():
    state = _state_with_responses()
    output = _FakeOutput()

    response = await handle_voice_auto(_json_request(state, output, {"enabled": True}))
    status = await handle_voice_status(_json_request(state, output, {}))
    payload = json.loads(status.text)

    assert response.status == 200
    assert output.auto_enabled is True
    assert payload["tts_enabled"] is True
    assert payload["auto_speak"] is True
    assert payload["latest_response_sequence"] == 2


async def test_web_auto_toggle_rejects_non_boolean():
    state = _state_with_responses()
    output = _FakeOutput()

    response = await handle_voice_auto(_json_request(state, output, {"enabled": "yes"}))

    assert response.status == 400
    assert output.auto_enabled is False


def test_web_has_manual_replay_and_autoplay_controls():
    assert 'id="voice-replay"' in DASHBOARD_HTML
    assert 'id="voice-auto"' in DASHBOARD_HTML
    assert "/api/voice/speak" in DASHBOARD_HTML
    assert "/api/voice/auto" in DASHBOARD_HTML


async def test_core_autoplay_requires_actual_message_delivery(monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_TEST_MODE", "1")
    agent = DigitalBeing(name="Voice9C2Undelivered")
    runner = AgentRunner(agent, EventBus())
    router = VoiceRouter(tts_enabled=True)
    engine = _audible_console(router)
    router.set_auto_speak(True)
    agent.voice_router = router
    agent.user_interaction = None

    result = await runner._reply_to_user(
        "Недоставленный ответ.", context="social_reply", source="test"
    )

    assert result is None
    assert engine.get_log() == []
