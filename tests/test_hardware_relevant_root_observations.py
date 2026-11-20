"""12B: независимые sanitized read-only наблюдения разрешённых roots."""

from copy import deepcopy

import pytest

import src.core.hardware_interoception as interoception_module
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


def _storage(free_ratio, *, total=1000, source="test"):
    return {
        "available": True,
        "total_bytes": total,
        "free_bytes": int(total * free_ratio),
        "source": source,
    }


def _observer(monkeypatch, tmp_path, *root_ids):
    roots = {root_id: tmp_path / f"private {root_id}" for root_id in root_ids}
    monkeypatch.setattr(
        "config.simulation_config.SIM_CONFIG.HARDWARE_RELEVANT_ROOTS",
        {root_id: str(path) for root_id, path in roots.items()},
    )
    observer = HardwareInteroception()
    return observer, roots


def _patch_extra_reads(monkeypatch, readings):
    calls = []

    def read(path):
        calls.append(path)
        value = readings[path]
        if isinstance(value, BaseException):
            raise value
        return deepcopy(value)

    monkeypatch.setattr(
        interoception_module, "read_relevant_root_storage", read, raising=False
    )
    return calls


def _empty_writes():
    return {
        "latest": {
            "operation": None,
            "outcome": "unknown",
            "category": "no_observation",
            "origin": "unknown",
            "cycle": None,
        },
        "sample_count": 0,
    }


def test_roots_use_free_ratio_without_disclosing_absolute_bytes_or_paths(
    monkeypatch, tmp_path
):
    observer, roots = _observer(monkeypatch, tmp_path, "archive")
    _patch_extra_reads(
        monkeypatch,
        {str(roots["archive"].absolute()): _storage(0.1, total=10_000)},
    )

    report = observer.observe(
        _resources(), cycle=0, storage_status=_storage(0.8, total=1000)
    )
    roots_report = report["relevant_root_observations"]

    assert set(roots_report) == {"data", "archive"}
    assert roots_report["data"]["channel"]["value"] == pytest.approx(0.8)
    assert roots_report["archive"]["channel"]["value"] == pytest.approx(0.1)
    for root_report in roots_report.values():
        assert root_report["channel"]["unit"] == "free_ratio"
        assert "free_bytes" not in root_report["channel"]
        assert "total_bytes" not in root_report["channel"]
    assert str(tmp_path) not in str(roots_report)


def test_one_root_failure_does_not_hide_or_reset_other_roots(monkeypatch, tmp_path):
    observer, roots = _observer(monkeypatch, tmp_path, "archive", "drafts")
    readings = {
        str(roots["archive"].absolute()): _storage(0.8),
        str(roots["drafts"].absolute()): _storage(0.8),
    }
    _patch_extra_reads(monkeypatch, readings)
    observer.observe(_resources(), cycle=0, storage_status=_storage(0.8))

    readings[str(roots["archive"].absolute())] = {
        "available": False,
        "reason": "source_error",
        "source": "test",
    }
    readings[str(roots["drafts"].absolute())] = _storage(0.7)
    report = observer.observe(_resources(), cycle=1, storage_status=_storage(0.8))
    roots_report = report["relevant_root_observations"]

    assert roots_report["archive"]["channel"] == {
        "status": "unavailable",
        "value": None,
        "reason": "source_error",
        "source": "test",
    }
    assert roots_report["archive"]["trend"]["reason"] == "channel_unavailable"
    assert roots_report["data"]["channel"]["status"] == "available"
    assert roots_report["data"]["trend"]["window_size"] == 2
    assert roots_report["drafts"]["channel"]["value"] == pytest.approx(0.7)
    assert roots_report["drafts"]["trend"]["window_size"] == 2
    assert report["states"]["storage_risk"]["value"] == 0.0


def test_unavailable_extra_root_is_not_empty_full_or_safe(monkeypatch, tmp_path):
    observer, roots = _observer(monkeypatch, tmp_path, "archive")
    _patch_extra_reads(
        monkeypatch,
        {
            str(roots["archive"].absolute()): {
                "available": False,
                "reason": "source_error",
                "source": "test",
            }
        },
    )

    report = observer.observe(_resources(), cycle=0, storage_status=_storage(0.8))
    archive = report["relevant_root_observations"]["archive"]

    assert archive["channel"]["status"] == "unavailable"
    assert archive["channel"]["value"] is None
    assert archive["trend"] == {
        "version": 1,
        "window_size": 0,
        "decline_cycles": 0,
        "drop": None,
        "reason": "channel_unavailable",
    }
    assert report["states"]["storage_risk"]["value"] == 0.0
    assert report["endocrine_events"] == []


def test_root_trends_are_independent_bounded_and_do_not_interpolate(
    monkeypatch, tmp_path
):
    observer, roots = _observer(monkeypatch, tmp_path, "archive", "drafts")
    archive_path = str(roots["archive"].absolute())
    drafts_path = str(roots["drafts"].absolute())
    readings = {archive_path: _storage(0.8), drafts_path: _storage(0.8)}
    calls = _patch_extra_reads(monkeypatch, readings)

    for cycle, free_ratio in enumerate((0.8, 0.7, 0.6, 0.5)):
        readings[archive_path] = _storage(free_ratio)
        report = observer.observe(
            _resources(), cycle=cycle, storage_status=_storage(0.8)
        )
    roots_report = report["relevant_root_observations"]
    assert roots_report["archive"]["trend"]["decline_cycles"] == 3
    assert roots_report["archive"]["trend"]["drop"] == pytest.approx(0.3)
    assert roots_report["drafts"]["trend"]["decline_cycles"] == 0
    assert roots_report["drafts"]["trend"]["drop"] is None

    readings[archive_path] = {"available": False, "reason": "source_error"}
    report = observer.observe(_resources(), cycle=4, storage_status=_storage(0.8))
    assert report["relevant_root_observations"]["archive"]["trend"]["window_size"] == 0
    assert report["relevant_root_observations"]["drafts"]["trend"]["window_size"] == 5
    before_duplicate = deepcopy(observer.status()["relevant_root_observations"])
    call_count = len(calls)
    duplicate = observer.observe(_resources(), cycle=4, storage_status=_storage(0.1))
    assert duplicate["skipped"] == "duplicate_cycle"
    assert len(calls) == call_count
    assert observer.status()["relevant_root_observations"] == before_duplicate

    readings[archive_path] = _storage(0.4)
    report = observer.observe(_resources(), cycle=10, storage_status=_storage(0.8))
    roots_report = report["relevant_root_observations"]
    assert roots_report["archive"]["trend"]["window_size"] == 1
    assert roots_report["archive"]["trend"]["reason"] == "no_sustained_decline"
    assert roots_report["drafts"]["trend"]["window_size"] == 1
    assert roots_report["drafts"]["trend"]["reason"] == "noncontiguous_observation"

    for cycle in range(11, 22):
        readings[archive_path] = _storage(max(0.01, 0.4 - (cycle - 10) * 0.02))
        report = observer.observe(
            _resources(), cycle=cycle, storage_status=_storage(0.8)
        )
    assert report["relevant_root_observations"]["archive"]["trend"]["window_size"] == 8
    assert report["relevant_root_observations"]["drafts"]["trend"]["window_size"] == 8


def test_only_data_root_reuses_actual_write_outcomes(monkeypatch, tmp_path):
    observer, roots = _observer(monkeypatch, tmp_path, "archive")
    _patch_extra_reads(monkeypatch, {str(roots["archive"].absolute()): _storage(0.8)})
    observer.record_storage_write(
        "checkpoint", outcome="failed", category="no_space", cycle=0
    )

    report = observer.observe(_resources(), cycle=0, storage_status=_storage(0.1))
    roots_report = report["relevant_root_observations"]

    assert roots_report["data"]["writes"]["sample_count"] == 1
    assert roots_report["data"]["writes"]["latest"]["category"] == "no_space"
    assert roots_report["archive"]["writes"] == _empty_writes()


def test_observation_dtos_are_deep_copied_and_sanitized(monkeypatch, tmp_path):
    observer, roots = _observer(monkeypatch, tmp_path, "archive")
    _patch_extra_reads(monkeypatch, {str(roots["archive"].absolute()): _storage(0.8)})
    report = observer.observe(_resources(), cycle=0, storage_status=_storage(0.8))

    report["relevant_root_observations"]["archive"]["channel"]["value"] = 999
    report["relevant_root_observations"]["archive"]["trend"]["window_size"] = 999
    report["relevant_root_observations"]["archive"]["writes"]["latest"]["operation"] = (
        "tampered"
    )
    status = observer.status()
    assert status["relevant_root_observations"]["archive"]["channel"][
        "value"
    ] == pytest.approx(0.8)
    assert status["relevant_root_observations"]["archive"]["trend"]["window_size"] == 1
    assert status["relevant_root_observations"]["archive"]["writes"] == _empty_writes()

    status["relevant_root_observations"]["data"]["channel"]["status"] = "tampered"
    assert (
        observer.status()["relevant_root_observations"]["data"]["channel"]["status"]
        == "available"
    )
    assert str(tmp_path) not in str(status["relevant_root_observations"])


def test_restart_marks_allowed_roots_stale_and_removed_roots_stay_removed(
    monkeypatch, tmp_path
):
    observer, roots = _observer(monkeypatch, tmp_path, "archive")
    _patch_extra_reads(monkeypatch, {str(roots["archive"].absolute()): _storage(0.8)})
    observer.observe(_resources(), cycle=0, storage_status=_storage(0.8))
    checkpoint = observer.to_checkpoint()

    assert checkpoint["schema_version"] == 6
    assert "relevant_root_observations" not in checkpoint
    restored = HardwareInteroception.from_checkpoint(deepcopy(checkpoint))
    restored_roots = restored.status()["relevant_root_observations"]
    assert set(restored_roots) == {"data", "archive"}
    assert restored_roots["data"]["channel"]["status"] == "stale"
    assert restored_roots["archive"]["channel"]["status"] == "stale"

    monkeypatch.setattr(
        "config.simulation_config.SIM_CONFIG.HARDWARE_RELEVANT_ROOTS", {}
    )
    removed = HardwareInteroception.from_checkpoint(deepcopy(checkpoint))
    calls = _patch_extra_reads(monkeypatch, {})
    report = removed.observe(_resources(), cycle=1, storage_status=_storage(0.8))
    assert set(report["relevant_root_observations"]) == {"data"}
    assert calls == []


def test_disk_usage_error_is_sanitized_and_does_not_create_root(monkeypatch, tmp_path):
    private_root = tmp_path / "missing private root"

    def deny(path):
        raise OSError(f"private read failure: {path}")

    monkeypatch.setattr(interoception_module.shutil, "disk_usage", deny)

    assert interoception_module.read_relevant_root_storage(private_root) == {
        "available": False,
        "reason": "source_error",
        "source": "shutil.disk_usage",
    }
    assert not private_root.exists()
