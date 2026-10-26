"""Тишина не замораживает время; evolve не повторяет уже прожитый soul tick."""

from unittest.mock import Mock, patch

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.event_bus import EventBus


def test_idle_tick_advances_life_without_stimulus_work():
    agent = DigitalBeing(name="IdleClockTest")
    runner = AgentRunner(agent, EventBus())
    before = agent.cycle_count
    with patch.object(agent, "think", side_effect=AssertionError("forced thought")):
        runner._rest_tick()
        assert agent.cycle_count == before + 1
        runner._rest_tick()
        assert agent.cycle_count == before + 2
    assert runner._tick_count == 2
    assert runner._last_tick_ledger["completed"]
    assert runner._last_tick_ledger["cycle_after"] == before + 2


def test_soul_is_not_ticked_twice_by_evolve():
    agent = DigitalBeing(name="SingleSoulTickTest")
    with patch.object(agent.soul, "tick", wraps=agent.soul.tick) as soul:
        first = agent.tick_soul(agent.cycle_count)
        second = agent.tick_soul(agent.cycle_count)
        agent.evolve()
        assert soul.call_count == 1
        assert second is first
        agent.cycle_count += 1
        agent.tick_soul(agent.cycle_count)
        assert soul.call_count == 2
