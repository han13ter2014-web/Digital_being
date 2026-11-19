"""Аппаратная интероцепция: свежесть, доказательства и строгий shadow-режим."""

from copy import deepcopy
from types import SimpleNamespace
import random

import numpy as np
import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.hardware_behavior import apply_own_load_advice, own_load_advice
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
    assert current["schema_version"] == 4

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
    assert migrated_state["schema_version"] == 4
    validate_hardware_interoception(migrated_state)
