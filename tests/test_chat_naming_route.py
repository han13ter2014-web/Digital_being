"""«Просто имя» из чата уходит в propose_name, как обещает подсказка.

Подсказка NamingDialogue говорит: «Введите имя: >>> name <ваше_имя>
(или просто имя в строке ввода)». Раньше текст без слэша уходил в
USER_MESSAGE и агент имя не получал: ветка ``name `` в
_handle_command была недостижима. Теперь в фазе именования простой
текст маршрутизируется в USER_COMMAND ``propose_name``; решение
(принять/отклонить) по-прежнему принимает Core.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.core.event_bus import Events
from src.ui.chat_window import ChatWindow


class FakeBus:
    """Минимальная шина: записывает publish_sync, принимает подписки."""

    def __init__(self):
        self.published = []

    def subscribe(self, name, callback):
        pass

    def publish_sync(self, name, data=None, source="system", priority=1):
        self.published.append((name, dict(data or {})))


class FakeVar:
    """Заглушка tk.StringVar: UI ещё не построен."""

    def __init__(self, text):
        self.text = text

    def get(self):
        return self.text

    def set(self, value):
        self.text = value


def _make_window(text):
    bus = FakeBus()
    window = ChatWindow(bus, "Alpha")
    window._input_var = FakeVar(text)
    window._history = []
    window._history_idx = -1
    return window, bus


def _commands(bus):
    return [
        data.get("command")
        for name, data in bus.published
        if name == Events.USER_COMMAND
    ]


@pytest.mark.asyncio
async def test_plain_text_during_naming_routes_to_propose_name():
    window, bus = _make_window("Мелория")
    await window._on_naming_initiated(
        SimpleNamespace(data={"agent_name": "Alpha"})
    )
    window._on_send()
    assert _commands(bus) == ["propose_name Мелория"]
    assert not any(
        name == Events.USER_MESSAGE for name, _ in bus.published
    )


@pytest.mark.asyncio
async def test_plain_text_after_name_changed_is_normal_message():
    window, bus = _make_window("просто привет")
    await window._on_naming_initiated(
        SimpleNamespace(data={"agent_name": "Alpha"})
    )
    await window._on_agent_name_changed(
        SimpleNamespace(data={"new_name": "Омелла"})
    )
    window._on_send()
    assert any(
        name == Events.USER_MESSAGE for name, _ in bus.published
    )
    assert _commands(bus) == []


@pytest.mark.asyncio
async def test_slash_command_still_works_during_naming():
    window, bus = _make_window("/status")
    await window._on_naming_initiated(
        SimpleNamespace(data={"agent_name": "Alpha"})
    )
    window._on_send()
    assert _commands(bus) == ["status"]


def test_stop_routes_through_queue_without_tk_api():
    """stop() не зовёт Tk API из чужого потока — только очередь."""
    window, bus = _make_window("")
    root = Mock()
    window._root = root
    window.stop()
    root.after.assert_not_called()
    kind, _ = window._incoming_queue.get_nowait()
    assert kind == "__close__"
