"""История исходов мягко меняет силу способа и переживает запуск."""

import pytest

from src.cognition.method_preferences import observe, strength, apply
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent


def test_failure_softens_but_does_not_remove_method():
    agent = DigitalBeing(name="MethodPreference")
    for _ in range(3):
        observe(agent, "play", outcome="error")
    assert 0.5 <= strength(agent, "play") < 1.0
    candidates = apply(agent, [{"action": "play", "strength": 1.0}])
    assert candidates[0]["strength"] > 0


def test_success_restores_method_strength_and_unrelated_methods():
    agent = DigitalBeing(name="MethodPreferenceSuccess")
    for _ in range(3):
        observe(agent, "play", outcome="error")
    weak = strength(agent, "play")
    for _ in range(5):
        observe(agent, "play", had_effect=True)
    assert strength(agent, "play") > weak
    assert strength(agent, "communicate") == 1.0


@pytest.mark.parametrize("action", ["play", "create_draft"])
def test_preferences_roundtrip_without_changing_values(action):
    agent = DigitalBeing(name="MethodPreferenceRestore")
    observe(agent, action, had_effect=True)
    state = build_state_from_agent(agent)
    other = DigitalBeing(name="MethodPreferenceRestore")
    apply_state_to_agent(other, state)
    assert other._method_preferences == agent._method_preferences
    assert other.innate_values == agent.innate_values
