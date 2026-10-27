"""Контроль отдельного игрового действия и кандидата, без требования учиться."""

import argparse
import json
import os
from pathlib import Path
import random
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def measure():
    from src.core.agent import DigitalBeing
    from src.core.subsystems.decision_arbitrator import DecisionArbitrator

    random.seed(1)
    agent = DigitalBeing(name="PlayMeasure")
    system = agent.motivation_system
    for need in system.needs.values():
        need.current_level = need.base_level
    for drive in system.drives.values():
        drive.current_level = 0
    system.needs["play"].current_level = 0
    candidate = next(c for c in system.get_action_candidates({}) if c["action"] == "play")
    before = agent.mental_models.to_storage_dict()
    energy_before = agent.energy
    play_before = system.needs["play"].current_level
    boards = []
    for _ in range(3):
        agent.act("play")
        boards.append(dict(agent._last_play_result))
    verdict = {"score": 0.5, "verdict": "proceed", "confidence": 0.5, "reasoning": "controlled", "voices": {}}
    choices = []
    with patch.object(agent.decision_arbitrator, "arbitrate", return_value=verdict):
        for strength in (0.1, 1.0):
            other = {"action": "communicate", "source": "other_desire", "strength": strength}
            choices.append({"other_strength": strength,
                            "winner": agent.decision_arbitrator.choose_action([candidate, other], {})["action"]})
    return {"candidate": candidate, "turns": boards, "knowledge_unchanged": before == agent.mental_models.to_storage_dict(),
            "energy_spent": energy_before - agent.energy, "play_before": play_before,
            "play_after": system.needs["play"].current_level, "controlled_choices": choices}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="db_local_play_") as directory:
        os.environ["DIGITAL_BEING_DATA_DIR"] = directory
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        from config.simulation_config import LR_CONFIG
        LR_CONFIG.WEB_SEARCH_ENABLED = False
        result = measure()
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True, indent=2))
