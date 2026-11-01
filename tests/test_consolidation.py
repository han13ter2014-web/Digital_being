"""Консолидация во сне: связи крепнут, опыт становится формулировкой.

Смысл: во время работы агент только записывает опыт. Превращать записи в
понимание нужно отдельно, иначе «сон» — ритуал, а не работа. Способности
при этом не меняются: меняется только то, что успело закрепиться.

До этой правки консолидации не было вовсе, а связи не могли укрепиться
принципиально: ``_update_associations`` сравнивал контексты встреч, но они
уникальны по построению (``гипотеза_цикл_12``), поэтому пересечение было
всегда пустым и вес связи оставался 0.1 навсегда.
"""

import re

import pytest

from src.core.agent import DigitalBeing
from src.cognition.mental_models import MentalModel, _mentions


@pytest.fixture()
def agent():
    a = DigitalBeing(name="SleepAgent")
    searcher = getattr(a, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)  # тесты не ходят в сеть
    return a


def _model_with_link() -> MentalModel:
    model = MentalModel()
    for name in ("время", "память"):
        model.encounter_concept(name, f"контекст_{name}", "первая встреча", 0.0)
    # Определение «времени» упоминает «память» — это и есть наблюдённая
    # связь, которую сон должен закрепить.
    model.concepts["время"].definition_hypothesis = (
        "По опыту: 'время' связано с 'память'"
    )
    return model


# ============================================================
# 1. Связи
# ============================================================


def test_consolidation_strengthens_links_from_definition():
    model = _model_with_link()
    before = model.concepts["время"].connections.get("память", 0.0)

    report = model.consolidate(link_delta=0.1)

    after = model.concepts["время"].connections.get("память", 0.0)
    assert after > before
    assert report["links"] >= 1
    # Связь двусторонняя: упоминание в одну сторону — отношение между двумя.
    assert model.concepts["память"].connections.get("время", 0.0) >= after


def test_consolidation_creates_link_when_absent():
    """Формулировка — уже свидетельство: связь создаётся, а не только крепнет."""
    model = _model_with_link()
    model.concepts["время"].connections.pop("память", None)
    model.concepts["память"].connections.pop("время", None)

    report = model.consolidate(link_delta=0.05)

    assert report["links"] >= 1
    assert model.concepts["время"].connections["память"] > 0.2


def test_consolidation_does_not_link_unrelated_concepts():
    model = MentalModel()
    for name in ("время", "память"):
        model.encounter_concept(name, f"контекст_{name}", "встреча", 0.0)
    model.concepts["время"].definition_hypothesis = "По опыту: 'время' — длительность"

    report = model.consolidate(link_delta=0.1)

    assert report["links"] == 0


def test_mentions_respects_word_boundaries():
    """«время» не должно находиться внутри «временной»."""
    assert _mentions("связь со временем", "время") is False
    assert _mentions("это время пришло", "время") is True
    assert _mentions("время,память", "время") is True


def test_consolidation_link_is_bounded():
    model = MentalModel()
    for i in range(30):
        name = f"концепция{i:02d}"
        model.encounter_concept(name, f"ctx_{i}", "встреча", 0.0)
    # Каждая концепция упоминает все остальные — 870 потенциальных связей.
    for name, node in model.concepts.items():
        others = [other for other in model.concepts if other != name][:10]
        node.definition_hypothesis = "связано с " + ", ".join(others)

    report = model.consolidate(link_delta=0.1, max_links=25)

    assert report["links"] <= 25


# ============================================================
# 2. Формулировки
# ============================================================


def test_consolidation_forms_definition_from_experience():
    model = MentalModel()
    model.encounter_concept("энтропия", "гипотеза_цикл_1", "мера беспорядка", 0.5,
                            evidence_kind="hypothesis", source="self:hypothesis")
    model.encounter_concept("энтропия", "гипотеза_цикл_2", "растёт в замкнутой системе", 0.5,
                            evidence_kind="hypothesis", source="self:hypothesis")
    node = model.concepts["энтропия"]
    # Опыт есть, а формулировки ещё нет — ровно то, что делает сон.
    node.definition_hypothesis = ""
    assert len(node.experiences) >= 2

    report = model.consolidate()

    assert report["definitions"] >= 1
    assert len(node.definition_hypothesis) > 10
    assert "энтропия" in node.definition_hypothesis
    assert node.confidence == pytest.approx(0.1)
    assert not model.can_answer_about("энтропия")


def test_consolidation_skips_single_encounter():
    """Одной встречи мало для формулировки — иначе это догадка, не знание."""
    model = MentalModel()
    model.encounter_concept("фрактал", "гипотеза_цикл_1", "самоподобие", 0.5)
    node = model.concepts["фрактал"]
    node.definition_hypothesis = ""

    model.consolidate()

    assert node.definition_hypothesis == ""


def test_consolidation_refines_definition_from_links():
    """Формулировка переписывается через окрепшие связи, а не сырой опыт."""
    model = MentalModel()
    for name in ("энтропия", "порядок", "хаос"):
        model.encounter_concept(name, f"ctx_{name}", "встреча", 0.0)
    node = model.concepts["энтропия"]
    model.encounter_concept(
        "энтропия", "ctx2", "мера беспорядка", 0.5,
        evidence_strength=0.5, evidence_kind="observation", source="ctx2",
    )
    node.definition_hypothesis = "По опыту (2 встреч): 'энтропия' — мера беспорядка"
    node.connections["порядок"] = 0.6
    node.connections["хаос"] = 0.5

    report = model.consolidate()

    assert report["refined"] >= 1
    assert "порядок" in node.definition_hypothesis
    assert "хаос" in node.definition_hypothesis


def test_refinement_excludes_reflexive_concepts():
    """«'X' связано с я, ты» — шум общего контекста рождения, не знание.

    На живом стенде это дало формулировку «'следствие' связано с
    причина, я, ты»: рефлексивные примитивы получили связи с темой
    только за общую встречу при рождении, сон их усилил, и они
    затесались в определение наравне с настоящим соседом «причина».
    """
    model = MentalModel()
    for name in ("следствие", "причина", "время", "я", "ты"):
        model.encounter_concept(name, f"ctx_{name}", "встреча", 0.0)
    node = model.concepts["следствие"]
    model.encounter_concept(
        "следствие", "ctx2", "результат причины", 0.5,
        evidence_strength=0.5, evidence_kind="observation", source="ctx2",
    )
    node.definition_hypothesis = "По опыту (2 встреч): 'следствие' — результат причины"
    node.connections["причина"] = 0.6
    node.connections["время"] = 0.5
    node.connections["я"] = 0.9
    node.connections["ты"] = 0.5

    report = model.consolidate()

    assert report["refined"] >= 1
    words = set(re.findall(r"\w+", node.definition_hypothesis.lower()))
    assert {"причина", "время"} <= words
    assert not words & {"я", "ты", "мы"}


def test_refinement_lists_links_after_colon():
    """Список соседей стоит после двоеточия: «с» не управляет падежом."""

    model = MentalModel()
    for name in ("время", "память"):
        model.encounter_concept(name, f"ctx_{name}", "встреча", 0.0)
    node = model.concepts["время"]
    model.encounter_concept(
        "время", "ctx2", "идёт вперёд", 0.5,
        evidence_strength=0.5, evidence_kind="observation", source="ctx2",
    )
    node.definition_hypothesis = "По опыту (2 встреч): 'время' — идёт вперёд"
    node.connections["память"] = 0.6
    node.connections["порядок"] = 0.5
    model.encounter_concept("порядок", "ctx_порядок", "встреча", 0.0)

    model.consolidate()

    assert "связано с: " in node.definition_hypothesis


def test_synthesized_definition_lists_outcomes_after_colon():
    """Формулировка из сырых результатов тоже перечисляет после двоеточия."""
    model = MentalModel()
    model.encounter_concept("память", "встреча", "запомнила шаг", 0.5,
                            evidence_kind="hypothesis", source="self:hypothesis")
    model.encounter_concept("память", "встреча", "воспроизвела шаг", 0.5,
                            evidence_kind="hypothesis", source="self:hypothesis")
    node = model.concepts["память"]
    node.definition_hypothesis = ""

    model.consolidate()

    assert "связано с:" in node.definition_hypothesis


def test_refinement_needs_evidence():
    """Без подкреплённых связей формулировка не трогается.

    Иначе сон «придумывал» бы связи, которых никто не наблюдал.
    """
    model = MentalModel()
    for name in ("энтропия", "порядок", "хаос"):
        model.encounter_concept(name, f"ctx_{name}", "встреча", 0.0)
    node = model.concepts["энтропия"]
    model.encounter_concept(
        "энтропия", "ctx2", "мера беспорядка", 0.5,
        evidence_strength=0.5, evidence_kind="observation", source="ctx2",
    )
    original = "По опыту (2 встреч): 'энтропия' — мера беспорядка"
    node.definition_hypothesis = original
    node.connections["порядок"] = 0.1
    node.connections["хаос"] = 0.1

    report = model.consolidate()

    assert report["refined"] == 0
    assert node.definition_hypothesis == original


# ============================================================
# 3. Уверенность
# ============================================================


def test_consolidation_recomputes_consistent_confidence_without_bonus():
    model = MentalModel()
    for cycle in range(3):
        context = f"наблюдение_цикл_{cycle}"
        model.encounter_concept(
            "градиент", context, "направление роста", 0.6,
            evidence_strength=0.6, evidence_kind="observation", source=context,
        )
    node = model.concepts["градиент"]
    expected = node.confidence
    node.confidence = 0.4

    model.consolidate()

    assert node.confidence == pytest.approx(expected)
    model.consolidate()
    assert node.confidence == pytest.approx(expected)


def test_inconsistent_experience_is_not_stabilized():
    model = MentalModel()
    for cycle, valence in enumerate((0.8, 0.8, -0.8)):
        context = f"наблюдение_цикл_{cycle}"
        model.encounter_concept(
            "риск", context, "плохо" if valence > 0 else "хорошо", valence,
            evidence_strength=abs(valence), evidence_kind="observation",
            source=context, evidence_direction=-1 if valence < 0 else 1,
        )
    node = model.concepts["риск"]
    expected = node.confidence
    assert not model.can_answer_about("риск")
    node.confidence = 0.4

    model.consolidate()

    assert node.confidence == pytest.approx(expected)
    model.consolidate()
    assert node.confidence == pytest.approx(expected)
    assert not model.can_answer_about("риск")


# ============================================================
# 4. Сон как условие, а не ритуал
# ============================================================


def test_work_alone_does_not_consolidate(agent):
    for _ in range(30):
        agent.energy = float(agent.energy_subsystem.max_energy)
        agent.act("explore")

    assert agent._consolidation_count == 0
    assert agent._last_consolidation == {}


def test_new_concept_does_not_link_to_everything():
    """Связи появляются по свидетельству, а не «на всякий случай».

    Раньше новая концепция получала связь 0.1 с КАЖДОЙ существующей:
    на 80 концепциях — 6320 рёбер шума, и обход графа возвращал всё
    подряд. Синтез после этого «находил связи» между случайными темами.
    """
    model = MentalModel()
    for i in range(20):
        model.encounter_concept(f"тема{i:02d}", f"ctx_{i}", "встреча", 0.0)

    node = model.concepts["тема19"]
    assert node.connections == {}


def test_mention_in_outcome_creates_weak_link():
    """Одно упоминание — наблюдение, а не знание: вес ниже порога 0.3."""
    model = MentalModel()
    model.encounter_concept("время", "ctx3", "длительность", 0.0)
    model.encounter_concept("память", "ctx", "хранение следов", 0.0)
    model.encounter_concept("память", "ctx2", "связана с время", 0.0)

    node = model.concepts["память"]
    weight = node.connections.get("время", 0.0)
    assert 0.0 < weight < 0.3
    # Связь двусторонняя.
    assert model.concepts["время"].connections.get("память", 0.0) == weight


def test_sleep_turns_observation_into_link():
    """Сон доводит наблюдённое отношение до устойчивой связи."""
    model = MentalModel()
    model.encounter_concept("время", "ctx3", "длительность", 0.0)
    model.encounter_concept("память", "ctx", "хранение следов", 0.0)
    model.encounter_concept("память", "ctx2", "связана с время", 0.0)
    model.concepts["память"].definition_hypothesis = (
        "По опыту: 'память' связана с время"
    )
    before = model.concepts["память"].connections["время"]
    assert before < 0.3

    for _ in range(4):
        model.consolidate(link_delta=0.05)

    assert model.concepts["память"].connections["время"] >= 0.3


def test_deep_rest_accumulates_sleep_and_consolidates(agent):
    from config.simulation_config import LR_CONFIG

    threshold = float(LR_CONFIG.CONSOLIDATION_SLEEP_UNITS)
    agent._sleep_units = threshold - 1.0

    agent.energy = 50.0
    agent.act("deep_rest")

    assert agent._consolidation_count == 1
    assert agent._last_consolidation.get("scanned", 0) >= 0


def test_shallow_rest_counts_half(agent):
    from config.simulation_config import LR_CONFIG

    agent._sleep_units = 0.0
    agent.energy = 50.0
    agent.act("rest")

    assert agent._sleep_units == pytest.approx(0.5)
    assert float(LR_CONFIG.CONSOLIDATION_SLEEP_UNITS) > 0.5


def test_rest_reports_consolidation_in_action_text(agent):
    from config.simulation_config import LR_CONFIG

    agent._sleep_units = float(LR_CONFIG.CONSOLIDATION_SLEEP_UNITS) - 1.0
    agent.energy = 50.0

    result = agent.act("deep_rest")

    assert "осмыслил накопленное" in result


def test_consolidation_state_survives_checkpoint(agent):
    from src.core.checkpoint_serializer import (
        apply_state_to_agent,
        build_state_from_agent,
    )

    agent._consolidation_count = 7
    agent._sleep_units = 1.5

    snapshot = build_state_from_agent(agent)

    reborn = DigitalBeing(name="SleepAgentReborn")
    try:
        reborn.web_searcher.toggle(False)
        apply_state_to_agent(reborn, snapshot)
        assert reborn._consolidation_count == 7
        assert reborn._sleep_units == pytest.approx(1.5)
    finally:
        reborn.plugin_registry.teardown_all()


def test_consolidation_is_visible_in_state(agent):
    agent._consolidation_count = 3
    agent._sleep_units = 0.5
    agent._last_consolidation = {"links": 4, "definitions": 1}

    state = agent.get_full_state()["consolidation"]

    assert state["count"] == 3
    assert state["pending_sleep_units"] == pytest.approx(0.5)
    assert state["last"]["links"] == 4