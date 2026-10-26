"""Окончание runner должно завершать runtime и просить Tk закрыться через очередь."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from main import Runtime
from src.core.event_bus import EventBus
from src.ui.chat_window import ChatWindow


@pytest.mark.asyncio
async def test_failed_runner_stops_runtime_and_saves():
    async def fail():
        raise RuntimeError("runner failed")

    runner = SimpleNamespace(start=AsyncMock(), set_speed=Mock(), save_now=Mock(return_value=True),
                             run_forever=fail, stop=AsyncMock(), _stop_requested=False)
    runtime = Runtime(SimpleNamespace(name="test"), EventBus(), runner)
    await asyncio.wait_for(runtime._main("step"), timeout=5)
    assert runtime.error == "runner failed"
    assert runtime.saved_on_stop
    assert runner.stop.called


@pytest.mark.asyncio
async def test_save_failure_is_not_successful_shutdown():
    async def finish():
        return

    runner = SimpleNamespace(start=AsyncMock(), set_speed=Mock(), save_now=Mock(return_value=False),
                             run_forever=finish, stop=AsyncMock(), _stop_requested=False)
    runtime = Runtime(SimpleNamespace(name="test"), EventBus(), runner)
    await asyncio.wait_for(runtime._main("step"), timeout=5)
    assert not runtime.saved_on_stop
    assert "сохранить" in runtime.error


@pytest.mark.asyncio
async def test_dormant_runner_waits_and_resumes_without_new_task():
    from src.core.agent_runner import AgentRunner

    runner = AgentRunner.__new__(AgentRunner)
    runner.name = "WakeTest"
    runner._running = True
    runner._stop_requested = False
    state = {"value": "dormant", "steps": 0}
    runner.agent = SimpleNamespace(life_guard=SimpleNamespace(load_state=lambda: state["value"]))
    runner._agent_is_alive = lambda: state["value"] == "alive"
    runner._pause_poll_sec = lambda: 0.001
    runner.stop = AsyncMock()

    async def iteration():
        state["steps"] += 1
        runner._stop_requested = True

    runner._one_iteration = iteration
    task = asyncio.create_task(runner.run_forever())
    await asyncio.sleep(0.01)
    assert state["steps"] == 0
    assert not task.done()
    state["value"] = "alive"
    await asyncio.wait_for(task, timeout=1)
    assert state["steps"] == 1


def test_window_close_uses_queue_not_cross_thread_tk_calls():
    from queue import Queue

    window = ChatWindow.__new__(ChatWindow)
    window._incoming_queue = Queue()
    window._destroy_root = Mock()
    window.request_close()
    assert not window._destroy_root.called
    kind, data = window._incoming_queue.get_nowait()
    window._handle_incoming(kind, data)
    window._destroy_root.assert_called_once()
    assert not window._poll_running
