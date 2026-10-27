"""Окончание занятия не требует победы или вымышленных учебных наград."""

from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.cognition.activity_goals import attach_activity, record_activity_step


def setup_goal(agent, action):
    identifier = agent.set_goal("Контроль занятия", activate=True)
    attach_activity(agent, identifier, {"source": "self", "action_hint": action})
    return agent.active_goal


def test_game_round_finishes_even_when_opponent_wins_without_learning_reward():
    agent = DigitalBeing(name="RoundCompletion")
    goal = setup_goal(agent, "play")
    selection = {"params": {"activity_goal_id": goal["id"]}}
    count, energy, streak = agent.completed_goals, agent.energy, agent.success_streak
    record_activity_step(agent, selection, "play", {"result": None}, {"result": "O", "board": ["O"]})
    assert goal["status"] == "completed"
    assert agent.completed_goals == count + 1
    assert agent.goal_subsystem.completed_goals == count + 1
    assert agent.energy == energy
    assert agent.success_streak == streak
    record_activity_step(agent, selection, "play", None, {"result": "O"})
    assert agent.completed_goals == count + 1


def test_creative_leave_does_not_finish_revision_goal():
    agent = DigitalBeing(name="LeaveNotRevision")
    goal = setup_goal(agent, "creative_act")
    selection = {"params": {"activity_goal_id": goal["id"]}}
    record_activity_step(agent, selection, "create_draft", {"revision": 1}, {"revision": 1, "status": "left"})
    assert goal["status"] == "active"
    assert "steps" not in goal["activity"]


def test_real_selected_draft_revision_completes_activity_not_knowledge():
    agent = DigitalBeing(name="DraftCompletion")
    goal = setup_goal(agent, "creative_act")
    knowledge = agent.mental_models.to_storage_dict()
    selection = {"action": "create_draft", "source": "own_activity", "verdict": "proceed",
                 "params": {"activity_goal_id": goal["id"], "draft_mode": "new"}}
    streak = agent.success_streak
    with patch.object(agent.decision_arbitrator, "choose_action", return_value=selection):
        agent.autonomous_tick()
    assert goal["status"] == "completed"
    assert goal["activity"]["steps"] == 1
    assert agent.success_streak == streak
    assert agent.mental_models.to_storage_dict() == knowledge
