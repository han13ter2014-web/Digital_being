"""Один выбор: внешняя задача или автономное действие, без скрытого второго act."""

from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.event_bus import EventBus


def test_selected_external_attention_executes_only_stimulus_action():
    agent = DigitalBeing(name="ExternalAttentionTest")
    runner = AgentRunner(agent, EventBus())

    def choose(candidates, context):
        return {**next(c for c in candidates if c["source"] == "external_attention"), "verdict": "proceed"}

    with patch.object(agent.decision_arbitrator, "choose_action", side_effect=choose), \
         patch.object(agent, "perceive", return_value="вопрос"), \
         patch.object(agent, "think", return_value="Знаю ответ: тест") as think, \
         patch.object(agent, "act", return_value="Ответ: тест") as act:
        runner._do_one_agent_cycle("вопрос человека", user_initiated=True)
    think.assert_called_once()
    act.assert_called_once_with("Знаю ответ: тест")
    assert agent._deferred_stimulus is None
    assert agent._attention_stimulus is None


def test_autonomous_choice_defers_without_thinking_about_stimulus():
    agent = DigitalBeing(name="OwnAttentionTest")
    runner = AgentRunner(agent, EventBus())
    with patch.object(agent.decision_arbitrator, "choose_action", return_value={"action": "communicate", "source": "social"}), \
         patch.object(agent, "act", return_value="Общение") as act, \
         patch.object(agent, "think") as think:
        runner._do_one_agent_cycle("вопрос человека", user_initiated=True)
    act.assert_called_once_with("communicate")
    assert not think.called
    assert agent._deferred_stimulus["text"] == "вопрос человека"
