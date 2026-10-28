"""Мягкая история способа меняет порядок выбора, но не превращается в запрет."""

from unittest.mock import patch

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.cognition.method_preferences import observe, strength, apply
from src.core.subsystem_base import PluginRegistry


def equal_candidates():
    return [{"action": "play", "source": "activity", "strength": 0.8, "params": {}},
            {"action": "create_draft", "source": "activity", "strength": 0.8, "params": {}}]


def test_repeated_failure_changes_real_arbitration_order_not_availability():
    from src.core.agent import DigitalBeing

    agent = DigitalBeing(name="PreferenceChoice")
    verdict = {"score": 0.5, "verdict": "proceed", "confidence": 0.5, "reasoning": "equal", "voices": {}}
    with patch.object(agent.decision_arbitrator, "arbitrate", return_value=verdict):
        fresh = agent.decision_arbitrator.choose_action(equal_candidates(), {})
        for _ in range(5):
            observe(agent, "play", outcome="error")
        softened = agent.decision_arbitrator.choose_action(apply(agent, equal_candidates()), {})
    assert fresh["action"] in {"play", "create_draft"}
    assert softened["action"] == "create_draft"
    assert agent._is_action_available("play")
    assert strength(agent, "play") >= 0.5


def test_success_can_restore_preference_and_other_method_is_untouched():
    from src.core.agent import DigitalBeing

    agent = DigitalBeing(name="PreferenceRecovery")
    for _ in range(5):
        observe(agent, "play", outcome="error")
    weak = strength(agent, "play")
    for _ in range(6):
        observe(agent, "play", had_effect=True)
    assert strength(agent, "play") > weak
    assert strength(agent, "create_draft") == 1.0


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_preference_survives_real_profile_restart(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "PreferenceLife", new=True)
        for _ in range(4):
            observe(first, "play", outcome="error")
        expected = first._method_preferences.copy()
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, report = create_agent(env, "PreferenceLife")
        assert report["source"] == "checkpoint"
        assert second._method_preferences == expected
        assert strength(second, "play") < strength(second, "create_draft")
    finally:
        PluginRegistry.reset_global()
