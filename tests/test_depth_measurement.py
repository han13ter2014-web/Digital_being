"""Замер глубины не должен путать повторение темы с новым знанием."""

import pytest

from src.cognition.mental_models import MentalModel
from tools.manual.depth_sweep_summary import parse_report


def test_neutral_repetition_and_sleep_do_not_make_knowledge():
    model = MentalModel()
    for index in range(8):
        node = model.encounter_concept(
            "энтропия", f"вопрос_{index}", "Неизвестная концепция: энтропия", 0.0
        )
        model.consolidate()

    assert len(node.experiences) == 8
    assert node.definition_hypothesis == ""
    assert node.evidence()[0] == 0
    assert node.confidence == pytest.approx(0.1)
    assert not model.can_answer_about("энтропия")


def test_summary_uses_final_sample_not_birth_and_exact_share():
    report = """Доля углубления: 0.35
Зерно случайности: 1
  цикл 0: концепций 26 (своих 0)
  цикл 500: концепций 85 (своих 59)
Итог:
  отвечаемых: 0 → 22 (0% → 37%)
  встречались дважды и более: 59 (100% своих)
  встреч на концепцию: 4.64
  средняя уверенность: 0.000 → 0.439
"""
    result = parse_report(report)

    assert result["own"] == 59
    assert result["answerable"] == 22
    assert result["deep"] == 59
    assert result["encounters"] == 4.64
    assert result["confidence"] == 0.439


def test_missing_measurement_is_error_not_zero():
    with pytest.raises(ValueError):
        parse_report("Итог:\nНеполный отчёт")
