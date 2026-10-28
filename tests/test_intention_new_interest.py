"""Новое возвращение к забытой теме — отдельное намерение и причина."""

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.cognition.intention_waiting import resolve_wait, start_new_intention
from src.core.subsystem_base import PluginRegistry


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_new_interest_survives_profile_restart(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "NewInterestLife", new=True)
        first.ask_user("память", source="self", max_explorations=2)
        # Создаём waiting через существующий API истории; это не auto-interest.
        from src.cognition.intention_history import begin_intention, finish_intention
        entry = begin_intention(first, {"action": "explore", "params": {"topic": "память", "reason": "проверить"}})
        finish_intention(entry)
        from src.cognition.intention_evidence import finish_evidence_goal
        finish_evidence_goal(first, entry)
        first.cycle_count += 1
        from src.cognition.intention_waiting import remember_wait
        remember_wait(first, entry)
        resolve_wait(first, "explore", "память", kind="forgotten", reason="отпустить")
        new = start_new_intention(first, "explore", "память", reason="новый интерес")
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, _ = create_agent(env, "NewInterestLife")
        entries = [entry for entry in second._intention_history if entry["id"] == new["id"]]
        assert len(entries) == 1
        assert entries[0]["new_interest"] is True
        assert entries[0]["continuation_of"] is None
    finally:
        PluginRegistry.reset_global()
