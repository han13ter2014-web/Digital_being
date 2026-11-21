"""RE-S1 phase 1: controlled event inventory and deterministic baselines.

No production writer, model, network, live biography, or new dependency is used.
Run from the repository root:
    .venv/Scripts/python.exe tests/observations/re_s1_response_experience.py \
        --label controlled --output tmp/response_experience_shadow/report.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import tracemalloc
from collections import Counter
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBSERVATION_ROOT = PROJECT_ROOT / "tmp" / "response_experience_shadow"
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

OBSERVED_OUTCOMES = (
    "answer",
    "follow_up",
    "unclassified_reply",
    "ordinary_reply",
    "explicit_support",
    "explicit_opposition",
)
NO_OBSERVED_REACTION = "no_observed_reaction"
ALPHA = 1.0
B1_PRIOR_STRENGTH = 6.0
EVENT_SCHEMA_VERSION = 1
FEATURE_CONTRACT_VERSION = "re_s1_structured_v1"

_ACT_BY_OUTCOME = {
    "answer": ACT_ANSWER,
    "follow_up": ACT_FOLLOW_UP,
    "unclassified_reply": ACT_UNKNOWN,
    "ordinary_reply": ACT_SOCIAL,
}

# Fixed before looking at validation or held-out metrics. Each block repeats the
# same ten controlled episodes; this is a synthetic instrument check, not life data.
CONTROLLED_SCHEDULE = (
    ("dialogue_learning", "answer"),
    ("dialogue_learning", "answer"),
    ("social_reply", "explicit_support"),
    ("unknown_reply", "unclassified_reply"),
    ("dialogue_learning", "follow_up"),
    ("social_reply", "explicit_opposition"),
    ("unknown_reply", "ordinary_reply"),
    ("dialogue_learning", "answer"),
    ("social_reply", "ordinary_reply"),
    ("unknown_reply", "follow_up"),
) * 3


def _length_bucket(text: str) -> str:
    length = len(text)
    if length == 0:
        return "0"
    if length <= 40:
        return "1-40"
    if length <= 160:
        return "41-160"
    if length <= 500:
        return "161-500"
    return "501+"


def feature_snapshot(record: dict, *, life_id: str, episode_id: str) -> dict:
    """Capture only pre-outcome structured fields; never copy raw dialogue text."""
    plan = record["plan"]
    realization = plan["realization"]
    language = plan.get("language_context") or {}
    borrowed = plan.get("borrowed")
    references = plan.get("references") or []
    reference_kinds = Counter(item["kind"] for item in references)
    base_text = realization["base_text"]
    return {
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "life_id": life_id,
        "profile_id": plan["state"]["profile_id"],
        "response_id": record["response_id"],
        "episode_id": episode_id,
        "delivery_cycle": record["cycle"],
        "intention": plan["intention"],
        "context": plan["context"],
        "source": plan["source"],
        "expected_reaction": record["expected_reaction"],
        "uncertainties": list(record["uncertainties"]),
        "language_missing": not bool(language),
        "input_language": language.get("input_language"),
        "dialogue_language": language.get("dialogue_language"),
        "response_language": language.get("response_language", "ru"),
        "language_source": language.get("source"),
        "language_confidence": language.get("confidence"),
        "realization_kind": realization["kind"],
        "realization_rule_id": realization.get("rule_id"),
        "realization_act": realization.get("act"),
        "realization_fallback_policy": realization.get("fallback_policy", "none"),
        "realization_rule_missing": "rule_id" not in realization,
        "components": list(plan["components"]),
        "borrowed_present": borrowed is not None,
        "borrowed_context": (borrowed or {}).get("context"),
        "borrowed_level": (borrowed or {}).get("level"),
        "borrowed_language": (borrowed or {}).get("language_id"),
        "reference_count": len(references),
        "reference_kind_counts": dict(sorted(reference_kinds.items())),
        "provenance_verified": plan["provenance_verified"],
        "input_length_bucket": _length_bucket(plan["observed_input"]),
        "realization_length_bucket": _length_bucket(base_text),
        # Aggregate-only identity for repeat metrics; not a model feature.
        "realization_fingerprint": hashlib.sha256(
            base_text.encode("utf-8")
        ).hexdigest(),
    }


class ResponseEventJournal:
    """Prospective test-only wrapper around the real ResponseExperience methods."""

    def __init__(self, life_id: str) -> None:
        self.life_id = life_id
        self.events: list[dict] = []
        self.deliveries: dict[tuple[str, str], dict] = {}
        self.outcomes: dict[tuple[str, str], dict] = {}

    def _append(self, event_kind: str, **fields) -> dict:
        event = {
            "event_schema_version": EVENT_SCHEMA_VERSION,
            "sequence": len(self.events) + 1,
            "event_kind": event_kind,
            "life_id": self.life_id,
            **fields,
        }
        self.events.append(event)
        return event

    @staticmethod
    def _pending(experience: ResponseExperience) -> dict[str, str]:
        return {
            response_id: record["status"]
            for response_id, record in experience.responses.items()
            if record["status"] == "pending"
        }

    def _capture_expired(
        self,
        experience: ResponseExperience,
        before: dict[str, str],
        *,
        profile_id: str,
        cycle: int,
    ) -> None:
        for response_id in before:
            record = experience.responses.get(response_id)
            if record is None or record["status"] != "expired":
                continue
            key = (profile_id, response_id)
            if key in self.outcomes:
                continue
            event = self._append(
                "outcome",
                profile_id=profile_id,
                response_id=response_id,
                episode_id=self.deliveries[key]["episode_id"],
                outcome_cycle=cycle,
                outcome=NO_OBSERVED_REACTION,
                source="real_expire",
            )
            self.outcomes[key] = event

    def deliver(
        self,
        experience: ResponseExperience,
        agent: SimpleNamespace,
        *,
        profile_id: str,
        response_id: str,
        episode_id: str,
        cycle: int,
        context: str,
    ) -> dict:
        agent.cycle_count = cycle
        before = self._pending(experience)
        prepared = experience.prepare_plan(
            agent,
            f"Контролируемая реплика: {context}.",
            context=context,
            source="re_s1_controlled",
            user_text="Контролируемый вход без реальной биографии",
        )
        self._capture_expired(experience, before, profile_id=profile_id, cycle=cycle)
        record = experience.register_delivery(response_id, prepared["plan"], cycle)
        event = self._append(
            "delivery",
            profile_id=profile_id,
            response_id=response_id,
            episode_id=episode_id,
            delivery_cycle=cycle,
            source="real_register_delivery_controlled",
        )
        features = feature_snapshot(record, life_id=self.life_id, episode_id=episode_id)
        features["delivery_sequence"] = event["sequence"]
        self.deliveries[(profile_id, response_id)] = features
        return deepcopy(features)

    def observe(
        self,
        experience: ResponseExperience,
        *,
        profile_id: str,
        response_id: str,
        outcome: str,
        cycle: int,
    ) -> dict:
        if outcome not in OBSERVED_OUTCOMES:
            raise ValueError("unsupported controlled observed outcome")
        key = (profile_id, response_id)
        before = self._pending(experience)
        if outcome in {"explicit_support", "explicit_opposition"}:
            feedback = "support" if outcome == "explicit_support" else "opposition"
            record = experience.observe_feedback(
                response_id, feedback, cycle, language_id="ru"
            )
        else:
            pending = experience.latest_pending(language_id="ru")
            if pending is None or pending["response_id"] != response_id:
                raise ValueError("controlled reply would close another expectation")
            record = experience.observe_reply(
                _ACT_BY_OUTCOME[outcome], cycle, language_id="ru"
            )
        self._capture_expired(experience, before, profile_id=profile_id, cycle=cycle)
        if record is None or record["outcome"] != outcome:
            raise ValueError("real observation did not produce the controlled outcome")
        event = self._append(
            "outcome",
            profile_id=profile_id,
            response_id=response_id,
            episode_id=self.deliveries[key]["episode_id"],
            outcome_cycle=cycle,
            outcome=outcome,
            source="real_observe_reply_or_feedback",
        )
        self.outcomes[key] = event
        return deepcopy(event)

    def expire(
        self, experience: ResponseExperience, *, profile_id: str, cycle: int
    ) -> int:
        before = self._pending(experience)
        expired = experience.expire(cycle)
        self._capture_expired(experience, before, profile_id=profile_id, cycle=cycle)
        return expired

    def episode_order(self) -> list[str]:
        first_sequences: dict[str, int] = {}
        for features in self.deliveries.values():
            episode_id = features["episode_id"]
            first_sequences[episode_id] = min(
                first_sequences.get(episode_id, features["delivery_sequence"]),
                features["delivery_sequence"],
            )
        return sorted(first_sequences, key=first_sequences.__getitem__)

    def samples(
        self,
        *,
        episode_ids: set[str] | None = None,
        outcome_before_sequence: int | None = None,
    ) -> list[dict]:
        samples = []
        for key, features in self.deliveries.items():
            outcome = self.outcomes.get(key)
            if outcome is None or outcome["outcome"] not in OBSERVED_OUTCOMES:
                continue
            if episode_ids is not None and features["episode_id"] not in episode_ids:
                continue
            if (
                outcome_before_sequence is not None
                and outcome["sequence"] >= outcome_before_sequence
            ):
                continue
            if outcome["sequence"] <= features["delivery_sequence"]:
                raise ValueError("outcome must follow delivery")
            samples.append(
                {
                    "features": deepcopy(features),
                    "outcome": outcome["outcome"],
                    "outcome_cycle": outcome["outcome_cycle"],
                    "outcome_sequence": outcome["sequence"],
                }
            )
        return sorted(samples, key=lambda item: item["features"]["delivery_sequence"])

    def inventory(self) -> dict:
        outcome_counts = Counter(event["outcome"] for event in self.outcomes.values())
        observed = sum(outcome_counts[name] for name in OBSERVED_OUTCOMES)
        expired = outcome_counts[NO_OBSERVED_REACTION]
        return {
            "registered": len(self.deliveries),
            "observed": observed,
            "pending": len(self.deliveries) - len(self.outcomes),
            "expired": expired,
            "observed_class_counts": {
                name: outcome_counts[name] for name in OBSERVED_OUTCOMES
            },
            "missing_outcome_cycle": sum(
                "outcome_cycle" not in event for event in self.outcomes.values()
            ),
            "missing_episode_id": sum(
                not features["episode_id"] for features in self.deliveries.values()
            ),
        }


def temporal_split(journal: ResponseEventJournal) -> dict:
    """Split whole episodes 60/20/20 in delivery order, never by shuffle."""
    episodes = journal.episode_order()
    train_count = int(len(episodes) * 0.6)
    validation_count = int(len(episodes) * 0.2)
    train = episodes[:train_count]
    validation = episodes[train_count : train_count + validation_count]
    held_out = episodes[train_count + validation_count :]
    first_delivery = {
        episode: min(
            features["delivery_sequence"]
            for features in journal.deliveries.values()
            if features["episode_id"] == episode
        )
        for episode in episodes
    }
    validation_start = (
        first_delivery[validation[0]] if validation else len(journal.events) + 1
    )
    held_out_start = (
        first_delivery[held_out[0]] if held_out else len(journal.events) + 1
    )
    return {
        "train": train,
        "validation": validation,
        "held_out": held_out,
        "train_outcome_before_sequence": validation_start,
        "held_out_start_sequence": held_out_start,
    }


def _context_key(features: dict) -> tuple[str, str, str]:
    return (
        features["profile_id"],
        features["context"],
        features["response_language"],
    )


def fit_baselines(samples: list[dict], *, life_id: str) -> dict:
    if any(sample["features"]["life_id"] != life_id for sample in samples):
        raise ValueError("baseline history cannot cross lives")
    global_counts = Counter(sample["outcome"] for sample in samples)
    context_counts: dict[tuple[str, str, str], Counter] = {}
    last_outcome: dict[tuple[str, str, str], tuple[int, str]] = {}
    for sample in sorted(samples, key=lambda item: item["outcome_sequence"]):
        key = _context_key(sample["features"])
        context_counts.setdefault(key, Counter())[sample["outcome"]] += 1
        last_outcome[key] = (sample["outcome_sequence"], sample["outcome"])
    return {
        "life_id": life_id,
        "sample_count": len(samples),
        "global_counts": dict(global_counts),
        "context_counts": {key: dict(value) for key, value in context_counts.items()},
        "last_outcome": last_outcome,
    }


def _smoothed(
    counts: Counter | dict, *, prior=None, prior_strength=ALPHA
) -> list[float]:
    if prior is None:
        total = sum(counts.values())
        denominator = total + ALPHA * len(OBSERVED_OUTCOMES)
        return [
            (counts.get(name, 0) + ALPHA) / denominator for name in OBSERVED_OUTCOMES
        ]
    total = sum(counts.values())
    denominator = total + prior_strength
    return [
        (counts.get(name, 0) + prior_strength * prior[index]) / denominator
        for index, name in enumerate(OBSERVED_OUTCOMES)
    ]


def predict_baseline(model: dict, baseline: str, features: dict) -> list[float]:
    if features["life_id"] != model["life_id"]:
        raise ValueError("baseline prediction cannot cross lives")
    b0 = _smoothed(model["global_counts"])
    key = _context_key(features)
    if baseline == "B0":
        return b0
    if baseline == "B1":
        return _smoothed(
            model["context_counts"].get(key, {}),
            prior=b0,
            prior_strength=B1_PRIOR_STRENGTH,
        )
    if baseline == "B2":
        previous = model["last_outcome"].get(key)
        if previous is None:
            return b0
        return _smoothed({previous[1]: 1})
    raise ValueError("unknown baseline")


def metric_values(samples: list[dict], predictions: list[list[float]]) -> dict:
    if not samples:
        return {"status": "insufficient_data", "examples": 0}
    if len(samples) != len(predictions):
        raise ValueError("prediction count does not match samples")
    log_loss = 0.0
    brier = 0.0
    correct = 0
    calibration_rows = []
    per_class = {}
    for index, name in enumerate(OBSERVED_OUTCOMES):
        actual = sum(sample["outcome"] == name for sample in samples)
        predicted = sum(
            OBSERVED_OUTCOMES[max(range(6), key=prediction.__getitem__)] == name
            for prediction in predictions
        )
        hits = sum(
            sample["outcome"] == name
            and OBSERVED_OUTCOMES[max(range(6), key=prediction.__getitem__)] == name
            for sample, prediction in zip(samples, predictions)
        )
        per_class[name] = {
            "support": actual,
            "predicted": predicted,
            "recall": hits / actual if actual else None,
        }
    for sample, prediction in zip(samples, predictions):
        actual_index = OBSERVED_OUTCOMES.index(sample["outcome"])
        probability = prediction[actual_index]
        log_loss -= math.log(max(probability, 1e-15))
        brier += sum(
            (probability - float(index == actual_index)) ** 2
            for index, probability in enumerate(prediction)
        )
        predicted_index = max(range(6), key=prediction.__getitem__)
        confidence = prediction[predicted_index]
        calibration_rows.append((confidence, predicted_index == actual_index))
        correct += int(predicted_index == actual_index)
    count = len(samples)
    ece = 0.0
    reliability = []
    for bin_index in range(10):
        lower = bin_index / 10
        upper = (bin_index + 1) / 10
        rows = [
            row
            for row in calibration_rows
            if lower <= row[0] < upper or bin_index == 9 and row[0] == 1.0
        ]
        if not rows:
            continue
        confidence = sum(row[0] for row in rows) / len(rows)
        accuracy = sum(row[1] for row in rows) / len(rows)
        ece += len(rows) / count * abs(accuracy - confidence)
        reliability.append(
            {
                "lower": lower,
                "upper": upper,
                "examples": len(rows),
                "confidence": confidence,
                "accuracy": accuracy,
            }
        )
    return {
        "status": "ok",
        "examples": count,
        "coverage": 1.0,
        "log_loss": log_loss / count,
        "brier": brier / count,
        "ece_10_bins": ece,
        "accuracy_diagnostic": correct / count,
        "per_class": per_class,
        "reliability": reliability,
    }


def score_with_abstention(
    samples: list[dict],
    predictions: list[list[float]],
    abstain: list[bool],
    fallback: list[list[float]],
) -> dict:
    """Primary scoring rule: abstention receives the same-moment B0 fallback."""
    if not len(samples) == len(predictions) == len(abstain) == len(fallback):
        raise ValueError("abstention inputs have different lengths")
    effective = [
        fallback_item if skipped else prediction
        for prediction, skipped, fallback_item in zip(predictions, abstain, fallback)
    ]
    metrics = metric_values(samples, effective)
    metrics["coverage"] = (
        sum(not skipped for skipped in abstain) / len(abstain) if abstain else 0.0
    )
    return metrics


def evaluate_baselines(
    model: dict, samples: list[dict], baselines=("B0", "B1", "B2")
) -> dict:
    report = {}
    for baseline in baselines:
        predictions = [
            predict_baseline(model, baseline, sample["features"]) for sample in samples
        ]
        overall = metric_values(samples, predictions)
        slices = {}
        for field in (
            "context",
            "expected_reaction",
            "response_language",
            "borrowed_present",
        ):
            values = sorted({sample["features"][field] for sample in samples})
            field_report = {}
            for value in values:
                indexes = [
                    index
                    for index, sample in enumerate(samples)
                    if sample["features"][field] == value
                ]
                field_report[str(value)] = metric_values(
                    [samples[index] for index in indexes],
                    [predictions[index] for index in indexes],
                )
            slices[field] = field_report
        report[baseline] = {"overall": overall, "slices": slices}
    return report


def repeat_report(train: list[dict], held_out: list[dict]) -> dict:
    previous = {sample["features"]["realization_fingerprint"] for sample in train}
    if not held_out:
        return {"status": "insufficient_data", "examples": 0}
    repeated = sum(
        sample["features"]["realization_fingerprint"] in previous for sample in held_out
    )
    return {
        "status": "ok",
        "examples": len(held_out),
        "repeated_realizations": repeated,
        "repeat_rate": repeated / len(held_out),
        "raw_text_exported": False,
    }


def controlled_history(life_id="life-controlled-a") -> ResponseEventJournal:
    journal = ResponseEventJournal(life_id)
    experience = ResponseExperience()
    profile_id = "owner"
    agent = SimpleNamespace(
        cycle_count=0,
        social_registry=SimpleNamespace(current_profile_id=profile_id),
        social_attribution=None,
    )
    for index, (context, outcome) in enumerate(CONTROLLED_SCHEDULE):
        response_id = f"controlled-{index:02d}"
        journal.deliver(
            experience,
            agent,
            profile_id=profile_id,
            response_id=response_id,
            episode_id=f"episode-{index:02d}",
            cycle=index * 2,
            context=context,
        )
        journal.observe(
            experience,
            profile_id=profile_id,
            response_id=response_id,
            outcome=outcome,
            cycle=index * 2 + 1,
        )
    journal.deliver(
        experience,
        agent,
        profile_id=profile_id,
        response_id="control-expired",
        episode_id="control-expired",
        cycle=100,
        context="social_reply",
    )
    journal.expire(experience, profile_id=profile_id, cycle=151)
    journal.deliver(
        experience,
        agent,
        profile_id=profile_id,
        response_id="control-pending",
        episode_id="control-pending",
        cycle=200,
        context="social_reply",
    )
    return journal


def baseline_observation(life_id="life-controlled-a") -> dict:
    journal = controlled_history(life_id)
    split = temporal_split(journal)
    train_all = journal.samples(episode_ids=set(split["train"]))
    train = journal.samples(
        episode_ids=set(split["train"]),
        outcome_before_sequence=split["train_outcome_before_sequence"],
    )
    validation = journal.samples(episode_ids=set(split["validation"]))
    held_out = journal.samples(episode_ids=set(split["held_out"]))
    model = fit_baselines(train, life_id=life_id)
    return {
        "journal": journal,
        "split": split,
        "train_all": train_all,
        "train": train,
        "validation": validation,
        "held_out": held_out,
        "validation_metrics": evaluate_baselines(model, validation),
        "held_out_metrics": evaluate_baselines(model, held_out),
        "repeat": repeat_report(train, held_out),
    }


def _live_data_manifest() -> dict:
    """Metadata-only integrity check; never read live biography file contents."""
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run_root = OBSERVATION_ROOT / "runs" / args.label
    run_root.mkdir(parents=True, exist_ok=True)
    os.environ["DIGITAL_BEING_DATA_DIR"] = str(run_root / "data")
    live_before = _live_data_manifest()
    tracemalloc.start()
    started = time.perf_counter()
    observation = baseline_observation()
    repeated = baseline_observation()
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    journal = observation["journal"]
    split = observation["split"]
    second_life = ResponseEventJournal("life-controlled-b")
    empty_second_model = fit_baselines([], life_id="life-controlled-b")
    empty_second_distribution = _smoothed(empty_second_model["global_counts"])
    result = {
        "schema": "re_s1_phase1_controlled_v1",
        "label": args.label,
        "revision": _revision(),
        "synthetic_controlled_events": True,
        "real_biography_used": False,
        "network_used": False,
        "production_writer_created": False,
        "model_trained": False,
        "delivery_witness": (
            "real ResponseExperience.register_delivery under controlled plans; "
            "not a natural AgentRunner/UI conversation"
        ),
        "constants": {
            "observed_outcomes": OBSERVED_OUTCOMES,
            "alpha": ALPHA,
            "b1_prior_strength": B1_PRIOR_STRENGTH,
            "split": "whole episodes, chronological 60/20/20",
            "abstention_primary_rule": "same-moment B0 fallback",
            "ece_bins": 10,
        },
        "inventory": journal.inventory(),
        "temporal": {
            "prospective_event_journal": True,
            "delivery_and_outcome_sequences": True,
            "delivery_and_outcome_cycles": True,
            "episode_ids": True,
            "retrospective_checkpoint_claim": False,
            "split_counts": {
                name: len(split[name]) for name in ("train", "validation", "held_out")
            },
            "train_observed_total": len(observation["train_all"]),
            "train_eligible_before_cut": len(observation["train"]),
            "train_late_outcomes_excluded": len(observation["train_all"])
            - len(observation["train"]),
            "validation_observed": len(observation["validation"]),
            "held_out_observed": len(observation["held_out"]),
        },
        "validation": observation["validation_metrics"],
        "held_out": observation["held_out_metrics"],
        "repeat": observation["repeat"],
        "determinism": {
            "same_controlled_history": journal.events == repeated["journal"].events,
            "same_held_out_metrics": observation["held_out_metrics"]
            == repeated["held_out_metrics"],
        },
        "second_life": {
            "registered": len(second_life.deliveries),
            "training_examples": empty_second_model["sample_count"],
            "empty_b0_is_uniform": all(
                math.isclose(value, 1 / len(OBSERVED_OUTCOMES))
                for value in empty_second_distribution
            ),
            "fresh_response_experience_empty": not ResponseExperience().responses,
            "inherited_weights_or_statistics": False,
        },
        "resources": {
            "scope": "two controlled baseline observations, not a model",
            "elapsed_seconds": elapsed,
            "tracemalloc_peak_bytes": peak,
            "journal_events": len(journal.events),
            "journal_json_bytes": len(
                json.dumps(journal.events, ensure_ascii=False).encode("utf-8")
            ),
        },
        "live_data": {
            "content_read_for_observation": False,
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
    for baseline in ("B0", "B1", "B2"):
        metrics = result["held_out"][baseline]["overall"]
        print(
            f"{baseline}: n={metrics['examples']} "
            f"log_loss={metrics['log_loss']:.12f} "
            f"brier={metrics['brier']:.12f} ece={metrics['ece_10_bins']:.12f}"
        )
    print(f"live_data_metadata_unchanged={result['live_data']['metadata_unchanged']}")


if __name__ == "__main__":
    main()
