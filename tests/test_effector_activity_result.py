"""Отложенный/ошибочный effector не выдаётся за выполненное творчество."""

from src.core.agent import DigitalBeing


def test_effector_activity_updates_method_only_at_terminal_result():
    agent = DigitalBeing(name="EffectorActivityResult")
    agent._on_effector_result({"status": "waiting_approval", "ok": False,
                               "detail": {"activity": "creative"}})
    assert not getattr(agent, "_method_preferences", {})
    agent._on_effector_result({"status": "failed", "ok": False,
                               "detail": {"activity": "creative"}})
    assert agent._method_preferences["create_draft"]["failures"] == 1
    agent._on_effector_result({"status": "succeeded", "ok": True,
                               "detail": {"activity": "creative"}})
    assert agent._method_preferences["create_draft"]["effects"] == 1
    assert agent._last_effector_activity_result["status"] == "succeeded"


def test_successful_creative_effector_completes_matching_activity_goal():
    agent = DigitalBeing(name="EffectorGoalResult")
    goal_id = agent.set_goal("Сохранить текст", activate=True)
    goal = agent.active_goal
    goal["activity"] = {"action": "create_draft", "criterion": "draft_revision"}
    result = {"status": "succeeded", "ok": True,
              "detail": {"activity": "creative", "metadata": {"activity_goal_id": goal_id}}}
    agent._on_effector_result(result)
    assert goal["status"] == "completed"
    assert agent.completed_goals == 1


def test_failed_creative_effector_does_not_complete_goal():
    agent = DigitalBeing(name="EffectorGoalFailure")
    goal_id = agent.set_goal("Сохранить текст", activate=True)
    agent.active_goal["activity"] = {"action": "create_draft", "criterion": "draft_revision"}
    agent._on_effector_result({"status": "failed", "ok": False,
                               "detail": {"activity": "creative", "metadata": {"activity_goal_id": goal_id}}})
    assert agent.active_goal["status"] == "active"
    assert agent.completed_goals == 0


def test_non_activity_effector_does_not_change_creative_preference():
    agent = DigitalBeing(name="OtherEffectorResult")
    agent._on_effector_result({"status": "succeeded", "ok": True,
                               "detail": {"activity": "other"}})
    assert not getattr(agent, "_method_preferences", {})
