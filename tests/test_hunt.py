"""Тесты «Охоты-1»: кулдаун промаха и след добычи в _act_web_search.

Сеть не нужна: WebSearcher подменён заглушкой, агент — лёгкий fake
с привязанными настоящими методами DigitalBeing (как в
tests/test_emotional_state.py).
"""

import unittest
from types import SimpleNamespace

from src.core.agent import DigitalBeing


class _FakeMentalModels:
    """Минимальная замена MentalModel: фиксирует encounter_concept."""

    def __init__(self):
        self.concepts = {}
        self.encounters = []

    def encounter_concept(self, concept_name, context, outcome, valence=0.0):
        self.encounters.append(
            {
                "concept_name": concept_name,
                "context": context,
                "outcome": outcome,
                "valence": valence,
            }
        )
        node = SimpleNamespace(confidence=0.1)
        self.concepts[concept_name] = node
        return node


class _FakeAgent(SimpleNamespace):
    """SimpleNamespace + настоящие методы DigitalBeing как атрибуты класса."""

    _META_TOPIC_WORDS = DigitalBeing._META_TOPIC_WORDS

    _is_learnable = DigitalBeing._is_learnable
    _is_meta_topic = DigitalBeing._is_meta_topic
    _record_will = DigitalBeing._record_will
    _act_web_search = DigitalBeing._act_web_search


def _make_searcher(result):
    """Заглушка WebSearcher: отдаёт заранее заданный результат, считает вызовы."""
    searcher = SimpleNamespace(is_enabled=True, calls=[])
    searcher.search = lambda query: (searcher.calls.append(query), result)[1]
    return searcher


def _make_agent(searcher, target="энтелехия", cycle=10):
    agent = _FakeAgent(
        web_searcher=searcher,
        cycle_count=cycle,
        knowledge_base={},
        _known_definitions={},
        _hunt_misses={},
        mental_models=_FakeMentalModels(),
        will_registry=None,
    )
    agent._pick_exploration_target = lambda: target
    agent._save_knowledge_base = lambda: None
    return agent


_FOUND_SOUL = {
    "found": True,
    "title": "Душа",
    "extract": "Душа — нематериальная сущность живого существа, "
    "описываемая в философии и религии.",
    "url": "https://ru.wikipedia.org/wiki/Душа",
    "lang": "ru",
    "source": "wikipedia:search",
    "error": None,
}


class HuntCooldownTests(unittest.TestCase):
    """Промах оставляет след: повторная охота по теме — только после кулдауна."""

    def test_miss_cooldown_blocks_repeat_hunt(self):
        searcher = _make_searcher({"found": False, "error": "no_pages"})
        agent = _make_agent(searcher, cycle=10)

        first = agent._act_web_search()
        self.assertIn("ничего", first["text"])
        self.assertEqual(len(searcher.calls), 1)
        self.assertEqual(agent._hunt_misses.get("энтелехия"), 10)

        # След свеж — повторный заход не доходит до сети.
        second = agent._act_web_search()
        self.assertIn("след ещё свеж", second["text"])
        self.assertEqual(len(searcher.calls), 1)

        # Кулдаун истёк — охота разрешена снова.
        agent.cycle_count = 10 + 200
        third = agent._act_web_search()
        self.assertIn("ничего", third["text"])
        self.assertEqual(len(searcher.calls), 2)
        self.assertEqual(agent._hunt_misses.get("энтелехия"), 210)

    def test_rejected_result_counts_as_miss(self):
        # «Нашёл, но слабое» — тоже промах: добыча оказалась несъедобной.
        searcher = _make_searcher({"found": True, "title": "X", "extract": ""})
        agent = _make_agent(searcher, cycle=5)

        result = agent._act_web_search()
        self.assertIn("без содержания", result["text"])
        self.assertEqual(agent._hunt_misses.get("энтелехия"), 5)

    def test_success_clears_miss_trail(self):
        searcher = _make_searcher(dict(_FOUND_SOUL, title="Энтелехия"))
        agent = _make_agent(searcher, cycle=500)
        agent._hunt_misses["энтелехия"] = 100  # старый, остывший след

        result = agent._act_web_search()
        self.assertIn("нашла в сети", result["text"])
        self.assertNotIn("энтелехия", agent._hunt_misses)
        self.assertIn("энтелехия", agent.knowledge_base)


class HuntTrailTests(unittest.TestCase):
    """След добычи: соседняя найденная концепция становится новой темой."""

    def test_trail_registers_neighbor_concept(self):
        searcher = _make_searcher(dict(_FOUND_SOUL))  # title «Душа» ≠ target
        agent = _make_agent(searcher, cycle=42)

        result = agent._act_web_search()
        self.assertIn("по следам — новая тема 'душа'", result["text"])
        self.assertEqual(len(agent.mental_models.encounters), 1)
        encounter = agent.mental_models.encounters[0]
        self.assertEqual(encounter["concept_name"], "душа")
        self.assertEqual(encounter["valence"], 0.0)
        self.assertIn("энтелехия", encounter["outcome"])

    def test_no_trail_when_title_matches_target(self):
        searcher = _make_searcher(dict(_FOUND_SOUL, title="Энтелехия"))
        agent = _make_agent(searcher)

        result = agent._act_web_search()
        self.assertNotIn("по следам", result["text"])
        self.assertEqual(agent.mental_models.encounters, [])

    def test_no_trail_for_already_known_concept(self):
        searcher = _make_searcher(dict(_FOUND_SOUL))
        agent = _make_agent(searcher)
        agent.mental_models.concepts["душа"] = SimpleNamespace(confidence=0.8)

        result = agent._act_web_search()
        self.assertNotIn("по следам", result["text"])
        self.assertEqual(agent.mental_models.encounters, [])


if __name__ == "__main__":
    unittest.main()
