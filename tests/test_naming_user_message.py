"""Обычный ответ на вопрос об имени должен попасть в NamingDialogue."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.core.agent_runner import AgentRunner
from src.core.subsystems.naming_dialogue import NamingDialogue


@pytest.mark.asyncio
async def test_user_message_during_naming_changes_core_name():
    agent = SimpleNamespace(
        name="Alpha",
        cycle_count=4,
        naming_dialogue=NamingDialogue(agent_name="Alpha"),
        propose_name=Mock(return_value={
            "status": "accepted", "new_name": "Малютка"
        }),
    )
    agent.naming_dialogue.phase = NamingDialogue.PHASE_AWAITING_NAME
    runner = AgentRunner.__new__(AgentRunner)
    runner.name = "Alpha"
    runner.agent = agent
    runner.bus = SimpleNamespace(publish=AsyncMock())

    event = SimpleNamespace(data={"text": "Малютка"})
    await runner._on_user_message(event)

    agent.propose_name.assert_called_once_with("Малютка", cycle=4)
    runner.bus.publish.assert_awaited_once()
    assert runner.bus.publish.call_args.args[0] == "agent_thought"
    assert "Малютка" in runner.bus.publish.call_args.args[1]["text"]
    assert not hasattr(runner, "_pending_user_messages")


def test_name_result_formatter_does_not_invent_alternative():
    text = AgentRunner._format_name_result(
        {"status": "alternative_proposed", "agent_alternative": "Альфа Jr."},
        "Малютка",
    )
    assert "Альфа Jr." in text
    assert "Малютка" not in text or "другое имя" in text
