"""Творческий запрос получает узкий effector-план и не расширяет права."""

import pytest

from src.core.workspace_request import creative_write_request
from src.delamain.actions import ActionRegistry
from src.delamain.memory import MemoryStore
from src.delamain.sandbox import Sandbox, SandboxError
from pathlib import Path
def test_creative_request_is_explicit_bounded_and_dangerous_action():
    request = creative_write_request("draft.txt", "текст")
    assert request.metadata["activity"] == "creative"
    assert request.plan[0]["action"] == "write_creative_draft"
    assert request.success_predicate == "file_exists:draft.txt"
    with pytest.raises(ValueError):
        creative_write_request("../outside.txt", "bad")
    with pytest.raises(ValueError):
        creative_write_request("draft.py", "bad")


def test_registry_writes_only_under_creative_workspace(tmp_path):
    root = tmp_path / "creative"
    memory = MemoryStore(tmp_path / "memory.sqlite3")
    registry = ActionRegistry.default(Sandbox(root.parent, max_file_bytes=8192), memory)
    assert registry.get("write_creative_draft") is not None
    result = registry.execute("write_creative_draft", {"path": "draft.txt", "content": "текст"})
    assert result.ok
    assert (root / "draft.txt").read_text(encoding="utf-8") == "текст"
    outside = registry.execute("write_creative_draft", {"path": "../bad.txt", "content": "bad"})
    assert not outside.ok
