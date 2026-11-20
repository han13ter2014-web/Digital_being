"""10B: устойчивый storage-тренд отделён от одиночных скачков и записей."""

from copy import deepcopy

import pytest

from src.core.hardware_interoception import HardwareInteroception


def _resources():
    return {
        "available": True,
        "host_cpu_percent": 10.0,
        "process_cpu_percent": 5.0,
        "host_memory_percent": 20.0,
        "process_rss_mb": 50.0,
        "process_rss_ratio": 0.1,
        "cycle_duration_ms": 10.0,
        "source": "test",
    }


def _storage(free_ratio):
    return {
        "available": True,
        "total_bytes": 1000,
        "free_bytes": int(1000 * free_ratio),
        "source": "test",
    }


def _observe(observer, cycle, free_ratio):
    return observer.observe(
        _resources(), cycle=cycle, storage_status=_storage(free_ratio)
    )


def test_single_drop_is_not_trend_and_stable_low_preserves_base_risk():
    observer = HardwareInteroception()
    _observe(observer, 0, 0.8)
    report = _observe(observer, 1, 0.5)

    state = report["states"]["storage_risk"]
    assert state["value"] == 0.0
    assert state["evidence"] == ["data_free_ratio=0.500"]
    assert report["storage_trend"] == {
        "version": 1,
        "window_size": 2,
        "decline_cycles": 1,
        "drop": None,
        "reason": "insufficient_sustained_decline",
    }

    low = HardwareInteroception()
    for cycle in range(5):
        low_report = _observe(low, cycle, 0.01)
    assert low_report["states"]["storage_risk"]["value"] == pytest.approx(0.96)
    assert low_report["storage_trend"]["drop"] is None
    assert len(low_report["endocrine_events"]) == 1
    assert low_report["endocrine_events"][0]["reason"] == "sustained_storage_risk"


def test_three_contiguous_declines_create_versioned_bounded_evidence():
    observer = HardwareInteroception()
    for cycle, free_ratio in enumerate((0.8, 0.7, 0.6)):
        report = _observe(observer, cycle, free_ratio)
        assert report["states"]["storage_risk"]["value"] == 0.0
        assert report["storage_trend"]["drop"] is None

    report = _observe(observer, 3, 0.5)
    state = report["states"]["storage_risk"]
    assert state["value"] == pytest.approx(0.6)
    assert state["reason"] == "observed_data_storage"
    assert state["origin"] == "unknown"
    assert "data_free_ratio_sustained_drop_v1=0.300" in state["evidence"]
    assert report["storage_trend"] == {
        "version": 1,
        "window_size": 4,
        "decline_cycles": 3,
        "drop": pytest.approx(0.3),
        "reason": "sustained_decline",
    }


def test_interrupted_decline_restarts_evidence_and_window_is_bounded():
    observer = HardwareInteroception()
    for cycle, free_ratio in enumerate((0.8, 0.7, 0.6, 0.65, 0.55)):
        report = _observe(observer, cycle, free_ratio)
    assert report["states"]["storage_risk"]["value"] == 0.0
    assert report["storage_trend"]["decline_cycles"] == 1

    _observe(observer, 5, 0.45)
    report = _observe(observer, 6, 0.35)
    assert report["states"]["storage_risk"]["value"] == pytest.approx(0.6)
    assert report["storage_trend"]["decline_cycles"] == 3

    for cycle in range(7, 30):
        report = _observe(observer, cycle, max(0.01, 0.35 - (cycle - 6) * 0.01))
    assert report["storage_trend"]["window_size"] == 8
    assert report["storage_trend"]["decline_cycles"] == 7


def test_gap_sensor_loss_duplicate_and_restart_do_not_interpolate_trend():
    gap = HardwareInteroception()
    _observe(gap, 0, 0.8)
    _observe(gap, 1, 0.7)
    report = _observe(gap, 100, 0.6)
    assert report["states"]["storage_risk"]["value"] == 0.0
    assert report["storage_trend"]["window_size"] == 1
    assert report["storage_trend"]["reason"] == "noncontiguous_observation"

    loss = HardwareInteroception()
    _observe(loss, 0, 0.8)
    _observe(loss, 1, 0.7)
    report = loss.observe(_resources(), cycle=2, storage_status={"available": False})
    assert report["storage_trend"]["reason"] == "channel_unavailable"
    assert report["storage_trend"]["window_size"] == 0
    report = _observe(loss, 3, 0.5)
    assert report["states"]["storage_risk"]["value"] == 0.0
    assert report["storage_trend"]["window_size"] == 1

    duplicate_before = deepcopy(loss.storage_trend.status())
    duplicate = _observe(loss, 3, 0.4)
    assert duplicate["skipped"] == "duplicate_cycle"
    assert loss.storage_trend.status() == duplicate_before

    restored = HardwareInteroception.from_checkpoint(loss.to_checkpoint())
    assert restored.status()["storage_trend"]["reason"] == "no_observation"
    report = _observe(restored, 4, 0.4)
    assert report["states"]["storage_risk"]["value"] == 0.0
    assert report["storage_trend"]["window_size"] == 1


def test_tiny_changes_and_write_outcomes_do_not_create_trend_risk():
    observer = HardwareInteroception()
    observer.record_storage_write(
        "checkpoint", outcome="failed", category="no_space", cycle=0
    )
    for cycle, free_ratio in enumerate((0.8, 0.799, 0.798, 0.797)):
        report = _observe(observer, cycle, free_ratio)

    state = report["states"]["storage_risk"]
    assert state["value"] == 0.0
    assert state["evidence"] == ["data_free_ratio=0.797"]
    assert report["storage_trend"]["drop"] is None
    assert observer.status()["storage_writes"]["latest"]["category"] == "no_space"
    assert "storage_writes" not in observer.to_checkpoint()
    assert "storage_trend" not in observer.to_checkpoint()


def test_exact_minimum_step_is_float_safe_and_smaller_step_is_rejected():
    exact = HardwareInteroception()
    for cycle, free_ratio in enumerate((0.700, 0.695, 0.690, 0.685)):
        report = _observe(exact, cycle, free_ratio)
    assert report["storage_trend"]["decline_cycles"] == 3
    assert report["storage_trend"]["drop"] == pytest.approx(0.015)
    assert report["states"]["storage_risk"]["value"] == pytest.approx(0.03)

    below = HardwareInteroception()
    for cycle, free_ratio in enumerate((0.700, 0.696, 0.692, 0.688)):
        report = _observe(below, cycle, free_ratio)
    assert report["storage_trend"]["drop"] is None
    assert report["states"]["storage_risk"]["value"] == 0.0


def test_storage_gap_restarts_five_cycle_event_evidence():
    observer = HardwareInteroception()
    for cycle in range(4):
        report = _observe(observer, cycle, 0.01)
        assert report["endocrine_events"] == []

    report = _observe(observer, 100, 0.01)
    assert report["endocrine_events"] == []
    assert observer.slow_states["storage"]["sustained_cycles"] == 1
    for cycle in range(101, 104):
        report = _observe(observer, cycle, 0.01)
        assert report["endocrine_events"] == []

    report = _observe(observer, 104, 0.01)
    assert len(report["endocrine_events"]) == 1
    assert report["endocrine_events"][0]["duration_cycles"] == 5


def test_sustained_trend_alone_can_cross_existing_advisor_threshold():
    from src.core.hardware_behavior import storage_risk_behavior_report

    observer = HardwareInteroception()
    for cycle, free_ratio in enumerate(
        (0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05, 0.01)
    ):
        report = _observe(observer, cycle, free_ratio)
        if cycle == 5:
            # Порог пересекает устойчивый тренд, а базовый риск ещё равен нулю.
            assert report["states"]["storage_risk"]["value"] == pytest.approx(1.0)
        if cycle < 9:
            assert report["endocrine_events"] == []

    assert report["states"]["storage_risk"]["value"] == pytest.approx(1.0)
    assert (
        "data_free_ratio_sustained_drop_v1=0.590"
        in report["states"]["storage_risk"]["evidence"]
    )
    assert len(report["endocrine_events"]) == 1
    assert report["endocrine_events"][0]["reason"] == "sustained_storage_risk"
    advisor = storage_risk_behavior_report(observer)
    assert advisor["eligible"] is True
    assert advisor["factor"] >= 0.75
    assert advisor["adjustments"] == []
