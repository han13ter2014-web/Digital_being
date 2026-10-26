"""Один реальный отдых, два независимых вывода, обычный повторный запуск."""

import argparse
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="db_claim_measure_") as directory:
        os.environ["DIGITAL_BEING_DATA_DIR"] = directory
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        from config.simulation_config import LR_CONFIG
        from src.app.bootstrap import create_agent
        from src.app.paths import setup_environment

        with patch.object(LR_CONFIG, "WEB_SEARCH_ENABLED", False):
            env = setup_environment(chdir=False)
            first, _ = create_agent(env, "ClaimsMeasure", new=True)
            first.energy = 20
            first.interoception.state.fatigue = 0.8
            fatigue_before = first.interoception.state.fatigue
            with patch.object(first, "_recover_energy", return_value=0.0):
                first.act("rest")
            initial = dict(first.action_expectations.last_trial)
            stored = {key: claim.to_dict() for key, claim in first.mental_models.claims.items()}
            first.save_state(force=True)
            second, startup = create_agent(env, "ClaimsMeasure")
            restored = {key: claim.to_dict() for key, claim in second.mental_models.claims.items()}
            second.act("rest")
            result = {"startup": startup["source"], "energy_delta": initial["delta"],
                      "fatigue_before": fatigue_before, "fatigue_after": initial["fatigue_after"],
                      "conclusions": initial["claims"], "restored_identically": stored == restored,
                      "next_energy_expectation": second.action_expectations.last_trial["expected_direction"],
                      "next_fatigue_expectation": second.action_expectations.last_trial["fatigue_expected_direction"]}
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result, ensure_ascii=True, indent=2))
        logging.shutdown()


if __name__ == "__main__":
    main()
