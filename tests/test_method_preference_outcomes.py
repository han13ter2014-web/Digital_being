"""Все выбранные занятия получают структурированный результат, без смешения методов."""

from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.core.loop_closure import ActionOutcome
from src.core.world_delta import WorldDelta


def test_research_and_communication_are_recorded_separately():
    agent = DigitalBeing(name="MethodOutcomeKinds")
    selection = {"action": "explore", "source": "test", "verdict": "proceed",
                 "params": {"topic": "память"}}
    with patch.object(agent.decision_arbitrator, "choose_action", return_value=selection), \
         patch.object(agent, "think", return_value="Не знаю"):
        agent.autonomous_tick()
    assert agent._method_preferences["explore"]["attempts"] == 1
    assert "communicate" not in agent._method_preferences


def test_generic_action_outcome_is_recorded_separately():
    agent = DigitalBeing(name="GenericMethodOutcome")
    selection = {"action": "communicate", "source": "test", "verdict": "proceed", "params": {}}
    with patch.object(agent.decision_arbitrator, "choose_action", return_value=selection), \
         patch.object(agent, "act", return_value="сообщение"):
        agent.autonomous_tick()
    assert agent._method_preferences["communicate"]["attempts"] == 1


def test_denied_method_is_failure_not_success():
    agent = DigitalBeing(name="MethodDenied")
    denied = ActionOutcome("play", WorldDelta(), reason="denied:too_tired")
    from src.cognition.method_preferences import observe

    observe(agent, "play", outcome="denied", had_effect=denied.had_effect)
    assert agent._method_preferences["play"]["attempts"] == 1
    assert agent._method_preferences["play"]["failures"] == 1
    assert agent._method_preferences["play"]["effects"] == 0


def test_leaving_draft_is_not_effectful_success():
    agent = DigitalBeing(name="MethodLeave")
    agent.act("create_draft")
    selection = {"action": "create_draft", "source": "test", "verdict": "proceed",
                 "params": {"draft_mode": "leave", "draft_id": agent._creative_draft["id"], "reason": "оставить"}}
    with patch.object(agent.decision_arbitrator, "choose_action", return_value=selection):
        agent.autonomous_tick()
    assert agent._method_preferences["create_draft"]["leaves"] == 1
    assert agent._method_preferences["create_draft"]["effects"] == 0
