"""Имя алиаса не превращает исследование в игру или неопределённый акт в успех."""

import pytest

from src.core.agent import DigitalBeing


@pytest.mark.parametrize("action", ["explore", "synthesis", "know_answer", "hypothesis", "default"])
def test_research_does_not_satisfy_play_by_alias(action):
    agent = DigitalBeing(name="FeedbackSeparation")
    system = agent.motivation_system
    system.needs["play"].current_level = 0.1
    system.on_action_result(action, True, 0.8)
    assert system.needs["play"].current_level == 0.1


@pytest.mark.parametrize("action", ["play", "create_draft"])
def test_actual_play_or_draft_satisfies_play_without_curiosity_reward(action):
    agent = DigitalBeing(name="RealActivityFeedback")
    system = agent.motivation_system
    system.needs["play"].current_level = 0.1
    system.needs["curiosity"].current_level = 0.1
    system.on_action_result(action, True, 0.8)
    assert system.needs["play"].current_level > 0.1
    assert system.needs["curiosity"].current_level == 0.1


def test_unspecified_action_cannot_satisfy_many_needs():
    agent = DigitalBeing(name="NoGenericReward")
    system = agent.motivation_system
    before = {name: need.current_level for name, need in system.needs.items()}
    system.on_action_result("default", True, 0.8)
    assert {name: need.current_level for name, need in system.needs.items()} == before
