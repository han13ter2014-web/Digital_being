"""Forgotten intention releases candidate attention; new interest is explicit."""

from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.cognition.intention_history import begin_intention, finish_intention
from src.cognition.intention_evidence import finish_evidence_goal
from src.cognition.intention_waiting import remember_wait, resolve_wait, start_new_intention
from src.cognition.intention_continuation import continuation_candidate


def setup_waiting():
    agent = DigitalBeing(name="ForgottenAttention")
    entry = begin_intention(agent, {"action": "explore", "params": {"topic": "память", "reason": "проверить"}})
    finish_intention(entry)
    finish_evidence_goal(agent, entry)
    agent.cycle_count += 1
    retry = begin_intention(agent, continuation_candidate(agent))
    finish_intention(retry)
    finish_evidence_goal(agent, retry)
    remember_wait(agent, retry)
    return agent


def test_forgotten_is_not_a_candidate_but_new_interest_is():
    agent = setup_waiting()
    assert resolve_wait(agent, "explore", "память", kind="forgotten", reason="отпустить")['status'] == "forgotten"
    assert continuation_candidate(agent) is None
    new = start_new_intention(agent, "explore", "память", reason="новый интерес")
    assert new["new_interest"]
    assert new["continuation_of"] is None
    assert new["id"] != next(iter(agent._waiting_intentions.values()))["id"]


def test_forgotten_does_not_delete_memory_or_change_values():
    agent = setup_waiting()
    values = list(agent.value_evolution.current_values)
    concepts = set(agent.mental_models.concepts)
    resolve_wait(agent, "explore", "память", kind="forgotten", reason="не сейчас")
    assert set(agent.mental_models.concepts) == concepts
    assert agent.value_evolution.current_values == values
