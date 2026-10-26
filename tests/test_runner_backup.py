"""Сохранение и копия выполняются без уступки следующему тику."""

import asyncio
from unittest.mock import Mock

import pytest

from src.core.agent_runner import AgentRunner


@pytest.mark.asyncio
async def test_backup_has_no_yield_between_save_and_copy(monkeypatch):
    events = []
    runner = AgentRunner.__new__(AgentRunner)
    runner._save_state_safe = lambda: events.append("save") or True
    monkeypatch.setattr("src.memory.profile_backup.create_backup", lambda source, destination: events.append("copy") or destination)
    asyncio.get_running_loop().call_soon(events.append, "tick")
    assert runner.backup_now("new_backup") == "new_backup"
    assert events == ["save", "copy"]
    await asyncio.sleep(0)
    assert events == ["save", "copy", "tick"]


@pytest.mark.asyncio
async def test_failed_save_prevents_backup(monkeypatch):
    runner = AgentRunner.__new__(AgentRunner)
    runner._save_state_safe = lambda: False
    copy = Mock()
    monkeypatch.setattr("src.memory.profile_backup.create_backup", copy)
    with pytest.raises(RuntimeError):
        runner.backup_now("new_backup")
    assert not copy.called
