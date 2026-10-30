"""Дневник UUID: переименование не теряет записи и не подхватывает тёзку."""

from types import SimpleNamespace

from src.core.life_identity import new_life_id
from src.delamain.memory import MemoryStore
from src.ui.life_snapshot import recent_life_episodes


def test_uuid_and_proven_legacy_events_survive_rename(tmp_path):
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    identity = new_life_id()
    try:
        memory.record_life_episode(life_id="Alpha", intention_id="old", action="play")
        memory.record_life_episode(life_id=identity, intention_id="new", action="play")
        memory.record_life_episode(life_id="Alpha", intention_id="unrelated", action="play")
        memory.record_life_episode(life_id=new_life_id(), intention_id="old", action="play")
        agent = SimpleNamespace(name="Омелла", life_id=identity,
                                _intention_history=[{"id": "old"}],
                                delamain=SimpleNamespace(runtime=SimpleNamespace(memory=memory)))
        episodes = recent_life_episodes(agent)
        assert [item["task_id"] for item in episodes] == ["new", "old"]
        assert memory.recent_life_episodes(life_id="Alpha")[0]["task_id"] == "unrelated"
    finally:
        memory.close()
