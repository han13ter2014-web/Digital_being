"""Read-only projection доказуемо чистых интервалов response-journal.

Функции не открывают файлы, не изменяют события или аннотации и не разрешают
обучение. Исключённые интервалы и provenance gaps остаются видимыми в отчёте.
"""

from __future__ import annotations

from collections import Counter

from src.core.response_annotation import prepare_r2_dataset

_STARTUP_GAPS = {"previous_shutdown_unclean", "previous_writer_degraded"}
_TERMINAL_OR_PRUNED = {"outcome", "expired", "record_pruned"}


def _annotation_key(item):
    return (
        item.get("profile_id"),
        item.get("response_id"),
        item.get("episode_id"),
        (
            item.get("event_sequence")
            if item.get("event_kind") == "delivery"
            else item.get("delivery_sequence")
        ),
    )


def project_clean_response_segments(response_events, annotation_events, *, life_id):
    """Сохранить только завершённые интервалы без operational gaps.

    Startup gaps остаются видимыми на границе. Terminal/pruning событие без
    допущенной delivery исключается, если его delivery находится в исключённом
    интервале. Неизвестная аннотация не скрывается, а создаёт provenance gap.
    """
    ordered = sorted(response_events, key=lambda event: event["event_sequence"])
    eligible_events = []
    excluded_events = []
    intervals = []
    current = None

    def finish(end_sequence, *, clean_stop):
        nonlocal current
        if current is None:
            return
        eligible = clean_stop and current["invalid_reason"] is None
        target = eligible_events if eligible else excluded_events
        target.extend(current["events"])
        intervals.append(
            {
                "start_sequence": current["start_sequence"],
                "end_sequence": end_sequence,
                "eligible": eligible,
                "reason": (
                    current["invalid_reason"]
                    if current["invalid_reason"] is not None
                    else None
                    if clean_stop
                    else "missing_clean_stop"
                ),
                "startup_gap_count": current["startup_gap_count"],
            }
        )
        current = None

    for event in ordered:
        kind = event["event_kind"]
        sequence = event["event_sequence"]
        if kind == "journal_started":
            finish(sequence, clean_stop=False)
            current = {
                "start_sequence": sequence,
                "events": [],
                "invalid_reason": None,
                "startup": True,
                "startup_gap_count": 0,
            }
            continue
        if current is None:
            excluded_events.append(event)
            continue
        if kind == "journal_gap":
            reason = event["payload"].get("reason")
            if current["startup"] and reason in _STARTUP_GAPS:
                current["startup_gap_count"] += 1
            else:
                current["invalid_reason"] = reason or "unknown_gap"
                current["startup"] = False
            excluded_events.append(event)
            continue
        if kind == "journal_stopped":
            finish(sequence, clean_stop=True)
            continue
        current["startup"] = False
        current["events"].append(event)
    finish(ordered[-1]["event_sequence"] if ordered else 0, clean_stop=False)

    all_response_keys = {
        (event["profile_id"], event["response_id"])
        for event in response_events
        if event["event_kind"] == "delivery"
    }
    eligible_response_keys = {
        (event["profile_id"], event["response_id"])
        for event in eligible_events
        if event["event_kind"] == "delivery"
    }
    retained_events = []
    cross_interval_excluded = 0
    for event in eligible_events:
        response_key = (event["profile_id"], event["response_id"])
        if (
            event["event_kind"] in _TERMINAL_OR_PRUNED
            and response_key not in eligible_response_keys
            and response_key in all_response_keys
        ):
            excluded_events.append(event)
            cross_interval_excluded += 1
            continue
        retained_events.append(event)
    eligible_events = retained_events

    all_deliveries = {}
    eligible_deliveries = {}
    for delivery in response_events:
        if delivery["event_kind"] == "delivery":
            all_deliveries.setdefault(_annotation_key(delivery), []).append(delivery)
    for delivery in eligible_events:
        if delivery["event_kind"] == "delivery":
            eligible_deliveries.setdefault(_annotation_key(delivery), []).append(
                delivery
            )

    eligible_annotations = []
    excluded_annotations = []
    for annotation in annotation_events:
        if _annotation_key(annotation) in eligible_deliveries:
            eligible_annotations.append(annotation)
        elif _annotation_key(annotation) in all_deliveries:
            excluded_annotations.append(annotation)
        else:
            # Неизвестная provenance не скрывается ради готовности набора.
            eligible_annotations.append(annotation)

    dataset = prepare_r2_dataset(
        eligible_events,
        eligible_annotations,
        life_id=life_id,
    )
    report = {
        "intervals": intervals,
        "eligible_interval_count": sum(item["eligible"] for item in intervals),
        "excluded_interval_count": sum(not item["eligible"] for item in intervals),
        "eligible_delivery_count": sum(
            event["event_kind"] == "delivery" for event in eligible_events
        ),
        "excluded_annotation_count": len(excluded_annotations),
        "cross_interval_excluded_events": cross_interval_excluded,
        "excluded_gap_reasons": dict(
            Counter(
                event["payload"].get("reason")
                for event in excluded_events
                if event["event_kind"] == "journal_gap"
            )
        ),
    }
    return dataset, report
