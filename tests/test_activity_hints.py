"""Игровые/творческие подсказки больше не скрывают исследовательский способ."""

from src.core.agent import DigitalBeing
from src.core.motivation.unified_motivation import NEED_GOAL_TEMPLATES, DRIVE_GOAL_TEMPLATES


def test_play_and_creativity_templates_reference_actual_activities():
    agent = DigitalBeing(name="ActivityTemplates")
    for templates in (NEED_GOAL_TEMPLATES["play"], DRIVE_GOAL_TEMPLATES["creativity"]):
        assert {agent._normalize_action(item["action"]) for item in templates} == {"play", "create_draft"}


def test_isolated_creative_drive_proposes_nonresearch_handlers():
    agent = DigitalBeing(name="CreativeDriveRoutes")
    system = agent.motivation_system
    for need in system.needs.values():
        need.current_level = need.base_level
    for drive in system.drives.values():
        drive.current_level = 0
    system.drives["creativity"].current_level = 0.8
    candidates = system.get_action_candidates({})
    creative = [c for c in candidates if c.get("drive") == "creativity"]
    assert {agent._normalize_action(c["action"]) for c in creative} == {"play", "create_draft"}


def test_exploration_drive_remains_research_capability():
    agent = DigitalBeing(name="ResearchStillAvailable")
    drive = agent.motivation_system.drives["exploration"]
    assert all(agent._normalize_action(action) == "explore" for action in drive.goal_types)
