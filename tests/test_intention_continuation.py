"""Отдых не стирает выбранную тему, а возвращение остаётся необязательным."""

from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.cognition.intention_history import begin_intention, finish_intention
from src.cognition.intention_continuation import continuation_candidate
from src.core.world_delta import WorldSignature


def pending(agent):
    entry = begin_intention(agent, {"action": "explore", "source": "test",
                                   "params": {"topic": "память", "reason": "интерес"}})
    finish_intention(entry)
    agent.cycle_count += 1
    return entry


def test_unfinished_topic_remains_after_rest_and_has_reason():
    agent = DigitalBeing(name="ContinueAfterRest")
    entry = pending(agent)
    rest = begin_intention(agent, {"action": "rest", "source": "body"})
    finish_intention(rest)
    agent.cycle_count += 1
    candidate = continuation_candidate(agent)
    assert candidate["params"]["topic"] == "память"
    assert candidate["params"]["reason"] == "интерес"
    assert candidate["params"]["continuation_of"] == entry["id"]


def test_continuation_survives_state_restore():
    from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent

    first = DigitalBeing(name="ContinueRestore")
    entry = pending(first)
    second = DigitalBeing(name="ContinueRestore")
    apply_state_to_agent(second, build_state_from_agent(first))
    candidate = continuation_candidate(second)
    assert candidate["params"]["continuation_of"] == entry["id"]
    assert candidate["params"]["topic"] == "память"


def test_stuck_method_is_not_retried_by_continuation():
    agent = DigitalBeing(name="ContinueStuck")
    pending(agent)
    for _ in range(3):
        agent.loop_closer.observe("explore", WorldSignature(), WorldSignature())
    assert continuation_candidate(agent) is None


def test_continuation_can_lose_and_later_execute_same_topic():
    agent = DigitalBeing(name="ContinueChoice")
    original = pending(agent)
    with patch.object(agent.decision_arbitrator, "choose_action", return_value={"action": "rest", "source": "body"}):
        report = agent.autonomous_tick()
    assert report["continuation_proposal"]["params"]["topic"] == "память"
    assert agent._intention_history[-1]["action"] == "rest"
    agent.cycle_count += 1

    def choose(candidates, context):
        return next(c for c in candidates if c["source"] == "intention_continuation")

    with patch.object(agent.decision_arbitrator, "choose_action", side_effect=choose), \
         patch.object(agent, "think", return_value="Не знаю") as think:
        agent.autonomous_tick()
    think.assert_called_once_with("вопрос: память")
    assert agent._intention_history[-1]["continuation_of"] == original["id"]
