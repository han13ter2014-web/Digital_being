"""Повторный запрос в одном цикле не создаёт второй порыв или сообщение."""

from unittest.mock import patch

from src.core.agent import DigitalBeing
from src.core.checkpoint_serializer import apply_state_to_agent, build_state_from_agent


def test_will_generates_at_most_once_per_cycle():
    agent = DigitalBeing(name="WillClockTest")
    with patch.object(agent.spontaneous_generator, "maybe_generate", return_value=None) as generate:
        agent.tick_will(10)
        assert agent.tick_will(10)["skipped"] == "duplicate_cycle"
        generate.assert_called_once()
        agent.tick_will(11)
        assert generate.call_count == 2


def test_communication_checks_initiative_once_per_cycle():
    agent = DigitalBeing(name="CommunicationClockTest")
    with patch.object(agent.proactive_communication, "maybe_initiate", return_value=None) as initiate:
        agent.tick_communication(10)
        assert agent.tick_communication(10)["skipped"] == "duplicate_cycle"
        initiate.assert_called_once()
        agent.tick_communication(11)
        assert initiate.call_count == 2


def test_restore_discards_transient_tick_markers():
    agent = DigitalBeing(name="RestoreClockTest")
    agent.cycle_count = 10
    state = build_state_from_agent(agent)
    agent.tick_will(10)
    agent.tick_communication(10)
    apply_state_to_agent(agent, state)
    assert agent._last_will_tick_cycle is None
    assert agent._last_communication_tick_cycle is None
