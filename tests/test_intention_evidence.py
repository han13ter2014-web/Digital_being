"""Изменение WorldDelta не означает получение свидетельства о теме."""

from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.cognition.intention_history import begin_intention, finish_intention
from src.cognition.intention_evidence import finish_evidence_goal
from src.cognition.intention_continuation import continuation_candidate
from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent


def attempt(agent):
    return begin_intention(agent, {"action": "explore", "params": {"topic": "память"}})


def test_exposure_effect_does_not_finish_evidence_goal():
    agent = DigitalBeing(name="ExposureGoal")
    with patch.object(agent.decision_arbitrator, "choose_action", return_value={"action": "explore", "params": {"topic": "память"}}):
        # Регистрация темы — наблюдаемый эффект, но не свидетельство.
        def think(text):
            agent.mental_models.encounter_concept("память", "встреча", "Встретил неизвестную тему")
            return "Не знаю"
        with patch.object(agent, "think", side_effect=think):
            agent.autonomous_tick()
    entry = agent._intention_history[-1]
    assert entry["outcome"]["had_effect"]
    assert entry["evidence_goal"]["status"] == "pending"
    agent.cycle_count += 1
    assert continuation_candidate(agent)["params"]["topic"] == "память"


def test_failed_continuation_waits_for_new_information():
    agent = DigitalBeing(name="NoRepeatWithoutEvidence")
    original = attempt(agent)
    finish_intention(original)
    finish_evidence_goal(agent, original)
    agent.cycle_count += 1
    candidate = continuation_candidate(agent)
    retry = begin_intention(agent, candidate)
    finish_intention(retry)
    finish_evidence_goal(agent, retry)
    agent.cycle_count += 1
    assert continuation_candidate(agent) is None
    agent.knowledge_base["новый источник"] = "Новое содержательное объяснение"
    assert continuation_candidate(agent) is not None


def test_new_source_finishes_but_repeated_source_does_not():
    agent = DigitalBeing(name="EvidenceGoal")
    agent.mental_models.encounter_concept("память", "прочитал", "Сохранение и использование опыта", evidence_strength=0.7, evidence_kind="testimony", source="book:1")
    entry = attempt(agent)
    agent.mental_models.encounter_concept("память", "повтор", "Сохранение и использование опыта", evidence_strength=0.7, evidence_kind="testimony", source="book:1")
    finish_intention(entry)
    finish_evidence_goal(agent, entry)
    assert entry["evidence_goal"]["status"] == "pending"
    agent.mental_models.encounter_concept("память", "наблюдение", "Запись восстановилась после перезапуска", evidence_strength=0.5, evidence_kind="observation", source="action:2")
    finish_evidence_goal(agent, entry)
    assert entry["evidence_goal"]["status"] == "satisfied"
    assert entry["evidence_goal"]["new_sources"] == ["action:2"]
    state = build_state_from_agent(agent)
    apply_state_to_agent(agent, state)
    assert agent._intention_history[-1]["evidence_goal"]["status"] == "satisfied"
