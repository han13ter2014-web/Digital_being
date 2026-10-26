"""Повторное чтение состояния не является ещё одним прожитым событием."""

from unittest.mock import patch

from src.core.subsystems.mortality_awareness import MortalityAwareness


def test_status_does_not_tick_or_modify_state():
    mortality = MortalityAwareness(expected_lifespan=100)
    mortality.tick(97)
    before = dict(mortality.__dict__)
    with patch.object(mortality, "tick", side_effect=AssertionError("status must be read only")):
        assert mortality.get_status()["current_phase"] == "finale"
    assert mortality.__dict__ == before


def test_same_cycle_reuses_calculation_but_not_mutable_result():
    mortality = MortalityAwareness(expected_lifespan=100)
    first = mortality.tick(97)
    first["phase"] = "modified"
    assert mortality.tick(97)["phase"] == "finale"
    mortality.expected_lifespan = 1000
    assert mortality.tick(97)["phase"] == "childhood"
