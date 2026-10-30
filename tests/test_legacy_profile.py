"""Обновление старого профиля без создания новой жизни и без выбора случайной."""

import sqlite3

import pytest

from src.app.active_profile import active_name
from src.app.bootstrap import RecoveryRequiredError, create_agent
from src.app.paths import setup_environment
from src.core.checkpoint_serializer import CheckpointSerializer


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_legacy_renamed_profile_restores_without_pointer(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)
    agent, _ = create_agent(env, "Омелла", new=True)
    agent.cycle_count = 74
    from src.core.checkpoint_serializer import build_state_from_agent

    serializer = CheckpointSerializer(checkpoint_dir=tmp_path / "checkpoints", backend=backend)
    serializer.save(build_state_from_agent(agent), agent.name, agent.cycle_count)
    before = {p: p.read_bytes() for p in (tmp_path / "checkpoints").iterdir() if p.is_file()}
    selected = active_name(tmp_path, "Alpha")
    assert selected == "Омелла"
    assert all(p.read_bytes() == data for p, data in before.items())
    restored, report = create_agent(env, selected)
    assert report["source"] == "checkpoint"
    assert restored.cycle_count == 74
    assert restored.name == "Омелла"
    assert not (tmp_path / "active_profile.json").exists()


def test_multiple_profiles_require_explicit_choice_even_with_default(tmp_path):
    directory = tmp_path / "checkpoints"
    directory.mkdir()
    for name in ("Alpha", "Омелла"):
        (directory / f"{name}_cycle_1.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RecoveryRequiredError, match="несколько"):
        active_name(tmp_path, "Alpha")


def test_corrupt_database_never_falls_back_to_new_life(tmp_path):
    directory = tmp_path / "checkpoints"
    directory.mkdir()
    (directory / "life.sqlite3").write_bytes(b"broken")
    with pytest.raises(RecoveryRequiredError):
        active_name(tmp_path, "Alpha")


def test_empty_supported_database_is_new_profile(tmp_path):
    directory = tmp_path / "checkpoints"
    directory.mkdir()
    with sqlite3.connect(directory / "life.sqlite3") as connection:
        connection.execute("PRAGMA user_version = 1")
        connection.execute("CREATE TABLE snapshots (agent_name TEXT)")
    assert active_name(tmp_path, "Alpha") == "Alpha"
