"""Дело продолжается после файлового запуска и завершается своим результатом."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from config.simulation_config import SIM_CONFIG, LR_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.cognition.activity_goals import attach_activity, activity_candidate
from src.core.subsystem_base import PluginRegistry


@pytest.mark.parametrize("backend", ["json", "sqlite"])
@pytest.mark.parametrize("action", ["play", "create_draft"])
def test_activity_completes_after_profile_restart(tmp_path, monkeypatch, backend, action):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    monkeypatch.setattr(LR_CONFIG, "WEB_SEARCH_ENABLED", False)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "ActivityLife", new=True)
        identifier = first.set_goal("Своё занятие", activate=True)
        attach_activity(first, identifier, {"source": "self", "need": "play", "action_hint": action})
        if action == "play":
            # Настоящий первый ход, но партия пока не закончена.
            candidate = activity_candidate(first)
            with patch.object(first.decision_arbitrator, "choose_action", return_value={**candidate, "verdict": "proceed"}):
                first.autonomous_tick()
            assert first.active_goal["activity"]["steps"] == 1
        original = deepcopy(next(g for g in first.goals if g["id"] == identifier))
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, report = create_agent(env, "ActivityLife")
        assert report["source"] == "checkpoint"
        goal = next(g for g in second.goals if g["id"] == identifier)
        assert goal == original
        assert second.active_goal is goal
        before_memory = second.mental_models.to_storage_dict()
        count, streak = second.completed_goals, second.success_streak
        for _ in range(5):
            candidate = activity_candidate(second)
            if candidate is None:
                break
            with patch.object(second.decision_arbitrator, "choose_action", return_value={**candidate, "verdict": "proceed"}):
                second.autonomous_tick()
            second.cycle_count += 1
            if goal["status"] == "completed":
                break
        assert goal["status"] == "completed"
        assert second.completed_goals == count + 1
        assert second.success_streak == streak
        assert second.mental_models.to_storage_dict() == before_memory
        second.save_state(force=True)
        PluginRegistry.reset_global()
        third, _ = create_agent(env, "ActivityLife")
        assert next(g for g in third.goals if g["id"] == identifier)["status"] == "completed"
        assert third.completed_goals == count + 1
    finally:
        PluginRegistry.reset_global()
