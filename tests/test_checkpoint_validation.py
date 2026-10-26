from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.cognition.mental_models import ConceptNode
from src.core.checkpoint_migrations import SCHEMA_VERSION
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent
from src.core.checkpoint_validation import validate_checkpoint_state


@pytest.mark.parametrize("state", [{}, {"energy": -5}, {"schema_version": 0}, {
    "_goal_progress": {"12": ["legacy"]},
    "active_goal": "existing agent goal",
}, {"meta_learning": {"best_config": None, "best_fitness": None}}, {
    "meta_learning": {"best_fitness": float("-inf")},
}])
def test_legacy_omissions_and_sentinels_are_valid(state):
    assert validate_checkpoint_state(state) is None


@pytest.mark.parametrize("state,path", [
    ([], "state"),
    ({"schema_version": SCHEMA_VERSION + 1}, "schema_version"),
    ({"schema_version": "1"}, "schema_version"),
    ({"energy": float("nan")}, "energy"),
    ({"energy": float("inf")}, "energy"),
    ({"energy": True}, "energy"),
    ({"cycle_count": -1}, "cycle_count"),
    ({"cycle_count": 1.5}, "cycle_count"),
    ({"completed_goals": "2"}, "completed_goals"),
    ({"success_streak": False}, "success_streak"),
    ({"knowledge_base": []}, "knowledge_base"),
    ({"_known_definitions": None}, "_known_definitions"),
    ({"_learned_facts": [{}]}, "_learned_facts[0]"),
    ({"goals": {}}, "goals"),
    ({"goals": [None]}, "goals[0]"),
    ({"goals": [{"title": "missing id"}]}, "goals[0].id"),
    ({"goals": [{"id": 1}]}, "goals[0].title"),
    ({"goals": [], "active_goal": "absent"}, "active_goal"),
    ({"_goal_progress": {"bad": []}}, "_goal_progress.bad"),
    ({"_goal_progress": {"1": {"percentage": "bad"}}}, "_goal_progress.1.percentage"),
    ({"_goal_progress": {"1": {"last_update_cycle": float("inf")}}}, "_goal_progress.1.last_update_cycle"),
    ({"_goal_progress": {"1": {"matched_concepts": [[]]}}}, "_goal_progress.1.matched_concepts[0]"),
    ({"mental_models": {}}, "mental_models.concepts"),
    ({"mental_models": {"concepts": {"x": {"experiences": [None]}}}}, "mental_models.concepts.x.experiences[0]"),
    ({"mental_models": {"concepts": {"x": {"experiences": [{"valence": float("nan")}]}}}}, "mental_models.concepts.x.experiences[0].valence"),
    ({"mental_models": {"concepts": {"x": {"connections": {"y": "bad"}}}}}, "mental_models.concepts.x.connections.y"),
    ({"mental_models": {"concepts": {"x": {"created_at": "invalid"}}}}, "mental_models.concepts.x.created_at"),
    ({"mental_models": {"concepts": {}, "claims": {"bad": {}}}}, "mental_models.claims.bad.evidence"),
    ({"interoception": {"glucose": float("inf")}}, "interoception.glucose"),
    ({"continuous_time": {"subjective_time_dilation": "bad"}}, "continuous_time.subjective_time_dilation"),
    ({"death_risk": {"last_checkpoint_step": 1.5}}, "death_risk.last_checkpoint_step"),
    ({"consolidation": {"count": float("inf")}}, "consolidation.count"),
    ({"loop_closure": {"no_effect_streak": {"rest": float("nan")}}}, "loop_closure.no_effect_streak.rest"),
    ({"meta_learning": {"current_config": []}}, "meta_learning.current_config"),
    ({"meta_learning": {"population": [None]}}, "meta_learning.population[0]"),
    ({"meta_learning": {"best_fitness": float("inf")}}, "meta_learning.best_fitness"),
    ({"meta_learning": {"current_config": {"rate": float("-inf")}}}, "meta_learning.current_config.rate"),
    ({"social_cell": {"current_tom_level": 99}}, "social_cell.current_tom_level"),
    ({"social_cell": {"agent_models": {"peer": []}}}, "social_cell.agent_models.peer"),
    ({"social_cell": {"agent_models": {"peer": {"tom_level": 99}}}}, "social_cell.agent_models.peer.tom_level"),
    ({"social_cell": {"agent_models": {"peer": {"believed_goals": []}}}}, "social_cell.agent_models.peer.believed_goals"),
    ({"social_cell": {"self_model_as_seen_by_others": []}}, "social_cell.self_model_as_seen_by_others"),
    ({"motivation": {"needs": []}}, "motivation.needs"),
    ({"motivation": {"needs": {"curiosity": None}}}, "motivation.needs.curiosity"),
    ({"motivation": {"drives": {"exploration": []}}}, "motivation.drives.exploration"),
    ({"motivation": {"needs": {"curiosity": {"current_level": float("nan")}}}}, "motivation.needs.curiosity.current_level"),
    ({"motivation": {"drives": {"exploration": {"activation_count": "bad"}}}}, "motivation.drives.exploration.activation_count"),
    ({"motivation": {"goal_history": {}}}, "motivation.goal_history"),
    ({"open_questions": [None]}, "open_questions[0]"),
])
def test_invalid_fields_report_their_path(state, path):
    with pytest.raises(ValueError) as error:
        validate_checkpoint_state(state)
    assert path in str(error.value)


def test_validation_parses_concepts_and_claims_without_mutating_input():
    from src.cognition.empirical_claims import EmpiricalClaim

    node = ConceptNode("rest")
    claim = EmpiricalClaim.create("claim", "rest", "energy", "increase", {})
    state = {
        "mental_models": {
            "concepts": {"rest": node.to_storage_dict()},
            "claims": {"claim": claim.to_dict()},
            "metadata": {"custom": {"preserved": True}},
            "recent_associations": [],
        },
        "_goal_progress": {"1": {"matched_concepts": ["rest"], "percentage": "20", "last_update_cycle": "3"}},
        "goals": [{"id": 1, "title": "rest"}],
        "active_goal": "rest",
    }
    before = deepcopy(state)
    validate_checkpoint_state(state)
    assert state == before


def test_motivation_preflight_does_not_construct_system_or_apply_configs(monkeypatch):
    from src.core.motivation.unified_motivation import UnifiedMotivationSystem

    def forbidden(*args, **kwargs):
        pytest.fail("validation must not construct a motivation system")

    monkeypatch.setattr(UnifiedMotivationSystem, "__init__", forbidden)
    state = {
        "motivation": {
            "needs": {"curiosity": {"base_level": 0.5, "current_level": 0.2}},
            "drives": {"exploration": {"current_level": 0.3, "activation_count": 2}},
            "goal_history": [], "last_generated_cycle": 4,
        },
        "meta_learning": {
            "current_config": {"unknown_numeric_parameter": 1.5},
            "best_config": None, "population": [{"unknown_numeric_parameter": 2}],
            "best_fitness": None,
        },
    }
    before = deepcopy(state)
    validate_checkpoint_state(state)
    assert state == before


def test_claim_parser_rejects_unknown_metric():
    from src.cognition.empirical_claims import EmpiricalClaim

    claim = EmpiricalClaim.create("claim", "rest", "energy", "increase", {}).to_dict()
    claim["metric"] = "invalid"
    with pytest.raises(ValueError, match="mental_models.claims.claim"):
        validate_checkpoint_state({"mental_models": {"concepts": {}, "claims": {"claim": claim}}})


def _agent():
    node = ConceptNode("original")
    model = SimpleNamespace(
        concepts={"original": node}, claims={}, name="test", metadata={},
        association_memory=[], _related_cache={},
    )
    model.to_storage_dict = lambda: {
        "concepts": {key: value.to_storage_dict() for key, value in model.concepts.items()},
        "claims": {}, "name": model.name, "metadata": model.metadata,
        "recent_associations": model.association_memory,
    }
    return SimpleNamespace(
        name="test", energy=100, cycle_count=5, knowledge_base={"original": "known"},
        intelligence=1, completed_goals=0, goals=[{"id": 1, "title": "original"}],
        active_goal=None, success_streak=0, _goal_progress={}, _learned_facts=set(),
        _known_definitions={}, naming_dialogue=SimpleNamespace(phase="none", _name_history=[]),
        _open_questions=[], mental_models=model,
    )


@pytest.mark.parametrize("late_field", [
    {"social_cell": {"current_tom_level": 99}},
    {"motivation": {"needs": {"curiosity": None}}},
])
def test_apply_rejects_late_corruption_before_any_memory_mutation(late_field):
    agent = _agent()
    before = deepcopy(build_state_from_agent(agent))
    before.pop("saved_at")
    original_node = agent.mental_models.concepts["original"]
    replacement = ConceptNode("replacement")
    state = {
        "energy": 10,
        "knowledge_base": {"replacement": "new"},
        "mental_models": {"concepts": {"replacement": replacement.to_storage_dict()}},
        **late_field,
    }
    incoming = deepcopy(state)
    with pytest.raises(ValueError):
        apply_state_to_agent(agent, state)
    after = build_state_from_agent(agent)
    after.pop("saved_at")
    assert after == before
    assert agent.mental_models.concepts["original"] is original_node
    assert state == incoming
