"""Контролируемый живой сценарий InternalSimulator для decomposition.

Это НЕ автономный замер: набор кандидатов заранее ограничен одной декомпозицией
с явной темой. Выбор выполняет настоящий DecisionArbitrator, действие — act(),
фактический исход — LoopCloser/WorldDelta. Исходы не назначаются и не меняются.

Первые три выполнения создают опыт, последующие прогнозы разрешаются фактом.
Повтор одной темы естественно даёт смешанные исходы: новые под-вопросы могут
быть добавлены один раз, затем дубликаты не меняют наблюдаемый мир.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import logging
import os
from pathlib import Path
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from tools.manual.internal_simulation_measure import (  # noqa: E402
    accuracy_metrics,
    majority_baseline,
    per_action_metrics,
)


def run_scenario(target: str, trials: int) -> dict:
    from config.simulation_config import SIM_CONFIG
    from src.app.paths import setup_environment
    from src.app.bootstrap import create_agent
    from src.cognition.intention_history import begin_intention, finish_intention
    from src.cognition.simulation_bridge import (
        cancel_selected_prediction,
        learn_from_selected_action,
        predict_candidates,
    )

    env = setup_environment(chdir=False)
    agent, _ = create_agent(env, "InternalSimulationDecomposition", new=True)
    rows = []
    traces = []

    for trial in range(1, trials + 1):
        original = [{
            "action": "decomposition",
            "source": "controlled_decomposition_scenario",
            "strength": 0.8,
            "params": {"topic": target},
        }]
        candidates, diagnostics = predict_candidates(agent, original, mode="shadow")
        selection = agent.decision_arbitrator.choose_action(
            candidates,
            {"simulation_mode": "shadow", "simulation_max_adjustment": 0.1},
        )
        intention_entry = begin_intention(agent, selection)
        agent._last_action_outcome = None
        outcome = None
        feedback = None
        error = None
        try:
            if selection.get("action") == "decomposition":
                agent.act("decomposition", intention=selection)
                outcome = agent._last_action_outcome
            if outcome is not None:
                feedback = learn_from_selected_action(
                    agent, selection, intention_entry, outcome
                )
            else:
                cancel_selected_prediction(
                    agent, intention_entry,
                    "arbitrator_refusal" if selection.get("action") != "decomposition" else "unobserved",
                )
            finish_intention(intention_entry, outcome)
        except Exception as exc:
            error = str(exc)
            cancel_selected_prediction(agent, intention_entry, "execution_error")
            finish_intention(intention_entry, error=exc)

        prediction_id = (feedback or {}).get("prediction_id")
        saved_prediction = next(
            (item for item in agent.internal_simulator.memory.simulated_events
             if item.get("prediction_id") == prediction_id),
            None,
        ) if prediction_id else None
        history_prediction = next(
            (item for item in reversed(agent.internal_simulator.prediction_accuracy_history)
             if item.get("prediction_id") == prediction_id),
            None,
        ) if prediction_id else None
        selected_prediction = selection.get("simulation") or {}
        intention_prediction = intention_entry.get("simulation") or {}
        outcome_dict = intention_entry.get("outcome") or {}
        chain_checks = {
            "selected_prediction": selected_prediction.get("prediction_id") == prediction_id,
            "intention_prediction": intention_prediction.get("prediction_id") == prediction_id,
            "intention_resolved": intention_prediction.get("status") == "resolved",
            "saved_prediction_resolved": (saved_prediction or {}).get("status") == "resolved",
            "accuracy_history_saved": history_prediction is not None,
            "world_delta_saved": feedback is not None and feedback.get("actual_delta") is not None,
            "outcome_matches": outcome_dict.get("had_effect") == (feedback or {}).get("had_effect"),
            "shadow_mode": diagnostics.get("mode") == "shadow",
        } if prediction_id else {}
        traces.append({
            "trial": trial,
            "cycle": agent.cycle_count,
            "target": target,
            "selected_action": selection.get("action"),
            "verdict": selection.get("verdict"),
            "prediction_status_before_action": selected_prediction.get("status"),
            "prediction_id": prediction_id,
            "predicted_effect_probability": (feedback or {}).get("predicted_effect_probability"),
            "had_effect": None if outcome is None else bool(outcome.had_effect),
            "actual_delta": None if outcome is None else outcome.delta.as_dict(),
            "outcome_summary": None if outcome is None else outcome.summary,
            "error": error,
            "chain_checks": chain_checks,
            "chain_complete": bool(chain_checks) and all(chain_checks.values()),
        })
        agent.cycle_count += 1
        if error:
            break

    rows = deepcopy(agent.internal_simulator.prediction_accuracy_history)
    simulator_metrics = accuracy_metrics(rows)
    baseline_metrics = majority_baseline(rows)
    return {
        "schema_version": 1,
        "scenario": "controlled_decomposition",
        "autonomous_candidate_generation": False,
        "selection_policy": "single_candidate_real_decision_arbitrator",
        "actions_and_outcomes_substituted": False,
        "new_agent": True,
        "isolated_temporary_data": True,
        "mode": SIM_CONFIG.INTERNAL_SIMULATION_MODE,
        "target": target,
        "trials_completed": len(traces),
        "resolved_predictions": len(rows),
        "had_effect_counts": {
            "true": sum(bool(row["had_effect"]) for row in rows),
            "false": sum(not bool(row["had_effect"]) for row in rows),
        },
        "all_trial_had_effect": [trace["had_effect"] for trace in traces],
        "simulator": simulator_metrics,
        "majority_baseline": baseline_metrics,
        "comparison": {
            "accuracy_delta": simulator_metrics["accuracy"] - baseline_metrics["accuracy"] if rows else None,
            "mae_delta": simulator_metrics["mae"] - baseline_metrics["mae"] if rows else None,
            "brier_score_delta": simulator_metrics["brier_score"] - baseline_metrics["brier_score"] if rows else None,
        },
        "chain": {
            "traces": sum(bool(trace["prediction_id"]) for trace in traces),
            "complete": sum(bool(trace["chain_complete"]) for trace in traces),
            "incomplete": [trace for trace in traces if trace["prediction_id"] and not trace["chain_complete"]],
        },
        "trial_traces": traces,
        "prediction_accuracy_history": rows,
        "final_internal_simulation": agent.internal_simulator.to_checkpoint_dict(),
    }


def combined_report(autonomous_path: Path, focused: dict, focused_path: Path) -> dict:
    autonomous = json.loads(autonomous_path.read_text(encoding="utf-8"))
    autonomous_rows = autonomous.get("prediction_accuracy_history") or []
    focused_rows = focused.get("prediction_accuracy_history") or []
    rows = deepcopy(autonomous_rows) + deepcopy(focused_rows)
    prediction_ids = [row.get("prediction_id") for row in rows]
    if len(prediction_ids) != len(set(prediction_ids)):
        raise ValueError("В объединённой выборке повторяются prediction_id")
    autonomous_traces = autonomous.get("resolution_traces") or []
    focused_traces = [
        trace for trace in focused["trial_traces"] if trace.get("prediction_id")
    ]
    traces = deepcopy(autonomous_traces) + deepcopy(focused_traces)
    simulator_metrics = accuracy_metrics(rows)
    baseline_metrics = majority_baseline(rows)
    return {
        "schema_version": 1,
        "sample_kind": "autonomous_plus_explicitly_controlled_decomposition",
        "not_a_uniform_autonomous_sample": True,
        "sources": [
            {
                "kind": "autonomous",
                "path": str(autonomous_path.resolve()),
                "resolved_predictions": len(autonomous_rows),
            },
            {
                "kind": "controlled_decomposition",
                "path": str(focused_path.resolve()),
                "resolved_predictions": len(focused_rows),
            },
        ],
        "resolved_predictions": len(rows),
        "resolved_action_types": sorted({row["action"] for row in rows}),
        "had_effect_counts": {
            "true": sum(bool(row["had_effect"]) for row in rows),
            "false": sum(not bool(row["had_effect"]) for row in rows),
        },
        "simulator": simulator_metrics,
        "majority_baseline": baseline_metrics,
        "per_action": per_action_metrics(rows),
        "comparison": {
            "accuracy_delta": simulator_metrics["accuracy"] - baseline_metrics["accuracy"],
            "mae_delta": simulator_metrics["mae"] - baseline_metrics["mae"],
            "brier_score_delta": simulator_metrics["brier_score"] - baseline_metrics["brier_score"],
        },
        "chain": {
            "traces": len(traces),
            "complete": sum(bool(trace["chain_complete"]) for trace in traces),
            "incomplete": [trace for trace in traces if not trace["chain_complete"]],
        },
        "data_criteria_met": {
            "at_least_30_resolved": len(rows) >= 30,
            "at_least_3_action_types": len({row["action"] for row in rows}) >= 3,
            "both_outcome_classes": (
                0 < sum(bool(row["had_effect"]) for row in rows) < len(rows)
            ),
            "complete_chains": bool(traces) and all(trace["chain_complete"] for trace in traces),
        },
        "prediction_accuracy_history": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="что такое сознание")
    parser.add_argument("--trials", type=int, default=12)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--combine-with", type=Path)
    parser.add_argument("--combined-report", type=Path)
    args = parser.parse_args()
    if args.trials < 4:
        parser.error("Нужны минимум четыре выполнения: три опыта и один прогноз")
    if bool(args.combine_with) != bool(args.combined_report):
        parser.error("--combine-with и --combined-report задаются вместе")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="db_simulation_decomposition_") as data_dir:
        os.environ["DIGITAL_BEING_DATA_DIR"] = data_dir
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        from config.simulation_config import LR_CONFIG, SIM_CONFIG

        LR_CONFIG.WEB_SEARCH_ENABLED = False
        SIM_CONFIG.INTERNAL_SIMULATION_MODE = "shadow"
        try:
            result = run_scenario(args.target, args.trials)
            args.report.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            combined = None
            if args.combine_with:
                combined = combined_report(args.combine_with, result, args.report)
                args.combined_report.parent.mkdir(parents=True, exist_ok=True)
                args.combined_report.write_text(
                    json.dumps(combined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
        finally:
            logging.shutdown()

    summary = {
        "scenario": result["scenario"],
        "trials_completed": result["trials_completed"],
        "resolved_predictions": result["resolved_predictions"],
        "all_trial_had_effect": result["all_trial_had_effect"],
        "simulator": result["simulator"],
        "majority_baseline": result["majority_baseline"],
        "chain": result["chain"],
    }
    if combined is not None:
        summary["combined"] = {
            key: combined[key] for key in (
                "resolved_predictions", "resolved_action_types", "had_effect_counts",
                "simulator", "majority_baseline", "comparison", "chain",
                "data_criteria_met",
            )
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report: {args.report}")
    if combined is not None:
        print(f"Combined report: {args.combined_report}")


if __name__ == "__main__":
    main()
