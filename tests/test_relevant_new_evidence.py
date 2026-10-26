"""Новая возможность по теме учитывается без искусственного повторного исследования."""

import pytest

from src.core.agent import DigitalBeing
from src.cognition.intention_history import begin_intention, finish_intention
from src.cognition.intention_evidence import finish_evidence_goal
from src.cognition.intention_continuation import continuation_candidate


@pytest.mark.parametrize("topic,expected", [("дерево", "pending"), ("память", "satisfied")])
def test_real_reply_only_satisfies_matching_evidence_goal(topic, expected):
    agent = DigitalBeing(name="RelevantReply")
    agent.cycle_count = 100
    entry = begin_intention(agent, {"action": "explore", "params": {"topic": "память"}})
    agent.mental_models.encounter_concept("память", "встреча", "Неизвестная тема")
    finish_intention(entry)
    finish_evidence_goal(agent, entry)
    agent.cycle_count += 1
    retry = begin_intention(agent, continuation_candidate(agent))
    finish_intention(retry)
    finish_evidence_goal(agent, retry)
    agent.cycle_count += 1
    assert continuation_candidate(agent) is None
    assert agent.user_interaction.ask_user(topic, cycle=agent.cycle_count)["status"] == "queued"
    agent._process_user_answer("Содержательное объяснение, полученное от собеседника")
    assert continuation_candidate(agent) is None
    assert retry["evidence_goal"]["status"] == expected
    if expected == "satisfied":
        assert "[Ментальная модель]" in agent.think("вопрос: память")
        assert retry["evidence_goal"]["new_sources"]
    else:
        assert not retry["evidence_goal"]["new_sources"]
