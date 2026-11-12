"""Regression tests for the public ImmuneSystem API."""

import pytest

from src.emotion.immune_system import ImmuneSystem


def test_identify_threat_handles_neutral_context() -> None:
    immune = ImmuneSystem()

    result = immune.identify_threat("спокойный нейтральный контекст")

    assert result["is_threat"] is False
    assert result["threat_type"] is None
    assert result["antibody_strength"] is None
    assert immune.pathogens == []


def test_identify_threat_preserves_threat_reporting() -> None:
    immune = ImmuneSystem()

    result = immune.identify_threat(
        "токсичный вредный использует эксплуатирует манипулирует шантаж"
    )

    assert result["is_threat"] is True
    assert result["threat_type"] == "эксплуатация"
    assert result["antibody_strength"] == pytest.approx(0.21)
    assert len(immune.pathogens) == 1
