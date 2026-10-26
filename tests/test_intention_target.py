"""Выбранная тема не заменяется случайным новым выбором обработчика."""

from unittest.mock import patch

from src.core.agent import DigitalBeing


def test_explicit_exploration_uses_selected_topic():
    agent = DigitalBeing(name="TargetTest")
    agent.energy = 150
    intention = {"source": "motivation", "params": {"topic": "память", "reason": "хочу разобраться"}}
    with patch.object(agent, "_pick_exploration_target", side_effect=AssertionError("must not retarget")) as picker, \
         patch.object(agent, "think", return_value="Не знаю") as think:
        agent.act("explore", intention=intention)
    picker.assert_not_called()
    think.assert_called_once_with("вопрос: память")
    assert agent.loop_closer.last_outcome.topic == "память"


def test_autonomous_choice_passes_concept_and_reason():
    agent = DigitalBeing(name="IntentionPassTest")
    selection = {"action": "explore", "source": "motivation", "verdict": "proceed",
                 "params": {"concept": "память", "reason": "интерес"}}
    with patch.object(agent.decision_arbitrator, "choose_action", return_value=selection), \
         patch.object(agent, "think", return_value="Не знаю") as think:
        report = agent.autonomous_tick()
    think.assert_called_once_with("вопрос: память")
    assert report["executed_intention"]["params"] == selection["params"]


def test_explicit_decomposition_uses_selected_topic():
    agent = DigitalBeing(name="DecompositionTargetTest")
    with patch.object(agent, "_pick_decomposable_target", side_effect=AssertionError("must not retarget")) as picker, \
         patch.object(agent, "_decompose_query", return_value=[]) as decompose:
        agent.act("think_decompose", intention={"params": {"topic": "память и время"}})
    picker.assert_not_called()
    decompose.assert_called_once_with("память и время")


def test_direct_call_keeps_default_target_selection():
    agent = DigitalBeing(name="DefaultTargetTest")
    with patch.object(agent, "_pick_exploration_target", return_value="время") as picker, \
         patch.object(agent, "think", return_value="Не знаю") as think:
        agent.act("explore")
    picker.assert_called_once()
    think.assert_called_once_with("вопрос: время")
