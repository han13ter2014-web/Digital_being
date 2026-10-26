"""Честная бухгалтерия петли: результат, а не шевеление.

Три регрессии, найденные замером (300 циклов, зрелость 3/6):

* ``decomposition`` вычислял под-вопросы, клал их в текст ответа и терял.
  Мир не менялся, действие считалось бесплодным — и при этом служило
  запасным выходом из тупика. В замере ``think_decompose`` выбирался
  115–162 раза за 500 циклов, то есть каждый четвёртый-пятый цикл
  уходил в пустоту.
* ``effect_ratio`` считался по всем действиям: отдых (45 % действий) и
  отказы (243 за 400 попыток) попадали в знаменатель, поэтому критерий
  зрелости «≥50 %» был недостижим арифметически. Замер: 28 %.
* запасной выход из тупика был тем же действием, которое в тупик и
  приводило.
"""

from __future__ import annotations

import pytest

from src.core.agent import DigitalBeing
from src.core.loop_closure import LoopCloser
from src.core.world_delta import WorldSignature, between, capture


@pytest.fixture()
def agent():
    a = DigitalBeing(name="AccountingAgent")
    searcher = getattr(a, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)
    return a


# ============================================================
# 1. Декомпозиция оставляет след
# ============================================================


def test_decomposition_queues_sub_questions(agent):
    """Под-вопросы не теряются: они попадают в очередь открытых вопросов."""
    before = len(
        [q for q in agent.get_open_questions() if not q.get("answered")]
    )

    agent.act("think_decompose")

    after = agent.get_open_questions()
    unanswered = [q for q in after if not q.get("answered")]
    assert len(unanswered) > before
    assert all(str(q.get("text") or "").strip() for q in unanswered)


def test_decomposition_has_observable_effect(agent):
    """Результат декомпозиции виден в подписи мира, а не только в тексте.

    До правки: ``had_effect`` всегда False, потому что подпись мира не
    считала очередь вопросов.
    """
    agent.act("think_decompose")
    outcome = agent._last_action_outcome

    assert outcome is not None
    assert outcome.action == "decomposition"
    assert outcome.had_effect is True, outcome.delta.as_dict()


def test_world_signature_counts_open_questions(agent):
    agent.ask_user("что такое время", source="test")

    signature = capture(agent)

    assert signature.open_questions == 1
    assert between(WorldSignature(), signature).open_questions == 1


def test_decomposition_is_not_offered_with_full_queue(agent):
    """Очередь полна — декомпозиция не добавит ничего, значит не предлагается."""
    index = 0
    while agent._decomposition_has_room() and index < 20:
        agent.ask_user(f"вопрос номер {index}", source="test")
        index += 1

    assert index < 20
    assert agent._decomposition_has_room() is False
    assert agent._is_action_available("think_decompose") is False


def test_decomposition_is_not_offered_without_decomposable_target(agent):
    """Нечего раскладывать — действие не предлагается, а не тратит цикл."""
    from config.simulation_config import LR_CONFIG

    agent.mental_models.concepts.clear()
    agent._exploration_history = []
    original = LR_CONFIG.STIMULI_POOL
    try:
        LR_CONFIG.STIMULI_POOL = []
        assert agent._pick_decomposable_target(remember=False) is None
        assert agent._is_action_available("think_decompose") is False
    finally:
        LR_CONFIG.STIMULI_POOL = original


def test_decomposition_target_is_actually_decomposable(agent):
    """Цель декомпозиции — та, что делится на части, а не первая попавшаяся."""
    agent.ask_user("что такое счастье", source="test")

    target = agent._pick_decomposable_target(remember=False)

    assert target != "что такое счастье"
    assert agent._decompose_query(target)


# ============================================================
# 2. Доля результативности считает работу, а не простой
# ============================================================


def test_rest_does_not_lower_effect_ratio():
    """Отдых не меняет мир по своей природе — он не должен портить метрику."""
    closer = LoopCloser()
    empty = WorldSignature()

    closer.observe("deep_rest", empty, empty)
    closer.observe("rest", empty, empty)
    closer.observe("reflect", empty, empty)
    closer.observe("explore", empty, WorldSignature(concepts=1))

    assert closer.effect_ratio() == 1.0
    assert closer.productive_total == 1
    assert closer.productive_effect_total == 1


def test_denials_do_not_lower_effect_ratio():
    """Отказ — «не выполнялось», а не «выполнено без результата»."""
    closer = LoopCloser()
    empty = WorldSignature()

    for _ in range(5):
        closer.observe("explore", empty, empty, reason="denied:too_tired")

    assert closer.total_actions == 0
    assert closer.effect_ratio() == 0.0


def test_denial_does_not_poison_no_effect_streak():
    """После восстановления действие не должно оставаться тупиковым."""
    closer = LoopCloser(max_no_effect=1)
    empty = WorldSignature()

    closer.observe("explore", empty, empty, reason="denied:too_tired")
    assert closer.is_stuck("explore") is True  # отказ — тоже причина не выбирать

    closer.reset_denial("explore")

    assert closer.is_stuck("explore") is False
    assert closer.no_effect_streak("explore") == 0


def test_effect_ratio_is_zero_without_history():
    assert LoopCloser().effect_ratio() == 0.0


def test_recall_is_not_knowledge_work():
    """Ответ по памяти не обещает прирост знания — это обслуживание.

    ``know_answer`` стоял в списке продуктивных, но ничего не меняет в
    мире: он читает уже накопленное. За 200 циклов таких ответов 104 из
    400 действий, и доля результативности падала до 46 % на ровном месте.
    Вспомнить — не значит узнать.
    """
    from src.core.loop_closure import DEFAULT_PRODUCTIVE_ACTIONS

    assert "know_answer" not in DEFAULT_PRODUCTIVE_ACTIONS

    closer = LoopCloser(max_no_effect=1)
    empty = WorldSignature()
    closer.observe("know_answer", empty, empty)

    assert closer.is_stuck("know_answer") is False


def test_effect_ratio_survives_checkpoint():
    closer = LoopCloser()
    empty = WorldSignature()
    closer.observe("explore", empty, WorldSignature(concepts=1))
    closer.observe("explore", empty, empty)
    closer.observe("deep_rest", empty, empty)

    restored = LoopCloser()
    restored.restore_from_checkpoint(closer.to_checkpoint_dict())

    assert restored.effect_ratio() == closer.effect_ratio() == 0.5
    assert restored.productive_total == 2


# ============================================================
# 3. Запасной выход не ведёт в тот же тупик
# ============================================================


def test_stuck_fallback_prefers_proven_action(agent):
    """Застряли все — берём то, что раньше давало результат, а не пустой ход."""
    closer = agent.loop_closer
    empty = WorldSignature()
    closer.observe("explore", empty, WorldSignature(concepts=1))
    closer.observe("decomposition", empty, empty)
    closer.observe("decomposition", empty, empty)
    closer.observe("decomposition", empty, empty)
    assert closer.is_stuck("decomposition") is True

    assert agent._stuck_fallback() == "explore"


def test_stuck_fallback_rests_when_nothing_proven(agent):
    """Нет доказанных действий — отдых честнее, чем имитация работы."""
    agent.energy = 200.0
    agent.loop_closer.observe(
        "explore", WorldSignature(), WorldSignature(),
    )
    agent.loop_closer.observe(
        "explore", WorldSignature(), WorldSignature(),
    )
    agent.loop_closer.observe(
        "explore", WorldSignature(), WorldSignature(),
    )

    assert agent._stuck_fallback() == "deep_rest"


def test_stuck_fallback_never_returns_itself(agent):
    """Тупиковое действие не может быть собственным запасным выходом."""
    closer = agent.loop_closer
    for _ in range(3):
        closer.observe("decomposition", WorldSignature(), WorldSignature())
    closer.observe("synthesis", WorldSignature(), WorldSignature())
    closer.observe("synthesis", WorldSignature(), WorldSignature())
    closer.observe("synthesis", WorldSignature(), WorldSignature())

    fallback = agent._stuck_fallback()

    assert closer.is_stuck(fallback) is False
