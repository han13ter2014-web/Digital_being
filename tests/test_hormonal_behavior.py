"""Контрактные векторы ограниченного гормонального advisor 4C-1."""

from copy import deepcopy
import math

import pytest

from src.core.agent_body import HEAVY_ACTIONS
from src.core.hardware_behavior import apply_own_load_advice
from src.core.hardware_interoception import HardwareInteroception
from src.core.hormonal_behavior import apply_hormonal_advice, projection_signals
from src.emotion.hormonal_system import HormonalSystem


def _normalize(value):
    return str(value or "")


def _rich_system(sample_count=20, **levels):
    system = HormonalSystem()
    for name, level in levels.items():
        system.hormones[name] = level
        values = system.profile.values[name]
        values["sample_count"] = sample_count
        values["confidence"] = min(1.0, sample_count / 200.0)
        source = {
            "oxytocin": "social_message",
            "cortisol": "hardware",
        }.get(name, "action_outcome")
        values["source_sample_counts"] = {source: sample_count}
    return system


def _resources():
    return {
        "available": True,
        "host_cpu_percent": 95.0,
        "process_cpu_percent": 90.0,
        "host_memory_percent": 92.0,
        "process_rss_mb": 475.0,
        "process_rss_ratio": 0.95,
        "cycle_duration_ms": 12.0,
        "score": 0.95,
        "source": "test",
    }


def _observe_own_load(observer, cycle):
    return observer.observe(
        _resources(),
        cycle=cycle,
        storage_status={
            "available": True,
            "total_bytes": 1000,
            "free_bytes": 800,
            "source": "test",
        },
    )


def test_projection_signal_uses_personal_baseline_and_bounded_evidence():
    system = _rich_system(sample_count=10, dopamine=0.6)

    projection = projection_signals(system)
    assert projection["evidence"]["dopamine"] == pytest.approx(0.5)
    assert projection["signals"]["dopamine"] == pytest.approx((0.2 / 0.6) * 0.5)

    system.profile.values["dopamine"]["baseline"] = 0.45
    personalized = projection_signals(system)
    assert personalized["signals"]["dopamine"] == pytest.approx((0.15 / 0.55) * 0.5)

    system.profile.values["dopamine"]["sample_count"] = 200
    assert projection_signals(system)["evidence"]["dopamine"] == 1.0
    system.profile.values["dopamine"]["sample_count"] = 0
    assert projection_signals(system)["signals"]["dopamine"] == 0.0


def test_projection_signal_rejects_invalid_values_and_zero_denominators():
    for baseline, level in ((1.0, 1.0), (0.0, 0.0)):
        system = _rich_system(dopamine=level)
        system.profile.values["dopamine"]["baseline"] = baseline
        assert projection_signals(system)["signals"]["dopamine"] == 0.0

    for field, value in (
        ("level", math.nan),
        ("level", math.inf),
        ("baseline", -0.1),
        ("baseline", 1.1),
        ("sample_count", True),
        ("sample_count", -1),
    ):
        system = _rich_system(dopamine=0.8)
        if field == "level":
            system.hormones["dopamine"] = value
        else:
            system.profile.values["dopamine"][field] = value
        assert projection_signals(system)["signals"]["dopamine"] == 0.0, (
            field,
            value,
        )


def test_advisor_applies_only_signed_map_and_preserves_checkpoint():
    system = _rich_system(dopamine=1.0, oxytocin=1.0, cortisol=1.0)
    checkpoint = system.to_checkpoint()
    candidates = [
        {"action": "explore", "source": "motivation", "strength": 0.8},
        {"action": "reflection", "source": "motivation", "strength": 0.8},
        {"action": "draw", "source": "creative", "strength": 0.5},
        {"action": "communicate", "source": "social", "strength": 0.7},
        {"action": "wait", "source": "deliberate_pause", "strength": 0.6},
        {"action": "rest", "source": "body", "strength": 0.8},
        {"action": "user_answer", "source": "social", "strength": 0.9},
        {"action": "ask_user", "source": "social", "strength": 0.4},
        {"action": "repair", "source": "body", "strength": 0.5},
    ]
    original = deepcopy(candidates)

    report = apply_hormonal_advice(candidates, system, _normalize)

    assert report["active"] is True
    assert report["reason"] == "applied"
    # explore: dopamine +10% и cortisol -10% дают один нулевой суммарный вклад.
    assert candidates[0]["strength"] == pytest.approx(original[0]["strength"])
    assert candidates[1]["strength"] == pytest.approx(0.72)
    assert candidates[2]["strength"] == pytest.approx(0.55)
    assert candidates[3]["strength"] == pytest.approx(0.77)
    assert candidates[4:] == original[4:]
    assert len(candidates) == len(original)
    assert system.to_checkpoint() == checkpoint
    assert [entry["input_index"] for entry in report["adjustments"]] == [1, 2, 3]


def test_advisor_evidence_ramp_limits_single_episode():
    expected = ((0, 0.5, 0.0), (1, 0.5025, 0.005), (20, 0.55, 0.1))
    for sample_count, expected_strength, expected_contribution in expected:
        system = _rich_system(sample_count=sample_count, dopamine=1.0)
        candidates = [{"action": "draw", "source": "creative", "strength": 0.5}]

        report = apply_hormonal_advice(candidates, system, _normalize)

        assert candidates[0]["strength"] == pytest.approx(expected_strength)
        if expected_contribution == 0.0:
            assert report["active"] is False
            assert report["adjustments"] == []
        else:
            assert report["adjustments"][0]["contribution"] == pytest.approx(
                expected_contribution
            )


def test_low_levels_do_not_reward_idle_or_force_contact():
    system = _rich_system(dopamine=0.0, oxytocin=0.0, cortisol=0.0)
    candidates = [
        {"action": "draw", "strength": 0.5},
        {"action": "communicate", "strength": 0.7},
        {"action": "wait", "strength": 0.1},
        {"action": "rest", "strength": 0.4},
        {"action": "reflection", "strength": 0.8},
    ]
    original = deepcopy(candidates)

    report = apply_hormonal_advice(candidates, system, _normalize)

    assert candidates[0]["strength"] == pytest.approx(0.45)
    assert candidates[1:] == original[1:]
    assert [entry["input_index"] for entry in report["adjustments"]] == [0]


def test_active_hardware_advisor_owns_heavy_budget(monkeypatch):
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_physical_sensors", lambda: {}
    )
    observer = HardwareInteroception()
    for cycle in range(5):
        _observe_own_load(observer, cycle)
    system = _rich_system(dopamine=1.0, oxytocin=1.0, cortisol=1.0)
    candidates = [
        {"action": "explore", "source": "motivation", "strength": 0.8},
        {"action": "reflection", "source": "motivation", "strength": 0.8},
        {"action": "draw", "source": "creative", "strength": 0.5},
        {"action": "communicate", "source": "social", "strength": 0.7},
    ]
    original = deepcopy(candidates)

    hardware_report = apply_own_load_advice(candidates, observer, _normalize)
    after_hardware = deepcopy(candidates)
    report = apply_hormonal_advice(
        candidates,
        system,
        _normalize,
        hardware_advisor_active=hardware_report["active"],
    )

    assert hardware_report["active"] is True
    for index, action in ((0, "explore"), (1, "reflection")):
        assert action in HEAVY_ACTIONS
        assert candidates[index]["strength"] == after_hardware[index]["strength"]
        assert candidates[index]["strength"] >= (
            original[index]["strength"] * 0.75 - 1e-12
        )
    assert candidates[2]["strength"] == pytest.approx(0.55)
    assert candidates[3]["strength"] == pytest.approx(0.77)
    assert [entry["input_index"] for entry in report["adjustments"]] == [2, 3]


def test_advisor_application_is_atomic_on_normalization_error():
    system = _rich_system(dopamine=1.0, oxytocin=1.0)
    candidates = [
        {"action": "draw", "strength": 0.5},
        {"action": "communicate", "strength": 0.7},
    ]
    original = deepcopy(candidates)

    def failing_normalize(value):
        if value == "communicate":
            raise ValueError("broken action")
        return _normalize(value)

    with pytest.raises(ValueError, match="broken action"):
        apply_hormonal_advice(candidates, system, failing_normalize)

    assert candidates == original


def test_missing_system_and_invalid_strengths_fail_closed():
    candidates = [{"action": "draw", "strength": 0.5}]
    original = deepcopy(candidates)
    report = apply_hormonal_advice(candidates, None, _normalize)
    assert report["active"] is False
    assert report["reason"] == "no_hormonal_system"
    assert candidates == original

    system = _rich_system(dopamine=1.0)
    candidates = [
        {"action": "draw", "strength": math.nan},
        {"action": "draw", "strength": -0.2},
        {"action": "draw", "strength": 0.0},
        {"action": "draw", "strength": True},
    ]
    original = deepcopy(candidates)
    report = apply_hormonal_advice(candidates, system, _normalize)
    assert report["active"] is False
    assert report["adjustments"] == []
    assert math.isnan(candidates[0]["strength"])
    assert candidates[1:] == original[1:]
