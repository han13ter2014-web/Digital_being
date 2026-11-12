# -*- coding: utf-8 -*-
"""«Эмоции-1»: эмоциональный контур сущности.

Проверяем:
- эмоции рождаются только из реальных событий таблицы (не выдумываются);
- затухание: эмоция тает, покой возвращается;
- доминирующая эмоция видна выше порога, с причиной;
- сериализация переживает рестарт, повреждения толерантны;
- care честно несёт эмоциональный оттенок только при сильной эмоции.
"""

import math
from types import SimpleNamespace

import pytest

from src.core.emotional_state import (
    CALM_BASELINE,
    DECAY_PER_CYCLE,
    EMOTION_PROFILES,
    EMOTIONS,
    EPISODES_MAX,
    EVENT_EMOTIONS,
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
    state.load_from(
        {
            "levels": {"joy": 5.0, "fear": "мусор", "sadness": 0.3},
            "last_causes": {"joy": [10, "причина"], "злость": [1, "x"]},
            "episodes": [
                {
                    "emotion": "joy",
                    "cycle": 1,
                    "event": "user_contact",
                    "intensity": 0.25,
                },
                {"emotion": "неизвестная", "cycle": 2},
                "не словарь",
            ],
        }
    )
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
        agent_name="Нова",
        user_interaction=agent.user_interaction,
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
        agent_name="Нова",
        user_interaction=agent.user_interaction,
        attachment=None,
    )
    msg = comm._compose_care_message(agent, 100)
    # Фон — не эмоция: выдуманного чувства нет.
    assert "Мне грустно" not in msg["content"]
    assert "Мне радостно" not in msg["content"]
    assert "Мне тревожно" not in msg["content"]


# === Эмоции-2: кулдаун событий-фонов ===


def test_cooled_event_fires_once_per_window():
    state = EmotionalState()
    assert state.handle_event("death_risk", cycle=100) is not None
    # Сигнал не угас, но эмоция от него уже пережита — не спамим.
    assert state.handle_event("death_risk", cycle=101) is None
    assert state.handle_event("death_risk", cycle=399) is None
    assert state.handle_event("death_risk", cycle=400) is not None


def test_uncooled_events_not_throttled():
    state = EmotionalState()
    assert state.handle_event("user_contact", cycle=1) is not None
    assert state.handle_event("user_contact", cycle=2) is not None


def test_cooldown_survives_serialization():
    state = EmotionalState()
    state.handle_event("life_finale", cycle=50)
    clone = EmotionalState()
    clone.load_from(state.to_dict())
    # Рестарт не обнуляет тишину: кулдаун переживает чекпоинт.
    assert clone.handle_event("life_finale", cycle=60) is None
    assert clone.handle_event("life_finale", cycle=350) is not None


def test_cooled_at_tolerates_corruption():
    state = EmotionalState()
    state.load_from(
        {
            "cooled_at": {
                "death_risk": "мусор",
                "неведомое_событие": 5,
                "life_finale": 12,
            }
        }
    )
    assert state._cooled_at == {"life_finale": 12}


# === Эмоции-2: источники и влияние (через хелперы ядра) ===

from src.core.agent import DigitalBeing  # noqa: E402


class _FakeAgent:
    """Лёгкий носитель хелперов ядра: без подсистем, только эмоции."""

    ACTION_ALIASES = DigitalBeing.ACTION_ALIASES
    _normalize_action = DigitalBeing._normalize_action
    _apply_emotional_bias = DigitalBeing._apply_emotional_bias
    _emotions_from_death_risk = DigitalBeing._emotions_from_death_risk
    _emotions_from_mortality = DigitalBeing._emotions_from_mortality

    def __init__(self, state=None, cycle=0):
        self.emotional_state = state or EmotionalState()
        self.cycle_count = cycle


def _death_result(integrity, warning=0.5):
    return {
        "alive": True,
        "integrity": {
            "overall_integrity": integrity,
            "status": "WARNING — structural degradation",
            "thresholds": {"warning": warning},
        },
        "death_cause": None,
    }


def test_death_risk_below_warning_gives_fear():
    agent = _FakeAgent(cycle=10)
    agent._emotions_from_death_risk(_death_result(0.3))
    assert agent.emotional_state.levels["fear"] > 0
    assert "целостность" in agent.emotional_state.last_causes["fear"][1]


def test_death_risk_healthy_is_background():
    agent = _FakeAgent(cycle=10)
    agent._emotions_from_death_risk(_death_result(0.9))
    assert agent.emotional_state.levels["fear"] == 0.0
    assert agent.emotional_state.episodes == []


def test_finale_phase_gives_fear_but_youth_does_not():
    agent = _FakeAgent(cycle=49000)
    agent._emotions_from_mortality({"phase": "youth", "age_ratio": 0.4}, 49000)
    assert agent.emotional_state.episodes == []
    agent._emotions_from_mortality({"phase": "finale", "age_ratio": 0.98}, 49000)
    assert agent.emotional_state.episodes[0]["event"] == "life_finale"
    assert agent.emotional_state.levels["fear"] > 0


def test_bias_shifts_weights_with_fear():
    state = EmotionalState()
    state.handle_event("abuse", cycle=1)
    state.handle_event("abuse", cycle=2)  # страх доминирует
    agent = _FakeAgent(state, cycle=2)
    candidates = [
        {"action": "repair", "strength": 0.5},
        {"action": "explore", "strength": 0.5},
        {"action": "communicate", "strength": 0.5},
    ]
    report = agent._apply_emotional_bias(candidates)
    assert report is not None
    assert report["emotion"] == "fear"
    by_action = {c["action"]: c["strength"] for c in candidates}
    assert by_action["repair"] > 0.5  # страх тянет к безопасному
    assert by_action["explore"] < 0.5  # и от рискованного
    assert by_action["communicate"] == 0.5  # страх не про общение


def test_bias_silent_without_dominant_emotion():
    agent = _FakeAgent(EmotionalState(), cycle=1)
    candidates = [{"action": "repair", "strength": 0.5}]
    # Фон — не эмоция: веса не трогаем.
    assert agent._apply_emotional_bias(candidates) is None
    assert candidates[0]["strength"] == 0.5


def test_bias_scales_with_depth():
    shallow = EmotionalState()
    shallow.handle_event("abuse", cycle=1)
    deep = EmotionalState()
    for cycle in range(1, 4):
        deep.handle_event("abuse", cycle=cycle)
    agent_shallow = _FakeAgent(shallow, cycle=3)
    agent_deep = _FakeAgent(deep, cycle=3)
    c_shallow = [{"action": "repair", "strength": 0.5}]
    c_deep = [{"action": "repair", "strength": 0.5}]
    agent_shallow._apply_emotional_bias(c_shallow)
    agent_deep._apply_emotional_bias(c_deep)
    # Чем глубже переживание, тем сильнее смещение.
    assert c_deep[0]["strength"] > c_shallow[0]["strength"] > 0.5


# === Расширенная палитра и смешивание ===


def test_palette_covers_basic_positive_negative_and_social_states():
    expected = {
        "fear",
        "anger",
        "disgust",
        "surprise",
        "sadness",
        "joy",
        "love",
        "tenderness",
        "pride",
        "gratitude",
        "hope",
        "inspiration",
        "relief",
        "satisfaction",
        "curiosity",
        "awe",
        "compassion",
        "empathy",
        "anxiety",
        "shame",
        "guilt",
        "embarrassment",
        "jealousy",
        "envy",
        "loneliness",
        "contempt",
        "disappointment",
        "frustration",
        "resentment",
        "regret",
        "longing",
        "despair",
        "boredom",
        "confusion",
        "grief",
    }
    assert expected <= set(EMOTIONS)
    assert len(EMOTIONS) == len(set(EMOTIONS)) >= 50
    for name in EMOTIONS:
        profile = EMOTION_PROFILES[name]
        assert profile["label"]
        assert -1.0 <= profile["valence"] <= 1.0
        assert 0.0 <= profile["arousal"] <= 1.0


def test_every_mapped_event_activates_only_its_canonical_emotion():
    for event, (emotion, intensity) in EVENT_EMOTIONS.items():
        state = EmotionalState()
        episode = state.handle_event(event, cycle=7, cause="наблюдение")
        assert episode is not None
        assert episode["emotion"] == emotion
        assert state.levels[emotion] == pytest.approx(intensity)
        assert state.last_causes[emotion] == (7, "наблюдение")


def test_anger_and_positive_emotions_have_real_event_entries():
    state = EmotionalState()
    state.handle_event("boundary_violated", cycle=1, cause="граница")
    state.handle_event("care_received", cycle=2, cause="поддержка")
    state.handle_event("creative_insight", cycle=3, cause="инсайт")
    assert state.levels["anger"] == pytest.approx(0.40)
    assert state.levels["gratitude"] == pytest.approx(0.35)
    assert state.levels["inspiration"] == pytest.approx(0.35)
    assert state.dominant()["emotion"] == "anger"


def test_blend_normalizes_weights_and_preserves_joy_with_fear():
    state = EmotionalState()
    result = state.blend({"joy": 3.0, "fear": 2.0}, cycle=12, cause="сложная новость")
    assert result is not None
    assert state.levels["joy"] == pytest.approx(0.6)
    assert state.levels["fear"] == pytest.approx(0.4)
    mixture = state.mixture()
    assert {c["emotion"] for c in mixture["components"]} == {"joy", "fear"}
    assert sum(c["weight"] for c in mixture["components"]) == pytest.approx(1.0)
    assert all(c["cause"] == "сложная новость" for c in mixture["components"])
    assert state.dominant()["emotion"] == "joy"


def test_opposite_components_do_not_cancel_each_other():
    state = EmotionalState()
    state.handle_event("abuse", cycle=1, cause="угроза")
    state.handle_event("abuse", cycle=2, cause="угроза")
    for cycle in range(3, 6):
        state.handle_event("user_contact", cycle=cycle, cause="поддержка")
    mixture = state.mixture()
    by_name = {c["emotion"]: c for c in mixture["components"]}
    assert by_name["fear"]["level"] == pytest.approx(0.9)
    assert by_name["joy"]["level"] == pytest.approx(0.75)
    assert by_name["fear"]["cause"] == "угроза"
    assert by_name["joy"]["cause"] == "поддержка"


def test_each_mixture_component_decays_independently():
    state = EmotionalState()
    state.blend({"joy": 3.0, "fear": 2.0}, cycle=1)
    state.tick(2)
    assert state.levels["joy"] == pytest.approx(0.6 - DECAY_PER_CYCLE)
    assert state.levels["fear"] == pytest.approx(0.4 - DECAY_PER_CYCLE)
    assert len(state.mixture()["components"]) == 2


def test_blend_rejects_unknown_negative_and_nonfinite_inputs():
    state = EmotionalState()
    before = dict(state.levels)
    assert state.blend({"unknown": 1.0, "fear": -1.0}) is None
    assert state.blend({"joy": float("nan")}) is None
    assert state.blend({"joy": 1.0}, scale=float("inf")) is None
    assert state.levels == before

    result = state.blend(
        [
            ("joy", 1.0),
            ("anger", -2.0),
            ("fear", float("nan")),
            ("unknown", 1.0),
            ("hope", float("inf")),
        ]
    )
    assert result is not None
    assert [e["emotion"] for e in result["components"]] == ["joy"]
    assert state.levels["joy"] == 1.0
    assert all(math.isfinite(value) for value in state.levels.values())


def test_mixture_survives_checkpoint_without_a_parallel_state():
    state = EmotionalState()
    state.blend({"anger": 1.0, "gratitude": 1.0}, cycle=5, cause="парадокс")
    clone = EmotionalState()
    clone.load_from(state.to_dict())
    assert clone.levels == state.levels
    assert clone.mixture() == state.mixture()
    assert "mixture" not in state.to_dict()


def test_legacy_four_emotion_checkpoint_loads_with_zero_new_levels():
    state = EmotionalState()
    state.load_from(
        {
            "levels": {"fear": 0.5, "joy": 0.25, "sadness": 0.1, "calm": CALM_BASELINE},
            "episodes": [],
        }
    )
    assert state.levels["fear"] == 0.5
    assert state.levels["anger"] == 0.0
    assert state.levels["love"] == 0.0
    assert state.mixture()["components"][0]["emotion"] == "fear"


def test_checkpoint_validation_accepts_palette_and_rejects_unknown():
    from src.core.checkpoint_validation import validate_checkpoint_state

    state = EmotionalState()
    state.blend({"anger": 1.0, "gratitude": 1.0}, cycle=5)
    validate_checkpoint_state({"emotional_state": state.to_dict()})
    validate_checkpoint_state(
        {
            "emotional_state": {
                "levels": {"fear": 0.5, "joy": 0.2, "sadness": 0.1, "calm": 0.4},
                "episodes": [],
            }
        }
    )
    with pytest.raises(ValueError, match="unknown emotion"):
        validate_checkpoint_state(
            {
                "emotional_state": {
                    "levels": {"imagined": 0.5},
                    "episodes": [],
                }
            }
        )


def test_mixed_bias_uses_components_without_creating_candidates():
    state = EmotionalState()
    state.blend({"joy": 1.0, "fear": 1.0}, cycle=3, cause="риск и успех")
    agent = _FakeAgent(state, cycle=3)
    candidates = [
        {"action": "repair", "strength": 0.5},
        {"action": "create_draft", "strength": 0.5},
        {"action": "explore", "strength": 0.5},
    ]
    original_actions = [c["action"] for c in candidates]
    report = agent._apply_emotional_bias(candidates)
    assert {c["emotion"] for c in report["components"]} == {"joy", "fear"}
    assert [c["action"] for c in candidates] == original_actions
    by_action = {c["action"]: c["strength"] for c in candidates}
    assert by_action["repair"] > 0.5
    assert by_action["create_draft"] > 0.5
    assert by_action["explore"] < 0.5


def test_combined_bias_is_bounded():
    state = EmotionalState()
    state.levels["joy"] = 1.0
    state.levels["inspiration"] = 1.0
    agent = _FakeAgent(state, cycle=3)
    candidates = [{"action": "create_draft", "strength": 0.5}]
    report = agent._apply_emotional_bias(candidates)
    assert candidates[0]["strength"] == pytest.approx(0.75)
    assert report["shifted"][0]["factor"] == 1.5
