"""Смена отображаемого имени сохраняет выбор жизни при следующем запуске."""

import json
import os
from pathlib import Path
import threading

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


def test_failed_pointer_write_preserves_previous_and_cleans_temp(tmp_path, monkeypatch):
    from src.app.active_profile import remember_active_name

    remember_active_name(tmp_path, "Original")
    destination = tmp_path / "active_profile.json"
    before = destination.read_bytes()
    original_write_text = Path.write_text

    def fail_temp_write(path, data, *args, **kwargs):
        if path.parent == tmp_path and path.suffix == ".tmp":
            original_write_text(path, data, *args, **kwargs)
            raise OSError("disk full")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_temp_write)

    with pytest.raises(OSError, match="disk full"):
        remember_active_name(tmp_path, "Renamed")

    assert destination.read_bytes() == before
    assert list(tmp_path.iterdir()) == [destination]


def test_concurrent_pointer_writes_use_independent_temp_files(tmp_path, monkeypatch):
    from src.app.active_profile import remember_active_name

    original_write_text = Path.write_text
    original_replace = os.replace
    both_written = threading.Barrier(2)
    both_replacing = threading.Barrier(2)
    replace_sources = []
    errors = []

    def synchronize_temp_writes(path, data, *args, **kwargs):
        result = original_write_text(path, data, *args, **kwargs)
        if path.parent == tmp_path and path.suffix == ".tmp":
            both_written.wait(timeout=5)
        return result

    def synchronize_replaces(source, destination):
        replace_sources.append(source)
        both_replacing.wait(timeout=5)
        return original_replace(source, destination)

    def remember(name):
        try:
            remember_active_name(tmp_path, name)
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(Path, "write_text", synchronize_temp_writes)
    monkeypatch.setattr("src.app.active_profile.os.replace", synchronize_replaces)
    threads = [threading.Thread(target=remember, args=(name,)) for name in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert all(isinstance(exc, PermissionError) for exc in errors)
    assert len(set(replace_sources)) == 2
    destination = tmp_path / "active_profile.json"
    assert json.loads(destination.read_text(encoding="utf-8"))["name"] in {"A", "B"}
    assert list(tmp_path.iterdir()) == [destination]
