"""Синтез: связи из свидетельств, а не «нет связанных концепций».

Регрессия: ``_act_synthesize`` вызывал ``find_related_concepts(target,
max_depth=2)``, а параметр называется ``max_distance``. TypeError
глотался ``except Exception``, список связей всегда был пуст, и действие
всегда отвечало «для 'X' нет связанных концепций» — при этом считалось
выполненным.
"""

import pytest

from src.core.agent import DigitalBeing


@pytest.fixture()
def agent():
    a = DigitalBeing(name="SynthAgent")
    searcher = getattr(a, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)
    return a


def test_synthesis_uses_strong_links(agent):
    models = agent.mental_models
    # Чистый граф: у рождённого агента уже есть родовые связи, и они
    # сделали бы проверку бессмысленной.
    models.concepts.clear()
    models.encounter_concept("время", "ctx", "длительность", 0.4)
    models.encounter_concept("память", "ctx", "хранение", 0.4)
    models.concepts["время"].connections["память"] = 0.5
    models.concepts["память"].connections["время"] = 0.5

    agent._pick_exploration_target = lambda: "время"
    result = agent.act("synthesize")

    assert "память" in result
    assert "нет связанных концепций" not in result


def test_synthesis_reports_no_links_honestly(agent):
    models = agent.mental_models
    models.concepts.clear()
    models.encounter_concept("одиночество", "ctx", "одна встреча", 0.4)
    models.concepts["одиночество"].connections.clear()

    agent._pick_exploration_target = lambda: "одиночество"
    result = agent.act("synthesize")

    assert "нет связанных концепций" in result


def test_synthesis_prefers_evidence_over_distant_hops(agent):
    """Прямая подкреплённая связь важнее дальней по слабым рёбрам."""
    models = agent.mental_models
    models.concepts.clear()
    for name in ("время", "память", "случайность"):
        models.encounter_concept(name, "ctx", "встреча", 0.4)
    # Прямая сильная связь.
    models.concepts["время"].connections["память"] = 0.6
    models.concepts["память"].connections["время"] = 0.6
    # Дальняя слабая: время -> случайность.
    models.concepts["время"].connections["случайность"] = 0.1
    models.concepts["случайность"].connections["время"] = 0.1

    agent._pick_exploration_target = lambda: "время"
    result = agent.act("synthesize")

    assert "память" in result
    assert "случайность" not in result
