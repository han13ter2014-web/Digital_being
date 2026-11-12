"""Регрессионные проверки проводки времени, метаобучения и SocialCell."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.cognition.active_inference import encode_observations
from src.cognition.experience_observers import (
    observe_action_intention,
    observe_action_outcome,
)
from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import (
    apply_state_to_agent,
    build_state_from_agent,
)
from src.core.continuous_time import ContinuousTimeEngine, EventType
from src.core.dialogue_acts import classify_user_text
from src.core.life_systems_bridge import (
    observe_user_message,
    record_action_intention,
    record_action_outcome,
    step_meta_learning,
    tick_continuous_time,
)
from src.core.meta_learning import MetaLearner


def test_time_tick_links_intention_prediction_and_actual_outcome():
    agent = SimpleNamespace()
    agent.continuous_time = ContinuousTimeEngine(agent)

    tick = tick_continuous_time(agent, 7)
    selection = {
        "action": "explore",
        "strength": 0.7,
        "simulation": {
            "prediction_id": "prediction-1",
            "status": "predicted",
            "action": "explore",
            "target": "память",
            "predicted_effect_probability": 0.75,
            "predicted_outcome": "вероятен эффект",
            "confidence": 0.6,
        },
    }
    entry = {
        "id": "intention-1",
        "action": "explore",
        "simulation": selection["simulation"],
    }
    record_action_intention(agent, selection, entry)

    assert tick["objective_time"] == 1.0
    assert len(agent.continuous_time.protension.active_intentions) == 1
    assert len(agent.continuous_time.protension.predictions) == 1

    outcome = SimpleNamespace(had_effect=True, reason="knowledge_changed")
    record_action_outcome(agent, entry, outcome)

    assert agent.continuous_time.protension.active_intentions == []
    assert agent.continuous_time.protension.predictions == []
    events = list(agent.continuous_time.retention.events)
    assert [event.event_type for event in events] == [
        EventType.TICK,
        EventType.ACTION,
        EventType.OBSERVATION,
    ]
    assert events[-1].causality == ["intention-1"]
    assert events[-1].payload["had_effect"] is True


def test_meta_learning_main_contour_observes_without_mutating_parameters():
    needs = {
        "curiosity": SimpleNamespace(current_level=0.8),
        "connection": SimpleNamespace(current_level=0.6),
    }
    agent = SimpleNamespace(
        motivation_system=SimpleNamespace(needs=needs),
        energy=100.0,
        intelligence=2,
        completed_goals=1,
        goals=[{}],
    )
    agent.meta_learner = MetaLearner(agent)
    agent.meta_learner.eval_window = 2
    config_before = agent.meta_learner._get_current_config()
    population_before = deepcopy(agent.meta_learner.population)

    first = step_meta_learning(agent)
    second = step_meta_learning(agent)

    assert first["mode"] == second["mode"] == "shadow"
    assert agent.meta_learner.cycle_counter == 2
    assert list(agent.meta_learner.fitness_history) == [
        first["current_fitness"],
        second["current_fitness"],
    ]
    assert agent.meta_learner._get_current_config() == config_before
    assert agent.meta_learner.population == population_before
    assert second["best_fitness"] is not None


def test_user_message_updates_social_model_used_by_active_inference():
    agent = DigitalBeing(name="SocialObservation")

    observe_user_message(
        agent,
        "Память сохраняет опыт",
        classify_user_text("Память сохраняет опыт"),
        3,
    )
    observations = encode_observations(agent)

    model = agent.social_cell.agent_models["user"]
    assert len(model.interaction_history) == 1
    assert model.interaction_history[0]["observation"]["action"] == "unknown"
    assert observations["social_model_precision"] == 1
    # Начальная predictability=0.5 даёт evasive, а не старый постоянный unknown.
    assert observations["social_predicted_reaction"] == 1
    social_events = [
        event
        for event in agent.continuous_time.retention.events
        if event.event_type == EventType.SOCIAL
    ]
    assert len(social_events) == 1


def test_checkpoint_preserves_meta_fitness_and_observed_social_history():
    agent = DigitalBeing(name="LifeSystemsCheckpoint")
    agent.meta_learner.fitness_history.extend([0.25, 0.5, 0.75])
    observe_user_message(agent, "привет", classify_user_text("привет"), 4)

    state = build_state_from_agent(agent)
    reborn = DigitalBeing(name="LifeSystemsCheckpointRestored")
    apply_state_to_agent(reborn, state)

    assert list(reborn.meta_learner.fitness_history) == [0.25, 0.5, 0.75]
    restored = reborn.social_cell.agent_models["user"]
    assert len(restored.interaction_history) == 1
    assert restored.interaction_history[0]["observation"]["action"] == "social"


def test_autonomous_tick_steps_time_and_shadow_meta_learning():
    agent = DigitalBeing(name="RegularLifeSystems")
    config_before = agent.meta_learner._get_current_config()

    report = agent.autonomous_tick()

    assert report["continuous_time"]["objective_time"] == 1.0
    assert report["meta_learning"]["mode"] == "shadow"
    assert agent.meta_learner.cycle_counter == 1
    assert len(agent.meta_learner.fitness_history) == 1
    assert agent.meta_learner._get_current_config() == config_before


def test_text_perception_enriches_real_stimulus_without_replacing_it():
    agent = DigitalBeing(name="SensoryObservation")
    stimulus = "Почему память развивается, когда опыт повторяется циклом?"

    returned = agent.perceive(stimulus)

    assert returned == stimulus
    report = agent._last_sensory_perception
    assert report["visual"]["depth"] > 0.3
    assert report["visual"]["patterns"] == ["цикл", "рост"]
    assert agent.continuous_time.retention.events[-1].event_type == EventType.STIMULUS


def test_metacognition_observes_outcome_and_survives_checkpoint():
    agent = DigitalBeing(name="MetaObservation")
    target = next(iter(agent.mental_models.concepts))
    selection = {
        "action": "explore",
        "params": {"topic": target},
        "simulation": {"predicted_effect_probability": 0.8},
    }
    entry = {"id": "meta-intention", "action": "explore"}
    observe_action_intention(agent, selection, entry)
    outcome = SimpleNamespace(
        had_effect=True,
        delta=SimpleNamespace(knowledge_entries=1),
    )
    observe_action_outcome(agent, entry, outcome)

    assert len(agent.meta_cognition.thought_traces) == 1
    assert agent.meta_cognition.thought_traces[0].is_useful is True
    assert agent.meta_cognition.thought_traces[0].produced_insight is True
    assert target in agent.meta_cognition.knowledge_awareness.known_concepts

    state = build_state_from_agent(agent)
    reborn = DigitalBeing(name="MetaObservationRestored")
    apply_state_to_agent(reborn, state)

    trace = reborn.meta_cognition.thought_traces[0]
    assert trace.resulting_actions == ["explore"]
    assert trace.is_useful is True
    assert reborn.meta_cognition.knowledge_awareness.understanding_level[target] > 0.0


@pytest.mark.asyncio
async def test_runner_records_early_social_route_once():
    from src.core.agent_runner import AgentRunner

    agent = DigitalBeing(name="RunnerSocialObservation")
    runner = AgentRunner.__new__(AgentRunner)
    runner.name = agent.name
    runner.agent = agent
    runner.bus = SimpleNamespace(publish=AsyncMock(), publish_sync=Mock())

    await runner._on_user_message(SimpleNamespace(data={"text": "привет"}))

    model = agent.social_cell.agent_models["user"]
    assert len(model.interaction_history) == 1
    assert model.interaction_history[0]["observation"]["action"] == "social"
