"""Доступность относится к выбранной теме, malformed payload не переизбирает тему."""

from unittest.mock import patch

import pytest

from src.cognition.intention_payload import intention_target
from src.core.agent import DigitalBeing


@pytest.mark.parametrize("params", [{"topic": []}, {"topic": " "}, {"topic": "a", "concept": "b"}, []])
def test_invalid_payload_rejected(params):
    with pytest.raises(ValueError):
        intention_target({"params": params})


def test_decomposition_checks_selected_topic_not_another_available_one():
    agent = DigitalBeing(name="CandidateTarget")
    with patch.object(agent, "_decomposition_has_room", return_value=True), \
         patch.object(agent, "_decompose_query", side_effect=lambda text: ["one"] if text == "неделимая" else ["one", "two"]):
        assert not agent._is_candidate_available({"action": "think_decompose", "params": {"topic": "неделимая"}})
        assert agent._is_candidate_available({"action": "think_decompose", "params": {"topic": "сложная тема"}})


def test_synthesis_and_question_receive_selected_topic():
    agent = DigitalBeing(name="OtherTargetHandlers")
    with patch.object(agent, "_act_synthesize", return_value={"target": "память"}) as synthesize:
        agent.act("synthesize", intention={"params": {"topic": "память"}})
    synthesize.assert_called_once_with(target="память")
    with patch.object(agent, "_act_ask_user", return_value={"target": "время"}) as ask:
        agent.act("ask_user", intention={"params": {"concept": "время"}})
    ask.assert_called_once_with(target="время")


def test_invalid_payload_has_no_cost_or_handler_effect():
    agent = DigitalBeing(name="MalformedNoEffect")
    energy = agent.energy
    with patch.object(agent, "_act_explore") as handler:
        with pytest.raises(ValueError):
            agent.act("explore", intention={"params": {"topic": []}})
    handler.assert_not_called()
    assert agent.energy == energy
