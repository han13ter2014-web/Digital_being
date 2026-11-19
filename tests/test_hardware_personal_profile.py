"""Личный опыт аппаратной интероцепции: привыкание без сокрытия риска."""

from copy import deepcopy

import pytest

from src.core.hardware_interoception import (
    HardwareInteroception,
    validate_hardware_interoception,
)


@pytest.fixture(autouse=True)
def _disable_real_physical_sampling(monkeypatch):
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_physical_sensors", lambda: {}
    )


def _resources(*, high=False, slow=False):
    level = 95.0 if high else 20.0
    process = 90.0 if high else 10.0
    return {
        "available": True,
        "host_cpu_percent": level,
        "process_cpu_percent": process,
        "host_memory_percent": level,
        "process_rss_mb": 100.0,
        "process_rss_ratio": 0.95 if high else 0.2,
        "cycle_duration_ms": 100.0 if slow else 12.0,
        "slow_cycle": slow,
        "score": 0.95 if high else 0.2,
        "source": "test",
    }


def _storage(free_ratio=0.8):
    return {
        "available": True,
        "total_bytes": 1000,
        "free_bytes": int(1000 * free_ratio),
        "source": "test",
    }


def _observe(observer, cycle, *, high=False, slow=False):
    return observer.observe(
        _resources(high=high, slow=slow),
        cycle=cycle,
        storage_status=_storage(),
    )


def _episode(observer, start, *, slow=False):
    for offset in range(5):
        _observe(observer, start + offset, high=True, slow=slow)
    for offset in range(5, 10):
        _observe(observer, start + offset)


def test_baseline_requires_fresh_observations_and_idle_is_not_adaptation():
    observer = HardwareInteroception()
    for cycle in range(50):
        _observe(observer, cycle)

    profile = observer.personal
    baseline = profile.baseline["own_load"]
    assert baseline["sample_count"] == 50
    assert baseline["baseline"] is not None
    assert profile.adaptation == 0.0
    assert profile.observation_count == 50

    before = deepcopy(profile.to_checkpoint())
    for cycle in range(50, 55):
        observer.observe(
            {"available": False, "reason": "sensor_disabled"},
            cycle=cycle,
            storage_status={"available": False, "reason": "sensor_disabled"},
        )
    duplicate = _observe(observer, 54)
    assert duplicate["skipped"] == "duplicate_cycle"
    assert profile.to_checkpoint() == before


def test_chronic_strain_becomes_familiar_but_risk_and_strain_remain():
    observer = HardwareInteroception()
    for cycle in range(200):
        report = _observe(observer, cycle, high=True)

    experience = report["personal_experience"]["latest_experience"]
    own = experience["own_load"]
    environment = experience["environmental_pressure"]
    assert observer.strain_active is True
    assert observer.personal.adaptation == pytest.approx(0.5)
    assert own["expectedness"] == "familiar"
    assert own["risk"] == pytest.approx(0.915)
    assert own["experienced"] == pytest.approx(own["risk"] * 0.9)
    assert environment["risk"] == pytest.approx(0.95)
    assert [event["type"] for event in observer.events] == ["hardware_strain"]
    assert not any(event["type"] == "hardware_recovery" for event in observer.events)


def test_completed_episodes_update_bounded_parameters_and_recovery_shadow():
    observer = HardwareInteroception()
    for start in (0, 10, 20):
        _episode(observer, start)

    profile = observer.personal
    assert profile.completed_episode_count == 3
    assert len(profile.episodes) == 3
    assert profile.adaptation == pytest.approx(0.06)
    assert 0.8 <= profile.sensitivity < 1.0
    assert 10.0 <= profile.strain_half_life <= 20.0
    assert 1.0 < profile.recovery_rate <= 1.25
    assert profile.shadow_recovery > 0.0
    validate_hardware_interoception(observer.to_checkpoint())


def test_sensor_loss_does_not_grow_continuous_recovery():
    observer = HardwareInteroception()
    _episode(observer, 0)
    initial = observer.personal.shadow_recovery
    assert initial > 0.0

    for cycle in range(10, 15):
        observer.observe(
            {"available": False},
            cycle=cycle,
            storage_status=_storage(),
        )
    assert observer.personal.shadow_recovery == initial


def test_checkpoint_v3_round_trip_v1_migration_and_corruption():
    observer = HardwareInteroception()
    for cycle in range(30):
        _observe(observer, cycle, high=True)
    state = observer.to_checkpoint()
    assert state["schema_version"] == 3
    validate_hardware_interoception(state)

    restored = HardwareInteroception.from_checkpoint(state)
    assert (
        restored.personal.to_checkpoint()["personal_profile"]
        == state["personal_profile"]
    )
    assert restored.personal.current_episode == state["current_episode"]
    assert all(
        item["risk"] is None and item["experienced"] is None
        for item in restored.personal.latest_experience.values()
    )
    assert restored.latest_observation["channels"]["host_cpu"]["status"] == "stale"
    assert (
        restored.latest_observation["channels"]["gpu_temperature"]["status"]
        == "unavailable"
    )

    legacy = deepcopy(state)
    legacy["schema_version"] = 1
    for key in (
        "personal_profile",
        "current_episode",
        "episodes",
        "shadow_strain",
        "shadow_recovery",
        "latest_experience",
    ):
        legacy.pop(key)
    for name in (
        "gpu_utilization",
        "gpu_memory",
        "gpu_temperature",
        "gpu_power",
        "cpu_temperature",
        "external_power",
        "battery_charge",
    ):
        legacy["latest_observation"]["channels"].pop(name)
    migrated = HardwareInteroception.from_checkpoint(legacy)
    assert migrated.history == state["history"]
    assert migrated.personal.observation_count == 0
    assert migrated.personal.adaptation == 0.0
    assert migrated.to_checkpoint()["schema_version"] == 3

    corrupted = deepcopy(state)
    corrupted["personal_profile"]["sensitivity"] = 2.0
    with pytest.raises(ValueError, match="sensitivity"):
        HardwareInteroception.from_checkpoint(corrupted)


def test_determinism_and_ten_thousand_cycle_soak_keep_all_histories_bounded():
    first = HardwareInteroception()
    second = HardwareInteroception()
    for cycle in range(10_000):
        high = (cycle // 10) % 2 == 0
        _observe(first, cycle, high=high)
        _observe(second, cycle, high=high)

    assert first.to_checkpoint() == second.to_checkpoint()
    assert len(first.history) == 200
    assert len(first.events) == 50
    assert len(first.personal.episodes) == 50
    assert first.personal.completed_episode_count == 500
    assert first.personal.adaptation == pytest.approx(1.0)
    assert 0.8 <= first.personal.sensitivity <= 1.2
    assert 10.0 <= first.personal.strain_half_life <= 80.0
    assert 0.75 <= first.personal.recovery_rate <= 1.25
    validate_hardware_interoception(first.to_checkpoint())


def test_diagnostic_dto_and_legacy_restore_exclude_raw_os_details():
    observer = HardwareInteroception()
    report = observer.observe(
        {
            "available": False,
            "reason": "C:/private/sensor failure",
            "source": "C:/private/python.exe",
        },
        cycle=1,
        storage_status={
            "available": False,
            "reason": "C:/private/disk failure",
            "source": "C:/private/disk.exe",
        },
    )
    serialized = str(report)
    assert "C:/private" not in serialized
    assert report["observation"]["channels"]["host_cpu"]["reason"] == (
        "resource_source_unavailable"
    )
    assert report["observation"]["channels"]["data_storage"]["reason"] == (
        "storage_unavailable"
    )

    state = observer.to_checkpoint()
    state["schema_version"] = 1
    for key in (
        "personal_profile",
        "current_episode",
        "episodes",
        "shadow_strain",
        "shadow_recovery",
        "latest_experience",
    ):
        state.pop(key)
    for name in (
        "gpu_utilization",
        "gpu_memory",
        "gpu_temperature",
        "gpu_power",
        "cpu_temperature",
        "external_power",
        "battery_charge",
    ):
        state["latest_observation"]["channels"].pop(name)
    for channel in state["latest_observation"]["channels"].values():
        channel["reason"] = "C:/private/restored failure"
        channel["source"] = "C:/private/restored.exe"
    state["latest_observation"]["channels"]["host_cpu"]["status"] = "stale"
    restored = HardwareInteroception.from_checkpoint(state)
    assert "C:/private" not in str(restored.status())
