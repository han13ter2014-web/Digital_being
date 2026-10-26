"""Выбор и исход связаны; незавершённое сохранение не выдумывает успех."""

from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent
from src.cognition.intention_history import begin_intention, LIMIT


def test_real_execution_records_target_reason_and_observed_outcome():
    agent = DigitalBeing(name="IntentionMemory")
    selected = {"action": "explore", "source": "motivation", "verdict": "proceed",
                "params": {"topic": "память", "reason": "интерес"}}
    with patch.object(agent.decision_arbitrator, "choose_action", return_value=selected), \
         patch.object(agent, "think", return_value="Не знаю"):
        report = agent.autonomous_tick()
    entry = agent._intention_history[-1]
    assert entry["id"] == report["intention_id"]
    assert entry["target"] == "память"
    assert entry["reason"] == "интерес"
    assert entry["status"] == "performed"
    assert entry["outcome"]["topic"] == "память"
    restored = DigitalBeing(name="IntentionMemory")
    apply_state_to_agent(restored, build_state_from_agent(agent))
    assert restored._intention_history == agent._intention_history


def test_unfinished_attempt_restores_as_interrupted_without_outcome():
    agent = DigitalBeing(name="InterruptedIntention")
    begin_intention(agent, {"action": "rest", "source": "test"})
    state = build_state_from_agent(agent)
    apply_state_to_agent(agent, state)
    assert agent._intention_history[-1]["status"] == "interrupted"
    assert agent._intention_history[-1]["outcome"] is None
    assert state["intention_history"][-1]["status"] == "started"


def test_no_stale_outcome_when_handler_is_unobserved():
    agent = DigitalBeing(name="UnobservedIntention")
    agent.act("rest")
    with patch.object(agent.decision_arbitrator, "choose_action", return_value={"action": "communicate", "source": "test"}), \
         patch.object(agent, "act", return_value="text"):
        agent.autonomous_tick()
    assert agent._intention_history[-1]["status"] == "unobserved"
    assert agent._intention_history[-1]["outcome"] is None


def test_history_is_bounded():
    agent = DigitalBeing(name="BoundedIntentions")
    for _ in range(LIMIT + 5):
        begin_intention(agent, {"action": "rest"})
    assert len(agent._intention_history) == LIMIT
