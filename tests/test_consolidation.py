"""Консолидация во сне: связи крепнут, опыт становится формулировкой.

Смысл: во время работы агент только записывает опыт. Превращать записи в
понимание нужно отдельно, иначе «сон» — ритуал, а не работа. Способности
при этом не меняются: меняется только то, что успело закрепиться.

До этой правки консолидации не было вовсе, а связи не могли укрепиться
принципиально: ``_update_associations`` сравнивал контексты встреч, но они
уникальны по построению (``гипотеза_цикл_12``), поэтому пересечение было
всегда пустым и вес связи оставался 0.1 навсегда.
"""

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
    model.encounter_concept("энтропия", "гипотеза_цикл_1", "мера беспорядка", 0.5)
    model.encounter_concept("энтропия", "гипотеза_цикл_2", "растёт в замкнутой системе", 0.5)
    node = model.concepts["энтропия"]
    # Опыт есть, а формулировки ещё нет — ровно то, что делает сон.
    node.definition_hypothesis = ""
    assert len(node.experiences) >= 2

    report = model.consolidate()

    assert report["definitions"] >= 1
    assert len(node.definition_hypothesis) > 10
    assert "энтропия" in node.definition_hypothesis


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
    model.encounter_concept("энтропия", "ctx2", "мера беспорядка", 0.5)
    node.definition_hypothesis = "По опыту (2 встреч): 'энтропия' — мера беспорядка"
    node.connections["порядок"] = 0.6
    node.connections["хаос"] = 0.5

    report = model.consolidate()

    assert report["refined"] >= 1
    assert "порядок" in node.definition_hypothesis
    assert "хаос" in node.definition_hypothesis


def test_refinement_needs_evidence():
    """Без подкреплённых связей формулировка не трогается.

    Иначе сон «придумывал» бы связи, которых никто не наблюдал.
    """
    model = MentalModel()
    for name in ("энтропия", "порядок", "хаос"):
        model.encounter_concept(name, f"ctx_{name}", "встреча", 0.0)
    node = model.concepts["энтропия"]
    model.encounter_concept("энтропия", "ctx2", "мера беспорядка", 0.5)
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


def test_consolidation_stabilizes_consistent_confidence():
    model = MentalModel()
    for cycle in range(3):
        model.encounter_concept(
            "градиент", f"гипотеза_цикл_{cycle}", "направление роста", 0.6
        )
    node = model.concepts["градиент"]
    node.confidence = 0.4

    report = model.consolidate(confidence_bonus=0.05)

    assert report["confidence"] >= 1
    assert node.confidence > 0.4


def test_inconsistent_experience_is_not_stabilized():
    model = MentalModel()
    model.encounter_concept("риск", "гипотеза_цикл_1", "плохо", 0.8)
    model.encounter_concept("риск", "гипотеза_цикл_2", "плохо", 0.8)
    model.encounter_concept("риск", "гипотеза_цикл_3", "хорошо", -0.8)
    node = model.concepts["риск"]
    node.confidence = 0.4

    report = model.consolidate(confidence_bonus=0.05)

    assert report["confidence"] == 0
    assert node.confidence == 0.4


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