"""Переживание, собственная версия и подтверждение — разные состояния."""

import pytest

from src.cognition.mental_models import ConceptNode, MentalModel
from src.core.agent import DigitalBeing


def test_unpleasant_observation_can_support_knowledge():
    node = ConceptNode("ошибка")
    node.add_experience("действие", "Результат не совпал с ожидаемым", -0.9,
                        evidence_strength=0.8, evidence_kind="observation", source="action:1")
    assert node.confidence > 0.4
    assert node.experiences[0]["valence"] == -0.9


def test_pleasant_repeated_hypothesis_does_not_become_fact():
    model = MentalModel()
    for index in range(6):
        node = model.encounter_concept("тема", f"мысль_{index}", "Возможно, это связано с памятью", 0.9,
                                       evidence_kind="hypothesis", source="self:hypothesis")
        model.consolidate()
    assert node.definition_hypothesis
    assert node.confidence == pytest.approx(0.1)
    assert not model.can_answer_about("тема")


def test_legacy_emotion_is_not_migrated_into_evidence():
    node = ConceptNode.from_dict({
        "name": "память", "confidence": 0.9,
        "definition_hypothesis": "Старая версия определения",
        "experiences": [{"context": "раньше", "outcome": "неясно", "valence": 0.9}],
    })
    restored = ConceptNode.from_dict(node.to_storage_dict())
    assert restored.confidence == pytest.approx(0.1)
    assert restored.legacy_confidence == pytest.approx(0.9)
    assert restored.experiences[0]["valence"] == 0.9
    assert restored.experiences[0]["evidence_kind"] == "legacy"


def test_same_source_is_not_independent_confirmation():
    node = ConceptNode("память")
    for index in range(10):
        node.add_experience(f"чтение_{index}", "Сохранение опыта", evidence_strength=0.3,
                            evidence_kind="testimony", source="book:one")
    assert node.evidence()[0] == pytest.approx(0.3)
    assert node.confidence == pytest.approx(0.3)


def test_new_evidence_changes_exploration_without_changing_desires():
    model = MentalModel()
    node = model.encounter_concept("память", "мысль", "Возможно, это сохранение опыта",
                                   evidence_kind="hypothesis", source="self:hypothesis")
    agent = DigitalBeing.__new__(DigitalBeing)
    agent._exploration_history = []
    agent.innate_values = {"любопытство": 0.7}
    assert agent._pick_shallow_concept(model.concepts) == "память"
    model.encounter_concept("память", "проверка", "После перезапуска запись сохранилась", -0.2,
                            evidence_strength=0.8, evidence_kind="observation", source="action:restart:1")
    assert node.confidence > 0.4
    assert agent._pick_shallow_concept(model.concepts) is None
    assert agent.innate_values == {"любопытство": 0.7}


def test_uncertain_topic_does_not_repeat_within_exploration_round():
    node = ConceptNode("память")
    node.add_experience("стимул", "неизвестно")
    agent = DigitalBeing.__new__(DigitalBeing)
    agent._exploration_history = ["память"]
    assert agent._pick_shallow_concept({"память": node}) is None


@pytest.mark.parametrize("kwargs", [
    {"evidence_strength": float("nan")},
    {"evidence_strength": 0.7, "evidence_kind": "hypothesis", "source": "self"},
    {"evidence_strength": 0.7, "evidence_kind": "observation"},
])
def test_invalid_evidence_is_not_recorded(kwargs):
    node = ConceptNode("тема")
    with pytest.raises(ValueError):
        node.add_experience("контекст", "результат", **kwargs)
    assert not node.experiences
