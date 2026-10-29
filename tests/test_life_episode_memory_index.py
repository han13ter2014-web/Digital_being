"""Life episode retrieval has bounded pagination and a dedicated SQLite index."""

import sqlite3

from src.delamain.memory import MemoryStore


def test_life_episode_index_and_bounded_page(tmp_path):
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    try:
        for index in range(5):
            memory.record_life_episode(life_id="one", intention_id=f"i{index}", action="play")
        for index in range(2):
            memory.record_life_episode(life_id="two", intention_id=f"j{index}", action="play")
        rows = memory.recent_life_episodes(life_id="one", limit=2, offset=1)
        assert len(rows) == 2
        assert [row["task_id"] for row in rows] == ["i3", "i2"]
        with sqlite3.connect(tmp_path / "memory.sqlite3") as connection:
            indexes = {row[1] for row in connection.execute("PRAGMA index_list(episodes)")}
        assert "idx_episodes_life" in indexes
    finally:
        memory.close()


def test_life_episode_limit_is_hard_capped(tmp_path):
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    try:
        for index in range(3):
            memory.record_life_episode(life_id="one", intention_id=str(index), action="play")
        assert len(memory.recent_life_episodes(life_id="one", limit=10000)) == 3
    finally:
        memory.close()
