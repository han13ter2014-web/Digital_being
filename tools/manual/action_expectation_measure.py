"""Compare real rest actions with and without body-expectation observations.

Run from the project root:
    python tools/manual/action_expectation_measure.py --report report.json

Uses isolated temporary data, disables web search, and needs no pytest fixtures.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CLAIM = "телесный опыт: rest повышает энергию ниже потолка"


def model_snapshot(agent):
    concepts = agent.mental_models.concepts
    node = concepts.get(CLAIM)
    return {
        "concept_count": len(concepts),
        "total_experiences": sum(len(item.experiences) for item in concepts.values()),
        "claim": None if node is None else {
            "name": CLAIM,
            "confidence": node.confidence,
            "evidence_strength": node.evidence()[0],
            "evidence_agreement": node.evidence()[1],
            "signed_observation_evidence": sum(
                exp.get("evidence_strength", 0.0) * exp.get("evidence_direction", 1)
                for exp in node.experiences
                if exp.get("evidence_kind") == "observation"
            ),
            "experiences": deepcopy(node.experiences),
        },
    }


def measure_agent(enabled, agent_class, expectations_class, config):
    def run():
        agent = agent_class(name="ActionExpectationEnabled" if enabled else "ActionExpectationBaseline")
        initial = model_snapshot(agent)
        rows = []

        def rest(phase):
            agent.energy = 20
            outcome = agent.act("rest")
            rows.append({
                "trial_number": len(rows) + 1,
                "phase": phase,
                "energy_before": 20,
                "energy_after": float(agent.energy),
                "actual_delta": float(agent.energy) - 20,
                "action_result": outcome,
                "last_trial": deepcopy(agent.action_expectations.last_trial),
                "model": model_snapshot(agent),
            })

        for _ in range(2):
            rest("normal_recovery")
        with patch.object(agent, "_recover_energy", return_value=0.0):
            for _ in range(4):
                rest("zero_recovery")

        before_ceiling = model_snapshot(agent)
        previous_trial = deepcopy(agent.action_expectations.last_trial)
        agent.energy = config.ENERGY_MAX
        ceiling_result = agent.act("rest")
        after_ceiling = model_snapshot(agent)
        ceiling = {
            "energy_before": float(config.ENERGY_MAX),
            "energy_after": float(agent.energy),
            "action_result": ceiling_result,
            "last_trial_before": previous_trial,
            "last_trial_after": deepcopy(agent.action_expectations.last_trial),
            "no_new_trial": (
                agent.action_expectations.last_trial is None
                or (previous_trial is not None and
                    agent.action_expectations.last_trial["trial_id"] == previous_trial["trial_id"])
            ),
            "no_new_model_experience": before_ceiling == after_ceiling,
        }
        return {
            "observation_hook_enabled": enabled,
            "web_disabled": agent.web_searcher is None,
            "initial_model": initial,
            "trials": rows,
            "ceiling": ceiling,
            "final_model": after_ceiling,
            "experience_growth": after_ceiling["total_experiences"] - initial["total_experiences"],
        }

    if enabled:
        return run()
    with patch.object(expectations_class, "begin", return_value=None):
        return run()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="UTF-8 JSON output path")
    args = parser.parse_args()
    sys.path.insert(0, str(PROJECT_ROOT))
    preferred_temp = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp" / "opencode"
    temp_parent = str(preferred_temp) if preferred_temp.is_dir() else None
    with tempfile.TemporaryDirectory(prefix="db_action_expectation_", dir=temp_parent) as data_dir:
        # Set isolation before importing any agent/path module.
        with patch.dict(os.environ, {"DIGITAL_BEING_DATA_DIR": data_dir, "DIGITAL_BEING_TEST_MODE": "1"}):
            from config.simulation_config import LR_CONFIG
            from src.cognition.action_expectations import ActionExpectations
            from src.core.agent import DigitalBeing

            original_begin = ActionExpectations.begin
            with patch.object(LR_CONFIG, "WEB_SEARCH_ENABLED", False):
                baseline = measure_agent(False, DigitalBeing, ActionExpectations, LR_CONFIG)
                enabled = measure_agent(True, DigitalBeing, ActionExpectations, LR_CONFIG)
            baseline_deltas = [row["actual_delta"] for row in baseline["trials"]]
            enabled_deltas = [row["actual_delta"] for row in enabled["trials"]]
            report = {
                "data_dir": data_dir,
                "temporary_data_removed_on_exit": True,
                "baseline": baseline,
                "enabled": enabled,
                "comparison": {
                    "baseline_deltas": baseline_deltas,
                    "enabled_deltas": enabled_deltas,
                    "same_physical_outcomes": baseline_deltas == enabled_deltas,
                    "baseline_experience_growth": baseline["experience_growth"],
                    "enabled_experience_growth": enabled["experience_growth"],
                    "expected_directions": [row["last_trial"]["expected_direction"] for row in enabled["trials"]],
                    "prediction_matches": [row["last_trial"]["prediction_matched"] for row in enabled["trials"]],
                    "confidences": [row["model"]["claim"]["confidence"] for row in enabled["trials"]],
                    "evidence_strengths": [row["model"]["claim"]["evidence_strength"] for row in enabled["trials"]],
                    "begin_restored": ActionExpectations.begin is original_begin,
                },
            }
            checks = {
                "web_disabled": baseline["web_disabled"] and enabled["web_disabled"],
                "baseline_has_no_trials": all(row["last_trial"] is None for row in baseline["trials"]),
                "same_physical_outcomes": baseline_deltas == enabled_deltas,
                "six_enabled_trials": len({row["last_trial"]["trial_id"] for row in enabled["trials"]}) == 6,
                "prediction_revised": enabled["trials"][-1]["last_trial"]["expected_direction"] == -1,
                "normal_recovery_positive": all(delta > 0 for delta in enabled_deltas[:2]),
                "patched_recovery_zero": enabled_deltas[2:] == [0.0, 0.0, 0.0, 0.0],
                "ceiling_no_new_trial": baseline["ceiling"]["no_new_trial"] and enabled["ceiling"]["no_new_trial"],
                "ceiling_no_new_experience": baseline["ceiling"]["no_new_model_experience"] and enabled["ceiling"]["no_new_model_experience"],
                "begin_restored": ActionExpectations.begin is original_begin,
            }
            report["checks"] = checks
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report["comparison"], ensure_ascii=True, indent=2))
            print(f"Report: {args.report}")
            if not all(checks.values()):
                raise SystemExit("Measurement checks failed; inspect the report")


if __name__ == "__main__":
    main()
