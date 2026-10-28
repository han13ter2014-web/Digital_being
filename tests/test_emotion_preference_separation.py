"""Эмоция хранится рядом с предпочтением, но не является его формулой."""

from src.core.agent import DigitalBeing
from src.cognition.method_preferences import observe, strength, validate


def test_same_outcome_different_emotion_has_same_method_strength():
    positive = DigitalBeing(name="PositivePreference")
    negative = DigitalBeing(name="NegativePreference")
    for agent, valence in ((positive, 0.9), (negative, -0.9)):
        for _ in range(5):
            observe(agent, "play", had_effect=True, emotional_valence=valence)
    assert strength(positive, "play") == strength(negative, "play")
    assert positive._method_preferences["play"]["valence_sum"] == 4.5
    assert negative._method_preferences["play"]["valence_sum"] == -4.5


def test_failure_preference_and_emotion_remain_separate():
    agent = DigitalBeing(name="EmotionFailure")
    observe(agent, "play", outcome="error", emotional_valence=0.8)
    assert strength(agent, "play") < 1.0
    assert agent._method_preferences["play"]["valence_sum"] == 0.8
    validate(agent._method_preferences)


def test_emotion_does_not_change_values_or_identity():
    agent = DigitalBeing(name="EmotionIdentity")
    values = list(agent.value_evolution.current_values)
    identity = agent.soul.get("self").to_dict()
    observe(agent, "create_draft", had_effect=True, emotional_valence=-1.0)
    assert agent.value_evolution.current_values == values
    assert agent.soul.get("self").to_dict() == identity
