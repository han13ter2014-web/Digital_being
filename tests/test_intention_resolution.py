"""Оставленное намерение не возобновляется таймером или старым журналом."""

from src.core.agent import DigitalBeing
from src.cognition.intention_history import begin_intention, finish_intention
from src.cognition.intention_evidence import finish_evidence_goal
from src.cognition.intention_continuation import continuation_candidate
from src.cognition.intention_waiting import resolve_wait
from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent


def waiting_agent():
    agent = DigitalBeing(name="ResolutionTest")
    original = begin_intention(agent, {"action": "explore", "params": {"topic": "память"}})
    finish_intention(original)
    finish_evidence_goal(agent, original)
    agent.cycle_count += 1
    retry = begin_intention(agent, continuation_candidate(agent))
    finish_intention(retry)
    finish_evidence_goal(agent, retry)
    agent.cycle_count += 1
    return agent


def test_cancellation_is_not_success_and_survives_restore():
    agent = waiting_agent()
    result = resolve_wait(agent, "explore", "память", kind="cancelled", reason="сейчас мне важнее другое")
    assert result["status"] == "cancelled"
    assert resolve_wait(agent, "explore", "память", kind="completed", reason="другая причина")["status"] == "already_resolved"
    state = build_state_from_agent(agent)
    apply_state_to_agent(agent, state)
    agent.knowledge_base["новый материал"] = "Новые сведения"
    assert continuation_candidate(agent) is None
    entry = next(iter(agent._waiting_intentions.values()))
    assert entry["evidence_goal"]["status"] == "pending"
    assert entry["resolution"]["reason"] == "сейчас мне важнее другое"


def test_completion_requires_actual_evidence_not_operator_label():
    agent = waiting_agent()
    assert resolve_wait(agent, "explore", "память", kind="completed", reason="готово")["status"] == "not_satisfied"
    agent.mental_models.encounter_concept("память", "источник", "Память сохраняет и использует пережитый опыт",
        evidence_strength=0.8, evidence_kind="testimony", source="book:new")
    assert resolve_wait(agent, "explore", "память", kind="completed", reason="свидетельство получено")["status"] == "completed"
    assert continuation_candidate(agent) is None
