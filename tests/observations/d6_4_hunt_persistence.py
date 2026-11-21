"""D6-4 differential observation; never writes to the live data directory."""

from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
os.environ["VOICE_CONSOLE_QUIET"] = "1"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.observations import d5_curiosity as d5  # noqa: E402
from src.core.checkpoint_serializer import (  # noqa: E402
    CheckpointSerializer,
    apply_state_to_agent,
    build_state_from_agent,
)


def restart_boundary() -> dict:
    d5.use_sandbox("additional/restart_boundary")
    first = d5.new_agent("D64Boundary", without_active_goal=True)
    initial = d5.controlled_search(
        first,
        10,
        source="d6_4_initial_miss",
        response=d5.miss_response(),
    )
    first.cycle_count = 209
    checkpoint = first.save_state(force=True)
    snapshot = CheckpointSerializer().load(checkpoint)
    restored = d5.new_agent("D64BoundaryRestored", without_active_goal=True)
    apply_state_to_agent(restored, snapshot)
    restored_trace = deepcopy(restored._hunt_misses)
    before = d5.controlled_search(
        restored,
        209,
        source="d6_4_restart_before_boundary",
        response=d5.memory_success_response(),
    )
    at = d5.controlled_search(
        restored,
        210,
        source="d6_4_restart_at_boundary",
        response=d5.miss_response(),
    )
    return {
        "initial": initial,
        "restored_trace": restored_trace,
        "difference_199": before,
        "difference_200": at,
    }


def without_restart() -> dict:
    d5.use_sandbox("additional/without_restart")
    agent = d5.new_agent("D64NoRestart", without_active_goal=True)
    initial = d5.controlled_search(
        agent,
        10,
        source="d6_4_no_restart_initial",
        response=d5.miss_response(),
    )
    before = d5.controlled_search(
        agent,
        209,
        source="d6_4_no_restart_before_boundary",
        response=d5.memory_success_response(),
    )
    at = d5.controlled_search(
        agent,
        210,
        source="d6_4_no_restart_at_boundary",
        response=d5.miss_response(),
    )
    return {"initial": initial, "difference_199": before, "difference_200": at}


def legacy_restore() -> dict:
    d5.use_sandbox("additional/legacy")
    first = d5.new_agent("D64Legacy", without_active_goal=True)
    first.cycle_count = 20
    first._hunt_misses = {"saved elsewhere": 10}
    state = build_state_from_agent(first)
    state.pop("hunt_misses", None)
    restored = d5.new_agent("D64LegacyRestored", without_active_goal=True)
    restored._hunt_misses = {"stale": 1}
    apply_state_to_agent(restored, state)
    return {"legacy_field_absent": True, "restored_trace": restored._hunt_misses}


def outcome_controls() -> dict:
    d5.use_sandbox("additional/outcome_controls")
    results = {}
    for name, controls in (
        ("success", {"response": d5.memory_success_response()}),
        ("exception", {"search_error": RuntimeError("controlled failure")}),
        ("disabled", {"search_enabled": False}),
        ("denied", {"denied": True}),
    ):
        agent = d5.new_agent(f"D64Outcome{name}", without_active_goal=True)
        agent._hunt_misses = {"память": 10, "другая тема": 10}
        results[name] = d5.controlled_search(
            agent,
            210,
            source=f"d6_4_{name}",
            **controls,
        )

    other = d5.new_agent("D64OtherTopic", without_active_goal=True)
    other._hunt_misses = {"память": 10}
    results["other_topic"] = d5.controlled_search(
        other,
        11,
        source="d6_4_other_topic",
        target="новая тема",
        response=d5.miss_response(),
    )
    return results


def compact() -> dict:
    return {
        "d5_06": d5.observe_d5_06(),
        "d5_07": d5.observe_d5_07(),
        "restart_boundary": restart_boundary(),
        "without_restart": without_restart(),
        "legacy_restore": legacy_restore(),
        "outcome_controls": outcome_controls(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    observation_root = PROJECT_ROOT / "tmp" / "motivation_d6_4" / "runs" / args.label
    observation_root.mkdir(parents=True, exist_ok=True)
    d5.OBSERVATION_ROOT = observation_root / "d5"
    os.environ["DIGITAL_BEING_DATA_DIR"] = str(observation_root / "bootstrap")
    result = {
        "schema": "d6_4_hunt_persistence_differential_v1",
        "label": args.label,
        "observation_root": str(observation_root),
        "real_network_used": False,
        "results": compact(),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"label={args.label} output={args.output.resolve()}")


if __name__ == "__main__":
    main()
