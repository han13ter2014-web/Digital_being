"""Единый творческий путь: submit → approval → core step → activity/restart."""

from pathlib import Path
from unittest.mock import patch

import pytest

from config.simulation_config import LR_CONFIG
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.core.subsystem_base import PluginRegistry
from src.core.workspace_request import creative_write_request


def make_sub(tmp_path):
    from src.delamain.subsystem import DelamainSubsystem

    return DelamainSubsystem(
        agent_name="EffectorCreativeLife", workspace=tmp_path / "workspace",
        db_path=tmp_path / "delamain.sqlite3", enabled=True,
        approval_mode="dangerous", effector_enabled=True, core_driven=True,
        tick_interval=1,
    )


def test_approval_waits_then_core_step_succeeds_and_is_idempotent(tmp_path):
    sub = make_sub(tmp_path)
    sub.setup({})
    try:
        request = creative_write_request("draft.txt", "Маленькая композиция", request_id="creative-fixed")
        first = sub.effector.submit(request)
        waiting = sub.effector.step(1)
        assert waiting.status.value == "waiting_approval"
        approved = sub.approve(waiting.approval_id)
        assert approved["status"] == "approved"
        assert sub.effector.poll(request.request_id).status.value == "queued"
        result = sub.effector.step(2)
        assert result.status.value == "succeeded"
        assert result.ok
        assert (tmp_path / "workspace" / "creative" / "draft.txt").read_text(encoding="utf-8") == "Маленькая композиция"
        duplicate = sub.effector.submit(request)
        assert duplicate.status.value == "succeeded"
        assert sub.list_goals().__len__() == 1
    finally:
        sub.teardown()


def test_rejected_creative_request_never_creates_success(tmp_path):
    sub = make_sub(tmp_path)
    sub.setup({})
    try:
        request = creative_write_request("draft.txt", "текст", request_id="creative-rejected")
        waiting = sub.effector.submit(request)
        pending = sub.effector.step(1)
        rejected = sub.reject(pending.approval_id, "не сейчас")
        assert rejected["ok"] is False
        assert rejected["approval_status"] == "rejected"
        final = sub.effector.poll(request.request_id)
        assert final.status.value == "rejected"
        assert not (tmp_path / "workspace" / "creative" / "draft.txt").exists()
    finally:
        sub.teardown()
