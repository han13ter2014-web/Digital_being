"""Аппаратная интероцепция: свежесть, доказательства и строгий shadow-режим."""

from copy import deepcopy
from types import SimpleNamespace
import random

import numpy as np
import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.hardware_behavior import (
    apply_own_load_advice,
    apply_own_recovery_advice,
    own_load_advice,
    own_recovery_behavior_report,
    own_recovery_evidence,
)
from src.core.hardware_interoception import (
    HardwareInteroception,
    observe_hardware_interoception,
    validate_hardware_interoception,
)
from src.emotion.hormonal_system import HormonalSystem


@pytest.fixture(autouse=True)
def _disable_real_physical_sampling(monkeypatch):
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_physical_sensors", lambda: {}
    )
    # Прежние differential-тесты проверяют именно shadow-наблюдатель.
    # Поведенческий advisor включается в отдельных тестах явно.
    monkeypatch.setattr(
        "config.simulation_config.SIM_CONFIG.HARDWARE_BEHAVIOR_MODE", "shadow"
    )


def _resources(
    *,
    host_cpu=20.0,
    process_cpu=10.0,
    host_memory=30.0,
    rss_ratio=0.2,
    duration_ms=12.0,
):
    return {
        "available": True,
        "host_cpu_percent": host_cpu,
        "process_cpu_percent": process_cpu,
        "host_memory_percent": host_memory,
        "process_rss_mb": rss_ratio * 500.0,
        "process_rss_ratio": rss_ratio,
        "cycle_duration_ms": duration_ms,
        "score": max(host_cpu, process_cpu, host_memory, rss_ratio * 100.0) / 100.0,
        "source": "test",
    }


def _storage(free_ratio=0.8):
    return {
        "available": True,
        "total_bytes": 1000,
        "free_bytes": int(1000 * free_ratio),
        "source": "test",
    }


def _observe(observer, cycle, resources=None, free_ratio=0.8):
    return observer.observe(
        _resources() if resources is None else resources,
        cycle=cycle,
        storage_status=_storage(free_ratio),
    )


def _high_resources():
    return _resources(host_cpu=95.0, process_cpu=90.0, host_memory=92.0, rss_ratio=0.95)


def _low_resources():
    return _resources(host_cpu=10.0, process_cpu=5.0, host_memory=20.0, rss_ratio=0.1)


def test_watchdog_reports_completed_cycle_duration(monkeypatch):
    from src.core.watchdog import Watchdog

    moments = iter((10.0, 10.125))
    monkeypatch.setattr("src.core.watchdog.time.monotonic", lambda: next(moments))
    process = SimpleNamespace(
        memory_info=lambda: SimpleNamespace(rss=100 * 1024 * 1024),
        cpu_percent=lambda interval=None: 10.0,
    )
    fake_psutil = SimpleNamespace(
        Process=lambda pid: process,
        cpu_percent=lambda interval=None: 20.0,
        virtual_memory=lambda: SimpleNamespace(percent=30.0),
    )
    monkeypatch.setattr("src.core.watchdog._HAS_PSUTIL", True)
    monkeypatch.setattr("src.core.watchdog.psutil", fake_psutil)
    watchdog = Watchdog(max_rss_mb=500.0)

    watchdog.on_cycle_start()
    watchdog.on_cycle_end()

    assert watchdog.get_resource_status()["cycle_duration_ms"] == pytest.approx(125.0)


def test_host_and_process_load_remain_separate():
    observer = HardwareInteroception()
    report = _observe(
        observer,
        1,
        _resources(host_cpu=95.0, process_cpu=5.0, host_memory=40.0, rss_ratio=0.1),
    )

    states = report["states"]
    assert states["environmental_pressure"]["value"] == pytest.approx(0.95)
    assert states["environmental_pressure"]["origin"] == "external"
    assert states["own_load"]["value"] < 0.1
    assert states["own_load"]["origin"] == "own"
    assert report["observation"]["channels"]["cycle_duration"]["value"] == 12.0


def test_unavailable_channels_are_not_zero_or_recovery():
    observer = HardwareInteroception()
    report = _observe(
        observer,
        1,
        {"available": False, "reason": "sensor_disabled"},
    )

    for name in ("host_cpu", "process_cpu", "host_memory", "cycle_duration"):
        channel = report["observation"]["channels"][name]
        assert channel["status"] == "unavailable"
        assert channel["value"] is None
    for name in ("own_load", "environmental_pressure", "memory_pressure", "reserve"):
        assert report["states"][name]["value"] is None
        assert report["states"][name]["confidence"] == 0.0
    assert report["states"]["recovery"]["value"] is None
    assert observer.strain_active is False


def test_sustained_strain_and_recovery_are_single_events():
    observer = HardwareInteroception()
    for cycle in range(4):
        report = _observe(observer, cycle, _high_resources())
        assert report["endocrine_events"] == []

    report = _observe(observer, 4, _high_resources())
    assert [event["type"] for event in report["endocrine_events"]] == [
        "hardware_strain"
    ]
    assert report["endocrine_events"][0]["duration_cycles"] == 5
    history_size = len(observer.history)

    duplicate = _observe(observer, 4, _high_resources())
    assert duplicate["skipped"] == "duplicate_cycle"
    assert len(observer.history) == history_size

    for cycle in range(5, 9):
        report = _observe(observer, cycle, _low_resources())
        assert report["endocrine_events"] == []
    report = _observe(observer, 9, _low_resources())
    assert [event["type"] for event in report["endocrine_events"]] == [
        "hardware_recovery"
    ]
    assert report["states"]["recovery"]["value"] == 1.0
    assert observer.strain_active is False


def test_sensor_loss_does_not_confirm_recovery():
    observer = HardwareInteroception()
    for cycle in range(5):
        _observe(observer, cycle, _high_resources())
    assert observer.strain_active is True

    for cycle in range(5, 10):
        report = _observe(observer, cycle, {"available": False})
        assert report["endocrine_events"] == []
        assert report["states"]["recovery"]["value"] is None
    assert observer.strain_active is True

    for cycle in range(10, 14):
        assert _observe(observer, cycle, _low_resources())["endocrine_events"] == []
    report = _observe(observer, 14, _low_resources())
    assert report["endocrine_events"][0]["type"] == "hardware_recovery"


def test_hardware_projection_preserves_reward_and_social_hormones():
    observer = HardwareInteroception()
    hormones = HormonalSystem()
    agent = SimpleNamespace(hardware_interoception=observer, hormonal_system=hormones)
    baseline = dict(hormones.hormones)

    for cycle in range(5):
        report = observe_hardware_interoception(agent, _high_resources(), cycle)

    assert report["projection"]["processed_events"] == 1
    assert hormones.hormones["cortisol"] > baseline["cortisol"]
    assert hormones.hormones["dopamine"] == baseline["dopamine"]
    assert hormones.hormones["oxytocin"] == baseline["oxytocin"]
    assert hormones.hormones["prolactin"] == baseline["prolactin"]
    assert hormones.history[-1]["event"] == "hardware_strain"
    event = report["endocrine_events"][0]
    assert hormones.history[-1]["provenance"] == {
        "source": "hardware",
        "cycle": 4,
        "reason": event["reason"],
        "origin": event["origin"],
        "duration_cycles": 5,
        "evidence": event["evidence"],
    }


def test_low_resource_idle_creates_no_endocrine_reward():
    observer = HardwareInteroception()
    hormones = HormonalSystem()
    agent = SimpleNamespace(hardware_interoception=observer, hormonal_system=hormones)
    baseline = dict(hormones.hormones)

    for cycle in range(20):
        report = observe_hardware_interoception(agent, _low_resources(), cycle)

    assert report["projection"]["processed_events"] == 0
    assert observer.events == []
    assert hormones.hormones == baseline


def test_own_load_advisor_requires_five_complete_fresh_cycles():
    observer = HardwareInteroception()
    for cycle in range(4):
        _observe(observer, cycle, _high_resources())
        advice = own_load_advice(observer)
        assert advice["active"] is False
        assert advice["reason"] == "insufficient_sustained_own_load"

    _observe(observer, 4, _high_resources())
    advice = own_load_advice(observer)
    assert advice["active"] is True
    assert advice["reason"] == "sustained_own_load"
    assert advice["duration_cycles"] == 5
    assert advice["risk"] == pytest.approx(0.915)
    assert advice["factor"] == pytest.approx(1.0 - 0.25 * 0.915)

    # Тот же цикл не создаёт новый опыт и не усиливает поправку повторно.
    _observe(observer, 4, _high_resources())
    assert own_load_advice(observer) == advice


def test_own_load_advisor_changes_only_existing_heavy_candidates():
    observer = HardwareInteroception()
    for cycle in range(5):
        _observe(observer, cycle, _high_resources())
    candidates = [
        {"action": "explore", "source": "motivation", "strength": 0.8},
        {"action": "synthesis", "source": "active_goal", "strength": 0.6},
        {"action": "communicate", "source": "social", "strength": 0.8},
        {
            "action": "process_stimulus",
            "source": "external_attention",
            "strength": 0.85,
            "params": {"user_initiated": True},
        },
        {"action": "repair", "source": "maintenance", "strength": 0.9},
        {"action": "wait", "source": "deliberate_pause", "strength": 0.3},
        {"action": "hypothesis", "source": "invalid_negative", "strength": -0.2},
        {"action": "reflection", "source": "zero", "strength": 0.0},
    ]
    original_actions = [candidate["action"] for candidate in candidates]

    report = apply_own_load_advice(candidates, observer, lambda action: action)

    assert report["active"] is True
    assert [candidate["action"] for candidate in candidates] == original_actions
    assert [item["action"] for item in report["adjustments"]] == [
        "explore",
        "synthesis",
    ]
    assert candidates[0]["strength"] == pytest.approx(0.8 * report["factor"])
    assert candidates[1]["strength"] == pytest.approx(0.6 * report["factor"])
    assert candidates[2]["strength"] == 0.8
    assert candidates[3]["strength"] == 0.85
    assert candidates[4]["strength"] == 0.9
    assert candidates[5]["strength"] == 0.3
    assert candidates[6]["strength"] == -0.2
    assert candidates[7]["strength"] == 0.0
    assert report["factor"] >= 0.75


def test_own_load_advisor_ignores_external_storage_and_physical_pressure():
    observer = HardwareInteroception()
    external = _resources(
        host_cpu=98.0, process_cpu=5.0, host_memory=96.0, rss_ratio=0.1
    )
    for cycle in range(5):
        _observe(observer, cycle, external, free_ratio=0.01)
    assert observer.strain_active is True
    assert own_load_advice(observer)["active"] is False

    physical_observer = HardwareInteroception()
    for cycle in range(5):
        physical_observer.observe(
            _low_resources(),
            cycle=cycle,
            storage_status=_storage(),
            physical_status=_physical(
                gpu_utilization=100.0,
                gpu_memory=1.0,
                gpu_temperature=100.0,
                gpu_power=1.0,
            ),
        )
    assert physical_observer.states["physical_strain"]["value"] == 1.0
    assert own_load_advice(physical_observer)["active"] is False


def test_own_load_advisor_sensor_loss_and_restart_require_fresh_evidence():
    observer = HardwareInteroception()
    for cycle in range(5):
        _observe(observer, cycle, _high_resources())
    assert own_load_advice(observer)["active"] is True

    restored = HardwareInteroception.from_checkpoint(observer.to_checkpoint())
    restored_advice = own_load_advice(restored)
    assert restored_advice["active"] is False
    assert restored_advice["reason"] == "waiting_for_fresh_process_channels"

    # Прошлый опыт сохраняется, но обязательна новая полная выборка после restore.
    _observe(restored, 5, _high_resources())
    assert own_load_advice(restored)["active"] is True
    incomplete = _high_resources()
    incomplete.pop("process_rss_ratio")
    _observe(restored, 6, incomplete)
    assert own_load_advice(restored)["active"] is False
    _observe(restored, 7, _low_resources())
    assert own_load_advice(restored)["active"] is False


def test_own_load_advisor_application_is_atomic_on_normalization_error():
    observer = HardwareInteroception()
    for cycle in range(5):
        _observe(observer, cycle, _high_resources())
    candidates = [
        {"action": "explore", "strength": 0.8},
        {"action": "synthesis", "strength": 0.6},
    ]

    def fail_on_second(action):
        if action == "synthesis":
            raise ValueError("normalization failed")
        return action

    with pytest.raises(ValueError, match="normalization failed"):
        apply_own_load_advice(candidates, observer, fail_on_second)
    assert [candidate["strength"] for candidate in candidates] == [0.8, 0.6]


def test_own_recovery_evidence_requires_exact_five_plus_five_transition_once():
    observer = HardwareInteroception()
    for cycle in range(5):
        _observe(observer, cycle, _high_resources())
    for cycle in range(5, 9):
        _observe(observer, cycle, _low_resources())
        evidence = own_recovery_evidence(observer)
        assert evidence["eligible"] is False
        assert evidence["reason"] == "insufficient_recovery_history"

    _observe(observer, 9, _low_resources())
    evidence = own_recovery_evidence(observer)
    assert evidence["eligible"] is True
    assert evidence["reason"] == "confirmed_own_recovery_transition"
    assert evidence["strain_cycles"] == 5
    assert evidence["recovery_cycles"] == 5
    assert evidence["max_recovery_risk"] == pytest.approx(0.065)
    assert evidence["factor"] == pytest.approx(1.0 + 0.10 * 0.935)
    report = own_recovery_behavior_report(observer, "shadow")
    assert report["active"] is False
    assert report["eligible"] is True
    assert report["reason"] == "shadow_only"
    assert report["adjustments"] == []

    history_size = len(observer.history)
    _observe(observer, 9, _low_resources())
    assert len(observer.history) == history_size
    assert own_recovery_evidence(observer) == evidence

    _observe(observer, 10, _low_resources())
    consumed = own_recovery_evidence(observer)
    assert consumed["eligible"] is False
    assert consumed["reason"] == "no_new_own_recovery_transition"
    assert consumed["factor"] == 1.0


def test_own_recovery_evidence_rejects_sensor_loss_incomplete_channels_and_gaps():
    observer = HardwareInteroception()
    for cycle in range(5):
        resources = _high_resources()
        if cycle == 2:
            resources.pop("process_rss_ratio")
        _observe(observer, cycle, resources)
    for cycle in range(5, 10):
        _observe(observer, cycle, _low_resources())
    evidence = own_recovery_evidence(observer)
    assert evidence["eligible"] is False
    assert evidence["reason"] == "invalid_own_recovery_evidence"

    _observe(observer, 10, {"available": False, "reason": "sensor_disabled"})
    unavailable = own_recovery_evidence(observer)
    assert unavailable["eligible"] is False
    assert unavailable["reason"] == "waiting_for_fresh_process_channels"

    gapped = HardwareInteroception()
    for cycle in range(5):
        _observe(gapped, cycle, _high_resources())
    for cycle in range(6, 11):
        _observe(gapped, cycle, _low_resources())
    gap = own_recovery_evidence(gapped)
    assert gap["eligible"] is False
    assert gap["reason"] == "insufficient_recovery_history"


def test_own_recovery_evidence_ignores_generic_and_external_recovery():
    observer = HardwareInteroception()
    external = _resources(
        host_cpu=98.0, process_cpu=5.0, host_memory=96.0, rss_ratio=0.1
    )
    for cycle in range(5):
        _observe(observer, cycle, external, free_ratio=0.01)
    for cycle in range(5, 10):
        _observe(observer, cycle, _low_resources())

    assert any(event["type"] == "hardware_recovery" for event in observer.events)
    evidence = own_recovery_evidence(observer)
    assert evidence["eligible"] is False
    assert evidence["reason"] == "no_new_own_recovery_transition"

    physical = HardwareInteroception()
    for cycle in range(5):
        physical.observe(
            _low_resources(),
            cycle=cycle,
            storage_status=_storage(free_ratio=0.01),
            physical_status={
                "gpu_temperature": {"available": True, "value": 100.0},
                "gpu_power": {"available": True, "value": 1.0},
            },
        )
    for cycle in range(5, 10):
        _observe(physical, cycle, _low_resources())
    assert own_recovery_evidence(physical)["eligible"] is False


def test_own_recovery_evidence_restart_requires_fresh_completion():
    observer = HardwareInteroception()
    for cycle in range(5):
        _observe(observer, cycle, _high_resources())
    for cycle in range(5, 9):
        _observe(observer, cycle, _low_resources())

    restored = HardwareInteroception.from_checkpoint(observer.to_checkpoint())
    stale = own_recovery_evidence(restored)
    assert stale["eligible"] is False
    assert stale["reason"] == "waiting_for_fresh_process_channels"

    _observe(restored, 9, _low_resources())
    evidence = own_recovery_evidence(restored)
    assert evidence["eligible"] is True
    assert evidence["recovery_cycles"] == 5


def test_recovery_shadow_and_unknown_mode_match_full_behavioral_baseline(monkeypatch):
    source = DigitalBeing(name="HardwareRecoveryCounterfactualSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    shadow = DigitalBeing(name="HardwareRecoveryCounterfactualShadow")
    unknown = DigitalBeing(name="HardwareRecoveryCounterfactualUnknown")
    for agent in (shadow, unknown):
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)

    sequence = [
        *(_high_resources() for _ in range(5)),
        *(_low_resources() for _ in range(5)),
    ]
    current = {"resources": sequence[0]}
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: current["resources"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", lambda: _storage()
    )

    def run(agent, mode):
        monkeypatch.setattr(
            "config.simulation_config.SIM_CONFIG.HARDWARE_RECOVERY_BEHAVIOR_MODE",
            mode,
            raising=False,
        )
        random.seed(2026)
        np.random.seed(2026)
        trace = []
        reports = []
        for resources in sequence:
            current["resources"] = resources
            report = agent.autonomous_tick()
            reports.append(report)
            trace.append(_canonical_trace(agent, report))
            agent.cycle_count += 1
        return trace, reports

    shadow_trace, shadow_reports = run(shadow, "shadow")
    unknown_trace, unknown_reports = run(unknown, "unsupported")
    assert unknown_trace == shadow_trace
    assert all(
        report["hardware_recovery_behavior"]["active"] is False
        and not report["hardware_recovery_behavior"]["adjustments"]
        for report in [*shadow_reports, *unknown_reports]
    )
    activation = shadow_reports[-1]["hardware_recovery_behavior"]
    assert activation["mode"] == "shadow"
    assert activation["eligible"] is True
    assert activation["reason"] == "shadow_only"
    assert unknown_reports[-1]["hardware_recovery_behavior"]["reason"] == (
        "unsupported_mode"
    )


def _ready_recovery_observer():
    observer = HardwareInteroception()
    for cycle in range(5):
        _observe(observer, cycle, _high_resources())
    for cycle in range(5, 10):
        _observe(observer, cycle, _low_resources())
    assert own_recovery_evidence(observer)["eligible"] is True
    return observer


def test_own_recovery_advisor_changes_only_existing_embodied_deep_rest_once():
    observer = _ready_recovery_observer()
    candidates = [
        {
            "action": "deep_rest",
            "source": "embodiment",
            "strength": 1.0,
            "params": {"reason": "tired"},
        },
        {
            "action": "deep_rest",
            "source": "embodiment",
            "strength": 0.5,
            "params": {"reason": "low_energy"},
        },
        {
            "action": "deep_rest",
            "source": "motivation",
            "strength": 0.5,
            "params": {"reason": "tired"},
        },
        {
            "action": "deep_rest",
            "source": "embodiment",
            "strength": 0.5,
            "params": {"reason": "nothing_affordable"},
        },
        {
            "action": "rest",
            "source": "embodiment",
            "strength": 0.5,
            "params": {"reason": "tired"},
        },
        {"action": "wait", "source": "deliberate_pause", "strength": 0.3},
        {
            "action": "process_stimulus",
            "source": "external_attention",
            "strength": 0.85,
            "params": {"user_initiated": True},
        },
    ]
    original_actions = [candidate["action"] for candidate in candidates]

    report = apply_own_recovery_advice(candidates, observer, lambda action: action)

    assert report["active"] is True
    assert report["reason"] == "applied"
    assert [candidate["action"] for candidate in candidates] == original_actions
    assert len(report["adjustments"]) == 2
    assert candidates[0]["strength"] == pytest.approx(report["factor"])
    assert candidates[0]["strength"] == pytest.approx(1.0935)
    assert candidates[1]["strength"] == pytest.approx(0.5 * report["factor"])
    assert candidates[2]["strength"] == 0.5
    assert candidates[3]["strength"] == 0.5
    assert candidates[4]["strength"] == 0.5
    assert candidates[5]["strength"] == 0.3
    assert candidates[6]["strength"] == 0.85
    assert all(item["after_strength"] <= 1.1 for item in report["adjustments"])

    strengths = [candidate["strength"] for candidate in candidates]
    duplicate = apply_own_recovery_advice(candidates, observer, lambda action: action)
    assert duplicate["active"] is False
    assert duplicate["reason"] == "duplicate_cycle"
    assert duplicate["adjustments"] == []
    assert [candidate["strength"] for candidate in candidates] == strengths


def test_own_recovery_advisor_does_not_create_rest_or_reward():
    observer = _ready_recovery_observer()
    candidates = [
        {"action": "explore", "source": "motivation", "strength": 0.8},
        {"action": "wait", "source": "deliberate_pause", "strength": 0.3},
    ]
    original = deepcopy(candidates)
    events = deepcopy(observer.events)
    checkpoint = observer.to_checkpoint()

    report = apply_own_recovery_advice(candidates, observer, lambda action: action)

    assert report["active"] is False
    assert report["reason"] == "no_matching_candidates"
    assert report["adjustments"] == []
    assert candidates == original
    assert observer.events == events
    assert observer.to_checkpoint() == checkpoint


def test_own_recovery_advisor_application_is_atomic_and_checkpoint_neutral():
    observer = _ready_recovery_observer()
    checkpoint = observer.to_checkpoint()
    candidates = [
        {
            "action": "deep_rest",
            "source": "embodiment",
            "strength": 1.0,
            "params": {"reason": "tired"},
        },
        {
            "action": "deep_rest",
            "source": "embodiment",
            "strength": 0.5,
            "params": {"reason": "low_energy"},
        },
    ]
    calls = 0

    def fail_on_second(action):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("normalization failed")
        return action

    with pytest.raises(ValueError, match="normalization failed"):
        apply_own_recovery_advice(candidates, observer, fail_on_second)
    assert [candidate["strength"] for candidate in candidates] == [1.0, 0.5]
    assert observer.to_checkpoint() == checkpoint

    report = apply_own_recovery_advice(candidates, observer, lambda action: action)
    assert report["active"] is True
    assert observer.to_checkpoint() == checkpoint
    validate_hardware_interoception(observer.to_checkpoint())


def test_recovery_advisor_activates_in_autonomous_tick_without_candidate_drift(
    monkeypatch,
):
    source = DigitalBeing(name="HardwareRecoveryAdvisorSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    shadow = DigitalBeing(name="HardwareRecoveryAdvisorShadow")
    advisor = DigitalBeing(name="HardwareRecoveryAdvisorOn")
    for agent in (shadow, advisor):
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)

    sequence = [
        *(_high_resources() for _ in range(5)),
        *(_low_resources() for _ in range(5)),
    ]
    current = {"resources": sequence[0]}
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: current["resources"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", lambda: _storage()
    )

    def run(agent, mode):
        monkeypatch.setattr(
            "config.simulation_config.SIM_CONFIG.HARDWARE_RECOVERY_BEHAVIOR_MODE",
            mode,
        )
        random.seed(2027)
        np.random.seed(2027)
        trace = []
        reports = []
        for resources in sequence:
            current["resources"] = resources
            # В живом контуре тело предлагает deep_rest силой 1.0. Этот тест
            # доказывает реальную поправку 1.0 -> 1.0 * factor, а не no-op.
            agent.interoception.state.fatigue = 0.6
            report = agent.autonomous_tick()
            reports.append(report)
            trace.append(_canonical_trace(agent, report))
            agent.cycle_count += 1
        return trace, reports

    shadow_trace, shadow_reports = run(shadow, "shadow")
    advisor_trace, advisor_reports = run(advisor, "advisor")
    assert advisor_trace[:9] == shadow_trace[:9]
    assert [report["hardware_interoception"] for report in advisor_reports] == [
        report["hardware_interoception"] for report in shadow_reports
    ]

    activation = advisor_reports[-1]["hardware_recovery_behavior"]
    assert activation["active"] is True
    assert activation["reason"] == "applied"
    assert activation["adjustments"]
    shadow_evaluations = {
        (item["input_index"], item["action"], item["source"]): item
        for item in shadow_reports[-1]["arbitrator"]["all_evaluations"]
    }
    advisor_evaluations = {
        (item["input_index"], item["action"], item["source"]): item
        for item in advisor_reports[-1]["arbitrator"]["all_evaluations"]
    }
    assert advisor_evaluations.keys() == shadow_evaluations.keys()
    for key, advisor_evaluation in advisor_evaluations.items():
        shadow_evaluation = shadow_evaluations[key]
        if key[1:] == ("deep_rest", "embodiment"):
            assert shadow_evaluation["strength"] == 1.0
            assert advisor_evaluation["strength"] == pytest.approx(
                shadow_evaluation["strength"] * activation["factor"]
            )
            assert advisor_evaluation["strength"] <= 1.1
        else:
            assert advisor_evaluation["strength"] == shadow_evaluation["strength"]


def test_checkpoint_legacy_restart_and_corruption_contract():
    agent = DigitalBeing(name="HardwareCheckpoint")
    for cycle in range(5):
        observe_hardware_interoception(agent, _high_resources(), cycle)
    state = build_state_from_agent(agent)
    validate_hardware_interoception(state["hardware_interoception"])

    reborn = DigitalBeing(name="HardwareCheckpointRestored")
    apply_state_to_agent(reborn, state)
    restored = reborn.hardware_interoception
    assert restored.strain_active is True
    assert restored.history == state["hardware_interoception"]["history"]
    restored_channels = restored.latest_observation["channels"]
    assert all(
        restored_channels[name]["status"] == "stale"
        for name, channel in state["hardware_interoception"]["latest_observation"][
            "channels"
        ].items()
        if channel["status"] == "available"
    )
    assert restored_channels["gpu_temperature"]["status"] == "unavailable"
    assert all(state["confidence"] == 0.0 for state in restored.states.values())
    assert (
        reborn.hormonal_system.to_checkpoint()
        == state["integrated_experience"]["hormones"]
    )
    validate_hardware_interoception(restored.to_checkpoint())

    legacy = deepcopy(state)
    legacy.pop("hardware_interoception")
    legacy_target = DigitalBeing(name="HardwareLegacy")
    apply_state_to_agent(legacy_target, legacy)
    assert legacy_target.hardware_interoception.latest_observation == {}
    assert legacy_target.hardware_interoception.history == []

    corrupted = deepcopy(state)
    corrupted["hardware_interoception"]["states"]["own_load"]["confidence"] = 2.0
    before = build_state_from_agent(legacy_target)
    before.pop("saved_at")
    observer_identity = legacy_target.hardware_interoception
    with pytest.raises(
        ValueError, match="hardware_interoception.states.own_load.confidence"
    ):
        apply_state_to_agent(legacy_target, corrupted)
    after = build_state_from_agent(legacy_target)
    after.pop("saved_at")
    assert after == before
    assert legacy_target.hardware_interoception is observer_identity


def test_history_is_bounded_and_validates_after_long_observation():
    observer = HardwareInteroception()
    for cycle in range(205):
        _observe(observer, cycle, _low_resources())

    assert len(observer.history) == 200
    assert observer.history[0]["cycle"] == 5
    validate_hardware_interoception(observer.to_checkpoint())


def _semantic_goal_state(value):
    """Исключить wall-clock метки, сохранив содержание и порядок целей."""
    if isinstance(value, dict):
        return {
            key: _semantic_goal_state(item)
            for key, item in value.items()
            if key != "timestamp" and not key.endswith("_at")
        }
    if isinstance(value, list):
        return [_semantic_goal_state(item) for item in value]
    return value


def _canonical_evaluations(evaluations):
    normalized = deepcopy(evaluations)
    for evaluation in normalized or []:
        # UUID намерения создаётся заново; сравниваем само продолжение, не UUID.
        if evaluation.get("continuation_of") is not None:
            evaluation["continuation_of"] = "present"
    return normalized


def _canonical_trace(agent, report):
    arbitrator = report.get("arbitrator") or {}
    needs = {
        name: need.to_dict() for name, need in agent.motivation_system.needs.items()
    }
    rewards = [entry["reward"] for entry in agent.active_inference.experience_buffer]
    body = agent.interoception.state
    return {
        "action": arbitrator.get("action"),
        "evaluations": _canonical_evaluations(arbitrator.get("all_evaluations")),
        "diagnostics": deepcopy(arbitrator.get("choice_diagnostics")),
        "goals": _semantic_goal_state(agent.goals),
        "active_goal": _semantic_goal_state(agent.active_goal),
        "needs": needs,
        "emotions": deepcopy(agent.emotional_state.levels),
        "energy": agent.energy,
        "body": (body.glucose, body.atp, body.fatigue, body.mitochondrial_health),
        "resource_scale": agent.meta_learner.hyperparams["cycle_interval_scale"].value,
        "predicted_valence": report.get("predicted_valence"),
        "actual_valence": report.get("actual_valence"),
        "rewards": rewards,
    }


def test_advisor_non_own_inputs_match_shadow_full_trace(monkeypatch):
    source = DigitalBeing(name="HardwareAdvisorCounterfactualSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    shadow = DigitalBeing(name="HardwareAdvisorCounterfactualShadow")
    advisor = DigitalBeing(name="HardwareAdvisorCounterfactualOn")
    for agent in (shadow, advisor):
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)

    external = _resources(
        host_cpu=98.0, process_cpu=5.0, host_memory=96.0, rss_ratio=0.1
    )
    unavailable = {"available": False, "reason": "sensor_disabled"}
    sequence = [
        _high_resources(),
        _high_resources(),  # короткий собственный всплеск ещё не совет
        *(deepcopy(external) for _ in range(5)),
        unavailable,
        *(_low_resources() for _ in range(3)),
    ]
    current = {"resources": sequence[0]}
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: current["resources"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", lambda: _storage()
    )

    def run(agent, mode):
        monkeypatch.setattr(
            "config.simulation_config.SIM_CONFIG.HARDWARE_BEHAVIOR_MODE", mode
        )
        random.seed(1919)
        np.random.seed(1919)
        trace = []
        reports = []
        for resources in sequence:
            current["resources"] = resources
            report = agent.autonomous_tick()
            reports.append(report)
            trace.append(_canonical_trace(agent, report))
            agent.cycle_count += 1
        return trace, reports

    shadow_trace, _ = run(shadow, "shadow")
    advisor_trace, advisor_reports = run(advisor, "advisor")
    assert advisor_trace == shadow_trace
    assert all(
        report["hardware_behavior"]["active"] is False
        and not report["hardware_behavior"].get("adjustments")
        for report in advisor_reports
    )


def test_advisor_activates_in_autonomous_tick_without_shadow_drift(monkeypatch):
    source = DigitalBeing(name="HardwareAdvisorActivationSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    shadow = DigitalBeing(name="HardwareAdvisorActivationShadow")
    advisor = DigitalBeing(name="HardwareAdvisorActivationOn")
    for agent in (shadow, advisor):
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)

    current = {"resources": _high_resources()}
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: current["resources"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", lambda: _storage()
    )

    def run(agent, mode):
        monkeypatch.setattr(
            "config.simulation_config.SIM_CONFIG.HARDWARE_BEHAVIOR_MODE", mode
        )
        random.seed(1920)
        np.random.seed(1920)
        trace = []
        reports = []
        for _ in range(5):
            report = agent.autonomous_tick()
            reports.append(report)
            trace.append(_canonical_trace(agent, report))
            agent.cycle_count += 1
        return trace, reports

    shadow_trace, shadow_reports = run(shadow, "shadow")
    advisor_trace, advisor_reports = run(advisor, "advisor")
    assert advisor_trace[:4] == shadow_trace[:4]
    assert [report["hardware_interoception"] for report in advisor_reports] == [
        report["hardware_interoception"] for report in shadow_reports
    ]
    assert all(
        not report["hardware_behavior"].get("adjustments")
        for report in advisor_reports[:4]
    )

    activation = advisor_reports[-1]["hardware_behavior"]
    assert activation["active"] is True
    assert activation["duration_cycles"] == 5
    assert activation["adjustments"]
    assert activation["factor"] >= 0.75
    shadow_choice = shadow_reports[-1]["arbitrator"]["all_evaluations"]
    advisor_choice = advisor_reports[-1]["arbitrator"]["all_evaluations"]
    assert [
        (item["input_index"], item["action"], item["source"]) for item in advisor_choice
    ] == [
        (item["input_index"], item["action"], item["source"]) for item in shadow_choice
    ]


def test_endocrine_shadow_matches_full_behavioral_baseline(monkeypatch):
    source = DigitalBeing(name="HardwareBaselineSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)

    baseline = DigitalBeing(name="HardwareBaselineOff")
    enabled = DigitalBeing(name="HardwareBaselineOn")
    apply_state_to_agent(baseline, deepcopy(initial))
    apply_state_to_agent(enabled, deepcopy(initial))
    baseline.web_searcher.toggle(False)
    enabled.web_searcher.toggle(False)
    baseline.hardware_interoception = None

    current = {"resources": _high_resources()}
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: current["resources"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage",
        lambda: _storage(0.8),
    )

    def run(agent):
        random.seed(1701)
        np.random.seed(1701)
        trace = []
        for cycle in range(10):
            current["resources"] = _high_resources() if cycle < 5 else _low_resources()
            report = agent.autonomous_tick()
            trace.append(_canonical_trace(agent, report))
            # Прямой вызов не Runner: продвигаем цикл так же, как основной цикл.
            agent.cycle_count += 1
        return trace

    baseline_trace = run(baseline)
    enabled_trace = run(enabled)

    assert enabled.hardware_interoception.events
    assert [event["type"] for event in enabled.hardware_interoception.events] == [
        "hardware_strain",
        "hardware_recovery",
    ]
    for cycle, (observed, expected) in enumerate(zip(enabled_trace, baseline_trace)):
        for field in expected:
            assert observed[field] == expected[field], (cycle, field)


def test_two_different_personal_profiles_match_behavioral_baseline(monkeypatch):
    source = DigitalBeing(name="HardwareProfileSource")
    source.web_searcher.toggle(False)
    source.cycle_count = 200
    initial = build_state_from_agent(source)

    baseline = DigitalBeing(name="HardwareProfileBaseline")
    neutral = DigitalBeing(name="HardwareProfileNeutral")
    experienced = DigitalBeing(name="HardwareProfileExperienced")
    for agent in (baseline, neutral, experienced):
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)
    baseline.hardware_interoception = None
    for cycle in range(200):
        _observe(experienced.hardware_interoception, cycle, _high_resources())
    assert experienced.hardware_interoception.personal.adaptation == pytest.approx(0.5)
    assert neutral.hardware_interoception.personal.adaptation == 0.0

    current = {"resources": _high_resources()}
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: current["resources"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage",
        lambda: _storage(0.8),
    )

    def run(agent):
        random.seed(1702)
        np.random.seed(1702)
        trace = []
        for offset in range(10):
            current["resources"] = _high_resources() if offset < 5 else _low_resources()
            report = agent.autonomous_tick()
            trace.append(_canonical_trace(agent, report))
            agent.cycle_count += 1
        return trace

    baseline_trace = run(baseline)
    neutral_trace = run(neutral)
    experienced_trace = run(experienced)
    for cycle, (baseline_row, neutral_row, experienced_row) in enumerate(
        zip(baseline_trace, neutral_trace, experienced_trace)
    ):
        for field in baseline_row:
            assert neutral_row[field] == baseline_row[field], (cycle, field)
            assert experienced_row[field] == baseline_row[field], (cycle, field)


def test_full_six_hundred_cycles_with_two_restarts_match_baseline(monkeypatch):
    source = DigitalBeing(name="HardwareLongSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    current = {"resources": _low_resources()}
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: current["resources"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage",
        lambda: _storage(0.8),
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_physical_sensors",
        lambda: _physical(
            gpu_utilization=95.0,
            gpu_memory=0.9,
            gpu_temperature=95.0,
            gpu_power=0.9,
            external_power=1.0,
        ),
    )

    def restart(agent, *, hardware_enabled):
        state = build_state_from_agent(agent)
        restored = DigitalBeing(name=agent.name)
        apply_state_to_agent(restored, state)
        restored.web_searcher.toggle(False)
        if not hardware_enabled:
            restored.hardware_interoception = None
        return restored

    def run(*, hardware_enabled):
        random.seed(60017)
        np.random.seed(60017)
        agent = DigitalBeing(
            name="HardwareLongOn" if hardware_enabled else "HardwareLongOff"
        )
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)
        if not hardware_enabled:
            agent.hardware_interoception = None
        trace = []
        for cycle in range(600):
            if cycle in {200, 400}:
                agent = restart(agent, hardware_enabled=hardware_enabled)
            if cycle % 200 in {150, 151, 152}:
                current["resources"] = {
                    "available": False,
                    "reason": "sensor_disabled",
                }
            else:
                current["resources"] = (
                    _high_resources() if (cycle // 20) % 2 == 0 else _low_resources()
                )
            report = agent.autonomous_tick()
            trace.append(_canonical_trace(agent, report))
            agent.cycle_count += 1
        return agent, trace

    baseline_agent, baseline_trace = run(hardware_enabled=False)
    enabled_agent, enabled_trace = run(hardware_enabled=True)

    assert enabled_agent.cycle_count == baseline_agent.cycle_count == 600
    assert enabled_agent.hardware_interoception.personal.completed_episode_count > 0
    assert len(enabled_agent.hardware_interoception.history) == 200
    assert len(enabled_agent.hardware_interoception.events) <= 50
    assert len(enabled_agent.hardware_interoception.personal.episodes) <= 50
    validate_hardware_interoception(
        enabled_agent.hardware_interoception.to_checkpoint()
    )
    for cycle, (observed, expected) in enumerate(zip(enabled_trace, baseline_trace)):
        for field in expected:
            assert observed[field] == expected[field], (cycle, field)


def test_hormonal_profiles_match_behavior_for_six_hundred_cycles_and_restarts(
    monkeypatch,
):
    source = DigitalBeing(name="HormonalLongSource")
    source.web_searcher.toggle(False)
    neutral_initial = build_state_from_agent(source)

    trained = HormonalSystem()
    for cycle in range(25):
        trained.process_event(
            "success",
            1.0,
            provenance={
                "source": "action_outcome",
                "cycle": cycle,
                "action": "explore",
                "reason": "knowledge_changed",
                "origin": "own",
            },
        )
        trained.tick(300.0)
    trained_checkpoint = trained.to_checkpoint()
    assert trained_checkpoint["profile"]["dopamine"]["baseline"] > 0.4
    assert trained_checkpoint["profile"]["dopamine"]["sensitivity"] < 1.0

    experienced_initial = deepcopy(neutral_initial)
    experienced_initial["integrated_experience"]["hormones"] = deepcopy(
        trained_checkpoint
    )
    current = {"resources": _low_resources()}
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: current["resources"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage",
        lambda: _storage(0.8),
    )

    def run(initial):
        random.seed(60018)
        np.random.seed(60018)
        agent = DigitalBeing(name="HormonalLongLife")
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)
        trace = []
        for cycle in range(600):
            if cycle in {200, 400}:
                state = build_state_from_agent(agent)
                restored = DigitalBeing(name=agent.name)
                apply_state_to_agent(restored, state)
                restored.web_searcher.toggle(False)
                agent = restored
            if cycle % 200 in {150, 151, 152}:
                current["resources"] = {
                    "available": False,
                    "reason": "sensor_disabled",
                }
            else:
                current["resources"] = (
                    _high_resources() if (cycle // 20) % 2 == 0 else _low_resources()
                )
            report = agent.autonomous_tick()
            trace.append(_canonical_trace(agent, report))
            agent.cycle_count += 1
        return agent, trace

    neutral_agent, neutral_trace = run(neutral_initial)
    experienced_agent, experienced_trace = run(experienced_initial)

    assert neutral_agent.cycle_count == experienced_agent.cycle_count == 600
    neutral_checkpoint = neutral_agent.hormonal_system.to_checkpoint()
    experienced_checkpoint = experienced_agent.hormonal_system.to_checkpoint()
    assert experienced_checkpoint != neutral_checkpoint
    assert (
        experienced_checkpoint["profile"]["dopamine"]["sample_count"]
        > neutral_checkpoint["profile"]["dopamine"]["sample_count"]
    )
    for checkpoint in (neutral_checkpoint, experienced_checkpoint):
        HormonalSystem.validate_checkpoint(checkpoint)
        assert len(checkpoint["history"]) <= 200
        assert len(checkpoint["episodes"]) <= 50
        for name, level in checkpoint["hormones"].items():
            assert 0.0 <= level <= 1.0
            profile = checkpoint["profile"][name]
            spec = HormonalSystem.HORMONES[name]
            assert (
                spec.base_level - 0.05 <= profile["baseline"] <= spec.base_level + 0.05
            )
            assert 0.75 <= profile["sensitivity"] <= 1.25
            assert 0.75 <= profile["half_life_scale"] <= 1.5
            assert 0.0 <= profile["confidence"] <= 1.0

    for cycle, (observed, expected) in enumerate(zip(experienced_trace, neutral_trace)):
        for field in expected:
            assert observed[field] == expected[field], (cycle, field)


def test_advisor_long_life_does_not_collapse_into_idle(monkeypatch):
    from src.core.agent_body import HEAVY_ACTIONS

    source = DigitalBeing(name="HardwareAdvisorLongSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    current = {"resources": _low_resources()}
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: current["resources"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", lambda: _storage()
    )

    def run(mode):
        monkeypatch.setattr(
            "config.simulation_config.SIM_CONFIG.HARDWARE_BEHAVIOR_MODE", mode
        )
        random.seed(60017)
        np.random.seed(60017)
        agent = DigitalBeing(name=f"HardwareAdvisorLong_{mode}")
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)
        actions = []
        adjustment_count = 0
        for cycle in range(600):
            if cycle in {200, 400}:
                state = build_state_from_agent(agent)
                restored = DigitalBeing(name=agent.name)
                apply_state_to_agent(restored, state)
                restored.web_searcher.toggle(False)
                agent = restored
            if cycle % 200 in {150, 151, 152}:
                current["resources"] = {
                    "available": False,
                    "reason": "sensor_disabled",
                }
            else:
                current["resources"] = (
                    _high_resources() if (cycle // 20) % 2 == 0 else _low_resources()
                )
            report = agent.autonomous_tick()
            actions.append(report["arbitrator"].get("action"))
            adjustment_count += len(report["hardware_behavior"].get("adjustments", []))
            if current["resources"]["available"] is False:
                assert report["hardware_behavior"]["active"] is False
            agent.cycle_count += 1
        return agent, actions, adjustment_count

    shadow_agent, shadow_actions, shadow_adjustments = run("shadow")
    advisor_agent, advisor_actions, advisor_adjustments = run("advisor")
    shadow_idle = sum(action in {"wait", "deep_rest"} for action in shadow_actions)
    advisor_idle = sum(action in {"wait", "deep_rest"} for action in advisor_actions)
    advisor_heavy = sum(
        advisor_agent._normalize_action(action) in HEAVY_ACTIONS
        for action in advisor_actions
    )
    assert shadow_agent.cycle_count == advisor_agent.cycle_count == 600
    assert shadow_adjustments == 0
    assert advisor_adjustments > 0
    assert advisor_heavy > 0
    # Высокая доля пауз свойственна этому сценарию и без advisor; новый контур
    # не должен увеличивать её относительно того же seeded shadow-бейслайна.
    assert advisor_idle <= shadow_idle
    assert advisor_agent.motivation_system.goal_summary["generated"] > 0
    assert all(
        0.0 <= need.current_level <= 1.0
        for need in advisor_agent.motivation_system.needs.values()
    )
    assert len(advisor_agent.hardware_interoception.history) == 200
    assert len(advisor_agent.hardware_interoception.events) <= 50
    assert len(advisor_agent.hardware_interoception.personal.episodes) <= 50
    validate_hardware_interoception(
        advisor_agent.hardware_interoception.to_checkpoint()
    )


def test_hormonal_behavior_mode_defaults_to_shadow():
    from config.simulation_config import SIM_CONFIG

    assert SIM_CONFIG.HORMONAL_BEHAVIOR_MODE == "shadow"


def test_hormonal_advisor_is_connected_in_autonomous_tick(monkeypatch):
    monkeypatch.setattr(
        "config.simulation_config.SIM_CONFIG.HORMONAL_BEHAVIOR_MODE", "advisor"
    )
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: _low_resources(),
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", lambda: _storage(0.8)
    )
    agent = DigitalBeing(name="HormonalAdvisorConnected")
    agent.web_searcher.toggle(False)
    for name in ("dopamine", "oxytocin", "cortisol"):
        agent.hormonal_system.hormones[name] = 1.0
        agent.hormonal_system.profile.values[name]["sample_count"] = 20

    behavior = {}
    for _ in range(80):
        report = agent.autonomous_tick()
        behavior = report["hormonal_behavior"]
        if behavior["adjustments"]:
            break
        agent.cycle_count += 1

    assert behavior["mode"] == "advisor"
    assert behavior["active"] is True, behavior
    assert behavior["reason"] == "applied"
    assert behavior["signals"]["dopamine"] > 0.0
    assert behavior["adjustments"]
    assert all(
        -0.1 <= entry["contribution"] <= 0.1
        and entry["before_strength"] != entry["after_strength"]
        for entry in behavior["adjustments"]
    )


def test_hormonal_shadow_extreme_rich_profile_matches_full_trace(monkeypatch):
    source = DigitalBeing(name="HormonalShadowCounterfactual")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    baseline = DigitalBeing(name="HormonalShadowCounterfactual")
    extreme = DigitalBeing(name="HormonalShadowCounterfactual")
    for agent in (baseline, extreme):
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)

    extreme.hormonal_system.hormones.update(
        {
            "dopamine": 1.0,
            "serotonin": 0.0,
            "oxytocin": 1.0,
            "cortisol": 1.0,
            "prolactin": 1.0,
        }
    )
    for name, values in extreme.hormonal_system.profile.values.items():
        if name == "prolactin":
            continue
        source_name = {
            "oxytocin": "social_message",
            "cortisol": "hardware",
        }.get(name, "action_outcome")
        values["sample_count"] = 200
        values["confidence"] = 1.0
        values["source_sample_counts"] = {source_name: 200}

    monkeypatch.setattr(
        "config.simulation_config.SIM_CONFIG.HORMONAL_BEHAVIOR_MODE", "shadow"
    )
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: _low_resources(),
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", lambda: _storage(0.8)
    )

    def run(agent):
        random.seed(4040)
        np.random.seed(4040)
        trace = []
        reports = []
        for cycle in range(12):
            if cycle == 6:
                state = build_state_from_agent(agent)
                restored = DigitalBeing(name=agent.name)
                apply_state_to_agent(restored, state)
                restored.web_searcher.toggle(False)
                agent = restored
            report = agent.autonomous_tick()
            reports.append(report)
            trace.append(_canonical_trace(agent, report))
            agent.cycle_count += 1
        return agent, trace, reports

    baseline_agent, baseline_trace, baseline_reports = run(baseline)
    extreme_agent, extreme_trace, extreme_reports = run(extreme)

    assert extreme_trace == baseline_trace
    assert (
        extreme_agent.hormonal_system.to_checkpoint()
        != baseline_agent.hormonal_system.to_checkpoint()
    )
    for report in (*baseline_reports, *extreme_reports):
        assert report["hormonal_behavior"] == {
            "mode": "shadow",
            "active": False,
            "reason": "shadow_only",
            "adjustments": [],
        }


def test_hormonal_advisor_differential_for_six_hundred_cycles_and_restarts(
    monkeypatch,
):
    import math

    from src.core.agent_body import HEAVY_ACTIONS

    source = DigitalBeing(name="HormonalAdvisorLongSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    rich = HormonalSystem()
    rich.hormones.update(
        {
            "dopamine": 1.0,
            "serotonin": 0.5,
            "oxytocin": 1.0,
            "cortisol": 0.0,
            "prolactin": 0.2,
        }
    )
    for name, values in rich.profile.values.items():
        source_name = {
            "oxytocin": "social_message",
            "cortisol": "hardware",
        }.get(name, "action_outcome")
        values["sample_count"] = 200
        values["confidence"] = 1.0
        values["source_sample_counts"] = {source_name: 200}
    initial["integrated_experience"]["hormones"] = rich.to_checkpoint()

    current = {"resources": _low_resources()}
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: current["resources"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", lambda: _storage(0.8)
    )
    monkeypatch.setattr(
        "config.simulation_config.SIM_CONFIG.HARDWARE_BEHAVIOR_MODE", "advisor"
    )

    def run(mode):
        monkeypatch.setattr(
            "config.simulation_config.SIM_CONFIG.HORMONAL_BEHAVIOR_MODE", mode
        )
        random.seed(60019)
        np.random.seed(60019)
        agent = DigitalBeing(name=f"HormonalAdvisorLong_{mode}")
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)
        actions = []
        adjustment_count = 0
        restart_absence = 0
        for cycle in range(600):
            if cycle in {200, 400}:
                state = build_state_from_agent(agent)
                assert "hormonal_behavior_last" not in state
                restored = DigitalBeing(name=agent.name)
                apply_state_to_agent(restored, state)
                assert not hasattr(restored, "hormonal_behavior_last")
                restart_absence += 1
                restored.web_searcher.toggle(False)
                agent = restored
            current["resources"] = (
                _high_resources() if (cycle // 20) % 2 == 0 else _low_resources()
            )
            report = agent.autonomous_tick()
            behavior = report["hormonal_behavior"]
            assert agent.hormonal_behavior_last == behavior
            assert agent.hormonal_behavior_last is not behavior
            evaluations = report["arbitrator"].get("all_evaluations") or []
            input_indices = {entry["input_index"] for entry in evaluations}
            seen_indices = set()
            for entry in behavior.get("adjustments") or []:
                contribution = entry["contribution"]
                before = entry["before_strength"]
                after = entry["after_strength"]
                action = agent._normalize_action(entry["action"])
                assert math.isfinite(contribution)
                assert math.isfinite(before) and before > 0.0
                assert math.isfinite(after)
                assert -0.1 <= contribution <= 0.1
                assert after == pytest.approx(before * (1.0 + contribution))
                assert entry["input_index"] in input_indices
                assert entry["input_index"] not in seen_indices
                seen_indices.add(entry["input_index"])
                if action in {"wait", "rest", "deep_rest"}:
                    assert contribution <= 0.0
                if report["hardware_behavior"].get("active") is True:
                    assert action not in HEAVY_ACTIONS
            adjustment_count += len(behavior.get("adjustments") or [])
            actions.append(report["arbitrator"].get("action"))
            for need in agent.motivation_system.needs.values():
                assert math.isfinite(need.current_level)
                assert 0.0 <= need.current_level <= 1.0
            agent.cycle_count += 1
        return agent, actions, adjustment_count, restart_absence

    shadow_agent, shadow_actions, shadow_adjustments, shadow_restarts = run("shadow")
    advisor_agent, advisor_actions, advisor_adjustments, advisor_restarts = run(
        "advisor"
    )
    shadow_idle = sum(action in {"wait", "deep_rest"} for action in shadow_actions)
    advisor_idle = sum(action in {"wait", "deep_rest"} for action in advisor_actions)
    advisor_heavy = sum(
        advisor_agent._normalize_action(action) in HEAVY_ACTIONS
        for action in advisor_actions
    )

    assert shadow_agent.cycle_count == advisor_agent.cycle_count == 600
    assert shadow_restarts == advisor_restarts == 2
    assert shadow_adjustments == 0
    assert advisor_adjustments > 0
    assert advisor_heavy > 0
    assert advisor_idle <= shadow_idle
    assert advisor_agent.motivation_system.goal_summary["generated"] > 0
    assert len(advisor_agent.hardware_interoception.history) == 200
    assert len(advisor_agent.hardware_interoception.events) <= 50
    assert len(advisor_agent.hardware_interoception.personal.episodes) <= 50
    validate_hardware_interoception(
        advisor_agent.hardware_interoception.to_checkpoint()
    )
    hormonal_checkpoint = advisor_agent.hormonal_system.to_checkpoint()
    HormonalSystem.validate_checkpoint(hormonal_checkpoint)
    assert len(hormonal_checkpoint["history"]) <= 200
    assert len(hormonal_checkpoint["episodes"]) <= 50


def _physical(**values):
    result = {
        name: {
            "available": False,
            "reason": "resource_source_unavailable",
            "source": "test",
        }
        for name in (
            "gpu_utilization",
            "gpu_memory",
            "gpu_temperature",
            "gpu_power",
            "cpu_temperature",
            "external_power",
            "battery_charge",
        )
    }
    for name, value in values.items():
        result[name] = {"available": True, "value": value, "source": "test"}
    return result


def _observe_physical(observer, cycle, **values):
    return observer.observe(
        _low_resources(),
        cycle=cycle,
        storage_status=_storage(),
        physical_status=_physical(**values),
    )


def test_physical_channels_are_independent_before_confirmed_strain():
    observer = HardwareInteroception()
    for cycle in range(4):
        report = _observe_physical(
            observer,
            cycle,
            gpu_utilization=98.0,
            gpu_memory=0.9,
            gpu_temperature=100.0,
            gpu_power=0.95,
            external_power=1.0,
        )

    channels = report["observation"]["channels"]
    assert channels["gpu_temperature"]["value"] == 100.0
    assert channels["cpu_temperature"]["status"] == "unavailable"
    assert channels["battery_charge"]["value"] is None
    assert channels["external_power"]["value"] == 1.0
    assert report["states"]["physical_strain"]["value"] == pytest.approx(1.0)
    assert report["states"]["physical_strain"]["origin"] == "unknown"
    assert report["endocrine_events"] == []
    assert observer.events == []
    assert observer.personal.adaptation == 0.0
    assert observer.personal.current_episode is None


def test_stage5_gpu_only_and_short_physical_spike_create_no_events():
    observer = HardwareInteroception()
    for cycle in range(10):
        report = _observe_physical(
            observer, cycle, gpu_utilization=100.0, gpu_memory=1.0
        )
        assert report["states"]["physical_strain"]["value"] == 1.0
        assert report["endocrine_events"] == []

    for cycle in range(10, 14):
        report = _observe_physical(
            observer,
            cycle,
            gpu_utilization=100.0,
            gpu_temperature=100.0,
            gpu_power=0.95,
        )
        assert report["endocrine_events"] == []
    assert observer.events == []


def test_stage5_sustained_physical_strain_and_recovery_have_own_provenance():
    observer = HardwareInteroception()
    for cycle in range(5):
        report = _observe_physical(
            observer,
            cycle,
            gpu_utilization=98.0,
            gpu_temperature=100.0,
            gpu_power=0.95,
        )
    assert len(report["endocrine_events"]) == 1
    strain = report["endocrine_events"][0]
    assert strain["type"] == "hardware_strain"
    assert strain["reason"] == "sustained_physical_strain"
    assert strain["duration_cycles"] == 5
    assert "gpu_temperature=100.000" in strain["evidence"]

    for cycle in range(5, 10):
        report = _observe_physical(
            observer,
            cycle,
            gpu_utilization=5.0,
            gpu_temperature=45.0,
            gpu_power=0.2,
        )
    assert len(report["endocrine_events"]) == 1
    recovery = report["endocrine_events"][0]
    assert recovery["type"] == "hardware_recovery"
    assert recovery["reason"] == "confirmed_physical_recovery"
    assert recovery["duration_cycles"] == 5


def test_stage5_storage_strain_and_recovery_have_own_provenance():
    observer = HardwareInteroception()
    for cycle in range(5):
        report = observer.observe(
            _low_resources(),
            cycle=cycle,
            storage_status=_storage(0.01),
            physical_status=_physical(),
        )
    assert len(report["endocrine_events"]) == 1
    strain = report["endocrine_events"][0]
    assert strain["type"] == "hardware_strain"
    assert strain["reason"] == "sustained_storage_risk"
    assert strain["duration_cycles"] == 5
    assert "data_free_ratio=0.010" in strain["evidence"]

    for cycle in range(5, 10):
        report = observer.observe(
            _low_resources(),
            cycle=cycle,
            storage_status=_storage(0.8),
            physical_status=_physical(),
        )
    assert len(report["endocrine_events"]) == 1
    recovery = report["endocrine_events"][0]
    assert recovery["type"] == "hardware_recovery"
    assert recovery["reason"] == "confirmed_storage_recovery"
    assert recovery["duration_cycles"] == 5


def test_stage5_projection_separates_domains_and_preserves_other_hormones(
    monkeypatch,
):
    observer = HardwareInteroception()
    hormones = HormonalSystem()
    agent = SimpleNamespace(hardware_interoception=observer, hormonal_system=hormones)
    baseline = dict(hormones.hormones)
    current = {
        "storage": _storage(0.01),
        "physical": _physical(gpu_temperature=100.0, gpu_power=0.95),
    }
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage",
        lambda: current["storage"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_physical_sensors",
        lambda: current["physical"],
    )

    for cycle in range(5):
        report = observe_hardware_interoception(agent, _low_resources(), cycle)
    assert report["projection"]["processed_events"] == 2
    assert {entry["provenance"]["reason"] for entry in hormones.history[-2:]} == {
        "sustained_physical_strain",
        "sustained_storage_risk",
    }
    assert hormones.hormones["cortisol"] > baseline["cortisol"]
    for name in ("dopamine", "oxytocin", "prolactin"):
        assert hormones.hormones[name] == baseline[name]

    current["storage"] = _storage(0.8)
    current["physical"] = _physical(gpu_temperature=45.0, gpu_power=0.2)
    for cycle in range(5, 10):
        report = observe_hardware_interoception(agent, _low_resources(), cycle)
    assert report["projection"]["processed_events"] == 2
    assert {entry["provenance"]["reason"] for entry in hormones.history[-2:]} == {
        "confirmed_physical_recovery",
        "confirmed_storage_recovery",
    }
    assert hormones.hormones["serotonin"] > baseline["serotonin"]
    for name in ("dopamine", "oxytocin", "prolactin"):
        assert hormones.hormones[name] == baseline[name]


def test_stage5_sensor_loss_duplicate_and_restart_do_not_confirm_recovery():
    observer = HardwareInteroception()
    for cycle in range(5):
        observer.observe(
            _low_resources(),
            cycle=cycle,
            storage_status=_storage(0.01),
            physical_status=_physical(gpu_temperature=100.0),
        )
    restored = HardwareInteroception.from_checkpoint(observer.to_checkpoint())
    restored_before = restored.to_checkpoint()
    assert restored.latest_observation["channels"]["data_storage"]["status"] == "stale"
    assert restored.latest_observation["channels"]["gpu_temperature"]["status"] == (
        "stale"
    )

    for cycle in range(5, 10):
        report = restored.observe(
            _low_resources(),
            cycle=cycle,
            storage_status={"available": False, "reason": "sensor_disabled"},
            physical_status=_physical(),
        )
        assert report["endocrine_events"] == []
    duplicate = restored.observe(
        _low_resources(),
        cycle=9,
        storage_status=_storage(0.8),
        physical_status=_physical(gpu_temperature=45.0),
    )
    assert duplicate["skipped"] == "duplicate_cycle"
    duplicate_before = restored.to_checkpoint()
    assert (
        restored.observe(
            _low_resources(),
            cycle=9,
            storage_status=_storage(0.8),
            physical_status=_physical(gpu_temperature=45.0),
        )
        == duplicate
    )
    assert restored.to_checkpoint() == duplicate_before
    assert len(restored.history) == len(restored_before["history"]) + 5

    for cycle in range(10, 14):
        report = restored.observe(
            _low_resources(),
            cycle=cycle,
            storage_status=_storage(0.8),
            physical_status=_physical(gpu_temperature=45.0),
        )
        assert report["endocrine_events"] == []
    report = restored.observe(
        _low_resources(),
        cycle=14,
        storage_status=_storage(0.8),
        physical_status=_physical(gpu_temperature=45.0),
    )
    assert {event["reason"] for event in report["endocrine_events"]} == {
        "confirmed_physical_recovery",
        "confirmed_storage_recovery",
    }


def test_physical_invalid_values_and_raw_os_details_are_sanitized():
    observer = HardwareInteroception()
    physical = _physical(external_power=0.0)
    physical["gpu_utilization"] = {
        "available": True,
        "value": True,
        "source": "C:/private/nvml.exe",
    }
    physical["gpu_temperature"] = {
        "available": True,
        "value": 1000.0,
        "source": "test",
    }
    physical["battery_charge"] = {
        "available": False,
        "reason": "C:/private/battery failure",
        "source": "C:/private/sensor.exe",
    }

    report = observer.observe(
        _low_resources(),
        cycle=1,
        storage_status=_storage(),
        physical_status=physical,
    )

    channels = report["observation"]["channels"]
    assert channels["gpu_utilization"]["reason"] == "invalid_or_missing_measurement"
    assert channels["gpu_temperature"]["value"] is None
    assert channels["external_power"]["value"] == 0.0
    assert channels["battery_charge"]["reason"] == "resource_source_unavailable"
    assert channels["battery_charge"]["source"] == "windows"
    assert "C:/private" not in str(report)


def test_schema2_physical_migration_and_schema4_restart_require_fresh_samples(
    monkeypatch,
):
    observer = HardwareInteroception()
    observer.observe(
        _low_resources(),
        cycle=1,
        storage_status=_storage(),
        physical_status=_physical(gpu_temperature=75.0, external_power=1.0),
    )
    current = observer.to_checkpoint()
    assert current["schema_version"] == 6

    restored = HardwareInteroception.from_checkpoint(current)
    channels = restored.latest_observation["channels"]
    assert channels["gpu_temperature"]["status"] == "stale"
    assert channels["external_power"]["status"] == "stale"
    assert restored.states["physical_strain"]["value"] is None

    legacy = deepcopy(current)
    legacy["schema_version"] = 2
    legacy.pop("slow_states")
    legacy.pop("domain_experience")
    legacy["latest_experience"]["storage_risk"] = {
        "risk": None,
        "experienced": None,
        "expectedness": "unknown",
    }
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

    def unexpected_sampling():
        raise AssertionError("restore must not sample the OS")

    monkeypatch.setattr(
        "src.core.hardware_interoception.read_physical_sensors", unexpected_sampling
    )
    migrated = HardwareInteroception.from_checkpoint(legacy)
    migrated_channels = migrated.latest_observation["channels"]
    assert migrated_channels["host_cpu"]["status"] == "stale"
    for name in (
        "gpu_utilization",
        "gpu_memory",
        "gpu_temperature",
        "gpu_power",
        "cpu_temperature",
        "external_power",
        "battery_charge",
    ):
        assert migrated_channels[name]["status"] == "unavailable"
        assert migrated_channels[name]["value"] is None
    assert migrated.slow_states == HardwareInteroception().slow_states
    migrated_state = migrated.to_checkpoint()
    assert migrated_state["schema_version"] == 6
    validate_hardware_interoception(migrated_state)


def test_recovery_advisor_differential_for_six_hundred_cycles_and_restarts(
    monkeypatch,
):
    source = DigitalBeing(name="RecoveryAdvisorLongSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    current = {"resources": _low_resources()}
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: current["resources"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", lambda: _storage(0.8)
    )

    def run(mode):
        monkeypatch.setattr(
            "config.simulation_config.SIM_CONFIG.HARDWARE_RECOVERY_BEHAVIOR_MODE",
            mode,
        )
        random.seed(60023)
        np.random.seed(60023)
        agent = DigitalBeing(name=f"RecoveryAdvisorLong_{mode}")
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)
        trace = []
        applied_cycles = []
        restart_absence = 0
        for cycle in range(600):
            if cycle in {200, 400}:
                state = build_state_from_agent(agent)
                assert "hardware_recovery_behavior_last" not in state
                restored = DigitalBeing(name=agent.name)
                apply_state_to_agent(restored, state)
                assert not hasattr(restored, "hardware_recovery_behavior_last")
                restart_absence += 1
                restored.web_searcher.toggle(False)
                agent = restored
            current["resources"] = (
                _high_resources() if (cycle // 20) % 2 == 0 else _low_resources()
            )
            # Живой телесный кандидат уже выбирается: поправка не создаёт новый
            # эпизод отдыха и позволяет отделить score-differential от дрейфа.
            agent.interoception.state.fatigue = 0.6
            report = agent.autonomous_tick()
            behavior = report["hardware_recovery_behavior"]
            assert agent.hardware_recovery_behavior_last == behavior
            assert agent.hardware_recovery_behavior_last is not behavior
            if behavior["active"] is True:
                applied_cycles.append(cycle)
            elif mode == "advisor":
                assert behavior["adjustments"] == []
            else:
                assert behavior["active"] is False
                assert behavior["adjustments"] == []
            evaluations = report["arbitrator"].get("all_evaluations") or []
            input_indices = {entry["input_index"] for entry in evaluations}
            seen_indices = set()
            for entry in behavior["adjustments"]:
                assert entry["action"] == "deep_rest"
                assert entry["source"] == "embodiment"
                assert 0.0 < entry["before_strength"] <= 1.0
                assert entry["after_strength"] == pytest.approx(
                    min(1.1, entry["before_strength"] * entry["factor"])
                )
                assert entry["after_strength"] <= 1.1
                assert entry["input_index"] in input_indices
                assert entry["input_index"] not in seen_indices
                seen_indices.add(entry["input_index"])
            trace.append(_canonical_trace(agent, report))
            agent.cycle_count += 1
        return agent, trace, applied_cycles, restart_absence

    shadow_agent, shadow_trace, shadow_applied, shadow_restarts = run("shadow")
    advisor_agent, advisor_trace, advisor_applied, advisor_restarts = run("advisor")

    assert shadow_agent.cycle_count == advisor_agent.cycle_count == 600
    assert shadow_restarts == advisor_restarts == 2
    assert shadow_applied == []
    assert advisor_applied == list(range(24, 600, 40))
    diverged = False
    first_choice_difference = None
    choice_differences = []
    for cycle, (observed, expected) in enumerate(zip(advisor_trace, shadow_trace)):
        if observed["action"] != expected["action"]:
            if first_choice_difference is None:
                # Первое различие обязано быть непосредственным эффектом advisor.
                # После него трассы уже описывают разные downstream-состояния.
                assert cycle in advisor_applied, cycle
                first_choice_difference = cycle
            choice_differences.append(cycle)
        if not diverged and cycle not in advisor_applied:
            assert observed == expected, cycle
        if cycle in advisor_applied:
            observed_evaluations = {
                (row["input_index"], row["action"], row["source"]): row
                for row in observed["evaluations"]
            }
            expected_evaluations = {
                (row["input_index"], row["action"], row["source"]): row
                for row in expected["evaluations"]
            }
            # Отдых уже предложен в обоих контурах: advisor не создаёт эпизод.
            assert any(
                key[1:] == ("deep_rest", "embodiment") for key in observed_evaluations
            )
            assert any(
                key[1:] == ("deep_rest", "embodiment") for key in expected_evaluations
            )
            # Пока трассы не разошлись, сравнение является counterfactual на
            # одинаковом входе. После расхождения остальные evaluations тоже
            # могут отличаться downstream; сама поправка проверена выше.
            if (
                not diverged
                and observed_evaluations.keys() == expected_evaluations.keys()
            ):
                for key, observed_evaluation in observed_evaluations.items():
                    expected_evaluation = expected_evaluations[key]
                    if key[1:] == ("deep_rest", "embodiment"):
                        assert observed_evaluation["strength"] == pytest.approx(
                            min(1.1, expected_evaluation["strength"] * 1.0935)
                        )
                    else:
                        assert observed_evaluation == expected_evaluation, (cycle, key)
        if not diverged and any(
            observed[field] != expected[field]
            for field in expected
            if field not in {"evaluations", "diagnostics"}
        ):
            diverged = True

    assert choice_differences
    assert len(advisor_agent.hardware_interoception.history) == 200
    assert len(advisor_agent.hardware_interoception.events) <= 50
    assert len(advisor_agent.hardware_interoception.personal.episodes) <= 50
    validate_hardware_interoception(
        advisor_agent.hardware_interoception.to_checkpoint()
    )


def test_physical_behavior_shadow_requires_sustained_thermal_or_power_evidence():
    from src.core.hardware_behavior import physical_strain_behavior_report

    gpu_only = HardwareInteroception()
    for cycle in range(5):
        _observe_physical(gpu_only, cycle, gpu_utilization=100.0, gpu_memory=1.0)
    assert physical_strain_behavior_report(gpu_only)["eligible"] is False

    observer = HardwareInteroception()
    for cycle in range(4):
        _observe_physical(observer, cycle, gpu_temperature=100.0, gpu_power=0.95)
        early = physical_strain_behavior_report(observer)
        assert early["active"] is False
        assert early["eligible"] is False
        assert early["reason"] == "insufficient_sustained_physical_strain"
        assert early["adjustments"] == []

    _observe_physical(observer, 4, gpu_temperature=100.0, gpu_power=0.95)
    before = observer.to_checkpoint()
    report = physical_strain_behavior_report(observer)

    assert set(report) == {
        "mode",
        "active",
        "eligible",
        "reason",
        "duration_cycles",
        "risk",
        "experienced",
        "confidence",
        "factor",
        "adjustments",
    }
    assert report["mode"] == "shadow"
    assert report["active"] is False
    assert report["eligible"] is True
    assert report["reason"] == "shadow_only"
    assert report["duration_cycles"] == 5
    assert report["risk"] == pytest.approx(1.0)
    assert report["experienced"] == pytest.approx(1.0)
    assert 0.0 < report["confidence"] <= 1.0
    assert report["factor"] == pytest.approx(
        1.0 - 0.25 * report["experienced"] * report["confidence"]
    )
    assert 0.75 <= report["factor"] < 1.0
    assert report["adjustments"] == []
    assert observer.states["physical_strain"]["origin"] == "unknown"
    assert observer.to_checkpoint() == before

    advisor = physical_strain_behavior_report(observer, "advisor")
    assert advisor["active"] is False
    assert advisor["eligible"] is True
    assert advisor["reason"] == "advisor_requires_candidates"
    assert advisor["adjustments"] == []
    assert observer.to_checkpoint() == before


def test_physical_behavior_rejects_gaps_sensor_loss_and_restart_without_fresh_data():
    from src.core.hardware_behavior import physical_strain_behavior_report

    observer = HardwareInteroception()
    for cycle in (0, 1, 2, 3, 100):
        _observe_physical(observer, cycle, gpu_temperature=100.0, gpu_power=0.95)
    gap = physical_strain_behavior_report(observer)
    assert gap["active"] is False
    assert gap["eligible"] is False
    assert gap["reason"] == "noncontiguous_physical_evidence"

    for cycle in range(101, 105):
        _observe_physical(observer, cycle, gpu_temperature=100.0, gpu_power=0.95)
    assert physical_strain_behavior_report(observer)["eligible"] is True

    restored = HardwareInteroception.from_checkpoint(observer.to_checkpoint())
    restored_before = restored.to_checkpoint()
    waiting = physical_strain_behavior_report(restored)
    assert waiting["active"] is False
    assert waiting["eligible"] is False
    assert waiting["reason"] == "waiting_for_fresh_physical_channels"
    assert restored.to_checkpoint() == restored_before

    _observe_physical(observer, 105)
    loss = physical_strain_behavior_report(observer)
    assert loss["active"] is False
    assert loss["eligible"] is False
    assert loss["reason"] == "waiting_for_fresh_physical_channels"

    non_physical = HardwareInteroception()
    for cycle in range(5):
        non_physical.observe(
            _high_resources(),
            cycle=cycle,
            storage_status=_storage(0.01),
            physical_status=_physical(gpu_utilization=100.0),
        )
    assert physical_strain_behavior_report(non_physical)["eligible"] is False
    assert non_physical.states["physical_strain"]["origin"] == "unknown"


def test_physical_advisor_activation_has_no_upstream_or_candidate_drift(monkeypatch):
    from src.core.agent_body import HEAVY_ACTIONS

    source = DigitalBeing(name="PhysicalBehaviorShadowSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    shadow = DigitalBeing(name="PhysicalBehaviorShadow")
    advisor = DigitalBeing(name="PhysicalBehaviorAdvisor")
    unknown = DigitalBeing(name="PhysicalBehaviorUnknown")
    for agent in (shadow, advisor, unknown):
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)
        for name in ("dopamine", "oxytocin", "cortisol"):
            agent.hormonal_system.hormones[name] = 1.0
            agent.hormonal_system.profile.values[name]["sample_count"] = 20

    current = {
        "resources": _low_resources(),
        "physical": _physical(gpu_temperature=100.0, gpu_power=0.95),
    }
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: current["resources"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", lambda: _storage()
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_physical_sensors",
        lambda: current["physical"],
    )
    monkeypatch.setattr(
        "config.simulation_config.SIM_CONFIG.HORMONAL_BEHAVIOR_MODE", "advisor"
    )

    def run(agent, mode):
        monkeypatch.setattr(
            "config.simulation_config.SIM_CONFIG.HARDWARE_PHYSICAL_BEHAVIOR_MODE",
            mode,
            raising=False,
        )
        random.seed(7007)
        np.random.seed(7007)
        trace = []
        reports = []
        for _ in range(6):
            report = agent.autonomous_tick()
            reports.append(report)
            trace.append(_canonical_trace(agent, report))
            agent.cycle_count += 1
        return trace, reports

    shadow_trace, shadow_reports = run(shadow, "shadow")
    advisor_trace, advisor_reports = run(advisor, "advisor")
    unknown_trace, unknown_reports = run(unknown, "unsupported")

    assert advisor_trace[:4] == shadow_trace[:4]
    assert unknown_trace == shadow_trace
    assert [report["hardware_interoception"] for report in advisor_reports] == [
        report["hardware_interoception"] for report in shadow_reports
    ]
    assert all(
        report["hardware_physical_behavior"]["active"] is False
        and report["hardware_physical_behavior"]["adjustments"] == []
        for report in [*shadow_reports, *advisor_reports[:4], *unknown_reports]
    )
    activation = advisor_reports[4]["hardware_physical_behavior"]
    assert activation["mode"] == "advisor"
    assert activation["active"] is True
    assert activation["eligible"] is True
    assert activation["reason"] == "applied"
    assert activation["adjustments"]
    for report in advisor_reports:
        if report["hardware_physical_behavior"]["active"]:
            assert all(
                item["action"] not in HEAVY_ACTIONS
                for item in report["hormonal_behavior"]["adjustments"]
            )
    shadow_choice = shadow_reports[4]["arbitrator"]["all_evaluations"]
    advisor_choice = advisor_reports[4]["arbitrator"]["all_evaluations"]
    assert [
        (item["input_index"], item["action"], item["source"]) for item in advisor_choice
    ] == [
        (item["input_index"], item["action"], item["source"]) for item in shadow_choice
    ]
    assert unknown_reports[-1]["hardware_physical_behavior"]["reason"] == (
        "unsupported_mode"
    )
    assert "hardware_physical_behavior" not in build_state_from_agent(shadow)
    assert (
        shadow.hardware_physical_behavior_last
        == shadow_reports[-1]["hardware_physical_behavior"]
    )
    assert (
        shadow.hardware_physical_behavior_last
        is not shadow_reports[-1]["hardware_physical_behavior"]
    )


def test_physical_advisor_changes_only_existing_heavy_candidates_once():
    from src.core.hardware_behavior import apply_physical_strain_advice

    observer = HardwareInteroception()
    for cycle in range(5):
        _observe_physical(observer, cycle, gpu_temperature=100.0, gpu_power=0.95)
    candidates = [
        {"action": "explore", "source": "motivation", "strength": 0.8},
        {"action": "synthesis", "source": "active_goal", "strength": 0.6},
        {"action": "communicate", "source": "social", "strength": 0.8},
        {
            "action": "process_stimulus",
            "source": "external_attention",
            "strength": 0.85,
            "params": {"user_initiated": True},
        },
        {"action": "repair", "source": "maintenance", "strength": 0.9},
        {"action": "wait", "source": "deliberate_pause", "strength": 0.3},
        {"action": "hypothesis", "source": "invalid_negative", "strength": -0.2},
        {"action": "reflection", "source": "zero", "strength": 0.0},
    ]
    original_actions = [candidate["action"] for candidate in candidates]
    input_strengths = [candidate["strength"] for candidate in candidates]
    checkpoint = observer.to_checkpoint()

    report = apply_physical_strain_advice(
        candidates,
        observer,
        lambda action: action,
        input_strengths=input_strengths,
    )

    assert report["active"] is True
    assert report["eligible"] is True
    assert report["reason"] == "applied"
    assert [candidate["action"] for candidate in candidates] == original_actions
    assert [item["action"] for item in report["adjustments"]] == [
        "explore",
        "synthesis",
    ]
    assert candidates[0]["strength"] == pytest.approx(0.8 * report["factor"])
    assert candidates[1]["strength"] == pytest.approx(0.6 * report["factor"])
    assert candidates[2]["strength"] == 0.8
    assert candidates[3]["strength"] == 0.85
    assert candidates[4]["strength"] == 0.9
    assert candidates[5]["strength"] == 0.3
    assert candidates[6]["strength"] == -0.2
    assert candidates[7]["strength"] == 0.0
    assert report["factor"] >= 0.75
    assert observer.to_checkpoint() == checkpoint

    strengths = [candidate["strength"] for candidate in candidates]
    duplicate = apply_physical_strain_advice(
        candidates,
        observer,
        lambda action: action,
        input_strengths=input_strengths,
    )
    assert duplicate["active"] is False
    assert duplicate["eligible"] is True
    assert duplicate["reason"] == "duplicate_cycle"
    assert duplicate["adjustments"] == []
    assert [candidate["strength"] for candidate in candidates] == strengths
    assert observer.to_checkpoint() == checkpoint


def test_physical_advisor_shares_one_strength_budget_with_own_load():
    from src.core.hardware_behavior import apply_physical_strain_advice

    def confirmed_observer():
        observer = HardwareInteroception()
        for cycle in range(5):
            observer.observe(
                _high_resources(),
                cycle=cycle,
                storage_status=_storage(),
                physical_status=_physical(gpu_temperature=100.0, gpu_power=0.95),
            )
        return observer

    # Ослабленный привыканием own_load даёт меньшую скидку, чем physical.
    observer = confirmed_observer()
    observer.personal.latest_experience["own_load"]["experienced"] = 0.1
    candidates = [
        {"action": "explore", "source": "motivation", "strength": 0.8},
        {"action": "communicate", "source": "social", "strength": 0.8},
    ]
    input_strengths = [0.8, 0.8]
    own = apply_own_load_advice(candidates, observer, lambda action: action)
    own_after = candidates[0]["strength"]
    physical = apply_physical_strain_advice(
        candidates,
        observer,
        lambda action: action,
        input_strengths=input_strengths,
    )
    assert own["active"] is True
    assert physical["active"] is True
    assert physical["factor"] < own["factor"]
    assert candidates[0]["strength"] == pytest.approx(0.8 * physical["factor"])
    assert candidates[0]["strength"] < own_after
    assert candidates[0]["strength"] > own_after * physical["factor"]
    assert candidates[0]["strength"] >= 0.8 * 0.75
    assert candidates[1]["strength"] == 0.8

    # Если own_load уже снизил сильнее, повторной physical-скидки нет.
    observer = confirmed_observer()
    candidates = [{"action": "explore", "source": "motivation", "strength": 0.8}]
    own = apply_own_load_advice(candidates, observer, lambda action: action)
    own_after = candidates[0]["strength"]
    physical = apply_physical_strain_advice(
        candidates,
        observer,
        lambda action: action,
        input_strengths=[0.8],
    )
    assert own["active"] is True
    assert own["factor"] < physical["factor"]
    assert physical["active"] is False
    assert physical["reason"] == "shared_budget_already_applied"
    assert physical["adjustments"] == []
    assert candidates[0]["strength"] == own_after
    assert candidates[0]["strength"] >= 0.8 * 0.75


def test_physical_advisor_application_is_atomic_and_checkpoint_neutral():
    from src.core.hardware_behavior import apply_physical_strain_advice

    observer = HardwareInteroception()
    for cycle in range(5):
        _observe_physical(observer, cycle, gpu_temperature=100.0, gpu_power=0.95)
    candidates = [
        {"action": "explore", "strength": 0.8},
        {"action": "synthesis", "strength": 0.6},
    ]
    checkpoint = observer.to_checkpoint()

    def fail_on_second(action):
        if action == "synthesis":
            raise ValueError("normalization failed")
        return action

    with pytest.raises(ValueError, match="normalization failed"):
        apply_physical_strain_advice(
            candidates,
            observer,
            fail_on_second,
            input_strengths=[0.8, 0.6],
        )
    assert [candidate["strength"] for candidate in candidates] == [0.8, 0.6]
    assert observer.to_checkpoint() == checkpoint


def test_physical_advisor_differential_for_six_hundred_cycles_and_restarts(
    monkeypatch,
):
    from src.core.agent_body import HEAVY_ACTIONS

    source = DigitalBeing(name="PhysicalAdvisorLongSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    current = {
        "resources": _low_resources(),
        "physical": _physical(gpu_temperature=100.0, gpu_power=0.95),
    }
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: current["resources"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", lambda: _storage(0.8)
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_physical_sensors",
        lambda: current["physical"],
    )

    pre_emotional_traces = {}
    current_trace_key = {"mode": None}
    original_emotional_bias = DigitalBeing._apply_emotional_bias

    def capture_pre_emotional(self, candidates):
        mode = current_trace_key["mode"]
        snapshot = deepcopy(candidates)
        for candidate in snapshot:
            params = candidate.get("params") or {}
            if params.get("continuation_of") is not None:
                params["continuation_of"] = "present"
        pre_emotional_traces.setdefault(mode, []).append(snapshot)
        return original_emotional_bias(self, candidates)

    monkeypatch.setattr(DigitalBeing, "_apply_emotional_bias", capture_pre_emotional)

    def run(mode):
        current_trace_key["mode"] = mode
        monkeypatch.setattr(
            "config.simulation_config.SIM_CONFIG.HARDWARE_PHYSICAL_BEHAVIOR_MODE",
            mode,
        )
        random.seed(70029)
        np.random.seed(70029)
        agent = DigitalBeing(name=f"PhysicalAdvisorLong_{mode}")
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)
        trace = []
        eligible_cycles = []
        applied_cycles = []
        adjustment_history = {}
        restart_absence = 0
        for cycle in range(600):
            if cycle in {200, 400}:
                state = build_state_from_agent(agent)
                assert "hardware_physical_behavior_last" not in state
                restored = DigitalBeing(name=agent.name)
                apply_state_to_agent(restored, state)
                assert not hasattr(restored, "hardware_physical_behavior_last")
                restart_absence += 1
                restored.web_searcher.toggle(False)
                agent = restored
            current["physical"] = (
                _physical(gpu_temperature=100.0, gpu_power=0.95)
                if (cycle // 20) % 2 == 0
                else _physical(gpu_temperature=45.0, gpu_power=0.2)
            )
            report = agent.autonomous_tick()
            behavior = report["hardware_physical_behavior"]
            assert agent.hardware_physical_behavior_last == behavior
            assert agent.hardware_physical_behavior_last is not behavior
            expected_eligible = (cycle // 20) % 2 == 0 and cycle % 20 >= 4
            assert behavior["eligible"] is expected_eligible
            if expected_eligible:
                eligible_cycles.append(cycle)
            if behavior["active"] is True:
                applied_cycles.append(cycle)
                adjustment_history[cycle] = deepcopy(behavior["adjustments"])
            else:
                assert behavior["adjustments"] == []
            evaluations = report["arbitrator"].get("all_evaluations") or []
            input_indices = {entry["input_index"] for entry in evaluations}
            seen_indices = set()
            for entry in behavior["adjustments"]:
                assert agent._normalize_action(entry["action"]) in HEAVY_ACTIONS
                assert entry["before_strength"] > 0.0
                assert entry["after_strength"] == pytest.approx(
                    entry["before_strength"] * entry["factor"]
                )
                assert entry["after_strength"] >= entry["before_strength"] * 0.75
                assert entry["input_index"] in input_indices
                assert entry["input_index"] not in seen_indices
                seen_indices.add(entry["input_index"])
            trace.append(_canonical_trace(agent, report))
            agent.cycle_count += 1
        pre_emotional = pre_emotional_traces[mode]
        assert len(pre_emotional) == len(trace) == 600
        for entry, candidates in zip(trace, pre_emotional):
            entry["pre_emotional_candidates"] = candidates
        return (
            agent,
            trace,
            eligible_cycles,
            applied_cycles,
            restart_absence,
            adjustment_history,
        )

    shadow_agent, shadow_trace, _, shadow_applied, shadow_restarts, _ = run("shadow")
    (
        advisor_agent,
        advisor_trace,
        expected_eligible,
        advisor_applied,
        advisor_restarts,
        adjustments,
    ) = run("advisor")

    assert shadow_agent.cycle_count == advisor_agent.cycle_count == 600
    assert shadow_restarts == advisor_restarts == 2
    assert shadow_applied == []
    assert advisor_applied
    assert set(advisor_applied) <= set(expected_eligible)
    diverged = False
    first_choice_difference = None
    choice_differences = []
    evaluation_differences = []
    for cycle, (observed, expected) in enumerate(zip(advisor_trace, shadow_trace)):
        if observed["action"] != expected["action"]:
            if first_choice_difference is None:
                assert cycle in advisor_applied, cycle
                first_choice_difference = cycle
            choice_differences.append(cycle)
        if not diverged and cycle not in advisor_applied:
            assert observed == expected, cycle
        if cycle in advisor_applied:
            observed_evaluations = {
                (row["input_index"], row["action"], row["source"]): row
                for row in observed["evaluations"]
            }
            expected_evaluations = {
                (row["input_index"], row["action"], row["source"]): row
                for row in expected["evaluations"]
            }
            if observed_evaluations != expected_evaluations:
                evaluation_differences.append(cycle)
            if not diverged:
                observed_candidates = {
                    (index, row["action"], row["source"]): row
                    for index, row in enumerate(observed["pre_emotional_candidates"])
                }
                expected_candidates = {
                    (index, row["action"], row["source"]): row
                    for index, row in enumerate(expected["pre_emotional_candidates"])
                }
                assert observed_candidates.keys() == expected_candidates.keys()
                assert observed_candidates.keys() == observed_evaluations.keys()
                cycle_adjustments = {
                    (row["input_index"], row["action"], row["source"]): row
                    for row in adjustments[cycle]
                }
                for key, observed_candidate in observed_candidates.items():
                    expected_candidate = expected_candidates[key]
                    if key in cycle_adjustments:
                        adjustment = cycle_adjustments[key]
                        assert observed_candidate["strength"] == pytest.approx(
                            adjustment["after_strength"]
                        )
                        assert observed_candidate["strength"] == pytest.approx(
                            expected_candidate["strength"] * adjustment["factor"]
                        )
                        assert observed_candidate["strength"] >= (
                            adjustment["before_strength"] * 0.75
                        )
                        assert {
                            field: value
                            for field, value in observed_candidate.items()
                            if field != "strength"
                        } == {
                            field: value
                            for field, value in expected_candidate.items()
                            if field != "strength"
                        }
                    else:
                        assert observed_candidate == expected_candidate, (cycle, key)
        if not diverged and any(
            observed[field] != expected[field]
            for field in expected
            if field not in {"evaluations", "diagnostics"}
        ):
            diverged = True

    assert evaluation_differences
    assert len(advisor_agent.hardware_interoception.history) == 200
    assert len(advisor_agent.hardware_interoception.events) <= 50
    assert len(advisor_agent.hardware_interoception.personal.episodes) <= 50
    physical = advisor_agent.hardware_interoception.domain_personal.domains["physical"]
    assert len(physical["episodes"]) <= 50
    validate_hardware_interoception(
        advisor_agent.hardware_interoception.to_checkpoint()
    )


def test_storage_behavior_shadow_requires_five_sustained_fresh_cycles():
    from src.core.hardware_behavior import storage_risk_behavior_report

    observer = HardwareInteroception()
    for cycle in range(4):
        _observe(observer, cycle, _low_resources(), free_ratio=0.01)
        early = storage_risk_behavior_report(observer)
        assert early["active"] is False
        assert early["eligible"] is False
        assert early["reason"] == "insufficient_sustained_storage_risk"
        assert early["factor"] == 1.0
        assert early["adjustments"] == []

    _observe(observer, 4, _low_resources(), free_ratio=0.01)
    before = observer.to_checkpoint()
    report = storage_risk_behavior_report(observer)

    assert set(report) == {
        "mode",
        "active",
        "eligible",
        "reason",
        "duration_cycles",
        "risk",
        "experienced",
        "confidence",
        "factor",
        "adjustments",
    }
    assert report["mode"] == "shadow"
    assert report["active"] is False
    assert report["eligible"] is True
    assert report["reason"] == "shadow_only"
    assert report["duration_cycles"] == 5
    assert report["risk"] == pytest.approx(0.96)
    assert report["experienced"] == pytest.approx(0.96)
    assert report["confidence"] == pytest.approx(1.0)
    assert report["factor"] == pytest.approx(0.76)
    assert report["adjustments"] == []
    assert observer.states["storage_risk"]["origin"] == "unknown"
    assert observer.to_checkpoint() == before

    advisor = storage_risk_behavior_report(observer, "advisor")
    assert advisor["active"] is False
    assert advisor["eligible"] is True
    assert advisor["reason"] == "advisor_requires_candidates"
    assert advisor["factor"] == pytest.approx(0.76)
    assert advisor["adjustments"] == []
    assert observer.to_checkpoint() == before

    duplicate = _observe(observer, 4, _low_resources(), free_ratio=0.01)
    assert duplicate["skipped"] == "duplicate_cycle"
    assert storage_risk_behavior_report(observer) == report
    assert observer.to_checkpoint() == before


def test_storage_behavior_rejects_gaps_sensor_loss_restart_and_other_domains():
    from src.core.hardware_behavior import storage_risk_behavior_report

    observer = HardwareInteroception()
    for cycle in (0, 1, 2, 3, 100):
        _observe(observer, cycle, _low_resources(), free_ratio=0.01)
    gap = storage_risk_behavior_report(observer)
    assert gap["active"] is False
    assert gap["eligible"] is False
    assert gap["reason"] == "noncontiguous_storage_evidence"

    for cycle in range(101, 105):
        _observe(observer, cycle, _low_resources(), free_ratio=0.01)
    assert storage_risk_behavior_report(observer)["eligible"] is True

    restored = HardwareInteroception.from_checkpoint(observer.to_checkpoint())
    restored_before = restored.to_checkpoint()
    waiting = storage_risk_behavior_report(restored)
    assert waiting["active"] is False
    assert waiting["eligible"] is False
    assert waiting["reason"] == "waiting_for_fresh_storage_channel"
    assert restored.to_checkpoint() == restored_before

    observer.observe(
        _low_resources(),
        cycle=105,
        storage_status={"available": False, "reason": "sensor_disabled"},
        physical_status={},
    )
    loss = storage_risk_behavior_report(observer)
    assert loss["active"] is False
    assert loss["eligible"] is False
    assert loss["reason"] == "waiting_for_fresh_storage_channel"

    non_storage = HardwareInteroception()
    for cycle in range(5):
        non_storage.observe(
            _high_resources(),
            cycle=cycle,
            storage_status=_storage(0.8),
            physical_status=_physical(gpu_temperature=100.0, gpu_power=0.95),
        )
    assert storage_risk_behavior_report(non_storage)["eligible"] is False
    assert non_storage.states["storage_risk"]["origin"] == "unknown"


def _confirmed_storage_observer():
    observer = HardwareInteroception()
    for cycle in range(5):
        _observe(observer, cycle, _low_resources(), free_ratio=0.01)
    return observer


def _storage_test_action(action):
    return {"creative_act": "create_draft"}.get(action, action)


def test_storage_advisor_changes_only_allowed_existing_candidates_once():
    from src.core.hardware_behavior import apply_storage_risk_advice

    observer = _confirmed_storage_observer()
    candidates = [
        {
            "action": "creative_act",
            "source": "motivation",
            "strength": 0.8,
            "params": {"draft_mode": "new", "topic": "private-test-topic"},
        },
        {
            "action": "create_draft",
            "source": "creative_choices",
            "strength": 0.6,
            "params": {"draft_mode": "continue"},
        },
        {
            "action": "create_draft",
            "source": "creative_choices",
            "strength": 0.5,
            "params": {},
        },
        {"action": "draw", "source": "motivation", "strength": 0.4},
        {"action": "compose_music", "source": "motivation", "strength": 0.9},
        {
            "action": "create_draft",
            "source": "creative_choices",
            "strength": 0.7,
            "params": {"draft_mode": "leave"},
        },
        {"action": "web_search", "source": "motivation", "strength": 0.8},
        {"action": "explore", "source": "motivation", "strength": 0.8},
        {"action": "checkpoint_now", "source": "maintenance", "strength": 1.0},
        {"action": "repair", "source": "maintenance", "strength": 1.0},
        {"action": "rest", "source": "embodiment", "strength": 0.9},
        {"action": "deep_rest", "source": "embodiment", "strength": 0.9},
        {"action": "wait", "source": "deliberate_pause", "strength": 0.3},
        {"action": "draw", "source": "invalid_bool", "strength": True},
        {"action": "draw", "source": "invalid_nan", "strength": float("nan")},
        {"action": "draw", "source": "invalid_zero", "strength": 0.0},
        {"action": "draw", "source": "invalid_negative", "strength": -0.2},
    ]
    original = deepcopy(candidates)
    checkpoint = observer.to_checkpoint()

    report = apply_storage_risk_advice(candidates, observer, _storage_test_action)

    assert report["active"] is True
    assert report["eligible"] is True
    assert report["reason"] == "applied"
    assert report["factor"] == pytest.approx(0.76)
    assert [item["input_index"] for item in report["adjustments"]] == [0, 1, 2, 3, 4]
    for index, adjustment in zip(range(5), report["adjustments"]):
        assert candidates[index]["strength"] == pytest.approx(
            original[index]["strength"] * 0.76
        )
        assert adjustment["before_strength"] == original[index]["strength"]
        assert adjustment["after_strength"] == candidates[index]["strength"]
        assert adjustment["factor"] == report["factor"]
        assert adjustment["action"] == original[index]["action"]
        assert adjustment["source"] == original[index]["source"]
    for index, (candidate, before) in enumerate(zip(candidates, original)):
        assert candidate["action"] == before["action"]
        assert candidate["source"] == before["source"]
        assert candidate.get("params") == before.get("params")
        if before["source"] == "invalid_nan":
            assert candidate["strength"] != candidate["strength"]
        elif index >= 5:
            assert candidate["strength"] == before["strength"]
    assert observer.to_checkpoint() == checkpoint

    strengths = [candidate["strength"] for candidate in candidates]
    duplicate = apply_storage_risk_advice(candidates, observer, _storage_test_action)
    assert duplicate["active"] is False
    assert duplicate["eligible"] is True
    assert duplicate["reason"] == "duplicate_cycle"
    assert duplicate["adjustments"] == []
    assert [candidate["strength"] for candidate in candidates] == strengths
    assert observer.to_checkpoint() == checkpoint


def test_storage_advisor_is_atomic_and_ignores_absent_candidates():
    from src.core.hardware_behavior import apply_storage_risk_advice

    observer = _confirmed_storage_observer()
    candidates = [
        {
            "action": "create_draft",
            "strength": 0.8,
            "params": {"draft_mode": "new"},
        },
        {"action": "draw", "strength": 0.6},
    ]
    original = deepcopy(candidates)
    checkpoint = observer.to_checkpoint()

    def fail_on_second(action):
        if action == "draw":
            raise ValueError("normalization failed")
        return action

    with pytest.raises(ValueError, match="normalization failed"):
        apply_storage_risk_advice(candidates, observer, fail_on_second)
    assert candidates == original
    assert observer.to_checkpoint() == checkpoint
    assert not hasattr(observer, "_storage_advisor_applied_cycle")

    no_match = apply_storage_risk_advice(
        [
            {
                "action": "create_draft",
                "strength": 0.8,
                "params": {"draft_mode": "leave"},
            },
            {"action": "web_search", "strength": 0.8},
        ],
        observer,
        _storage_test_action,
    )
    assert no_match["active"] is False
    assert no_match["eligible"] is True
    assert no_match["reason"] == "no_matching_candidates"
    assert no_match["adjustments"] == []
    assert observer.to_checkpoint() == checkpoint


def _inject_storage_candidate(monkeypatch):
    from src.cognition import method_feedback

    original = method_feedback.prepare_candidates

    def prepare(agent, candidates):
        prepared, feedback = original(agent, candidates)
        prepared.append(
            {
                "action": "draw",
                "source": "storage_advisor_probe",
                "strength": 0.08,
                "params": {"probe": True},
            }
        )
        return prepared, feedback

    monkeypatch.setattr(method_feedback, "prepare_candidates", prepare)


def test_storage_behavior_modes_and_advisor_candidate_drift(monkeypatch):
    source = DigitalBeing(name="StorageBehaviorSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    agents = {
        mode: DigitalBeing(name=f"StorageBehavior_{mode}")
        for mode in ("shadow", "advisor", "unsupported")
    }
    for agent in agents.values():
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)

    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: _low_resources(),
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", lambda: _storage(0.01)
    )
    _inject_storage_candidate(monkeypatch)
    pre_emotional = {}
    current_mode = {"value": None}
    original_emotional_bias = DigitalBeing._apply_emotional_bias

    def capture_candidates(self, candidates):
        snapshot = deepcopy(candidates)
        for candidate in snapshot:
            params = candidate.get("params") or {}
            if params.get("continuation_of") is not None:
                params["continuation_of"] = "present"
        pre_emotional.setdefault(current_mode["value"], []).append(snapshot)
        return original_emotional_bias(self, candidates)

    monkeypatch.setattr(DigitalBeing, "_apply_emotional_bias", capture_candidates)

    def run(mode):
        current_mode["value"] = mode
        monkeypatch.setattr(
            "config.simulation_config.SIM_CONFIG.HARDWARE_STORAGE_BEHAVIOR_MODE",
            mode,
            raising=False,
        )
        random.seed(8008)
        np.random.seed(8008)
        reports = []
        traces = []
        for _ in range(6):
            report = agents[mode].autonomous_tick()
            reports.append(report)
            traces.append(_canonical_trace(agents[mode], report))
            agents[mode].cycle_count += 1
        return traces, reports

    shadow_trace, shadow_reports = run("shadow")
    advisor_trace, advisor_reports = run("advisor")
    unknown_trace, unknown_reports = run("unsupported")

    assert unknown_trace == shadow_trace
    assert advisor_trace[:4] == shadow_trace[:4]
    assert [report["hardware_interoception"] for report in advisor_reports] == [
        report["hardware_interoception"] for report in shadow_reports
    ]
    assert all(
        report["hardware_storage_behavior"]["active"] is False
        and report["hardware_storage_behavior"]["adjustments"] == []
        for report in [*shadow_reports, *unknown_reports]
    )
    assert shadow_reports[4]["hardware_storage_behavior"]["eligible"] is True
    assert shadow_reports[4]["hardware_storage_behavior"]["reason"] == "shadow_only"
    assert unknown_reports[-1]["hardware_storage_behavior"]["reason"] == (
        "unsupported_mode"
    )
    for cycle in (4, 5):
        behavior = advisor_reports[cycle]["hardware_storage_behavior"]
        assert behavior["active"] is True
        assert behavior["reason"] == "applied"
        adjustments = {item["input_index"]: item for item in behavior["adjustments"]}
        assert any(
            item["action"] == "draw" and item["source"] == "storage_advisor_probe"
            for item in adjustments.values()
        )
        observed = pre_emotional["advisor"][cycle]
        expected = pre_emotional["shadow"][cycle]
        assert len(observed) == len(expected)
        for index, (candidate, baseline) in enumerate(zip(observed, expected)):
            if index in adjustments:
                adjustment = adjustments[index]
                assert _storage_test_action(adjustment["action"]) in {
                    "create_draft",
                    "draw",
                    "compose_music",
                }
                assert candidate["strength"] == pytest.approx(
                    baseline["strength"] * behavior["factor"]
                )
                assert candidate["strength"] >= baseline["strength"] * 0.75
                assert {
                    key: value for key, value in candidate.items() if key != "strength"
                } == {
                    key: value for key, value in baseline.items() if key != "strength"
                }
            else:
                assert candidate == baseline
    for mode, agent in agents.items():
        behavior = {"shadow": shadow_reports, "advisor": advisor_reports}.get(
            mode, unknown_reports
        )[-1]["hardware_storage_behavior"]
        assert agent.hardware_storage_behavior_last == behavior
        assert agent.hardware_storage_behavior_last is not behavior
        assert "hardware_storage_behavior_last" not in build_state_from_agent(agent)


def test_storage_advisor_differential_for_six_hundred_cycles_and_restarts(
    monkeypatch,
):
    source = DigitalBeing(name="StorageAdvisorLongSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    current = {"free_ratio": 0.8}
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: _low_resources(),
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage",
        lambda: _storage(current["free_ratio"]),
    )
    _inject_storage_candidate(monkeypatch)

    pre_emotional_traces = {}
    current_trace_key = {"mode": None}
    original_emotional_bias = DigitalBeing._apply_emotional_bias

    def capture_pre_emotional(self, candidates):
        mode = current_trace_key["mode"]
        snapshot = deepcopy(candidates)
        for candidate in snapshot:
            params = candidate.get("params") or {}
            if params.get("continuation_of") is not None:
                params["continuation_of"] = "present"
        pre_emotional_traces.setdefault(mode, []).append(snapshot)
        return original_emotional_bias(self, candidates)

    monkeypatch.setattr(DigitalBeing, "_apply_emotional_bias", capture_pre_emotional)

    def run(mode):
        current_trace_key["mode"] = mode
        monkeypatch.setattr(
            "config.simulation_config.SIM_CONFIG.HARDWARE_STORAGE_BEHAVIOR_MODE",
            mode,
        )
        random.seed(80029)
        np.random.seed(80029)
        agent = DigitalBeing(name=f"StorageAdvisorLong_{mode}")
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)
        trace = []
        eligible_cycles = []
        applied_cycles = []
        adjustment_history = {}
        restart_absence = 0
        for cycle in range(600):
            if cycle in {200, 400}:
                state = build_state_from_agent(agent)
                assert "hardware_storage_behavior_last" not in state
                restored = DigitalBeing(name=agent.name)
                apply_state_to_agent(restored, state)
                assert not hasattr(restored, "hardware_storage_behavior_last")
                assert not hasattr(
                    restored.hardware_interoception, "_storage_advisor_applied_cycle"
                )
                restart_absence += 1
                restored.web_searcher.toggle(False)
                agent = restored
            current["free_ratio"] = 0.01 if (cycle // 20) % 2 == 0 else 0.8
            report = agent.autonomous_tick()
            behavior = report["hardware_storage_behavior"]
            assert agent.hardware_storage_behavior_last == behavior
            assert agent.hardware_storage_behavior_last is not behavior
            expected_eligible = (cycle // 20) % 2 == 0 and cycle % 20 >= 4
            assert behavior["eligible"] is expected_eligible
            if expected_eligible:
                eligible_cycles.append(cycle)
            if behavior["active"] is True:
                applied_cycles.append(cycle)
                adjustment_history[cycle] = deepcopy(behavior["adjustments"])
            else:
                assert behavior["adjustments"] == []
            evaluations = report["arbitrator"].get("all_evaluations") or []
            input_indices = {entry["input_index"] for entry in evaluations}
            seen_indices = set()
            for entry in behavior["adjustments"]:
                assert agent._normalize_action(entry["action"]) in {
                    "create_draft",
                    "draw",
                    "compose_music",
                }
                assert entry["before_strength"] > 0.0
                assert entry["after_strength"] == pytest.approx(
                    entry["before_strength"] * entry["factor"]
                )
                assert entry["after_strength"] >= entry["before_strength"] * 0.75
                assert entry["input_index"] in input_indices
                assert entry["input_index"] not in seen_indices
                seen_indices.add(entry["input_index"])
            trace.append(_canonical_trace(agent, report))
            agent.cycle_count += 1
        pre_emotional = pre_emotional_traces[mode]
        assert len(pre_emotional) == len(trace) == 600
        for entry, candidates in zip(trace, pre_emotional):
            entry["pre_emotional_candidates"] = candidates
        return (
            agent,
            trace,
            eligible_cycles,
            applied_cycles,
            restart_absence,
            adjustment_history,
        )

    shadow_agent, shadow_trace, _, shadow_applied, shadow_restarts, _ = run("shadow")
    (
        advisor_agent,
        advisor_trace,
        expected_eligible,
        advisor_applied,
        advisor_restarts,
        adjustments,
    ) = run("advisor")

    assert shadow_agent.cycle_count == advisor_agent.cycle_count == 600
    assert shadow_restarts == advisor_restarts == 2
    assert shadow_applied == []
    assert advisor_applied
    assert set(advisor_applied) <= set(expected_eligible)
    diverged = False
    evaluation_differences = []
    for cycle, (observed, expected) in enumerate(zip(advisor_trace, shadow_trace)):
        if observed["action"] != expected["action"] and not diverged:
            assert cycle in advisor_applied, cycle
        if not diverged and cycle not in advisor_applied:
            assert observed == expected, cycle
        if cycle in advisor_applied:
            observed_evaluations = {
                (row["input_index"], row["action"], row["source"]): row
                for row in observed["evaluations"]
            }
            expected_evaluations = {
                (row["input_index"], row["action"], row["source"]): row
                for row in expected["evaluations"]
            }
            if observed_evaluations != expected_evaluations:
                evaluation_differences.append(cycle)
            if not diverged:
                observed_candidates = {
                    (index, row["action"], row["source"]): row
                    for index, row in enumerate(observed["pre_emotional_candidates"])
                }
                expected_candidates = {
                    (index, row["action"], row["source"]): row
                    for index, row in enumerate(expected["pre_emotional_candidates"])
                }
                assert observed_candidates.keys() == expected_candidates.keys()
                assert observed_candidates.keys() == observed_evaluations.keys()
                cycle_adjustments = {
                    (row["input_index"], row["action"], row["source"]): row
                    for row in adjustments[cycle]
                }
                for key, observed_candidate in observed_candidates.items():
                    expected_candidate = expected_candidates[key]
                    if key in cycle_adjustments:
                        adjustment = cycle_adjustments[key]
                        assert observed_candidate["strength"] == pytest.approx(
                            adjustment["after_strength"]
                        )
                        assert observed_candidate["strength"] == pytest.approx(
                            expected_candidate["strength"] * adjustment["factor"]
                        )
                        assert {
                            field: value
                            for field, value in observed_candidate.items()
                            if field != "strength"
                        } == {
                            field: value
                            for field, value in expected_candidate.items()
                            if field != "strength"
                        }
                    else:
                        assert observed_candidate == expected_candidate, (cycle, key)
        if not diverged and any(
            observed[field] != expected[field]
            for field in expected
            if field not in {"evaluations", "diagnostics"}
        ):
            diverged = True

    assert evaluation_differences
    assert len(advisor_agent.hardware_interoception.history) == 200
    assert len(advisor_agent.hardware_interoception.events) <= 50
    assert len(advisor_agent.hardware_interoception.personal.episodes) <= 50
    storage = advisor_agent.hardware_interoception.domain_personal.domains["storage"]
    assert len(storage["episodes"]) <= 50
    checkpoint = advisor_agent.hardware_interoception.to_checkpoint()
    assert "_storage_advisor_applied_cycle" not in checkpoint
    validate_hardware_interoception(checkpoint)


def test_conditional_write_advisor_differential_for_six_hundred_cycles_and_restarts(
    monkeypatch,
):
    from src.cognition import method_feedback

    source = DigitalBeing(name="ConditionalWriteAdvisorLongSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: _low_resources(),
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage",
        lambda: _storage(0.01),
    )
    monkeypatch.setattr(
        "config.simulation_config.SIM_CONFIG.HORMONAL_BEHAVIOR_MODE", "shadow"
    )

    original_prepare = method_feedback.prepare_candidates

    def prepare(agent, candidates):
        prepared, feedback = original_prepare(agent, candidates)
        prepared.insert(
            0,
            {
                "action": "web_search",
                "source": "conditional_advisor_probe",
                "strength": 0.08,
                "params": {"probe": True},
            },
        )
        return prepared, feedback

    monkeypatch.setattr(method_feedback, "prepare_candidates", prepare)
    pre_emotional_traces = {}
    current_trace_key = {"mode": None}
    original_emotional_bias = DigitalBeing._apply_emotional_bias

    def capture_pre_emotional(self, candidates):
        snapshot = deepcopy(candidates)
        for candidate in snapshot:
            params = candidate.get("params") or {}
            if params.get("continuation_of") is not None:
                params["continuation_of"] = "present"
        pre_emotional_traces.setdefault(current_trace_key["mode"], []).append(snapshot)
        return original_emotional_bias(self, candidates)

    monkeypatch.setattr(DigitalBeing, "_apply_emotional_bias", capture_pre_emotional)

    def seed_standalone_writes(agent):
        observer = agent.hardware_interoception
        for cycle in range(5):
            token = observer.begin_conditional_write(
                "web_search", managed=False, cycle=cycle
            )
            assert token is not None
            observer.record_conditional_save("immediate")
            observer.end_conditional_write(token)
        evidence = observer.conditional_writes.evidence("web_search", managed=False)
        assert evidence["sample_count"] == 5
        assert evidence["write_count"] == 5

    def run(mode):
        current_trace_key["mode"] = mode
        monkeypatch.setattr(
            "config.simulation_config.SIM_CONFIG.HARDWARE_CONDITIONAL_WRITE_MODE",
            mode,
        )
        random.seed(110029)
        np.random.seed(110029)
        agent = DigitalBeing(name=f"ConditionalWriteAdvisorLong_{mode}")
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)
        seed_standalone_writes(agent)
        trace = []
        eligible_cycles = []
        applied_cycles = []
        adjustment_history = {}
        restart_absence = 0
        for cycle in range(600):
            if cycle in {200, 400}:
                assert "conditional_writes" not in (
                    agent.hardware_interoception.to_checkpoint()
                )
                state = build_state_from_agent(agent)
                assert "hardware_conditional_write_behavior_last" not in state
                restored = DigitalBeing(name=agent.name)
                apply_state_to_agent(restored, state)
                assert not hasattr(restored, "hardware_conditional_write_behavior_last")
                assert not hasattr(
                    restored.hardware_interoception,
                    "_conditional_write_advisor_applied_cycle",
                )
                assert (
                    restored.hardware_interoception.conditional_writes.sample_count == 0
                )
                restart_absence += 1
                restored.web_searcher.toggle(False)
                agent = restored
                seed_standalone_writes(agent)
            report = agent.autonomous_tick()
            behavior = report["hardware_conditional_write_behavior"]
            assert agent.hardware_conditional_write_behavior_last == behavior
            assert agent.hardware_conditional_write_behavior_last is not behavior
            # Checkpoint сохраняет подтверждённый storage risk: после restart
            # eligibility возвращается с первым свежим наблюдением, а опыт записей
            # при этом заново накоплен только в runtime.
            expected_eligible = cycle >= 4
            assert behavior["eligible"] is expected_eligible, (
                cycle,
                behavior["reason"],
            )
            if expected_eligible:
                eligible_cycles.append(cycle)
            if behavior["active"] is True:
                applied_cycles.append(cycle)
                adjustment_history[cycle] = deepcopy(behavior["adjustments"])
            else:
                assert behavior["adjustments"] == []
            evaluations = report["arbitrator"].get("all_evaluations") or []
            input_indices = {entry["input_index"] for entry in evaluations}
            seen_indices = set()
            for entry in behavior["adjustments"]:
                assert agent._normalize_action(entry["action"]) == "web_search"
                assert entry["before_strength"] > 0.0
                assert entry["after_strength"] == pytest.approx(
                    entry["before_strength"] * entry["factor"]
                )
                assert entry["after_strength"] >= entry["before_strength"] * 0.75
                assert entry["input_index"] in input_indices
                assert entry["input_index"] not in seen_indices
                seen_indices.add(entry["input_index"])
            trace.append(_canonical_trace(agent, report))
            agent.cycle_count += 1
        pre_emotional = pre_emotional_traces[mode]
        assert len(pre_emotional) == len(trace) == 600
        for entry, candidates in zip(trace, pre_emotional):
            entry["pre_emotional_candidates"] = candidates
        return (
            agent,
            trace,
            eligible_cycles,
            applied_cycles,
            restart_absence,
            adjustment_history,
        )

    shadow_agent, shadow_trace, _, shadow_applied, shadow_restarts, _ = run("shadow")
    (
        advisor_agent,
        advisor_trace,
        expected_eligible,
        advisor_applied,
        advisor_restarts,
        adjustments,
    ) = run("advisor")

    assert shadow_agent.cycle_count == advisor_agent.cycle_count == 600
    assert shadow_restarts == advisor_restarts == 2
    assert shadow_applied == []
    assert advisor_applied == expected_eligible
    diverged = False
    evaluation_differences = []
    for cycle, (observed, expected) in enumerate(zip(advisor_trace, shadow_trace)):
        if observed["action"] != expected["action"] and not diverged:
            assert cycle in advisor_applied, cycle
        if not diverged and cycle not in advisor_applied:
            assert observed == expected, cycle
        if cycle in advisor_applied:
            observed_evaluations = {
                (row["input_index"], row["action"], row["source"]): row
                for row in observed["evaluations"]
            }
            expected_evaluations = {
                (row["input_index"], row["action"], row["source"]): row
                for row in expected["evaluations"]
            }
            if observed_evaluations != expected_evaluations:
                evaluation_differences.append(cycle)
            if not diverged:
                observed_candidates = {
                    (index, row["action"], row["source"]): row
                    for index, row in enumerate(observed["pre_emotional_candidates"])
                }
                expected_candidates = {
                    (index, row["action"], row["source"]): row
                    for index, row in enumerate(expected["pre_emotional_candidates"])
                }
                assert observed_candidates.keys() == expected_candidates.keys()
                assert observed_candidates.keys() == observed_evaluations.keys()
                cycle_adjustments = {
                    (row["input_index"], row["action"], row["source"]): row
                    for row in adjustments[cycle]
                }
                for key, observed_candidate in observed_candidates.items():
                    expected_candidate = expected_candidates[key]
                    if key in cycle_adjustments:
                        adjustment = cycle_adjustments[key]
                        assert observed_candidate["strength"] == pytest.approx(
                            adjustment["after_strength"]
                        )
                        assert observed_candidate["strength"] == pytest.approx(
                            expected_candidate["strength"] * adjustment["factor"]
                        )
                        assert {
                            field: value
                            for field, value in observed_candidate.items()
                            if field != "strength"
                        } == {
                            field: value
                            for field, value in expected_candidate.items()
                            if field != "strength"
                        }
                    else:
                        assert observed_candidate == expected_candidate, (cycle, key)
        if not diverged and any(
            observed[field] != expected[field]
            for field in expected
            if field not in {"evaluations", "diagnostics"}
        ):
            diverged = True

    assert evaluation_differences
    assert len(advisor_agent.hardware_interoception.history) == 200
    assert len(advisor_agent.hardware_interoception.conditional_writes.history) <= 50
    assert len(advisor_agent.hardware_interoception.conditional_writes.profiles) <= 7
    checkpoint = advisor_agent.hardware_interoception.to_checkpoint()
    assert "conditional_writes" not in checkpoint
    assert "_conditional_write_advisor_applied_cycle" not in checkpoint
    validate_hardware_interoception(checkpoint)


def test_action_experience_differential_for_six_hundred_cycles_and_restarts(
    monkeypatch,
):
    from src.core.hardware_action_experience import HardwareActionExperience

    source = DigitalBeing(name="ActionExperienceLongSource")
    source.web_searcher.toggle(False)
    initial = build_state_from_agent(source)
    current = {"resources": _low_resources()}
    monkeypatch.setattr(
        "src.core.watchdog.Watchdog.get_resource_status",
        lambda self: current["resources"],
    )
    monkeypatch.setattr(
        "src.core.hardware_interoception.read_data_storage", lambda: _storage(0.8)
    )

    def run(learning_enabled):
        if not learning_enabled:
            with monkeypatch.context() as disabled:
                disabled.setattr(
                    HardwareActionExperience,
                    "observe",
                    lambda self, *args, **kwargs: deepcopy(self.latest),
                )
                return _run(False)
        return _run(True)

    def _run(learning_enabled):
        random.seed(90029)
        np.random.seed(90029)
        agent = DigitalBeing(name=f"ActionExperienceLong_{learning_enabled}")
        apply_state_to_agent(agent, deepcopy(initial))
        agent.web_searcher.toggle(False)
        trace = []
        fresh_samples = 0
        for cycle in range(600):
            if cycle in {200, 400}:
                state = build_state_from_agent(agent)
                restored = DigitalBeing(name=agent.name)
                apply_state_to_agent(restored, state)
                if learning_enabled:
                    latest = restored.hardware_interoception.status()[
                        "action_experience"
                    ]["latest"]
                    assert latest["freshness"] == "stale"
                    assert latest["risk"] is None
                restored.web_searcher.toggle(False)
                agent = restored
            current["resources"] = (
                _high_resources() if (cycle // 20) % 2 == 0 else _low_resources()
            )
            report = agent.autonomous_tick()
            experience = report["hardware_interoception"]["action_experience"]
            if experience["freshness"] == "fresh":
                fresh_samples += 1
            trace.append(_canonical_trace(agent, report))
            agent.cycle_count += 1
        return agent, trace, fresh_samples

    baseline_agent, baseline_trace, baseline_samples = run(False)
    observed_agent, observed_trace, observed_samples = run(True)

    assert observed_trace == baseline_trace
    assert baseline_samples == 0
    assert observed_samples > 0
    assert baseline_agent.hardware_interoception.action_experience.profiles == {}
    assert observed_agent.hardware_interoception.action_experience.profiles
    assert len(observed_agent.hardware_interoception.history) == 200
    assert len(observed_agent.hardware_interoception.events) <= 50
    for (
        profile
    ) in observed_agent.hardware_interoception.action_experience.profiles.values():
        assert len(profile.episodes) <= 50
    validate_hardware_interoception(
        observed_agent.hardware_interoception.to_checkpoint()
    )
