"""История попыток проходит файловый checkpoint и обычный create_agent."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from config.simulation_config import SIM_CONFIG, LR_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.cognition.intention_history import begin_intention
from src.core.subsystem_base import PluginRegistry


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_intention_history_survives_normal_restart(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    monkeypatch.setattr(LR_CONFIG, "WEB_SEARCH_ENABLED", False)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "IntentionLife", new=True)
        first.energy = 20
        first.cycle_count = 41
        selected = {"action": "rest", "source": "test", "verdict": "proceed",
                    "params": {"reason": "восстановиться"}}
        with patch.object(first.decision_arbitrator, "choose_action", return_value=selected):
            report = first.autonomous_tick()
        completed = deepcopy(first._intention_history[-1])
        assert completed["id"] == report["intention_id"]
        assert completed["status"] == "performed"
        unfinished = begin_intention(first, {"action": "explore", "source": "test",
                                             "params": {"topic": "память", "reason": "продолжить"}})
        unfinished_id = unfinished["id"]
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, startup = create_agent(env, "IntentionLife")
        assert startup["source"] == "checkpoint"
        assert len(second._intention_history) == 2
        assert second._intention_history[0] == completed
        assert second._intention_history[1]["id"] == unfinished_id
        assert second._intention_history[1]["status"] == "interrupted"
        assert second._intention_history[1]["outcome"] is None
        with patch.object(second.decision_arbitrator, "choose_action", return_value=selected):
            second.autonomous_tick()
        assert len(second._intention_history) == 3
        assert len({entry["id"] for entry in second._intention_history}) == 3
        assert second._intention_history[0] == completed
        second.save_state(force=True)
        PluginRegistry.reset_global()
        third, _ = create_agent(env, "IntentionLife")
        assert third._intention_history == second._intention_history
    finally:
        PluginRegistry.reset_global()
