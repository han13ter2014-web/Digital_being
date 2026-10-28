"""История исходов влияет на долгосрочный выбор и переживает перезапуск."""

from unittest.mock import patch

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.cognition.method_preferences import observe, apply
from src.core.subsystem_base import PluginRegistry
from src.core.personal_continuity import capture_personal_state


def candidates():
    return [{"action": "play", "source": "activity", "strength": 0.8, "params": {}},
            {"action": "create_draft", "source": "activity", "strength": 0.8, "params": {}}]


def test_long_term_preference_changes_arbitration_without_emotion_or_identity():
    from src.core.agent import DigitalBeing

    agent = DigitalBeing(name="LongTermChoice")
    personal = capture_personal_state(agent)
    for _ in range(5):
        observe(agent, "play", outcome="error", emotional_valence=0.8)
    verdict = {"score": 0.5, "verdict": "proceed", "confidence": 0.5, "reasoning": "equal", "voices": {}}
    with patch.object(agent.decision_arbitrator, "arbitrate", return_value=verdict):
        choice = agent.decision_arbitrator.choose_action(apply(agent, candidates()), {})
    assert choice["action"] == "create_draft"
    assert capture_personal_state(agent) == personal
    assert agent._method_preferences["play"]["valence_sum"] == 4.0
    assert agent._is_action_available("play")


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_long_term_preference_survives_restart(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "LongTermLife", new=True)
        for _ in range(5):
            observe(first, "play", outcome="error")
        expected = dict(first._method_preferences)
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, _ = create_agent(env, "LongTermLife")
        assert second._method_preferences == expected
        assert second._is_action_available("play")
    finally:
        PluginRegistry.reset_global()
