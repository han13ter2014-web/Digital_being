"""Обновление старого профиля v0.1.1: память переносится, оригинал цел."""

from pathlib import Path

from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import (
    CheckpointSerializer,
    build_state_from_agent,
)
from src.memory.long_term_memory import LongTermMemory


def test_legacy_profile_keeps_memory_after_binding_uuid(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)

    legacy_memory = LongTermMemory("Old")
    legacy_memory.store("старое воспоминание", importance=0.9)
    legacy_memory.save()
    original_bytes = Path(legacy_memory.memory_file).read_bytes()

    born = DigitalBeing("Old")
    state = build_state_from_agent(born)
    state.pop("life_id", None)
    CheckpointSerializer(checkpoint_dir=str(checkpoints), backend="json").save(state, "Old", 0)

    restored, report = create_agent(env, "Old")
    assert report["source"] == "checkpoint"
    assert restored.life_id
    assert restored.long_term_memory.get_memory_stats()["total_memories"] == 1
    assert Path(legacy_memory.memory_file).read_bytes() == original_bytes

    restored.cycle_count = 3
    assert restored.save_state(force=True)
    from src.app.active_profile import active_name, remember_active_name

    remember_active_name(str(tmp_path), restored.name, restored.life_id)
    assert active_name(str(tmp_path), "fallback") == "Old"

    again, report = create_agent(env, "Old", expected_life_id=restored.life_id)
    assert report["source"] == "checkpoint"
    assert again.life_id == restored.life_id
    assert again.long_term_memory.get_memory_stats()["total_memories"] == 1


def test_corrupt_uuid_memory_stops_restore_without_overwrite(tmp_path, monkeypatch):
    """Повреждённая память не должна молча стать пустой."""
    import pytest
    from src.app.bootstrap import RecoveryRequiredError

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)
    first, _ = create_agent(env, "Alpha", new=True)
    assert first.save_state(force=True)
    path = Path(first.long_term_memory.memory_file)
    path.write_text("{повреждено", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(RecoveryRequiredError):
        create_agent(env, "Alpha", expected_life_id=first.life_id)
    assert path.read_bytes() == before


def test_nested_non_uuid_directory_is_not_used_as_identity(tmp_path, monkeypatch):
    """Папка с произвольным именем не должна становиться жизнью."""
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)
    stray = tmp_path / "checkpoints" / "backup_copy"
    stray.mkdir(parents=True, exist_ok=True)
    (stray / "Old_cycle_0.json").write_text("{}", encoding="utf-8")
    agent, report = create_agent(env, "Old", new=True)
    assert report["source"] == "new"
    assert agent.life_id
