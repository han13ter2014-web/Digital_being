"""Минимальная авторитетная Core-запись жизненного эпизода."""

from types import SimpleNamespace
from unittest.mock import Mock

from src.core.agent import DigitalBeing
from src.cognition.intention_history import begin_intention, finish_intention


def test_core_records_finished_intention_only_when_memory_is_present():
    agent = DigitalBeing(name="CoreEpisode")
    memory = Mock()
    agent.delamain = SimpleNamespace(runtime=SimpleNamespace(memory=memory))
    entry = begin_intention(agent, {"action": "play", "source": "activity",
                                   "params": {"topic": "партия"}})
    finish_intention(entry, outcome=SimpleNamespace(reason="", as_dict=lambda: {"action": "play", "had_effect": True}))
    record = agent._record_core_life_episode(entry)
    assert record is not None
    kwargs = memory.record_life_episode.call_args.kwargs
    assert kwargs["life_id"] == "CoreEpisode"
    assert kwargs["intention_id"] == entry["id"]
    assert kwargs["target"] == "партия"
    assert kwargs["status"] == "performed"


def test_core_does_not_create_hidden_memory_without_delamain():
    agent = DigitalBeing(name="CoreNoMemory")
    entry = begin_intention(agent, {"action": "play", "params": {"topic": "игра"}})
    finish_intention(entry)
    assert agent._record_core_life_episode(entry) is None
    assert not hasattr(agent, "_life_episode_memory")


def test_episodes_are_append_only_for_retries():
    memory = Mock()
    agent = DigitalBeing(name="CoreRetries")
    agent.delamain = SimpleNamespace(runtime=SimpleNamespace(memory=memory))
    for status in ("error", "performed", "denied"):
        entry = begin_intention(agent, {"action": "play", "params": {"topic": "игра"}})
        finish_intention(entry, error=RuntimeError("bad") if status == "error" else None)
        if status == "denied":
            entry["status"] = "denied"
        agent._record_core_life_episode(entry)
    assert memory.record_life_episode.call_count == 3
