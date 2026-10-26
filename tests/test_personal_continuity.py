"""Текущие ценности/отношения/журнал переживают обычный запуск без новых актов."""

from copy import deepcopy

import pytest

from config.simulation_config import SIM_CONFIG
from config.will_config import WILL_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.core.personal_continuity import capture_personal_state
from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent
from src.core.subsystem_base import PluginRegistry


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_values_relationships_and_will_survive_startup(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "PersonalLife", new=True)
        first.cycle_count = 100
        first.add_value("Забота", "значимый опыт")
        first.value_evolution.remove_value("Знание", "пересмотр", cycle=150)
        first.cycle_count = 150
        first.attachment.record_interaction("user", was_helpful=True)
        for _ in range(WILL_CONFIG.MAX_REFUSALS_PER_100_CYCLES):
            first.defend_refusal("тема", "не хочу")
        assert not first.right_to_refuse.can_refuse(150)
        original = capture_personal_state(first)
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, report = create_agent(env, "PersonalLife")
        assert report["source"] == "checkpoint"
        assert capture_personal_state(second) == original
        assert "Забота" in second.value_evolution.current_values
        assert "Знание" not in second.value_evolution.current_values
        assert not second.value_evolution.can_evolve(150)
        assert second.value_evolution.can_evolve(200)
        assert not second.right_to_refuse.can_refuse(150)
        assert second.right_to_refuse.can_refuse(251)
        assert second.value_evolution.registry is second.will_registry
        assert second.right_to_refuse.registry is second.will_registry
        assert second.proactive_communication.attachment is second.attachment
        second.cycle_count = 200
        second.add_value("Терпение", "продолжение")
        assert second.will_registry.get_stats()["by_type"]["value_changes"] == 3
    finally:
        PluginRegistry.reset_global()


def test_empty_values_are_not_replaced_with_defaults(tmp_path, monkeypatch):
    from src.core.agent import DigitalBeing

    first = DigitalBeing(name="EmptyValues")
    first.value_evolution.current_values = []
    state = build_state_from_agent(first)
    second = DigitalBeing(name="EmptyValues")
    apply_state_to_agent(second, state)
    assert second.value_evolution.current_values == []


def test_invalid_personal_state_does_not_partially_change_agent():
    from src.core.agent import DigitalBeing

    agent = DigitalBeing(name="InvalidPersonal")
    state = build_state_from_agent(agent)
    before = deepcopy(capture_personal_state(agent))
    state["personal_state"]["attachments"] = {"user": {"name": "user", "kind": "user", "trust": float("nan")}}
    with pytest.raises(ValueError, match="personal_state"):
        apply_state_to_agent(agent, state)
    assert capture_personal_state(agent) == before
