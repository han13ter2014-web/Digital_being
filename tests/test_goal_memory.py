"""Ограниченная история целей без потери их происхождения и исходов."""

import pytest

from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.internal_motivation import InternalMotivation
from src.core.motivation.unified_motivation import UnifiedMotivationSystem
from src.core.subsystems.goal_manager import GoalSubsystem
from src.core.subsystems.motivation_controller import MotivationController
from src.core.subsystems.sleep_cycle import SleepCycle
from src.motivation.goal_memory import (
    format_goal_outcome,
    is_automatic_goal_repeat_blocked,
)
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


class RecordingLongTermMemory:
    def __init__(self, fail_writes=0):
        self.consolidation_threshold = 0.7
        self.fail_writes = fail_writes
        self.stored = []

    def store(self, **kwargs):
        if self.fail_writes:
            self.fail_writes -= 1
            raise OSError("временный сбой записи")
        self.stored.append(kwargs)
        return f"goal-memory-{len(self.stored)}"


def _terminal_goal_subsystem(status):
    subsystem = GoalSubsystem("GoalConsolidation")
    reason = "наблюдаемая причина"
    goal = {
        "id": 7,
        "title": "Проверить долговременную память",
        "status": status,
        "difficulty": 2,
    }
    if status == "failed":
        goal["failure_reason"] = reason
    elif status == "cancelled":
        goal["cancellation_reason"] = reason
    subsystem.goals = [goal]
    return subsystem


@pytest.mark.parametrize(
    ("status", "label"),
    [
        ("completed", "Цель достигнута"),
        ("failed", "Цель не выполнена"),
        ("cancelled", "Цель отменена"),
    ],
)
def test_sleep_consolidates_significant_goal_outcome_once_across_restart(status, label):
    memory = RecordingLongTermMemory()
    subsystem = _terminal_goal_subsystem(status)
    sleep = SleepCycle(
        long_term_memory=memory,
        goal_subsystem=subsystem,
        cycle_interval=1,
    )

    first = sleep.sleep(1)
    second = sleep.sleep(2)

    assert first["goal_outcomes_consolidated"] == 1
    assert second["goal_outcomes_consolidated"] == 0
    assert sleep.get_status()["last_goal_outcomes_consolidated"] == 0
    assert len(memory.stored) == 1
    trace = memory.stored[0]
    assert trace["content"].startswith(f"{label}: Проверить долговременную память")
    assert trace["importance"] == pytest.approx(0.8)
    assert trace["context"] == "goal_outcome:7"
    assert trace["memory_type"] == "episodic"
    if status in {"failed", "cancelled"}:
        assert trace["content"].endswith("Причина: наблюдаемая причина")

    restored = GoalSubsystem("GoalConsolidation")
    restored.restore_from_checkpoint(subsystem.to_checkpoint_dict())
    restored_sleep = SleepCycle(
        long_term_memory=memory,
        goal_subsystem=restored,
        cycle_interval=1,
    )
    assert restored_sleep.sleep(1)["goal_outcomes_consolidated"] == 0
    assert len(memory.stored) == 1


def test_sleep_skips_active_and_insignificant_goal_outcomes():
    memory = RecordingLongTermMemory()
    subsystem = GoalSubsystem("GoalConsolidation")
    subsystem.goals = [
        {"id": 1, "title": "Активная", "status": "active", "difficulty": 3},
        {"id": 2, "title": "Обычная", "status": "completed", "difficulty": 1},
        {"id": 3, "title": "Отменённая", "status": "cancelled", "priority": "low"},
    ]
    sleep = SleepCycle(
        long_term_memory=memory,
        goal_subsystem=subsystem,
        cycle_interval=1,
    )

    assert sleep.sleep(1)["goal_outcomes_consolidated"] == 0
    assert memory.stored == []
    assert all("ltm_trace_id" not in goal for goal in subsystem.goals)


@pytest.mark.parametrize(
    "goal_patch",
    [{"priority": "high"}, {"significance": 0.95}],
)
def test_sleep_respects_explicit_goal_significance(goal_patch):
    memory = RecordingLongTermMemory()
    subsystem = GoalSubsystem("GoalConsolidation")
    goal = {"id": 1, "title": "Важная", "status": "completed", "difficulty": 1}
    goal.update(goal_patch)
    subsystem.goals = [goal]
    sleep = SleepCycle(
        long_term_memory=memory,
        goal_subsystem=subsystem,
        cycle_interval=1,
    )

    assert sleep.sleep(1)["goal_outcomes_consolidated"] == 1
    assert memory.stored[0]["importance"] == pytest.approx(
        goal_patch.get("significance", 0.9)
    )


def test_goal_outcome_consolidation_retries_failed_write():
    memory = RecordingLongTermMemory(fail_writes=1)
    subsystem = _terminal_goal_subsystem("failed")
    sleep = SleepCycle(
        long_term_memory=memory,
        goal_subsystem=subsystem,
        cycle_interval=1,
    )

    assert sleep.sleep(1)["goal_outcomes_consolidated"] == 0
    assert "ltm_trace_id" not in subsystem.goals[0]
    assert sleep.sleep(2)["goal_outcomes_consolidated"] == 1
    assert subsystem.goals[0]["ltm_trace_id"] == "goal-memory-1"


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_automatic_terminal_goal_repeat_requires_new_reason(status):
    agent = GoalAgent()
    agent.goals = [
        {"id": 1, "title": "Понять: память", "status": status},
    ]

    assert is_automatic_goal_repeat_blocked(agent, {"title": "  Понять:   память  "})
    assert not is_automatic_goal_repeat_blocked(
        agent,
        {
            "title": "Понять: память",
            "retry_reason": "Появились новые наблюдения",
        },
    )


def test_automatic_live_goal_repeat_is_blocked_even_with_new_reason():
    agent = GoalAgent()
    agent.goals = [{"id": 1, "title": "Понять: память", "status": "active"}]

    assert is_automatic_goal_repeat_blocked(
        agent,
        {"title": "Понять: память", "retry_reason": "Новая причина"},
    )


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_automatic_goal_repeat_uses_ltm_after_current_history_is_gone(status):
    memory = RecordingLongTermMemory()
    title = "Понять: долговременную память"
    memory.store(
        content=format_goal_outcome({"title": title}, status),
        importance=0.9,
        context="goal_outcome:1",
        memory_type="episodic",
    )
    memory.recall = lambda *_args, **_kwargs: memory.stored
    agent = GoalAgent()
    agent.long_term_memory = memory

    assert is_automatic_goal_repeat_blocked(agent, {"title": title.casefold()})
    assert not is_automatic_goal_repeat_blocked(agent, {"title": "Понять: другую тему"})
    assert not is_automatic_goal_repeat_blocked(
        agent,
        {"title": title, "retry_reason": "Изменились условия"},
    )


def test_intrinsic_goal_repeat_is_blocked_and_reasoned_retry_is_recorded():
    agent = GoalAgent()
    system = InternalMotivation(agent)
    goal = {
        "title": "Понять: память",
        "priority": 0.8,
        "urgency": 0.7,
        "context": "тестовое происхождение",
    }
    need = system.needs["curiosity"]

    assert system._set_intrinsic_goal(goal, need) is True
    agent.goals[0]["status"] = "failed"
    agent.active_goal = None
    generated_before = system.goal_summary["generated"]

    assert system._set_intrinsic_goal(goal, need) is False
    assert system.goal_summary["generated"] == generated_before

    retry = {**goal, "retry_reason": "Найден новый способ проверки"}
    assert system._set_intrinsic_goal(retry, need) is True
    assert len(agent.goals) == 2
    assert agent.goals[-1]["retry_reason"] == "Найден новый способ проверки"
    assert system.goal_summary["generated"] == generated_before + 1


def test_legacy_motivation_controller_uses_same_repeat_rule():
    class LegacySystem:
        candidates = []

        def time_progression(self):
            pass

        def get_motivation_profile(self):
            return {}

        def generate_motivated_goals(self, _context):
            return [dict(candidate) for candidate in self.candidates]

        def bind_goal(self, _goal, _goal_id):
            pass

    controller = MotivationController("LegacyRepeat")
    legacy_system = LegacySystem()
    controller._system = legacy_system
    controller._available = True
    subsystem = GoalSubsystem("LegacyRepeat")
    subsystem.goals = [
        {"id": 1, "title": "Понять: память", "status": "cancelled"},
    ]
    controller.attach_goal_subsystem(subsystem)
    candidate = {"title": "Понять: память", "drive": "curiosity"}

    legacy_system.candidates = [candidate]
    assert controller.tick()["new_goals"] == []
    assert len(subsystem.goals) == 1

    retry = {**candidate, "retry_reason": "Новые обстоятельства"}
    legacy_system.candidates = [retry]
    assert controller.tick()["new_goals"] == [retry]
    assert len(subsystem.goals) == 2
    assert subsystem.goals[-1]["retry_reason"] == "Новые обстоятельства"


def _outcome_agent(status="failed", action="hypothesis", *, with_signature=True):
    from types import SimpleNamespace

    from src.motivation.goal_memory import capture_goal_evidence

    agent = GoalAgent()
    agent.mental_models = SimpleNamespace(concepts={})
    goal = {
        "id": 1,
        "title": "Понять: память",
        "status": status,
        "motivation_origin": {"action_hint": action},
    }
    agent.goals = [goal]
    if with_signature:
        goal["evidence_at_outcome"] = capture_goal_evidence(agent, goal["title"])
    return agent, goal


def _add_evidence(agent, concept="память", kind="observation"):
    from src.cognition.mental_models import ConceptNode

    node = agent.mental_models.concepts.get(concept)
    if node is None:
        node = ConceptNode(concept)
        agent.mental_models.concepts[concept] = node
    node.add_experience(
        "новый контекст",
        "новое наблюдение",
        evidence_strength=0.5,
        evidence_kind=kind,
        source="test:evidence",
    )


def test_failed_goal_retry_uses_recorded_alternative_strategy():
    from src.motivation.goal_memory import prepare_automatic_goal_retry

    agent, _goal = _outcome_agent()
    candidate = {"title": "Понять: память", "action_hint": "explore"}

    prepare_automatic_goal_retry(agent, candidate)

    assert not is_automatic_goal_repeat_blocked(agent, candidate)
    assert "hypothesis" in candidate["retry_reason"]
    assert "explore" in candidate["retry_reason"]
    assert candidate["retry_of"] == 1


def test_failed_goal_retry_does_not_ping_pong_between_failed_strategies():
    from src.motivation.goal_memory import prepare_automatic_goal_retry

    agent, first = _outcome_agent()
    second = {
        "id": 2,
        "title": "Исследовать: память",
        "status": "failed",
        "motivation_origin": {"action_hint": "explore"},
        "evidence_at_outcome": dict(first["evidence_at_outcome"]),
    }
    agent.goals.append(second)
    candidate = {"title": "Исследовать: память", "action_hint": "explore"}

    prepare_automatic_goal_retry(agent, candidate)

    assert "retry_reason" not in candidate
    assert is_automatic_goal_repeat_blocked(agent, candidate)


@pytest.mark.parametrize("evidence_kind", ["observation", "testimony"])
def test_new_relevant_evidence_reasons_about_goal_retry(evidence_kind):
    from src.motivation.goal_memory import prepare_automatic_goal_retry

    agent, _goal = _outcome_agent()
    candidate = {"title": "Понять: память", "action_hint": "hypothesis"}
    _add_evidence(agent, kind=evidence_kind)

    prepare_automatic_goal_retry(agent, candidate)

    assert not is_automatic_goal_repeat_blocked(agent, candidate)
    assert "0 → 1" in candidate["retry_reason"]
    assert candidate["retry_of"] == 1


def test_unrelated_evidence_does_not_reason_about_goal_retry():
    from src.motivation.goal_memory import prepare_automatic_goal_retry

    agent, _goal = _outcome_agent()
    candidate = {"title": "Понять: память", "action_hint": "hypothesis"}
    _add_evidence(agent, concept="кухня")

    prepare_automatic_goal_retry(agent, candidate)

    assert "retry_reason" not in candidate
    assert is_automatic_goal_repeat_blocked(agent, candidate)


@pytest.mark.parametrize("status", ["completed", "cancelled"])
def test_non_failure_retry_requires_evidence_not_only_another_strategy(status):
    from src.motivation.goal_memory import prepare_automatic_goal_retry

    agent, _goal = _outcome_agent(status=status)
    candidate = {"title": "Исследовать: память", "action_hint": "explore"}

    prepare_automatic_goal_retry(agent, candidate)
    assert "retry_reason" not in candidate
    assert is_automatic_goal_repeat_blocked(agent, candidate)

    _add_evidence(agent, kind="testimony")
    prepare_automatic_goal_retry(agent, candidate)
    assert not is_automatic_goal_repeat_blocked(agent, candidate)
    assert candidate["retry_of"] == 1


def test_legacy_outcome_without_signature_does_not_invent_evidence_retry():
    from src.motivation.goal_memory import prepare_automatic_goal_retry

    agent, _goal = _outcome_agent(with_signature=False)
    candidate = {"title": "Понять: память", "action_hint": "hypothesis"}
    _add_evidence(agent)

    prepare_automatic_goal_retry(agent, candidate)

    assert "retry_reason" not in candidate
    assert is_automatic_goal_repeat_blocked(agent, candidate)


def test_direct_knowledge_entry_is_new_relevant_evidence():
    from src.motivation.goal_memory import prepare_automatic_goal_retry

    agent, _goal = _outcome_agent(status="completed")
    candidate = {"title": "Понять: память", "action_hint": "hypothesis"}
    agent.knowledge_base["память"] = "Новое проверенное определение"

    prepare_automatic_goal_retry(agent, candidate)

    assert not is_automatic_goal_repeat_blocked(agent, candidate)
    assert "запись в базе знаний" in candidate["retry_reason"]


def test_explicit_retry_reason_is_not_overwritten():
    from src.motivation.goal_memory import prepare_automatic_goal_retry

    agent, _goal = _outcome_agent()
    candidate = {
        "title": "Понять: память",
        "action_hint": "explore",
        "retry_reason": "Явно указанная причина",
    }

    prepare_automatic_goal_retry(agent, candidate)

    assert candidate["retry_reason"] == "Явно указанная причина"
