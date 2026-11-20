"""12D: root-specific storage evidence и fail-closed advisor по write path."""

from copy import deepcopy

import pytest

import src.core.hardware_interoception as interoception_module
from src.core.hardware_behavior import apply_storage_risk_advice, storage_risk_evidence
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


def _storage(free_ratio):
    return {
        "available": True,
        "total_bytes": 1000,
        "free_bytes": int(1000 * free_ratio),
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


def _observe(observer, cycle, *, data_free=0.8):
    return observer.observe(
        _resources(),
        cycle=cycle,
        storage_status=_storage(data_free),
        physical_status={},
    )


def _confirmed_data_observer():
    observer = HardwareInteroception()
    for cycle in range(5):
        _observe(observer, cycle, data_free=0.01)
    return observer


def test_additional_root_evidence_needs_five_fresh_high_cycles(monkeypatch, tmp_path):
    observer, roots = _observer(monkeypatch, tmp_path, "archive")
    _patch_reads(monkeypatch, roots, {"archive": 0.01})

    for cycle in range(4):
        _observe(observer, cycle)
        archive = storage_risk_evidence(observer, root_id="archive")
        assert archive["eligible"] is False
        assert archive["reason"] == "insufficient_sustained_storage_risk"
        assert storage_risk_evidence(observer)["eligible"] is False

    _observe(observer, 4)
    archive = storage_risk_evidence(observer, root_id="archive")
    assert archive == {
        "eligible": True,
        "reason": "confirmed_storage_risk",
        "duration_cycles": 5,
        "risk": pytest.approx(0.96),
        "experienced": pytest.approx(0.96),
        "confidence": pytest.approx(1.0),
        "factor": pytest.approx(0.76),
    }
    assert observer.events == []


def test_archive_risk_never_adjusts_candidates_with_only_data_write_path(
    monkeypatch, tmp_path
):
    observer, roots = _observer(monkeypatch, tmp_path, "archive")
    _patch_reads(monkeypatch, roots, {"archive": 0.01})
    for cycle in range(5):
        _observe(observer, cycle)
    assert storage_risk_evidence(observer, root_id="archive")["eligible"] is True

    candidates = [
        {"action": "draw", "strength": 0.8},
        {"action": "compose_music", "strength": 0.7},
        {
            "action": "create_draft",
            "strength": 0.6,
            "params": {"draft_mode": "new"},
        },
        {"action": "web_search", "strength": 0.8},
        {"action": "rest", "strength": 0.9},
    ]
    before = deepcopy(candidates)
    checkpoint = observer.to_checkpoint()

    report = apply_storage_risk_advice(candidates, observer, lambda action: action)

    assert report["active"] is False
    assert report["eligible"] is False
    assert report["adjustments"] == []
    assert candidates == before
    assert observer.to_checkpoint() == checkpoint


def test_data_advisor_does_not_borrow_archive_risk_or_experience(monkeypatch, tmp_path):
    observer, roots = _observer(monkeypatch, tmp_path, "archive")
    _patch_reads(monkeypatch, roots, {"archive": 0.8})
    for cycle in range(5):
        _observe(observer, cycle, data_free=0.01)

    assert storage_risk_evidence(observer, root_id="archive")["eligible"] is False
    candidates = [{"action": "draw", "strength": 0.8}]
    report = apply_storage_risk_advice(
        candidates, observer, lambda action: action, input_strengths=[0.8]
    )

    assert report["active"] is True
    assert report["risk"] == pytest.approx(0.96)
    assert report["factor"] == pytest.approx(0.76)
    assert candidates[0]["strength"] == pytest.approx(0.608)


def test_root_evidence_fail_closed_for_gap_restart_sensor_loss_and_unknown(
    monkeypatch, tmp_path
):
    observer, roots = _observer(monkeypatch, tmp_path, "archive")
    readings = _patch_reads(monkeypatch, roots, {"archive": 0.01})
    for cycle in range(5):
        _observe(observer, cycle)

    _observe(observer, 100)
    gap = storage_risk_evidence(observer, root_id="archive")
    assert gap["eligible"] is False
    assert gap["reason"] == "insufficient_sustained_storage_risk"

    for cycle in range(101, 105):
        _observe(observer, cycle)
    assert storage_risk_evidence(observer, root_id="archive")["eligible"] is True

    restored = HardwareInteroception.from_checkpoint(observer.to_checkpoint())
    waiting = storage_risk_evidence(restored, root_id="archive")
    assert waiting["eligible"] is False
    assert waiting["reason"] == "waiting_for_fresh_storage_channel"

    readings[str(roots["archive"].absolute())] = {
        "available": False,
        "reason": "source_error",
    }
    _observe(observer, 105)
    loss = storage_risk_evidence(observer, root_id="archive")
    assert loss["eligible"] is False
    assert loss["reason"] == "waiting_for_fresh_storage_channel"
    unknown = storage_risk_evidence(observer, root_id="unknown")
    assert unknown["eligible"] is False
    assert unknown["reason"] == "root_not_observed"


def test_storage_advisor_uses_original_strength_and_shared_twenty_five_percent_cap():
    observer = _confirmed_data_observer()
    candidates = [{"action": "draw", "strength": 0.6}]
    checkpoint = observer.to_checkpoint()

    already = apply_storage_risk_advice(
        candidates, observer, lambda action: action, input_strengths=[0.8]
    )

    assert already["active"] is False
    assert already["reason"] == "shared_budget_already_applied"
    assert already["adjustments"] == []
    assert candidates[0]["strength"] == 0.6
    assert observer.to_checkpoint() == checkpoint

    candidates[0]["strength"] = 0.7
    report = apply_storage_risk_advice(
        candidates, observer, lambda action: action, input_strengths=[0.8]
    )
    assert report["active"] is True
    assert candidates[0]["strength"] == pytest.approx(0.608)
    assert candidates[0]["strength"] >= 0.8 * 0.75


def test_storage_advisor_rejects_mismatched_originals_before_mutation():
    observer = _confirmed_data_observer()
    candidates = [{"action": "draw", "strength": 0.8}]
    before = deepcopy(candidates)

    with pytest.raises(ValueError, match="input strength count mismatch"):
        apply_storage_risk_advice(
            candidates, observer, lambda action: action, input_strengths=[]
        )
    assert candidates == before


def test_root_advisor_acceptance_for_six_hundred_cycles_and_two_restarts(
    monkeypatch, tmp_path
):
    observer, roots = _observer(monkeypatch, tmp_path, "archive", "drafts")
    readings = _patch_reads(monkeypatch, roots, {"archive": 0.8, "drafts": 0.8})
    archive_path = str(roots["archive"].absolute())
    data_applied = 0
    archive_eligible = 0

    for cycle in range(600):
        if cycle in {200, 400}:
            observer = HardwareInteroception.from_checkpoint(observer.to_checkpoint())
            assert storage_risk_evidence(observer)["reason"] == (
                "waiting_for_fresh_storage_channel"
            )
            assert storage_risk_evidence(observer, root_id="archive")["reason"] == (
                "waiting_for_fresh_storage_channel"
            )
        data_high = (cycle // 20) % 2 == 0
        readings[archive_path] = _storage(0.8 if data_high else 0.01)
        _observe(observer, cycle, data_free=0.01 if data_high else 0.8)

        data_evidence = storage_risk_evidence(observer)
        archive_evidence = storage_risk_evidence(observer, root_id="archive")
        assert storage_risk_evidence(observer, root_id="drafts")["eligible"] is False
        archive_eligible += int(archive_evidence["eligible"])
        candidates = [{"action": "draw", "strength": 0.8}]
        report = apply_storage_risk_advice(
            candidates, observer, lambda action: action, input_strengths=[0.8]
        )
        if data_evidence["eligible"]:
            data_applied += int(report["active"])
            assert candidates[0]["strength"] >= 0.6
        else:
            assert report["active"] is False
            assert candidates[0]["strength"] == 0.8
        if not data_high and archive_evidence["eligible"]:
            assert report["adjustments"] == []
        if cycle % 50 == 0:
            validate_hardware_interoception(observer.to_checkpoint())

    assert data_applied > 0
    assert archive_eligible > 0
    assert len(observer.history) == 200
    assert len(observer.relevant_root_experiences["archive"].profile["episodes"]) <= 25
    assert "hardware_storage_behavior" not in observer.to_checkpoint()
