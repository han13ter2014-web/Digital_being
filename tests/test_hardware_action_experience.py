"""Этап 9A: тестовые векторы ожидаемости после завершённого действия."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.core.hardware_interoception import (
    HardwareInteroception,
    observe_hardware_interoception,
    validate_hardware_interoception,
)


def _resources(*, high=True):
    level = 95.0 if high else 20.0
    process = 90.0 if high else 10.0
    return {
        "available": True,
        "host_cpu_percent": level,
        "process_cpu_percent": process,
        "host_memory_percent": level,
        "process_rss_mb": 100.0,
        "process_rss_ratio": 0.95 if high else 0.2,
        "cycle_duration_ms": 12.0,
        "score": 0.95 if high else 0.2,
        "source": "test",
    }


def _observe_action(
    observer,
    cycle,
    *,
    action=None,
    action_cycle=None,
    status="completed",
    high=True,
    private=None,
):
    context = None
    if action is not None:
        context = {
            "action": action,
            "cycle": cycle - 1 if action_cycle is None else action_cycle,
            "status": status,
        }
        if private:
            context.update(private)
    return observer.observe(
        _resources(high=high),
        cycle=cycle,
        storage_status={
            "available": True,
            "total_bytes": 1000,
            "free_bytes": 800,
            "source": "test",
        },
        physical_status={},
        action_context=context,
    )


def test_stage9_only_previous_completed_action_creates_action_experience():
    observer = HardwareInteroception()

    absent = _observe_action(observer, 0)
    assert absent["action_experience"]["reason"] == "no_previous_completed_action"

    current = _observe_action(observer, 1, action="explore", action_cycle=1)
    assert current["action_experience"]["reason"] == "invalid_action_context"
    assert current["action_experience"]["sample_count"] == 0

    selected = _observe_action(observer, 2, action="explore", status="selected")
    assert selected["action_experience"]["reason"] == "invalid_action_context"
    assert selected["action_experience"]["sample_count"] == 0

    completed = _observe_action(observer, 3, action="explore")
    experience = completed["action_experience"]
    assert experience["action"] == "explore"
    assert experience["sample_count"] == 1
    assert experience["expectedness"] == "unknown"
    assert experience["freshness"] == "fresh"
    assert experience["reason"] == "observed_after_completed_action"
    assert experience["risk"] == pytest.approx(completed["states"]["own_load"]["value"])


def test_stage9_equal_risk_has_separate_expectations_for_different_actions():
    observer = HardwareInteroception()
    for cycle in range(200):
        report = _observe_action(
            observer,
            cycle,
            action=None if cycle == 0 else "explore",
        )

    explore = report["action_experience"]
    assert explore["action"] == "explore"
    assert explore["sample_count"] == 199
    assert explore["expectedness"] == "familiar"
    explore_risk = explore["risk"]

    first_rest = _observe_action(observer, 200, action="rest")["action_experience"]
    assert first_rest["action"] == "rest"
    assert first_rest["sample_count"] == 1
    assert first_rest["expectedness"] == "unknown"
    assert first_rest["risk"] == pytest.approx(explore_risk)

    explore_again = _observe_action(observer, 201, action="explore")[
        "action_experience"
    ]
    assert explore_again["sample_count"] == 200
    assert explore_again["expectedness"] == "familiar"
    assert explore_again["risk"] == pytest.approx(first_rest["risk"])


def test_stage9_action_context_rejects_gaps_duplicates_and_private_fields():
    observer = HardwareInteroception()
    first = _observe_action(observer, 1, action="explore")
    assert first["action_experience"]["sample_count"] == 1
    before_duplicate = deepcopy(observer.to_checkpoint())

    duplicate = _observe_action(observer, 1, action="explore")
    assert duplicate["skipped"] == "duplicate_cycle"
    assert observer.to_checkpoint() == before_duplicate

    gap = _observe_action(observer, 3, action="explore", action_cycle=1)
    assert gap["action_experience"]["reason"] == "invalid_action_context"
    assert gap["action_experience"]["sample_count"] == 1

    private = _observe_action(
        observer,
        4,
        action="explore",
        private={
            "target": "private goal",
            "params": {"path": "C:/private/secret.txt"},
            "text": "private message",
        },
    )
    assert private["action_experience"]["sample_count"] == 2
    serialized = str(private) + str(observer.to_checkpoint())
    assert "private goal" not in serialized
    assert "C:/private" not in serialized
    assert "private message" not in serialized

    unknown = _observe_action(observer, 5, action="../../private")
    assert unknown["action_experience"]["reason"] == "invalid_action_context"
    assert unknown["action_experience"]["sample_count"] == 2

    _observe_action(observer, 6, action="rest")
    wrong_action = _observe_action(observer, 7, action="explore", status="selected")
    assert wrong_action["action_experience"]["reason"] == "invalid_action_context"
    assert wrong_action["action_experience"]["sample_count"] == 2


def test_stage9_action_experience_survives_restart_without_offline_learning():
    observer = HardwareInteroception()
    for cycle in range(30):
        _observe_action(
            observer,
            cycle,
            action=None if cycle == 0 else "explore",
        )

    state = observer.to_checkpoint()
    assert state["schema_version"] == 6
    assert state["action_experience"]["explore"]["sample_count"] == 29
    validate_hardware_interoception(state)

    restored = HardwareInteroception.from_checkpoint(state)
    latest = restored.status()["action_experience"]["latest"]
    assert latest["freshness"] == "stale"
    assert latest["risk"] is None
    assert restored.to_checkpoint()["action_experience"] == state["action_experience"]

    fresh = _observe_action(restored, 30, action="explore")["action_experience"]
    assert fresh["freshness"] == "fresh"
    assert fresh["sample_count"] == 30
    assert fresh["expectedness"] == "unknown"

    legacy = deepcopy(state)
    legacy["schema_version"] = 4
    legacy.pop("action_experience")
    migrated = HardwareInteroception.from_checkpoint(legacy)
    assert migrated.to_checkpoint()["schema_version"] == 6
    assert migrated.to_checkpoint()["action_experience"] == {}
    validate_hardware_interoception(migrated.to_checkpoint())

    corrupted = deepcopy(state)
    corrupted["action_experience"]["explore"] = None
    with pytest.raises(ValueError, match="invalid profile"):
        HardwareInteroception.from_checkpoint(corrupted)


def test_stage9_wrapper_reads_only_previous_performed_action():
    observer = HardwareInteroception()
    agent = SimpleNamespace(
        hardware_interoception=observer,
        hormonal_system=None,
        _normalize_action=lambda action: {
            "exploration": "explore",
        }.get(action, action),
        _intention_history=[
            {
                "cycle": 0,
                "action": "exploration",
                "status": "performed",
                "target": "private goal",
                "outcome": {"text": "private result"},
            }
        ],
    )

    report = observe_hardware_interoception(agent, _resources(high=False), 1)
    experience = report["action_experience"]
    assert experience["action"] == "explore"
    assert experience["sample_count"] == 1
    assert experience["freshness"] == "fresh"

    agent._intention_history.append(
        {"cycle": 1, "action": "explore", "status": "denied"}
    )
    denied = observe_hardware_interoception(agent, _resources(high=False), 2)
    assert denied["action_experience"]["reason"] == "no_previous_completed_action"
    assert observer.action_experience.profiles["explore"].observation_count == 1

    gap = observe_hardware_interoception(agent, _resources(high=False), 4)
    assert gap["action_experience"]["reason"] == "no_previous_completed_action"
    serialized = str(report) + str(observer.to_checkpoint())
    assert "private goal" not in serialized
    assert "private result" not in serialized
