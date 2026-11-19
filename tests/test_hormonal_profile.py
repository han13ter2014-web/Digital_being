"""Ограниченная per-life эндокринная адаптация и checkpoint schema 2."""

from copy import deepcopy

import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.emotion.hormonal_system import HormonalSystem


def _provenance(source: str, cycle: int) -> dict:
    return {"source": source, "cycle": cycle, "reason": f"{source}_observed"}


def _profile(system: HormonalSystem, name: str) -> dict:
    return system.profile.to_checkpoint()[name]


def test_adaptation_starts_only_after_twenty_episodes_of_one_source():
    system = HormonalSystem()

    for cycle in range(20):
        system.process_event(
            "connection",
            1.0,
            provenance=_provenance("social_message", cycle),
        )
        system.tick(300.0)

    assert _profile(system, "oxytocin") == {
        "baseline": 0.3,
        "sensitivity": 1.0,
        "half_life_scale": 1.0,
        "confidence": 0.1,
        "sample_count": 20,
        "source_sample_counts": {"social_message": 20},
    }

    system.process_event(
        "connection",
        1.0,
        provenance=_provenance("social_message", 20),
    )

    adapted = _profile(system, "oxytocin")
    assert adapted["sample_count"] == 21
    assert adapted["baseline"] > 0.3
    assert adapted["sensitivity"] < 1.0
    assert adapted["half_life_scale"] > 1.0
    assert adapted["confidence"] == pytest.approx(21 / 200)


def test_sources_and_lives_are_independent_and_hardware_is_not_social():
    hardware = HormonalSystem()
    social = HormonalSystem()
    untouched = HormonalSystem()
    neutral_specs = {
        name: (spec.base_level, spec.half_life)
        for name, spec in HormonalSystem.HORMONES.items()
    }

    for cycle in range(21):
        hardware.process_event(
            "hardware_strain",
            1.0,
            provenance={
                "source": "hardware",
                "cycle": cycle,
                "origin": "own",
                "duration_cycles": 5,
                "evidence": ["process_cpu", "process_rss"],
            },
        )
        hardware.tick(60.0)
        social.process_event(
            "connection",
            1.0,
            provenance=_provenance("social_message", cycle),
        )
        social.tick(300.0)

    assert _profile(hardware, "cortisol")["source_sample_counts"] == {"hardware": 21}
    assert _profile(hardware, "oxytocin")["sample_count"] == 0
    assert _profile(hardware, "prolactin")["sample_count"] == 0
    assert hardware.hormones["oxytocin"] == 0.3
    assert hardware.hormones["prolactin"] == 0.2
    assert _profile(social, "oxytocin")["source_sample_counts"] == {
        "social_message": 21
    }
    assert _profile(social, "cortisol")["source_sample_counts"] == {
        "social_message": 21
    }
    assert _profile(social, "cortisol")["sample_count"] == 21
    assert _profile(untouched, "oxytocin")["sample_count"] == 0
    assert untouched.profile.to_checkpoint() != social.profile.to_checkpoint()
    assert {
        name: (spec.base_level, spec.half_life)
        for name, spec in HormonalSystem.HORMONES.items()
    } == neutral_specs


def test_long_experience_is_bounded_and_schema_two_roundtrip_is_deterministic():
    system = HormonalSystem()

    for cycle in range(120):
        system.process_event(
            "success",
            1.0,
            provenance={
                "source": "action_outcome",
                "cycle": cycle,
                "action": "explore",
                "reason": "knowledge_changed",
            },
        )
        system.tick(300.0)

    state = system.to_checkpoint()
    assert state["schema_version"] == 2
    assert state["time_model"] == "tick_only"
    assert state["legacy_mixed_time"] is False
    assert len(state["history"]) == 120
    assert len(state["episodes"]) == 50
    for name in HormonalSystem.HORMONES:
        profile = state["profile"][name]
        spec = HormonalSystem.HORMONES[name]
        assert spec.base_level - 0.05 <= profile["baseline"] <= spec.base_level + 0.05
        assert 0.75 <= profile["sensitivity"] <= 1.25
        assert 0.75 <= profile["half_life_scale"] <= 1.5
        assert 0.0 <= profile["confidence"] <= 1.0
        assert profile["sample_count"] >= 0
    assert state["profile"]["dopamine"]["baseline"] > 0.4
    assert state["profile"]["dopamine"]["sensitivity"] < 1.0
    assert state["profile"]["dopamine"]["half_life_scale"] > 1.0

    restored = HormonalSystem.from_checkpoint(deepcopy(state))
    assert restored.to_checkpoint() == state

    for current in (system, restored):
        current.process_event(
            "success",
            1.0,
            provenance={
                "source": "action_outcome",
                "cycle": 120,
                "action": "explore",
                "reason": "knowledge_changed",
            },
        )
        current.tick(300.0)
    assert restored.to_checkpoint() == system.to_checkpoint()


def test_schema_one_migrates_without_reconstructing_missing_provenance():
    legacy = {
        "schema_version": 1,
        "hormones": {
            name: level.base_level for name, level in HormonalSystem.HORMONES.items()
        },
        "history": [
            {
                "time": 3.0,
                "event": "connection",
                "quality": "neutral",
                "intensity": 1.0,
                "changes": {"oxytocin": 0.12},
            },
            {
                "time": 4.0,
                "event": "success",
                "quality": "positive",
                "intensity": 1.0,
                "changes": {"dopamine": 0.15},
                "provenance": {
                    "source": "action_outcome",
                    "cycle": 4,
                    "action": "explore",
                    "reason": "knowledge_changed",
                },
            },
        ],
        "cycle_time": 4.0,
    }

    restored = HormonalSystem.from_checkpoint(legacy)
    state = restored.to_checkpoint()

    assert state["schema_version"] == 2
    assert state["cycle_time"] == 4.0
    assert state["time_model"] == "tick_only"
    assert state["legacy_mixed_time"] is True
    assert state["episodes"] == []
    assert state["history"][0]["provenance_status"] == "legacy"
    assert "provenance" not in state["history"][0]
    assert "provenance_status" not in state["history"][1]
    assert state["history"][1]["provenance"] == legacy["history"][1]["provenance"]
    assert all(
        profile["sample_count"] == 0
        and profile["confidence"] == 0.0
        and profile["sensitivity"] == 1.0
        and profile["half_life_scale"] == 1.0
        for profile in state["profile"].values()
    )


def test_corrupted_profile_is_rejected_before_live_agent_changes():
    source = DigitalBeing(name="HormonalProfileSource")
    state = build_state_from_agent(source)
    state["integrated_experience"]["hormones"]["profile"]["dopamine"]["sensitivity"] = (
        2.0
    )
    state_before = deepcopy(state)

    target = DigitalBeing(name="HormonalProfileTarget")
    live = target.hormonal_system
    before = target.integrated_experience.to_checkpoint()

    with pytest.raises(ValueError, match="sensitivity"):
        apply_state_to_agent(target, state)

    assert target.hormonal_system is live
    assert target.integrated_experience.hormones is live
    assert target.integrated_experience.to_checkpoint() == before
    assert state == state_before
