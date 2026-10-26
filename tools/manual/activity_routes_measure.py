"""Куда ведут существующие побуждения, без подмены арбитра и выполнения действий.

Изолированные дефициты — причинный контроль генератора, не естественная жизнь.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def measure():
    from src.core.agent import DigitalBeing
    from src.core.subsystem_base import PluginRegistry
    from src.core.motivation.unified_motivation import ACTION_ALIASES

    PluginRegistry.reset_global()
    agent = DigitalBeing(name="ActivityRoutes")
    rows = []
    motivation = agent.motivation_system
    for target in motivation.needs:
        for need in motivation.needs.values():
            need.current_level = need.base_level
        motivation.needs[target].current_level = 0.0
        # Отключённые в контроле драйвы не маскируют причинную связь need→hint.
        for drive in motivation.drives.values():
            drive.current_level = 0.0
        candidates = motivation.get_action_candidates({"energy": agent.energy, "cycle": 100})
        rows.append({"need": target, "candidates": [
            {"hint": c["action"], "handler": agent._normalize_action(c["action"]),
             "params": c.get("params"), "strength": c["strength"]}
            for c in candidates if c.get("need") == target]})
    for need in motivation.needs.values():
        need.current_level = need.base_level
    for drive in motivation.drives.values():
        drive.current_level = 0.0
    default = motivation.get_action_candidates({})
    PluginRegistry.reset_global()
    return {"isolated_needs": rows, "no_pressing_needs": default,
            "research_feedback_aliases": {key: ACTION_ALIASES[key] for key in ("explore", "synthesis", "know_answer")},
            "limits": "Generator routes only; no execution, no sentience or diversity claims"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="db_activity_routes_") as directory:
        os.environ["DIGITAL_BEING_DATA_DIR"] = directory
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        from config.simulation_config import LR_CONFIG
        LR_CONFIG.WEB_SEARCH_ENABLED = False
        result = measure()
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True, indent=2))
