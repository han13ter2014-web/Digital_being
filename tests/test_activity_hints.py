"""Игровые/творческие подсказки больше не скрывают исследовательский способ."""

from src.core.agent import DigitalBeing
from src.core.motivation.unified_motivation import (
    NEED_GOAL_TEMPLATES,
    DRIVE_GOAL_TEMPLATES,
)


def test_play_and_creativity_templates_reference_actual_activities():
    agent = DigitalBeing(name="ActivityTemplates")
    for templates in (NEED_GOAL_TEMPLATES["play"], DRIVE_GOAL_TEMPLATES["creativity"]):
        assert {agent._normalize_action(item["action"]) for item in templates} == {
            "play",
            "create_draft",
            "draw",
            "compose_music",
        }


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
    assert {agent._normalize_action(c["action"]) for c in creative} == {
        "play",
        "create_draft",
        "draw",
        "compose_music",
    }


def test_exploration_drive_remains_research_capability():
    agent = DigitalBeing(name="ResearchStillAvailable")
    drive = agent.motivation_system.drives["exploration"]
    assert all(
        agent._normalize_action(action) == "explore" for action in drive.goal_types
    )


def test_creative_organs_offered_and_satisfy_play_need():
    """Творческие draw и compose_music предлагаются мотивацией.

    При активном creativity-драйве в кандидатах присутствуют оба органа
    с положительной силой; их исполнение удовлетворяет потребность play
    через существующий мост ACTION_ALIASES (draw/compose_music →
    creative_act → need "play").
    """
    agent = DigitalBeing(name="CreativeOrgansOffered")
    system = agent.motivation_system
    for need in system.needs.values():
        need.current_level = need.base_level
    for drive in system.drives.values():
        drive.current_level = 0
    system.drives["creativity"].current_level = 0.8

    candidates = system.get_action_candidates({})
    offered = {
        c["action"]: c
        for c in candidates
        if c.get("drive") == "creativity"
        and agent._normalize_action(c["action"]) in {"draw", "compose_music"}
    }
    assert {"draw", "compose_music"} <= set(offered)
    assert all(c["strength"] > 0 for c in offered.values())

    # Петля удовлетворения: исполненный орган гасит play-нужду.
    agent.act("draw")
    assert (
        agent.motivation_system.needs["play"].current_level
        > system.needs["play"].base_level
    )

    agent2 = DigitalBeing(name="MusicSatisfiesPlay")
    system2 = agent2.motivation_system
    for need in system2.needs.values():
        need.current_level = need.base_level
    system2.needs["play"].current_level = system2.needs["play"].base_level
    agent2.act("compose_music")
    assert system2.needs["play"].current_level > system2.needs["play"].base_level
