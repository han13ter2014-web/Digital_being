"""Проверка собственного представления может выиграть или уступить выбор."""

from unittest.mock import patch

from src.cognition.empirical_claims import get_body_claim
from src.cognition.experiment_proposals import propose_experiment
from src.cognition.mental_models import MentalModel
from src.core.subsystems.decision_arbitrator import DecisionArbitrator


def proposal(model, **kwargs):
    return propose_experiment(model, **({"energy": 80, "energy_max": 200,
                              "fatigue": 0.2, "cycle": 25} | kwargs))


def test_only_existing_uncertain_claim_is_proposed_without_side_effects():
    model = MentalModel()
    assert proposal(model) is None
    claim = get_body_claim(model, "rest", "energy")
    before = model.to_storage_dict()
    candidate = proposal(model)
    assert candidate["source"] == "self_experiment"
    assert candidate["params"]["claim_id"] == claim.claim_id
    assert model.to_storage_dict() == before


def test_conditions_cooldown_and_confident_refutation_prevent_proposal():
    model = MentalModel()
    claim = get_body_claim(model, "rest", "energy")
    assert proposal(model, energy=200) is None
    assert proposal(model, last_cycle=24) is None
    for index in range(3):
        claim.observe(f"trial:{index}", 80, 80, False, context="rest")
    assert claim.conclusion()["status"] == "refuted"
    assert proposal(model) is None


def test_fatigue_check_remains_possible_at_energy_ceiling():
    model = MentalModel()
    get_body_claim(model, "rest", "fatigue")
    assert proposal(model, energy=200)["params"]["metric"] == "fatigue"
    assert proposal(model, energy=200, fatigue=0) is None
    assert proposal(model, energy=200, fatigue=0.0000005) is None


def test_real_arbiter_can_choose_or_decline_experiment():
    model = MentalModel()
    get_body_claim(model, "rest", "energy")
    candidate = proposal(model)
    arbiter = DecisionArbitrator()
    verdict = {"score": 0.5, "verdict": "proceed", "confidence": 0.5,
               "reasoning": "равные условия", "voices": {}}
    with patch.object(arbiter, "arbitrate", return_value=verdict):
        weak = {"source": "other_desire", "action": "communicate", "strength": 0.1}
        strong = {**weak, "strength": 1.0}
        assert arbiter.choose_action([weak, candidate], {})["source"] == "self_experiment"
        assert arbiter.choose_action([strong, candidate], {})["source"] == "other_desire"


def test_autonomous_tick_offers_and_executes_selected_check():
    from src.core.agent import DigitalBeing

    agent = DigitalBeing(name="ExperimentChoiceTest")
    agent.energy = 80
    claim = get_body_claim(agent.mental_models, "rest", "energy")
    agent.cycle_count = 25

    def choose(candidates, context):
        candidate = next(item for item in candidates if item["source"] == "self_experiment")
        return {**candidate, "verdict": "proceed", "reasoning": "controlled selection"}

    with patch.object(agent.decision_arbitrator, "choose_action", side_effect=choose):
        result = agent.autonomous_tick()
    assert result["experiment_result"]["claim_id"] == claim.claim_id
    assert result["experiment_result"]["observation"]["claims"]["energy"]["status"] == "supported"
    assert agent._last_experiment_cycle == 25
    assert proposal(agent.mental_models, cycle=26, last_cycle=agent._last_experiment_cycle) is None


def test_observation_changes_proposed_claim():
    model = MentalModel()
    energy = get_body_claim(model, "rest", "energy")
    fatigue = get_body_claim(model, "rest", "fatigue")
    for index in range(3):
        energy.observe(f"energy:{index}", 20, 32, True, context="trial")
    assert proposal(model)["params"]["claim_id"] == fatigue.claim_id
