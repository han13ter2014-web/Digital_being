"""Write-ahead сохранность принятых сообщений между checkpoint."""

from unittest.mock import patch

import pytest

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.core.agent_runner import AgentRunner, PersistentMessageQueue
from src.core.event_bus import EventBus
from src.core.subsystem_base import PluginRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["json", "sqlite"])
@pytest.mark.parametrize("dequeue_before_crash", [False, True])
async def test_accepted_message_survives_crash_before_next_checkpoint(
    tmp_path, monkeypatch, backend, dequeue_before_crash
):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "MessageCrashLife", new=True)
        first_runner = AgentRunner(first, EventBus())
        assert first_runner.save_now()
        queue = PersistentMessageQueue(first)
        first_runner._pending_user_messages = queue
        text = "сообщение после исходного снимка"
        await queue.put(text)
        if dequeue_before_crash:
            assert queue.get_nowait() == text

        # Авария: ни save_now, ни stop, ни нового checkpoint.
        PluginRegistry.reset_global()
        second, report = create_agent(env, "MessageCrashLife")
        assert report["source"] == "checkpoint"
        restored = AgentRunner(second, EventBus())
        await restored.start()
        received = []

        def perceive(value):
            received.append(value)
            return value

        with patch.object(
            second, "autonomous_tick", return_value={"attention_selected": True}
        ), patch.object(second, "perceive", side_effect=perceive), patch.object(
            second, "think", return_value="проверка"
        ), patch.object(second, "act", return_value="проверка"):
            await restored.step_once()

        assert received == [text]
        assert second._pending_message_texts == []
        assert second._deferred_stimulus is None
        await restored.stop()
    finally:
        PluginRegistry.reset_global()


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["json", "sqlite"])
async def test_processed_message_is_not_resurrected_from_stale_checkpoint(
    tmp_path, monkeypatch, backend
):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "MessageAckLife", new=True)
        runner = AgentRunner(first, EventBus())
        await runner.start()
        queue = PersistentMessageQueue(first)
        runner._pending_user_messages = queue
        text = "уже обработанное сообщение"
        await queue.put(text)
        # В снимке сообщение ещё ожидает обработки.
        assert runner.save_now()

        with patch.object(
            first, "autonomous_tick", return_value={"attention_selected": True}
        ), patch.object(first, "perceive", side_effect=lambda value: value), patch.object(
            first, "think", return_value="проверка"
        ), patch.object(first, "act", return_value="проверка"):
            await runner.step_once()
        assert first._pending_message_texts == []
        assert first._deferred_stimulus is None

        # Авария после подтверждения обработки, но до следующего checkpoint.
        PluginRegistry.reset_global()
        second, _ = create_agent(env, "MessageAckLife")
        assert second._pending_message_texts == [text]
        restored = AgentRunner(second, EventBus())
        await restored.start()
        assert restored._pending_user_messages.qsize() == 0
        assert second._pending_message_texts == []
        assert second._deferred_stimulus is None
        await restored.stop()
    finally:
        PluginRegistry.reset_global()
