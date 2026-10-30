"""Смена отображаемого имени сохраняет выбор жизни при следующем запуске."""

import pytest

from src.app.active_profile import active_name
from src.app.bootstrap import RecoveryRequiredError, create_agent
from src.app.paths import setup_environment
from src.core.agent_runner import AgentRunner
from src.core.event_bus import EventBus


def test_renamed_life_restores_from_active_pointer(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)
    first, _ = create_agent(env, "Alpha", new=True)
    first.name = "Омелла"
    first.cycle_count = 57
    assert AgentRunner(first, EventBus()).save_now()
    assert active_name(tmp_path, "Alpha") == "Омелла"
    second, report = create_agent(env, active_name(tmp_path, "Alpha"))
    assert report["source"] == "checkpoint"
    assert second.cycle_count == 57
    assert second.name == "Омелла"


def test_corrupt_pointer_never_silently_starts_new_life(tmp_path):
    (tmp_path / "active_profile.json").write_text("broken", encoding="utf-8")
    with pytest.raises(RecoveryRequiredError):
        active_name(tmp_path, "Alpha")


def test_missing_pointer_keeps_legacy_selection(tmp_path):
    assert active_name(tmp_path, "Alpha") == "Alpha"


def test_failed_checkpoint_keeps_existing_pointer(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.app.active_profile import remember_active_name

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    remember_active_name(tmp_path, "Original")
    before = (tmp_path / "active_profile.json").read_bytes()

    def fail_save(**kwargs):
        raise OSError("disk write failed")

    runner = AgentRunner.__new__(AgentRunner)
    runner.name = "test"
    runner.agent = SimpleNamespace(name="Renamed", save_state=fail_save)
    assert runner._save_state_safe() is False
    assert (tmp_path / "active_profile.json").read_bytes() == before


def test_pointer_without_checkpoint_stops_restore(tmp_path):
    from src.app.active_profile import remember_active_name

    remember_active_name(tmp_path, "Missing")
    with pytest.raises(RecoveryRequiredError):
        active_name(tmp_path, "Alpha")
