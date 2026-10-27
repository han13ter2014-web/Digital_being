"""Темп не определяет обязанность получать учебные вопросы."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from main import parse_args
from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.event_bus import EventBus


@pytest.mark.parametrize("speed", ["live", "fast", "max", "step"])
def test_quiet_has_no_generated_pool_at_any_speed(speed):
    agent = DigitalBeing(name="QuietStimuli")
    runner = AgentRunner(agent, EventBus())
    runner.set_speed(speed)
    with patch("src.core.agent_runner.select_novel_stimulus", side_effect=AssertionError("no imposed pool")) as pool:
        assert runner._next_stimulus() is None
    pool.assert_not_called()


def test_quiet_keeps_own_open_question():
    agent = DigitalBeing(name="OwnQuestionQuiet")
    agent.ask_user("почему", source="self")
    runner = AgentRunner(agent, EventBus())
    assert "почему" in runner._next_stimulus()


def test_pool_is_explicit_independent_of_speed():
    agent = DigitalBeing(name="ExplicitPool")
    runner = AgentRunner(agent, EventBus())
    runner.set_stimulus_mode("pool")
    with patch("src.core.agent_runner.select_novel_stimulus", return_value="лабораторный вопрос"):
        assert runner._next_stimulus() == "лабораторный вопрос"
    assert parse_args([]).stimuli == "quiet"
    assert parse_args(["--stimuli", "pool"]).stimuli == "pool"


@pytest.mark.asyncio
async def test_quiet_delivers_user_message_and_advances_idle_time():
    agent = DigitalBeing(name="UserInQuiet")
    runner = AgentRunner(agent, EventBus())
    await runner.start()
    before = agent.cycle_count
    with patch.object(agent, "autonomous_tick", return_value={}):
        await runner.step_once()
    assert agent.cycle_count == before + 1
    await runner._on_user_message(SimpleNamespace(data={"text": "сообщение"}))
    with patch.object(runner, "_do_one_agent_cycle") as process:
        await runner.step_once()
    process.assert_called_once_with("сообщение", user_initiated=True)
    await runner.stop()
