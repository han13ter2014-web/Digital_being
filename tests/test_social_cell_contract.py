"""Регрессии минимального контракта социального познания."""

from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.social_cell import SocialCell, ToMLevel


def test_recursion_depth_defaults_to_two_and_rejects_invalid_values():
    assert SocialCell(SimpleNamespace()).max_recursion_depth == 2

    for value in (-1, 3):
        with pytest.raises(ValueError, match="max_recursion_depth"):
            SocialCell(SimpleNamespace(), max_recursion_depth=value)
    for value in (True, 1.5, "2"):
        with pytest.raises(TypeError, match="max_recursion_depth"):
            SocialCell(SimpleNamespace(), max_recursion_depth=value)


@pytest.mark.parametrize("depth", [0, 1, 2])
def test_observation_honors_effective_recursion_depth(depth):
    social = SocialCell(SimpleNamespace(), max_recursion_depth=depth)

    social.observe_interaction(
        "peer",
        {
            "action": "help",
            "expressed_beliefs": {"cooperation": 1.0},
            "reaction_to_us": "trust",
        },
    )

    model = social.agent_models["peer"]
    assert len(model.interaction_history) == 1
    assert bool(model.believed_goals) is (depth >= 1)
    assert bool(model.believed_beliefs) is (depth >= 1)
    assert ("trustworthiness" in model.believed_model_of_self) is (depth >= 2)


def test_reserved_third_level_cannot_bypass_recursion_cap(monkeypatch):
    social = SocialCell(SimpleNamespace(), max_recursion_depth=2)
    social.set_tom_level(ToMLevel.THIRD)

    def fail_recursive_update(model, obs):
        raise AssertionError("reserved recursive update must not run")

    monkeypatch.setattr(social, "_update_recursive_model", fail_recursive_update)
    social.observe_interaction("peer", {"action": "help"})


def test_beliefs_require_explicit_positions_and_change_gradually():
    social = SocialCell(SimpleNamespace())
    social.observe_interaction("peer", {"text": "Сотрудничество важно"})
    model = social.agent_models["peer"]
    assert model.believed_beliefs == {}

    social.observe_interaction("peer", {"expressed_beliefs": {"cooperation": 1.0}})
    assert model.believed_beliefs["cooperation"] == pytest.approx(0.55)

    social.observe_interaction("peer", {"expressed_beliefs": {"cooperation": 0.0}})
    assert model.believed_beliefs["cooperation"] == pytest.approx(0.495)


def test_beliefs_decay_without_new_evidence_and_ignore_invalid_values():
    social = SocialCell(SimpleNamespace())
    social.observe_interaction("peer", {"expressed_beliefs": {"cooperation": 1.0}})
    model = social.agent_models["peer"]
    learned = model.believed_beliefs["cooperation"]

    social.observe_interaction("peer", {"action": "observe"})
    assert model.believed_beliefs["cooperation"] == pytest.approx(learned * 0.99)

    social.observe_interaction(
        "peer",
        {
            "expressed_beliefs": {
                "": 1.0,
                "too_high": 2.0,
                "boolean": True,
                "not_finite": float("nan"),
            }
        },
    )
    assert set(model.believed_beliefs) == {"cooperation"}


def test_initial_beliefs_are_not_shared_between_models_or_caller():
    initial = {"beliefs": {"cooperation": 1.0}}
    social = SocialCell(SimpleNamespace())
    first = social.register_agent("first", initial)
    second = social.register_agent("second", initial)

    first.believed_beliefs["cooperation"] = 0.2

    assert second.believed_beliefs["cooperation"] == 1.0
    assert initial["beliefs"]["cooperation"] == 1.0


def test_learned_cooperation_belief_changes_social_choice():
    baseline = SocialCell(SimpleNamespace())
    baseline.register_agent("peer")
    experienced = SocialCell(SimpleNamespace())
    for _ in range(20):
        experienced.observe_interaction(
            "peer",
            {"action": "cooperate", "expressed_beliefs": {"cooperation": 1.0}},
        )

    actions = ["cooperate", "ask"]
    assert baseline.choose_action_social("peer", actions) == "ask"
    assert experienced.choose_action_social("peer", actions) == "cooperate"


def test_beliefs_survive_checkpoint_roundtrip_without_sharing_state():
    agent = DigitalBeing(name="SocialBeliefCheckpoint")
    agent.social_cell.observe_interaction(
        "peer", {"expressed_beliefs": {"cooperation": 1.0}}
    )
    expected = agent.social_cell.agent_models["peer"].believed_beliefs["cooperation"]

    state = build_state_from_agent(agent)
    reborn = DigitalBeing(name="SocialBeliefCheckpointRestored")
    apply_state_to_agent(reborn, state)

    restored = reborn.social_cell.agent_models["peer"]
    assert restored.believed_beliefs["cooperation"] == pytest.approx(expected)
    restored.believed_beliefs["cooperation"] = 0.0
    assert agent.social_cell.agent_models["peer"].believed_beliefs[
        "cooperation"
    ] == pytest.approx(expected)
