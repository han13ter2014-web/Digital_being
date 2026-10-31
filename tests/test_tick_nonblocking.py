"""Цикл жизни не замораживает event loop на синхронных сетевых паузах.

До исправления ``autonomous_tick`` выполнялся прямо в корутине: каждый
Wikipedia-запрос (timeout 5 c × 2 языка + rate-limit 2 c) замораживал
EventBus, StatusLoop и откладывал tick_will/tick_communication.
Теперь цикл агента уходит в worker-поток (asyncio.to_thread), а loop
остаётся отзывчивым.
"""

import asyncio
import threading
from unittest.mock import patch

import pytest

from src.core.agent import DigitalBeing
from src.core.agent_runner import AgentRunner
from src.core.event_bus import EventBus


@pytest.mark.asyncio
async def test_loop_stays_responsive_while_agent_cycle_blocks():
    agent = DigitalBeing(name="NonBlockingTick")
    agent.ask_user("вопрос человека", source="self")
    runner = AgentRunner(agent, EventBus())
    await runner.start()

    block = threading.Event()
    calls = []

    def slow_tick():
        calls.append(True)
        assert block.wait(timeout=5), "гейт теста не отпущен"
        return {}

    heartbeats = 0

    async def heartbeat():
        nonlocal heartbeats
        while not block.is_set():
            heartbeats += 1
            await asyncio.sleep(0.01)

    with patch.object(agent, "autonomous_tick", side_effect=slow_tick):
        tick_task = asyncio.create_task(runner.step_once())
        hb_task = asyncio.create_task(heartbeat())

        await asyncio.sleep(0.2)

        assert calls, "цикл агента не начался"
        assert heartbeats > 5, "event loop заморожен во время цикла агента"

        block.set()
        await asyncio.wait_for(tick_task, timeout=5)
        hb_task.cancel()

    assert calls == [True]
    await runner.stop()
