"""Жизненный путь create_agent → act → save → create_agent, не ручной импорт памяти."""

from unittest.mock import patch

import pytest

from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.cognition.action_expectations import ActionExpectations
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.event_bus import EventBus


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "life"))
    return setup_environment(chdir=False)


def experienced_agent(env):
    first, _ = create_agent(env, "Continuity", new=True)
    first.energy = 20
    first.cycle_count = 41
    with patch.object(first, "_recover_energy", return_value=0.0):
        first.act("rest")
    claim = first.action_expectations.last_trial["claim"]
    return first, claim


def test_normal_restart_remembers_experience_and_next_expectation(env):
    first, claim = experienced_agent(env)
    original = first.mental_models.concepts[claim].to_storage_dict()
    fatigue = first.interoception.state.fatigue
    runner = AgentRunner(first, EventBus(), name="RestartTest")
    assert runner.save_now()
    second, report = create_agent(env, "Continuity")
    assert report["source"] == "checkpoint"
    assert second.cycle_count == 41
    assert second.energy == 20
    assert second.interoception.state.fatigue == pytest.approx(fatigue)
    assert second.mental_models.concepts[claim].to_storage_dict() == original
    assert second.sleep_cycle.mental_models is second.mental_models
    second.act("rest")
    assert second.action_expectations.last_trial["expected_direction"] == -1
    assert not second.action_expectations.last_trial["prediction_matched"]


def test_checkpoint_memory_wins_over_newer_separate_export(env):
    first, claim = experienced_agent(env)
    original = first.mental_models.concepts[claim].to_storage_dict()
    first.save_state(force=True)
    first.act("rest")
    first.save_mental_models()
    second, _ = create_agent(env, "Continuity")
    assert second.mental_models.concepts[claim].to_storage_dict() == original
    assert second.energy == 20


@pytest.mark.parametrize("options", [{"new": True}, {"restore": False}])
def test_explicit_new_life_does_not_inherit_previous_experience(env, options):
    first, claim = experienced_agent(env)
    first.save_state(force=True)
    first.save_mental_models()
    second, report = create_agent(env, "Continuity", **options)
    assert report["source"] == "new"
    assert claim not in second.mental_models.concepts
    assert second.cycle_count == 0


def test_another_name_cannot_load_this_life(env):
    first, claim = experienced_agent(env)
    first.save_state(force=True)
    first.save_mental_models()
    second, report = create_agent(env, "OtherLife")
    assert report["source"] == "new"
    assert claim not in second.mental_models.concepts


def test_unfinished_attempt_does_not_become_observation(env):
    first, claim = experienced_agent(env)
    pending = first.action_expectations.begin(first.mental_models, "rest", 20, 200)
    count = len(first.mental_models.concepts[claim].experiences)
    first.save_state(force=True)
    second, _ = create_agent(env, "Continuity")
    assert len(second.mental_models.concepts[claim].experiences) == count
    assert getattr(second, "action_expectations", None) is None
    # Повторная загрузка в существующий объект также сбрасывает pending.
    state = build_state_from_agent(first)
    apply_state_to_agent(first, state)
    assert first.action_expectations.finish(first.mental_models, pending, 32) is None
    second.act("rest")
    assert second.action_expectations.last_trial["trial_id"] != pending.trial_id
    assert len(second.mental_models.concepts[claim].experiences) == count + 1


def test_legacy_checkpoint_does_not_borrow_unrelated_export(env):
    first, claim = experienced_agent(env)
    first.save_mental_models()
    state = build_state_from_agent(first)
    del state["mental_models"]
    from src.core.checkpoint_serializer import CheckpointSerializer

    CheckpointSerializer(checkpoint_dir=first.checkpoint_dir).save(state, first.name, first.cycle_count)
    second, report = create_agent(env, "Continuity")
    assert report["source"] == "checkpoint"
    assert second.cycle_count == 41
    assert claim not in second.mental_models.concepts


def test_invalid_memory_section_is_not_partially_applied(env):
    first, claim = experienced_agent(env)
    state = build_state_from_agent(first)
    state["mental_models"]["concepts"]["сломано"] = {"created_at": "not-a-date"}
    original = first.mental_models.to_storage_dict()
    with pytest.raises(ValueError):
        apply_state_to_agent(first, state)
    assert first.mental_models.to_storage_dict() == original


def test_shutdown_save_is_not_skipped_between_checkpoint_intervals(env):
    first, claim = experienced_agent(env)
    first._last_saved_intelligence = first.intelligence
    from config.simulation_config import SIM_CONFIG

    first.cycle_count = SIM_CONFIG.CHECKPOINT_INTERVAL + 1
    runner = AgentRunner(first, EventBus(), name="ForcedSaveTest")
    assert runner.save_now()
    second, report = create_agent(env, "Continuity")
    assert report["source"] == "checkpoint"
    assert second.cycle_count == first.cycle_count
    assert claim in second.mental_models.concepts


def test_failed_restore_is_not_reported_as_checkpoint(env, monkeypatch):
    first, _ = experienced_agent(env)
    first.save_state(force=True)
    from src.core.agent import DigitalBeing

    monkeypatch.setattr(DigitalBeing, "load_state", lambda self, filename: False)
    _, report = create_agent(env, "Continuity")
    assert report["source"] != "checkpoint"
