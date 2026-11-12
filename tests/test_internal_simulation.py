"""InternalSimulator связан с WorldDelta без второго классификатора успеха."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from config.simulation_config import SIM_CONFIG
from src.cognition.intention_history import begin_intention, restore_history
from src.cognition.internal_simulator import InternalSimulator
from src.cognition.simulation_bridge import (
    cancel_selected_prediction,
    learn_from_selected_action,
    predict_candidates,
)
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.loop_closure import ActionOutcome
from src.core.subsystems.decision_arbitrator import DecisionArbitrator
from src.core.world_delta import WorldDelta


class FakeAgent:
    def __init__(self):
        self.internal_simulator = InternalSimulator("test")
        self.energy = 100.0
        self.web_searcher = None
        self.cycle_count = 0
        self._intention_history = []
        self.mental_models = type("MentalModels", (), {"concepts": {}})()

    @staticmethod
    def _normalize_action(action):
        return {
            "exploration": "explore",
            "think_decompose": "decomposition",
            "synthesize": "synthesis",
        }.get(str(action or ""), str(action or ""))


def context(action="explore", target="память", web_enabled=False):
    return {
        "action": action,
        "target": target,
        "web_enabled": web_enabled,
        "energy_band": "normal",
    }


def seed(
    simulator,
    *,
    action="explore",
    target="память",
    outcomes=(True, True, True),
    web_enabled=False,
):
    for index, success in enumerate(outcomes):
        simulator.learn_from_outcome(
            action,
            context(action, target, web_enabled),
            f"исход {index}",
            success,
            actual_delta={"knowledge_entries": 1 if success else 0},
        )


def outcome(*, action="explore", target="память", delta=None, reason=""):
    return ActionOutcome(
        action=action,
        topic=target,
        delta=delta if delta is not None else WorldDelta(knowledge_entries=1),
        reason=reason,
    )


def prediction_for(agent, action="explore", target="память"):
    candidates, diagnostics = predict_candidates(
        agent,
        [
            {
                "action": action,
                "source": "test",
                "strength": 0.7,
                "params": {"topic": target},
            }
        ],
        mode="shadow",
    )
    assert diagnostics["errors"] == []
    return candidates[0]


def test_cold_start_is_unavailable_not_failure():
    agent = FakeAgent()
    selected = prediction_for(agent)
    prediction = selected["simulation"]
    assert prediction["status"] == "unavailable"
    assert prediction["predicted_effect_probability"] is None
    assert prediction["confidence"] == 0.0
    assert prediction["sample_size"] == 0
    assert prediction["adjustment"] == 0.0
    assert selected["strength"] == 0.7
    assert agent.internal_simulator.memory.real_events == []


def test_decomposition_without_explicit_target_uses_planned_target():
    agent = FakeAgent()
    seed(agent.internal_simulator, action="decomposition")
    calls = []

    def pick_target(*, remember):
        calls.append(remember)
        return "память"

    agent._pick_decomposable_target = pick_target
    candidates, diagnostics = predict_candidates(
        agent,
        [{"action": "decomposition", "source": "test", "strength": 0.7, "params": {}}],
        mode="shadow",
    )

    prediction = candidates[0]["simulation"]
    assert diagnostics["errors"] == []
    assert prediction["status"] == "predicted"
    assert prediction["target"] == "память"
    assert prediction["predicted_effect_probability"] == 1.0
    assert calls == [False]


def test_experience_is_strictly_scoped_by_action_and_target():
    simulator = InternalSimulator()
    seed(simulator, outcomes=(True, False, True, True))

    same = simulator.simulate_outcome("explore", {}, context())
    other_action = simulator.simulate_outcome("synthesis", {}, context("synthesis"))
    other_target = simulator.simulate_outcome("explore", {}, context(target="другое"))

    assert same.status == "predicted"
    assert same.predicted_effect_probability == 0.75
    assert same.sample_size == 4
    assert other_action.status == "unavailable"
    assert other_target.status == "unavailable"


def test_web_search_experience_respects_network_state():
    simulator = InternalSimulator()
    seed(simulator, action="web_search", web_enabled=True)
    enabled = simulator.simulate_outcome(
        "web_search", {}, context("web_search", web_enabled=True)
    )
    disabled = simulator.simulate_outcome(
        "web_search", {}, context("web_search", web_enabled=False)
    )
    assert enabled.status == "predicted"
    assert disabled.status == "unavailable"


def test_selected_prediction_resolves_once_against_had_effect_and_signed_delta():
    agent = FakeAgent()
    seed(agent.internal_simulator, outcomes=(True, True, True))
    selected = prediction_for(agent)
    intention = begin_intention(agent, selected)
    actual = outcome(delta=WorldDelta(knowledge_entries=-2))

    report = learn_from_selected_action(agent, selected, intention, actual)

    assert report["had_effect"] is True
    assert report["predicted_effect_probability"] == 1.0
    assert report["absolute_error"] == 0.0
    assert report["prediction_matched"] is True
    assert report["actual_delta"]["knowledge_entries"] == -2
    assert intention["simulation"]["status"] == "resolved"
    assert intention["simulation"]["had_effect"] is True
    assert len(agent.internal_simulator.prediction_accuracy_history) == 1

    duplicate = learn_from_selected_action(agent, selected, intention, actual)
    assert duplicate["real_event_stored"] is False
    assert len(agent.internal_simulator.memory.real_events) == 4
    assert len(agent.internal_simulator.prediction_accuracy_history) == 1


def test_empty_delta_is_real_executed_failure_not_text_inference():
    agent = FakeAgent()
    seed(agent.internal_simulator)
    selected = prediction_for(agent)
    intention = begin_intention(agent, selected)
    report = learn_from_selected_action(
        agent, selected, intention, outcome(delta=WorldDelta())
    )
    assert report["had_effect"] is False
    assert report["prediction_matched"] is False
    assert report["absolute_error"] == 1.0
    assert agent.internal_simulator.memory.real_events[-1]["success"] is False


def test_unselected_prediction_does_not_receive_outcome():
    simulator = InternalSimulator()
    seed(simulator)
    selected = simulator.simulate_outcome("explore", {}, context())
    unselected = simulator.simulate_outcome("explore", {}, context())
    simulator.learn_from_outcome(
        "explore",
        context(),
        "факт",
        True,
        prediction_id=selected.prediction_id,
    )
    assert selected.status == "predicted"  # объект результата не мутируется
    stored = {
        event["prediction_id"]: event for event in simulator.memory.simulated_events
    }
    assert stored[selected.prediction_id]["status"] == "resolved"
    assert stored[unselected.prediction_id]["status"] == "predicted"
    assert len(simulator.prediction_accuracy_history) == 1


def test_denial_and_execution_error_cancel_without_real_experience():
    agent = FakeAgent()
    seed(agent.internal_simulator)
    selected = prediction_for(agent)
    intention = begin_intention(agent, selected)
    before = len(agent.internal_simulator.memory.real_events)

    denied = learn_from_selected_action(
        agent,
        selected,
        intention,
        outcome(delta=WorldDelta(), reason="denied:too_tired"),
    )
    assert denied is None
    assert intention["simulation"]["status"] == "cancelled"
    assert len(agent.internal_simulator.memory.real_events) == before
    assert agent.internal_simulator.prediction_accuracy_history == []

    selected = prediction_for(agent)
    intention = begin_intention(agent, selected)
    cancel_selected_prediction(agent, intention, "execution_error")
    assert intention["simulation"]["status"] == "cancelled"
    assert len(agent.internal_simulator.memory.real_events) == before


def test_simulator_error_produces_neutral_prediction_and_preserves_choice_input():
    agent = FakeAgent()
    original = [
        {
            "action": "explore",
            "source": "test",
            "strength": 0.7,
            "params": {"topic": "память"},
        }
    ]
    with patch.object(
        agent.internal_simulator, "simulate_outcome", side_effect=RuntimeError("broken")
    ):
        candidates, diagnostics = predict_candidates(agent, original, mode="shadow")
    assert candidates[0]["simulation"]["status"] == "unavailable"
    assert candidates[0]["simulation"]["confidence"] == 0.0
    assert diagnostics["errors"] == ["broken"]
    assert "simulation" not in original[0]


def test_off_mode_creates_neither_predictions_nor_learning(monkeypatch):
    agent = FakeAgent()
    monkeypatch.setattr(SIM_CONFIG, "INTERNAL_SIMULATION_MODE", "off")
    candidates, diagnostics = predict_candidates(
        agent, [{"action": "explore", "strength": 0.7, "params": {}}], mode="off"
    )
    assert diagnostics["mode"] == "off"
    assert "simulation" not in candidates[0]
    intention = {"id": "off", "target": "память"}
    assert (
        learn_from_selected_action(agent, {"action": "explore"}, intention, outcome())
        is None
    )
    assert agent.internal_simulator.memory.real_events == []


def verdict(kind="proceed", score=0.5):
    return {
        "verdict": kind,
        "score": score,
        "confidence": 0.8,
        "reasoning": kind,
        "voices": {},
    }


def simulation(probability, confidence=0.5):
    return {
        "prediction_id": "p",
        "schema_version": 1,
        "action": "explore",
        "target": "память",
        "context_key": "k",
        "status": "predicted",
        "predicted_effect_probability": probability,
        "confidence": confidence,
        "sample_size": 5,
        "predicted_outcome": "прогноз",
        "adjustment": 0.0,
    }


@pytest.mark.parametrize("mode", ["off", "shadow"])
def test_shadow_and_off_preserve_base_scores(mode):
    arbiter = DecisionArbitrator()
    with patch.object(arbiter, "arbitrate", return_value=verdict()):
        result = arbiter.choose_action(
            [
                {
                    "action": "explore",
                    "source": "test",
                    "strength": 0.8,
                    "simulation": simulation(1.0),
                }
            ],
            {"simulation_mode": mode, "simulation_max_adjustment": 0.1},
        )
    evaluation = result["all_evaluations"][0]
    assert evaluation["base_combined_score"] == pytest.approx(0.62)
    assert evaluation["combined_score"] == pytest.approx(0.62)
    assert evaluation["simulation_adjustment"] == 0.0


def test_advisor_adjustment_is_bounded_and_diagnosed_separately():
    arbiter = DecisionArbitrator()
    with patch.object(arbiter, "arbitrate", return_value=verdict()):
        result = arbiter.choose_action(
            [
                {
                    "action": "explore",
                    "source": "test",
                    "strength": 0.8,
                    "simulation": simulation(0.0, 1.0),
                }
            ],
            {"simulation_mode": "advisor", "simulation_max_adjustment": 99.0},
        )
    evaluation = result["all_evaluations"][0]
    assert evaluation["base_combined_score"] == pytest.approx(0.62)
    assert evaluation["simulation_adjustment"] == pytest.approx(-0.1)
    assert evaluation["combined_score"] == pytest.approx(0.52)
    assert result["simulation"]["adjustment"] == pytest.approx(-0.1)


def test_advisor_does_not_override_stop_or_unknown_prediction():
    arbiter = DecisionArbitrator()
    unknown = simulation(1.0)
    unknown.update(
        status="unavailable", predicted_effect_probability=None, confidence=0.0
    )
    with patch.object(
        arbiter, "arbitrate", side_effect=[verdict("stop", 0.9), verdict()]
    ):
        result = arbiter.choose_action(
            [
                {
                    "action": "explore",
                    "source": "test",
                    "strength": 1.0,
                    "simulation": simulation(1.0),
                },
                {
                    "action": "synthesis",
                    "source": "test",
                    "strength": 0.2,
                    "simulation": unknown,
                },
            ],
            {"simulation_mode": "advisor", "simulation_max_adjustment": 0.1},
        )
    assert result["action"] == "synthesis"
    assert result["all_evaluations"][-1]["simulation_adjustment"] == 0.0


def test_checkpoint_roundtrip_preserves_experience_and_cancels_pending():
    agent = DigitalBeing(name="SimulationCheckpoint")
    seed(agent.internal_simulator)
    resolved = agent.internal_simulator.simulate_outcome("explore", {}, context())
    agent.internal_simulator.resolve_prediction(
        resolved.prediction_id,
        actual_outcome="факт",
        success=True,
        actual_delta={"knowledge_entries": 1},
        intention_id="done",
    )
    pending = agent.internal_simulator.simulate_outcome("explore", {}, context())

    state = build_state_from_agent(agent)
    reborn = DigitalBeing(name="SimulationCheckpoint")
    apply_state_to_agent(reborn, state)

    assert len(reborn.internal_simulator.memory.real_events) == 3
    assert len(reborn.internal_simulator.prediction_accuracy_history) == 1
    stored = {
        event["prediction_id"]: event
        for event in reborn.internal_simulator.memory.simulated_events
    }
    assert stored[resolved.prediction_id]["status"] == "resolved"
    assert stored[pending.prediction_id]["status"] == "cancelled"
    assert stored[pending.prediction_id]["cancel_reason"] == "interrupted"


def test_old_checkpoint_resets_simulator_and_corruption_is_atomic():
    agent = DigitalBeing(name="SimulationLegacy")
    seed(agent.internal_simulator)
    state = build_state_from_agent(agent)
    state.pop("internal_simulation")
    apply_state_to_agent(agent, state)
    assert agent.internal_simulator.memory.real_events == []

    seed(agent.internal_simulator)
    state = build_state_from_agent(agent)
    state["energy"] = 1.0
    state["internal_simulation"]["real_events"] = "broken"
    energy_before = agent.energy
    real_before = deepcopy(agent.internal_simulator.memory.real_events)
    with pytest.raises(ValueError, match="internal_simulation"):
        apply_state_to_agent(agent, state)
    assert agent.energy == energy_before
    assert agent.internal_simulator.memory.real_events == real_before


def test_unfinished_intention_prediction_is_cancelled_on_restore():
    agent = FakeAgent()
    seed(agent.internal_simulator)
    selected = prediction_for(agent)
    intention = begin_intention(agent, selected)
    restored = restore_history([intention])
    assert restored[0]["status"] == "interrupted"
    assert restored[0]["simulation"]["status"] == "cancelled"
    assert restored[0]["simulation"]["cancel_reason"] == "interrupted"
