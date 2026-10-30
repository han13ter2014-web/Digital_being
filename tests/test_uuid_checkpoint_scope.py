"""UUID namespace: имя не участвует в записи, выбор чужой жизни запрещён."""

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.active_profile import active_name
from src.app.bootstrap import create_agent, RecoveryRequiredError
from src.app.paths import setup_environment
from src.core.agent_runner import AgentRunner
from src.core.event_bus import EventBus


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_rename_keeps_checkpoint_namespace(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    env = setup_environment(chdir=False, console=False)
    first, _ = create_agent(env, "Alpha", new=True)
    identity = first.life_id
    runner = AgentRunner(first, EventBus())
    assert runner.save_now()
    first.name = "Омелла"
    first.cycle_count = 8
    assert runner.save_now()
    assert set(p.name for p in (tmp_path / "checkpoints").iterdir()) == {identity}
    restored, report = create_agent(env, "outdated display name", expected_life_id=identity)
    assert restored.life_id == identity
    assert restored.name == "Омелла"
    assert restored.cycle_count == 8
    assert report["source"] == "checkpoint"


def test_two_lives_with_same_name_require_uuid(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)
    first, _ = create_agent(env, "Same", new=True)
    first.save_state(force=True)
    second, _ = create_agent(env, "Same", new=True)
    second.cycle_count = 9
    second.save_state(force=True)
    assert first.life_id != second.life_id
    with pytest.raises(RecoveryRequiredError):
        create_agent(env, "Same")
    restored, _ = create_agent(env, "Same", expected_life_id=first.life_id)
    assert restored.life_id == first.life_id
    assert restored.cycle_count == 0


def test_missing_pointer_with_uuid_data_cannot_start_new_life(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)
    first, _ = create_agent(env, "Alpha", new=True)
    first.save_state(force=True)
    with pytest.raises(RecoveryRequiredError):
        active_name(tmp_path, "Alpha")
