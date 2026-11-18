"""P3-C-1: история форм и продолжение работ без скрытых наград."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from src.cognition.creative_history import with_creative_history
from src.cognition.decision_episode import finish_decision_episode
from src.cognition.intention_history import (
    begin_intention,
    finish_intention,
    validate_history,
)
from src.core.activity_workspace import workspace_for
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.subsystems.decision_arbitrator import DecisionArbitrator


def verdict():
    return {
        "verdict": "proceed",
        "score": 0.5,
        "confidence": 0.0,
        "reasoning": "test",
        "voices": {},
    }


def creative_candidate(action, form, last_cycle, strength=0.5):
    return {
        "action": action,
        "source": "motivation",
        "strength": strength,
        "params": {
            "creative_form": form,
            "creative_operation": "continue",
            "creative_last_cycle": last_cycle,
        },
    }


def perform_new_work(agent, action, attr):
    candidate = with_creative_history(
        agent, [{"action": action, "source": "test", "strength": 0.5, "params": {}}]
    )[0]
    assert candidate["params"]["creative_operation"] == "new"
    assert candidate["params"]["continuation_of"] is None
    entry = begin_intention(agent, candidate)
    before = deepcopy(getattr(agent, attr, None))
    agent.act(action, intention=candidate)
    after = getattr(agent, attr)
    outcome = agent._last_action_outcome
    finish_intention(entry, outcome)
    finish_decision_episode(
        agent,
        entry,
        outcome=outcome,
        activity_before=before,
        activity_after=after,
    )
    assert entry["status"] == "performed"
    return entry, after


@pytest.mark.parametrize(
    "action,attr,form",
    [
        ("create_draft", "_creative_draft", "text"),
        ("draw", "_art_work", "art"),
        ("compose_music", "_music_work", "music"),
    ],
)
def test_actual_result_links_continuation_after_restart(action, attr, form):
    agent = DigitalBeing(name=f"CreativeHistory{form}")
    entry, work = perform_new_work(agent, action, attr)
    episode = entry["decision_episode"]

    assert episode["creative_intention"]["operation"] == "new"
    assert episode["creative_intention"]["work_id"] is None
    assert episode["creative_result"] == {
        "form": form,
        "work_id": work["id"],
        "revision": 1,
        "status": "active",
    }
    validate_history(agent._intention_history)

    agent.cycle_count += 1
    state = build_state_from_agent(agent)
    apply_state_to_agent(agent, state)
    continued = with_creative_history(
        agent, [{"action": action, "source": "test", "strength": 0.5, "params": {}}]
    )[0]

    assert continued["params"]["creative_form"] == form
    assert continued["params"]["creative_operation"] == "continue"
    assert continued["params"]["creative_work_id"] == work["id"]
    assert continued["params"]["continuation_of"] == entry["id"]
    assert continued["params"]["creative_last_cycle"] == entry["cycle"]


def test_candidate_history_has_no_file_or_work_side_effects():
    agent = DigitalBeing(name="CreativeHistoryReadOnly")
    candidates = [
        {"action": action, "source": "test", "strength": 0.5, "params": {}}
        for action in ("create_draft", "draw", "compose_music")
    ]
    before_files = workspace_for(agent).list()

    decorated = with_creative_history(agent, candidates)

    assert workspace_for(agent).list() == before_files
    assert getattr(agent, "_creative_draft", None) is None
    assert getattr(agent, "_art_work", None) is None
    assert getattr(agent, "_music_work", None) is None
    assert all("creative_form" not in candidate["params"] for candidate in candidates)
    assert [c["params"]["creative_form"] for c in decorated] == [
        "text",
        "art",
        "music",
    ]


def test_creative_result_corruption_is_rejected():
    agent = DigitalBeing(name="CreativeHistoryCorruption")
    perform_new_work(agent, "draw", "_art_work")
    state = build_state_from_agent(agent)
    state["intention_history"][-1]["decision_episode"]["creative_result"]["work_id"] = (
        ""
    )

    with pytest.raises(ValueError, match="creative_result.work_id"):
        apply_state_to_agent(agent, state)


def test_forms_of_one_creativity_drive_have_equal_strength():
    agent = DigitalBeing(name="CreativeHistoryStrength")
    for need in agent.motivation_system.needs.values():
        need.current_level = need.base_level
    for drive in agent.motivation_system.drives.values():
        drive.current_level = 0.0
    agent.motivation_system.drives["creativity"].current_level = 0.8

    candidates = agent.motivation_system.get_action_candidates()
    creative = {
        candidate["action"]: candidate["strength"]
        for candidate in candidates
        if candidate.get("drive") == "creativity"
    }

    assert creative["creative_act"] == pytest.approx(0.64)
    assert creative["draw"] == pytest.approx(0.64)
    assert creative["compose_music"] == pytest.approx(0.64)
    assert creative["play"] == pytest.approx(0.448)


def test_unrecorded_form_wins_only_creative_exact_tie():
    arbiter = DecisionArbitrator()
    candidates = [
        creative_candidate("create_draft", "text", 9),
        creative_candidate("draw", "art", None),
        creative_candidate("compose_music", "music", 2),
    ]
    with patch.object(arbiter, "arbitrate", return_value=verdict()):
        result = arbiter.choose_action(candidates, {})

    assert result["action"] == "draw"
    assert result["choice_diagnostics"]["tie_break"] == "creative_history"
    assert result["choice_diagnostics"]["winner_input_index"] == 1


def test_longest_unseen_recorded_form_wins_creative_exact_tie():
    arbiter = DecisionArbitrator()
    candidates = [
        creative_candidate("create_draft", "text", 9),
        creative_candidate("draw", "art", 3),
        creative_candidate("compose_music", "music", 5),
    ]
    with patch.object(arbiter, "arbitrate", return_value=verdict()):
        result = arbiter.choose_action(candidates, {})

    assert result["action"] == "draw"
    assert result["choice_diagnostics"]["tie_break"] == "creative_history"


def test_same_form_and_equal_history_keep_input_order():
    arbiter = DecisionArbitrator()
    same_form = [
        creative_candidate("create_draft", "text", 1),
        creative_candidate("create_draft", "text", 2),
    ]
    equal_history = [
        creative_candidate("create_draft", "text", 4),
        creative_candidate("draw", "art", 4),
    ]
    with patch.object(arbiter, "arbitrate", return_value=verdict()):
        same_result = arbiter.choose_action(same_form, {})
        equal_result = arbiter.choose_action(equal_history, {})

    assert same_result["choice_diagnostics"]["winner_input_index"] == 0
    assert same_result["choice_diagnostics"]["tie_break"] == "input_order"
    assert equal_result["choice_diagnostics"]["winner_input_index"] == 0


def test_higher_score_and_noncreative_first_tie_keep_existing_policy():
    arbiter = DecisionArbitrator()
    higher_score = [
        creative_candidate("create_draft", "text", 1, strength=0.6),
        creative_candidate("draw", "art", None, strength=0.5),
    ]
    noncreative_first = [
        {"action": "explore", "source": "test", "strength": 0.5, "params": {}},
        creative_candidate("create_draft", "text", 9),
        creative_candidate("draw", "art", None),
    ]
    with patch.object(arbiter, "arbitrate", return_value=verdict()):
        higher_result = arbiter.choose_action(higher_score, {})
        mixed_result = arbiter.choose_action(noncreative_first, {})

    assert higher_result["action"] == "create_draft"
    assert higher_result["choice_diagnostics"]["tie_break"] == "none"
    assert mixed_result["action"] == "explore"
    assert mixed_result["choice_diagnostics"]["tie_break"] == "input_order"
