"""Measure save -> profile backup -> restore -> create_agent continuity.

python tools/manual/backup_life_measure.py --report PATH

Four isolated JSON/SQLite, awake/dormant cases; no network or live profile use.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def checkpoint_bytes(profile):
    directory = profile / "checkpoints"
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.suffix != ".log" and "logs" not in path.parts
        and not path.name.endswith(("-wal", "-shm", "-journal"))
    }


def fingerprints(files):
    return {
        name: {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        for name, content in files.items()
    }


def snapshot(agent):
    return deepcopy({
        "mental_models": agent.mental_models.to_storage_dict(),
        "energy": agent.energy,
        "fatigue": agent.interoception.state.fatigue,
        "cycle": agent.cycle_count,
        "life_guard": agent.life_guard.state_details(),
    })


async def measure_case(root, backend, dormant):
    from config.simulation_config import SIM_CONFIG
    from src.app.bootstrap import create_agent
    from src.app.paths import setup_environment
    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus
    from src.core.subsystem_base import PluginRegistry
    from src.memory.profile_backup import create_backup, restore_backup, verify_backup

    case_name = f"{backend}_{'dormant' if dormant else 'awake'}"
    source = root / case_name / "source"
    backup = root / case_name / "backup"
    restored = root / case_name / "restored"
    name = "BackupLifeMeasure"
    with patch.object(SIM_CONFIG, "CHECKPOINT_BACKEND", backend):
        os.environ["DIGITAL_BEING_DATA_DIR"] = str(source)
        env = setup_environment(chdir=False, console=False)
        PluginRegistry.reset_global()
        first, _ = create_agent(env, name, new=True)
        first.energy = 20
        first.interoception.state.fatigue = 0.8
        first.cycle_count = 41
        with patch.object(first, "_recover_energy", return_value=0.0):
            action = first.act("rest")
        observation = deepcopy(first.action_expectations.last_trial)
        first.life_guard.set_state(
            "dormant" if dormant else "alive", reason="isolated backup measurement"
        )
        before = snapshot(first)
        runner = AgentRunner(first, EventBus(), name=case_name)
        saved = runner.save_now()
        original = checkpoint_bytes(source)
        create_backup(source, backup)
        manifest = verify_backup(backup)
        destination_was_new = not restored.exists()
        restore_backup(backup, restored)
        os.environ["DIGITAL_BEING_DATA_DIR"] = str(restored)
        restored_env = setup_environment(chdir=False, console=False)
        PluginRegistry.reset_global()
        second, startup = create_agent(restored_env, name)
        after = snapshot(second)
        restored_runner = AgentRunner(second, EventBus(), name=case_name + "_restored")
        next_observation = None
        execution_count = 0
        # The runner's life gate must be checked before any action is executed.
        with patch.object(second, "act", wraps=second.act) as execute_action:
            if restored_runner._agent_is_alive():
                with patch.object(second, "_recover_energy", return_value=0.0):
                    second.act("rest")
                next_observation = deepcopy(second.action_expectations.last_trial)
            execution_count = execute_action.call_count
        final = checkpoint_bytes(source)
        checks = {
            "network_disabled": first.web_searcher is None and second.web_searcher is None,
            "saved": saved,
            "checkpoint_present": bool(original),
            "backend_matches": (
                any(name.endswith(".sqlite3") for name in original)
                if backend == "sqlite" else
                any(name.endswith((".json", ".json.gz")) for name in original)
                and not any(name.endswith(".sqlite3") for name in original)
            ),
            "controlled_body_experience": (
                observation is not None and observation["energy_before"] == 20
                and observation["energy_after"] == 20
                and observation["fatigue_before"] == 0.8
            ),
            "destination_was_new": destination_was_new,
            "backup_complete": manifest["complete"] is True,
            "startup_from_checkpoint": startup["source"] == "checkpoint",
            "mental_models_identical": before["mental_models"] == after["mental_models"],
            "energy_identical": before["energy"] == after["energy"] == 20,
            "fatigue_identical": before["fatigue"] == after["fatigue"],
            "cycle_identical": before["cycle"] == after["cycle"] == 41,
            "life_guard_identical": before["life_guard"] == after["life_guard"],
            "life_state_correct": second.life_guard.load_state() == ("dormant" if dormant else "alive"),
            "next_action_correct": (
                execution_count == 0 and next_observation is None and snapshot(second) == after
                if dormant else execution_count == 1 and next_observation is not None
                and next_observation["expected_direction"] == -1
            ),
            "source_checkpoints_bytes_unchanged": original == final,
        }
        return {
            "case": case_name, "backend": backend, "dormant": dormant,
            "source": str(source), "backup": str(backup), "restored": str(restored),
            "action": action, "original_observation": observation,
            "before": before, "after": after, "startup": startup,
            "next_observation": next_observation, "execution_count": execution_count,
            "source_checkpoints_before": fingerprints(original),
            "source_checkpoints_after": fingerprints(final),
            "backup_file_count": len(manifest["files"]),
            "checks": checks, "passed": all(checks.values()),
        }


async def measure(root):
    cases = []
    for backend in ("json", "sqlite"):
        for dormant in (False, True):
            try:
                cases.append(await measure_case(root, backend, dormant))
            except Exception:
                cases.append({
                    "case": f"{backend}_{'dormant' if dormant else 'awake'}",
                    "backend": backend, "dormant": dormant, "passed": False,
                    "error": traceback.format_exc(),
                })
    return {"cases": cases, "passed": all(case["passed"] for case in cases)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(PROJECT_ROOT))
    preferred_temp = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp" / "opencode"
    temp_parent = str(preferred_temp) if preferred_temp.is_dir() else None
    with tempfile.TemporaryDirectory(prefix="db_backup_life_", dir=temp_parent) as directory:
        try:
            with patch.dict(os.environ, {
                "DIGITAL_BEING_DATA_DIR": directory, "DIGITAL_BEING_TEST_MODE": "1",
            }):
                from config.simulation_config import LR_CONFIG

                with asyncio.Runner() as async_runner:
                    async_runner.get_loop()
                    with patch.object(LR_CONFIG, "WEB_SEARCH_ENABLED", False), \
                            patch("socket.socket.connect", side_effect=OSError("Network disabled for measurement")), \
                            patch("socket.create_connection", side_effect=OSError("Network disabled for measurement")):
                        report = async_runner.run(measure(Path(directory)))
        finally:
            logging.shutdown()
    report["source_checkpoint_comparison"] = {
        "method": "exact bytes and file set; SHA-256 fingerprints included",
        "excluded": ["logs", "*.log", "SQLite transient -wal/-shm/-journal sidecars"],
    }
    report["temporary_data_removed"] = not Path(directory).exists()
    report["passed"] = report["passed"] and report["temporary_data_removed"]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": report["passed"],
        "cases": [{"case": case["case"], "passed": case["passed"],
                   "failed_checks": [key for key, value in case.get("checks", {}).items() if not value],
                   "error": case.get("error")} for case in report["cases"]],
        "report": str(args.report),
    }, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
