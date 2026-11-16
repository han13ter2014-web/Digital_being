"""P3-B: диагностика конкуренции не меняет действующий выбор."""

from unittest.mock import patch

from src.core.subsystems.decision_arbitrator import DecisionArbitrator


def verdict(kind="proceed", score=0.5):
    return {
        "verdict": kind,
        "score": score,
        "confidence": 0.0,
        "reasoning": kind,
        "voices": {},
    }


def test_exact_tie_preserves_input_order_and_exposes_intention_context():
    arbiter = DecisionArbitrator()
    candidates = [
        {
            "action": "explore",
            "source": "active_goal",
            "strength": 0.5,
            "params": {
                "topic": " память ",
                "goal_id": 7,
                "continuation_of": "previous-intention",
            },
        },
        {
            "action": "draw",
            "source": "activity",
            "strength": 0.5,
            "params": {"topic": "рисунок"},
        },
    ]
    with patch.object(arbiter, "arbitrate", return_value=verdict()):
        result = arbiter.choose_action(candidates, {})

    assert result["action"] == "explore"
    assert result["choice_diagnostics"] == {
        "candidate_count": 2,
        "allowed_count": 2,
        "stopped_count": 0,
        "winner_input_index": 0,
        "exact_tie": True,
        "tied_input_indices": [0, 1],
    }
    first, second = result["all_evaluations"]
    assert first["input_index"] == 0
    assert first["strength"] == 0.5
    assert first["arbiter_score"] == 0.5
    assert first["target"] == "память"
    assert first["goal_id"] == 7
    assert first["continuation_of"] == "previous-intention"
    assert second["input_index"] == 1
    assert second["target"] == "рисунок"


def test_lower_score_and_stop_diagnostics_do_not_change_selection():
    arbiter = DecisionArbitrator()
    with patch.object(
        arbiter,
        "arbitrate",
        side_effect=[
            verdict("stop", 0.9),
            verdict("proceed", 0.5),
            verdict("proceed", 0.4),
        ],
    ):
        result = arbiter.choose_action(
            [
                {"action": "explore", "source": "test", "strength": 1.0},
                {"action": "rest", "source": "body", "strength": 0.2},
                {"action": "draw", "source": "activity", "strength": 0.1},
            ],
            {},
        )

    assert result["action"] == "rest"
    assert result["choice_diagnostics"] == {
        "candidate_count": 3,
        "allowed_count": 2,
        "stopped_count": 1,
        "winner_input_index": 1,
        "exact_tie": False,
        "tied_input_indices": [1],
    }


def test_empty_and_all_stopped_rounds_have_explicit_diagnostics():
    arbiter = DecisionArbitrator()
    empty = arbiter.choose_action([], {})
    assert empty["choice_diagnostics"]["candidate_count"] == 0
    assert empty["choice_diagnostics"]["winner_input_index"] is None

    with patch.object(arbiter, "arbitrate", return_value=verdict("stop", 0.3)):
        stopped = arbiter.choose_action(
            [{"action": "explore", "source": "test", "strength": 1.0}], {}
        )
    assert stopped["action"] == "wait"
    assert stopped["choice_diagnostics"] == {
        "candidate_count": 1,
        "allowed_count": 0,
        "stopped_count": 1,
        "winner_input_index": None,
        "exact_tie": False,
        "tied_input_indices": [],
    }
