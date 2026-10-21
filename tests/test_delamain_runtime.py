from pathlib import Path

from src.delamain.models import ActionRequest
from src.delamain.runtime import DelamainRuntime


def test_runtime_executes_plan_and_records_episodes(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    with DelamainRuntime(root, tmp_path / "memory.sqlite3") as runtime:
        result = runtime.run_task(
            "write, verify and remember",
            plan=[
                ActionRequest("write_file", {"path": "notes/a.txt", "content": "привет"}),
                ActionRequest("verify_file", {"path": "notes/a.txt", "contains": "привет"}),
                ActionRequest("remember_fact", {"key": "note", "value": "привет", "source": "test"}),
                ActionRequest("recall_facts", {"query": "note"}),
            ],
        )

        assert result.ok is True
        assert len(result.steps) == 4
        assert (root / "notes" / "a.txt").read_text(encoding="utf-8") == "привет"
        assert result.final_output["facts"][0]["value"] == "привет"
        assert result.planned_actions == [
            {
                "action": "write_file",
                "args": {"path": "notes/a.txt", "content": "привет"},
            },
            {
                "action": "verify_file",
                "args": {"path": "notes/a.txt", "contains": "привет"},
            },
            {
                "action": "remember_fact",
                "args": {"key": "note", "value": "привет", "source": "test"},
            },
            {"action": "recall_facts", "args": {"query": "note"}},
        ]

        history = runtime.history(task_id=result.task_id)
        actions = [item["action"] for item in history]
        assert actions == [
            "task.start",
            "write_file",
            "verify_file",
            "remember_fact",
            "recall_facts",
            "task.finish",
        ]
        assert history[-1]["ok"] is True
        assert history[-1]["output"]["planned_actions"] == result.planned_actions


def test_runtime_stops_on_first_failure(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    with DelamainRuntime(root, tmp_path / "memory.sqlite3") as runtime:
        result = runtime.run_task(
            "stop on failure",
            plan=[
                ActionRequest("read_file", {"path": "missing.txt"}),
                ActionRequest("write_file", {"path": "should-not-exist.txt", "content": "x"}),
            ],
        )

        assert result.ok is False
        assert len(result.steps) == 1
        assert result.steps[0].ok is False
        assert not (root / "should-not-exist.txt").exists()

        history = runtime.history(task_id=result.task_id)
        assert [item["action"] for item in history] == [
            "task.start",
            "read_file",
            "task.finish",
        ]
        assert history[-1]["ok"] is False


def test_runtime_rejects_sandbox_escape(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    with DelamainRuntime(root, tmp_path / "memory.sqlite3") as runtime:
        result = runtime.run_task(
            "escape attempt",
            plan=[ActionRequest("write_file", {"path": "../outside.txt", "content": "x"})],
        )

        assert result.ok is False
        assert not (tmp_path / "outside.txt").exists()


def test_runtime_can_use_heuristic_planner(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    with DelamainRuntime(root, tmp_path / "memory.sqlite3") as runtime:
        result = runtime.run_task("запиши в notes/a.txt: привет")

        assert result.ok is True
        assert (root / "notes" / "a.txt").read_text(encoding="utf-8") == "привет"


def test_runtime_reports_planner_and_unknown_action_errors(tmp_path: Path) -> None:
    with DelamainRuntime(tmp_path / "workspace", tmp_path / "memory.sqlite3") as runtime:
        result = runtime.run_task("неизвестная команда")
        assert result.ok is False
        assert "cannot parse" in (result.error or "")

        result = runtime.run_task(
            "unknown action",
            plan=[ActionRequest("does_not_exist", {})],
        )
        assert result.ok is False
        assert "unknown action" in (result.error or "")


def test_describe_actions(tmp_path: Path) -> None:
    with DelamainRuntime(tmp_path / "workspace", tmp_path / "memory.sqlite3") as runtime:
        names = {spec["name"] for spec in runtime.describe_actions()}
        assert {"write_file", "read_file", "search_files", "verify_file"} <= names
        assert "remember_fact" in names
