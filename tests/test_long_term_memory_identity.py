"""Long-term memory uses stable life_id for managed agents."""

from src.core.agent import DigitalBeing
from src.memory.long_term_memory import LongTermMemory


def test_managed_agent_memory_file_uses_life_id(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing("Alpha", profile_managed=True)
    memory = agent.long_term_memory
    assert memory is not None
    assert agent.life_id in memory.memory_file
    agent.name = "Омелла"
    assert agent.life_id in memory.memory_file


def test_direct_legacy_agent_keeps_name_based_memory(tmp_path, monkeypatch):
    """Прямое использование не должно терять старый файл памяти."""
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = DigitalBeing("Alpha")
    assert "Alpha_long_term.json" in agent.long_term_memory.memory_file


def test_uuid_memory_survives_checkpoint_reload(tmp_path, monkeypatch):
    from src.app.bootstrap import create_agent
    from src.app.paths import setup_environment

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)
    first, _ = create_agent(env, "Alpha", new=True)
    first.long_term_memory.store("воспоминание", importance=0.9)
    first.long_term_memory.save()
    first.name = "Омелла"
    first.save_state(force=True)
    second, _ = create_agent(env, "Омелла", expected_life_id=first.life_id)
    assert second.long_term_memory.memory_file == first.long_term_memory.memory_file
    assert second.long_term_memory.get_memory_stats()["total_memories"] == 1


def test_restore_keeps_memory_object_for_subsystems(tmp_path, monkeypatch):
    from src.app.bootstrap import create_agent
    from src.app.paths import setup_environment

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    env = setup_environment(chdir=False, console=False)
    first, _ = create_agent(env, "Alpha", new=True)
    first.long_term_memory.store("воспоминание", importance=0.9)
    first.long_term_memory.save()
    first.save_state(force=True)
    second, _ = create_agent(env, "Alpha", expected_life_id=first.life_id)
    memory = second.long_term_memory
    assert memory.life_id == first.life_id
    sleep = getattr(second, "sleep_cycle", None)
    if sleep is not None and getattr(sleep, "long_term_memory", None) is not None:
        assert sleep.long_term_memory is memory
    assert memory.get_memory_stats()["total_memories"] == 1


def test_legacy_copy_preserves_original(tmp_path, monkeypatch):
    from pathlib import Path
    from src.core.life_identity import new_life_id

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    old = LongTermMemory("Old")
    old.store("старое воспоминание", importance=0.9)
    old.save()
    before = Path(old.memory_file).read_bytes()
    target = LongTermMemory("Old", life_id=new_life_id())
    target.bind_legacy_file("Old")
    assert Path(old.memory_file).read_bytes() == before
    assert target.get_memory_stats()["total_memories"] == 1


def test_legacy_memory_constructor_keeps_name_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    memory = LongTermMemory("Legacy")
    assert "Legacy_long_term.json" in memory.memory_file
