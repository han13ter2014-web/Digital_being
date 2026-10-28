"""Stage 19: Delamain goal attempts share the core action budget."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from src.core.action_budget import ActionBudget
from src.core.effector_port import EffectorRequest, EffectorStatus
from src.delamain.subsystem import DelamainSubsystem


class _AgentStub:
    def __init__(
        self,
        energy: float,
        *,
        enabled: bool = True,
        min_reserve: float = 5.0,
        max_action_cost: float = 20.0,
        essential_actions: Optional[Iterable[str]] = None,
    ) -> None:
        self.energy = float(energy)
        kwargs: Dict[str, Any] = {
            "enabled": enabled,
            "min_reserve": min_reserve,
            "max_action_cost": max_action_cost,
        }
        if essential_actions is not None:
            kwargs["essential_actions"] = essential_actions
        self.action_budget = ActionBudget(
            lambda: self.energy,
            lambda value: setattr(self, "energy", value),
            **kwargs,
        )


def make_sub(tmp_path: Path, **kwargs: Any) -> DelamainSubsystem:
    params: Dict[str, Any] = {
        "agent_name": "BudgetTest",
        "workspace": tmp_path / "workspace",
        "db_path": tmp_path / "memory.sqlite3",
        "enabled": True,
        "tick_interval": 1,
        "effector_enabled": True,
        # Keep the stage-19 tests independent from the user's current
        # approval and driver settings; those paths have their own tests.
        "approval_mode": "off",
        "core_driven": False,
    }
    params.update(kwargs)
    return DelamainSubsystem(**params)


def write_request(request_id: str = "req-1") -> EffectorRequest:
    return EffectorRequest(
        request_id=request_id,
        goal="write a note",
        plan=[
            {
                "action": "write_file",
                "args": {"path": "notes/a.txt", "content": "hello"},
            }
        ],
    )


def test_disabled_budget_does_not_gate_or_charge_delamain(tmp_path: Path) -> None:
    agent = _AgentStub(energy=10, enabled=False)
    sub = make_sub(tmp_path, core_driven=True)
    sub.setup({"agent": agent})
    try:
        request = write_request("budget-off")
        sub.effector.submit(request)

        result = sub.effector.step(1)

        assert result is not None
        assert result.status is EffectorStatus.SUCCEEDED
        assert agent.energy == 10.0
        assert (
            tmp_path / "workspace" / "notes" / "a.txt"
        ).read_text(encoding="utf-8") == "hello"
    finally:
        sub.teardown()


def test_core_driven_step_waits_for_energy_then_executes(
    tmp_path: Path,
) -> None:
    agent = _AgentStub(energy=2, min_reserve=5)
    sub = make_sub(tmp_path, core_driven=True)
    sub.setup({"agent": agent})
    try:
        request = write_request("budget-core")
        sub.effector.submit(request)

        denied = sub.effector.step(1)

        assert denied is not None
        assert denied.status is EffectorStatus.QUEUED
        assert denied.detail["budget"]["allowed"] is False
        assert denied.detail["budget"]["reason"] == "insufficient_energy"
        assert agent.energy == 2.0
        assert not (tmp_path / "workspace" / "notes" / "a.txt").exists()
        assert sub.get_goal(denied.goal_id)["status"] == "pending"

        agent.energy = 20.0
        allowed = sub.effector.step(2)

        assert allowed is not None
        assert allowed.status is EffectorStatus.SUCCEEDED
        assert agent.energy == 16.0
        assert (
            tmp_path / "workspace" / "notes" / "a.txt"
        ).read_text(encoding="utf-8") == "hello"
        assert sub.get_goal(allowed.goal_id)["status"] == "done"
    finally:
        sub.teardown()


def test_standalone_tick_stops_on_budget_and_goal_stays_pending(
    tmp_path: Path,
) -> None:
    agent = _AgentStub(energy=2, min_reserve=5)
    sub = make_sub(tmp_path)
    sub.setup({"agent": agent})
    try:
        goal = sub.queue_goal(
            "write a note",
            plan=[
                {
                    "action": "write_file",
                    "args": {"path": "notes/a.txt", "content": "hello"},
                }
            ],
        )

        event = sub.tick(1, {})

        assert event is not None
        assert event["events"][0]["name"] == "delamain_goal"
        summary = event["events"][0]["data"]
        assert summary["budget_denied"] is True
        assert summary["budget"]["reason"] == "insufficient_energy"
        assert sub.get_goal(goal["id"])["status"] == "pending"
        assert not (tmp_path / "workspace" / "notes" / "a.txt").exists()
        assert agent.energy == 2.0

        agent.energy = 20.0
        event = sub.tick(2, {})

        assert event is not None
        summary = event["events"][0]["data"]
        assert summary["ok"] is True
        assert sub.get_goal(goal["id"])["status"] == "done"
        assert agent.energy == 16.0
        assert (
            tmp_path / "workspace" / "notes" / "a.txt"
        ).read_text(encoding="utf-8") == "hello"
    finally:
        sub.teardown()


def test_approve_uses_budget_without_consuming_approval_on_denial(
    tmp_path: Path,
) -> None:
    agent = _AgentStub(energy=100, enabled=False)
    sub = make_sub(
        tmp_path,
        approval_mode="dangerous",
        core_driven=True,
    )
    sub.setup({"agent": agent})
    try:
        request = write_request("budget-approval")
        sub.effector.submit(request)
        waiting = sub.effector.step(1)
        assert waiting is not None
        assert waiting.status is EffectorStatus.WAITING_APPROVAL
        assert waiting.approval_id

        agent.action_budget.enabled = True
        agent.energy = 2.0
        denied = sub.approve(waiting.approval_id)

        assert denied["budget_denied"] is True
        assert agent.energy == 2.0
        assert not (tmp_path / "workspace" / "notes" / "a.txt").exists()
        assert len(sub.list_approvals(status="approved")) == 1

        agent.energy = 20.0
        allowed = sub.approve(waiting.approval_id)

        assert allowed["ok"] is True
        assert allowed.get("status") == "approved"
        assert agent.energy == 16.0
        result = sub.effector.step(2)
        assert result is not None
        assert result.status is EffectorStatus.SUCCEEDED
        assert agent.energy == 16.0
        assert (
            tmp_path / "workspace" / "notes" / "a.txt"
        ).read_text(encoding="utf-8") == "hello"
    finally:
        sub.teardown()


def test_run_now_uses_the_same_budget_gate(tmp_path: Path) -> None:
    agent = _AgentStub(energy=2, min_reserve=5)
    sub = make_sub(tmp_path)
    sub.setup({"agent": agent})
    plan: list[Dict[str, Any]] = [
        {
            "action": "write_file",
            "args": {"path": "notes/a.txt", "content": "hello"},
        }
    ]
    try:
        denied = sub.run_now("write a note", plan=plan)

        assert denied["budget_denied"] is True
        assert denied["ok"] is False
        assert denied["trigger"] == "manual"
        assert agent.energy == 2.0
        assert not (tmp_path / "workspace" / "notes" / "a.txt").exists()

        agent.energy = 20.0
        allowed = sub.run_now("write a note", plan=plan)

        assert allowed["ok"] is True
        assert allowed.get("budget_denied") is None
        assert agent.energy == 16.0
        assert (
            tmp_path / "workspace" / "notes" / "a.txt"
        ).read_text(encoding="utf-8") == "hello"
    finally:
        sub.teardown()
