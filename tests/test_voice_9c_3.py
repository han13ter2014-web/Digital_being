"""9C-3: frozen offline-аудио, restart/privacy и воспроизводимая приёмка.

WAV-файлы содержат синтетический PCM-сигнал, а не человеческую речь. Fake STT
сопоставляет их SHA-256 с заранее записанными результатами: так проверяется
транспорт и контракт, но не качество Whisper. Сеть и живой data/ не используются.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import socket
import sys
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_CLI_DATA_DIR = None
if __name__ == "__main__":
    _CLI_DATA_DIR = tempfile.mkdtemp(prefix="db_voice_9c_3_")
    os.environ["DIGITAL_BEING_DATA_DIR"] = _CLI_DATA_DIR

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.metrics.voice import ConsoleVoiceEngine, STTResult, VoiceEngine, VoiceRouter
from src.metrics.voice_input import VoiceInputService
from src.metrics.voice_output import VoiceOutputService
from src.ui.web_dashboard import VOICE_KEY, handle_voice_transcribe

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "voice_9c"
MANIFEST = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
SCENARIOS = MANIFEST["scenarios"]
PRIVATE_MARKER = "9C3_PRIVATE_AUDIO_TRANSCRIPT_NEVER_PERSIST"


def _fixture_path(scenario):
    return FIXTURE_DIR / scenario["audio"]


def _fixture_bytes(scenario):
    return _fixture_path(scenario).read_bytes()


class _FixtureSTT(VoiceEngine):
    """Детерминированный STT только для frozen synthetic fixtures."""

    name = "fixture-stt"
    capabilities = {"tts": False, "stt": True, "audible": False}

    def __init__(self):
        super().__init__(enabled=True)
        self.streams = []

    def _synthesize(self, text, *, voice=None, rate=None):
        return False

    def _listen(self, timeout=5.0):
        return None

    def transcribe_file(self, audio):
        self.streams.append(audio)
        digest = hashlib.sha256(audio.read()).hexdigest()
        scenario = next((item for item in SCENARIOS if item["sha256"] == digest), None)
        if scenario is None:
            return None
        expected = scenario["fake_stt"]
        return STTResult(
            text=expected["text"],
            confidence=expected["confidence"],
            confidence_basis="frozen_fixture_sha256",
            engine=self.name,
            model=MANIFEST["catalog_revision"],
        )


def _input_service():
    router = VoiceRouter(stt_enabled=True)
    engine = _FixtureSTT()
    router.add(engine)
    return VoiceInputService(router), engine


def _run_fixture(scenario):
    service, engine = _input_service()
    result = service.transcribe_bytes(_fixture_bytes(scenario), suffix=".wav")
    return result, engine


def _assert_fixture_result(scenario, result):
    expected = scenario["fake_stt"]
    assert result.text == expected["text"]
    assert result.confidence == pytest.approx(expected["confidence"])
    assert result.confidence_basis == "frozen_fixture_sha256"
    assert result.engine == "fixture-stt"
    assert result.model == MANIFEST["catalog_revision"]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["scenario_id"])
def test_frozen_audio_hashes_and_pcm_contract(scenario):
    raw = _fixture_bytes(scenario)
    assert hashlib.sha256(raw).hexdigest() == scenario["sha256"]
    with wave.open(io.BytesIO(raw), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 16_000
        assert audio.getnframes() == 1_600
    assert scenario["real_speech"] is False


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item["scenario_id"])
def test_offline_fixture_passes_memory_stream_and_expected_stt_contract(scenario):
    result, engine = _run_fixture(scenario)

    _assert_fixture_result(scenario, result)
    assert len(engine.streams) == 1
    assert isinstance(engine.streams[0], io.BytesIO)
    assert not hasattr(engine.streams[0], "name")


def test_fixture_results_are_repeatable_without_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("9C-3 acceptance must remain offline")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    for scenario in SCENARIOS:
        first, _ = _run_fixture(scenario)
        second, _ = _run_fixture(scenario)
        assert first == second


def test_transcription_creates_no_audio_files_or_temp_files(tmp_path, monkeypatch):
    service, _ = _input_service()

    def forbidden_temp_file(*args, **kwargs):
        raise AssertionError("raw audio must not be written to a temporary file")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", forbidden_temp_file)
    monkeypatch.setattr(tempfile, "mkstemp", forbidden_temp_file)
    before = set(tmp_path.iterdir())
    result = service.transcribe_bytes(_fixture_bytes(SCENARIOS[0]), suffix=".wav")

    _assert_fixture_result(SCENARIOS[0], result)
    assert set(tmp_path.iterdir()) == before


async def test_web_preview_does_not_return_audio_or_publish_to_core():
    service, _ = _input_service()
    raw = _fixture_bytes(SCENARIOS[0])

    async def read():
        return raw

    request = SimpleNamespace(
        app={VOICE_KEY: service},
        headers={"Content-Type": "audio/wav"},
        content_length=len(raw),
        read=read,
    )
    response = await handle_voice_transcribe(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["status"] == "preview"
    assert payload["text"] == SCENARIOS[0]["fake_stt"]["text"]
    assert set(payload) == {
        "status",
        "text",
        "confidence",
        "confidence_basis",
        "engine",
        "model",
    }
    assert hashlib.sha256(raw).hexdigest() not in response.text


def test_restart_disables_autoplay_and_drops_tts_history(monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_TEST_MODE", "1")
    monkeypatch.setenv("VOICE_CONSOLE_QUIET", "1")
    monkeypatch.setenv("DIGITAL_BEING_VOICE_TTS", "1")
    monkeypatch.delenv("DIGITAL_BEING_VOICE_STT", raising=False)
    agent = DigitalBeing(name="Voice9C3Restart")
    router = VoiceRouter(tts_enabled=True)
    audible = ConsoleVoiceEngine()
    audible.capabilities["audible"] = True
    router.add(audible)
    agent.voice_router = router
    output = VoiceOutputService(router)
    output.set_auto(True)
    output.speak(PRIVATE_MARKER, blocking=True)

    state = build_state_from_agent(agent)
    restored = DigitalBeing(name="Voice9C3Restart")
    apply_state_to_agent(restored, state)

    assert PRIVATE_MARKER not in json.dumps(state, ensure_ascii=False)
    assert restored.voice_router.auto_speak_enabled is False
    assert restored.voice_router.status()["auto_speak"] is False
    assert all(
        engine["spoken_count"] == 0
        for engine in restored.voice_router.status()["engines"]
    )
    assert restored.voice_router.speak_response(PRIVATE_MARKER, blocking=True) is False


def test_restart_requires_permissions_again_without_stt_or_tts(monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_TEST_MODE", "1")
    monkeypatch.setenv("VOICE_CONSOLE_QUIET", "1")
    monkeypatch.delenv("DIGITAL_BEING_VOICE_TTS", raising=False)
    monkeypatch.delenv("DIGITAL_BEING_VOICE_STT", raising=False)
    restored = DigitalBeing(name="Voice9C3NoPermissions")

    status = restored.voice_router.status()
    assert status["enabled"] is False
    assert status["available_stt"] == []
    assert status["audible_tts"] == []
    assert status["auto_speak"] is False


def _privacy_probe():
    service, engine = _input_service()
    with tempfile.TemporaryDirectory(prefix="db_voice_9c_3_privacy_") as directory:
        root = Path(directory)
        before = set(root.iterdir())
        result = service.transcribe_bytes(_fixture_bytes(SCENARIOS[0]), suffix=".wav")
        created = [str(path.relative_to(root)) for path in root.rglob("*")]
        assert before == set()
        assert created == []
    return {
        "memory_stream": isinstance(engine.streams[0], io.BytesIO),
        "files_created": created,
        "text_available_only_as_preview": result.text
        == SCENARIOS[0]["fake_stt"]["text"],
    }


def _restart_probe():
    with patch.dict(
        os.environ,
        {
            "DIGITAL_BEING_TEST_MODE": "1",
            "DIGITAL_BEING_VOICE_TTS": "1",
            "VOICE_CONSOLE_QUIET": "1",
        },
        clear=False,
    ):
        agent = DigitalBeing(name="Voice9C3Report")
        router = VoiceRouter(tts_enabled=True)
        audible = ConsoleVoiceEngine()
        audible.capabilities["audible"] = True
        router.add(audible)
        agent.voice_router = router
        output = VoiceOutputService(router)
        output.set_auto(True)
        output.speak(PRIVATE_MARKER, blocking=True)
        state = build_state_from_agent(agent)
        restored = DigitalBeing(name="Voice9C3Report")
        apply_state_to_agent(restored, state)
    return {
        "auto_speak_after_restart": restored.voice_router.auto_speak_enabled,
        "private_marker_in_checkpoint": PRIVATE_MARKER
        in json.dumps(state, ensure_ascii=False),
        "spoken_count_after_restart": sum(
            engine["spoken_count"]
            for engine in restored.voice_router.status()["engines"]
        ),
    }


def build_acceptance_report():
    first = [_run_fixture(scenario)[0] for scenario in SCENARIOS]
    second = [_run_fixture(scenario)[0] for scenario in SCENARIOS]
    mismatches = [
        scenario["scenario_id"]
        for scenario, left, right in zip(SCENARIOS, first, second, strict=True)
        if left != right
    ]
    for scenario, result in zip(SCENARIOS, first, strict=True):
        _assert_fixture_result(scenario, result)
    return {
        "schema_version": 1,
        "stage": "9C-3",
        "catalog_revision": MANIFEST["catalog_revision"],
        "fixture_kind": "synthetic_pcm_transport_only",
        "real_speech_recognition_verified": False,
        "real_audio_devices_verified": False,
        "fixture_count": len(SCENARIOS),
        "repetitions": 2,
        "repeatability_mismatches": mismatches,
        "privacy": _privacy_probe(),
        "restart": _restart_probe(),
        "network_calls": 0,
    }


def test_acceptance_report_has_zero_violations_and_honest_limits():
    report = build_acceptance_report()

    assert report["fixture_count"] == len(SCENARIOS) == 2
    assert report["repeatability_mismatches"] == []
    assert report["privacy"]["files_created"] == []
    assert report["restart"] == {
        "auto_speak_after_restart": False,
        "private_marker_in_checkpoint": False,
        "spoken_count_after_restart": 0,
    }
    assert report["network_calls"] == 0
    assert report["real_speech_recognition_verified"] is False
    assert report["real_audio_devices_verified"] is False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        with patch.object(
            socket, "create_connection", side_effect=AssertionError
        ), patch.object(socket.socket, "connect", side_effect=AssertionError):
            report = build_acceptance_report()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        if _CLI_DATA_DIR:
            import shutil

            from src.core.buffered_logger import flush_logs

            flush_logs()
            shutil.rmtree(_CLI_DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
