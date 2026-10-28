"""Core-driven approval не является вторым исполнителем."""

from unittest.mock import Mock

from src.delamain.subsystem import DelamainSubsystem


def test_core_driven_approval_defers_execution_to_step():
    subsystem = DelamainSubsystem(agent_name="ApprovalClock", enabled=True,
                                  effector_enabled=True, core_driven=True,
                                  approval_mode="dangerous")
    runtime = Mock()
    approval = {"status": "pending", "goal_id": 7, "task": "write"}
    runtime.memory.get_approval.side_effect = [approval, {**approval, "status": "approved"}]
    runtime.memory.approve_approval.return_value = {**approval, "status": "approved"}
    runtime.memory.get_goal.return_value = {"id": 7, "title": "write", "metadata": {}}
    subsystem.runtime = runtime
    result = subsystem.approve("approval-1")
    assert result["status"] == "approved"
    assert result["detail"]["execution"] == "deferred_to_core_effector"
    runtime.run_approved.assert_not_called()
