"""Sandbox-only human review UI and session for R2-PREP annotations."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from src.core.response_annotation import (
    AnnotationError,
    ResponseAnnotationJournal,
    prepare_r2_dataset,
)
from src.core.response_annotation_review import (
    AnnotationReviewSession,
    ReviewError,
    load_review_candidates,
    open_review_session,
)
from src.core.response_experience_journal import ResponseExperienceJournal

LIFE_ID = "00000000-0000-4000-8000-000000000001"
OTHER_LIFE_ID = "00000000-0000-4000-8000-000000000002"
ROOT = Path(__file__).resolve().parents[1]
PRIVATE_INPUT = "PRIVATE INPUT: не записывать в разметку"
PRIVATE_RESPONSE = "PRIVATE RESPONSE: не записывать в разметку"


@pytest.fixture(autouse=True)
def sandbox_data_dir(tmp_path, monkeypatch):
    root = tmp_path / "runtime-data"
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(root))
    return root


def _semantic(intent: str, response_id: str, cycle: int) -> dict:
    activity = None
    completed = {"kind": "compose_music", "cycle": 2, "target": "PRIVATE TARGET"}
    energy = 0.7
    claims = ["state.energy", "activity.completed:compose_music"]
    if intent == "ASK_SELF_ACTIVITY":
        activity = {
            "status": "current",
            "kind": "draw",
            "work_id": "PRIVATE WORK",
            "started_cycle": cycle,
            "target": "PRIVATE TARGET",
        }
        completed = None
        energy = None
        claims = ["activity.current:draw", "activity.target"]
    return {
        "schema_version": 1,
        "response_id": response_id,
        "cycle": cycle,
        "language": "ru",
        "intent": intent,
        "activity": activity,
        "last_completed_action": completed,
        "energy": energy,
        "evidence_refs": [{"kind": "state", "id": "PRIVATE REFERENCE"}],
        "allowed_claims": claims,
        "baseline_text": PRIVATE_RESPONSE,
    }


def _record(response_id: str, cycle: int, intent: str | None) -> dict:
    plan = {
        "observed_input": f"{PRIVATE_INPUT} {response_id}",
        "intention": "social_acknowledgement",
        "context": "social_reply",
        "source": "core",
        "references": [],
        "state": {"cycle": cycle, "profile_id": "owner"},
        "components": ["deterministic_reply"],
        "realization": {
            "kind": "fixed_template",
            "base_text": f"{PRIVATE_RESPONSE} {response_id}",
            "text": f"{PRIVATE_RESPONSE} {response_id}",
        },
        "provenance_verified": True,
        "borrowed": None,
    }
    if intent is not None:
        semantic = _semantic(intent, response_id, cycle)
        semantic["baseline_text"] = plan["realization"]["base_text"]
        plan["semantic_response_plan"] = semantic
    return {
        "response_id": response_id,
        "cycle": cycle,
        "plan": plan,
        "expected_reaction": "continuation_or_support",
        "uncertainties": [],
        "status": "answered",
        "outcome": "ordinary_reply",
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def sandbox(tmp_path):
    root = tmp_path / "review-sandbox"
    root.mkdir()
    response_path = root / "responses.sqlite3"
    records = [
        _record("state", 3, "ASK_SELF_STATE"),
        _record("activity", 4, "ASK_SELF_ACTIVITY"),
        _record("other", 5, None),
    ]
    writer = ResponseExperienceJournal(response_path, LIFE_ID)
    experience = type("Experience", (), {})()
    experience.responses = {}
    for record in records:
        writer.record_delivery(experience, record, cycle=record["cycle"], turn_id=None)
        experience.responses[record["response_id"]] = record
    writer.close()
    snapshot_path = root / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "life_id": LIFE_ID,
                "response_experience": {"responses": records},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {
        "root": root,
        "snapshot": snapshot_path,
        "responses": response_path,
        "annotations": root / "annotations.sqlite3",
        "records": records,
    }


def _session(sandbox) -> AnnotationReviewSession:
    return open_review_session(
        sandbox_root=sandbox["root"],
        snapshot_path=sandbox["snapshot"],
        response_journal_path=sandbox["responses"],
        annotation_journal_path=sandbox["annotations"],
        life_id=LIFE_ID,
    )


def _response_events(path: Path) -> list[dict]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        return [
            {**dict(row), "payload": json.loads(row["payload"])}
            for row in connection.execute(
                "SELECT * FROM events ORDER BY event_sequence"
            )
        ]
    finally:
        connection.close()


def test_loader_matches_text_to_verified_delivery_and_sanitizes_plan(sandbox):
    response_before = _sha256(sandbox["responses"])
    snapshot_before = _sha256(sandbox["snapshot"])

    batch = load_review_candidates(
        sandbox["snapshot"], sandbox["responses"], life_id=LIFE_ID
    )

    assert response_before == _sha256(sandbox["responses"])
    assert snapshot_before == _sha256(sandbox["snapshot"])
    assert [item.response_id for item in batch.candidates] == [
        "state",
        "activity",
        "other",
    ]
    state, activity, other = batch.candidates
    assert state.input_text.endswith("state")
    assert state.response_text.endswith("state")
    assert state.delivery_sequence == 2
    assert state.suggested_intent == "ASK_SELF_STATE"
    assert state.suggested_plan == {
        "schema_version": 1,
        "language": "ru",
        "activity": None,
        "last_completed_action": {"kind": "compose_music", "cycle": 2},
        "energy": 0.7,
        "allowed_claims": ["state.energy", "activity.completed:compose_music"],
    }
    assert activity.suggested_plan["activity"] == {
        "status": "current",
        "kind": "draw",
        "started_cycle": 4,
    }
    assert other.suggested_intent == "UNKNOWN_OR_OTHER"
    assert other.suggested_plan is None
    assert batch.skipped == {}
    encoded = json.dumps(batch.candidates[0].suggested_plan)
    for forbidden in ("PRIVATE", "baseline_text", "evidence_refs", "work_id"):
        assert forbidden not in encoded


def test_unmatched_snapshot_and_orphan_delivery_are_visible_not_labelled(sandbox):
    snapshot = json.loads(sandbox["snapshot"].read_text(encoding="utf-8"))
    snapshot["response_experience"]["responses"].append(_record("orphan", 6, None))
    sandbox["snapshot"].write_text(json.dumps(snapshot), encoding="utf-8")
    records = [_record("missing-snapshot", 7, None)]
    writer = ResponseExperienceJournal(sandbox["responses"], LIFE_ID)
    experience = type("Experience", (), {})()
    experience.responses = {}
    writer.record_delivery(experience, records[0], cycle=7, turn_id=None)
    writer.close()

    batch = load_review_candidates(
        sandbox["snapshot"], sandbox["responses"], life_id=LIFE_ID
    )

    assert len(batch.candidates) == 3
    assert batch.skipped == {"missing_delivery": 1, "missing_snapshot": 1}
    assert not any(item.response_id == "orphan" for item in batch.candidates)


def test_loader_skips_empty_input_as_unreviewable(sandbox):
    snapshot = json.loads(sandbox["snapshot"].read_text(encoding="utf-8"))
    snapshot["response_experience"]["responses"][2]["plan"]["observed_input"] = "  "
    sandbox["snapshot"].write_text(json.dumps(snapshot), encoding="utf-8")

    batch = load_review_candidates(
        sandbox["snapshot"], sandbox["responses"], life_id=LIFE_ID
    )

    assert [item.response_id for item in batch.candidates] == ["state", "activity"]
    assert batch.skipped == {"missing_input": 1}


def test_confirm_correct_abstain_and_reopen_end_to_end(sandbox):
    session = _session(sandbox)
    try:
        assert session.progress() == {
            "total": 3,
            "annotated": 0,
            "resolved_intent": 0,
            "resolved_plan": 0,
            "remaining": 3,
        }
        confirmed = session.confirm_current()
        assert confirmed["payload"]["intent_review"] == "confirmed"
        session.next()
        corrected = session.correct_current(
            "ASK_SELF_STATE",
            semantic_plan=session.current.suggested_plan
            and {
                "schema_version": 1,
                "language": "ru",
                "activity": None,
                "last_completed_action": None,
                "energy": 0.4,
                "allowed_claims": ["state.energy"],
            },
        )
        assert corrected["payload"]["intent_review"] == "corrected"
        assert corrected["payload"]["plan_review"] == "corrected"
        session.next()
        abstained = session.abstain_current()
        assert abstained["payload"]["intent_review"] == "abstained"
        assert abstained["payload"]["intent"] is None
        assert session.progress()["resolved_intent"] == 2
        assert session.progress()["resolved_plan"] == 2
        first_hash = confirmed["event_hash"]
    finally:
        session.close()

    reopened = _session(sandbox)
    try:
        assert reopened.current.response_id == "state"
        revised = reopened.correct_current(
            "UNKNOWN_OR_OTHER",
            semantic_plan=None,
        )
        assert revised["revision"] == 2
        assert revised["supersedes_event_hash"] == first_hash
        assert reopened.draft()["intent"] == "UNKNOWN_OR_OTHER"
        assert len(reopened.journal.events()) == 4
        dataset = prepare_r2_dataset(
            _response_events(sandbox["responses"]),
            reopened.journal.events(),
            life_id=LIFE_ID,
        )
        assert dataset["coverage"]["total"]["annotated"] == 3
        assert dataset["coverage"]["total"]["resolved_intent_labels"] == 2
    finally:
        reopened.close()


def test_existing_uncertainty_and_plan_abstention_survive_reload(sandbox):
    session = _session(sandbox)
    try:
        session.correct_current(
            "ASK_SELF_STATE",
            semantic_plan=session.current.suggested_plan,
            intent_uncertainties=("input_meaning",),
        )
        session.abstain_current_plan()
        session.next()
        session.abstain_current()
    finally:
        session.close()

    reopened = _session(sandbox)
    try:
        reopened.go_to(0)
        draft = reopened.draft()
        assert draft["intent_uncertainties"] == ("input_meaning",)
        assert draft["plan_review"] == "abstained"
        assert draft["semantic_plan"] is None
        assert draft["plan_uncertainties"] == ("plan_facts",)
        assert reopened.progress()["resolved_intent"] == 0
        reopened.next()
        assert reopened.draft()["intent"] is None
        assert reopened.draft()["intent_review"] == "abstained"
    finally:
        reopened.close()


def test_annotation_database_never_contains_private_text_hashes_or_targets(sandbox):
    session = _session(sandbox)
    try:
        for index in range(3):
            if index == 1:
                session.correct_current(
                    "ASK_SELF_ACTIVITY",
                    semantic_plan=session.current.suggested_plan,
                )
            else:
                session.confirm_current()
            session.next()
        raw = sandbox["annotations"].read_bytes()
        for forbidden in (
            PRIVATE_INPUT,
            PRIVATE_RESPONSE,
            "PRIVATE TARGET",
            "PRIVATE WORK",
            "PRIVATE REFERENCE",
            "baseline_text",
            "observed_input",
            "work_id",
            "text_sha256",
        ):
            assert forbidden.encode("utf-8") not in raw
    finally:
        session.close()


def test_all_paths_must_stay_inside_explicit_sandbox(sandbox, tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    for key in ("snapshot", "responses", "annotations"):
        paths = dict(sandbox)
        paths[key] = outside if key == "snapshot" else tmp_path / "outside.sqlite3"
        with pytest.raises(ReviewError, match="sandbox"):
            open_review_session(
                sandbox_root=paths["root"],
                snapshot_path=paths["snapshot"],
                response_journal_path=paths["responses"],
                annotation_journal_path=paths["annotations"],
                life_id=LIFE_ID,
            )


def test_cross_life_snapshot_is_rejected_before_annotation_file_creation(sandbox):
    snapshot = json.loads(sandbox["snapshot"].read_text(encoding="utf-8"))
    snapshot["life_id"] = OTHER_LIFE_ID
    sandbox["snapshot"].write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(ReviewError, match="life"):
        _session(sandbox)
    assert not sandbox["annotations"].exists()


def test_second_life_has_independent_annotation_journal(sandbox):
    first = _session(sandbox)
    first.confirm_current()
    first.close()

    other_root = sandbox["root"] / "second-life"
    other_root.mkdir()
    second_snapshot = other_root / "snapshot.json"
    second_snapshot.write_text(
        json.dumps(
            {"life_id": OTHER_LIFE_ID, "response_experience": {"responses": []}}
        ),
        encoding="utf-8",
    )
    empty_response = other_root / "responses.sqlite3"
    ResponseExperienceJournal(empty_response, OTHER_LIFE_ID).close()
    second = open_review_session(
        sandbox_root=other_root,
        snapshot_path=second_snapshot,
        response_journal_path=empty_response,
        annotation_journal_path=other_root / "annotations.sqlite3",
        life_id=OTHER_LIFE_ID,
    )
    try:
        assert second.candidates == ()
        assert second.progress()["annotated"] == 0
        assert second.journal.life_id == OTHER_LIFE_ID
    finally:
        second.close()
    labels = ResponseAnnotationJournal(sandbox["annotations"], LIFE_ID)
    try:
        assert len(labels.labels()) == 1
        assert labels.labels()[0]["life_id"] == LIFE_ID
    finally:
        labels.close()


def test_closed_or_empty_session_cannot_write(sandbox):
    session = _session(sandbox)
    session.close()
    with pytest.raises(AnnotationError, match="closed"):
        session.confirm_current()


def test_import_has_no_data_or_active_runtime_side_effects(sandbox_data_dir):
    env = os.environ.copy()
    env["DIGITAL_BEING_DATA_DIR"] = str(sandbox_data_dir)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import src.core.response_annotation_review; "
            "import src.ui.annotation_review_window; "
            "import tools.manual.review_response_annotations",
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert not sandbox_data_dir.exists()


def test_tk_window_shows_plain_text_and_saves_correction(sandbox):
    tk = pytest.importorskip("tkinter")
    from src.ui.annotation_review_window import AnnotationReviewWindow

    try:
        root = tk.Tk()
    except Exception as error:
        pytest.skip(f"нет дисплея: {error}")
    root.withdraw()
    session = _session(sandbox)
    try:
        window = AnnotationReviewWindow(session)
        window.build(root)
        root.geometry("1000x780")
        root.deiconify()
        root.update()
        assert "Сообщение человека" in window._input_label.cget("text")
        assert window._input_text.get("1.0", "end-1c").endswith("state")
        assert window._response_text.get("1.0", "end-1c").endswith("state")
        assert str(window._input_text.cget("state")) == tk.DISABLED
        assert str(window._response_text.cget("state")) == tk.DISABLED
        window._intent_var.set("UNKNOWN_OR_OTHER")
        window._save_correction()
        labels = session.journal.labels()
        assert labels[0]["response_id"] == "state"
        assert labels[0]["payload"]["intent"] == "UNKNOWN_OR_OTHER"
        assert session.current.response_id == "activity"
        window._energy_var.set("1.0")
        activity_plan = window._plan_from_fields("ASK_SELF_ACTIVITY")
        assert activity_plan["energy"] is None
        assert "state.energy" not in activity_plan["allowed_claims"]
        window._abstain()
        labels = session.journal.labels()
        assert labels[1]["response_id"] == "activity"
        assert labels[1]["payload"]["intent_review"] == "abstained"
        assert session.current.response_id == "other"
        assert "размечено: 2" in window._progress_label.cget("text")
        root.update()
        assert window._confirm_button.winfo_ismapped()
        assert window._correction_button.winfo_ismapped()
        assert window._previous_button.winfo_ismapped()
        assert window._next_button.winfo_ismapped()
    finally:
        session.close()
        root.destroy()


def test_tk_plan_abstention_uses_selected_intent_and_disables_for_other(sandbox):
    tk = pytest.importorskip("tkinter")
    from src.ui.annotation_review_window import AnnotationReviewWindow

    try:
        root = tk.Tk()
    except Exception as error:
        pytest.skip(f"нет дисплея: {error}")
    root.withdraw()
    session = _session(sandbox)
    try:
        window = AnnotationReviewWindow(session)
        window.build(root)
        root.update()

        window._intent_var.set("UNKNOWN_OR_OTHER")
        root.update()
        assert str(window._plan_abstain_button.cget("state")) == tk.DISABLED

        window._intent_var.set("ASK_SELF_ACTIVITY")
        root.update()
        assert str(window._plan_abstain_button.cget("state")) == tk.NORMAL
        window._abstain_plan()

        label = session.journal.labels()[0]
        assert label["payload"]["intent"] == "ASK_SELF_ACTIVITY"
        assert label["payload"]["plan_review"] == "abstained"
        assert label["payload"]["semantic_plan"] is None
        assert label["payload"]["plan_uncertainties"] == ["plan_facts"]
    finally:
        session.close()
        root.destroy()


def test_loader_accepts_segment_v2_journal(sandbox, tmp_path):
    path = tmp_path / "segment.sqlite3"
    writer = ResponseExperienceJournal(
        path,
        LIFE_ID,
        segment_id="segment-review-test",
        boundary_cycle=0,
        archive_manifest_hash="a" * 64,
        preexisting={("owner", "legacy-response")},
    )
    experience = type("Experience", (), {})()
    experience.responses = {}
    for record in sandbox["records"]:
        writer.record_delivery(experience, record, cycle=record["cycle"], turn_id=None)
        experience.responses[record["response_id"]] = record
    writer.close()

    batch = load_review_candidates(sandbox["snapshot"], path, life_id=LIFE_ID)

    assert len(batch.candidates) == 3
    events = _response_events(path)
    assert all(event["journal_schema_version"] == 2 for event in events)
    assert any(event["event_kind"] == "segment_exclusion" for event in events)
