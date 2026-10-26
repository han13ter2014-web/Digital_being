"""Ожидание до действия, наблюдение после, пересмотр без принуждения."""

from dataclasses import FrozenInstanceError

import pytest

from src.cognition.action_expectations import ActionExpectations
from src.cognition.mental_models import MentalModel
from src.core.agent import DigitalBeing
from config.simulation_config import LR_CONFIG


def test_prediction_precedes_observation_and_is_immutable():
    model = MentalModel()
    learning = ActionExpectations()
    trial = learning.begin(model, "rest", 10.0, 200.0)
    assert trial.expected_direction == 1
    assert model.concepts[trial.claim].evidence()[0] == 0
    with pytest.raises(FrozenInstanceError):
        trial.energy_before = 50
    result = learning.finish(model, trial, 22.0)
    assert result["prediction_matched"]
    assert result["supports_claim"]
    assert result["delta"] == 12
    assert learning.finish(model, trial, 22.0) is None
    assert len(model.concepts[trial.claim].experiences) == 2


def test_failed_expectation_is_not_success_and_changes_next_prediction():
    model = MentalModel()
    learning = ActionExpectations()
    first = learning.begin(model, "rest", 10.0, 200.0)
    result = learning.finish(model, first, 10.0)
    assert not result["prediction_matched"]
    assert not result["supports_claim"]
    node = model.concepts[first.claim]
    assert node.experiences[-1]["evidence_direction"] == -1
    next_trial = learning.begin(model, "rest", 10.0, 200.0)
    assert next_trial.expected_direction == -1
    assert learning.finish(model, next_trial, 10.0)["prediction_matched"]


def test_negative_conclusion_is_not_reported_as_support():
    model = MentalModel()
    learning = ActionExpectations()
    for _ in range(4):
        trial = learning.begin(model, "rest", 10, 200)
        learning.finish(model, trial, 10)
    understanding = model.get_concept_understanding(trial.claim)
    assert understanding["evidence_direction"] == -1
    assert understanding["confidence"] > 0.5
    assert "не наблюдалось" in understanding["hypothesis"]


def test_conflicting_observation_reduces_certainty():
    model = MentalModel()
    learning = ActionExpectations()
    trial = learning.begin(model, "deep_rest", 10.0, 200.0)
    learning.finish(model, trial, 40.0)
    confidence = model.concepts[trial.claim].confidence
    second = learning.begin(model, "deep_rest", 10.0, 200.0)
    learning.finish(model, second, 10.0)
    assert model.concepts[trial.claim].confidence < confidence


@pytest.mark.parametrize("energy", [200, 201, -1, float("nan")])
def test_uninformative_or_invalid_context_is_not_evidence(energy):
    model = MentalModel()
    learning = ActionExpectations()
    assert learning.begin(model, "rest", energy, 200.0) is None
    assert not model.concepts


def test_unrelated_action_and_cancel_do_not_create_observation():
    model = MentalModel()
    learning = ActionExpectations()
    assert learning.begin(model, "explore", 10, 200) is None
    trial = learning.begin(model, "rest", 10, 200)
    learning.cancel(trial)
    assert learning.finish(model, trial, 22) is None
    assert model.concepts[trial.claim].evidence()[0] == 0


def test_rest_action_records_actual_numeric_outcome(monkeypatch):
    agent = DigitalBeing(name="BodyExpectationTest")
    agent.energy = 20
    agent.act("rest")
    observed = agent.action_expectations.last_trial
    assert observed["energy_before"] == 20
    assert observed["delta"] == pytest.approx(LR_CONFIG.REST_ENERGY_RECOVERY)
    assert observed["prediction_matched"]
    assert observed["energy_after"] == agent.energy
    assert agent.mental_models.concepts[observed["claim"]].evidence()[0] == 0.5
    # Текст успешного действия не подменяет отсутствие восстановления.
    monkeypatch.setattr(agent, "_recover_energy", lambda deep=False: 0.0)
    agent.act("rest")
    assert not agent.action_expectations.last_trial["prediction_matched"]
    assert agent.action_expectations.last_trial["delta"] == 0


def test_rest_at_ceiling_does_not_refute_recovery():
    agent = DigitalBeing(name="CeilingExpectationTest")
    agent.energy = LR_CONFIG.ENERGY_MAX
    agent.act("deep_rest")
    assert agent.action_expectations.last_trial is None
    assert not any(name.startswith("телесный опыт:") for name in agent.mental_models.concepts)


def test_new_attempt_cannot_complete_stale_trial():
    model = MentalModel()
    learning = ActionExpectations()
    first = learning.begin(model, "rest", 10, 200)
    second = learning.begin(model, "rest", 20, 200)
    assert learning.finish(model, first, 22) is None
    assert learning.finish(model, second, 32)["prediction_matched"]


def test_partial_headroom_is_valid_confirmation():
    model = MentalModel()
    learning = ActionExpectations()
    trial = learning.begin(model, "rest", 199, 200)
    result = learning.finish(model, trial, 200)
    assert result["prediction_matched"]
    assert result["delta"] == 1


def test_evidence_retains_next_prediction_after_storage_roundtrip():
    from src.cognition.mental_models import ConceptNode

    model = MentalModel()
    learning = ActionExpectations()
    trial = learning.begin(model, "rest", 10, 200)
    learning.finish(model, trial, 10)
    restored = MentalModel()
    restored.concepts[trial.claim] = ConceptNode.from_dict(model.concepts[trial.claim].to_storage_dict())
    fresh_learning = ActionExpectations()
    assert fresh_learning.begin(restored, "rest", 10, 200).expected_direction == -1
