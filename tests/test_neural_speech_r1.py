"""R1: смысловые планы, read-only предсказания и инвентаризация журнала."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from src.core.response_shadow_inventory import (
    assess_readiness,
    inventory_events,
    samples_from_events,
    temporal_split,
)
from src.core.semantic_response_plan import (
    ActivityFact,
    CompletedActionFact,
    EvidenceRef,
    SemanticResponsePlan,
    build_self_activity_plan,
    build_self_state_plan,
)
from src.core.shadow_prediction import PredictionProvenance, ShadowPrediction

LIFE_ID = "00000000-0000-4000-8000-000000000001"
OTHER_LIFE_ID = "00000000-0000-4000-8000-000000000002"


def _entry(
    action="draw",
    *,
    status="started",
    cycle=10,
    identifier="intention-1",
    target="тихий сад",
    work_id=None,
):
    creative_intention = None
    if work_id is not None:
        creative_intention = {"work_id": work_id}
    return {
        "id": identifier,
        "cycle": cycle,
        "action": action,
        "status": status,
        "target": target,
        "decision_episode": (
            {"creative_intention": creative_intention}
            if creative_intention is not None
            else None
        ),
    }


def _agent(history, *, energy=0.625):
    return SimpleNamespace(
        cycle_count=12,
        energy=energy,
        _intention_history=history,
        _art_catalog={"art-1": {"id": "art-1"}},
        _music_catalog={"music-1": {"id": "music-1"}},
        _creative_catalog={"draft-1": {"id": "draft-1"}},
    )


def _prediction(**overrides):
    values = {
        "prediction_id": "prediction-1",
        "life_id": LIFE_ID,
        "profile_id": "owner",
        "response_id": "response-1",
        "episode_id": "episode-1",
        "delivery_sequence": 10,
        "prediction_sequence": 20,
        "feature_contract_version": "pj_structured_v1",
        "architecture_version": "baseline-b1-v1",
        "weights_version": "frozen-baseline-v1",
        "training_contract_version": "neural-speech-r1-v1",
        "probabilities": (0.5, 0.1, 0.1, 0.1, 0.1, 0.1),
        "abstain_reason": None,
        "provenance": PredictionProvenance(
            source_delivery_event_hash="a" * 64,
            training_response_ids=("response-0",),
            training_cutoff_sequence=9,
            training_sample_count=1,
        ),
    }
    values.update(overrides)
    return ShadowPrediction(**values)


def _event(
    kind,
    sequence,
    response_id,
    *,
    episode_id="__default__",
    outcome=None,
    outcome_cycle=None,
    event_hash=None,
):
    delivery = kind == "delivery"
    return {
        "event_id": f"{kind}:{response_id}",
        "event_sequence": sequence,
        "event_kind": kind,
        "life_id": LIFE_ID,
        "profile_id": "owner",
        "cycle": sequence * 10,
        "episode_id": (
            episode_id if episode_id != "__default__" else f"episode:{response_id}"
        ),
        "response_id": response_id,
        "event_hash": event_hash or f"{sequence:064x}",
        "payload": {
            "delivery_cycle": sequence * 10,
            "features": {
                "context": "social_reply",
                "response_language": "ru",
            },
            **(
                {}
                if delivery
                else {
                    "delivery_sequence": sequence - 1,
                    "observed_outcome": outcome or "answer",
                    "outcome_cycle": outcome_cycle,
                }
            ),
        },
    }


def test_activity_plan_is_immutable_serializable_and_grounded():
    agent = _agent([_entry(work_id="art-1")])

    plan = build_self_activity_plan(
        agent, response_id="response-activity", baseline_text="Сейчас я рисую."
    )

    assert plan.schema_version == 1
    assert plan.intent == "ASK_SELF_ACTIVITY"
    assert plan.activity == ActivityFact(
        status="current",
        kind="draw",
        work_id="art-1",
        started_cycle=10,
        target="тихий сад",
    )
    assert plan.energy is None
    assert plan.evidence_refs == (EvidenceRef(kind="intention", id="intention-1"),)
    assert "activity.current:draw" in plan.allowed_claims
    assert SemanticResponsePlan.from_dict(plan.to_dict()) == plan
    assert (
        json.loads(json.dumps(plan.to_dict(), ensure_ascii=False))["activity"][
            "work_id"
        ]
        == "art-1"
    )
    with pytest.raises(FrozenInstanceError):
        plan.baseline_text = "Выдуманный ответ"


def test_activity_plan_verifies_catalog_and_does_not_invent_new_work():
    existing = build_self_activity_plan(
        _agent([_entry(work_id="art-1")]),
        response_id="existing",
        baseline_text="Сейчас я рисую.",
    )
    forged = build_self_activity_plan(
        _agent([_entry(work_id="forged")]),
        response_id="forged",
        baseline_text="Сейчас я рисую.",
    )
    new_work = build_self_activity_plan(
        _agent([_entry()]),
        response_id="new",
        baseline_text="Сейчас я рисую.",
    )

    assert existing.activity.work_id == "art-1"
    assert forged.activity.work_id is None
    assert new_work.activity.work_id is None


def test_activity_plan_separates_current_none_and_last_completed():
    completed = _entry(
        action="compose_music",
        status="performed",
        cycle=7,
        identifier="intention-done",
        target="вечер",
    )
    plan = build_self_activity_plan(
        _agent([completed]),
        response_id="response-none",
        baseline_text="Сейчас нет действия. Раньше была мелодия.",
    )

    assert plan.activity == ActivityFact(status="none")
    assert plan.last_completed_action == CompletedActionFact(
        kind="compose_music", cycle=7, target="вечер"
    )
    assert "activity.none" in plan.allowed_claims
    assert "activity.completed:compose_music" in plan.allowed_claims
    assert "activity.current:compose_music" not in plan.allowed_claims


def test_interrupted_action_is_neither_current_nor_completed():
    plan = build_self_activity_plan(
        _agent([_entry(status="interrupted")]),
        response_id="response-interrupted",
        baseline_text="Сейчас у меня нет незавершённого действия.",
    )

    assert plan.activity == ActivityFact(status="none")
    assert plan.last_completed_action is None
    assert plan.evidence_refs == ()


def test_plan_copies_history_before_later_mutation():
    history = [_entry()]
    plan = build_self_activity_plan(
        _agent(history), response_id="copy", baseline_text="Сейчас я рисую."
    )

    history[0]["action"] = "web_search"
    history[0]["target"] = "другой факт"
    history[0]["cycle"] = 999

    assert plan.activity.kind == "draw"
    assert plan.activity.target == "тихий сад"
    assert plan.activity.started_cycle == 10


def test_state_plan_exposes_energy_without_inferring_feeling():
    completed = _entry(status="performed", action="reflect", cycle=4)
    plan = build_self_state_plan(
        _agent([completed]),
        response_id="state",
        baseline_text="Моя энергия сейчас 0.62.",
    )

    assert plan.intent == "ASK_SELF_STATE"
    assert plan.activity is None
    assert plan.energy == pytest.approx(0.625)
    assert EvidenceRef(kind="state", id="energy") in plan.evidence_refs
    assert "state.energy" in plan.allowed_claims
    assert not any("sad" in claim or "tired" in claim for claim in plan.allowed_claims)


@pytest.mark.parametrize(
    "activity",
    [
        ActivityFact(status="current", kind="draw"),
        ActivityFact(status="current", started_cycle=1),
        ActivityFact(status="none", kind="draw"),
        ActivityFact(status="none", started_cycle=1),
        ActivityFact(status="none", target="не текущая тема"),
    ],
)
def test_activity_fact_rejects_missing_or_contradictory_fields(activity):
    with pytest.raises(ValueError):
        SemanticResponsePlan(
            response_id="invalid",
            cycle=1,
            language="ru",
            intent="ASK_SELF_ACTIVITY",
            activity=activity,
            last_completed_action=None,
            energy=None,
            evidence_refs=(),
            allowed_claims=("activity.none",),
            baseline_text="Проверка.",
        )


def test_plan_from_dict_rejects_unknown_fields():
    data = build_self_activity_plan(
        _agent([_entry()]), response_id="strict", baseline_text="Сейчас я рисую."
    ).to_dict()
    data["private_dialogue"] = "не входит в контракт"

    with pytest.raises(ValueError, match="unknown fields"):
        SemanticResponsePlan.from_dict(data)


def test_shadow_prediction_round_trip_and_immutability():
    prediction = _prediction()

    assert ShadowPrediction.from_dict(prediction.to_dict()) == prediction
    assert sum(prediction.probabilities) == pytest.approx(1.0)
    with pytest.raises(FrozenInstanceError):
        prediction.response_id = "other"


def test_shadow_prediction_supports_explicit_abstention():
    prediction = _prediction(probabilities=None, abstain_reason="insufficient_history")

    assert prediction.abstain_reason == "insufficient_history"
    assert ShadowPrediction.from_dict(prediction.to_dict()) == prediction


@pytest.mark.parametrize(
    "overrides",
    [
        {"probabilities": (0.7, 0.1, 0.1, 0.1, 0.1, 0.1)},
        {"probabilities": (0.5, 0.1, 0.1), "abstain_reason": None},
        {"abstain_reason": "ambiguous"},
        {"probabilities": None},
        {"probabilities": None, "abstain_reason": ""},
    ],
)
def test_shadow_prediction_requires_six_probabilities_or_abstention(overrides):
    with pytest.raises(ValueError):
        _prediction(**overrides)


def test_shadow_prediction_rejects_cross_life_and_future_provenance():
    with pytest.raises(ValueError, match="life"):
        _prediction(
            provenance=PredictionProvenance(
                source_delivery_event_hash="a" * 64,
                training_response_ids=("response-0",),
                training_cutoff_sequence=9,
                training_sample_count=1,
                training_life_id=OTHER_LIFE_ID,
            )
        )
    with pytest.raises(ValueError, match="cutoff"):
        _prediction(
            provenance=PredictionProvenance(
                source_delivery_event_hash="a" * 64,
                training_response_ids=("response-0",),
                training_cutoff_sequence=11,
                training_sample_count=1,
            )
        )


def test_shadow_prediction_rejects_outcome_and_raw_text_fields():
    for field, value in (
        ("outcome", "answer"),
        ("raw_text", "личная реплика"),
        ("baseline_text", "текст ответа"),
    ):
        data = _prediction().to_dict()
        data[field] = value
        with pytest.raises(ValueError, match="unknown fields"):
            ShadowPrediction.from_dict(data)


def test_inventory_counts_outcomes_and_provenance_without_raw_text():
    events = [
        _event("delivery", 2, "r1"),
        _event("outcome", 3, "r1", outcome="answer", outcome_cycle=31),
        _event("delivery", 4, "r2"),
        _event("outcome", 5, "r2", outcome="explicit_support", outcome_cycle=51),
        _event("delivery", 6, "r3"),
    ]

    inventory = inventory_events(events, life_id=LIFE_ID)

    assert inventory["registered"] == 3
    assert inventory["observed"] == 2
    assert inventory["pending"] == 1
    assert inventory["expired"] == 0
    assert inventory["observed_class_counts"]["answer"] == 1
    assert inventory["observed_class_counts"]["explicit_support"] == 1
    assert inventory["missing_outcome_cycle"] == 0
    assert inventory["missing_episode_id"] == 0
    assert inventory["provenance_gaps"] == 0
    assert inventory["invalid_ordering"] == 0
    assert inventory["journal_gaps"] == 0
    samples = samples_from_events(events, life_id=LIFE_ID)
    assert samples[0]["features"]["life_id"] == LIFE_ID
    assert samples[0]["features"]["profile_id"] == "owner"
    assert samples[0]["features"]["delivery_cycle"] == 20
    assert "outcome" not in samples[0]["features"]


def test_inventory_marks_missing_provenance_and_invalid_ordering():
    delivery = _event("delivery", 2, "r1", episode_id=None)
    delivery["event_hash"] = None
    outcome = _event("outcome", 1, "r1", outcome="answer", outcome_cycle=None)

    inventory = inventory_events([delivery, outcome], life_id=LIFE_ID)

    assert inventory["missing_episode_id"] == 1
    assert inventory["missing_outcome_cycle"] == 1
    assert inventory["provenance_gaps"] >= 1
    assert inventory["invalid_ordering"] == 1
    assert samples_from_events([delivery, outcome], life_id=LIFE_ID) == []


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"delivery_cycle": 20}, {"delivery_cycle": 20, "features": None}],
)
def test_inventory_treats_malformed_delivery_payload_as_provenance_gap(payload):
    delivery = _event("delivery", 2, "r1")
    delivery["payload"] = payload
    outcome = _event("outcome", 3, "r1", outcome="answer", outcome_cycle=31)

    inventory = inventory_events([delivery, outcome], life_id=LIFE_ID)

    assert inventory["provenance_gaps"] == 1
    assert samples_from_events([delivery, outcome], life_id=LIFE_ID) == []


def test_temporal_split_keeps_whole_episodes_and_cuts_late_outcomes():
    events = []
    sequence = 1
    for index in range(5):
        response_id = f"r{index}"
        events.append(_event("delivery", sequence, response_id))
        sequence += 1
        if index:
            events.append(
                _event(
                    "outcome", sequence, response_id, outcome="answer", outcome_cycle=1
                )
            )
            sequence += 1
    late = _event("outcome", sequence, "r0", outcome="answer", outcome_cycle=99)
    late["payload"]["delivery_sequence"] = 1
    events.append(late)

    split = temporal_split(events, life_id=LIFE_ID)
    train_all = samples_from_events(
        events, life_id=LIFE_ID, episode_ids=set(split["train"])
    )
    train = samples_from_events(
        events,
        life_id=LIFE_ID,
        episode_ids=set(split["train"]),
        outcome_before_sequence=split["train_outcome_before_sequence"],
    )

    assert len(split["train"]) == 3
    assert len(split["validation"]) == 1
    assert len(split["held_out"]) == 1
    assert len(train_all) == 3
    assert len(train) == 2
    assert all(sample["response_id"] != "r0" for sample in train)


def test_inventory_rejects_cross_life_history():
    events = [_event("delivery", 2, "r1")]
    events[0]["life_id"] = OTHER_LIFE_ID

    with pytest.raises(ValueError, match="cross lives"):
        inventory_events(events, life_id=LIFE_ID)


def test_readiness_does_not_promote_controlled_outcomes_to_semantic_labels():
    events = []
    sequence = 1
    for index in range(50):
        response_id = f"r{index}"
        events.extend(
            [
                _event("delivery", sequence, response_id),
                _event(
                    "outcome",
                    sequence + 1,
                    response_id,
                    outcome=("answer" if index % 2 else "explicit_support"),
                    outcome_cycle=sequence * 10 + 1,
                ),
            ]
        )
        sequence += 2
    inventory = inventory_events(events, life_id=LIFE_ID)
    split = temporal_split(events, life_id=LIFE_ID)

    readiness = assess_readiness(
        inventory,
        split,
        events,
        life_id=LIFE_ID,
        confirmed_intent_labels=0,
        semantic_plan_labels=0,
    )

    assert readiness["status"] == "insufficient_data"
    assert readiness["outcome_baseline_status"] == "measurable"
    assert "confirmed_intent_labels" in readiness["missing"]
    assert "semantic_plan_labels" in readiness["missing"]
    assert readiness["training_allowed"] is False


def test_input_events_are_not_mutated():
    events = [
        _event("delivery", 2, "r1"),
        _event("outcome", 3, "r1", outcome="answer", outcome_cycle=31),
    ]
    original = deepcopy(events)

    inventory_events(events, life_id=LIFE_ID)
    temporal_split(events, life_id=LIFE_ID)
    samples_from_events(events, life_id=LIFE_ID)

    assert events == original
