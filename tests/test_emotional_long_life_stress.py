"""Стресс-тест длинной эмоциональной жизни без накопления служебного мусора."""

import math

import pytest

from src.core.emotional_state import (
    CALM_BASELINE,
    EMOTIONS,
    EPISODES_MAX,
    EmotionalState,
)


def test_six_thousand_cycles_with_mixtures_restarts_and_final_fade():
    state = EmotionalState()
    checkpoints = 0

    for cycle in range(1, 5001):
        state.tick(cycle)
        # Постоянный сигнал риска проверяет сериализуемый кулдаун.
        state.handle_event("death_risk", cycle=cycle, cause="фон риска")
        if cycle % 2 == 0:
            state.handle_event("intention_completed", cycle=cycle, cause="дело")
        if cycle % 350 == 0:
            state.handle_event("user_contact", cycle=cycle, cause="контакт")
        if cycle % 400 == 0:
            state.handle_event("abuse", cycle=cycle, cause="вред")
        if cycle % 500 == 0:
            state.blend(
                {"joy": 2.0, "fear": 1.0, "hope": 1.0},
                cycle=cycle,
                cause="сложный период",
                scale=0.8,
            )
        if cycle % 700 == 0:
            state.handle_event("boundary_violated", cycle=cycle, cause="граница")
        if cycle % 700 == 50:
            state.handle_event("care_received", cycle=cycle, cause="забота")
        if cycle % 1000 == 100:
            state.handle_event("long_silence", cycle=cycle, cause="тишина")

        assert len(state.episodes) <= EPISODES_MAX
        assert len(state.last_causes) <= len(EMOTIONS)
        assert all(
            math.isfinite(value) and 0.0 <= value <= 1.0
            for value in state.levels.values()
        )
        mixture = state.mixture()
        if mixture["components"]:
            assert sum(c["weight"] for c in mixture["components"]) == pytest.approx(1.0)
        else:
            assert mixture["total_intensity"] == 0.0

        if cycle % 250 == 0:
            clone = EmotionalState()
            clone.load_from(state.to_dict())
            assert clone.levels == state.levels
            assert clone.last_causes == state.last_causes
            assert clone.episodes == state.episodes
            assert clone._cooled_at == state._cooled_at
            assert clone.mixture() == state.mixture()
            checkpoints += 1

    assert checkpoints == 20

    # После прекращения событий ни одна эмоция не становится вечным фоном.
    for cycle in range(5001, 6501):
        state.tick(cycle)
    assert all(state.levels[name] == 0.0 for name in EMOTIONS if name != "calm")
    assert state.levels["calm"] == CALM_BASELINE
    assert state.mixture()["components"] == []
    assert len(state.episodes) <= EPISODES_MAX
