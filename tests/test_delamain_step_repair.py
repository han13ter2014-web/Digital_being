from pathlib import Path

from src.delamain.models import ActionRequest
from src.delamain.planner import PlannerError
from src.delamain.runtime import DelamainRuntime
from src.delamain.subsystem import DelamainSubsystem


class RepairPlanner:
    """Planner stand-in that only answers repair requests."""

    def __init__(self, plan):
        self.plan_result = plan
        self.replan_calls = 0
        self.contexts = []

    def plan(self, task: str):
        raise PlannerError("explicit plans must not call plan()")

    def replan(self, task: str, failure_context):
        self.replan_calls += 1
        self.contexts.append(dict(failure_context))
        if isinstance(self.plan_result, Exception):
            raise self.plan_result
        return list(self.plan_result)


class SequenceRepairPlanner:
    """Return a different repair plan for each failed segment."""

    def __init__(self, plans):
        self.plans = [list(plan) for plan in plans]
        self.replan_calls = 0
        self.contexts = []

    def plan(self, task: str):
        raise PlannerError("explicit plans must not call plan()")

    def replan(self, task: str, failure_context):
        self.replan_calls += 1
        self.contexts.append(dict(failure_context))
        if not self.plans:
            raise PlannerError("no repair plan left")
        return list(self.plans.pop(0))


class PlanThenRepairPlanner:
    """Plan a missing read, then repair it with a dangerous write."""

    def plan(self, task: str):
        return [ActionRequest("read_file", {"path": "missing.txt"})]

    def replan(self, task: str, failure_context):
        return [
            ActionRequest("write_file", {"path": "recovered.txt", "content": "ok"})
        ]


def make_sub(tmp_path: Path, **kwargs) -> DelamainSubsystem:
    params = {
        "agent_name": "StepRepairTest",
        "workspace": tmp_path / "workspace",
        "db_path": tmp_path / "memory.sqlite3",
        "enabled": True,
        "tick_interval": 1,
    }
    params.update(kwargs)
    return DelamainSubsystem(**params)


def test_step_repair_config_is_off_by_default_and_env_opt_in(
    tmp_path: Path, monkeypatch
) -> None:
    default_sub = make_sub(tmp_path / "default")
    try:
        assert default_sub.status()["step_repair"] == {
            "enabled": False,
            "max_step_repairs": 1,
            "max_repair_steps": 5,
        }
    finally:
        default_sub.teardown()

    monkeypatch.setenv("DELAMAIN_STEP_REPAIR_ENABLED", "1")
    monkeypatch.setenv("DELAMAIN_MAX_STEP_REPAIRS", "2")
    monkeypatch.setenv("DELAMAIN_MAX_REPAIR_STEPS", "7")
    env_sub = make_sub(tmp_path / "env")
    try:
        assert env_sub.status()["step_repair"] == {
            "enabled": True,
            "max_step_repairs": 2,
            "max_repair_steps": 7,
        }
    finally:
        env_sub.teardown()


def test_step_repair_is_off_by_default(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    planner = RepairPlanner(
        [ActionRequest("write_file", {"path": "recovered.txt", "content": "ok"})]
    )
    with DelamainRuntime(root, tmp_path / "memory.sqlite3", planner=planner) as runtime:
        result = runtime.run_task(
            "missing without repair",
            task_id="off-by-default",
            plan=[ActionRequest("read_file", {"path": "missing.txt"})],
        )

        assert result.ok is False
        assert result.repair_count == 0
        assert planner.replan_calls == 0
        assert not (root / "recovered.txt").exists()
        assert [item["action"] for item in runtime.history(task_id="off-by-default")] == [
            "task.start",
            "read_file",
            "task.finish",
        ]


def test_step_repair_replaces_the_remaining_plan(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    planner = RepairPlanner(
        [ActionRequest("write_file", {"path": "recovered.txt", "content": "ok"})]
    )
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        planner=planner,
        approval_mode="off",
        step_repair_enabled=True,
        max_step_repairs=1,
        max_repair_steps=5,
    ) as runtime:
        result = runtime.run_task(
            "replace the remainder",
            task_id="replacement",
            plan=[
                ActionRequest(
                    "write_file", {"path": "completed.txt", "content": "done"}
                ),
                ActionRequest("read_file", {"path": "missing.txt"}),
                ActionRequest(
                    "write_file", {"path": "original-tail.txt", "content": "no"}
                ),
            ],
        )

        assert result.ok is True
        assert result.repair_count == 1
        assert result.steps_before == 0
        assert len(result.steps) == 3
        assert [step["action"] for step in result.planned_actions] == [
            "write_file",
            "read_file",
            "write_file",
        ]
        assert result.effective_actions == [
            {"action": "write_file", "args": {"path": "completed.txt", "content": "done"}},
            {"action": "write_file", "args": {"path": "recovered.txt", "content": "ok"}},
        ]
        assert (root / "completed.txt").read_text(encoding="utf-8") == "done"
        assert (root / "recovered.txt").read_text(encoding="utf-8") == "ok"
        assert not (root / "original-tail.txt").exists()

        assert planner.replan_calls == 1
        context = planner.contexts[0]
        assert context["stage"] == "action"
        assert context["failed_step"] == 2
        assert context["action"] == "read_file"
        assert context["args"] == {"path": "missing.txt"}
        assert "missing.txt" in context["error"]
        assert context["completed_steps"] == [
            {"action": "write_file", "args": {"path": "completed.txt", "content": "done"}}
        ]
        assert context["remaining_steps"] == [
            {"action": "write_file", "args": {"path": "original-tail.txt", "content": "no"}}
        ]
        assert context["repair_count"] == 0

        assert [item["action"] for item in runtime.history(task_id="replacement")] == [
            "task.start",
            "write_file",
            "read_file",
            "task.repair",
            "write_file",
            "task.finish",
        ]


def test_step_repair_rejects_repeating_an_attempted_step(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    planner = RepairPlanner(
        [
            ActionRequest("write_file", {"path": "completed.txt", "content": "done"}),
            ActionRequest("write_file", {"path": "recovered.txt", "content": "ok"}),
        ]
    )
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        planner=planner,
        approval_mode="off",
        step_repair_enabled=True,
    ) as runtime:
        result = runtime.run_task(
            "reject duplicate",
            task_id="duplicate",
            plan=[
                ActionRequest(
                    "write_file", {"path": "completed.txt", "content": "done"}
                ),
                ActionRequest("read_file", {"path": "missing.txt"}),
            ],
        )

        assert result.ok is False
        assert result.repair_count == 0
        assert "missing.txt" in (result.error or "")
        assert not (root / "recovered.txt").exists()
        rejected = [
            item
            for item in runtime.history(task_id="duplicate")
            if item["action"] == "task.repair.rejected"
        ]
        assert len(rejected) == 1
        assert "repeats an already attempted step" in rejected[0]["error"]


def test_step_repair_rejects_a_plan_that_is_too_large(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    planner = RepairPlanner(
        [
            ActionRequest("read_file", {"path": "one.txt"}),
            ActionRequest("read_file", {"path": "two.txt"}),
        ]
    )
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        planner=planner,
        step_repair_enabled=True,
        max_repair_steps=1,
    ) as runtime:
        result = runtime.run_task(
            "reject large repair",
            task_id="large-repair",
            plan=[ActionRequest("read_file", {"path": "missing.txt"})],
        )

        assert result.ok is False
        assert result.repair_count == 0
        rejected = [
            item
            for item in runtime.history(task_id="large-repair")
            if item["action"] == "task.repair.rejected"
        ]
        assert len(rejected) == 1
        assert "too many steps" in rejected[0]["error"]


def test_step_repair_budget_stops_after_one_segment(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    planner = RepairPlanner(
        [
            ActionRequest("read_file", {"path": "missing-2.txt"}),
            ActionRequest("read_file", {"path": "missing-3.txt"}),
        ]
    )
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        planner=planner,
        step_repair_enabled=True,
        max_step_repairs=1,
    ) as runtime:
        result = runtime.run_task(
            "one repair only",
            task_id="budget",
            plan=[ActionRequest("read_file", {"path": "missing-1.txt"})],
        )

        assert result.ok is False
        assert result.repair_count == 1
        assert planner.replan_calls == 1
        assert [step["action"] for step in result.planned_actions] == [
            "read_file",
            "read_file",
        ]
        assert [step["args"]["path"] for step in result.planned_actions] == [
            "missing-1.txt",
            "missing-2.txt",
        ]
        assert [item["action"] for item in runtime.history(task_id="budget")] == [
            "task.start",
            "read_file",
            "task.repair",
            "read_file",
            "task.finish",
        ]


def test_two_repair_segments_can_follow_each_other(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    planner = SequenceRepairPlanner(
        [
            [
                ActionRequest("write_file", {"path": "first-fix.txt", "content": "1"}),
                ActionRequest("read_file", {"path": "missing-2.txt"}),
            ],
            [
                ActionRequest("write_file", {"path": "second-fix.txt", "content": "2"}),
            ],
        ]
    )
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        planner=planner,
        approval_mode="off",
        step_repair_enabled=True,
        max_step_repairs=2,
    ) as runtime:
        result = runtime.run_task(
            "two segments",
            task_id="two-segments",
            plan=[ActionRequest("read_file", {"path": "missing-1.txt"})],
        )

        assert result.ok is True
        assert result.repair_count == 2
        assert [step["action"] for step in result.planned_actions] == [
            "read_file",
            "write_file",
            "read_file",
            "write_file",
        ]
        assert result.effective_actions == [
            {"action": "write_file", "args": {"path": "first-fix.txt", "content": "1"}},
            {"action": "write_file", "args": {"path": "second-fix.txt", "content": "2"}},
        ]
        assert planner.replan_calls == 2
        assert planner.contexts[0]["repair_count"] == 0
        assert planner.contexts[1]["repair_count"] == 1
        assert planner.contexts[1]["completed_steps"] == [
            {"action": "write_file", "args": {"path": "first-fix.txt", "content": "1"}}
        ]
        assert planner.contexts[1]["remaining_steps"] == []
        assert [item["action"] for item in runtime.history(task_id="two-segments")] == [
            "task.start",
            "read_file",
            "task.repair",
            "write_file",
            "read_file",
            "task.repair",
            "write_file",
            "task.finish",
        ]


def test_repair_context_does_not_mark_failed_steps_completed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    planner = SequenceRepairPlanner(
        [
            [ActionRequest("read_file", {"path": "missing-2.txt"})],
            [ActionRequest("write_file", {"path": "fixed.txt", "content": "ok"})],
        ]
    )
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        planner=planner,
        approval_mode="off",
        step_repair_enabled=True,
        max_step_repairs=2,
    ) as runtime:
        result = runtime.run_task(
            "failed steps are not completed",
            task_id="failed-not-completed",
            plan=[ActionRequest("read_file", {"path": "missing-1.txt"})],
        )

        assert result.ok is True
        assert planner.contexts[1]["completed_steps"] == []
        assert planner.contexts[1]["failed_step"] == 2
        assert planner.contexts[1]["action"] == "read_file"
        assert planner.contexts[1]["repair_count"] == 1
        assert (root / "fixed.txt").read_text(encoding="utf-8") == "ok"


def test_step_repair_rejects_unknown_action(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    planner = RepairPlanner([ActionRequest("does_not_exist", {})])
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        planner=planner,
        step_repair_enabled=True,
    ) as runtime:
        result = runtime.run_task(
            "unknown repair action",
            task_id="unknown-action",
            plan=[ActionRequest("read_file", {"path": "missing.txt"})],
        )

        assert result.ok is False
        assert result.repair_count == 0
        rejected = [
            item
            for item in runtime.history(task_id="unknown-action")
            if item["action"] == "task.repair.rejected"
        ]
        assert len(rejected) == 1
        assert "unknown action" in rejected[0]["error"]


def test_step_repair_rejects_internal_duplicate(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    step = ActionRequest("write_file", {"path": "same.txt", "content": "ok"})
    planner = RepairPlanner([step, step])
    with DelamainRuntime(
        root,
        tmp_path / "memory.sqlite3",
        planner=planner,
        approval_mode="off",
        step_repair_enabled=True,
    ) as runtime:
        result = runtime.run_task(
            "internal duplicate",
            task_id="internal-duplicate",
            plan=[ActionRequest("read_file", {"path": "missing.txt"})],
        )

        assert result.ok is False
        assert result.repair_count == 0
        assert not (root / "same.txt").exists()
        rejected = [
            item
            for item in runtime.history(task_id="internal-duplicate")
            if item["action"] == "task.repair.rejected"
        ]
        assert len(rejected) == 1
        assert "duplicate step" in rejected[0]["error"]


def test_repair_approval_resumes_with_completed_steps_preserved(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    db_path = tmp_path / "memory.sqlite3"
    planner = RepairPlanner(
        [ActionRequest("write_file", {"path": "recovered.txt", "content": "ok"})]
    )
    with DelamainRuntime(
        root,
        db_path,
        planner=planner,
        approval_mode="dangerous",
        step_repair_enabled=True,
    ) as runtime:
        pending = runtime.run_task(
            "repair approval",
            task_id="repair-approval",
            plan=[ActionRequest("read_file", {"path": "missing.txt"})],
        )

        assert pending.ok is False
        assert pending.approval_id is None
        assert pending.pending_approval is not None
        assert pending.repair_count == 1
        assert pending.steps_before == 0
        assert pending.effective_actions == []
        approval_id = pending.pending_approval["id"]
        stored = runtime.memory.get_approval(approval_id)
        assert stored is not None
        assert stored["metadata"]["kind"] == "step_repair"
        assert stored["metadata"]["prior_steps"] == 1
        assert stored["metadata"]["repair_count"] == 1
        assert stored["metadata"]["failed_step"] == 1
        assert stored["metadata"]["prior_actions"] == [
            {"action": "read_file", "args": {"path": "missing.txt"}}
        ]
        assert stored["metadata"]["prior_effective_actions"] == []
        assert not (root / "recovered.txt").exists()
        assert [item["action"] for item in runtime.history(task_id="repair-approval")] == [
            "task.start",
            "read_file",
            "task.repair",
            "approval.requested",
        ]

    with DelamainRuntime(
        root,
        db_path,
        planner=RepairPlanner([]),
        approval_mode="dangerous",
        step_repair_enabled=True,
    ) as runtime:
        stored = runtime.memory.get_approval(approval_id)
        assert stored is not None
        assert stored["status"] == "pending"
        runtime.memory.approve_approval(approval_id)
        result = runtime.run_approved(approval_id)

        assert result.ok is True
        assert result.approval_id == approval_id
        assert result.steps_before == 1
        assert result.repair_count == 1
        assert len(result.steps) == 1
        assert result.planned_actions == [
            {"action": "read_file", "args": {"path": "missing.txt"}},
            {"action": "write_file", "args": {"path": "recovered.txt", "content": "ok"}},
        ]
        assert result.effective_actions == [
            {"action": "write_file", "args": {"path": "recovered.txt", "content": "ok"}}
        ]
        assert (root / "recovered.txt").read_text(encoding="utf-8") == "ok"
        assert [item["action"] for item in runtime.history(task_id="repair-approval")] == [
            "task.start",
            "read_file",
            "task.repair",
            "approval.requested",
            "task.resume",
            "write_file",
            "task.finish",
        ]


def test_subsystem_repair_approval_survives_restart(tmp_path: Path) -> None:
    sub = make_sub(
        tmp_path,
        approval_mode="dangerous",
        step_repair_enabled=True,
    )
    try:
        sub.queue_goal(
            "restart repair",
            plan=[ActionRequest("read_file", {"path": "missing.txt"})],
        )
        sub.runtime.planner = RepairPlanner(
            [ActionRequest("write_file", {"path": "recovered.txt", "content": "ok"})]
        )
        first = sub.tick(1, {})["events"][0]["data"]
        approval_id = first["pending_approval"]["id"]
    finally:
        sub.teardown()

    restarted = make_sub(
        tmp_path,
        approval_mode="dangerous",
        step_repair_enabled=True,
    )
    try:
        assert restarted.list_goals()[0]["status"] == "pending"
        assert len(restarted.list_approvals(status="pending")) == 1
        assert not (tmp_path / "workspace" / "recovered.txt").exists()

        approved = restarted.approve(approval_id)

        assert approved["ok"] is True
        assert approved["steps"] == 2
        assert approved["effective_steps"] == 1
        assert approved["step_repairs"] == 1
        assert restarted.list_goals()[0]["status"] == "done"
        assert (tmp_path / "workspace" / "recovered.txt").read_text(
            encoding="utf-8"
        ) == "ok"
        skill = restarted.runtime.memory.get_skill("restart repair")
        assert skill is not None
        assert [step["action"] for step in skill["plan"]["steps"]] == ["write_file"]
    finally:
        restarted.teardown()


def test_subsystem_records_effective_skill_after_repair(tmp_path: Path) -> None:
    sub = make_sub(tmp_path, step_repair_enabled=True)
    try:
        sub.queue_goal(
            "repair skill",
            plan=[
                ActionRequest(
                    "write_file", {"path": "completed.txt", "content": "done"}
                ),
                ActionRequest("read_file", {"path": "missing.txt"}),
                ActionRequest(
                    "write_file", {"path": "original-tail.txt", "content": "no"}
                ),
            ],
        )
        sub.runtime.planner = RepairPlanner(
            [ActionRequest("write_file", {"path": "recovered.txt", "content": "ok"})]
        )

        data = sub.tick(1, {})["events"][0]["data"]

        assert data["ok"] is True
        assert data["steps"] == 3
        assert data["effective_steps"] == 2
        assert data["step_repairs"] == 1
        stored = sub.list_goals()[0]
        assert stored["status"] == "done"
        assert stored["metadata"]["step_repairs"] == 1
        assert sub.status()["step_repair"] == {
            "enabled": True,
            "max_step_repairs": 1,
            "max_repair_steps": 5,
        }
        skill = sub.runtime.memory.get_skill("repair skill")
        assert skill is not None
        assert skill["success_count"] == 1
        assert [step["action"] for step in skill["plan"]["steps"]] == [
            "write_file",
            "write_file",
        ]
        assert not (tmp_path / "workspace" / "original-tail.txt").exists()
    finally:
        sub.teardown()


def test_repair_approval_created_while_resuming_initial_approval(
    tmp_path: Path,
) -> None:
    sub = make_sub(
        tmp_path,
        approval_mode="dangerous",
        step_repair_enabled=True,
    )
    try:
        sub.queue_goal(
            "approved then repaired",
            plan=[
                ActionRequest(
                    "write_file", {"path": "marker.txt", "content": "kept"}
                ),
                ActionRequest("read_file", {"path": "missing.txt"}),
            ],
        )
        sub.runtime.planner = RepairPlanner(
            [ActionRequest("write_file", {"path": "recovered.txt", "content": "ok"})]
        )

        first = sub.tick(1, {})["events"][0]["data"]
        assert first["pending_approval"] is not None
        initial_id = first["pending_approval"]["id"]
        assert not (tmp_path / "workspace" / "marker.txt").exists()

        interrupted = sub.approve(initial_id)

        assert interrupted["ok"] is False
        assert interrupted["steps"] == 2
        assert interrupted["effective_steps"] == 1
        assert interrupted["step_repairs"] == 1
        assert interrupted["pending_approval"]["repair"] is True
        repair_id = interrupted["pending_approval"]["id"]
        assert repair_id != initial_id
        assert (tmp_path / "workspace" / "marker.txt").read_text(
            encoding="utf-8"
        ) == "kept"
        assert not (tmp_path / "workspace" / "recovered.txt").exists()
        assert sub.list_goals()[0]["status"] == "pending"
        assert sub.list_goals()[0]["metadata"]["approval_id"] == repair_id

        completed = sub.approve(repair_id)

        assert completed["ok"] is True
        assert completed["steps"] == 3
        assert completed["effective_steps"] == 2
        assert completed["step_repairs"] == 1
        assert completed["approval_status"] == "consumed"
        assert (tmp_path / "workspace" / "recovered.txt").read_text(
            encoding="utf-8"
        ) == "ok"
        skill = sub.runtime.memory.get_skill("approved then repaired")
        assert skill is not None
        assert [step["action"] for step in skill["plan"]["steps"]] == [
            "write_file",
            "write_file",
        ]
    finally:
        sub.teardown()


def test_subsystem_repair_approval_rejection_preserves_progress(
    tmp_path: Path,
) -> None:
    sub = make_sub(
        tmp_path,
        approval_mode="dangerous",
        step_repair_enabled=True,
    )
    try:
        sub.queue_goal(
            "reject repair",
            plan=[ActionRequest("read_file", {"path": "missing.txt"})],
        )
        sub.runtime.planner = RepairPlanner(
            [ActionRequest("write_file", {"path": "recovered.txt", "content": "ok"})]
        )

        data = sub.tick(1, {})["events"][0]["data"]
        approval_id = data["pending_approval"]["id"]
        rejected = sub.reject(approval_id, "not now")

        assert rejected["ok"] is False
        assert rejected["steps"] == 1
        assert rejected["effective_steps"] == 0
        assert rejected["step_repairs"] == 1
        assert rejected["approval_status"] == "rejected"
        assert not (tmp_path / "workspace" / "recovered.txt").exists()
        stored = sub.list_goals()[0]
        assert stored["status"] == "failed"
        assert stored["metadata"]["step_repairs"] == 1
        assert stored["metadata"]["approval_status"] == "rejected"
    finally:
        sub.teardown()


def test_subsystem_repair_approval_completes_goal_and_skill(
    tmp_path: Path,
) -> None:
    sub = make_sub(
        tmp_path,
        approval_mode="dangerous",
        step_repair_enabled=True,
    )
    try:
        sub.queue_goal(
            "repair approval",
            plan=[ActionRequest("read_file", {"path": "missing.txt"})],
        )
        sub.runtime.planner = RepairPlanner(
            [ActionRequest("write_file", {"path": "recovered.txt", "content": "ok"})]
        )

        data = sub.tick(1, {})["events"][0]["data"]
        assert data["ok"] is False
        assert data["step_repairs"] == 1
        assert data["pending_approval"]["repair"] is True
        assert data["pending_approval"]["prior_steps"] == 1
        approval_id = data["pending_approval"]["id"]
        assert sub.list_goals()[0]["status"] == "pending"
        assert sub.list_goals()[0]["metadata"]["step_repairs"] == 1
        assert (
            sub.list_approvals(status="pending")[0]["metadata"]["kind"]
            == "step_repair"
        )
        assert sub.tick(2, {}) is None
        assert len(sub.list_approvals(status="pending")) == 1

        approved = sub.approve(approval_id)

        assert approved["ok"] is True
        assert approved["goal_id"] == data["goal_id"]
        assert approved["steps"] == 2
        assert approved["effective_steps"] == 1
        assert approved["step_repairs"] == 1
        assert approved["approval_status"] == "consumed"
        assert (tmp_path / "workspace" / "recovered.txt").read_text(
            encoding="utf-8"
        ) == "ok"
        stored = sub.list_goals()[0]
        assert stored["status"] == "done"
        assert stored["metadata"]["step_repairs"] == 1
        skill = sub.runtime.memory.get_skill("repair approval")
        assert skill is not None
        assert skill["success_count"] == 1
        assert [step["action"] for step in skill["plan"]["steps"]] == ["write_file"]
    finally:
        sub.teardown()


def test_agent_runner_shows_repair_status_and_pending_note(
    tmp_path: Path,
) -> None:
    import asyncio

    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    class FakeAgent:
        name = "FakeRepairAgent"

        def __init__(self, delamain: DelamainSubsystem) -> None:
            self.energy = 100.0
            self.cycle_count = 0
            self.delamain = delamain

    sub = make_sub(
        tmp_path,
        approval_mode="dangerous",
        step_repair_enabled=True,
    )
    try:
        sub._ensure_runtime().planner = PlanThenRepairPlanner()
        runner = AgentRunner(FakeAgent(sub), EventBus(), watchdog=object())

        async def scenario() -> None:
            pending_text = await runner.handle_command(
                "/delamain run read missing"
            )
            assert "нужно подтверждение" in pending_text
            assert "Это repair-план" in pending_text
            assert "уже выполнено шагов: 1" in pending_text

            status = await runner.handle_command("/delamain status")
            assert "Repair: on, max_segments=1, max_steps=5" in status
            assert "repair=1" in status

            listed = await runner.handle_command("/delamain approvals")
            assert "repair-план" in listed

        asyncio.run(scenario())
    finally:
        sub.teardown()
