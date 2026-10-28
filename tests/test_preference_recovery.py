"""Новая возможность возвращает способ в выбор, не переписывая личность."""

from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.cognition.method_preferences import observe, strength, apply
from src.core.personal_continuity import capture_personal_state


def equal_candidates():
    return [{"action": "play", "source": "activity", "strength": 0.8, "params": {}},
            {"action": "create_draft", "source": "activity", "strength": 0.8, "params": {}}]


def test_successful_new_opportunity_restores_method_without_value_change():
    agent = DigitalBeing(name="PreferenceRecoveryBoundary")
    before_values = dict(agent.innate_values)
    before_personal = capture_personal_state(agent)
    for _ in range(5):
        observe(agent, "play", outcome="error")
    weak = strength(agent, "play")
    for _ in range(10):
        observe(agent, "play", had_effect=True)
    recovered = strength(agent, "play")
    assert recovered > weak
    assert recovered <= 1.2
    assert agent.innate_values == before_values
    assert capture_personal_state(agent) == before_personal


def test_new_opportunity_can_change_real_arbitration_but_not_force_it():
    agent = DigitalBeing(name="PreferenceRecoveryChoice")
    for _ in range(5):
        observe(agent, "play", outcome="error")
    verdict = {"score": 0.5, "verdict": "proceed", "confidence": 0.5,
               "reasoning": "controlled", "voices": {}}
    with patch.object(agent.decision_arbitrator, "arbitrate", return_value=verdict):
        before = agent.decision_arbitrator.choose_action(apply(agent, equal_candidates()), {})
        for _ in range(10):
            observe(agent, "play", had_effect=True)
        after = agent.decision_arbitrator.choose_action(apply(agent, equal_candidates()), {})
    assert before["action"] == "create_draft"
    assert after["action"] in {"play", "create_draft"}
    assert agent._is_action_available("play")
