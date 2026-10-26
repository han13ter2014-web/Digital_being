"""Бесплодность учитывается до выбора, а не подавляет само желание."""

from unittest.mock import patch

from src.cognition.method_feedback import prepare_candidates
from src.core.agent import DigitalBeing
from src.core.world_delta import WorldSignature


def stuck_agent():
    agent = DigitalBeing(name="MethodFeedbackTest")
    for _ in range(3):
        agent.loop_closer.observe("explore", WorldSignature(), WorldSignature())
    return agent


def test_failed_method_is_deferred_without_changing_desire_or_input():
    agent = stuck_agent()
    candidates = [{"action": "exploration", "source": "motivation", "strength": 1.0},
                  {"action": "communicate", "source": "social", "strength": 0.3}]
    allowed, feedback = prepare_candidates(agent, candidates)
    assert allowed == [candidates[1]]
    assert len(candidates) == 2
    assert feedback["deferred"][0]["normalized_action"] == "explore"
    assert agent.loop_closer.is_stuck("explore")


def test_time_body_and_repetition_do_not_release_failed_method():
    agent = stuck_agent()
    candidates = [{"action": "explore"}]
    prepare_candidates(agent, candidates)
    agent.cycle_count += 100
    agent.energy = 200
    agent.mental_models.encounter_concept("тема", "повтор", "неизвестно")
    allowed, feedback = prepare_candidates(agent, candidates)
    assert not allowed
    assert not feedback["released"]


def test_new_information_allows_retry_but_not_denied_action():
    agent = stuck_agent()
    candidates = [{"action": "explore"}]
    prepare_candidates(agent, candidates)
    agent.knowledge_base["новый ответ"] = "Полученное содержательное объяснение"
    allowed, feedback = prepare_candidates(agent, candidates)
    assert allowed == candidates
    assert feedback["released"] == ["explore"]
    agent.loop_closer.observe("explore", WorldSignature(), WorldSignature(), reason="denied:budget")
    agent.knowledge_base["ещё ответ"] = "Другой ответ"
    assert not prepare_candidates(agent, candidates)[0]


def test_retry_context_survives_checkpoint():
    from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent

    first = stuck_agent()
    prepare_candidates(first, [{"action": "explore"}])
    second = DigitalBeing(name="MethodFeedbackTest")
    apply_state_to_agent(second, build_state_from_agent(first))
    assert not prepare_candidates(second, [{"action": "explore"}])[0]
    second.knowledge_base["ответ"] = "Новые сведения"
    assert prepare_candidates(second, [{"action": "explore"}])[0]


def test_arbiter_receives_alternatives_not_stuck_winner():
    agent = stuck_agent()
    captured = []

    def choose(candidates, context):
        captured.extend(candidates)
        return {**candidates[0], "verdict": "proceed", "reasoning": "test"}

    with patch.object(agent.decision_arbitrator, "choose_action", side_effect=choose):
        result = agent.autonomous_tick()
    assert captured
    assert all(agent._normalize_action(c["action"]) != "explore" for c in captured)
    assert result["method_feedback"]["deferred"]
    assert "loop_escape" not in result
