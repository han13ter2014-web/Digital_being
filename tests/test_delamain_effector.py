"""Stage 18A: contract tests for the core-owned effector boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.effector_port import (
    EffectorConflict,
    EffectorDisabled,
    EffectorPort,
    EffectorRequest,
    EffectorStatus,
)
from src.delamain.subsystem import DelamainSubsystem


def make_sub(tmp_path: Path, **kwargs) -> DelamainSubsystem:
    params = {
        "agent_name": "EffectorTest",
        "workspace": tmp_path / "workspace",
        "db_path": tmp_path / "memory.sqlite3",
        "enabled": True,
        "tick_interval": 1,
        "effector_enabled": True,
    }
    params.update(kwargs)
    return DelamainSubsystem(**params)


def write_request(
    request_id: str = "req-1",
    *,
    content: str = "hello",
    path: str = "notes/a.txt",
) -> EffectorRequest:
    return EffectorRequest(
        request_id=request_id,
        goal="write a note",
        plan=[
            {
                "action": "write_file",
                "args": {"path": path, "content": content},
            }
        ],
    )


def test_request_validation_and_normalization() -> None:
    with pytest.raises(ValueError):
        EffectorRequest("", "goal", command="write a.txt: x")
    with pytest.raises(ValueError):
        EffectorRequest("req", "goal")
    with pytest.raises(ValueError):
        EffectorRequest(
            "req",
            "goal",
            command="write a.txt: x",
            plan=[{"action": "write_file", "args": {"path": "a.txt", "content": "x"}}],
        )
    with pytest.raises(TypeError):
        EffectorRequest("req", "goal", plan=["not-a-mapping"])  # type: ignore[list-item]

    request = EffectorRequest(
        " req ",
        " goal ",
        plan=[{"action": "read_file", "args": {"path": "a.txt"}}],
        priority=2.0,
    )
    assert request.request_id == "req"
    assert request.goal == "goal"
    assert request.priority == 1.0
    assert request.plan == ({"action": "read_file", "args": {"path": "a.txt"}},)
    assert request.to_dict()["plan"][0]["action"] == "read_file"


def test_effector_is_disabled_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DELAMAIN_EFFECTOR_ENABLED", raising=False)
    sub = DelamainSubsystem(
        agent_name="EffectorTest",
        workspace=tmp_path / "workspace",
        db_path=tmp_path / "memory.sqlite3",
        enabled=False,
    )

    assert sub.effector.enabled is False
    assert sub.effector.poll("missing").status is EffectorStatus.DISABLED
    with pytest.raises(EffectorDisabled):
        sub.effector.submit(write_request())
    assert sub.runtime is None
    assert not (tmp_path / "workspace").exists()


def test_adapter_can_be_enabled_explicitly(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)
    try:
        sub.setup({})
        assert isinstance(sub.effector, EffectorPort)
        assert sub.effector.enabled is True
        assert sub.effector.status()["enabled"] is True
    finally:
        sub.teardown()


def test_submit_is_idempotent_and_executes_once(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)
    sub.setup({})
    events: list[tuple[str, dict]] = []
    sub.effector.event_sink = lambda name, data: events.append((name, dict(data)))
    try:
        request = write_request()
        first = sub.effector.submit(request)
        assert first.status is EffectorStatus.QUEUED
        assert first.goal_id == 1

        duplicate = sub.effector.submit(request)
        assert duplicate.status is EffectorStatus.QUEUED
        assert duplicate.goal_id == first.goal_id
        assert len(sub.list_goals()) == 1

        event = sub.tick(1, {})
        assert event is not None
        final = sub.effector.poll(request.request_id)
        assert final.status is EffectorStatus.SUCCEEDED
        assert final.ok is True
        assert final.detail["attempts"] == 1
        assert (tmp_path / "workspace" / "notes" / "a.txt").read_text(
            encoding="utf-8"
        ) == "hello"

        # Polling a terminal request is observational, not a second execution.
        again = sub.effector.poll(request.request_id)
        assert again.status is EffectorStatus.SUCCEEDED
        assert len(sub.list_goals()) == 1
        assert [name for name, _ in events] == [
            "effector.queued",
            "effector.duplicate",
            "effector.succeeded",
        ]
    finally:
        sub.teardown()


def test_duplicate_id_with_different_payload_is_a_conflict(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)
    try:
        sub.effector.submit(write_request("same-id", content="first"))
        with pytest.raises(EffectorConflict):
            sub.effector.submit(write_request("same-id", content="second"))
        assert len(sub.list_goals()) == 1
    finally:
        sub.teardown()


def test_approval_waits_without_side_effects(tmp_path: Path) -> None:
    sub = make_sub(tmp_path, approval_mode="dangerous")
    try:
        request = write_request("needs-approval")
        sub.effector.submit(request)
        sub.tick(1, {})

        pending = sub.effector.poll(request.request_id)
        assert pending.status is EffectorStatus.WAITING_APPROVAL
        assert pending.approval_id
        assert pending.ok is False
        assert not (tmp_path / "workspace" / "notes" / "a.txt").exists()
        assert sub.status()["approval"]["counts"]["pending"] == 1

        approved = sub.approve(pending.approval_id)
        assert approved["ok"] is True
        done = sub.effector.poll(request.request_id)
        assert done.status is EffectorStatus.SUCCEEDED
        assert (tmp_path / "workspace" / "notes" / "a.txt").exists()
    finally:
        sub.teardown()


def test_rejected_approval_maps_to_rejected(tmp_path: Path) -> None:
    sub = make_sub(tmp_path, approval_mode="dangerous")
    try:
        request = write_request("reject-me")
        sub.effector.submit(request)
        sub.tick(1, {})
        pending = sub.effector.poll(request.request_id)
        assert pending.approval_id

        rejected = sub.reject(pending.approval_id, reason="not now")
        assert rejected["approval_status"] == "rejected"
        assert rejected["error"]
        final = sub.effector.poll(request.request_id)
        assert final.status is EffectorStatus.REJECTED
        assert final.approval_id == pending.approval_id
        assert not (tmp_path / "workspace" / "notes" / "a.txt").exists()
    finally:
        sub.teardown()


def test_pending_request_survives_restart_without_duplication(
    tmp_path: Path,
) -> None:
    first = make_sub(tmp_path, approval_mode="dangerous")
    request = write_request("restart-me")
    first.setup({})
    queued = first.effector.submit(request)
    assert queued.goal_id is not None
    first.tick(1, {})
    assert first.effector.poll(request.request_id).status is EffectorStatus.WAITING_APPROVAL
    first.teardown()

    second = make_sub(tmp_path, approval_mode="dangerous")
    second.setup({})
    try:
        restored = second.effector.poll(request.request_id)
        assert restored.status is EffectorStatus.WAITING_APPROVAL
        assert restored.goal_id == queued.goal_id
        assert restored.approval_id

        duplicate = second.effector.submit(request)
        assert duplicate.goal_id == queued.goal_id
        assert len(second.list_goals()) == 1
        assert len(second.list_approvals(status="pending")) == 1
    finally:
        second.teardown()


def test_sandbox_failure_is_reported_as_failed(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)
    try:
        request = write_request("escape", path="../escape.txt")
        sub.effector.submit(request)
        sub.tick(1, {})
        result = sub.effector.poll(request.request_id)
        assert result.status is EffectorStatus.FAILED
        assert result.ok is False
        assert "escape" in (result.error or "").lower()
        assert not (tmp_path / "escape.txt").exists()
    finally:
        sub.teardown()


def test_poll_not_found_and_status_counts(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)
    try:
        missing = sub.effector.poll("does-not-exist")
        assert missing.status is EffectorStatus.NOT_FOUND

        sub.effector.submit(write_request("count-me"))
        status = sub.effector.status()
        assert status["requests"] == 1
        assert status["by_status"]["queued"] == 1
        assert status["runtime_ready"] is True
    finally:
        sub.teardown()


def test_event_sink_failure_does_not_break_execution(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)
    try:
        def broken_sink(name: str, data: dict) -> None:
            raise RuntimeError("sink unavailable")

        sub.effector.event_sink = broken_sink
        request = write_request("event-error")
        result = sub.effector.submit(request)
        assert result.status is EffectorStatus.QUEUED
        assert sub.effector.status()["last_error"]
    finally:
        sub.teardown()
