"""Принятая пачка сообщений проходит настоящий save/start обоих backend."""

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
async def test_burst_survives_real_profile_restart(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", backend)
    PluginRegistry.reset_global()
    try:
        env = setup_environment(chdir=False, console=False)
        first, _ = create_agent(env, "MessageLife", new=True)
        runner = AgentRunner(first, EventBus())
        # «Собеседник-6»: _on_user_message больше не кладёт тексты в
        # очередь (нераспознанное получает честный отклик). Очередь
        # наполняем напрямую — тест проверяет непрерывность механизма
        # очереди через настоящий save/start, а не двери диалога.
        queue = PersistentMessageQueue(first)
        runner._pending_user_messages = queue
        messages = [f"вопрос {index // 2}" for index in range(40)]
        for text in messages:
            await queue.put(text)
        first._deferred_stimulus = {"text": "текущий вопрос", "user_initiated": True}
        assert runner.save_now()
        PluginRegistry.reset_global()
        second, report = create_agent(env, "MessageLife")
        assert report["source"] == "checkpoint"
        restored = AgentRunner(second, EventBus())
        await restored.start()
        restored.set_speed("max")
        received = []

        def perceive(text):
            received.append(text)
            return text

        with patch.object(
            second, "autonomous_tick", return_value={"attention_selected": True}
        ), patch.object(second, "perceive", side_effect=perceive), patch.object(
            second, "think", return_value="проверка"
        ), patch.object(second, "act", return_value="проверка"):
            for _ in range(41):
                await restored.step_once()
        assert received == ["текущий вопрос", *messages]
        assert second._deferred_stimulus is None
        assert second._pending_message_texts == []
        assert restored.save_now()
        await restored.stop()
        PluginRegistry.reset_global()
        third, _ = create_agent(env, "MessageLife")
        assert third._pending_message_texts == []
        assert third._deferred_stimulus is None
    finally:
        PluginRegistry.reset_global()
