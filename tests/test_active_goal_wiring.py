"""Активная когнитивная цель связана с выбором, графом и прогрессом."""

from unittest.mock import patch

import pytest

from src.cognition.activity_goals import active_goal_candidate, attach_activity
from src.core.agent import DigitalBeing
from src.core.subsystems.goal_manager import GoalSubsystem
from src.core.world_delta import WorldDelta


@pytest.fixture()
def agent():
    instance = DigitalBeing(name="ActiveGoalWiring")
    searcher = getattr(instance, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)
    return instance


def make_mapping_goal(agent):
    goal_id = agent.set_goal("Картирование: curiosity", activate=True)
    attach_activity(
        agent,
        goal_id,
        {
            "source": "drive",
            "drive": "exploration",
            "action_hint": "explore",
            "type": "mapping",
            "priority": 0.3,
        },
    )
    return agent.active_goal


def link(models, left, right, *, reverse=True):
    models.concepts[left].connections[right] = 0.6
    if reverse:
        models.concepts[right].connections[left] = 0.6


def make_graph(agent, *names):
    models = agent.mental_models
    models.concepts.clear()
    for name in names:
        # Общий контекст сам создаёт доказанную связь; здесь нужны только
        # рёбра, которые тест задаёт явно.
        models.encounter_concept(name, f"context_{name}", "test_observation", 0.0)
    return models


@pytest.mark.parametrize("reverse", [True, False])
def test_related_concept_counts_for_goal_in_either_graph_direction(agent, reverse):
    goal = make_mapping_goal(agent)
    models = make_graph(agent, "curiosity", "исследование")
    link(models, "curiosity", "исследование", reverse=reverse)

    result = agent._check_goal_progress(
        "исследование", answered=True, evidence=WorldDelta(concepts=1)
    )

    assert result["pct"] == 20
    assert agent._goal_progress[goal["id"]]["matched_concepts"] == {"исследование"}


def test_unrelated_concept_still_does_not_count(agent):
    goal = make_mapping_goal(agent)
    models = make_graph(agent, "curiosity", "исследование", "кухня")
    link(models, "curiosity", "исследование")

    result = agent._check_goal_progress(
        "кухня", answered=True, evidence=WorldDelta(concepts=1)
    )

    assert result["pct"] == 0
    assert agent._goal_progress[goal["id"]]["matched_concepts"] == set()


def test_mapping_candidate_walks_to_unmatched_related_concepts(agent):
    goal = make_mapping_goal(agent)
    models = make_graph(agent, "curiosity", "исследование", "наблюдение")
    link(models, "curiosity", "исследование")
    link(models, "curiosity", "наблюдение")
    agent._goal_progress[goal["id"]]["matched_concepts"] = {"curiosity"}

    first = active_goal_candidate(agent)
    assert first["source"] == "active_goal"
    assert first["action"] == "explore"
    assert first["params"]["concept"] in {"исследование", "наблюдение"}

    agent._goal_progress[goal["id"]]["matched_concepts"].add(first["params"]["concept"])
    second = active_goal_candidate(agent)
    assert second["params"]["concept"] != first["params"]["concept"]
    assert second["params"]["concept"] in {"исследование", "наблюдение"}


def test_autonomous_tick_executes_active_goal_through_existing_arbiter(agent):
    goal = make_mapping_goal(agent)
    models = make_graph(agent, "curiosity", "исследование")
    link(models, "curiosity", "исследование")

    def choose_active_goal(candidates, context):
        selected = next(c for c in candidates if c.get("source") == "active_goal")
        return {**selected, "verdict": "proceed", "reasoning": "regression"}

    with patch.object(
        agent.decision_arbitrator, "choose_action", side_effect=choose_active_goal
    ):
        report = agent.autonomous_tick()

    assert report["executed_intention"]["source"] == "active_goal"
    assert agent._last_action_outcome.action == "explore"
    assert agent._last_action_outcome.topic == "исследование"
    assert agent._last_action_outcome.had_effect
    assert agent._goal_progress[goal["id"]]["percentage"] == 20


def test_ingest_deduplicates_same_work_but_preserves_another_method(agent):
    make_mapping_goal(agent)
    before = len(agent.goals)

    agent._ingest_motivation_goals(
        [
            {
                "title": "Открыть новую область: curiosity",
                "source": "drive",
                "action_hint": "explore",
                "type": "discovery",
            },
            {
                "title": "Глубокое погружение в: curiosity",
                "source": "drive",
                "action_hint": "explore",
                "type": "deep_learning",
            },
            {
                "title": "Достичь мастерства в: curiosity",
                "source": "drive",
                "action_hint": "synthesize_understanding",
                "type": "mastery",
            },
        ]
    )

    assert len(agent.goals) == before + 1
    assert agent.goals[-1]["title"] == "Достичь мастерства в: curiosity"
    assert (
        agent.goals[-1]["motivation_origin"]["action_hint"]
        == "synthesize_understanding"
    )


def test_old_duplicate_is_skipped_without_reward_and_survives_checkpoint():
    completed = {
        "id": 1,
        "title": "Картирование: curiosity",
        "status": "active",
        "difficulty": 1,
        "motivation_origin": {"action_hint": "explore", "type": "mapping"},
    }
    duplicate = {
        "id": 2,
        "title": "Открыть новую область: curiosity",
        "status": "pending",
        "difficulty": 1,
        "motivation_origin": {"action_hint": "explore", "type": "discovery"},
    }
    different = {
        "id": 3,
        "title": "Достичь мастерства в: curiosity",
        "status": "pending",
        "difficulty": 2,
        "motivation_origin": {
            "action_hint": "synthesize_understanding",
            "type": "mastery",
        },
    }
    subsystem = GoalSubsystem("GoalQueue")
    subsystem.goals = [completed, duplicate, different]
    subsystem.active_goal = completed

    reward = subsystem.complete_goal(completed["id"])

    assert reward == 10
    assert subsystem.completed_goals == 1
    assert duplicate["status"] == "duplicate"
    assert duplicate["duplicate_of"] == completed["id"]
    assert subsystem.active_goal is different
    assert different["status"] == "active"

    restored = GoalSubsystem("GoalQueueRestored")
    restored.restore_from_checkpoint(subsystem.to_checkpoint_dict())
    assert restored.completed_goals == 1
    assert restored.active_goal["id"] == different["id"]
    assert restored.goals[1]["status"] == "duplicate"
    assert restored.goals[1]["duplicate_of"] == completed["id"]


def test_ingested_goal_binds_history_and_completion_by_id(agent):
    """Канонический ID связывает кандидата, историю и результат завершения."""
    motivation = agent.motivation_system
    curiosity = motivation.needs["curiosity"]
    curiosity.current_level = 0.1
    for drive in motivation.drives.values():
        drive.current_level = 0.0
    generated = motivation.generate_goals(pressing_needs=[curiosity])
    assert len(generated) == 1
    candidate = generated[0]

    agent._ingest_motivation_goals(generated)

    goal_id = candidate["goal_id"]
    assert agent.motivation_system.goal_history[-1]["goal_id"] == goal_id
    assert agent.goal_subsystem.get_goal(goal_id)["motivation_origin"]["need"] == (
        "curiosity"
    )

    agent.complete_goal(goal_id)

    assert agent.motivation_system.needs["curiosity"].current_level > 0.1
    checkpoint = agent.motivation_system.to_checkpoint_dict()
    assert checkpoint["goal_history"][-1]["goal_id"] == goal_id


def test_active_goal_id_and_motivation_survive_agent_restart(agent):
    """После перезапуска одинаковый текст не подменяет активную цель."""
    from src.core.checkpoint_serializer import (
        apply_state_to_agent,
        build_state_from_agent,
    )

    motivation = agent.motivation_system
    curiosity = motivation.needs["curiosity"]
    curiosity.current_level = 0.1
    for drive in motivation.drives.values():
        drive.current_level = 0.0
    generated = motivation.generate_goals(pressing_needs=[curiosity])
    assert len(generated) == 1
    candidate = generated[0]
    agent._ingest_motivation_goals(generated)
    first_id = candidate["goal_id"]

    second_id = agent.set_goal(candidate["title"], activate=True)
    motivation.goal_history.append(
        {
            "cycle": agent.cycle_count,
            "need": "meaning",
            "drive": None,
            "goal": candidate["title"],
            "priority": 0.5,
            "goal_id": second_id,
        }
    )
    motivation.needs["meaning"].current_level = 0.1
    snapshot = build_state_from_agent(agent)

    restored = DigitalBeing(name="ActiveGoalRestarted")
    searcher = getattr(restored, "web_searcher", None)
    if searcher is not None:
        searcher.toggle(False)
    apply_state_to_agent(restored, snapshot)

    assert first_id != second_id
    assert restored.active_goal["id"] == second_id
    assert restored.motivation_system.goal_history[-1]["goal_id"] == second_id

    restored.complete_goal()

    assert restored.motivation_system.needs["meaning"].current_level > 0.1
    assert restored.motivation_system.needs["curiosity"].current_level == 0.1


def test_goal_subsystem_restores_duplicate_active_goal_by_id():
    goals = [
        {"id": 1, "title": "Одинаковая цель", "status": "pending"},
        {"id": 2, "title": "Одинаковая цель", "status": "active"},
    ]
    subsystem = GoalSubsystem("GoalIdentity")
    subsystem.goals = goals
    subsystem.active_goal = goals[1]

    restored = GoalSubsystem("GoalIdentityRestored")
    restored.restore_from_checkpoint(subsystem.to_checkpoint_dict())

    assert restored.active_goal["id"] == 2


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_agent_failure_and_cancellation_reach_current_motivation(agent, outcome):
    motivation = agent.motivation_system
    curiosity = motivation.needs["curiosity"]
    curiosity.current_level = 0.1
    for drive in motivation.drives.values():
        drive.current_level = 0.0
    generated = motivation.generate_goals(pressing_needs=[curiosity])
    agent._ingest_motivation_goals(generated)
    goal_id = generated[0]["goal_id"]

    if outcome == "failed":
        assert agent.fail_goal(goal_id, "исполнение не удалось") is True
    else:
        assert agent.cancel_goal(goal_id, "больше не актуальна") is True

    assert motivation.goal_summary[outcome] == 1
    assert str(goal_id) not in motivation._pending_goal_origins
    entry = next(
        item for item in motivation.goal_history if item.get("goal_id") == goal_id
    )
    assert entry["status"] == outcome
    assert agent.complete_goal(goal_id) == 0
    assert motivation.goal_summary["achieved"] == 0
