"""Изолированный замер конкуренции желания проверки с иным побуждением."""

import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.cognition.mental_models import MentalModel
from src.cognition.empirical_claims import get_body_claim
from src.cognition.experiment_proposals import propose_experiment
from src.core.subsystems.decision_arbitrator import DecisionArbitrator


def measure():
    model = MentalModel()
    claim = get_body_claim(model, "rest", "energy")
    options = dict(energy=80, energy_max=200, fatigue=0.2, cycle=25)
    candidate = propose_experiment(model, **options)
    arbiter = DecisionArbitrator()
    verdict = dict(score=0.5, verdict="proceed", confidence=0.5, reasoning="controlled", voices={})
    rows = []
    with patch.object(arbiter, "arbitrate", return_value=verdict):
        for strength in (0.1, 1.0):
            other = dict(source="other_desire", action="communicate", strength=strength)
            before = arbiter.choose_action([other], {})
            after = arbiter.choose_action([other, candidate], {})
            rows.append(dict(other_strength=strength, before=before["source"], after=after["source"]))
    for index in range(3):
        claim.observe(f"action:{index}", 80, 80, False, context="trial")
    return dict(choices=rows, confident_refutation=claim.conclusion(),
                proposed_after_refutation=propose_experiment(model, **options),
                uninformative_ceiling=propose_experiment(model, **(options | {"energy": 200})))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = measure()
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))
