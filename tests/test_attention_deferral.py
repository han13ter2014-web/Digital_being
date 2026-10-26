"""Выбранный отдых не отменяется обязательной второй работой."""

from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent
from src.core.event_bus import EventBus


def test_rest_defers_user_question_and_preserves_it_across_restore():
    agent = DigitalBeing(name="AttentionTest")
    runner = AgentRunner(agent, EventBus())
    before = agent.cycle_count
    with patch.object(agent, "autonomous_tick", return_value={"autonomous_action": {"action": "deep_rest"}}), \
         patch.object(agent, "think") as think:
        runner._do_one_agent_cycle("вопрос: как устроена память", user_initiated=True)
        assert not think.called
    assert agent.cycle_count == before + 1
    assert agent._deferred_stimulus == {"text": "вопрос: как устроена память", "user_initiated": True}
    second = DigitalBeing(name="AttentionTest")
    apply_state_to_agent(second, build_state_from_agent(agent))
    assert second._deferred_stimulus == agent._deferred_stimulus


def test_deferred_question_is_processed_after_nonrest_choice():
    agent = DigitalBeing(name="AttentionProcessTest")
    agent._deferred_stimulus = {"text": "вопрос: память", "user_initiated": True}
    runner = AgentRunner(agent, EventBus())
    with patch.object(agent, "autonomous_tick", return_value={"attention_selected": True, "arbitrator": {"action": "process_stimulus"}}), \
         patch.object(agent, "perceive", return_value="память"), \
         patch.object(agent, "think", return_value="Ответ: проверка") as think, \
         patch.object(agent, "act", return_value="Ответ: проверка"):
        runner._do_one_agent_cycle(agent._deferred_stimulus["text"], user_initiated=True)
    think.assert_called_once()
    assert agent._deferred_stimulus is None
