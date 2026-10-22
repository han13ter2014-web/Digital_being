from pathlib import Path

from src.core.subsystems.goal_manager import GoalSubsystem
from src.delamain.subsystem import DelamainSubsystem


class FakeAgent:
    """Small agent stand-in for the bridge tests.

    It mirrors the aliases that ``DigitalBeing`` keeps in sync with
    ``GoalSubsystem`` without constructing the full (and slow) agent.
    """

    def __init__(self, name: str, goal_subsystem: GoalSubsystem) -> None:
        self.name = name
        self.energy = 100.0
        self.cycle_count = 0
        self.intelligence = 1
        self.mental_models = type("MentalModels", (), {"concepts": {}})()
        self.goal_subsystem = goal_subsystem
        self.goals = goal_subsystem.goals
        self.active_goal = goal_subsystem.active_goal
        self.completed_goals = goal_subsystem.completed_goals
        self._goal_progress = goal_subsystem._goal_progress
        self.delamain = None

    def complete_goal(self, goal_id=None):
        reward = self.goal_subsystem.complete_goal(goal_id)
        self.active_goal = self.goal_subsystem.active_goal
        self.completed_goals = self.goal_subsystem.completed_goals
        return reward

    def get_goals_status(self):
        return self.goal_subsystem.get_status()

    def refresh_aliases(self) -> None:
        self.goals = self.goal_subsystem.goals
        self.active_goal = self.goal_subsystem.active_goal
        self.completed_goals = self.goal_subsystem.completed_goals
        self._goal_progress = self.goal_subsystem._goal_progress


def make_agent(
    tmp_path: Path,
    *,
    title: str = "Написать отчёт",
    command: str | None = "запиши в report.txt: ready",
    success_predicate: str = "",
    bridge_enabled: bool = True,
    tick_interval: int = 1,
    **sub_kwargs,
):
    goal_subsystem = GoalSubsystem("BridgeTest")
    goal_id = goal_subsystem.set_goal(
        title,
        command=command,
        success_predicate=success_predicate,
    )
    agent = FakeAgent("BridgeTest", goal_subsystem)
    params = {
        "agent_name": "BridgeTest",
        "workspace": tmp_path / "workspace",
        "db_path": tmp_path / "memory.sqlite3",
        "enabled": True,
        "tick_interval": tick_interval,
        "bridge_enabled": bridge_enabled,
    }
    params.update(sub_kwargs)
    sub = DelamainSubsystem(**params)
    sub.setup({"agent": agent})
    agent.delamain = sub
    return sub, goal_subsystem, agent, goal_id


def test_bridge_disabled_does_not_queue_or_write(tmp_path: Path) -> None:
    sub, goals, agent, _ = make_agent(tmp_path, bridge_enabled=False)
    try:
        assert sub.tick(1, {"agent": agent}) is None
        assert sub.list_goals() == []
        assert "delamain_goal_id" not in goals.goals[0]
        assert not (tmp_path / "workspace" / "report.txt").exists()
    finally:
        sub.teardown()


def test_bridge_queues_one_goal_and_does_not_duplicate(tmp_path: Path) -> None:
    sub, goals, agent, goal_id = make_agent(tmp_path, tick_interval=20)
    try:
        sub.tick(1, {"agent": agent})
        sub.tick(2, {"agent": agent})

        stored = sub.list_goals()
        assert len(stored) == 1
        assert stored[0]["title"] == "Написать отчёт"
        assert stored[0]["metadata"]["bridge_source"] == "goal_subsystem"
        assert stored[0]["metadata"]["cognitive_goal_id"] == goal_id
        assert goals.goals[0]["delamain_goal_id"] == stored[0]["id"]
        assert goals.goals[0]["delamain_bridge"]["status"] == "pending"
    finally:
        sub.teardown()


def test_success_completes_cognitive_goal_and_progress(tmp_path: Path) -> None:
    sub, goals, agent, goal_id = make_agent(
        tmp_path,
        success_predicate="file_contains:report.txt:ready",
    )
    try:
        sub.tick(1, {"agent": agent})

        assert (tmp_path / "workspace" / "report.txt").read_text(
            encoding="utf-8"
        ) == "ready"
        stored = sub.list_goals()
        assert stored[0]["status"] == "done"
        assert stored[0]["bridge_status"] == "done"

        cognitive = goals.goals[0]
        assert cognitive["status"] == "completed"
        assert cognitive["delamain_bridge"]["status"] == "done"
        assert cognitive["delamain_bridge"]["predicate_ok"] is True
        assert goals.completed_goals == 1
        assert goals._goal_progress[goal_id]["percentage"] == 100
    finally:
        sub.teardown()


def test_pending_approval_keeps_cognitive_goal_active(tmp_path: Path) -> None:
    sub, goals, agent, _ = make_agent(
        tmp_path,
        approval_mode="dangerous",
    )
    try:
        sub.tick(1, {"agent": agent})
        approvals = sub.list_approvals(status="pending")
        assert len(approvals) == 1

        stored = sub.list_goals()[0]
        assert stored["status"] == "pending"
        assert stored["bridge_status"] == "waiting_approval"
        assert stored["metadata"]["approval_id"] == approvals[0]["id"]

        cognitive = goals.goals[0]
        assert cognitive["status"] == "active"
        assert cognitive["delamain_bridge"]["status"] == "waiting_approval"
        assert cognitive["delamain_bridge"]["approval_id"] == approvals[0]["id"]

        # Repeated ticks must not create a second approval or executable goal.
        sub.tick(2, {"agent": agent})
        assert len(sub.list_goals()) == 1
        assert len(sub.list_approvals(status="pending")) == 1
    finally:
        sub.teardown()


def test_approve_completes_cognitive_goal(tmp_path: Path) -> None:
    sub, goals, agent, _ = make_agent(
        tmp_path,
        approval_mode="dangerous",
    )
    try:
        sub.tick(1, {"agent": agent})
        approval_id = sub.list_approvals(status="pending")[0]["id"]

        result = sub.approve(approval_id)
        assert result["ok"] is True
        assert (tmp_path / "workspace" / "report.txt").read_text(
            encoding="utf-8"
        ) == "ready"

        assert goals.goals[0]["status"] == "completed"
        assert goals.goals[0]["delamain_bridge"]["status"] == "done"
        assert sub.list_goals()[0]["bridge_status"] == "done"
    finally:
        sub.teardown()


def test_reject_fails_cognitive_goal_without_skill_failure(tmp_path: Path) -> None:
    sub, goals, agent, _ = make_agent(
        tmp_path,
        approval_mode="dangerous",
    )
    try:
        sub.tick(1, {"agent": agent})
        approval_id = sub.list_approvals(status="pending")[0]["id"]

        sub.reject(approval_id, "not now")

        cognitive = goals.goals[0]
        assert cognitive["status"] == "failed"
        assert "not now" in cognitive["failure_reason"]
        assert cognitive["delamain_bridge"]["status"] == "failed"
        assert "approval rejected" in cognitive["delamain_bridge"]["message"]
        assert not (tmp_path / "workspace" / "report.txt").exists()
        # A rejected plan was never attempted: no skill success or failure.
        assert sub.runtime.memory.get_skill("Написать отчёт") is None
        assert goals.active_goal is None
        assert agent.active_goal is None
    finally:
        sub.teardown()


def test_success_predicate_failure_marks_bridge_failed(tmp_path: Path) -> None:
    sub, goals, agent, _ = make_agent(
        tmp_path,
        command="запиши в report.txt: wrong",
        success_predicate="file_contains:report.txt:ready",
    )
    try:
        sub.tick(1, {"agent": agent})

        stored = sub.list_goals()[0]
        assert stored["status"] == "done"
        assert stored["bridge_status"] == "failed"
        assert goals.goals[0]["status"] == "failed"
        link = goals.goals[0]["delamain_bridge"]
        assert link["status"] == "failed"
        assert link["predicate_ok"] is False
        assert "success predicate not met" in link["message"]
        # The executable action did succeed, so Delamain keeps its skill win.
        skill = sub.runtime.memory.get_skill("Написать отчёт")
        assert skill is not None
        assert skill["success_count"] == 1
    finally:
        sub.teardown()


def test_lost_cognitive_link_reuses_existing_goal(tmp_path: Path) -> None:
    sub, goals, agent, _ = make_agent(tmp_path, tick_interval=20)
    try:
        sub.tick(1, {"agent": agent})
        original = sub.list_goals()[0]
        assert goals.goals[0]["delamain_goal_id"] == original["id"]

        for key in ("delamain_goal_id", "delamain_bridge", "delamain_status"):
            goals.goals[0].pop(key, None)

        sub.tick(2, {"agent": agent})
        stored = sub.list_goals()
        assert len(stored) == 1
        assert stored[0]["id"] == original["id"]
        assert goals.goals[0]["delamain_goal_id"] == original["id"]
    finally:
        sub.teardown()


def test_bridge_ignores_goal_without_execution_payload(tmp_path: Path) -> None:
    sub, goals, agent, _ = make_agent(tmp_path, command=None)
    try:
        assert sub.tick(1, {"agent": agent}) is None
        assert sub.list_goals() == []
        assert "delamain_bridge" not in goals.goals[0]
    finally:
        sub.teardown()


def test_bridge_summary_in_status(tmp_path: Path) -> None:
    sub, goals, agent, goal_id = make_agent(
        tmp_path,
        approval_mode="dangerous",
    )
    try:
        sub.tick(1, {"agent": agent})
        status = sub.status()
        assert status["bridge"]["enabled"] is True
        assert status["bridge"]["linked"] == 1
        assert status["bridge"]["counts"]["waiting_approval"] == 1

        stored = sub.list_goals()[0]
        assert stored["cognitive_goal_id"] == goal_id
        assert stored["bridge_status"] == "waiting_approval"
    finally:
        sub.teardown()


def test_runner_shows_bridge_link_and_status(tmp_path: Path) -> None:
    import asyncio

    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    sub, goals, agent, goal_id = make_agent(
        tmp_path,
        approval_mode="dangerous",
    )
    try:
        sub.tick(1, {"agent": agent})
        runner = AgentRunner(agent, EventBus(), watchdog=object())

        async def scenario() -> None:
            listed = await runner.handle_command("/delamain goals")
            assert f"cognitive=#{goal_id}/waiting_approval" in listed
            assert "approval=" in listed

            goals_text = await runner.handle_command("/goals")
            assert "Delamain: goal #" in goals_text
            assert "waiting_approval" in goals_text

            status_text = await runner.handle_command("/status")
            assert "Delamain-цели: linked=1" in status_text
            assert "waiting=1" in status_text

        asyncio.run(scenario())
    finally:
        sub.teardown()


def test_next_cognitive_goal_is_linked_after_completion(tmp_path: Path) -> None:
    sub, goals, agent, first_id = make_agent(
        tmp_path,
        command="запиши в first.txt: one",
    )
    try:
        second_id = goals.set_goal(
            "Второй шаг",
            command="запиши в second.txt: two",
        )
        agent.refresh_aliases()

        sub.tick(1, {"agent": agent})
        first = next(g for g in goals.goals if g["id"] == first_id)
        second = next(g for g in goals.goals if g["id"] == second_id)
        assert first["status"] == "completed"
        assert second["status"] == "active"
        assert second["delamain_bridge"]["status"] == "pending"
        assert len(sub.list_goals()) == 2

        sub.tick(2, {"agent": agent})
        assert second["status"] == "completed"
        assert goals.completed_goals == 2
        assert {goal["status"] for goal in sub.list_goals()} == {"done"}
    finally:
        sub.teardown()


def test_evaluate_success_predicate_is_explicit_and_fail_closed(tmp_path: Path) -> None:
    from src.delamain.goal_bridge import evaluate_success_predicate
    from src.delamain.sandbox import Sandbox

    sandbox = Sandbox(tmp_path / "workspace")
    sandbox.write_text("report.txt", "ready")

    assert evaluate_success_predicate("", sandbox=sandbox)[0] is True
    assert evaluate_success_predicate("file_exists:report.txt", sandbox=sandbox)[0] is True
    assert evaluate_success_predicate(
        "file_contains:report.txt:ready", sandbox=sandbox
    )[0] is True
    ok, reason = evaluate_success_predicate(
        "file_contains:report.txt:missing", sandbox=sandbox
    )
    assert ok is False
    assert "does not contain" in reason
    ok, reason = evaluate_success_predicate("__import__('os')", sandbox=sandbox)
    assert ok is False
    assert "unsupported" in reason
