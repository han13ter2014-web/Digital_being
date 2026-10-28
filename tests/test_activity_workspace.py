"""Рабочая область занятия имеет фиксированную границу и свойства Sandbox."""

from pathlib import Path

import pytest

from src.core.activity_workspace import ActivityWorkspace
from src.delamain.sandbox import SandboxError


def test_workspace_root_is_profile_creative_and_roundtrip(tmp_path):
    workspace = ActivityWorkspace(tmp_path / "profile" / "delamain" / "workspace" / "creative")
    result = workspace.write("draft.txt", "текст")
    assert result["path"] == "draft.txt"
    assert workspace.read("draft.txt") == "текст"
    assert [item["path"] for item in workspace.list()] == ["draft.txt"]
    assert workspace.root.parts[-3:] == ("delamain", "workspace", "creative")


def test_workspace_rejects_escape_and_size():
    workspace = ActivityWorkspace()
    with pytest.raises(SandboxError):
        workspace.write("../outside.txt", "bad")
    with pytest.raises(SandboxError):
        workspace.write("large.txt", "x" * (workspace.MAX_FILE_BYTES + 1))
