from pathlib import Path

from src.delamain.memory import MemoryStore


def test_episode_roundtrip(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.record_episode(
            task_id="task-1",
            task="demo",
            action="write_file",
            args={"path": "a.txt"},
            ok=True,
            output={"created": True},
            metadata={"duration_ms": 1.5},
        )
        store.record_episode(
            task_id="task-1",
            task="demo",
            action="verify_file",
            args={"path": "a.txt"},
            ok=True,
            output={"verified": True},
        )

        episodes = store.recent_episodes(task_id="task-1")
        assert [item["action"] for item in episodes] == ["write_file", "verify_file"]
        assert episodes[0]["args"] == {"path": "a.txt"}
        assert episodes[0]["output"] == {"created": True}
        assert episodes[0]["metadata"]["duration_ms"] == 1.5
        assert episodes[0]["ok"] is True
    finally:
        store.close()


def test_facts_are_searchable_and_upserted(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.remember_fact("язык", "Python", source="user", confidence=0.8)
        store.remember_fact("язык", "Python", source="user", confidence=0.9)

        results = store.recall_facts("Python")
        assert len(results) == 1
        assert results[0]["key"] == "язык"
        assert results[0]["value"] == "Python"
        assert results[0]["confidence"] == 0.9

        russian = store.recall_facts("язык")
        assert russian and russian[0]["value"] == "Python"
    finally:
        store.close()


def test_self_model_goals_and_skills(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.set_self_model("name", "Delamain-local")
        store.set_self_model("principles", ["honesty", "safety"])
        assert store.get_self_model("name") == "Delamain-local"
        assert store.get_self_model()["principles"] == ["honesty", "safety"]

        goal_id = store.save_goal(
            "Проверить память",
            success_predicate="episode exists",
            priority=0.7,
        )
        goals = store.list_goals()
        assert goals[0]["id"] == goal_id
        assert goals[0]["priority"] == 0.7
        assert store.update_goal_status(goal_id, "done") is True
        assert store.list_goals(status="done")[0]["title"] == "Проверить память"

        store.record_skill("write-and-verify", [{"action": "write_file"}], success=True)
        store.record_skill("write-and-verify", [{"action": "write_file"}], success=True)
        store.record_skill("write-and-verify", [{"action": "write_file"}], success=False)
        skill = store.get_skill("write-and-verify")
        assert skill is not None
        assert skill["success_count"] == 2
        assert skill["failure_count"] == 1
    finally:
        store.close()
