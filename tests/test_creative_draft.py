"""Текстовый артефакт не является свидетельством; чужие правки не затираются."""

from pathlib import Path
from unittest.mock import patch

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.core.agent import DigitalBeing
from src.core.subsystem_base import PluginRegistry
from src.core.paths import data_path


def test_creating_draft_does_not_search_or_change_knowledge():
    agent = DigitalBeing(name="DraftNotKnowledge")
    before = agent.mental_models.to_storage_dict()
    with patch.object(agent, "think", side_effect=AssertionError("not research")) as think:
        agent.act("creative_act")
    think.assert_not_called()
    draft = agent._creative_draft
    assert draft["revision"] == 1
    assert (Path(data_path("delamain", "workspace", "creative")) / f"{draft['id']}.txt").is_file()
    assert agent.mental_models.to_storage_dict() == before


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_continue_draft_after_normal_startup(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "DraftLife", new=True)
        first.act("creative_act")
        old = dict(first._creative_draft)
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, _ = create_agent(env, "DraftLife")
        assert second._creative_draft == old
        second.act("creative_act")
        assert second._creative_draft["id"] == old["id"]
        assert second._creative_draft["revision"] == 2
    finally:
        PluginRegistry.reset_global()


def test_leaving_keeps_file_and_next_choice_starts_different_draft():
    agent = DigitalBeing(name="LeaveDraft")
    agent.act("creative_act")
    original = dict(agent._creative_draft)
    path = Path(data_path("delamain", "workspace", "creative")) / f"{original['id']}.txt"
    content = path.read_text(encoding="utf-8")
    agent.leave_creative_draft("хочу заняться другим")
    assert agent._creative_draft["status"] == "left"
    assert agent._creative_draft["leave_reason"] == "хочу заняться другим"
    assert path.read_text(encoding="utf-8") == content
    agent.act("creative_act")
    assert agent._creative_draft["id"] != original["id"]
    assert path.read_text(encoding="utf-8") == content


def test_full_workspace_blocks_new_draft_without_deleting_files(monkeypatch):
    from src.cognition import creative_draft

    agent = DigitalBeing(name="DraftQuota")
    agent.act("creative_act")
    agent.leave_creative_draft("достаточно")
    root = Path(data_path("delamain", "workspace", "creative"))
    files = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    monkeypatch.setattr(creative_draft, "MAX_DRAFTS", len(list(root.iterdir())))
    assert not agent._is_action_available("create_draft")
    with pytest.raises(ValueError, match="заполнена"):
        agent.act("creative_act")
    assert {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()} == files


def test_modified_draft_is_not_overwritten():
    agent = DigitalBeing(name="DraftExternalEdit")
    agent.act("creative_act")
    draft = dict(agent._creative_draft)
    path = Path(data_path("delamain", "workspace", "creative")) / f"{draft['id']}.txt"
    path.write_text("правка человека", encoding="utf-8")
    with pytest.raises(ValueError, match="изменён извне"):
        agent.act("creative_act")
    assert path.read_text(encoding="utf-8") == "правка человека"
    assert agent._creative_draft == draft
