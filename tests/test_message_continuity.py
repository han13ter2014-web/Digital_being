"""Вопрос в работе и ожидающие сообщения сохраняются раздельно и по порядку."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_serializer import build_state_from_agent, apply_state_to_agent
from src.core.checkpoint_validation import validate_checkpoint_state
from src.core.event_bus import EventBus


@pytest.mark.asyncio
async def test_pending_messages_survive_checkpoint_preserving_duplicates():
    first = DigitalBeing(name="MessageContinuity")
    runner = AgentRunner(first, EventBus())
    for text in ("одинаковый", "одинаковый", "последний"):
        await runner._on_user_message(SimpleNamespace(data={"text": text}))
    first._deferred_stimulus = {"text": "уже выбранный", "user_initiated": True}
    state = build_state_from_agent(first)
    second = DigitalBeing(name="MessageContinuity")
    apply_state_to_agent(second, state)
    restored = AgentRunner(second, EventBus())
    await restored.start()
    assert restored._pending_user_messages.qsize() == 3
    received = []

    def process(text, user_initiated=False):
        received.append(text)
        second._deferred_stimulus = None

    with patch.object(restored, "_do_one_agent_cycle", side_effect=process):
        for _ in range(4):
            await restored.step_once()
    assert received == ["уже выбранный", "одинаковый", "одинаковый", "последний"]
    assert second._pending_message_texts == []
    assert build_state_from_agent(second)["pending_user_messages"] == []
    await restored.stop()


def test_invalid_pending_message_rejected_before_restore():
    with pytest.raises(ValueError, match="pending_user_messages"):
        validate_checkpoint_state({"pending_user_messages": ["ok", {"text": "bad"}]})
