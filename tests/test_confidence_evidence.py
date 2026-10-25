"""Уверенность как функция свидетельств, а не счётчик встреч.

Регрессия, найденная замером (200 циклов, 8 встреч, определение 108
символов — уверенность 0.100, «ответить не могу»):

    confidence = 0.1 + 0.7 * (встреч с |valence| > 0.3) / (всего встреч)

Три порока:

* обрыв на границе: при valence ровно 0.3 (это значение пишет путь
  гипотезы) условие ``> 0.3`` ложно — уверенность не растёт никогда;
  при 0.31 — сразу 0.8;
* нет объёма: одна встреча и десять давали одно и то же;
* нет различения силы: догадка 0.3 и найденный источник 0.7 весили
  одинаково, как только перешли порог.

Следствие было не косметическим: ``can_answer_about`` требует
уверенность выше 0.4, поэтому агент не мог ответить ни об одной
концепции, которую изучил сам. Замер до правки: 0 из 53 (0%).
"""

import pytest

from src.cognition.mental_models import (
    CONFIDENCE_MAX,
    ConceptNode,
    MentalModel,
)


def _node(*valences: float, name: str = "тема") -> ConceptNode:
    node = ConceptNode(name)
    for index, valence in enumerate(valences):
        node.add_experience(f"ctx_{index}", "результат", valence)
    return node


# ============================================================
# 1. Нет обрыва на границе 0.3
# ============================================================


def test_valence_exactly_threshold_grows_confidence():
    """0.3 — рабочее значение, а не мёртвая зона."""
    node = _node(0.3)

    assert node.confidence > 0.1


def test_no_cliff_between_030_and_031():
    """Сотая доля разницы не должна решать «знаю / не знаю»."""
    low = _node(0.30)
    high = _node(0.31)

    assert abs(high.confidence - low.confidence) < 0.05


def test_zero_valence_is_not_evidence():
    """«Увидел тему» — не «узнал о ней»."""
    node = _node(0.0, 0.0, 0.0)

    assert node.confidence == pytest.approx(0.1)


# ============================================================
# 2. Объём свидетельств имеет значение
# ============================================================


def test_more_consistent_encounters_mean_more_confidence():
    one = _node(0.3)
    two = _node(0.3, 0.3)
    four = _node(0.3, 0.3, 0.3, 0.3)

    assert one.confidence < two.confidence < four.confidence


def test_single_weak_encounter_is_not_enough_to_answer():
    node = _node(0.3)

    assert not MentalModel().can_answer_about("тема")
    assert node.confidence < 0.4


def test_two_consistent_encounters_allow_answering():
    model = MentalModel()
    node = model.encounter_concept("тема", "ctx_1", "следы памяти", 0.3)
    model.encounter_concept("тема", "ctx_2", "следы памяти", 0.3)

    assert node.confidence > 0.4
    assert len(node.definition_hypothesis) > 10
    assert model.can_answer_about("тема") is True


def test_confidence_is_bounded():
    node = _node(*([0.9] * 10))

    assert node.confidence == pytest.approx(CONFIDENCE_MAX)
    assert node.confidence < 1.0


# ============================================================
# 3. Сила свидетельства, а не только факт
# ============================================================


def test_strong_source_weighs_more_than_guess():
    guess = _node(0.3)
    source = _node(0.7)

    assert source.confidence > guess.confidence


def test_one_real_source_is_enough_to_answer():
    """Прочитал источник — можешь пересказать. Догадка — нет."""
    model = MentalModel()
    model.encounter_concept("энтропия", "web:wikipedia", "мера беспорядка", 0.7)
    model.encounter_concept("энтропия", "ctx", "мера беспорядка", 0.0)

    assert model.can_answer_about("энтропия") is True


# ============================================================
# 4. Противоречия снижают уверенность
# ============================================================


def test_contradictory_evidence_lowers_confidence():
    consistent = _node(0.3, 0.3, 0.3)
    mixed = _node(0.3, 0.3, -0.3)

    assert mixed.confidence < consistent.confidence


def test_contradiction_can_block_answering():
    model = MentalModel()
    for index, valence in enumerate((0.3, 0.3, -0.3)):
        model.encounter_concept("риск", f"ctx_{index}", "что-то о риске", valence)

    assert model.can_answer_about("риск") is False


# ============================================================
# 5. Одна формула на всю систему
# ============================================================


def test_definition_synthesis_does_not_override_confidence():
    """Синтез определения пересчитывает уверенность, а не подменяет её.

    Раньше здесь была своя формула (0.3 + (1−дисперсия)·0.5 + встречи·0.05),
    и она перетирала значение из add_experience: два источника истины
    давали несовместимые числа.
    """
    model = MentalModel()
    model.encounter_concept("тема", "ctx_1", "первый результат", 0.3)
    node = model.concepts["тема"]
    expected = node.confidence

    model.encounter_concept("тема", "ctx_2", "второй результат", 0.0)

    # Нулевая встреча не добавляет свидетельств, поэтому уверенность
    # остаётся прежней — её не «поднимает» факт появления определения.
    assert node.confidence == pytest.approx(expected)


def test_recompute_matches_add_experience():
    node = _node(0.3, 0.5)
    manual = node.confidence
    node.recompute_confidence()

    assert node.confidence == pytest.approx(manual)
