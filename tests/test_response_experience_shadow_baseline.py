"""RE-S1 phase 1: test-only event journal and deterministic baseline checks."""

import json
import math
import os
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from src.core.response_experience import ResponseExperience
from tests.observations.re_s1_response_experience import (
    B1_PRIOR_STRENGTH,
    OBSERVED_OUTCOMES,
    ResponseEventJournal,
    baseline_observation,
    controlled_history,
    feature_snapshot,
    fit_baselines,
    metric_values,
    predict_baseline,
    score_with_abstention,
    temporal_split,
)


def _features(
    *,
    life_id="life-a",
    profile_id="owner",
    context="social_reply",
    response_language="ru",
):
    return {
        "life_id": life_id,
        "profile_id": profile_id,
        "context": context,
        "response_language": response_language,
    }


def _sample(outcome, sequence, **feature_overrides):
    return {
        "features": _features(**feature_overrides),
        "outcome": outcome,
        "outcome_sequence": sequence,
    }


def _deliver(
    journal, experience, response_id, episode_id, cycle, context="social_reply"
):
    agent = SimpleNamespace(
        cycle_count=0,
        social_registry=SimpleNamespace(current_profile_id="owner"),
        social_attribution=None,
    )
    return journal.deliver(
        experience,
        agent,
        profile_id="owner",
        response_id=response_id,
        episode_id=episode_id,
        cycle=cycle,
        context=context,
    )


def test_observation_import_preserves_pytest_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    observation = (
        Path(__file__).parent / "observations" / "re_s1_response_experience.py"
    )

    runpy.run_path(str(observation))

    assert os.environ["DIGITAL_BEING_DATA_DIR"] == str(tmp_path)


def test_feature_snapshot_excludes_raw_text_and_cannot_see_future_outcome():
    journal = ResponseEventJournal("life-features")
    experience = ResponseExperience()
    delivered = _deliver(journal, experience, "response", "episode", 1)
    before = feature_snapshot(
        experience.responses["response"], life_id="life-features", episode_id="episode"
    )

    journal.observe(
        experience,
        profile_id="owner",
        response_id="response",
        outcome="explicit_support",
        cycle=2,
    )
    after = feature_snapshot(
        experience.responses["response"], life_id="life-features", episode_id="episode"
    )

    assert (
        before
        == after
        == {
            key: value for key, value in delivered.items() if key != "delivery_sequence"
        }
    )
    serialized = json.dumps(after, ensure_ascii=False)
    assert "Контролируемая реплика" not in serialized
    assert "Контролируемый вход" not in serialized
    for forbidden in (
        "status",
        "outcome",
        "observed_input",
        "base_text",
        "latest_response_id",
        "successful_uses",
    ):
        assert forbidden not in after


def test_controlled_inventory_separates_observed_expired_and_pending():
    journal = controlled_history("life-inventory")

    assert journal.inventory() == {
        "registered": 32,
        "observed": 30,
        "pending": 1,
        "expired": 1,
        "observed_class_counts": {
            "answer": 9,
            "follow_up": 6,
            "unclassified_reply": 3,
            "ordinary_reply": 6,
            "explicit_support": 3,
            "explicit_opposition": 3,
        },
        "missing_outcome_cycle": 0,
        "missing_episode_id": 0,
    }
    assert len(journal.samples()) == 30
    assert all(sample["outcome"] in OBSERVED_OUTCOMES for sample in journal.samples())


def test_temporal_split_keeps_whole_episodes_and_censors_are_not_labels():
    journal = controlled_history("life-split")

    split = temporal_split(journal)
    assert {name: len(split[name]) for name in ("train", "validation", "held_out")} == {
        "train": 19,
        "validation": 6,
        "held_out": 7,
    }
    assert set(split["train"]).isdisjoint(split["validation"])
    assert set(split["train"]).isdisjoint(split["held_out"])
    assert set(split["validation"]).isdisjoint(split["held_out"])
    train = journal.samples(
        episode_ids=set(split["train"]),
        outcome_before_sequence=split["train_outcome_before_sequence"],
    )
    held_out = journal.samples(episode_ids=set(split["held_out"]))
    assert len(train) == 19
    assert len(held_out) == 5
    assert all(
        sample["outcome_sequence"] < split["train_outcome_before_sequence"]
        for sample in train
    )
    assert "control-expired" in split["held_out"]
    assert "control-pending" in split["held_out"]


def test_late_train_outcome_is_excluded_by_event_sequence_cut():
    journal = ResponseEventJournal("life-late")
    experience = ResponseExperience()
    for index in range(5):
        _deliver(
            journal,
            experience,
            f"response-{index}",
            f"episode-{index}",
            index * 10,
        )
        if index != 0:
            journal.observe(
                experience,
                profile_id="owner",
                response_id=f"response-{index}",
                outcome="answer",
                cycle=index * 10 + 1,
            )
    # The first train episode receives feedback after later deliveries but
    # before its real TTL expires: event order, not expiry, is under test.
    journal.observe(
        experience,
        profile_id="owner",
        response_id="response-0",
        outcome="explicit_support",
        cycle=45,
    )
    split = temporal_split(journal)

    all_train = journal.samples(episode_ids=set(split["train"]))
    eligible_train = journal.samples(
        episode_ids=set(split["train"]),
        outcome_before_sequence=split["train_outcome_before_sequence"],
    )
    assert len(all_train) == 3
    assert len(eligible_train) == 2
    assert all(
        sample["features"]["response_id"] != "response-0" for sample in eligible_train
    )


def test_b0_b1_and_b2_use_only_frozen_training_history():
    samples = [
        _sample("answer", 1),
        _sample("explicit_opposition", 2, context="unknown_reply"),
    ]
    model = fit_baselines(samples, life_id="life-a")

    b0 = predict_baseline(model, "B0", _features())
    assert b0 == pytest.approx([0.25, 0.125, 0.125, 0.125, 0.125, 0.25])
    b1 = predict_baseline(model, "B1", _features())
    expected_b1 = [
        (1 + B1_PRIOR_STRENGTH * b0[0]) / 7,
        *(B1_PRIOR_STRENGTH * value / 7 for value in b0[1:]),
    ]
    assert b1 == pytest.approx(expected_b1)
    b2 = predict_baseline(model, "B2", _features())
    assert b2 == pytest.approx([2 / 7, 1 / 7, 1 / 7, 1 / 7, 1 / 7, 1 / 7])
    assert predict_baseline(model, "B2", _features(context="missing")) == b0


def test_baselines_do_not_cross_lives_or_mix_personal_contexts():
    with pytest.raises(ValueError, match="cross lives"):
        fit_baselines([_sample("answer", 1, life_id="life-b")], life_id="life-a")
    model = fit_baselines(
        [
            _sample("answer", 1, profile_id="owner"),
            _sample("explicit_opposition", 2, profile_id="guest"),
        ],
        life_id="life-a",
    )
    with pytest.raises(ValueError, match="cross lives"):
        predict_baseline(model, "B0", _features(life_id="life-b"))

    assert set(model["context_counts"]) == {
        ("owner", "social_reply", "ru"),
        ("guest", "social_reply", "ru"),
    }
    owner_b2 = predict_baseline(model, "B2", _features(profile_id="owner"))
    guest_b2 = predict_baseline(model, "B2", _features(profile_id="guest"))
    assert owner_b2[0] == pytest.approx(2 / 7)
    assert guest_b2[-1] == pytest.approx(2 / 7)


def test_abstention_uses_b0_fallback_and_cannot_improve_primary_score():
    samples = [_sample("answer", 1), _sample("explicit_opposition", 2)]
    model = fit_baselines(samples, life_id="life-a")
    predictions = [
        predict_baseline(model, "B1", sample["features"]) for sample in samples
    ]
    fallback = [predict_baseline(model, "B0", sample["features"]) for sample in samples]

    all_abstained = score_with_abstention(samples, predictions, [True, True], fallback)
    expected_fallback = metric_values(samples, fallback)
    assert all_abstained["coverage"] == 0.0
    assert all_abstained["log_loss"] == expected_fallback["log_loss"]
    none_abstained = score_with_abstention(
        samples, predictions, [False, False], fallback
    )
    assert none_abstained["coverage"] == 1.0
    assert none_abstained["log_loss"] == metric_values(samples, predictions)["log_loss"]


def test_controlled_baseline_is_deterministic_and_second_life_is_empty():
    first = baseline_observation("life-deterministic")
    second = baseline_observation("life-deterministic")

    assert first["journal"].events == second["journal"].events
    assert first["held_out_metrics"] == second["held_out_metrics"]
    empty = fit_baselines([], life_id="life-new")
    distribution = predict_baseline(empty, "B0", _features(life_id="life-new"))
    assert distribution == pytest.approx([1 / 6] * 6)
    assert not ResponseExperience().responses


def test_all_baselines_have_full_coverage_and_finite_probabilities():
    observation = baseline_observation("life-finite")

    for baseline in observation["held_out_metrics"].values():
        overall = baseline["overall"]
        assert overall["coverage"] == 1.0
        assert overall["examples"] == 5
        assert math.isfinite(overall["log_loss"])
        assert math.isfinite(overall["brier"])
        assert math.isfinite(overall["ece_10_bins"])
