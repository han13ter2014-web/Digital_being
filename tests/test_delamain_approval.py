from pathlib import Path

import pytest

from src.delamain.models import ActionRequest
from src.delamain.runtime import DelamainRuntime
from src.delamain.subsystem import DelamainSubsystem


class WritePlanner:
    """A tiny planner stand-in for a model-produced plan."""

    def plan(self, task: str):
        return [
            ActionRequest(
                "write_file",
                {"path": "from_planner.txt", "content": "planned"},
            )
        ]


def make_sub(tmp_path: Path, **kwargs) -> DelamainSubsystem:
    params = {
        "agent_name": "ApprovalTest",
        "workspace": tmp_path / "workspace",
        "db_path": tmp_path / "memory.sqlite3",
        "enabled": True,
        "tick_interval": 1,
    }
    params.update(kwargs)
    return DelamainSubsystem(**params)


def test_write_file_is_dangerous_but_off_mode_executes(tmp_path: Path) -> None:
    with DelamainRuntime(
        tmp_path / "workspace",
        tmp_path / "memory.sqlite3",
        approval_mode="off",
    ) as runtime:
        specs = {spec["name"]: spec for spec in runtime.describe_actions()}
        assert specs["write_file"]["dangerous"] is True
        assert specs["set_self_model"]["dangerous"] is True
        assert specs["read_file"]["dangerous"] is False

        result = runtime.run_task(
            "write",
            plan=[ActionRequest("write_file", {"path": "a.txt", "content": "ok"})],
        )
        assert result.ok is True
        assert result.pending_approval is None
        assert (tmp_path / "workspace" / "a.txt").read_text(encoding="utf-8") == "ok"
        assert runtime.memory.count_approvals() == 0


def test_dangerous_plan_waits_without_side_effects(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        approval_mode="dangerous",
    ) as runtime:
        result = runtime.run_task(
            "write",
            task_id="task-1",
            plan=[
                ActionRequest("write_file", {"path": "a.txt", "content": "ok"}),
                ActionRequest("verify_file", {"path": "a.txt", "contains": "ok"}),
            ],
        )

        assert result.ok is False
        assert result.steps == []
        assert "approval required" in (result.error or "")
        assert result.pending_approval is not None
        approval = result.pending_approval
        assert approval["status"] == "pending"
        assert approval["dangerous_actions"] == ["write_file"]
        assert approval["plan"] == [
            {"action": "write_file", "args": {"path": "a.txt", "content": "ok"}},
            {"action": "verify_file", "args": {"path": "a.txt", "contains": "ok"}},
        ]
        assert not (root / "a.txt").exists()
        assert runtime.memory.count_approvals(status="pending") == 1
        # No task.start is written before the approval decision.
        assert [item["action"] for item in runtime.history(task_id="task-1")] == [
            "approval.requested"
        ]


def test_approve_executes_plan_once(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        approval_mode="dangerous",
    ) as runtime:
        pending = runtime.run_task(
            "write",
            task_id="task-1",
            plan=[ActionRequest("write_file", {"path": "a.txt", "content": "ok"})],
        )
        approval_id = pending.pending_approval["id"]
        approved = runtime.memory.approve_approval(approval_id)
        assert approved is not None
        assert approved["status"] == "approved"

        result = runtime.run_approved(approval_id)
        assert result.ok is True
        assert result.approval_id == approval_id
        assert (root / "a.txt").read_text(encoding="utf-8") == "ok"
        assert runtime.memory.get_approval(approval_id)["status"] == "consumed"
        assert [item["action"] for item in runtime.history(task_id="task-1")] == [
            "approval.requested",
            "task.start",
            "write_file",
            "task.finish",
        ]

        # A consumed approval cannot be replayed, even if the file changed.
        (root / "a.txt").write_text("changed", encoding="utf-8")
        replay = runtime.run_approved(approval_id)
        assert replay.ok is False
        assert "consumed" in (replay.error or "")
        assert (root / "a.txt").read_text(encoding="utf-8") == "changed"


def test_reject_prevents_execution(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        approval_mode="dangerous",
    ) as runtime:
        pending = runtime.run_task(
            "write",
            plan=[ActionRequest("write_file", {"path": "a.txt", "content": "ok"})],
        )
        approval_id = pending.pending_approval["id"]
        rejected = runtime.memory.reject_approval(approval_id, "not now")
        assert rejected is not None
        assert rejected["status"] == "rejected"
        assert rejected["reason"] == "not now"

        result = runtime.run_approved(approval_id)
        assert result.ok is False
        assert "rejected" in (result.error or "")
        assert not (root / "a.txt").exists()
        assert runtime.memory.approve_approval(approval_id) is None


def test_all_mode_gates_even_read_only_plans(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir(parents=True)
    (root / "a.txt").write_text("hello", encoding="utf-8")
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        approval_mode="all",
    ) as runtime:
        pending = runtime.run_task(
            "read",
            plan=[ActionRequest("read_file", {"path": "a.txt"})],
        )
        assert pending.ok is False
        assert pending.pending_approval["dangerous_actions"] == []
        approval_id = pending.pending_approval["id"]
        runtime.memory.approve_approval(approval_id)
        result = runtime.run_approved(approval_id)
        assert result.ok is True
        assert result.final_output["text"] == "hello"


def test_planner_plan_is_gated_before_execution(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        planner=WritePlanner(),
        approval_mode="dangerous",
    ) as runtime:
        pending = runtime.run_task("use the planner")
        assert pending.ok is False
        assert pending.pending_approval is not None
        assert not (root / "from_planner.txt").exists()

        approval_id = pending.pending_approval["id"]
        runtime.memory.approve_approval(approval_id)
        result = runtime.run_approved(approval_id)
        assert result.ok is True
        assert (root / "from_planner.txt").read_text(encoding="utf-8") == "planned"


def test_approval_survives_runtime_restart(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    db_path = tmp_path / "memory.sqlite3"
    with DelamainRuntime(root, db_path, approval_mode="dangerous") as runtime:
        pending = runtime.run_task(
            "write",
            task_id="durable",
            plan=[ActionRequest("write_file", {"path": "a.txt", "content": "ok"})],
        )
        approval_id = pending.pending_approval["id"]

    with DelamainRuntime(root, db_path, approval_mode="dangerous") as runtime:
        stored = runtime.memory.get_approval(approval_id)
        assert stored is not None
        assert stored["status"] == "pending"
        runtime.memory.approve_approval(approval_id)
        result = runtime.run_approved(approval_id)
        assert result.ok is True
        assert (root / "a.txt").read_text(encoding="utf-8") == "ok"


def test_goal_waits_for_approval_and_approve_completes_it(tmp_path: Path) -> None:
    sub = make_sub(tmp_path, approval_mode="dangerous")
    try:
        goal = sub.queue_goal("write", "write a.txt: ok")
        data = sub.tick(1, {})["events"][0]["data"]
        assert data["ok"] is False
        assert data["pending_approval"] is not None
        assert data["approval_status"] == "pending"
        approval_id = data["pending_approval"]["id"]
        assert not (tmp_path / "workspace" / "a.txt").exists()
        assert sub.list_goals()[0]["status"] == "pending"
        assert sub.list_goals()[0]["metadata"]["approval_id"] == approval_id
        assert sub.status()["goals"] == {"pending": 1, "done": 0, "failed": 0}
        assert sub.status()["approval"]["counts"]["pending"] == 1

        # The next tick must not create a second approval.
        assert sub.tick(2, {}) is None
        assert len(sub.list_approvals(status="pending")) == 1

        approved = sub.approve(approval_id)
        assert approved["ok"] is True
        assert approved["goal_id"] == goal["id"]
        assert approved["attempts"] == 1
        assert approved["approval_status"] == "consumed"
        assert (tmp_path / "workspace" / "a.txt").read_text(encoding="utf-8") == "ok"

        stored = sub.list_goals()[0]
        assert stored["status"] == "done"
        assert stored["metadata"]["approval_id"] is None
        assert stored["metadata"]["approval_status"] == "consumed"
        assert sub.runtime.memory.get_skill("write")["success_count"] == 1
    finally:
        sub.teardown()


def test_goal_reject_marks_failed_without_execution(tmp_path: Path) -> None:
    sub = make_sub(tmp_path, approval_mode="dangerous")
    try:
        sub.queue_goal("write", "write a.txt: ok")
        data = sub.tick(1, {})["events"][0]["data"]
        approval_id = data["pending_approval"]["id"]

        rejected = sub.reject(approval_id, "denied by test")
        assert rejected["ok"] is False
        assert rejected["approval_status"] == "rejected"
        assert rejected["goal_id"] == data["goal_id"]
        assert not (tmp_path / "workspace" / "a.txt").exists()

        stored = sub.list_goals()[0]
        assert stored["status"] == "failed"
        assert stored["metadata"]["approval_id"] is None
        assert stored["metadata"]["approval_status"] == "rejected"
        assert stored["metadata"]["approval_reason"] == "denied by test"
        # A rejected plan was never attempted, so it is not a skill failure.
        assert sub.runtime.memory.get_skill("write") is None
        assert sub.status()["approval"]["counts"]["rejected"] == 1
    finally:
        sub.teardown()


def test_invalid_approval_mode_fails_closed(tmp_path: Path) -> None:
    sub = make_sub(tmp_path, approval_mode="dangrous")
    try:
        assert sub.approval_mode == "dangerous"
        status = sub.status()
        assert status["approval"]["mode"] == "dangerous"
        assert "dangrous" in (status["approval"]["error"] or "")

        result = sub.run_now("write a.txt: ok")
        assert result["pending_approval"] is not None
        assert not (tmp_path / "workspace" / "a.txt").exists()
    finally:
        sub.teardown()


def test_agent_runner_approval_commands(tmp_path: Path) -> None:
    import asyncio

    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    class FakeAgent:
        name = "FakeApprovalAgent"

        def __init__(self, delamain: DelamainSubsystem) -> None:
            self.energy = 100.0
            self.cycle_count = 0
            self.delamain = delamain

    sub = make_sub(tmp_path, approval_mode="dangerous")
    runner = AgentRunner(FakeAgent(sub), EventBus(), watchdog=object())
    try:
        async def scenario() -> None:
            pending_text = await runner.handle_command(
                "/delamain run write cmd.txt: hi"
            )
            assert "нужно подтверждение" in pending_text
            approval_id = sub.list_approvals(status="pending")[0]["id"]
            assert approval_id in pending_text

            listed = await runner.handle_command("/delamain approvals")
            assert approval_id in listed
            assert "write_file" in listed

            approved = await runner.handle_command(
                f"/delamain approve {approval_id}"
            )
            assert "✅" in approved
            assert (tmp_path / "workspace" / "cmd.txt").read_text(
                encoding="utf-8"
            ) == "hi"

            status = await runner.handle_command("/delamain status")
            assert "Approval: dangerous; pending=0" in status

            pending_text = await runner.handle_command(
                "/delamain run write rejected.txt: no"
            )
            assert "нужно подтверждение" in pending_text
            approval_id = sub.list_approvals(status="pending")[0]["id"]
            rejected = await runner.handle_command(
                f"/delamain reject {approval_id} not now"
            )
            assert "approval rejected" in rejected
            assert not (tmp_path / "workspace" / "rejected.txt").exists()

        asyncio.run(scenario())
    finally:
        sub.teardown()


def test_unknown_approval_id_is_reported(tmp_path: Path) -> None:
    sub = make_sub(tmp_path, approval_mode="dangerous")
    try:
        result = sub.approve("appr-doesnotexist")
        assert result["ok"] is False
        assert "not found" in (result["error"] or "")
    finally:
        sub.teardown()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
