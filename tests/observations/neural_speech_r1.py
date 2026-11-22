"""R1 controlled observation на настоящем production SQLite response-журнале.

Не читает живую биографию, не обучает модель и не меняет активные ответы.
Запуск из корня репозитория:
    .venv/Scripts/python.exe tests/observations/neural_speech_r1.py \
        --label controlled --output tmp/neural_speech_r1/report.json
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import tracemalloc
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBSERVATION_ROOT = PROJECT_ROOT / "tmp" / "neural_speech_r1"
os.environ.setdefault("DIGITAL_BEING_DATA_DIR", str(OBSERVATION_ROOT / "bootstrap"))
os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
os.environ["VOICE_CONSOLE_QUIET"] = "1"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.dialogue_acts import (  # noqa: E402
    ACT_ANSWER,
    ACT_FOLLOW_UP,
    ACT_SOCIAL,
    ACT_UNKNOWN,
)
from src.core.response_experience import ResponseExperience  # noqa: E402
from src.core.response_experience_journal import (  # noqa: E402
    ResponseExperienceJournal,
)
from src.core.response_shadow_inventory import (  # noqa: E402
    assess_readiness,
    inventory_events,
    samples_from_events,
    temporal_split,
)
from tests.observations.re_s1_response_experience import (  # noqa: E402
    CONTROLLED_SCHEDULE,
    evaluate_baselines,
    fit_baselines,
    predict_baseline,
)

LIFE_ID = "00000000-0000-4000-8000-000000000101"
SECOND_LIFE_ID = "00000000-0000-4000-8000-000000000102"
WRITE_PAIR_P95_BUDGET_MS = 250.0
WRITE_PAIR_MAX_BUDGET_MS = 1000.0
ARTIFACT_BUDGET_BYTES = 4 * 1024 * 1024
TRACEMALLOC_BUDGET_BYTES = 16 * 1024 * 1024

_ACT_BY_OUTCOME = {
    "answer": ACT_ANSWER,
    "follow_up": ACT_FOLLOW_UP,
    "unclassified_reply": ACT_UNKNOWN,
    "ordinary_reply": ACT_SOCIAL,
}


def _prepare_and_deliver(
    experience,
    journal,
    agent,
    *,
    response_id,
    context,
    cycle,
    turn_id,
):
    agent.cycle_count = cycle
    prepared = experience.prepare_plan(
        agent,
        f"Контролируемая реплика: {context}.",
        context=context,
        source="core",
        user_text="Контролируемый вход; не реальная биография",
    )
    record = experience.register_delivery(response_id, prepared["plan"], cycle)
    written = journal.record_delivery(experience, record, cycle=cycle, turn_id=turn_id)
    if written is None:
        raise RuntimeError("controlled delivery was not journaled")
    return record


def _observe(experience, journal, *, response_id, outcome, cycle, turn_id):
    if outcome in {"explicit_support", "explicit_opposition"}:
        feedback = "support" if outcome == "explicit_support" else "opposition"
        record = experience.observe_feedback(
            response_id, feedback, cycle, language_id="ru"
        )
    else:
        pending = experience.latest_pending(language_id="ru")
        if pending is None or pending["response_id"] != response_id:
            raise RuntimeError("controlled observation would close another response")
        record = experience.observe_reply(
            _ACT_BY_OUTCOME[outcome], cycle, language_id="ru"
        )
    if record is None or record["outcome"] != outcome:
        raise RuntimeError("real ResponseExperience produced an unexpected outcome")
    written = journal.record_transition("outcome", record, cycle=cycle, turn_id=turn_id)
    if written is None:
        raise RuntimeError("controlled outcome was not journaled")


def controlled_production_history(root: Path, life_id=LIFE_ID) -> dict:
    """Создать sandbox SQLite через реальные production transitions."""
    path = root / "lives" / life_id / "response_experience_events.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    journal = ResponseExperienceJournal(path, life_id)
    experience = ResponseExperience()
    agent = SimpleNamespace(
        cycle_count=0,
        social_registry=SimpleNamespace(current_profile_id="owner"),
        social_attribution=None,
    )
    write_pair_ms = []
    try:
        for index, (context, outcome) in enumerate(CONTROLLED_SCHEDULE):
            response_id = f"controlled-{index:02d}"
            started = time.perf_counter()
            _prepare_and_deliver(
                experience,
                journal,
                agent,
                response_id=response_id,
                context=context,
                cycle=index * 2,
                turn_id=f"delivery-{index:02d}",
            )
            _observe(
                experience,
                journal,
                response_id=response_id,
                outcome=outcome,
                cycle=index * 2 + 1,
                turn_id=f"outcome-{index:02d}",
            )
            write_pair_ms.append((time.perf_counter() - started) * 1000)
        _prepare_and_deliver(
            experience,
            journal,
            agent,
            response_id="control-expired",
            context="social_reply",
            cycle=100,
            turn_id="delivery-expired",
        )
        if experience.expire(151) != 1:
            raise RuntimeError("controlled expiry did not occur")
        expired = experience.responses["control-expired"]
        journal.record_transition("expired", expired, cycle=151, turn_id=None)
        _prepare_and_deliver(
            experience,
            journal,
            agent,
            response_id="control-pending",
            context="social_reply",
            cycle=200,
            turn_id="delivery-pending",
        )
        events = journal.events()
        journal_status = journal.get_status()
    finally:
        journal.close()
    return {
        "events": events,
        "write_pair_ms": write_pair_ms,
        "artifact_bytes": path.stat().st_size,
        "journal_status": journal_status,
        "integrity_after_close": journal.integrity_after_close(),
    }


def _mark_small_slices(metrics: dict) -> dict:
    result = deepcopy(metrics)
    for baseline in result.values():
        overall = baseline["overall"]
        overall["data_status"] = (
            "ok" if overall["examples"] >= 5 else "insufficient_data"
        )
        for field_values in baseline["slices"].values():
            for slice_metrics in field_values.values():
                slice_metrics["data_status"] = (
                    "ok" if slice_metrics["examples"] >= 5 else "insufficient_data"
                )
    return result


def evaluate_history(history: dict, life_id=LIFE_ID) -> dict:
    events = history["events"]
    inventory = inventory_events(events, life_id=life_id)
    split = temporal_split(events, life_id=life_id)
    train_all = samples_from_events(
        events, life_id=life_id, episode_ids=set(split["train"])
    )
    train = samples_from_events(
        events,
        life_id=life_id,
        episode_ids=set(split["train"]),
        outcome_before_sequence=split["train_outcome_before_sequence"],
    )
    validation = samples_from_events(
        events, life_id=life_id, episode_ids=set(split["validation"])
    )
    held_out = samples_from_events(
        events, life_id=life_id, episode_ids=set(split["held_out"])
    )
    model = fit_baselines(train, life_id=life_id)
    readiness = assess_readiness(
        inventory,
        split,
        events,
        life_id=life_id,
        confirmed_intent_labels=0,
        semantic_plan_labels=0,
    )
    return {
        "inventory": inventory,
        "split": split,
        "samples": {
            "train_all": train_all,
            "train": train,
            "validation": validation,
            "held_out": held_out,
        },
        "validation": _mark_small_slices(evaluate_baselines(model, validation)),
        "held_out": _mark_small_slices(evaluate_baselines(model, held_out)),
        "readiness": readiness,
    }


def _semantic_projection(events: list[dict]) -> list[dict]:
    """Сравнивать факты без random journal start/stop IDs и hash-chain."""
    return [
        {
            "event_kind": event["event_kind"],
            "event_sequence": event["event_sequence"],
            "life_id": event["life_id"],
            "profile_id": event["profile_id"],
            "cycle": event["cycle"],
            "turn_id": event["turn_id"],
            "episode_id": event["episode_id"],
            "response_id": event["response_id"],
            "payload": event["payload"],
        }
        for event in events
        if event["event_kind"] in {"delivery", "outcome", "expired"}
    ]


def _live_data_manifest() -> dict:
    """Только metadata; содержимое живой биографии не читается."""
    root = PROJECT_ROOT / "data"
    rows = []
    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            rows.append((str(path.relative_to(root)), stat.st_size, stat.st_mtime_ns))
    digest = hashlib.sha256(
        json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"files": len(rows), "metadata_sha256": digest}


def _revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _percentile95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = math.ceil(len(ordered) * 0.95) - 1
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run_root = OBSERVATION_ROOT / "runs" / args.label
    os.environ["DIGITAL_BEING_DATA_DIR"] = str(run_root / "data")
    live_before = _live_data_manifest()
    tracemalloc.start()
    started = time.perf_counter()
    first_history = controlled_production_history(run_root / "first")
    first = evaluate_history(first_history)
    second_history = controlled_production_history(run_root / "second")
    second = evaluate_history(second_history)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    empty_model = fit_baselines([], life_id=SECOND_LIFE_ID)
    empty_distribution = predict_baseline(
        empty_model,
        "B0",
        {
            "life_id": SECOND_LIFE_ID,
            "profile_id": "owner",
            "context": "social_reply",
            "response_language": "ru",
        },
    )
    write_pairs = first_history["write_pair_ms"] + second_history["write_pair_ms"]
    p95 = _percentile95(write_pairs)
    max_write = max(write_pairs, default=0.0)
    max_artifact = max(
        first_history["artifact_bytes"], second_history["artifact_bytes"]
    )
    resources = {
        "scope": "two controlled production-SQLite observations; no neural model",
        "write_pair_examples": len(write_pairs),
        "write_pair_p95_ms": p95,
        "write_pair_p95_budget_ms": WRITE_PAIR_P95_BUDGET_MS,
        "write_pair_p95_within_budget": p95 < WRITE_PAIR_P95_BUDGET_MS,
        "write_pair_max_ms": max_write,
        "write_pair_max_budget_ms": WRITE_PAIR_MAX_BUDGET_MS,
        "write_pair_max_within_budget": max_write < WRITE_PAIR_MAX_BUDGET_MS,
        "write_pair_mean_ms": statistics.mean(write_pairs) if write_pairs else 0.0,
        "artifact_max_bytes": max_artifact,
        "artifact_budget_bytes": ARTIFACT_BUDGET_BYTES,
        "artifact_within_budget": max_artifact < ARTIFACT_BUDGET_BYTES,
        "tracemalloc_peak_bytes": peak,
        "tracemalloc_budget_bytes": TRACEMALLOC_BUDGET_BYTES,
        "tracemalloc_within_budget": peak < TRACEMALLOC_BUDGET_BYTES,
        "elapsed_seconds": elapsed,
    }
    resources["within_budget"] = all(
        resources[key]
        for key in (
            "write_pair_p95_within_budget",
            "write_pair_max_within_budget",
            "artifact_within_budget",
            "tracemalloc_within_budget",
        )
    )
    result = {
        "schema": "neural_speech_r1_controlled_v1",
        "label": args.label,
        "revision": _revision(),
        "synthetic_controlled_events": True,
        "real_biography_used": False,
        "network_used": False,
        "model_trained": False,
        "active_response_path_changed": False,
        "shadow_prediction_writer_created": False,
        "production_journal_used_in_sandbox": True,
        "inventory": first["inventory"],
        "temporal": {
            "strategy": "whole episodes, chronological 60/20/20",
            "split_counts": first["split"]["split_counts"],
            "train_observed_total": len(first["samples"]["train_all"]),
            "train_eligible_before_cut": len(first["samples"]["train"]),
            "train_late_outcomes_excluded": len(first["samples"]["train_all"])
            - len(first["samples"]["train"]),
            "validation_observed": len(first["samples"]["validation"]),
            "held_out_observed": len(first["samples"]["held_out"]),
            "train_outcome_before_sequence": first["split"][
                "train_outcome_before_sequence"
            ],
            "held_out_start_sequence": first["split"]["held_out_start_sequence"],
        },
        "validation": first["validation"],
        "held_out": first["held_out"],
        "determinism": {
            "same_delivery_outcome_projection": _semantic_projection(
                first_history["events"]
            )
            == _semantic_projection(second_history["events"]),
            "same_inventory": first["inventory"] == second["inventory"],
            "same_held_out_metrics": first["held_out"] == second["held_out"],
            "random_journal_envelope_compared": False,
        },
        "second_life": {
            "registered": 0,
            "training_examples": empty_model["sample_count"],
            "empty_b0_is_uniform": all(
                math.isclose(value, 1 / 6) for value in empty_distribution
            ),
            "inherited_weights_or_statistics": False,
        },
        "resources": resources,
        "journal_integrity": {
            "first": first_history["integrity_after_close"],
            "second": second_history["integrity_after_close"],
            "first_writer_status": first_history["journal_status"]["status"],
            "second_writer_status": second_history["journal_status"]["status"],
        },
        "real_data_inventory": {
            "status": "not_collected_from_live_biography",
            "live_content_read": False,
            "reason": "R1 controlled run does not inspect live data content",
            "existing_contract_provides_outcome_examples": True,
            "confirmed_intent_labels_in_existing_contract": 0,
            "human_confirmed_semantic_plans_in_existing_contract": 0,
            "raw_text_exported": False,
        },
        "readiness": first["readiness"],
        "decision": {
            "status": "insufficient_data",
            "r2_training_started": False,
            "reason": (
                "Outcome events support simple baselines, but the existing contract "
                "has no human-confirmed paraphrase intent labels or semantic plans; "
                "the controlled held-out is also below candidate thresholds."
            ),
            "baseline_remains": True,
        },
        "live_data": {
            "metadata_before": live_before,
            "metadata_after": _live_data_manifest(),
        },
    }
    result["live_data"]["metadata_unchanged"] = (
        result["live_data"]["metadata_before"] == result["live_data"]["metadata_after"]
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"output={output}")
    print(f"inventory={result['inventory']}")
    print(f"temporal={result['temporal']}")
    for baseline in ("B0", "B1", "B2"):
        metrics = result["held_out"][baseline]["overall"]
        print(
            f"{baseline}: n={metrics['examples']} "
            f"log_loss={metrics['log_loss']:.12f} "
            f"brier={metrics['brier']:.12f} ece={metrics['ece_10_bins']:.12f}"
        )
    print(f"resources_within_budget={resources['within_budget']}")
    print(f"readiness={result['readiness']['status']}")
    print(f"live_data_metadata_unchanged={result['live_data']['metadata_unchanged']}")


if __name__ == "__main__":
    main()
