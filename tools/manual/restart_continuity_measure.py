"""Обычный запуск: действие → остановка раннера → повторный create_agent.

python tools/manual/restart_continuity_measure.py --report PATH
Данные изолированы, сеть выключена. Вывод фиксирует факты без подгонки
порогов: до исправления lost_experiences > 0, после ожидается 0.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def measure():
    from src.app.bootstrap import create_agent
    from src.app.paths import setup_environment
    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    env = setup_environment(chdir=False)
    first, _ = create_agent(env, "ContinuityMeasure", new=True)
    first.energy = 20
    first.cycle_count = 17
    # Контролируемый разрыв ожидания без изменения самого пути act().
    with patch.object(first, "_recover_energy", return_value=0.0):
        first.act("rest")
    observed = first.action_expectations.last_trial
    claim = observed["claim"]
    before = first.mental_models.concepts[claim].to_storage_dict()
    pending = first.action_expectations.begin(first.mental_models, "rest", first.energy, 200)
    runner = AgentRunner(first, EventBus(), name="ContinuityMeasureRunner")
    saved = runner.save_now()
    second, report = create_agent(env, "ContinuityMeasure")
    node = second.mental_models.concepts.get(claim)
    after = node.to_storage_dict() if node else None
    second.act("rest")
    next_observation = second.action_expectations.last_trial
    fresh, fresh_report = create_agent(env, "ContinuityMeasure", new=True)
    return {
        "saved": saved, "startup_source": report["source"],
        "cycle_before": first.cycle_count, "cycle_after": second.cycle_count,
        "energy_before_restart": first.energy,
        "energy_after_restart": next_observation["energy_before"],
        "experiences_before": len(before["experiences"]),
        "experiences_restored": len(after["experiences"]) if after else 0,
        "lost_experiences": len(before["experiences"]) - (len(after["experiences"]) if after else 0),
        "evidence_before": before["experiences"][-1],
        "memory_identical": before == after,
        "next_expected_direction": next_observation["expected_direction"],
        "unfinished_trial_id": pending.trial_id,
        "next_trial_id": next_observation["trial_id"],
        "new_life_source": fresh_report["source"],
        "new_life_has_previous_claim": claim in fresh.mental_models.concepts,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="db_restart_measure_") as directory:
        os.environ["DIGITAL_BEING_DATA_DIR"] = directory
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        from config.simulation_config import LR_CONFIG

        with patch.object(LR_CONFIG, "WEB_SEARCH_ENABLED", False):
            result = asyncio.run(measure())
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True, indent=2))
        import logging

        logging.shutdown()
