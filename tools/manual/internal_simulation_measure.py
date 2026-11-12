"""Измеряет живой shadow-контур InternalSimulator ↔ WorldDelta.

Прогон использует изолированную временную data-директорию, новую сущность и
реальные autonomous_tick/AgentRunner. Веб-поиск по умолчанию отключён; флаг
--web разрешает настоящие сетевые запросы. Действия и их исходы не подменяются.
После каждого шага добавляется та же регенерация
энергии, что и в autonomous_life_measure.py, чтобы ускорить лабораторный замер.

Пример:
    python tools/manual/internal_simulation_measure.py \
        --cycles 2000 --report data/metrics/internal_simulation_shadow.json
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from copy import deepcopy
import json
import logging
import os
from pathlib import Path
import random
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def accuracy_metrics(rows: list[dict]) -> dict:
    if not rows:
        return {"count": 0, "accuracy": None, "mae": None, "brier_score": None}
    return {
        "count": len(rows),
        "accuracy": sum(bool(row["prediction_matched"]) for row in rows) / len(rows),
        "mae": sum(float(row["absolute_error"]) for row in rows) / len(rows),
        "brier_score": sum(
            (float(row["predicted_effect_probability"]) - float(row["had_effect"])) ** 2
            for row in rows
        ) / len(rows),
        "had_effect_count": sum(bool(row["had_effect"]) for row in rows),
    }


def majority_baseline(rows: list[dict]) -> dict:
    if not rows:
        return {"outcome": None, "probability": None, "accuracy": None, "mae": None}
    effects = sum(bool(row["had_effect"]) for row in rows)
    probability = effects / len(rows)
    outcome = probability >= 0.5
    baseline_rows = [
        {
            "had_effect": row["had_effect"],
            "prediction_matched": bool(row["had_effect"]) == outcome,
            "absolute_error": abs(probability - float(row["had_effect"])),
            "predicted_effect_probability": probability,
        }
        for row in rows
    ]
    return {"outcome": outcome, "probability": probability, **accuracy_metrics(baseline_rows)}


def per_action_metrics(rows: list[dict]) -> dict:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["action"]].append(row)
    result = {}
    for action, items in sorted(grouped.items()):
        baseline = majority_baseline(items)
        result[action] = {
            **accuracy_metrics(items),
            "majority_baseline": baseline,
            "targets": dict(sorted(Counter(row["target"] for row in items).items())),
        }
    return result


async def measure(cycles: int, seed: int, min_resolved: int, min_actions: int) -> dict:
    import numpy as np
    from src.app.paths import setup_environment
    from src.app.bootstrap import create_agent
    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    random.seed(seed)
    np.random.seed(seed)
    env = setup_environment(chdir=False)
    agent, _ = create_agent(env, "InternalSimulationMeasure", new=True)
    traces = []
    action_counts = Counter()
    unavailable_counts = Counter()
    original_tick = agent.autonomous_tick

    def observe_tick():
        report = original_tick()
        diagnostics = report.get("simulation") or {}
        unavailable_counts["unavailable"] += int(diagnostics.get("unavailable", 0))
        feedback = report.get("simulation_feedback") or {}
        prediction_id = feedback.get("prediction_id")
        if not prediction_id:
            return report
        action_counts[feedback.get("action", "")] += 1
        arbitration = report.get("arbitrator") or {}
        selected_prediction = arbitration.get("simulation") or {}
        intention_id = report.get("intention_id")
        entry = next(
            (item for item in reversed(getattr(agent, "_intention_history", []))
             if item.get("id") == intention_id),
            None,
        )
        saved_prediction = next(
            (item for item in agent.internal_simulator.memory.simulated_events
             if item.get("prediction_id") == prediction_id),
            None,
        )
        history_prediction = next(
            (item for item in reversed(agent.internal_simulator.prediction_accuracy_history)
             if item.get("prediction_id") == prediction_id),
            None,
        )
        intention_prediction = (entry or {}).get("simulation") or {}
        outcome = (entry or {}).get("outcome") or {}
        checks = {
            "selected_prediction": selected_prediction.get("prediction_id") == prediction_id,
            "intention_prediction": intention_prediction.get("prediction_id") == prediction_id,
            "intention_resolved": intention_prediction.get("status") == "resolved",
            "saved_prediction_resolved": (saved_prediction or {}).get("status") == "resolved",
            "accuracy_history_saved": history_prediction is not None,
            "world_delta_saved": bool(feedback.get("actual_delta") is not None),
            "outcome_matches": outcome.get("had_effect") == feedback.get("had_effect"),
            "shadow_mode": diagnostics.get("mode") == "shadow",
        }
        traces.append({
            "cycle": agent.cycle_count,
            "prediction_id": prediction_id,
            "intention_id": intention_id,
            "action": feedback.get("action"),
            "target": feedback.get("target"),
            "predicted_effect_probability": feedback.get("predicted_effect_probability"),
            "had_effect": feedback.get("had_effect"),
            "actual_delta": deepcopy(feedback.get("actual_delta")),
            "absolute_error": feedback.get("absolute_error"),
            "prediction_matched": feedback.get("prediction_matched"),
            "chain_checks": checks,
            "chain_complete": all(checks.values()),
        })
        return report

    agent.autonomous_tick = observe_tick
    runner = AgentRunner(agent, EventBus(), name="InternalSimulationMeasureRunner")
    runner.set_speed("max")
    runner.set_stimulus_mode("pool")
    await runner.start()
    completed = 0
    stop_reason = "cycle_limit"
    try:
        for _ in range(cycles):
            runner.energy_policy.regenerate(5.0)
            if not await runner.step_once():
                stop_reason = "runner_stopped"
                break
            completed += 1
            rows = agent.internal_simulator.prediction_accuracy_history
            if len(rows) >= min_resolved and len({row["action"] for row in rows}) >= min_actions:
                stop_reason = "threshold_reached"
                break
            if not runner._running:
                stop_reason = "runner_stopped"
                break
    finally:
        await runner.stop()

    simulator = agent.internal_simulator
    rows = deepcopy(simulator.prediction_accuracy_history)
    simulated_statuses = Counter(
        str(event.get("status")) for event in simulator.memory.simulated_events
    )
    searcher = getattr(agent, "web_searcher", None)
    web_search_enabled = bool(
        searcher is not None and getattr(searcher, "is_enabled", False)
    )
    report = {
        "schema_version": 1,
        "seed": seed,
        "mode": "shadow",
        "new_agent": True,
        "isolated_temporary_data": True,
        "web_search_enabled": web_search_enabled,
        "actions_and_outcomes_substituted": False,
        "energy_regeneration_per_cycle": 5.0,
        "cycles_completed": completed,
        "stop_reason": stop_reason,
        "criteria": {"min_resolved": min_resolved, "min_actions": min_actions},
        "resolved_predictions": len(rows),
        "resolved_action_types": sorted({row["action"] for row in rows}),
        "simulator": accuracy_metrics(rows),
        "majority_baseline": majority_baseline(rows),
        "per_action": per_action_metrics(rows),
        "chain": {
            "traces": len(traces),
            "complete": sum(bool(trace["chain_complete"]) for trace in traces),
            "incomplete": [trace for trace in traces if not trace["chain_complete"]],
        },
        "simulated_events_in_final_memory": dict(sorted(simulated_statuses.items())),
        "unavailable_candidate_predictions": unavailable_counts["unavailable"],
        "resolution_traces": traces,
        "prediction_accuracy_history": rows,
        "final_internal_simulation": simulator.to_checkpoint_dict(),
    }
    simulator_metrics = report["simulator"]
    baseline_metrics = report["majority_baseline"]
    report["comparison"] = {
        "accuracy_delta": (
            simulator_metrics["accuracy"] - baseline_metrics["accuracy"]
            if rows else None
        ),
        "mae_delta": (
            simulator_metrics["mae"] - baseline_metrics["mae"]
            if rows else None
        ),
        "brier_score_delta": (
            simulator_metrics["brier_score"] - baseline_metrics["brier_score"]
            if rows else None
        ),
    }
    report["criteria_met"] = {
        "resolved_predictions": len(rows) >= min_resolved,
        "action_types": len({row["action"] for row in rows}) >= min_actions,
        "complete_chains": bool(traces) and all(trace["chain_complete"] for trace in traces),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--min-resolved", type=int, default=30)
    parser.add_argument("--min-actions", type=int, default=3)
    parser.add_argument("--web", action="store_true", help="Разрешить реальный веб-поиск")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if min(args.cycles, args.min_resolved, args.min_actions) < 1:
        parser.error("cycles, min-resolved и min-actions должны быть положительными")

    sys.path.insert(0, str(PROJECT_ROOT))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="db_internal_simulation_") as data_dir:
        os.environ["DIGITAL_BEING_DATA_DIR"] = data_dir
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        from config.simulation_config import LR_CONFIG, SIM_CONFIG

        LR_CONFIG.WEB_SEARCH_ENABLED = args.web
        SIM_CONFIG.INTERNAL_SIMULATION_MODE = "shadow"
        try:
            result = asyncio.run(measure(
                args.cycles, args.seed, args.min_resolved, args.min_actions
            ))
            # На Windows отчёт сохраняем до удаления временной директории:
            # даже неожиданная блокировка log-файла не должна терять замер.
            args.report.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        finally:
            logging.shutdown()
    summary = {
        key: result[key] for key in (
            "cycles_completed", "stop_reason", "resolved_predictions",
            "resolved_action_types", "simulator", "majority_baseline",
            "comparison", "criteria_met",
        )
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report: {args.report}")
    if not all(result["criteria_met"].values()):
        raise SystemExit("Критерии измерения не выполнены; подробности в отчёте")


if __name__ == "__main__":
    main()
