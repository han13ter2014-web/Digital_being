"""Новые эмоции возникают из наблюдаемых фактов, а не из пожелания разнообразия."""

from types import SimpleNamespace

import pytest

from config.simulation_config import LR_CONFIG
from src.core.agent import DigitalBeing
from src.core.emotional_state import DECAY_PER_CYCLE, EmotionalState
from src.core.motivation.unified_motivation import create_motivation_system


def _motivation_agent():
    agent = SimpleNamespace(
        cycle_count=5,
        knowledge_base={},
        beliefs={},
        emotional_state=EmotionalState(),
    )
    return agent, create_motivation_system(agent)


def test_pressing_need_transition_yields_one_satisfaction():
    agent, system = _motivation_agent()
    system.needs["play"].current_level = 0.2

    system.on_action_result("create_draft", True, 0.8)

    episodes = [
        item
        for item in agent.emotional_state.episodes
        if item["event"] == "need_satisfied"
    ]
    assert len(episodes) == 1
    assert episodes[0]["emotion"] == "satisfaction"
    assert agent.emotional_state.last_causes["satisfaction"] == (5, "play")

    system.on_action_result("create_draft", True, 0.8)
    assert (
        len(
            [
                item
                for item in agent.emotional_state.episodes
                if item["event"] == "need_satisfied"
            ]
        )
        == 1
    )


def test_positive_result_without_transition_does_not_create_satisfaction():
    agent, system = _motivation_agent()
    system.needs["play"].current_level = 0.6

    system.on_action_result("create_draft", True, 0.8)

    assert agent.emotional_state.levels["satisfaction"] == 0.0
    assert agent.emotional_state.episodes == []


def test_multiple_newly_satisfied_needs_share_one_event():
    agent, system = _motivation_agent()
    system.needs["curiosity"].current_level = 0.2
    system.needs["competence"].current_level = 0.1

    system.on_action_result("hypothesis", True, 0.8)

    episodes = [
        item
        for item in agent.emotional_state.episodes
        if item["event"] == "need_satisfied"
    ]
    assert len(episodes) == 1
    assert agent.emotional_state.last_causes["satisfaction"] == (
        5,
        "curiosity, competence",
    )


def test_mismatched_observation_yields_surprise(monkeypatch):
    agent = DigitalBeing(name="SurpriseObserved")
    agent.energy = 20
    monkeypatch.setattr(agent, "_recover_energy", lambda deep=False: 0.0)

    agent.act("rest")

    assert agent.action_expectations.last_trial["prediction_matched"] is False
    episodes = [
        item
        for item in agent.emotional_state.episodes
        if item["event"] == "unexpected_outcome"
    ]
    assert len(episodes) == 1
    assert episodes[0]["emotion"] == "surprise"
    assert agent.emotional_state.last_causes["surprise"] == (agent.cycle_count, "rest")


def test_matched_or_unobserved_prediction_does_not_create_surprise():
    matched = DigitalBeing(name="SurpriseMatched")
    matched.energy = 20
    matched.act("rest")
    assert matched.action_expectations.last_trial["prediction_matched"] is True
    assert matched.emotional_state.levels["surprise"] == 0.0

    unobserved = DigitalBeing(name="SurpriseUnobserved")
    unobserved.energy = LR_CONFIG.ENERGY_MAX
    unobserved.act("deep_rest")
    assert unobserved.action_expectations.last_trial is None
    assert unobserved.emotional_state.levels["surprise"] == 0.0


@pytest.mark.parametrize(
    ("event", "emotion"),
    [("need_satisfied", "satisfaction"), ("unexpected_outcome", "surprise")],
)
def test_new_emotions_use_existing_decay(event, emotion):
    state = EmotionalState()
    state.handle_event(event, cycle=1, cause="test")
    before = state.levels[emotion]

    state.tick()

    assert state.levels[emotion] == pytest.approx(before - DECAY_PER_CYCLE)
