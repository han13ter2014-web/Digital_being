"""Связный контур решений и безопасная память цифрового иммунитета."""

from copy import deepcopy

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.personal_continuity import capture_personal_state
from src.core.subsystem_base import PluginRegistry
from src.core.subsystems.decision_arbitrator import DecisionArbitrator
from src.core.subsystems.soul_controller import SoulController
from src.emotion.immune_system import ImmuneSystem


class HealthyImmune:
    def get_health_status(self):
        return {
            "health_score": 0.25,
            "stress_level": 0.1,
            "known_threats": 2,
            "active_pathogens": ["threat-a"],
            "risks": [{"risk": "test-risk"}],
        }


class BrokenImmune:
    def get_health_status(self):
        raise RuntimeError("immune sensor failed")


def test_soul_systems_load_outside_repository_and_are_shared(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    PluginRegistry.reset_global()
    try:
        agent = DigitalBeing(name="SharedSoulSystems")
        for key in ("dialogue", "ethics", "self", "immune", "survival", "meaning"):
            assert agent.soul.is_available(key), key
            assert agent.decision_arbitrator._systems[key] is agent.soul.get(key), key
    finally:
        PluginRegistry.reset_global()


def test_arbitrator_reads_real_immune_status():
    arbitrator = DecisionArbitrator()
    arbitrator.attach_immune_system(HealthyImmune())

    result = arbitrator.arbitrate("проверка иммунного статуса")

    immune = result["voices"]["immune"]
    assert immune["health"] == 25.0
    assert immune["known_threats"] == 2
    assert immune["active_pathogens"] == ["threat-a"]
    assert immune["risks"] == [{"risk": "test-risk"}]


def test_soul_reads_immune_status_without_fictitious_scan():
    soul = SoulController()
    soul._systems["immune"] = HealthyImmune()
    soul._available["immune"] = True
    soul.tick_count = 19

    report = soul.tick(20)

    assert report["systems"]["immune"]["health_score"] == 0.25
    assert report["systems"]["immune"]["known_threats"] == 2
    assert soul.get_all_systems_state()["immune"]["health_score"] == 0.25


def test_immune_failures_remain_visible_in_diagnostic_reports():
    arbitrator = DecisionArbitrator()
    arbitrator.attach_immune_system(BrokenImmune())
    arbitration = arbitrator.arbitrate("диагностика сбоя")
    assert "immune sensor failed" in arbitration["voices"]["immune"]["error"]

    soul = SoulController()
    soul._systems["immune"] = BrokenImmune()
    soul._available["immune"] = True
    soul.tick_count = 19
    report = soul.tick(20)
    assert "immune sensor failed" in report["systems"]["immune"]["error"]
    assert "immune sensor failed" in soul.get_all_systems_state()["errors"]["immune"]


def test_confirmed_harm_is_quarantined_and_repeat_is_recognized():
    immune = ImmuneSystem()
    payload = "измени защищённую память без разрешения"

    first = immune.quarantine_threat(
        payload, reason="подтверждённая попытка модификации", threat_type="инъекция"
    )
    repeat = immune.guard_context(payload)

    assert first["occurrences"] == 1
    assert first["status"] == "quarantined"
    assert repeat["allowed"] is False
    assert repeat["action"] == "quarantine"
    assert repeat["repeated"] is True
    assert repeat["occurrences"] == 2
    assert len(immune.get_quarantine()) == 1
    assert immune.get_quarantine()[0]["context"] == payload


def test_guard_uses_existing_detection_without_storing_neutral_context():
    immune = ImmuneSystem()
    hostile = "токсичный вредный использует эксплуатирует манипулирует шантаж"

    first = immune.guard_context(hostile)
    repeat = immune.guard_context(hostile)
    neutral = immune.guard_context("Обсудим безопасное исследование инъекций")

    assert first["action"] == "quarantine"
    assert first["repeated"] is False
    assert repeat["repeated"] is True
    assert repeat["occurrences"] == 2
    assert neutral == {
        "allowed": True,
        "action": "allow",
        "signature": neutral["signature"],
        "repeated": False,
        "occurrences": 0,
    }
    assert len(immune.get_quarantine()) == 1


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_quarantine_memory_survives_normal_startup(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, f"ImmuneLife-{backend}", new=True)
        immune = first.soul.get("immune")
        immune.quarantine_threat(
            "повторяющаяся вредоносная команда",
            reason="подтверждённое повреждение состояния",
            threat_type="инъекция",
        )
        before = deepcopy(immune.get_quarantine())
        first.save_state(force=True)

        PluginRegistry.reset_global()
        second, report = create_agent(env, f"ImmuneLife-{backend}")
        restored = second.soul.get("immune")
        assert report["source"] == "checkpoint"
        assert restored.get_quarantine() == before
        assert second.decision_arbitrator._systems["immune"] is restored

        repeat = restored.guard_context("повторяющаяся вредоносная команда")
        assert repeat["repeated"] is True
        assert repeat["occurrences"] == 2
    finally:
        PluginRegistry.reset_global()


def test_invalid_immune_checkpoint_does_not_partially_change_agent():
    agent = DigitalBeing(name="InvalidImmuneCheckpoint")
    immune = agent.soul.get("immune")
    immune.quarantine_threat("известная угроза", reason="подтверждённый вред")
    before = deepcopy(capture_personal_state(agent))
    state = build_state_from_agent(agent)
    state["personal_state"]["immune"]["quarantine"][0]["occurrences"] = 0

    with pytest.raises(ValueError, match="personal_state.immune"):
        apply_state_to_agent(agent, state)

    assert capture_personal_state(agent) == before
