"""R2-PREP: contract-first tests for independent human semantic annotation."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from src.core.response_annotation import (
    ANNOTATION_INTENTS,
    AnnotationError,
    AnnotationRevision,
    ResponseAnnotationJournal,
    prepare_r2_dataset,
)

LIFE_ID = "00000000-0000-4000-8000-000000000001"
OTHER_LIFE_ID = "00000000-0000-4000-8000-000000000002"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT = object()


@pytest.fixture(autouse=True)
def sandbox_data_dir(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(root))
    return root


def _delivery_hash(response_id):
    return hashlib.sha256(f"delivery:{response_id}".encode("utf-8")).hexdigest()


def _plan(intent="ASK_SELF_STATE"):
    if intent == "ASK_SELF_ACTIVITY":
        return {
            "schema_version": 1,
            "language": "ru",
            "activity": {"status": "current", "kind": "draw", "started_cycle": 12},
            "last_completed_action": {"kind": "compose_music", "cycle": 9},
            "energy": None,
            "allowed_claims": [
                "activity.current:draw",
                "activity.completed:compose_music",
            ],
        }
    return {
        "schema_version": 1,
        "language": "ru",
        "activity": None,
        "last_completed_action": {"kind": "compose_music", "cycle": 9},
        "energy": 0.7,
        "allowed_claims": ["state.energy", "activity.completed:compose_music"],
    }


def _revision(
    *,
    annotation_id="annotation-1",
    life_id=LIFE_ID,
    profile_id="owner",
    response_id="r0",
    episode_id=None,
    delivery_sequence=1,
    source_delivery_event_hash=None,
    revision=1,
    supersedes_event_hash=None,
    annotator_id="owner",
    label_source="human_review",
    intent_review="confirmed",
    intent="ASK_SELF_STATE",
    intent_uncertainties=(),
    plan_review=None,
    semantic_plan=DEFAULT,
    plan_uncertainties=(),
):
    if semantic_plan is DEFAULT:
        semantic_plan = (
            _plan(intent)
            if intent
            in {
                "ASK_SELF_STATE",
                "ASK_SELF_ACTIVITY",
            }
            else None
        )
    if plan_review is None:
        plan_review = (
            "confirmed"
            if intent in {"ASK_SELF_STATE", "ASK_SELF_ACTIVITY"}
            else "not_applicable"
        )
    return AnnotationRevision(
        annotation_id=annotation_id,
        life_id=life_id,
        profile_id=profile_id,
        response_id=response_id,
        episode_id=episode_id or f"episode:{response_id}",
        delivery_sequence=delivery_sequence,
        source_delivery_event_hash=(
            source_delivery_event_hash or _delivery_hash(response_id)
        ),
        revision=revision,
        supersedes_event_hash=supersedes_event_hash,
        annotator_id=annotator_id,
        label_source=label_source,
        intent_review=intent_review,
        intent=intent,
        intent_uncertainties=intent_uncertainties,
        plan_review=plan_review,
        semantic_plan=semantic_plan,
        plan_uncertainties=plan_uncertainties,
    )


def _response_events(count=5, *, life_id=LIFE_ID):
    return [
        {
            "event_id": f"delivery:r{index}",
            "event_sequence": index + 1,
            "event_kind": "delivery",
            "life_id": life_id,
            "profile_id": "owner",
            "cycle": index,
            "episode_id": f"episode:r{index}",
            "response_id": f"r{index}",
            "event_hash": _delivery_hash(f"r{index}"),
            "payload": {"delivery_cycle": index, "features": {}},
        }
        for index in range(count)
    ]


def _record_annotations(path, revisions, *, life_id=LIFE_ID):
    journal = ResponseAnnotationJournal(path, life_id)
    try:
        return [journal.record(revision) for revision in revisions]
    finally:
        journal.close()


def _annotations_for(path, response_events):
    return _record_annotations(
        path,
        [
            _revision(
                annotation_id=f"annotation:{delivery['response_id']}",
                response_id=delivery["response_id"],
                episode_id=delivery["episode_id"],
                delivery_sequence=delivery["event_sequence"],
                source_delivery_event_hash=delivery["event_hash"],
            )
            for delivery in response_events
        ],
    )


def _all_samples(dataset):
    return [
        sample
        for name in ("train", "validation", "held_out")
        for sample in dataset["samples"][name]
    ]


@pytest.mark.parametrize(
    "intent", ["ASK_SELF_STATE", "ASK_SELF_ACTIVITY", "UNKNOWN_OR_OTHER"]
)
def test_three_intents_require_independent_human_review_and_round_trip(intent):
    revision = _revision(intent=intent)

    restored = AnnotationRevision.from_dict(revision.to_dict())

    assert intent in ANNOTATION_INTENTS
    assert restored == revision
    assert revision.label_source == "human_review"
    assert revision.intent_review == "confirmed"
    if intent == "UNKNOWN_OR_OTHER":
        assert revision.semantic_plan is None
        assert revision.plan_review == "not_applicable"
    else:
        assert revision.semantic_plan is not None
        assert revision.plan_review == "confirmed"


@pytest.mark.parametrize(
    "source", ["model_prediction", "self_review", "automatic", "response_outcome"]
)
def test_model_self_labels_and_outcomes_are_not_human_confirmation(source):
    with pytest.raises(ValueError, match="label_source"):
        _revision(label_source=source)


def test_unknown_or_other_is_a_label_not_abstention_or_a_plan_carrier():
    with pytest.raises(ValueError, match="not_applicable|semantic_plan"):
        _revision(
            intent="UNKNOWN_OR_OTHER",
            plan_review="confirmed",
            semantic_plan=_plan(),
        )

    revision = _revision(intent="UNKNOWN_OR_OTHER")
    assert revision.intent_review == "confirmed"
    assert not revision.intent_uncertainties


def test_intent_abstention_requires_uncertainty_and_has_no_plan():
    with pytest.raises(ValueError, match="uncertaint"):
        _revision(
            intent_review="abstained",
            intent=None,
            intent_uncertainties=(),
            plan_review="not_applicable",
            semantic_plan=None,
        )

    revision = _revision(
        intent_review="abstained",
        intent=None,
        intent_uncertainties=("input_meaning",),
        plan_review="not_applicable",
        semantic_plan=None,
    )
    assert revision.intent is None
    assert revision.semantic_plan is None


def test_plan_abstention_does_not_erase_a_resolved_intent(tmp_path):
    responses = _response_events(1)
    annotations = _record_annotations(
        tmp_path / "annotations.sqlite3",
        [
            _revision(
                plan_review="abstained",
                semantic_plan=None,
                plan_uncertainties=("plan_facts",),
            )
        ],
    )

    dataset = prepare_r2_dataset(responses, annotations, life_id=LIFE_ID)
    sample = dataset["samples"]["held_out"][0]
    assert sample["eligible_intent"] is True
    assert sample["eligible_semantic_plan"] is False
    assert dataset["coverage"]["total"]["resolved_intent_labels"] == 1
    assert dataset["coverage"]["total"]["resolved_semantic_plan_labels"] == 0
    assert dataset["coverage"]["total"]["plan_abstentions"] == 1


def test_uncertain_confirmation_is_visible_but_not_training_eligible(tmp_path):
    responses = _response_events(1)
    annotations = _record_annotations(
        tmp_path / "annotations.sqlite3",
        [_revision(intent_uncertainties=("input_meaning",))],
    )

    dataset = prepare_r2_dataset(responses, annotations, life_id=LIFE_ID)
    sample = dataset["samples"]["held_out"][0]
    assert sample["eligible_intent"] is False
    assert sample["eligible_semantic_plan"] is True
    assert dataset["coverage"]["total"]["uncertain_intent_labels"] == 1
    assert dataset["coverage"]["total"]["resolved_intent_labels"] == 0


@pytest.mark.parametrize(
    "forbidden",
    [
        ("baseline_text", "PRIVATE RESPONSE"),
        ("observed_input", "PRIVATE INPUT"),
        ("text_sha256", "PRIVATE HASH"),
        ("evidence_refs", [{"kind": "state", "id": "private-reference"}]),
        (
            "activity",
            {
                "status": "current",
                "kind": "draw",
                "started_cycle": 1,
                "target": "PRIVATE TARGET",
            },
        ),
        (
            "activity",
            {
                "status": "current",
                "kind": "draw",
                "started_cycle": 1,
                "work_id": "PRIVATE WORK",
            },
        ),
        (
            "last_completed_action",
            {"kind": "draw", "cycle": 1, "target": "PRIVATE TARGET"},
        ),
    ],
)
def test_raw_text_private_targets_and_reference_ids_are_rejected(forbidden):
    plan = _plan("ASK_SELF_ACTIVITY")
    key, value = forbidden
    plan[key] = value

    with pytest.raises(ValueError, match="semantic_plan|unknown|not allowed"):
        _revision(intent="ASK_SELF_ACTIVITY", semantic_plan=plan)


def test_revision_copies_nested_plan_and_serializes_only_whitelisted_fields():
    plan = _plan("ASK_SELF_ACTIVITY")
    revision = _revision(intent="ASK_SELF_ACTIVITY", semantic_plan=plan)

    plan["activity"]["kind"] = "MUTATED"
    encoded = json.dumps(revision.to_dict(), ensure_ascii=False)

    assert revision.semantic_plan["activity"]["kind"] == "draw"
    assert "MUTATED" not in encoded
    for forbidden in ("baseline_text", "observed_input", "target", "work_id"):
        assert forbidden not in encoded


def test_corrections_are_append_only_and_cutoff_restores_prior_revision(tmp_path):
    journal = ResponseAnnotationJournal(tmp_path / "annotations.sqlite3", LIFE_ID)
    try:
        first = journal.record(_revision())
        second = journal.record(
            _revision(
                annotation_id="annotation-2",
                revision=2,
                supersedes_event_hash=first["event_hash"],
                intent_review="corrected",
                intent="ASK_SELF_ACTIVITY",
                plan_review="corrected",
            )
        )

        assert (
            journal.labels(annotation_before_sequence=second["event_sequence"])[0][
                "payload"
            ]["intent"]
            == "ASK_SELF_STATE"
        )
        assert journal.labels()[0]["payload"]["intent"] == "ASK_SELF_ACTIVITY"
        assert [event["event_sequence"] for event in journal.events()] == [1, 2]
        with pytest.raises(sqlite3.IntegrityError, match="append_only"):
            journal.connection.execute(
                "UPDATE events SET response_id='rewritten' WHERE event_id=?",
                (first["event_id"],),
            )

        stolen = journal.events()
        stolen[0]["payload"]["intent"] = "MUTATED"
        assert journal.events()[0]["payload"]["intent"] == "ASK_SELF_STATE"
    finally:
        journal.close()


def test_revision_must_supersede_the_actual_immediate_head(tmp_path):
    journal = ResponseAnnotationJournal(tmp_path / "annotations.sqlite3", LIFE_ID)
    try:
        first = journal.record(_revision())
        with pytest.raises(AnnotationError, match="supersed|revision"):
            journal.record(
                _revision(
                    annotation_id="annotation-2",
                    revision=2,
                    supersedes_event_hash="0" * 64,
                )
            )
        with pytest.raises(AnnotationError, match="supersed|revision"):
            journal.record(
                _revision(
                    annotation_id="annotation-3",
                    revision=3,
                    supersedes_event_hash=first["event_hash"],
                )
            )
    finally:
        journal.close()


def test_idempotent_replay_cannot_be_used_for_a_conflicting_rewrite(tmp_path):
    journal = ResponseAnnotationJournal(tmp_path / "annotations.sqlite3", LIFE_ID)
    try:
        revision = _revision()
        first = journal.record(revision)

        assert journal.record(revision) == first
        assert len(journal.events()) == 1
        with pytest.raises(AnnotationError, match="conflict"):
            journal.record(_revision(intent="ASK_SELF_ACTIVITY"))
    finally:
        journal.close()


def test_reopen_verifies_history_without_creating_a_new_label(tmp_path):
    path = tmp_path / "annotations.sqlite3"
    journal = ResponseAnnotationJournal(path, LIFE_ID)
    first = journal.record(_revision())
    expected = journal.labels()
    journal.close()

    reopened = ResponseAnnotationJournal(path, LIFE_ID)
    try:
        assert reopened.labels() == expected
        assert reopened.labels()[0]["event_hash"] == first["event_hash"]
        assert len(reopened.events()) == 1
    finally:
        reopened.close()


def test_journal_and_projection_reject_cross_life_records(tmp_path):
    journal = ResponseAnnotationJournal(tmp_path / "first.sqlite3", LIFE_ID)
    try:
        with pytest.raises(AnnotationError, match="life"):
            journal.record(_revision(life_id=OTHER_LIFE_ID))
    finally:
        journal.close()

    annotations = _record_annotations(tmp_path / "second.sqlite3", [_revision()])
    annotations[0]["life_id"] = OTHER_LIFE_ID
    with pytest.raises(ValueError, match="cross lives"):
        prepare_r2_dataset(_response_events(1), annotations, life_id=LIFE_ID)


def test_hash_mismatch_is_a_provenance_gap_not_a_training_sample(tmp_path):
    responses = _response_events(1)
    annotations = _annotations_for(tmp_path / "annotations.sqlite3", responses)
    annotations[0]["source_delivery_event_hash"] = "f" * 64

    dataset = prepare_r2_dataset(responses, annotations, life_id=LIFE_ID)

    assert _all_samples(dataset) == []
    assert dataset["coverage"]["total"]["provenance_gaps"] == 1
    assert dataset["coverage"]["total"]["unannotated_deliveries"] == 1
    assert dataset["readiness"]["training_allowed"] is False


def test_temporal_split_is_deterministic_and_excludes_late_corrections(tmp_path):
    responses = _response_events(5)
    path = tmp_path / "annotations.sqlite3"
    journal = ResponseAnnotationJournal(path, LIFE_ID)
    annotations = []
    try:
        for delivery in responses:
            annotations.append(
                journal.record(
                    _revision(
                        annotation_id=f"annotation:{delivery['response_id']}",
                        response_id=delivery["response_id"],
                        episode_id=delivery["episode_id"],
                        delivery_sequence=delivery["event_sequence"],
                        source_delivery_event_hash=delivery["event_hash"],
                    )
                )
            )
        journal.record(
            _revision(
                annotation_id="annotation:r0:corrected",
                response_id="r0",
                delivery_sequence=1,
                revision=2,
                supersedes_event_hash=annotations[0]["event_hash"],
                intent_review="corrected",
                intent="ASK_SELF_ACTIVITY",
                plan_review="corrected",
            )
        )
        events = journal.events()
    finally:
        journal.close()

    response_before = deepcopy(responses)
    annotation_before = deepcopy(events)
    first = prepare_r2_dataset(responses, events, life_id=LIFE_ID)
    second = prepare_r2_dataset(responses, events, life_id=LIFE_ID)

    assert first == second
    assert responses == response_before
    assert events == annotation_before
    assert first["split"]["train"] == ["episode:r0", "episode:r1", "episode:r2"]
    assert first["split"]["validation"] == ["episode:r3"]
    assert first["split"]["held_out"] == ["episode:r4"]
    train_r0 = next(
        sample for sample in first["samples"]["train"] if sample["response_id"] == "r0"
    )
    assert train_r0["intent"] == "ASK_SELF_STATE"
    assert train_r0["revision"] == 1
    assert first["coverage"]["total"]["late_revisions_excluded"] == 1


def test_late_first_train_label_is_not_backfilled_into_training(tmp_path):
    responses = _response_events(5)
    order = [1, 2, 3, 4, 0]
    revisions = []
    for index in order:
        delivery = responses[index]
        revisions.append(
            _revision(
                annotation_id=f"annotation:r{index}",
                response_id=delivery["response_id"],
                episode_id=delivery["episode_id"],
                delivery_sequence=delivery["event_sequence"],
                source_delivery_event_hash=delivery["event_hash"],
            )
        )
    annotations = _record_annotations(tmp_path / "annotations.sqlite3", revisions)

    dataset = prepare_r2_dataset(responses, annotations, life_id=LIFE_ID)

    assert {sample["response_id"] for sample in dataset["samples"]["train"]} == {
        "r1",
        "r2",
    }
    assert "r0" not in {sample["response_id"] for sample in _all_samples(dataset)}


def test_second_life_is_empty_and_insufficient_labels_never_allow_training(tmp_path):
    responses = _response_events(5)
    annotations = _annotations_for(tmp_path / "annotations.sqlite3", responses)
    populated = prepare_r2_dataset(responses, annotations, life_id=LIFE_ID)

    empty = prepare_r2_dataset([], [], life_id=OTHER_LIFE_ID)

    assert len(_all_samples(populated)) == 5
    assert populated["readiness"]["confirmed_intent_labels"] == 5
    assert populated["readiness"]["semantic_plan_labels"] == 5
    assert populated["readiness"]["training_allowed"] is False
    assert "confirmed_intent_labels" in populated["readiness"]["missing"]
    assert "semantic_plan_labels" in populated["readiness"]["missing"]
    assert _all_samples(empty) == []
    assert empty["coverage"]["total"]["resolved_intent_labels"] == 0
    assert empty["readiness"]["training_allowed"] is False


def test_import_has_no_data_or_active_runtime_side_effects(sandbox_data_dir):
    env = os.environ.copy()
    env["DIGITAL_BEING_DATA_DIR"] = str(sandbox_data_dir)

    completed = subprocess.run(
        [sys.executable, "-c", "import src.core.response_annotation"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert not sandbox_data_dir.exists()
