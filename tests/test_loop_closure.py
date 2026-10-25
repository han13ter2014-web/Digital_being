"""Тесты замыкания петли: действие → наблюдаемый результат → прогресс.

Проверяется главное свойство: прогресс засчитывается по доказанному
изменению мира, а бесполезное действие перестаёт повторяться.

До этого этапа агент зацикливался на ``explore``: действие «выполнялось»,
следов не оставляло, а причины сменить его не возникало. Замер на живом
агенте: 6 тиков — 6 одинаковых действий, прогресс целей 0.
"""

import pytest

from src.core.loop_closure import (
    DEFAULT_PRODUCTIVE_ACTIONS,
    ActionOutcome,
    LoopCloser,
)
from src.core.world_delta import (
    WorldDelta,
    WorldSignature,
    between,
    capture,
)


# ============================================================
# Подпись мира
# ============================================================


class FakeNode:
    def __init__(self, confidence):
        self.confidence = confidence


class FakeMentalModels:
    def __init__(self, concepts=None):
        self.concepts = concepts or {}


class FakeAgent:
    def __init__(self, knowledge=None, concepts=None, questions=None):
        self.knowledge_base = knowledge or {}
        self.mental_models = FakeMentalModels(concepts)
        self._open_questions = questions or []


def test_capture_reads_all_counters():
    agent = FakeAgent(
        knowledge={"a": "1", "b": "2"},
        concepts={"x": FakeNode(0.5), "y": FakeNode(0.25)},
        questions=[
            {"text": "q1", "answered": True, "answer": "да"},
            {"text": "q2", "answered": False},
        ],
    )
    sig = capture(agent)

    assert sig.knowledge_entries == 2
    assert sig.concepts == 2
    assert sig.confidence_milli == 750  # (0.5 + 0.25) * 1000
    assert sig.answered_questions == 1


def test_capture_survives_empty_agent():
    sig = capture(FakeAgent())
    assert sig.knowledge_entries == 0
    assert sig.concepts == 0
    assert sig.confidence_milli == 0


def test_delta_empty_when_nothing_changed():
    sig = WorldSignature(knowledge_entries=5, concepts=3)
    assert between(sig, sig).is_empty is True


def test_delta_detects_new_concept():
    before = WorldSignature(concepts=3)
    after = WorldSignature(concepts=4)
    delta = between(before, after)

    assert delta.is_empty is False
    assert delta.concepts == 1
    assert delta.has_gain is True
    assert "концепций +1" in delta.summary()


def test_delta_reports_confidence_growth():
    delta = between(
        WorldSignature(confidence_milli=500),
        WorldSignature(confidence_milli=900),
    )
    assert delta.confidence_gain == pytest.approx(0.4)
    assert "уверенность +0.40" in delta.summary()


def test_delta_can_be_negative_without_counting_as_gain():
    delta = between(
        WorldSignature(knowledge_entries=10),
        WorldSignature(knowledge_entries=5),
    )
    assert delta.is_empty is False
    assert delta.has_gain is False  # только потеря


# ============================================================
# LoopCloser: учёт результатов
# ============================================================


def test_effect_resets_streak():
    closer = LoopCloser(max_no_effect=3)
    no_change = between(WorldSignature(), WorldSignature())
    growth = between(WorldSignature(concepts=0), WorldSignature(concepts=1))

    closer.observe("explore", WorldSignature(), WorldSignature())
    assert closer.no_effect_streak("explore") == 1

    closer.observe("explore", WorldSignature(), WorldSignature(concepts=1))
    assert closer.no_effect_streak("explore") == 0
    assert closer.has_effect_history("explore") is True
    assert growth.concepts == 1
    assert no_change.is_empty is True


def test_action_becomes_stuck_after_limit():
    closer = LoopCloser(max_no_effect=3)
    empty = WorldSignature()

    for _ in range(2):
        closer.observe("explore", empty, empty)
    assert closer.is_stuck("explore") is False

    closer.observe("explore", empty, empty)
    assert closer.is_stuck("explore") is True
    assert closer.stuck_actions() == ["explore"]


def test_non_productive_action_never_stuck():
    """Отдых и рефлексия не обязаны добавлять знания."""
    closer = LoopCloser(max_no_effect=1)
    empty = WorldSignature()

    for _ in range(10):
        closer.observe("rest", empty, empty)

    assert closer.is_stuck("rest") is False
    assert closer.stuck_actions() == []
    assert "rest" not in DEFAULT_PRODUCTIVE_ACTIONS


def test_denied_action_is_stuck_even_if_non_productive():
    """Вопрос, который нельзя задать, не должен выбираться снова.

    Регрессия: отказ записывался как «мир не изменился», но
    непродуктивные действия (вопрос, общение) никогда не считались
    тупиковыми — и невозможный вопрос выбирался каждый цикл.
    """
    closer = LoopCloser(max_no_effect=3)
    empty = WorldSignature()

    closer.observe("ask_user", empty, empty, reason="denied:too_tired")

    assert closer.denied_streak("ask_user") == 1
    assert closer.is_stuck("ask_user") is True
    assert "ask_user" in closer.stuck_actions()


def test_success_clears_denials():
    """Успешное действие доказывает, что тело снова способно действовать."""
    closer = LoopCloser()
    closer.observe(
        "ask_user", WorldSignature(), WorldSignature(), reason="denied:too_tired"
    )
    assert closer.is_stuck("ask_user") is True

    closer.observe("explore", WorldSignature(), WorldSignature(concepts=1))

    assert closer.is_stuck("ask_user") is False


def test_reset_clears_streak():
    closer = LoopCloser(max_no_effect=1)
    empty = WorldSignature()
    closer.observe("explore", empty, empty)
    assert closer.is_stuck("explore") is True

    closer.reset("explore")
    assert closer.is_stuck("explore") is False


# ============================================================
# LoopCloser: выбор действия
# ============================================================


def test_choose_skips_stuck_candidates():
    closer = LoopCloser(max_no_effect=2)
    empty = WorldSignature()
    for _ in range(2):
        closer.observe("explore", empty, empty)

    chosen = closer.choose(
        [
            {"action": "explore", "strength": 0.9},
            {"action": "synthesis", "strength": 0.5},
        ],
        fallback="think_decompose",
    )
    assert chosen["action"] == "synthesis"


def test_choose_uses_fallback_when_all_stuck():
    closer = LoopCloser(max_no_effect=1)
    empty = WorldSignature()
    closer.observe("explore", empty, empty)
    closer.observe("synthesis", empty, empty)

    chosen = closer.choose(
        [{"action": "explore"}, {"action": "synthesis"}],
        fallback="think_decompose",
    )
    assert chosen["action"] == "think_decompose"
    assert chosen["reason"] == "all_stuck"


def test_choose_normalizes_action_names():
    """«exploration» и «explore» — одно действие для счётчиков."""
    closer = LoopCloser(max_no_effect=1)
    empty = WorldSignature()
    closer.observe("explore", empty, empty)

    chosen = closer.choose(
        [{"action": "exploration", "strength": 0.9}],
        fallback="think_decompose",
        normalize=lambda name: "explore" if name == "exploration" else name,
    )
    assert chosen["action"] == "think_decompose"


# ============================================================
# Сериализация
# ============================================================


def test_counters_survive_checkpoint():
    closer = LoopCloser(max_no_effect=2)
    empty = WorldSignature()
    for _ in range(2):
        closer.observe("explore", empty, empty)
    closer.observe("synthesis", WorldSignature(), WorldSignature(concepts=1))

    state = closer.to_checkpoint_dict()
    restored = LoopCloser(max_no_effect=2)
    restored.restore_from_checkpoint(state)

    assert restored.is_stuck("explore") is True
    assert restored.has_effect_history("synthesis") is True


def test_status_is_json_friendly():
    closer = LoopCloser()
    closer.observe("explore", WorldSignature(), WorldSignature(concepts=1))
    status = closer.status()

    assert status["last_action"] == "explore"
    assert status["last_effect"] is True
    assert "концепций +1" in status["last_summary"]
    assert status["effective_actions"] == ["explore"]