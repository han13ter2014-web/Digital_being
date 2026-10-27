"""Игра меняет игровое состояние, не создавая вымышленных знаний."""

from unittest.mock import patch

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.core.agent import DigitalBeing
from src.core.subsystem_base import PluginRegistry
from src.cognition.local_play import new_game, play_turn, validate_game


def test_play_does_not_search_or_add_concept_experience():
    agent = DigitalBeing(name="PlayNotResearch")
    before = agent.mental_models.to_storage_dict()
    play_level = agent.motivation_system.needs["play"].current_level
    with patch.object(agent, "think", side_effect=AssertionError("game is not research")) as think:
        agent.act("play")
    think.assert_not_called()
    assert agent._local_play["turns"] == 1
    assert agent._local_play["board"].count("X") == 1
    assert agent._local_play["board"].count("O") == 1
    assert agent.mental_models.to_storage_dict() == before
    assert agent.motivation_system.needs["play"].current_level > play_level


def test_play_need_proposes_game_and_can_lose_arbitration():
    agent = DigitalBeing(name="PlayChoice")
    system = agent.motivation_system
    for need in system.needs.values():
        need.current_level = need.base_level
    for drive in system.drives.values():
        drive.current_level = 0
    system.needs["play"].current_level = 0
    candidate = next(c for c in system.get_action_candidates({}) if c["action"] == "play")
    verdict = {"score": 0.5, "verdict": "proceed", "confidence": 0.5, "reasoning": "test", "voices": {}}
    with patch.object(agent.decision_arbitrator, "arbitrate", return_value=verdict):
        other = {"action": "communicate", "source": "other_desire", "strength": 1.0}
        assert agent.decision_arbitrator.choose_action([candidate, other], {})["action"] == "communicate"
        other["strength"] = 0.1
        assert agent.decision_arbitrator.choose_action([candidate, other], {})["action"] == "play"


def test_round_ends_and_new_round_only_begins_on_next_chosen_turn():
    game = new_game()
    for _ in range(5):
        play_turn(game)
        validate_game(game)
        if game["result"]:
            break
    assert game["result"] in {"X", "O", "draw"}
    assert game["round"] == 1
    play_turn(game)
    assert game["round"] == 2
    assert game["turns"] == 1


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_game_survives_normal_restart(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "GameLife", new=True)
        first.act("play")
        before = dict(first._local_play, board=list(first._local_play["board"]))
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, _ = create_agent(env, "GameLife")
        assert second._local_play == before
        second.act("play")
        assert second._local_play["turns"] == 2
    finally:
        PluginRegistry.reset_global()
