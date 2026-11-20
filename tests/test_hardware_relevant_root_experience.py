"""12C: раздельный опыт roots, additive persistence и stale после restore."""

from copy import deepcopy

import pytest

import src.core.hardware_interoception as interoception_module
from src.core.hardware_interoception import (
    HardwareInteroception,
    validate_hardware_interoception,
)


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


def _storage(free_ratio, *, total=1000):
    return {
        "available": True,
        "total_bytes": total,
        "free_bytes": int(total * free_ratio),
        "source": "test",
    }


def _observer(monkeypatch, tmp_path, *root_ids):
    roots = {root_id: tmp_path / f"private {root_id}" for root_id in root_ids}
    monkeypatch.setattr(
        "config.simulation_config.SIM_CONFIG.HARDWARE_RELEVANT_ROOTS",
        {root_id: str(path) for root_id, path in roots.items()},
    )
    observer = HardwareInteroception()
    return observer, roots


def _patch_reads(monkeypatch, roots, values):
    readings = {
        str(roots[root_id].absolute()): _storage(value)
        for root_id, value in values.items()
    }
    monkeypatch.setattr(
        interoception_module,
        "read_relevant_root_storage",
        lambda path: deepcopy(readings[path]),
    )
    return readings


def _observe(observer, cycle, data_free=0.8):
    return observer.observe(
        _resources(), cycle=cycle, storage_status=_storage(data_free)
    )


def test_root_risk_and_experience_are_independent_and_shadow_only(
    monkeypatch, tmp_path
):
    observer, roots = _observer(monkeypatch, tmp_path, "archive", "drafts")
    readings = _patch_reads(monkeypatch, roots, {"archive": 0.01, "drafts": 0.8})

    for cycle in range(5):
        report = _observe(observer, cycle)
    roots_report = report["relevant_root_observations"]

    assert roots_report["data"]["risk"] == report["states"]["storage_risk"]
    assert roots_report["data"]["experience"] == report["domain_experience"]["storage"]
    assert roots_report["archive"]["risk"]["value"] == pytest.approx(0.96)
    assert roots_report["archive"]["experience"]["latest"]["risk"] == pytest.approx(
        0.96
    )
    assert roots_report["archive"]["experience"]["latest"]["freshness"] == "fresh"
    assert roots_report["archive"]["experience"]["current_episode"]["strain_cycle"] == 4
    assert roots_report["drafts"]["risk"]["value"] == 0.0
    assert roots_report["drafts"]["experience"]["latest"]["experienced"] == 0.0
    assert roots_report["data"]["experience"]["observation_count"] == 5
    assert roots_report["archive"]["experience"]["observation_count"] == 5
    assert roots_report["drafts"]["experience"]["observation_count"] == 5
    assert report["endocrine_events"] == []

    readings[str(roots["drafts"].absolute())] = _storage(0.01)
    report = _observe(observer, 5)
    assert report["relevant_root_observations"]["archive"]["risk"][
        "value"
    ] == pytest.approx(0.96)
    assert report["relevant_root_observations"]["drafts"]["risk"][
        "value"
    ] == pytest.approx(0.96)
    assert report["states"]["storage_risk"]["value"] == 0.0
    assert report["endocrine_events"] == []


def test_familiarity_of_one_root_does_not_change_another_or_objective_risk(
    monkeypatch, tmp_path
):
    observer, roots = _observer(monkeypatch, tmp_path, "archive", "drafts")
    _patch_reads(monkeypatch, roots, {"archive": 0.01, "drafts": 0.8})

    for cycle in range(100):
        report = _observe(observer, cycle)
    roots_report = report["relevant_root_observations"]
    archive = roots_report["archive"]["experience"]
    drafts = roots_report["drafts"]["experience"]

    assert archive["adaptation"] >= 0.3
    assert archive["latest"]["expectedness"] == "familiar"
    assert archive["latest"]["experienced"] < archive["latest"]["risk"]
    assert archive["latest"]["risk"] == pytest.approx(0.96)
    assert drafts["adaptation"] == 0.0
    assert drafts["latest"]["expectedness"] == "unknown"
    assert drafts["latest"]["experienced"] == 0.0
    assert roots_report["data"]["experience"]["adaptation"] == 0.0
    assert report["states"]["storage_risk"]["value"] == 0.0
    assert report["endocrine_events"] == []


def test_schema6_roundtrip_preserves_experience_but_marks_measurements_stale(
    monkeypatch, tmp_path
):
    observer, roots = _observer(monkeypatch, tmp_path, "archive")
    _patch_reads(monkeypatch, roots, {"archive": 0.01})
    for cycle in range(25):
        _observe(observer, cycle)
    observer.record_storage_write(
        "checkpoint", outcome="failed", category="no_space", cycle=24
    )

    checkpoint = observer.to_checkpoint()
    assert checkpoint["schema_version"] == 6
    assert set(checkpoint["relevant_root_experience"]) == {"archive"}
    assert "data" not in checkpoint["relevant_root_experience"]
    assert "trend" not in checkpoint["relevant_root_experience"]["archive"]
    assert "writes" not in checkpoint["relevant_root_experience"]["archive"]
    validate_hardware_interoception(checkpoint)

    restored = HardwareInteroception.from_checkpoint(deepcopy(checkpoint))
    roots_status = restored.status()["relevant_root_observations"]
    archive = roots_status["archive"]
    assert archive["channel"]["status"] == "stale"
    assert archive["channel"]["value"] == pytest.approx(0.01)
    assert archive["channel"]["reason"] == (
        "waiting_for_fresh_observation_after_restart"
    )
    assert archive["risk"]["value"] is None
    assert archive["risk"]["reason"] == "waiting_for_fresh_observation_after_restart"
    assert archive["experience"]["latest"]["risk"] is None
    assert archive["experience"]["latest"]["freshness"] == "stale"
    assert archive["experience"]["current_episode"]["fresh_observations"] == 25
    assert archive["trend"]["reason"] == "no_observation"
    assert archive["writes"]["sample_count"] == 0
    assert roots_status["data"]["channel"]["status"] == "stale"
    assert roots_status["data"]["writes"]["sample_count"] == 0
    assert restored.to_checkpoint()["schema_version"] == 6
    validate_hardware_interoception(restored.to_checkpoint())


def test_legacy_and_removed_roots_do_not_create_or_restore_measurements(
    monkeypatch, tmp_path
):
    observer, roots = _observer(monkeypatch, tmp_path, "archive")
    _patch_reads(monkeypatch, roots, {"archive": 0.01})
    _observe(observer, 0)
    current = observer.to_checkpoint()

    legacy = deepcopy(current)
    legacy["schema_version"] = 5
    legacy.pop("relevant_root_experience")
    migrated = HardwareInteroception.from_checkpoint(legacy)
    migrated_roots = migrated.status()["relevant_root_observations"]
    assert set(migrated_roots) == {"data"}
    assert migrated_roots["data"]["channel"]["status"] == "stale"
    assert migrated.relevant_root_experiences["archive"].last_cycle is None
    assert migrated.to_checkpoint()["schema_version"] == 6
    validate_hardware_interoception(migrated.to_checkpoint())

    monkeypatch.setattr(
        "config.simulation_config.SIM_CONFIG.HARDWARE_RELEVANT_ROOTS", {}
    )
    removed = HardwareInteroception.from_checkpoint(deepcopy(current))
    assert set(removed.status()["relevant_root_observations"]) == {"data"}
    assert removed.relevant_root_experiences == {}
    assert "archive" not in removed.to_checkpoint()["relevant_root_experience"]


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda state: state["relevant_root_experience"].update({"data": {}}),
        lambda state: state["relevant_root_experience"].update({"Bad ID": {}}),
        lambda state: state["relevant_root_experience"]["archive"]["channel"].update(
            {"path": "C:/private"}
        ),
        lambda state: state["relevant_root_experience"]["archive"]["channel"].update(
            {"free_bytes": 10}
        ),
        lambda state: state["relevant_root_experience"]["archive"]["profile"].update(
            {"adaptation": 2.0}
        ),
        lambda state: state["relevant_root_experience"]["archive"]["slow_state"].update(
            {"sustained_cycles": -1}
        ),
    ],
)
def test_schema6_rejects_corrupt_or_unsafe_root_state(corrupt, monkeypatch, tmp_path):
    observer, roots = _observer(monkeypatch, tmp_path, "archive")
    _patch_reads(monkeypatch, roots, {"archive": 0.8})
    _observe(observer, 0)
    state = observer.to_checkpoint()

    corrupt(state)

    with pytest.raises(ValueError):
        validate_hardware_interoception(state)


def test_sensor_loss_gap_and_duplicate_do_not_create_root_episode_evidence(
    monkeypatch, tmp_path
):
    observer, roots = _observer(monkeypatch, tmp_path, "archive")
    readings = _patch_reads(monkeypatch, roots, {"archive": 0.01})
    archive_path = str(roots["archive"].absolute())

    for cycle in range(4):
        report = _observe(observer, cycle)
    archive = report["relevant_root_observations"]["archive"]
    assert archive["experience"]["current_episode"]["strain_cycle"] is None
    assert archive["experience"]["observation_count"] == 4

    before_duplicate = deepcopy(observer.status()["relevant_root_observations"])
    duplicate = _observe(observer, 3, data_free=0.01)
    assert duplicate["skipped"] == "duplicate_cycle"
    assert observer.status()["relevant_root_observations"] == before_duplicate

    report = _observe(observer, 100)
    archive = report["relevant_root_observations"]["archive"]
    assert archive["experience"]["current_episode"]["strain_cycle"] is None
    assert archive["experience"]["current_episode"]["start_cycle"] == 0

    readings[archive_path] = {"available": False, "reason": "source_error"}
    report = _observe(observer, 101)
    archive = report["relevant_root_observations"]["archive"]
    assert archive["risk"]["value"] is None
    assert archive["experience"]["latest"]["freshness"] == "unavailable"
    assert archive["experience"]["latest"]["reason"] == "channel_unavailable"
    assert report["endocrine_events"] == []


def test_six_hundred_cycles_two_restarts_and_bounded_root_histories(
    monkeypatch, tmp_path
):
    observer, roots = _observer(monkeypatch, tmp_path, "archive", "drafts")
    readings = _patch_reads(monkeypatch, roots, {"archive": 0.8, "drafts": 0.8})
    archive_path = str(roots["archive"].absolute())

    for cycle in range(600):
        # Длинные высокие и низкие серии создают реальные завершённые эпизоды.
        readings[archive_path] = _storage(0.01 if (cycle // 10) % 2 == 0 else 0.8)
        report = _observe(observer, cycle)
        assert set(report["relevant_root_observations"]) == {
            "data",
            "archive",
            "drafts",
        }
        if cycle in {199, 399}:
            observer = HardwareInteroception.from_checkpoint(observer.to_checkpoint())
            stale = observer.status()["relevant_root_observations"]["archive"]
            assert stale["channel"]["status"] == "stale"
            assert stale["experience"]["latest"]["freshness"] == "stale"

    assert len(observer.history) == 200
    assert len(observer.relevant_root_experiences["archive"].profile["episodes"]) <= 25
    assert (
        observer.relevant_root_experiences["archive"].profile["completed_episode_count"]
        > 0
    )
    assert (
        observer.relevant_root_experiences["drafts"].profile["completed_episode_count"]
        == 0
    )
    assert report["endocrine_events"] == []
    validate_hardware_interoception(observer.to_checkpoint())
