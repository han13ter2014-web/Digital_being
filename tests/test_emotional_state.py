# -*- coding: utf-8 -*-
"""«Эмоции-1»: эмоциональный контур сущности.

Проверяем:
- эмоции рождаются только из реальных событий таблицы (не выдумываются);
- затухание: эмоция тает, покой возвращается;
- доминирующая эмоция видна выше порога, с причиной;
- сериализация переживает рестарт, повреждения толерантны;
- care честно несёт эмоциональный оттенок только при сильной эмоции.
"""
from types import SimpleNamespace

from src.core.emotional_state import (
    CALM_BASELINE,
    EPISODES_MAX,
    EmotionalState,
)


def test_event_raises_emotion_with_cause():
    state = EmotionalState()
    episode = state.handle_event("user_contact", cycle=10)
    assert episode["emotion"] == "joy"
    assert state.levels["joy"] > 0.0
    # Всплеск потеснил покой
    assert state.levels["calm"] < CALM_BASELINE


def test_unknown_event_creates_nothing():
    state = EmotionalState()
    assert state.handle_event("внезапное вдохновение", cycle=1) is None
    assert state.episodes == []


def test_emotions_decay_and_calm_recovers():
    state = EmotionalState()
    state.handle_event("abuse", cycle=0, cause="pain_input")
    fear_after_event = state.levels["fear"]
    calm_after_event = state.levels["calm"]
    for cycle in range(1, 101):
        state.tick(cycle)
    assert state.levels["fear"] < fear_after_event
    assert state.levels["calm"] > calm_after_event


def test_dominant_above_threshold_carries_cause():
    state = EmotionalState()
    assert state.dominant() is None  # фон — не событие
    state.handle_event("abuse", cycle=5, cause="humiliation")
    state.handle_event("abuse", cycle=6, cause="humiliation")
    dominant = state.dominant()
    assert dominant is not None
    assert dominant["emotion"] == "fear"
    assert dominant["cause"] == "humiliation"
    assert dominant["label"] == "мне тревожно"


def test_calm_dominates_only_when_truly_calm():
    state = EmotionalState()
    # Базовый покой — не повод говорить о нём.
    assert state.dominant() is None
    state.levels["calm"] = CALM_BASELINE + 0.3
    dominant = state.dominant()
    assert dominant is not None
    assert dominant["emotion"] == "calm"


def test_episodes_log_is_bounded():
    state = EmotionalState()
    for index in range(EPISODES_MAX + 20):
        state.handle_event("user_contact", cycle=index)
    assert len(state.episodes) == EPISODES_MAX


def test_serialization_roundtrip():
    state = EmotionalState()
    state.handle_event("learned_phrase", cycle=10, cause="теплая фраза")
    state.handle_event("long_silence", cycle=20)
    state.tick(21)

    clone = EmotionalState()
    clone.load_from(state.to_dict())
    assert clone.levels == state.levels
    assert clone.episodes == state.episodes
    assert clone.last_causes == state.last_causes


def test_load_from_tolerates_corruption():
    state = EmotionalState()
    state.load_from(None)
    state.load_from({"levels": "мусор", "episodes": "тоже мусор"})
    state.load_from({
        "levels": {"joy": 5.0, "fear": "мусор", "sadness": 0.3},
        "last_causes": {"joy": [10, "причина"], "злость": [1, "x"]},
        "episodes": [
            {"emotion": "joy", "cycle": 1, "event": "user_contact",
             "intensity": 0.25},
            {"emotion": "неизвестная", "cycle": 2},
            "не словарь",
        ],
    })
    assert state.levels["joy"] == 1.0  # обрезано до диапазона
    assert state.levels["sadness"] == 0.3
    assert "злость" not in state.last_causes
    assert len(state.episodes) == 1


# === Интеграция: care несёт эмоциональный оттенок честно ===

class _Interaction:
    def get_history(self, limit):
        return []


def test_care_carries_honest_emotional_tinge():
    from src.core.subsystems.proactive_communication import (
        ProactiveCommunication,
    )

    state = EmotionalState()
    state.handle_event("long_silence", cycle=90)
    state.handle_event("long_silence", cycle=95)
    agent = SimpleNamespace(
        user_interaction=_Interaction(),
        user_model=None,
        dialogue_learning=None,
        emotional_state=state,
    )
    comm = ProactiveCommunication(
        agent_name="Тэсс", user_interaction=agent.user_interaction,
        attachment=None,
    )
    msg = comm._compose_care_message(agent, 100)
    assert "Мне грустно." in msg["content"]


def test_care_without_emotion_has_no_tinge():
    from src.core.subsystems.proactive_communication import (
        ProactiveCommunication,
    )

    agent = SimpleNamespace(
        user_interaction=_Interaction(),
        user_model=None,
        dialogue_learning=None,
        emotional_state=EmotionalState(),
    )
    comm = ProactiveCommunication(
        agent_name="Тэсс", user_interaction=agent.user_interaction,
        attachment=None,
    )
    msg = comm._compose_care_message(agent, 100)
    # Фон — не эмоция: выдуманного чувства нет.
    assert "Мне грустно" not in msg["content"]
    assert "Мне радостно" not in msg["content"]
    assert "Мне тревожно" not in msg["content"]
