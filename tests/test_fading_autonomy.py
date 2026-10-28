"""Решение отпустить намерение поступает в арбитр и не применяется таймером."""

from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.cognition.intention_history import begin_intention, finish_intention
from src.cognition.intention_evidence import finish_evidence_goal
from src.cognition.intention_waiting import remember_wait


def make_waiting():
    agent = DigitalBeing(name="FadingAutonomy")
    first = begin_intention(agent, {"action": "explore", "params": {"topic": "память", "reason": "проверить"}})
    finish_intention(first)
    finish_evidence_goal(agent, first)
    agent.cycle_count += 1
    for _ in range(3):
        entry = begin_intention(agent, {"action": "explore", "source": "continuation",
                                       "params": {"topic": "память", "reason": "проверить", "continuation_of": first["id"]}})
        finish_intention(entry)
        finish_evidence_goal(agent, entry)
        remember_wait(agent, entry)
        agent.cycle_count += 1
    return agent


def test_fading_is_candidate_and_arbitrator_can_choose_other_activity():
    agent = make_waiting()
    with patch.object(agent.decision_arbitrator, "choose_action", side_effect=lambda candidates, context: next(
            item for item in candidates if item["action"] != "let_go")):
        result = agent.autonomous_tick()
    assert "память" in result["fading_proposals"]
    assert agent._waiting_intentions
    assert not next(iter(agent._waiting_intentions.values())).get("resolution")


def test_agent_chosen_let_go_resolves_with_reason():
    agent = make_waiting()
    with patch.object(agent.decision_arbitrator, "choose_action", side_effect=lambda candidates, context: next(
            item for item in candidates if item["action"] == "let_go")):
        result = agent.autonomous_tick()
    entry = next(iter(agent._waiting_intentions.values()))
    assert entry["resolution"]["kind"] == "forgotten"
    assert entry["resolution"]["reason"]
    assert result["autonomous_action"]["action"] == "let_go"
