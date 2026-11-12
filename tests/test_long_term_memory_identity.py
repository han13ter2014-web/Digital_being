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
    assert agent.delamain.life_id == agent.life_id
    from pathlib import Path
    from src.core.paths import data_path

    assert agent.delamain.db_path == Path(
        data_path("lives", agent.life_id, "life.sqlite3")
    )


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


def test_sqlite_memory_roundtrip_preserves_traces_links_and_order(
    tmp_path, monkeypatch
):
    from contextlib import closing
    from pathlib import Path
    from src.core.life_identity import new_life_id

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    life_id = new_life_id()
    memory = LongTermMemory("Alpha", life_id=life_id)
    consolidated_id = memory.store(
        "общий устойчивый след памяти", importance=0.9, context="контекст"
    )
    working_id = memory.store(
        "общий рабочий след", importance=0.4, memory_type="semantic"
    )
    episode_id = memory.store("отдельный эпизод", importance=0.2)
    assert memory._episodic_ids[id(memory._episodic[-1])] == episode_id
    # Эпизод может пережить удаление из short-term и остаётся самостоятельным.
    del memory._short_term[episode_id]
    memory.save()

    assert not Path(memory.memory_file).exists()
    restored = LongTermMemory("Переименованная", life_id=life_id)
    assert set(restored._long_term) == {consolidated_id}
    assert set(restored._short_term) == {working_id}
    assert restored._short_term[working_id].associations == {consolidated_id}
    assert [trace.content for trace in restored._episodic] == [
        "общий устойчивый след памяти",
        "отдельный эпизод",
    ]
    assert restored._episodic_ids == {
        id(trace): memory_id
        for memory_id, trace in zip((consolidated_id, episode_id), restored._episodic)
    }
    assert restored._consolidation_count == 1
    assert restored._decay_events_count == 0

    # Повторное сохранение не создаёт копий episodic-only следа.
    restored.save()
    with closing(restored.database.connect(readonly=True)) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM memory_traces").fetchone()[0] == 3
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM memory_links").fetchone()[0] == 1
        )
        row = connection.execute(
            "SELECT store, is_episodic, episode_order FROM memory_traces WHERE id = ?",
            (episode_id,),
        ).fetchone()
    assert tuple(row) == ("episodic", 1, 1)


def test_sqlite_memory_save_rolls_back_on_failure(tmp_path, monkeypatch):
    from contextlib import closing
    import pytest
    from src.core.life_identity import new_life_id

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    memory = LongTermMemory("Alpha", life_id=new_life_id())
    memory.store("исходный след", importance=0.9)
    memory.save()

    def snapshot():
        with closing(memory.database.connect(readonly=True)) as connection:
            traces = connection.execute(
                "SELECT * FROM memory_traces ORDER BY id"
            ).fetchall()
            links = connection.execute(
                "SELECT * FROM memory_links ORDER BY trace_id, related_trace_id"
            ).fetchall()
            metadata = connection.execute(
                "SELECT key, value_json FROM meta "
                "WHERE key LIKE 'long_term_memory.%' ORDER BY key"
            ).fetchall()
        return (
            [tuple(row) for row in traces],
            [tuple(row) for row in links],
            [tuple(row) for row in metadata],
        )

    before = snapshot()
    memory.store("не должен сохраниться", importance=0.2)

    def fail_meta(*args, **kwargs):
        raise RuntimeError("injected memory failure")

    monkeypatch.setattr(memory.database, "set_meta", fail_meta)
    with pytest.raises(RuntimeError, match="injected memory failure"):
        memory.save()
    assert snapshot() == before


def test_episodic_limit_forgets_service_ids_with_trace(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.core.life_identity import new_life_id
    import src.memory.long_term_memory as module

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        module, "_lr_config", lambda: SimpleNamespace(MAX_EPISODIC_MEMORIES=2)
    )
    memory = LongTermMemory("Alpha", life_id=new_life_id())
    memory.store("наименее важный", importance=0.1)
    memory.store("важный", importance=0.9)
    memory.store("средний", importance=0.5)

    assert [trace.content for trace in memory._episodic] == ["важный", "средний"]
    assert set(memory._episodic_ids) == {id(trace) for trace in memory._episodic}
