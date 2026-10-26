"""Один согласованный снимок: опыт, отношения, воля, self и обучение."""

import numpy as np
import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.cognition.inference_continuity import capture_inference
from src.core.personal_continuity import capture_personal_state
from src.core.subsystem_base import PluginRegistry


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_personal_life_continues_after_one_complete_snapshot(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "life"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "WholePersonalLife", new=True)
        first.cycle_count = 100
        first.add_value("Забота", "значимое взаимодействие")
        first.attachment.record_interaction("user", was_helpful=True)
        first.defend_refusal("тема", "не хочу")
        identity = first.soul.get("self")
        identity.core_identity = "Я сохраняю прожитый опыт"
        identity.history = ["изменённое самоописание"]
        first.ask_user("как работает память", source="self", max_explorations=4)
        stimulus = first._consume_open_question()
        first._record_open_question_exploration(stimulus, "Не знаю, буду проверять дальше")
        next_question = first._consume_open_question()
        engine = first.active_inference
        action = next(iter(engine.model.actions))
        key = next(iter(engine.model.actions[action].transitions))
        for _ in range(32):
            engine.record_experience(action, {}, {}, 0.2)
        engine.learn_from_experience()
        original_person = capture_personal_state(first)
        original_inference = capture_inference(engine)
        original_memory = first.mental_models.to_storage_dict()
        questions = [dict(q, explorations=[dict(e) for e in q["explorations"]]) for q in first._open_questions]
        first.save_state(force=True)
        PluginRegistry.reset_global()
        second, report = create_agent(env, "WholePersonalLife")
        assert report["source"] == "checkpoint"
        assert second.cycle_count == 100
        assert capture_personal_state(second) == original_person
        assert capture_inference(second.active_inference) == original_inference
        assert second.mental_models.to_storage_dict() == original_memory
        assert second._open_questions == questions
        assert second._consume_open_question() == next_question
        assert second.decision_arbitrator._systems["self"] is second.soul.get("self")
        assert second.value_evolution.registry is second.will_registry
        assert not second.value_evolution.can_evolve(100)
        # Продолжение не повторяет первую попытку и не начинает обучение с нуля.
        learned = second.active_inference.model.actions[action].transitions[key].copy()
        second.active_inference.learn_from_experience()
        assert not np.array_equal(learned, second.active_inference.model.actions[action].transitions[key])
        second._record_open_question_exploration(next_question, "Не знаю, другая проверка")
        assert "попытка 3/4" in second._consume_open_question()
        second.cycle_count = 150
        second.add_value("Терпение", "продолжение опыта")
        assert second.will_registry.get_stats()["by_type"]["value_changes"] == 2
    finally:
        PluginRegistry.reset_global()
