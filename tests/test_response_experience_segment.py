"""CS-I: production segment writer и read-only historical projection."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from src.core.agent import DigitalBeing
from src.core.paths import DATA_DIR_ENV
from src.core.response_annotation import AnnotationRevision, ResponseAnnotationJournal
from src.core.response_experience_journal import (
    JOURNAL_FILENAME,
    RESPONSE_JOURNAL_ARCHIVE_HASH_ENV,
    RESPONSE_JOURNAL_ENV,
    RESPONSE_JOURNAL_SEGMENT_ENV,
    RESPONSE_JOURNAL_SEGMENT_ID_ENV,
    JournalCorruption,
    ResponseExperienceJournal,
    open_response_experience_journal,
)
from src.core.response_segment import project_clean_response_segments

LIFE_ID = "00000000-0000-4000-8000-000000000001"
OTHER_LIFE_ID = "00000000-0000-4000-8000-000000000002"
SEGMENT_ID = "segment-test-001"
ARCHIVE_HASH = "a" * 64


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv(DATA_DIR_ENV, str(root))
    monkeypatch.setenv("VOICE_CONSOLE_QUIET", "1")
    for name in (
        RESPONSE_JOURNAL_ENV,
        RESPONSE_JOURNAL_SEGMENT_ENV,
        RESPONSE_JOURNAL_SEGMENT_ID_ENV,
        RESPONSE_JOURNAL_ARCHIVE_HASH_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    return root


def _agent(name="SegmentTest", life_id=LIFE_ID):
    return DigitalBeing(name=name, life_id=life_id)


def _record(agent, response_id, text="Ответ из состояния.", cycle=1):
    agent.cycle_count = cycle
    experience = agent.response_experience
    prepared = experience.prepare_plan(
        agent,
        text,
        context="social_reply",
        source="core",
        user_text="SECRET_RAW_INPUT_NEVER_PERSIST",
        profile_id=agent.social_registry.current_profile_id,
    )
    return experience.register_delivery(response_id, prepared["plan"], cycle)


def _deliver(agent, journal, response_id, text="Ответ из состояния.", cycle=1):
    record = _record(agent, response_id, text=text, cycle=cycle)
    event = None
    if journal is not None:
        event = journal.record_delivery(
            agent.response_experience,
            record,
            cycle=cycle,
            turn_id=f"turn-{cycle}",
        )
    return record, event


def _support(agent, journal, record, cycle=2):
    observed = agent.response_experience.observe_feedback(
        record["response_id"], "support", cycle, language_id="ru"
    )
    assert observed is not None
    event = None
    if journal is not None:
        event = journal.record_transition(
            "outcome", observed, cycle=cycle, turn_id=f"turn-{cycle}"
        )
    return observed, event


def _exclusions(agent):
    return {
        (record["plan"]["state"]["profile_id"], response_id)
        for response_id, record in agent.response_experience.responses.items()
    }


def _segment(path, *, life_id=LIFE_ID, segment_id=SEGMENT_ID, preexisting=()):
    return ResponseExperienceJournal(
        path,
        life_id,
        segment_id=segment_id,
        boundary_cycle=0,
        archive_manifest_hash=ARCHIVE_HASH,
        preexisting=preexisting,
    )


def _read_events(path):
    connection = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [
            ResponseExperienceJournal._row_event(row)
            for row in connection.execute(
                "SELECT * FROM events ORDER BY event_sequence"
            )
        ]
    finally:
        connection.close()


def _annotation(delivery, *, annotation_id, intent="UNKNOWN_OR_OTHER", **kwargs):
    if intent == "ASK_SELF_STATE":
        plan = {
            "schema_version": 1,
            "language": "ru",
            "activity": None,
            "last_completed_action": None,
            "energy": 0.5,
            "allowed_claims": [],
        }
        plan_review = "confirmed"
    elif intent == "ASK_SELF_ACTIVITY":
        plan = {
            "schema_version": 1,
            "language": "ru",
            "activity": {"status": "none", "kind": None, "started_cycle": None},
            "last_completed_action": None,
            "energy": None,
            "allowed_claims": [],
        }
        plan_review = "confirmed"
    else:
        plan = None
        plan_review = "not_applicable"
    return AnnotationRevision(
        annotation_id=annotation_id,
        life_id=delivery["life_id"],
        profile_id=delivery["profile_id"],
        response_id=delivery["response_id"],
        episode_id=delivery["episode_id"],
        delivery_sequence=delivery["event_sequence"],
        source_delivery_event_hash=kwargs.pop("source_hash", delivery["event_hash"]),
        revision=kwargs.pop("revision", 1),
        annotator_id="owner",
        intent_review="confirmed",
        intent=intent,
        plan_review=plan_review,
        semantic_plan=plan,
        **kwargs,
    )


def _annotations(path, revisions):
    journal = ResponseAnnotationJournal(path, LIFE_ID)
    try:
        return [journal.record(revision) for revision in revisions]
    finally:
        journal.close()


def test_segment_activation_is_explicit_and_default_off(sandbox, monkeypatch):
    agent = _agent("SegmentFlags")
    assert open_response_experience_journal(agent) is None
    path = sandbox / "lives" / LIFE_ID / JOURNAL_FILENAME
    assert not path.exists()

    monkeypatch.setenv(RESPONSE_JOURNAL_ENV, "1")
    monkeypatch.setenv(RESPONSE_JOURNAL_SEGMENT_ENV, "1")
    unavailable = open_response_experience_journal(agent)
    assert unavailable.get_status()["status"] == "degraded"
    assert not path.exists()

    monkeypatch.setenv(RESPONSE_JOURNAL_SEGMENT_ID_ENV, SEGMENT_ID)
    monkeypatch.setenv(RESPONSE_JOURNAL_ARCHIVE_HASH_ENV, ARCHIVE_HASH)
    journal = open_response_experience_journal(agent)
    try:
        assert journal.segment_id == SEGMENT_ID
        started = journal.events()[0]
        assert started["journal_schema_version"] == 2
        assert started["writer_contract_version"] == "cs_i_segment_v1"
        assert started["payload"]["segment_reason"] == (
            "owner_approved_clean_collection"
        )
    finally:
        journal.close()


def test_presegment_outcome_expiry_and_pruning_are_outside_collection(tmp_path):
    agent = _agent("SegmentPreexisting")
    _deliver(agent, None, "old-outcome", cycle=1)
    _deliver(agent, None, "old-expiry", cycle=2)
    journal = _segment(tmp_path / "segment.sqlite3", preexisting=_exclusions(agent))
    try:
        observed = agent.response_experience.observe_feedback(
            "old-outcome", "support", 3
        )
        journal.record_transition("outcome", observed, cycle=3, turn_id="turn-3")
        before = dict(agent.response_experience.responses)
        agent.response_experience.expire(4)
        for response_id, record in before.items():
            if response_id not in agent.response_experience.responses:
                journal.record_transition("expired", record, cycle=4, turn_id=None)
        pruned = agent.response_experience.responses.pop("old-outcome")
        journal.record_transition("record_pruned", pruned, cycle=5, turn_id=None)
        events = journal.events()
        assert not any(event["event_kind"] == "journal_gap" for event in events)
        assert not any(event["event_kind"] == "delivery" for event in events)
        assert sum(event["event_kind"] == "segment_exclusion" for event in events) == 2
        assert journal.samples() == []
    finally:
        journal.close()


def test_unknown_orphan_still_creates_gap(tmp_path):
    agent = _agent("SegmentOrphan")
    _record(agent, "unknown-orphan")
    observed = agent.response_experience.observe_feedback(
        "unknown-orphan", "support", 1
    )
    journal = _segment(tmp_path / "segment.sqlite3")
    try:
        journal.record_transition("outcome", observed, cycle=1, turn_id="turn-1")
        gaps = [
            event for event in journal.events() if event["event_kind"] == "journal_gap"
        ]
        assert [event["payload"]["reason"] for event in gaps] == ["orphan_outcome"]
    finally:
        journal.close()


def test_presegment_repeat_origin_is_not_in_segment_delivery(tmp_path):
    agent = _agent("SegmentRepeat")
    _deliver(agent, None, "old-repeat", text="Одинаковый ответ.", cycle=1)
    journal = _segment(tmp_path / "segment.sqlite3", preexisting=_exclusions(agent))
    try:
        record, delivery = _deliver(
            agent, journal, "new-repeat", text="Одинаковый ответ.", cycle=2
        )
        features = delivery["payload"]["features"]
        assert features["repeat_in_retained_window"] is True
        assert features["realization_origin_response_id"] == "old-repeat"
        assert not any(
            event["event_kind"] == "delivery" and event["response_id"] == "old-repeat"
            for event in journal.events()
        )
        _support(agent, journal, record, cycle=3)
        assert len(journal.samples()) == 1
    finally:
        journal.close()


def test_clean_restart_loads_exclusions_and_rejects_other_segment(tmp_path):
    path = tmp_path / "segment.sqlite3"
    agent = _agent("SegmentRestart")
    _deliver(agent, None, "before-restart", cycle=1)
    first = _segment(path, preexisting=_exclusions(agent))
    first.close()
    second = _segment(path)
    try:
        observed = agent.response_experience.observe_feedback(
            "before-restart", "support", 2
        )
        second.record_transition("outcome", observed, cycle=2, turn_id="turn-2")
        events = second.events()
        assert sum(event["event_kind"] == "segment_exclusion" for event in events) == 1
        assert not any(event["event_kind"] == "journal_gap" for event in events)
        assert events[-1]["payload"]["previous_shutdown_unclean"] is False
    finally:
        second.close()
    with pytest.raises(JournalCorruption, match="segment_mismatch"):
        _segment(path, segment_id="another-segment")


def test_unclean_restart_and_v1_compatibility(tmp_path):
    segment_path = tmp_path / "unclean.sqlite3"
    first = _segment(segment_path)
    first.connection.execute("DELETE FROM writer_leases")
    first.connection.execute("UPDATE head SET clean_shutdown=0 WHERE id=1")
    first.connection.close()
    first.connection = None
    second = _segment(segment_path)
    try:
        assert any(
            event["event_kind"] == "journal_gap"
            and event["payload"]["reason"] == "previous_shutdown_unclean"
            for event in second.events()
        )
    finally:
        second.close()

    v1_path = tmp_path / "v1.sqlite3"
    agent = _agent("SegmentV1")
    v1 = ResponseExperienceJournal(v1_path, LIFE_ID)
    record, _ = _deliver(agent, v1, "legacy", cycle=1)
    _support(agent, v1, record, cycle=2)
    v1.close()
    reopened = ResponseExperienceJournal(v1_path, LIFE_ID)
    try:
        assert all(event["journal_schema_version"] == 1 for event in reopened.events())
        assert not any(
            event["event_kind"] == "segment_exclusion" for event in reopened.events()
        )
        assert len(reopened.samples()) == 1
    finally:
        reopened.close()
    with pytest.raises(JournalCorruption):
        _segment(v1_path)


def test_second_life_has_no_segment_inheritance(tmp_path):
    journal = _segment(tmp_path / "second.sqlite3", life_id=OTHER_LIFE_ID)
    try:
        assert journal.samples() == []
        assert not any(
            event["event_kind"] == "segment_exclusion" for event in journal.events()
        )
    finally:
        journal.close()


def _historical(tmp_path):
    path = tmp_path / "history.sqlite3"
    agent = _agent("SegmentHistorical")
    journal = ResponseExperienceJournal(path, LIFE_ID)
    first, first_event = _deliver(agent, journal, "clean-1", cycle=1)
    _support(agent, journal, first, cycle=2)
    journal.close()

    journal = ResponseExperienceJournal(path, LIFE_ID)
    bad, bad_event = _deliver(agent, journal, "bad", cycle=3)
    _support(agent, journal, bad, cycle=4)
    _record(agent, "orphan", cycle=5)
    observed = agent.response_experience.observe_feedback("orphan", "support", 5)
    journal.record_transition("outcome", observed, cycle=5, turn_id="turn-5")
    journal.status = "degraded"
    journal.degradation_reason = "orphan_outcome"
    cross, cross_event = _deliver(agent, journal, "cross", cycle=6)
    journal.close()

    journal = ResponseExperienceJournal(path, LIFE_ID)
    _support(agent, journal, cross, cycle=7)
    second, second_event = _deliver(agent, journal, "clean-2", cycle=8)
    _support(agent, journal, second, cycle=9)
    journal.close()
    assert first_event and bad_event and cross_event and second_event
    return _read_events(path), [first_event, bad_event, second_event]


def test_projection_preserves_clean_annotations_and_visible_gaps(tmp_path):
    response_events, deliveries = _historical(tmp_path)
    annotations = _annotations(
        tmp_path / "annotations.sqlite3",
        [
            _annotation(delivery, annotation_id=f"annotation:{delivery['response_id']}")
            for delivery in deliveries
        ],
    )
    before_hashes = [event["event_hash"] for event in annotations]
    dataset, report = project_clean_response_segments(
        response_events, annotations, life_id=LIFE_ID
    )
    assert report["eligible_interval_count"] == 2
    assert report["excluded_interval_count"] == 1
    assert report["excluded_annotation_count"] == 1
    assert report["cross_interval_excluded_events"] == 1
    assert report["excluded_gap_reasons"]["orphan_outcome"] == 1
    assert report["excluded_gap_reasons"]["previous_writer_degraded"] == 1
    assert dataset["coverage"]["total"]["annotated"] == 2
    assert dataset["coverage"]["total"]["provenance_gaps"] == 0
    assert "journal_integrity" not in dataset["readiness"]["missing"]
    assert before_hashes == [event["event_hash"] for event in annotations]


def test_projection_keeps_hash_mismatch_as_provenance_gap(tmp_path):
    response_events, deliveries = _historical(tmp_path)
    good = _annotations(
        tmp_path / "good.sqlite3",
        [_annotation(deliveries[0], annotation_id="annotation:good")],
    )
    mismatch = _annotations(
        tmp_path / "mismatch.sqlite3",
        [
            _annotation(
                deliveries[2],
                annotation_id="annotation:mismatch",
                source_hash="0" * 64,
            )
        ],
    )
    dataset, _ = project_clean_response_segments(
        response_events, [good[0], mismatch[0]], life_id=LIFE_ID
    )
    assert dataset["coverage"]["total"]["provenance_gaps"] == 1
    assert "annotation_provenance" in dataset["readiness"]["missing"]
    assert not dataset["samples"]["held_out"]
    assert mismatch[0]["source_delivery_event_hash"] == "0" * 64


def test_late_annotation_revision_does_not_rewrite_train(tmp_path):
    response_events, deliveries = _historical(tmp_path)
    train_delivery = deliveries[0]
    held_out_delivery = deliveries[2]
    journal = ResponseAnnotationJournal(tmp_path / "annotations.sqlite3", LIFE_ID)
    try:
        first = journal.record(
            _annotation(
                train_delivery,
                annotation_id="annotation:train:rev1",
                intent="ASK_SELF_STATE",
            )
        )
        journal.record(
            _annotation(held_out_delivery, annotation_id="annotation:held-out")
        )
        journal.record(
            _annotation(
                train_delivery,
                annotation_id="annotation:train:rev2",
                intent="ASK_SELF_ACTIVITY",
                revision=2,
                supersedes_event_hash=first["event_hash"],
            )
        )
        annotations = journal.events()
    finally:
        journal.close()
    dataset, _ = project_clean_response_segments(
        response_events, annotations, life_id=LIFE_ID
    )
    train = next(
        sample
        for sample in dataset["samples"]["train"]
        if sample["response_id"] == train_delivery["response_id"]
    )
    assert train["revision"] == 1
    assert train["intent"] == "ASK_SELF_STATE"
    assert dataset["coverage"]["total"]["late_revisions_excluded"] == 1


def _normalized_experience(agent):
    result = agent.response_experience.to_dict()
    profile_id = agent.social_registry.current_profile_id

    def normalize(value):
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return "owner" if value == profile_id else value

    return normalize(result)


def test_writer_does_not_change_response_experience(tmp_path):
    disabled_agent = _agent("SegmentDifferential")
    disabled_record, _ = _deliver(
        disabled_agent, None, "differential", text="Один и тот же ответ.", cycle=1
    )
    _support(disabled_agent, None, disabled_record, cycle=2)

    enabled_agent = _agent("SegmentDifferential")
    journal = _segment(tmp_path / "segment.sqlite3")
    try:
        enabled_record, _ = _deliver(
            enabled_agent, journal, "differential", text="Один и тот же ответ.", cycle=1
        )
        _support(enabled_agent, journal, enabled_record, cycle=2)
    finally:
        journal.close()
    assert _normalized_experience(enabled_agent) == _normalized_experience(
        disabled_agent
    )


def test_segment_integrity_privacy_and_shutdown(tmp_path):
    path = tmp_path / "segment.sqlite3"
    agent = _agent("SegmentIntegrity")
    journal = _segment(path)
    record, _ = _deliver(
        agent,
        journal,
        "private-response",
        text="SECRET_RESPONSE_NEVER_PERSIST",
        cycle=1,
    )
    _support(agent, journal, record, cycle=2)
    journal.close()
    assert journal.integrity_after_close() == ["ok"]
    assert not Path(f"{path}-wal").exists()
    assert not Path(f"{path}-shm").exists()
    raw = path.read_bytes()
    assert b"SECRET_RAW_INPUT_NEVER_PERSIST" not in raw
    assert b"SECRET_RESPONSE_NEVER_PERSIST" not in raw
    events = _read_events(path)
    assert events[-1]["event_kind"] == "journal_stopped"
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        leases = connection.execute("SELECT COUNT(*) FROM writer_leases").fetchone()[0]
    finally:
        connection.close()
    assert leases == 0
