import asyncio
from pathlib import Path

from src.core.subsystems.goal_manager import GoalSubsystem
from src.delamain.models import ActionRequest
from src.delamain.subsystem import DelamainSubsystem


class FakeAgent:
    """Minimal agent stand-in with the aliases used by GoalSubsystem."""

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
        self.refresh_aliases()
        return reward

    def get_goals_status(self):
        return self.goal_subsystem.get_status()

    def refresh_aliases(self) -> None:
        self.goals = self.goal_subsystem.goals
        self.active_goal = self.goal_subsystem.active_goal
        self.completed_goals = self.goal_subsystem.completed_goals
        self._goal_progress = self.goal_subsystem._goal_progress


class FakePlanner:
    """Planner double used to prove that a plan stays a proposal."""

    def __init__(self, plan):
        self._plan = list(plan)
        self.last_used = "primary"

    def plan(self, task: str):
        return list(self._plan)


def make_authoring(
    tmp_path: Path,
    *,
    title: str = "Написать отчёт",
    proposal_enabled: bool = True,
    bridge_enabled: bool = True,
    approval_mode: str = "off",
    **sub_kwargs,
):
    goal_subsystem = GoalSubsystem("AuthoringTest")
    goal_id = goal_subsystem.set_goal(title)
    agent = FakeAgent("AuthoringTest", goal_subsystem)
    params = {
        "agent_name": "AuthoringTest",
        "workspace": tmp_path / "workspace",
        "db_path": tmp_path / "memory.sqlite3",
        "enabled": True,
        "tick_interval": 1,
        "bridge_enabled": bridge_enabled,
        "goal_proposal_enabled": proposal_enabled,
        "approval_mode": approval_mode,
    }
    params.update(sub_kwargs)
    sub = DelamainSubsystem(**params)
    sub.setup({"agent": agent})
    agent.delamain = sub
    return sub, goal_subsystem, agent, goal_id


def test_manual_attach_stores_accepted_proposal_and_executes(tmp_path: Path) -> None:
    sub, goals, agent, goal_id = make_authoring(tmp_path)
    try:
        result = sub.attach_goal_execution(
            goal_id,
            "запиши в report.txt: ready",
            agent=agent,
        )
        assert result["ok"] is True
        assert result["message"] == "payload attached"

        goal = goals.get_goal(goal_id)
        assert goal["execution"]["command"] == "запиши в report.txt: ready"
        assert goal["execution"]["plan"][0]["action"] == "write_file"
        assert goal["execution_proposal"]["status"] == "accepted"
        assert goal["execution_proposal"]["source"] == "manual"
        assert goal["execution_proposal"]["files"] == ["report.txt"]
        assert goal["execution_proposal"]["dangerous_actions"] == ["write_file"]
        assert goal["execution_proposal"]["requires_approval"] is False
        assert goal["execution_decision"]["accepted"] is True

        # Authoring itself never queues an executable goal.
        assert sub.list_goals() == []
        sub.tick(1, {"agent": agent})
        assert (tmp_path / "workspace" / "report.txt").read_text(
            encoding="utf-8"
        ) == "ready"
        assert goals.get_goal(goal_id)["status"] == "completed"
        assert sub.list_goals()[0]["status"] == "done"
    finally:
        sub.teardown()


def test_authoring_does_not_open_runtime_when_delamain_is_disabled(
    tmp_path: Path,
) -> None:
    sub, goals, agent, goal_id = make_authoring(tmp_path, enabled=False)
    try:
        assert sub.runtime is None
        assert sub.authoring.enabled is False
        assert sub.status()["authoring"]["enabled"] is False
        result = sub.attach_goal_execution(
            goal_id,
            "запиши в report.txt: ready",
            agent=agent,
        )
        assert result["ok"] is False
        assert "Delamain-local is disabled" in result["error"]
        assert sub.runtime is None
        assert not (tmp_path / "workspace").exists()
        assert "execution" not in goals.get_goal(goal_id)
    finally:
        sub.teardown()


def test_manual_attach_refuses_duplicate_payload(tmp_path: Path) -> None:
    sub, goals, agent, goal_id = make_authoring(tmp_path)
    try:
        first = sub.attach_goal_execution(
            goal_id,
            "запиши в report.txt: one",
            agent=agent,
        )
        assert first["ok"] is True
        second = sub.attach_goal_execution(
            goal_id,
            "запиши в report.txt: two",
            agent=agent,
        )
        assert second["ok"] is False
        assert "already has an executable payload" in second["error"]
        assert goals.get_goal(goal_id)["execution"]["command"].endswith("one")
        assert len(sub.list_goals()) == 0
    finally:
        sub.teardown()


def test_pending_proposal_is_not_executed_until_accepted(tmp_path: Path) -> None:
    sub, goals, agent, goal_id = make_authoring(
        tmp_path,
        title="запиши в report.txt: ready",
    )
    try:
        result = sub.propose_goal_execution(goal_id, agent=agent)
        assert result["ok"] is True
        proposal = result["proposal"]
        assert proposal["status"] == "pending"
        assert proposal["plan"][0]["action"] == "write_file"
        assert proposal["files"] == ["report.txt"]
        assert proposal["dangerous_actions"] == ["write_file"]
        assert "execution" not in goals.get_goal(goal_id)

        # A proposal is inert: a tick cannot execute it.
        sub.tick(1, {"agent": agent})
        assert not (tmp_path / "workspace" / "report.txt").exists()
        assert sub.list_goals() == []

        accepted = sub.accept_goal_execution(goal_id, agent=agent)
        assert accepted["ok"] is True
        assert goals.get_goal(goal_id)["execution_proposal"]["status"] == "accepted"
        assert goals.get_goal(goal_id)["execution"]["plan"][0]["action"] == "write_file"

        sub.tick(2, {"agent": agent})
        assert (tmp_path / "workspace" / "report.txt").read_text(
            encoding="utf-8"
        ) == "ready"
        assert goals.get_goal(goal_id)["status"] == "completed"
    finally:
        sub.teardown()


def test_rejected_proposal_is_not_attached_or_executed(tmp_path: Path) -> None:
    sub, goals, agent, goal_id = make_authoring(
        tmp_path,
        title="запиши в report.txt: ready",
    )
    try:
        assert sub.propose_goal_execution(goal_id, agent=agent)["ok"] is True
        result = sub.reject_goal_execution(
            goal_id,
            reason="not now",
            agent=agent,
        )
        assert result["ok"] is True
        proposal = goals.get_goal(goal_id)["execution_proposal"]
        assert proposal["status"] == "rejected"
        assert proposal["reason"] == "not now"
        assert goals.get_goal(goal_id)["execution_decision"]["accepted"] is False
        assert "execution" not in goals.get_goal(goal_id)

        sub.tick(1, {"agent": agent})
        assert not (tmp_path / "workspace" / "report.txt").exists()
        assert sub.list_goals() == []
        assert goals.get_goal(goal_id)["status"] == "active"
    finally:
        sub.teardown()


def test_manual_preview_with_unknown_action_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class BrokenPreview:
        def plan(self, task: str):
            return [ActionRequest("rm_rf", {"path": "x"})]

    sub, goals, agent, goal_id = make_authoring(tmp_path)
    try:
        monkeypatch.setattr(
            "src.delamain.goal_authoring.HeuristicPlanner",
            lambda: BrokenPreview(),
        )
        result = sub.attach_goal_execution(
            goal_id,
            "сделай что-то",
            agent=agent,
        )
        assert result["ok"] is False
        assert "preview plan is invalid" in result["error"]
        assert "unknown action" in result["error"]
        assert "execution" not in goals.get_goal(goal_id)
        assert goals.get_goal(goal_id).get("execution_proposal") is None
        assert sub.list_goals() == []
    finally:
        sub.teardown()


def test_planner_proposals_are_disabled_by_default(tmp_path: Path) -> None:
    sub, goals, agent, goal_id = make_authoring(
        tmp_path,
        title="запиши в report.txt: ready",
        proposal_enabled=False,
    )
    try:
        result = sub.propose_goal_execution(goal_id, agent=agent)
        assert result["ok"] is False
        assert "disabled" in result["error"]
        assert "execution" not in goals.get_goal(goal_id)
        assert goals.get_goal(goal_id).get("execution_proposal") is None
    finally:
        sub.teardown()


def test_unknown_planner_action_is_rejected_before_attach(tmp_path: Path) -> None:
    sub, goals, agent, goal_id = make_authoring(
        tmp_path,
        title="сделай что-то",
    )
    try:
        sub.runtime.planner = FakePlanner([ActionRequest("rm_rf", {"path": "x"})])
        result = sub.propose_goal_execution(goal_id, agent=agent)
        assert result["ok"] is False
        assert "unknown action" in result["error"]
        assert result["proposal"]["status"] == "error"
        assert "execution" not in goals.get_goal(goal_id)
        assert sub.list_goals() == []
    finally:
        sub.teardown()


def test_dangerous_proposal_uses_existing_approval_gate(tmp_path: Path) -> None:
    sub, goals, agent, goal_id = make_authoring(
        tmp_path,
        title="запиши в report.txt: ready",
        approval_mode="dangerous",
    )
    try:
        result = sub.propose_goal_execution(goal_id, agent=agent)
        assert result["ok"] is True
        assert result["proposal"]["dangerous_actions"] == ["write_file"]
        assert result["proposal"]["requires_approval"] is True

        accepted = sub.accept_goal_execution(goal_id, agent=agent)
        assert accepted["ok"] is True
        sub.tick(1, {"agent": agent})

        assert not (tmp_path / "workspace" / "report.txt").exists()
        approvals = sub.list_approvals(status="pending")
        assert len(approvals) == 1
        assert goals.get_goal(goal_id)["status"] == "active"
        assert sub.list_goals()[0]["bridge_status"] == "waiting_approval"

        approved = sub.approve(approvals[0]["id"])
        assert approved["ok"] is True
        assert (tmp_path / "workspace" / "report.txt").read_text(
            encoding="utf-8"
        ) == "ready"
        assert goals.get_goal(goal_id)["status"] == "completed"
    finally:
        sub.teardown()


def test_heuristic_does_not_guess_a_plan_for_natural_language_title(
    tmp_path: Path,
) -> None:
    sub, goals, agent, goal_id = make_authoring(
        tmp_path,
        title="Выучить основы Python",
    )
    try:
        result = sub.propose_goal_execution(goal_id, agent=agent)
        assert result["ok"] is False
        assert "planner could not build a safe plan" in result["error"]
        assert "execution" not in goals.get_goal(goal_id)
        assert sub.list_goals() == []
    finally:
        sub.teardown()


def test_llm_like_plan_stays_a_proposal_until_accept(tmp_path: Path) -> None:
    sub, goals, agent, goal_id = make_authoring(
        tmp_path,
        title="напиши отчёт",
    )
    try:
        sub.runtime.planner = FakePlanner(
            [
                ActionRequest(
                    "write_file",
                    {"path": "report.txt", "content": "ready"},
                )
            ]
        )
        result = sub.propose_goal_execution(goal_id, agent=agent)
        assert result["ok"] is True
        assert result["proposal"]["source"] == "planner"
        assert result["proposal"]["status"] == "pending"
        assert "execution" not in goals.get_goal(goal_id)
        assert not (tmp_path / "workspace" / "report.txt").exists()
        assert sub.list_goals() == []

        assert sub.accept_goal_execution(goal_id, agent=agent)["ok"] is True
        sub.tick(1, {"agent": agent})
        assert (tmp_path / "workspace" / "report.txt").read_text(
            encoding="utf-8"
        ) == "ready"
    finally:
        sub.teardown()


def test_runner_goals_exec_show_and_list(tmp_path: Path) -> None:
    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    sub, goals, agent, goal_id = make_authoring(tmp_path)
    try:
        runner = AgentRunner(agent, EventBus(), watchdog=object())

        async def scenario() -> None:
            text = await runner.handle_command(
                f"/goals exec {goal_id} | запиши в report.txt: ready"
            )
            assert "Payload привязан" in text
            assert "write_file" in text
            assert "report.txt" in text

            listed = await runner.handle_command("/goals list")
            assert f"#{goal_id}" in listed
            assert "exec" in listed

            shown = await runner.handle_command(f"/goals show {goal_id}")
            assert "Executable: да" in shown
            assert "Proposal: accepted" in shown
            assert "запиши в report.txt: ready" in shown

            summary = await runner.handle_command("/goals")
            assert "Executable: да" in summary

            duplicate = await runner.handle_command(
                f"/goals exec {goal_id} | запиши в report.txt: two"
            )
            assert "already has an executable payload" in duplicate

        asyncio.run(scenario())
    finally:
        sub.teardown()


def test_runner_goals_exec_supports_success_predicate(tmp_path: Path) -> None:
    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    sub, goals, agent, goal_id = make_authoring(tmp_path)
    try:
        runner = AgentRunner(agent, EventBus(), watchdog=object())

        async def scenario() -> None:
            text = await runner.handle_command(
                f"/goals exec {goal_id} | запиши в report.txt: ready "
                f"| file_contains:report.txt:ready"
            )
            assert "Payload привязан" in text
            goal = goals.get_goal(goal_id)
            assert goal["execution"]["success_predicate"] == (
                "file_contains:report.txt:ready"
            )
            shown = await runner.handle_command(f"/goals show {goal_id}")
            assert "Predicate: file_contains:report.txt:ready" in shown

        asyncio.run(scenario())
    finally:
        sub.teardown()


def test_runner_goals_propose_accept_reject(tmp_path: Path) -> None:
    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    sub, goals, agent, goal_id = make_authoring(
        tmp_path,
        title="запиши в report.txt: ready",
    )
    try:
        runner = AgentRunner(agent, EventBus(), watchdog=object())

        async def scenario() -> None:
            proposed = await runner.handle_command(f"/goals propose {goal_id}")
            assert "Proposal" in proposed
            assert "accept" in proposed
            assert "reject" in proposed

            shown = await runner.handle_command(f"/goals show {goal_id}")
            assert "Proposal: pending" in shown
            assert "Опасные действия: write_file" in shown

            rejected = await runner.handle_command(
                f"/goals reject {goal_id} not now"
            )
            assert "отклонён" in rejected
            assert "payload" not in rejected.lower()
            assert "будет исполнен" not in rejected
            assert (
                goals.get_goal(goal_id)["execution_proposal"]["reason"]
                == "not now"
            )

            proposed_again = await runner.handle_command(
                f"/goals propose {goal_id}"
            )
            assert "Proposal" in proposed_again

            accepted = await runner.handle_command(f"/goals accept {goal_id}")
            assert "принят" in accepted
            assert goals.get_goal(goal_id)["execution_proposal"]["status"] == "accepted"

            listed = await runner.handle_command("/goals list")
            assert "proposal=accepted" in listed

        asyncio.run(scenario())
    finally:
        sub.teardown()


def test_authoring_status_is_visible_in_delamain_status(tmp_path: Path) -> None:
    sub, _, _, _ = make_authoring(tmp_path)
    try:
        status = sub.status()
        assert status["authoring"]["proposal_enabled"] is True
        assert status["authoring"]["enabled"] is True
    finally:
        sub.teardown()
