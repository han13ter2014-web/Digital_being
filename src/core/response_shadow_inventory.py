"""Чистая read-only инвентаризация prospective response-журнала для R1."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy

OBSERVED_OUTCOMES = (
    "answer",
    "follow_up",
    "unclassified_reply",
    "ordinary_reply",
    "explicit_support",
    "explicit_opposition",
)
NO_OBSERVED_REACTION = "no_observed_reaction"
MIN_TRAIN_OBSERVED = 30
MIN_VALIDATION_OBSERVED = 10
MIN_HELD_OUT_OBSERVED = 10
MIN_CLASS_EXAMPLES = 2
MIN_SEMANTIC_LABELS = 50
SMALL_SLICE_EXAMPLES = 5


def _events(events, life_id: str) -> list[dict]:
    if not isinstance(events, (list, tuple)):
        raise ValueError("events: expected a sequence")
    result = []
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("event: expected a dictionary")
        if event.get("life_id") != life_id:
            raise ValueError("inventory cannot cross lives")
        result.append(event)
    return sorted(
        result,
        key=lambda event: event.get("event_sequence", -1)
        if isinstance(event.get("event_sequence"), int)
        else -1,
    )


def _deliveries(events: list[dict]) -> list[dict]:
    return [event for event in events if event.get("event_kind") == "delivery"]


def _terminal_events(events: list[dict]) -> list[dict]:
    return [
        event for event in events if event.get("event_kind") in {"outcome", "expired"}
    ]


def _valid_cycle(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _delivery_provenance_gap(delivery: dict) -> bool:
    payload = delivery.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), dict):
        return True
    return (
        not isinstance(delivery.get("response_id"), str)
        or not delivery["response_id"]
        or not isinstance(delivery.get("profile_id"), str)
        or not delivery["profile_id"]
        or not isinstance(delivery.get("event_hash"), str)
        or len(delivery["event_hash"]) != 64
        or not _valid_cycle(delivery.get("cycle"))
        or not _valid_cycle(payload.get("delivery_cycle"))
    )


def _matching_delivery(outcome: dict, deliveries: list[dict]):
    matches = [
        delivery
        for delivery in deliveries
        if delivery.get("response_id") == outcome.get("response_id")
        and delivery.get("profile_id") == outcome.get("profile_id")
    ]
    return matches[0] if len(matches) == 1 else None


def _valid_terminal(outcome: dict, delivery: dict | None) -> bool:
    if delivery is None:
        return False
    delivery_payload = delivery.get("payload")
    if not isinstance(delivery_payload, dict) or not isinstance(
        delivery_payload.get("features"), dict
    ):
        return False
    if not _valid_cycle(delivery_payload.get("delivery_cycle")):
        return False
    payload = outcome.get("payload")
    if not isinstance(payload, dict):
        return False
    if payload.get("delivery_sequence") != delivery.get("event_sequence"):
        return False
    if outcome.get("event_sequence", -1) <= delivery.get("event_sequence", -1):
        return False
    if outcome.get("episode_id") != delivery.get("episode_id"):
        return False
    expected = (
        NO_OBSERVED_REACTION
        if outcome.get("event_kind") == "expired"
        else OBSERVED_OUTCOMES
    )
    observed = payload.get("observed_outcome")
    return observed == expected if isinstance(expected, str) else observed in expected


def inventory_events(events, *, life_id: str) -> dict:
    """Посчитать доступность исходов и пробелы, не восстанавливая метки."""
    ordered = _events(events, life_id)
    deliveries = _deliveries(ordered)
    terminal = _terminal_events(ordered)
    counts = Counter()
    observed_counts = Counter()
    expired = 0
    invalid_ordering = 0
    terminal_keys = set()
    for outcome in terminal:
        delivery = _matching_delivery(outcome, deliveries)
        payload = outcome.get("payload")
        observed = (
            payload.get("observed_outcome") if isinstance(payload, dict) else None
        )
        key = (outcome.get("profile_id"), outcome.get("response_id"))
        if not _valid_terminal(outcome, delivery) or key in terminal_keys:
            invalid_ordering += 1
            continue
        terminal_keys.add(key)
        if outcome.get("event_kind") == "expired" and observed == NO_OBSERVED_REACTION:
            expired += 1
        elif observed in OBSERVED_OUTCOMES:
            observed_counts[observed] += 1
            counts["observed"] += 1
        else:
            invalid_ordering += 1
    missing_outcome_cycle = 0
    for outcome in terminal:
        payload = outcome.get("payload")
        cycle = payload.get("outcome_cycle") if isinstance(payload, dict) else None
        missing_outcome_cycle += int(not _valid_cycle(cycle))
    provenance_gaps = sum(_delivery_provenance_gap(item) for item in deliveries)
    for outcome in terminal:
        payload = outcome.get("payload")
        if not isinstance(payload, dict) or not isinstance(
            payload.get("delivery_sequence"), int
        ):
            provenance_gaps += 1
    observed = counts["observed"]
    return {
        "registered": len(deliveries),
        "observed": observed,
        "pending": max(0, len(deliveries) - len(terminal_keys)),
        "expired": expired,
        "observed_class_counts": {
            name: observed_counts[name] for name in OBSERVED_OUTCOMES
        },
        "missing_outcome_cycle": missing_outcome_cycle,
        "missing_episode_id": sum(
            not isinstance(item.get("episode_id"), str) or not item["episode_id"]
            for item in deliveries
        ),
        "provenance_gaps": provenance_gaps,
        "invalid_ordering": invalid_ordering,
        "journal_gaps": sum(
            item.get("event_kind") == "journal_gap" for item in ordered
        ),
        "orphan_outcomes": sum(
            _matching_delivery(item, deliveries) is None for item in terminal
        ),
    }


def samples_from_events(
    events,
    *,
    life_id: str,
    episode_ids: set[str] | None = None,
    outcome_before_sequence: int | None = None,
) -> list[dict]:
    """Адаптировать production SQLite events к существующим B0/B1/B2."""
    ordered = _events(events, life_id)
    deliveries = _deliveries(ordered)
    samples = []
    for outcome in _terminal_events(ordered):
        if outcome.get("event_kind") != "outcome":
            continue
        delivery = _matching_delivery(outcome, deliveries)
        if not _valid_terminal(outcome, delivery):
            continue
        payload = outcome["payload"]
        observed = payload.get("observed_outcome")
        if observed not in OBSERVED_OUTCOMES:
            continue
        if episode_ids is not None and delivery.get("episode_id") not in episode_ids:
            continue
        if (
            outcome_before_sequence is not None
            and outcome["event_sequence"] >= outcome_before_sequence
        ):
            continue
        features = deepcopy(delivery["payload"]["features"])
        features.update(
            {
                "life_id": life_id,
                "profile_id": delivery["profile_id"],
                "response_id": delivery["response_id"],
                "episode_id": delivery["episode_id"],
                "delivery_cycle": delivery["payload"]["delivery_cycle"],
            }
        )
        samples.append(
            {
                "features": features,
                "response_id": delivery["response_id"],
                "episode_id": delivery["episode_id"],
                "delivery_sequence": delivery["event_sequence"],
                "outcome": observed,
                "outcome_cycle": payload.get("outcome_cycle"),
                "outcome_sequence": outcome["event_sequence"],
            }
        )
    return sorted(samples, key=lambda item: item["delivery_sequence"])


def temporal_split(events, *, life_id: str) -> dict:
    """Целые эпизоды в delivery order: 60/20/20 без shuffle."""
    ordered = _events(events, life_id)
    deliveries = _deliveries(ordered)
    first_delivery = {}
    for delivery in deliveries:
        episode_id = delivery.get("episode_id")
        sequence = delivery.get("event_sequence")
        if (
            not isinstance(episode_id, str)
            or not episode_id
            or not isinstance(sequence, int)
        ):
            continue
        first_delivery[episode_id] = min(
            first_delivery.get(episode_id, sequence), sequence
        )
    episodes = sorted(first_delivery, key=first_delivery.__getitem__)
    train_count = int(len(episodes) * 0.6)
    validation_count = int(len(episodes) * 0.2)
    train = episodes[:train_count]
    validation = episodes[train_count : train_count + validation_count]
    held_out = episodes[train_count + validation_count :]
    next_sequence = (
        max((event.get("event_sequence", 0) for event in ordered), default=0) + 1
    )
    validation_start = first_delivery[validation[0]] if validation else next_sequence
    held_out_start = first_delivery[held_out[0]] if held_out else next_sequence
    return {
        "train": train,
        "validation": validation,
        "held_out": held_out,
        "train_outcome_before_sequence": validation_start,
        "held_out_start_sequence": held_out_start,
        "split_counts": {
            "train": len(train),
            "validation": len(validation),
            "held_out": len(held_out),
        },
    }


def assess_readiness(
    inventory: dict,
    split: dict,
    events,
    *,
    life_id: str,
    confirmed_intent_labels: int,
    semantic_plan_labels: int,
) -> dict:
    """Отделить измеримость outcome baseline от права обучать речевую сеть."""
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
    counts = Counter(sample["outcome"] for sample in train)
    temporal_ok = (
        len(train) >= MIN_TRAIN_OBSERVED
        and len(validation) >= MIN_VALIDATION_OBSERVED
        and len(held_out) >= MIN_HELD_OUT_OBSERVED
    )
    classes_ok = all(counts[name] >= MIN_CLASS_EXAMPLES for name in OBSERVED_OUTCOMES)
    integrity_ok = not any(
        inventory[key]
        for key in (
            "missing_outcome_cycle",
            "missing_episode_id",
            "provenance_gaps",
            "invalid_ordering",
            "journal_gaps",
            "orphan_outcomes",
        )
    )
    missing = []
    if not temporal_ok:
        missing.append("outcome_temporal_coverage")
    if not classes_ok:
        missing.append("outcome_class_coverage")
    if not integrity_ok:
        missing.append("journal_integrity")
    if confirmed_intent_labels < MIN_SEMANTIC_LABELS:
        missing.append("confirmed_intent_labels")
    if semantic_plan_labels < MIN_SEMANTIC_LABELS:
        missing.append("semantic_plan_labels")
    return {
        "status": "insufficient_data" if missing else "ready_for_r2_review",
        "training_allowed": not missing,
        "outcome_baseline_status": (
            "measurable" if temporal_ok and integrity_ok else "insufficient_data"
        ),
        "missing": missing,
        "observed_counts": {
            "train_eligible": len(train),
            "train_late_outcomes_excluded": len(train_all) - len(train),
            "validation": len(validation),
            "held_out": len(held_out),
        },
        "train_class_counts": {name: counts[name] for name in OBSERVED_OUTCOMES},
        "confirmed_intent_labels": confirmed_intent_labels,
        "semantic_plan_labels": semantic_plan_labels,
        "thresholds": {
            "train_observed": MIN_TRAIN_OBSERVED,
            "validation_observed": MIN_VALIDATION_OBSERVED,
            "held_out_observed": MIN_HELD_OUT_OBSERVED,
            "train_examples_per_class": MIN_CLASS_EXAMPLES,
            "semantic_labels_per_kind": MIN_SEMANTIC_LABELS,
            "small_slice_insufficient_below": SMALL_SLICE_EXAMPLES,
        },
    }
