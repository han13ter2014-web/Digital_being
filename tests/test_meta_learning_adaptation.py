"""Регрессии адаптации собственного темпа к ресурсам среды."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.continuous_time import ContinuousTimeEngine
from src.core.meta_learning import MetaLearner


def make_learner():
    needs = {"curiosity": SimpleNamespace(current_level=0.8)}
    agent = SimpleNamespace(
        motivation_system=SimpleNamespace(needs=needs),
        energy=100.0,
        intelligence=2,
        completed_goals=1,
        goals=[{}],
        continuous_time=None,
    )
    agent.continuous_time = ContinuousTimeEngine(agent)
    agent.meta_learner = MetaLearner(agent)
    agent.meta_learner.eval_window = 2
    agent.meta_learner.resource_recovery_cycles = 3
    return agent


def pressure(score):
    return {"available": True, "score": score, "source": "test"}


def test_watchdog_separates_host_pressure_from_process_rss(monkeypatch):
    from src.core.watchdog import Watchdog

    process = SimpleNamespace(
        memory_info=lambda: SimpleNamespace(rss=100 * 1024 * 1024),
        cpu_percent=lambda interval=None: 10.0,
    )
    fake_psutil = SimpleNamespace(
        Process=lambda pid: process,
        cpu_percent=lambda interval=None: 92.0,
        virtual_memory=lambda: SimpleNamespace(percent=88.0),
    )
    monkeypatch.setattr("src.core.watchdog._HAS_PSUTIL", True)
    monkeypatch.setattr("src.core.watchdog.psutil", fake_psutil)
    watchdog = Watchdog(max_rss_mb=200.0)

    status = watchdog.get_resource_status()

    assert status["available"] is True
    assert status["host_cpu_percent"] == 92.0
    assert status["host_memory_percent"] == 88.0
    assert status["process_rss_mb"] == 100.0
    assert status["score"] == pytest.approx(0.92)


def test_watchdog_reuses_process_handle_between_cpu_measurements(monkeypatch):
    from src.core.watchdog import Watchdog

    process = SimpleNamespace(cpu_percent=lambda interval=None: 10.0)
    calls = []
    fake_psutil = SimpleNamespace(
        Process=lambda pid: calls.append(pid) or process,
    )
    monkeypatch.setattr("src.core.watchdog._HAS_PSUTIL", True)
    monkeypatch.setattr("src.core.watchdog.psutil", fake_psutil)
    watchdog = Watchdog()

    watchdog.get_cpu_percent()
    watchdog.get_cpu_percent()

    assert len(calls) == 1


def test_unused_parameters_are_replaced_by_real_cycle_budget():
    learner = make_learner().meta_learner

    assert {
        "need_coupling_strength",
        "energy_cost_base",
        "rest_recovery_rate",
    }.isdisjoint(learner.hyperparams)
    assert learner.hyperparams["cycle_interval_scale"].value == 1.0


def test_host_pressure_reduces_life_tempo_without_random_evolution():
    agent = make_learner()
    learner = agent.meta_learner
    population_before = deepcopy(learner.population)

    learner.step(0.5, resource_status=pressure(0.9))

    assert learner.hyperparams["cycle_interval_scale"].value == 2.0
    assert learner.resource_adaptation_history[-1]["response"] == "conserve"
    assert learner.population == population_before

    learner.step(0.4, resource_status=pressure(0.95))
    assert learner.hyperparams["cycle_interval_scale"].value == 4.0


def test_external_pressure_does_not_rollback_when_host_stays_busy():
    learner = make_learner().meta_learner
    learner.step(0.5, resource_status=pressure(0.9))
    learner.step(0.4, resource_status=pressure(0.9))
    learner.step(0.3, resource_status=pressure(0.9))

    assert learner.hyperparams["cycle_interval_scale"].value == 8.0
    assert learner.resource_low_pressure_cycles == 0


def test_recovery_requires_sustained_low_pressure_and_is_gradual():
    learner = make_learner().meta_learner
    learner.step(0.5, resource_status=pressure(0.9))
    learner.step(0.5, resource_status=pressure(0.9))
    assert learner.hyperparams["cycle_interval_scale"].value == 4.0

    learner.step(0.5, resource_status=pressure(0.4))
    learner.step(0.5, resource_status=pressure(0.4))
    assert learner.hyperparams["cycle_interval_scale"].value == 4.0

    learner.step(0.5, resource_status=pressure(0.4))
    assert learner.hyperparams["cycle_interval_scale"].value == 2.0
    assert learner.resource_adaptation_history[-1]["response"] == "recover"

    learner.step(0.5, resource_status=pressure(0.7))
    assert learner.hyperparams["cycle_interval_scale"].value == 2.0
    assert learner.resource_low_pressure_cycles == 0


def test_unavailable_metrics_never_fake_safe_or_dangerous_pressure():
    learner = make_learner().meta_learner

    learner.step(0.5, resource_status={"available": False})
    learner.step(0.5, resource_status=None)

    assert learner.hyperparams["cycle_interval_scale"].value == 1.0
    assert list(learner.resource_adaptation_history) == []


def test_resource_mode_and_recovery_progress_survive_checkpoint_restart():
    agent = DigitalBeing(name="ResourceAdaptationCheckpoint")
    learner = agent.meta_learner
    learner.resource_recovery_cycles = 3
    learner.step(0.5, resource_status=pressure(0.9))
    learner.step(0.5, resource_status=pressure(0.4))

    state = build_state_from_agent(agent)
    reborn = DigitalBeing(name="ResourceAdaptationCheckpointRestored")
    apply_state_to_agent(reborn, state)

    restored = reborn.meta_learner
    assert restored.hyperparams["cycle_interval_scale"].value == 2.0
    assert restored.resource_recovery_cycles == 3
    assert restored.resource_low_pressure_cycles == 1
    assert restored.resource_adaptation_history[-1]["response"] == "conserve"
