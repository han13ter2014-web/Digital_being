"""Обученные ожидания действий сохраняются, обучение продолжается после запуска."""

import numpy as np
import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.cognition.inference_continuity import capture_inference
from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent
from src.core.subsystem_base import PluginRegistry


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_learned_transitions_survive_normal_startup(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "InferenceLife", new=True)
        engine = first.active_inference
        action = next(iter(engine.model.actions))
        key = next(iter(engine.model.actions[action].transitions))
        before = engine.model.actions[action].transitions[key].copy()
        for _ in range(32):
            engine.record_experience(action, {}, {}, 0.2)
        engine.learn_from_experience()
        learned = engine.model.actions[action].transitions[key].copy()
        assert not np.array_equal(before, learned)
        engine.temperature = 0.61
        original = capture_inference(engine)
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, _ = create_agent(env, "InferenceLife")
        restored = second.active_inference
        assert capture_inference(restored) == original
        assert restored.agent is second
        assert restored.planner.model is restored.model
        restored.learn_from_experience()
        assert not np.array_equal(restored.model.actions[action].transitions[key], learned)
    finally:
        PluginRegistry.reset_global()


def test_unmodeled_action_experience_is_preserved_and_skipped_by_learning():
    from src.core.agent import DigitalBeing
    from src.cognition.inference_continuity import restore_inference

    agent = DigitalBeing(name="UnmodeledExperience")
    engine = agent.active_inference
    for _ in range(32):
        engine.record_experience("communicate", {}, {}, 0.2)
    assert "communicate" not in engine.model.actions
    saved = capture_inference(engine)
    restore_inference(engine, saved)
    assert capture_inference(engine) == saved
    transitions = capture_inference(engine)["actions"]
    engine.learn_from_experience()
    assert capture_inference(engine)["actions"] == transitions
    assert len(engine.experience_buffer) == 32


def test_invalid_shape_rejected_before_any_agent_change():
    from src.core.agent import DigitalBeing

    agent = DigitalBeing(name="InvalidInference")
    state = build_state_from_agent(agent)
    before = capture_inference(agent.active_inference)
    name = next(iter(state["active_inference"]["states"]))
    state["active_inference"]["states"][name]["posterior"] = [float("nan")]
    with pytest.raises(ValueError, match="active_inference"):
        apply_state_to_agent(agent, state)
    assert capture_inference(agent.active_inference) == before
