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
        store.record_skill(
            "write-and-verify", [{"action": "write_file"}], success=False
        )
        skill = store.get_skill("write-and-verify")
        assert skill is not None
        assert skill["success_count"] == 2
        assert skill["failure_count"] == 1
    finally:
        store.close()


def test_update_goal_merges_metadata_and_priority(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    try:
        goal_id = store.save_goal(
            "retry me",
            metadata={"command": "read_file", "attempts": 1},
            priority=0.2,
        )

        assert store.update_goal(
            goal_id,
            status="pending",
            metadata={"last_error": "temporary", "attempts": 2},
            priority=0.8,
        )
        goal = store.list_goals()[0]
        assert goal["status"] == "pending"
        assert goal["priority"] == 0.8
        assert goal["metadata"]["command"] == "read_file"
        assert goal["metadata"]["attempts"] == 2
        assert goal["metadata"]["last_error"] == "temporary"
        assert store.update_goal(999, status="done") is False
    finally:
        store.close()


def test_failed_skill_keeps_last_successful_plan(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.sqlite3")
    try:
        plan = [{"action": "write_file", "args": {"path": "a.txt"}}]
        store.record_skill("keep-plan", plan, success=True)
        store.record_skill("keep-plan", None, success=False)

        skill = store.get_skill("keep-plan")
        assert skill is not None
        assert skill["success_count"] == 1
        assert skill["failure_count"] == 1
        assert skill["plan"] == plan
        assert store.list_skills()[0]["name"] == "keep-plan"
    finally:
        store.close()


def test_managed_store_roundtrip_uses_shared_life_schema(tmp_path: Path) -> None:
    import sqlite3
    from uuid import uuid4

    life_id = str(uuid4())
    path = tmp_path / "lives" / life_id / "life.sqlite3"
    with MemoryStore(path, life_id=life_id) as store:
        store.record_episode(
            task_id="task-managed",
            task="demo",
            action="test",
            output={"ok": True},
            metadata={"life_id": life_id},
        )
        store.remember_fact("язык", "Python", source="test", confidence=0.9)
        store.set_self_model("name", "Нова")
        goal_id = store.save_goal(
            "Проверить общую базу", metadata={"command": "test"}, priority=0.8
        )
        assert (
            store.update_goal(goal_id, status="done", metadata={"attempts": 1}) is True
        )
        store.record_skill("managed-skill", [{"action": "test"}], success=True)
        approval = store.create_approval(
            task_id="task-managed",
            task="demo",
            goal_id=goal_id,
            plan=[{"action": "test", "args": {}}],
        )
        assert store.approve_approval(approval["id"])["status"] == "approved"
        assert store.consume_approval(approval["id"]) is True

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "execution_goals" in tables
        assert "goals" not in tables
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    with MemoryStore(path, life_id=life_id) as reopened:
        assert reopened.life_id == life_id
        assert reopened.recent_episodes(task_id="task-managed")[0]["action"] == "test"
        assert reopened.recall_facts("Python")[0]["confidence"] == 0.9
        assert reopened.get_self_model("name") == "Нова"
        assert reopened.get_goal(goal_id)["metadata"] == {
            "command": "test",
            "attempts": 1,
        }
        assert reopened.list_goals(status="done")[0]["id"] == goal_id
        assert reopened.get_skill("managed-skill")["success_count"] == 1
        assert reopened.get_approval(approval["id"])["status"] == "consumed"
