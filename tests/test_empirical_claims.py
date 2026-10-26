"""Независимость выводов о разных свойствах одного действия."""

from unittest.mock import patch

from src.cognition.action_expectations import ActionExpectations
from src.cognition.empirical_claims import get_body_claim
from src.cognition.mental_models import MentalModel
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment


def test_same_trial_refutes_energy_but_supports_fatigue():
    model = MentalModel()
    learning = ActionExpectations()
    trial = learning.begin(model, "rest", 20, 200, fatigue=0.8)
    result = learning.finish(model, trial, 20, fatigue_after=0.5)
    assert result["claims"]["energy"]["status"] == "refuted"
    assert result["claims"]["fatigue"]["status"] == "supported"
    next_trial = learning.begin(model, "rest", 20, 200, fatigue=0.8)
    assert next_trial.expected_direction == -1
    assert next_trial.fatigue_expected_direction == 1


def test_energy_ceiling_does_not_block_fatigue_observation():
    model = MentalModel()
    learning = ActionExpectations()
    trial = learning.begin(model, "rest", 200, 200, fatigue=0.8)
    result = learning.finish(model, trial, 200, fatigue_after=0.5)
    assert "energy" not in result["claims"]
    assert result["supports_claim"] is None
    assert result["claims"]["fatigue"]["status"] == "supported"
    assert all(claim.metric != "energy" for claim in model.claims.values())


def test_unknown_and_conflicting_data_are_insufficient():
    model = MentalModel()
    claim = get_body_claim(model, "rest", "energy")
    assert claim.conclusion()["status"] == "insufficient"
    claim.observe("action:1", 20, 32, True, context="one")
    claim.observe("action:2", 20, 20, False, context="two")
    assert claim.conclusion()["status"] == "insufficient"


def test_existing_exact_energy_claim_migrates_without_fatigue_inference():
    model = MentalModel()
    model.encounter_concept("телесный опыт: rest повышает энергию ниже потолка", "trial:old", "роста нет",
                            evidence_strength=0.5, evidence_kind="observation", source="action:old", evidence_direction=-1)
    energy = get_body_claim(model, "rest", "energy")
    fatigue = get_body_claim(model, "rest", "fatigue")
    assert energy.conclusion()["status"] == "refuted"
    assert fatigue.conclusion()["status"] == "insufficient"
    assert energy.evidence_node.experiences[0]["source"] == "action:old"


def test_claim_export_roundtrip_keeps_conditions_and_sources():
    from src.cognition.empirical_claims import EmpiricalClaim

    model = MentalModel()
    claim = get_body_claim(model, "rest", "fatigue")
    claim.observe("action:one", 0.8, 0.5, True, context="trial:one")
    stored = model.to_storage_dict()["claims"][claim.claim_id]
    restored = EmpiricalClaim.from_dict(stored)
    assert restored.to_dict() == stored
    assert restored.conditions == {"fatigue_above_zero": True, "action_performed": True}
    assert restored.conclusion()["status"] == "supported"


def test_real_action_claims_survive_normal_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "life"))
    env = setup_environment(chdir=False)
    first, _ = create_agent(env, "ClaimLife", new=True)
    first.energy = 20
    first.interoception.state.fatigue = 0.8
    with patch.object(first, "_recover_energy", return_value=0.0):
        first.act("rest")
    energy = get_body_claim(first.mental_models, "rest", "energy")
    fatigue = get_body_claim(first.mental_models, "rest", "fatigue")
    assert energy.conclusion()["status"] == "refuted"
    assert fatigue.conclusion()["status"] == "supported"
    before = {key: claim.to_dict() for key, claim in first.mental_models.claims.items()}
    first.save_state(force=True)
    second, report = create_agent(env, "ClaimLife")
    assert report["source"] == "checkpoint"
    assert {key: claim.to_dict() for key, claim in second.mental_models.claims.items()} == before
    second.act("rest")
    assert second.action_expectations.last_trial["expected_direction"] == -1
    assert second.action_expectations.last_trial["fatigue_expected_direction"] == 1
