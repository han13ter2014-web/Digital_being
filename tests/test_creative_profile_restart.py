"""Каталог сохраняет разные работы и причины через настоящий старт."""

from pathlib import Path
from unittest.mock import patch

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.core.agent import DigitalBeing
from src.core.subsystem_base import PluginRegistry


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_catalog_restart_and_addressed_continuation(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "CreativeProfile", new=True)
        first.act("create_draft", intention={"params": {"draft_mode": "new"}})
        left_id = first._creative_draft["id"]
        first.leave_creative_draft("оставить эту композицию как есть")
        first.act("create_draft", intention={"params": {"draft_mode": "new"}})
        active_id = first._creative_draft["id"]
        catalog = first.list_creative_drafts()
        root = Path(env.data_root) / "delamain" / "workspace" / "creative"
        original_text = (root / f"{left_id}.txt").read_bytes()
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, report = create_agent(env, "CreativeProfile")
        assert report["source"] == "checkpoint"
        assert second.list_creative_drafts() == catalog
        second.act("create_draft", intention={"params": {"draft_id": active_id}})
        assert second._creative_draft["revision"] == 2
        assert second._creative_draft["id"] == active_id
        assert (root / f"{left_id}.txt").read_bytes() == original_text
        assert next(d for d in second.list_creative_drafts() if d["id"] == left_id)["leave_reason"] == "оставить эту композицию как есть"
    finally:
        PluginRegistry.reset_global()


def test_autonomous_leave_has_neutral_inference_feedback():
    agent = DigitalBeing(name="LeaveFeedback")
    agent.act("create_draft")
    selected = {"action": "create_draft", "source": "test", "verdict": "proceed",
                "params": {"draft_mode": "leave", "draft_id": agent._creative_draft["id"], "reason": "достаточно"}}
    with patch.object(agent.decision_arbitrator, "choose_action", return_value=selected), \
         patch.object(agent, "_record_active_inference_experience") as record:
        report = agent.autonomous_tick()
    assert report["actual_valence"] == 0
    record.assert_called_once()
    assert record.call_args.args[2] == 0
    assert agent._creative_draft["status"] == "left"
