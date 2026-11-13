"""Границы операционных журналов и сохранение накопленных итогов."""

import json

from src.cognition.reflection_engine import ReflectionEngine
from src.consciousness.internal_dialogue import InternalDialogueEngine
from src.core.subsystems.sleep_cycle import SleepCycle
from src.motivation.needs_system import Need


def test_internal_dialogue_retains_recent_window_and_total_count():
    engine = InternalDialogueEngine()

    for index in range(105):
        engine.initiate_dialogue(f"тема {index}")

    assert len(engine.voice_history) == 100
    assert engine.voice_history[0]["topic"] == "тема 5"
    assert engine.voice_history[-1]["topic"] == "тема 104"
    assert engine.dialogue_count == 105


def test_conflict_window_preserves_cumulative_summary():
    engine = InternalDialogueEngine()

    for index in range(105):
        engine.resolve_conflict(
            engine.voices["skeptic"], engine.voices["optimist"], f"риск {index}"
        )

    assert len(engine.conflict_events) == 100
    assert engine.conflict_events[0]["topic"] == "риск 5"
    assert engine.conflict_events[-1]["topic"] == "риск 104"
    assert engine.conflict_summary == {"total": 105, "ecosystem_impact_sum": 52.5}
    assert engine.get_micrbiome_state()["total_conflicts"] == 105


def test_runtime_histories_are_not_shared_between_lives():
    first = InternalDialogueEngine()
    second = InternalDialogueEngine()

    first.initiate_dialogue("личная тема")
    first.resolve_conflict(first.voices["skeptic"], first.voices["heart"], "выбор")

    assert second.voice_history == []
    assert second.conflict_events == []
    assert second.dialogue_count == 0
    assert second.conflict_summary["total"] == 0


def test_need_forgets_raw_events_but_not_satisfaction_count():
    need = Need("curiosity")

    for _ in range(105):
        need.satisfy(0.01)

    assert len(need.satisfaction_events) == 100
    assert need.satisfied_count == 105


def test_reflection_retains_recent_cycles_and_still_analyzes_them():
    engine = ReflectionEngine()

    for index in range(105):
        engine.record_cycle(
            {
                "cycle_count": index,
                "intelligence": float(index),
                "energy": 100.0,
                "completed_goals": index,
                "knowledge_base": {str(item): item for item in range(index)},
            }
        )

    assert len(engine.performance_history) == 100
    assert engine.performance_history[0]["cycle"] == 5
    assert engine.performance_history[-1]["cycle"] == 104
    assert engine.recorded_cycles == 105
    assert engine.analyze_performance() == {
        "avg_intelligence_growth": 0.9,
        "avg_energy": 100.0,
        "knowledge_growth": 9,
        "goal_progress": 9,
        "efficiency": 1.8,
    }
    assert any(
        pattern["type"] == "stable_growth" for pattern in engine.identify_patterns()
    )


def test_reflection_report_file_is_a_bounded_operational_log(tmp_path):
    path = tmp_path / "reflection_report.json"
    engine = ReflectionEngine()

    for index in range(105):
        engine.save_reflection_report({"cycle": index}, str(path))

    reports = json.loads(path.read_text(encoding="utf-8"))
    assert len(reports) == 100
    assert reports[0] == {"cycle": 5}
    assert reports[-1] == {"cycle": 104}


def test_sleep_log_is_bounded_without_losing_total_sleep_count():
    sleep = SleepCycle(cycle_interval=1)

    for cycle in range(1, 106):
        sleep.sleep(cycle)

    assert len(sleep.sleep_history) == 100
    assert sleep.sleep_history[0]["cycle"] == 6
    assert sleep.sleep_history[-1]["cycle"] == 105
    assert sleep.total_sleeps == 105
