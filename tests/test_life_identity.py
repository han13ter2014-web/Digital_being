"""Первый контракт стабильного life_id, независимого отображаемого имени."""

import json

import pytest

from src.app.active_profile import active_name, remember_active_name
from src.app.profile_identity import selected_life_id
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import build_state_from_agent
from src.core.life_identity import new_life_id, validate_life_id


def test_agent_gets_uuid_identity_and_name_is_not_identity():
    agent = DigitalBeing("Alpha")
    first = agent.life_id
    agent.name = "Омелла"
    assert validate_life_id(first) == first
    assert agent.name == "Омелла"
    assert build_state_from_agent(agent)["life_id"] == first


def test_active_profile_keeps_life_id_with_renamed_display_name(tmp_path):
    life_id = new_life_id()
    remember_active_name(tmp_path, "Омелла", life_id)
    assert selected_life_id(tmp_path) == life_id
    assert json.loads((tmp_path / "active_profile.json").read_text(encoding="utf-8")) == {
        "name": "Омелла", "life_id": life_id
    }


def test_uuid_survives_real_save_rename_restart(tmp_path, monkeypatch):
    from src.app.bootstrap import create_agent, RecoveryRequiredError
    from src.app.paths import setup_environment
    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)
    first, _ = create_agent(env, "Alpha", new=True)
    original = first.life_id
    first.name = "Омелла"
    first.cycle_count = 23
    assert AgentRunner(first, EventBus()).save_now()
    second, report = create_agent(env, active_name(tmp_path, "Alpha"),
                                  expected_life_id=selected_life_id(tmp_path))
    assert report["source"] == "checkpoint"
    assert second.life_id == original
    assert second.name == "Омелла"
    assert second.cycle_count == 23
    with pytest.raises(RecoveryRequiredError):
        create_agent(env, "Омелла", expected_life_id=new_life_id())


def test_invalid_life_id_is_rejected():
    with pytest.raises(ValueError):
        validate_life_id("not-an-id")
