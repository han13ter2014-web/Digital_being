"""stop меняет исполнение, а не только текст вердикта."""

from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.core.subsystems.decision_arbitrator import DecisionArbitrator


def verdict(kind, score):
    return {"verdict": kind, "score": score, "confidence": 0.8,
            "reasoning": kind, "voices": {}}


def test_stopped_high_score_loses_to_allowed_alternative():
    arbiter = DecisionArbitrator()
    with patch.object(arbiter, "arbitrate", side_effect=[verdict("stop", 0.9), verdict("proceed", 0.5)]):
        result = arbiter.choose_action([
            {"action": "explore", "source": "test", "strength": 1.0},
            {"action": "rest", "source": "test", "strength": 0.2}], {})
    assert result["action"] == "rest"
    assert result["verdict"] == "proceed"
    assert any(entry["verdict"] == "stop" for entry in result["all_evaluations"])


def test_all_stopped_returns_wait_not_least_bad_execution():
    arbiter = DecisionArbitrator()
    with patch.object(arbiter, "arbitrate", return_value=verdict("stop", 0.3)):
        result = arbiter.choose_action([{"action": "explore", "source": "test", "strength": 1}], {})
    assert result["action"] == "wait"
    assert result["verdict"] == "stop"


def test_core_does_not_execute_external_stopped_selection():
    agent = DigitalBeing(name="StopGateTest")
    with patch.object(agent.decision_arbitrator, "choose_action", return_value={
            "action": "explore", "source": "test", "verdict": "stop", "reasoning": "не хочу"}), \
         patch.object(agent, "act") as act:
        result = agent.autonomous_tick()
    act.assert_not_called()
    assert result["action_refused"]["action"] == "explore"
    assert "loop_escape" not in result
    assert "autonomous_action" not in result


def test_stopped_attention_does_not_authorize_question_processing():
    agent = DigitalBeing(name="StopAttentionTest")
    agent._attention_stimulus = {"text": "вопрос", "user_initiated": True}
    with patch.object(agent.decision_arbitrator, "choose_action", return_value={
            "action": "process_stimulus", "source": "external_attention", "verdict": "stop"}):
        result = agent.autonomous_tick()
    assert not result.get("attention_selected")
