"""Событие имени не вызывает Tk из потока Core."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ui.chat_window import ChatWindow


@pytest.mark.asyncio
async def test_name_event_is_applied_only_in_ui_queue():
    window = ChatWindow(SimpleNamespace(subscribe=Mock()), "Alpha")
    root = Mock()
    window._root = root
    await window._on_agent_name_changed(SimpleNamespace(data={"new_name": "Омелла"}))
    root.title.assert_not_called()
    window._poll_incoming()
    assert window.agent_name == "Омелла"
    root.title.assert_called_once_with("💬 Омелла")
