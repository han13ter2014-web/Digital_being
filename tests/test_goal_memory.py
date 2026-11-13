"""Ограниченная история целей без потери их происхождения и исходов."""

import pytest

from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.internal_motivation import InternalMotivation
from src.core.motivation.unified_motivation import UnifiedMotivationSystem
from src.core.subsystems.goal_manager import GoalSubsystem
from src.motivation.needs_system import InternalMotivationSystem


class GoalAgent:
    def __init__(self):
        self.cycle_count = 0
        self.innate_values = {}
        self.knowledge_base = {}
        self.beliefs = {}
        self.goals = []
        self.active_goal = None

    def set_goal(self, title, difficulty=1, activate=True):
        goal_id = len(self.goals) + 1
        goal = {
            "id": goal_id,
            "title": title,
            "difficulty": difficulty,
            "status": "active" if activate else "pending",
        }
        self.goals.append(goal)
        if activate:
            self.active_goal = goal
        return goal_id


def _generate_internal_goals(system, count):
    for index in range(count):
        system.agent.cycle_count = index + 1
        system._set_intrinsic_goal(
            {
                "title": f"Внутренняя цель {index}",
                "priority": 0.8,
                "urgency": 0.7,
                "context": "тестовое происхождение",
            },
            system.needs["curiosity"],
        )


@pytest.mark.parametrize("restart", [False, True])
def test_internal_goal_origin_survives_history_window_and_restart(restart):
    system = InternalMotivation(GoalAgent())
    _generate_internal_goals(system, 55)

    assert len(system.goal_history) == 50
    assert system.goal_history[0]["goal_id"] == 6
    assert system.goal_history[-1]["goal_id"] == 55
    assert system.goal_summary["generated"] == 55

    if restart:
        restored = InternalMotivation(GoalAgent())
        restored.restore_from_checkpoint(system.to_checkpoint_dict())
        system = restored

    system.needs["curiosity"].current_level = 0.1
    system.on_goal_achieved("Внутренняя цель 0", goal_id=1)

    assert system.needs["curiosity"].current_level > 0.1
    assert system.goal_summary["achieved"] == 1
    assert system.goal_summary["by_need"]["curiosity"] == {
        "generated": 55,
        "achieved": 1,
        "failed": 0,
        "cancelled": 0,
    }
    assert "1" not in system._pending_goal_origins
    achieved = next(entry for entry in system.goal_history if entry.get("goal_id") == 1)
    assert achieved["status"] == "achieved"
    assert achieved["achieved_cycle"] == system.agent.cycle_count

    level = system.needs["curiosity"].current_level
    system.on_goal_achieved("Внутренняя цель 0", goal_id=1)
    assert system.needs["curiosity"].current_level == level
    assert system.goal_summary["achieved"] == 1


def _generate_unified_goals(system, count):
    for index in range(count):
        system.agent.cycle_count = index + 1
        goals = system.generate_goals(
            pressing_needs=[system.needs["curiosity"]], active_drives=[]
        )
        assert len(goals) == 1
        system.bind_goal(goals[0], index + 1)


@pytest.mark.parametrize("restart", [False, True])
def test_unified_goal_origin_survives_history_window_and_restart(restart):
    system = UnifiedMotivationSystem(GoalAgent())
    _generate_unified_goals(system, 55)
    first_title = system._pending_goal_origins["1"]["goal"]

    assert len(system.goal_history) == 50
    assert system.goal_history[0]["goal_id"] == 6
    assert system.goal_history[-1]["goal_id"] == 55
    assert system.goal_summary["generated"] == 55

    if restart:
        system = UnifiedMotivationSystem.from_checkpoint_dict(
            GoalAgent(), system.to_checkpoint_dict()
        )

    system.needs["curiosity"].current_level = 0.1
    system.on_goal_achieved(first_title, goal_id=1)

    assert system.needs["curiosity"].current_level > 0.1
    assert system.goal_summary["achieved"] == 1
    assert system.goal_summary["by_need"]["curiosity"] == {
        "generated": 55,
        "achieved": 1,
        "failed": 0,
        "cancelled": 0,
    }
    assert "1" not in system._pending_goal_origins

    level = system.needs["curiosity"].current_level
    system.on_goal_achieved(first_title, goal_id=1)
    assert system.needs["curiosity"].current_level == level
    assert system.goal_summary["achieved"] == 1

    restored = UnifiedMotivationSystem.from_checkpoint_dict(
        GoalAgent(), system.to_checkpoint_dict()
    )
    assert restored.goal_summary["generated"] == 55
    assert restored.goal_summary["achieved"] == 1
    assert "1" not in restored._pending_goal_origins
    achieved = next(
        entry for entry in restored.goal_history if entry.get("goal_id") == 1
    )
    assert achieved["status"] == "achieved"


def test_legacy_goal_history_has_bounded_window_and_cumulative_origins():
    system = InternalMotivationSystem("GoalMemory")
    for name, need in system.needs.items():
        need.level = 1.0 if name in {"knowledge_acquisition", "competence"} else 0.0

    for index in range(55):
        goals = system.generate_motivated_goals(
            {"unknown_concepts": [f"концепция {index}"]}
        )
        assert len(goals) == 1

    assert len(system.goal_history) == 50
    assert system.goal_history[0]["title"] == "Изучить: концепция 5"
    assert system.goal_history[-1]["title"] == "Изучить: концепция 54"
    assert system.goal_summary["generated"] == 55
    assert system.goal_summary["by_drive"]["purposeful_learning"] == {
        "generated": 55,
        "achieved": 0,
        "failed": 0,
        "cancelled": 0,
    }
    assert system.to_dict()["goal_history_count"] == 55


def test_legacy_checkpoint_builds_available_goal_summary_and_pending_origins():
    history = [
        {
            "cycle": cycle,
            "need": "curiosity",
            "goal": f"Старая цель {cycle}",
            "goal_id": cycle,
        }
        for cycle in range(1, 52)
    ]

    restored = InternalMotivation(GoalAgent())
    restored.restore_from_checkpoint({"goal_history": history})

    assert len(restored.goal_history) == 50
    assert restored.goal_summary["generated"] == 50
    assert len(restored._pending_goal_origins) == 50
    assert "1" not in restored._pending_goal_origins
    assert restored._pending_goal_origins["2"]["need"] == "curiosity"


def test_goal_memory_is_not_shared_between_systems():
    first = UnifiedMotivationSystem(GoalAgent())
    second = UnifiedMotivationSystem(GoalAgent())
    _generate_unified_goals(first, 1)
    first.needs["curiosity"].current_level = 0.1
    first.on_goal_achieved(first.goal_history[-1]["goal"], goal_id=1)

    assert second.goal_history == []
    assert second.goal_summary["generated"] == 0
    assert second.goal_summary["achieved"] == 0
    assert second._pending_goal_origins == {}


@pytest.mark.parametrize(
    ("state", "path"),
    [
        (
            {"motivation": {"goal_summary": {"generated": -1}}},
            "motivation.goal_summary.generated",
        ),
        (
            {"motivation": {"goal_summary": {"failed": -1}}},
            "motivation.goal_summary.failed",
        ),
        (
            {"internal_motivation": {"pending_goal_origins": []}},
            "internal_motivation.pending_goal_origins",
        ),
    ],
)
def test_goal_memory_checkpoint_fields_are_validated(state, path):
    with pytest.raises(ValueError, match=path):
        validate_checkpoint_state(state)


@pytest.mark.parametrize("system_type", ["internal", "unified"])
@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_goal_failure_and_cancellation_survive_window_and_restart(system_type, outcome):
    if system_type == "internal":
        system = InternalMotivation(GoalAgent())
        _generate_internal_goals(system, 55)
        first_title = "Внутренняя цель 0"
    else:
        system = UnifiedMotivationSystem(GoalAgent())
        _generate_unified_goals(system, 55)
        first_title = system._pending_goal_origins["1"]["goal"]

    if system_type == "internal":
        restored = InternalMotivation(GoalAgent())
        restored.restore_from_checkpoint(system.to_checkpoint_dict())
        system = restored
    else:
        system = UnifiedMotivationSystem.from_checkpoint_dict(
            GoalAgent(), system.to_checkpoint_dict()
        )

    system.needs["curiosity"].current_level = 0.1
    callback = getattr(system, f"on_goal_{outcome}")
    callback(first_title, goal_id=1, reason="подтверждённый исход")

    assert system.needs["curiosity"].current_level == 0.1
    assert system.goal_summary[outcome] == 1
    assert system.goal_summary["by_need"]["curiosity"][outcome] == 1
    assert "1" not in system._pending_goal_origins
    entry = next(item for item in system.goal_history if item.get("goal_id") == 1)
    assert entry["status"] == outcome
    assert entry[f"{outcome}_cycle"] == system.agent.cycle_count
    reason_field = "failure_reason" if outcome == "failed" else "cancellation_reason"
    assert entry[reason_field] == "подтверждённый исход"

    callback(first_title, goal_id=1, reason="повтор")
    assert system.goal_summary[outcome] == 1

    if system_type == "internal":
        restored = InternalMotivation(GoalAgent())
        restored.restore_from_checkpoint(system.to_checkpoint_dict())
    else:
        restored = UnifiedMotivationSystem.from_checkpoint_dict(
            GoalAgent(), system.to_checkpoint_dict()
        )
    assert restored.goal_summary[outcome] == 1
    assert "1" not in restored._pending_goal_origins


def _legacy_goal_subsystem():
    system = InternalMotivationSystem("GoalOutcomes")
    for name, need in system.needs.items():
        need.level = 1.0 if name in {"knowledge_acquisition", "competence"} else 0.0
    generated = system.generate_motivated_goals({"unknown_concepts": ["память"]})
    goal = generated[0]
    system.bind_goal(goal, 1)

    subsystem = GoalSubsystem("GoalOutcomes")
    subsystem.attach_motivation(system)
    subsystem.goals = [
        {
            "id": 1,
            "title": goal["title"],
            "status": "active",
            "difficulty": 1,
            "drive": goal["drive"],
        },
        {
            "id": 2,
            "title": "Следующая цель",
            "status": "pending",
            "difficulty": 1,
        },
    ]
    subsystem.active_goal = subsystem.goals[0]
    return system, subsystem


@pytest.mark.parametrize("outcome", ["achieved", "failed", "cancelled"])
def test_legacy_goal_subsystem_records_every_terminal_outcome(outcome):
    system, subsystem = _legacy_goal_subsystem()

    if outcome == "achieved":
        subsystem.complete_goal(1)
    elif outcome == "failed":
        assert subsystem.fail_goal(1, "ошибка исполнения") is True
    else:
        assert subsystem.cancel_goal(1, "цель отменена") is True

    entry = system.goal_history[-1]
    assert entry["status"] == outcome
    assert system.goal_summary[outcome] == 1
    assert "1" not in system._pending_goal_origins
    assert subsystem.goals[1]["status"] == "active"

    if outcome == "achieved":
        subsystem.complete_goal(1)
    elif outcome == "failed":
        assert subsystem.fail_goal(1, "повтор") is False
    else:
        assert subsystem.cancel_goal(1, "повтор") is False
    assert system.goal_summary[outcome] == 1
