"""Резервная копия должна возвращать прожитый опыт, а не только файлы."""

from pathlib import Path
from unittest.mock import patch

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.core.agent_runner import AgentRunner
from src.core.event_bus import EventBus
from src.core.life_guard import STATE_DORMANT
from src.core.subsystem_base import PluginRegistry
from src.memory.profile_backup import create_backup, restore_backup


@pytest.fixture(autouse=True)
def isolated_registry():
    PluginRegistry.reset_global()
    yield
    PluginRegistry.reset_global()


@pytest.mark.parametrize("backend", ["json", "sqlite"])
@pytest.mark.parametrize("sleeping", [False, True], ids=["awake", "dormant"])
def test_restored_profile_preserves_experience_and_life_state(tmp_path, monkeypatch, backend, sleeping):
    source = tmp_path / "original"
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(source))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    env = setup_environment(chdir=False, console=False)
    first, _ = create_agent(env, "BackupLife", new=True)
    first.energy = 20
    first.interoception.state.fatigue = 0.8
    first.cycle_count = 41
    with patch.object(first, "_recover_energy", return_value=0.0):
        first.act("rest")
    first._last_experiment_cycle = 40
    pending = first.action_expectations.begin(
        first.mental_models, "rest", first.energy, 200,
        fatigue=first.interoception.state.fatigue,
    )
    if sleeping:
        first.life_guard.set_state(STATE_DORMANT, reason="backup test")
    runner = AgentRunner(first, EventBus(), name="BackupLifeRunner")
    assert runner.save_now()
    before_memory = first.mental_models.to_storage_dict()
    energy, fatigue = first.energy, first.interoception.state.fatigue
    before_files = {p.relative_to(source).as_posix(): p.read_bytes()
                    for p in source.rglob("*") if p.is_file() and "logs" not in p.parts}
    backup = tmp_path / "backup"
    create_backup(source, backup)
    restored_root = tmp_path / "restored"
    restore_backup(backup, restored_root)
    # Второй объект не должен использовать реестр подсистем первого.
    PluginRegistry.reset_global()
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(restored_root))
    restored_env = setup_environment(chdir=False, console=False)
    second, report = create_agent(restored_env, "BackupLife")
    assert report["source"] == "checkpoint"
    assert second.cycle_count == 41
    assert second.energy == energy
    assert second.interoception.state.fatigue == pytest.approx(fatigue)
    assert second._last_experiment_cycle == 40
    assert second.mental_models.to_storage_dict() == before_memory
    assert second.is_alive() is not sleeping
    assert getattr(second, "action_expectations", None) is None
    if not sleeping:
        second.act("rest")
        observed = second.action_expectations.last_trial
        assert observed["trial_id"] != pending.trial_id
        assert observed["expected_direction"] == -1
        assert observed["fatigue_expected_direction"] == 1
        assert not observed["prediction_matched"]
        assert observed["fatigue_prediction_matched"]
    assert Path(second.checkpoint_dir).is_relative_to(restored_root)
    for relative, content in before_files.items():
        assert (source / relative).read_bytes() == content
