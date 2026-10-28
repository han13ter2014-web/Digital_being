"""Творческий EffectorRequest отправляется только явно и идемпотентно."""

from unittest.mock import Mock, patch

import pytest

from src.core.effector_port import EffectorStatus
from src.core.workspace_request import creative_write_request
from src.delamain.effector import DelamainEffectorAdapter


def test_disabled_adapter_rejects_creative_submission():
    subsystem = Mock()
    adapter = DelamainEffectorAdapter(subsystem, enabled=False)
    with pytest.raises(Exception):
        adapter.submit(creative_write_request("draft.txt", "text"))
    subsystem.queue_goal.assert_not_called()


def test_enabled_adapter_submits_same_explicit_request_once():
    goal = {"id": 4, "metadata": {}}
    subsystem = Mock()
    subsystem.enabled = True
    subsystem.runtime = None
    subsystem.list_goals.return_value = []
    subsystem.queue_goal.return_value = {"id": 4}
    subsystem.get_goal.return_value = goal
    def goals():
        return ([{"id": 4, "metadata": {"effector_request_id": "creative-fixed",
                 "effector_fingerprint": adapter._request_fingerprint(request)}}]
                if subsystem.queue_goal.call_count else [])
    subsystem.list_goals.side_effect = goals
    adapter = DelamainEffectorAdapter(subsystem, enabled=True)
    request = creative_write_request("draft.txt", "text", request_id="creative-fixed")
    first = adapter.submit(request)
    second = adapter.submit(request)
    assert first.status == EffectorStatus.QUEUED
    assert second.status == EffectorStatus.QUEUED
    assert subsystem.queue_goal.call_count == 1


def test_creative_plan_contains_no_path_outside_workspace():
    request = creative_write_request("creative/draft.txt", "text")
    assert request.plan[0]["args"]["path"] == "creative/draft.txt"
