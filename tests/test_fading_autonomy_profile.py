"""Автономное забывание выбирается арбитром и переживает профильный restart."""

from unittest.mock import patch

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.cognition.intention_history import begin_intention, finish_intention
from src.cognition.intention_evidence import finish_evidence_goal
from src.cognition.intention_waiting import remember_wait
from src.core.subsystem_base import PluginRegistry


def make_waiting(agent):
    first = begin_intention(agent, {"action": "explore", "source": "test",
                                   "params": {"topic": "память", "reason": "проверить"}})
    finish_intention(first)
    finish_evidence_goal(agent, first)
    agent.cycle_count += 1
    remember_wait(agent, first)
    for index in range(3):
        entry = begin_intention(agent, {"action": "explore", "source": "continuation",
                                       "params": {"topic": "память", "reason": "проверить", "continuation_of": first["id"]}})
        finish_intention(entry)
        finish_evidence_goal(agent, entry)
        remember_wait(agent, entry)
        agent.cycle_count += 1


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_autonomous_let_go_is_a_real_terminal_decision(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "FadingLife", new=True)
        make_waiting(first)
        with patch.object(first.decision_arbitrator, "choose_action", side_effect=lambda candidates, context: next(
                candidate for candidate in candidates if candidate["action"] == "let_go")):
            result = first.autonomous_tick()
        assert result["autonomous_action"]["action"] == "let_go"
        waiting = next(iter(first._waiting_intentions.values()))
        assert waiting["resolution"]["kind"] == "forgotten"
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, report = create_agent(env, "FadingLife")
        assert report["source"] == "checkpoint"
        assert next(iter(second._waiting_intentions.values()))["resolution"]["kind"] == "forgotten"
        assert not any(item.get("action") == "let_go" for item in second._intention_history[-1:])
    finally:
        PluginRegistry.reset_global()


def test_autonomous_other_choice_leaves_waiting_intention_active():
    from src.core.agent import DigitalBeing

    agent = DigitalBeing(name="FadingOtherChoice")
    make_waiting(agent)
    with patch.object(agent.decision_arbitrator, "choose_action", side_effect=lambda candidates, context: next(
            candidate for candidate in candidates if candidate["action"] != "let_go")):
        result = agent.autonomous_tick()
    assert result["fading_proposals"] == ["память"]
    assert not next(iter(agent._waiting_intentions.values())).get("resolution")
