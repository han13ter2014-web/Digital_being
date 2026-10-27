"""Варианты черновиков сравниваются арбитром, не исполняются генератором."""

from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.cognition.creative_choices import creative_choices
from src.cognition.creative_draft import LIMIT


def base():
    return {"action": "creative_act", "source": "motivation", "strength": 0.6, "params": {"need": "play"}}


def test_choices_depend_on_work_state_without_creating_files():
    agent = DigitalBeing(name="CreativeOptions")
    assert [c["params"]["draft_mode"] for c in creative_choices(agent, base())] == ["new"]
    assert getattr(agent, "_creative_draft", None) is None
    agent.act("create_draft")
    choices = creative_choices(agent, base())
    assert {c["params"]["draft_mode"] for c in choices} == {"continue", "new"}
    assert choices[0]["params"]["draft_id"] == agent._creative_draft["id"]
    agent._creative_draft["revision"] = LIMIT
    choices = creative_choices(agent, base())
    assert {c["params"]["draft_mode"] for c in choices} == {"leave", "new"}


def test_arbiter_selected_new_work_uses_expanded_params():
    agent = DigitalBeing(name="CreativeArbitration")
    def choose(candidates, context):
        return {**next(c for c in candidates if c.get("params", {}).get("draft_mode") == "new"), "verdict": "proceed"}
    with patch.object(agent.motivation_system, "get_action_candidates", return_value=[base()]), \
         patch.object(agent.decision_arbitrator, "choose_action", side_effect=choose):
        report = agent.autonomous_tick()
    assert report["executed_intention"]["params"]["draft_mode"] == "new"
    assert agent._creative_draft["revision"] == 1


def test_leaving_does_not_reward_unwritten_text():
    agent = DigitalBeing(name="NoCreativeRewardForLeaving")
    agent.act("create_draft")
    before = agent.motivation_system.needs["play"].current_level
    agent.act("create_draft", intention={"params": {"draft_mode": "leave", "reason": "достаточно"}})
    assert agent.motivation_system.needs["play"].current_level == before
    assert agent._creative_draft["status"] == "left"
