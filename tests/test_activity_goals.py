"""Собственное занятие сохраняет способ и не получает учебный прогресс."""

from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.core.world_delta import WorldDelta
from src.cognition.activity_goals import activity_candidate
from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent


def test_ingest_preserves_origin_and_activity_across_restore():
    agent = DigitalBeing(name="ActivityOrigin")
    agent._ingest_motivation_goals([{"title": "Сыграть партию", "source": "need", "need": "play",
                                     "action_hint": "play", "priority": 0.7}])
    goal = agent.goals[-1]
    assert goal["motivation_origin"]["need"] == "play"
    assert goal["activity"]["action"] == "play"
    state = build_state_from_agent(agent)
    apply_state_to_agent(agent, state)
    assert agent.goals[-1] == goal


def test_learning_does_not_credit_active_play_goal():
    agent = DigitalBeing(name="NoLearningCreditForPlay")
    agent._ingest_motivation_goals([{"title": "Сыграть партию", "action_hint": "play"}])
    goal = agent.goals[-1]
    agent.active_goal = goal
    goal["status"] = "active"
    result = agent._check_goal_progress("новая тема", answered=True, evidence=WorldDelta(concepts=1))
    assert result["pct"] == 0
    assert goal["status"] == "active"


def test_selected_activity_records_game_step_not_goal_completion():
    agent = DigitalBeing(name="SelectedActivity")
    agent._ingest_motivation_goals([{"title": "Сыграть партию", "action_hint": "play"}])
    goal = agent.goals[-1]
    agent.active_goal = goal
    goal["status"] = "active"
    candidate = activity_candidate(agent)
    with patch.object(agent.decision_arbitrator, "choose_action", return_value={**candidate, "verdict": "proceed"}):
        agent.autonomous_tick()
    assert goal["activity"]["steps"] == 1
    assert goal["activity"]["last_step"]["artifact"]["board"] == agent._local_play["board"]
    assert goal["status"] == "active"


def test_own_goal_can_be_nonresearch_when_play_is_pressing():
    agent = DigitalBeing(name="OwnNonResearch")
    agent.motivation_system.needs["play"].current_level = 0
    with patch.object(agent, "_pick_exploration_target", side_effect=AssertionError("not learning")) as picker:
        agent._act_set_own_goal()
    picker.assert_not_called()
    assert agent.goals[-1]["activity"]["action"] in {"play", "create_draft"}
