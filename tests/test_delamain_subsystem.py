from pathlib import Path

import pytest

from src.delamain.models import ActionRequest
from src.delamain.subsystem import DelamainSubsystem


def make_sub(tmp_path: Path, **kwargs) -> DelamainSubsystem:
    params = {
        "agent_name": "DelamainTest",
        "workspace": tmp_path / "workspace",
        "db_path": tmp_path / "memory.sqlite3",
        "enabled": True,
        "tick_interval": 1,
    }
    params.update(kwargs)
    return DelamainSubsystem(**params)


def test_subsystem_is_disabled_and_lazy_by_default(tmp_path: Path) -> None:
    sub = DelamainSubsystem(
        workspace=tmp_path / "workspace",
        db_path=tmp_path / "memory.sqlite3",
        enabled=False,
    )

    assert sub.enabled is False
    assert sub.runtime is None
    assert sub.tick(1, {}) is None
    assert sub.runtime is None
    assert sub.status()["runtime_ready"] is False


def test_enable_creates_runtime_and_disable_stops_ticks(tmp_path: Path) -> None:
    sub = make_sub(tmp_path, enabled=False)

    assert sub.enable()["enabled"] is True
    assert sub.runtime is not None
    assert sub.status()["runtime_ready"] is True

    assert sub.disable()["enabled"] is False
    assert sub.enabled is False
    # Disabling does not destroy the open SQLite connection; teardown does.
    assert sub.runtime is not None
    assert sub.tick(2, {}) is None


def test_queue_goal_runs_on_tick_and_records_skill(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)
    sub.setup({})

    goal = sub.queue_goal("write note", "запиши в notes/a.txt: привет")
    assert goal["status"] == "pending"
    assert (tmp_path / "workspace" / "notes" / "a.txt").exists() is False

    event = sub.tick(1, {})
    assert event is not None
    data = event["events"][0]["data"]
    assert data["ok"] is True
    assert data["goal_id"] == goal["id"]
    assert data["steps"] == 1
    assert (tmp_path / "workspace" / "notes" / "a.txt").read_text(
        encoding="utf-8"
    ) == "привет"

    goals = sub.list_goals()
    assert goals[0]["status"] == "done"
    skill = sub.runtime.memory.get_skill("write note")
    assert skill is not None
    assert skill["success_count"] == 1
    assert skill["failure_count"] == 0


def test_tick_respects_interval(tmp_path: Path) -> None:
    sub = make_sub(tmp_path, tick_interval=3)
    sub.queue_goal("write", "запиши в a.txt: x")

    assert sub.tick(1, {}) is None
    assert sub.tick(2, {}) is None
    assert sub.tick(3, {}) is not None
    assert (tmp_path / "workspace" / "a.txt").read_text(encoding="utf-8") == "x"


def test_failed_goal_marks_goal_failed_and_records_failure(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)
    goal = sub.queue_goal("read missing", "прочитай missing.txt")

    event = sub.tick(1, {})
    data = event["events"][0]["data"]
    assert data["ok"] is False
    assert data["goal_id"] == goal["id"]
    assert "file not found" in (data["error"] or "")

    goals = sub.list_goals()
    assert goals[0]["status"] == "failed"
    skill = sub.runtime.memory.get_skill("read missing")
    assert skill["success_count"] == 0
    assert skill["failure_count"] == 1


def test_explicit_plan_goal_runs_without_planner(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)
    goal = sub.queue_goal(
        "write planned",
        plan=[
            {"action": "write_file", "args": {"path": "planned.txt", "content": "ok"}},
            {"action": "verify_file", "args": {"path": "planned.txt", "contains": "ok"}},
        ],
    )

    data = sub.tick(1, {})["events"][0]["data"]
    assert data["ok"] is True
    assert data["goal_id"] == goal["id"]
    assert data["steps"] == 2
    assert (tmp_path / "workspace" / "planned.txt").read_text(encoding="utf-8") == "ok"


def test_action_request_plan_is_stored_as_json(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)
    goal = sub.queue_goal(
        "write typed plan",
        plan=[ActionRequest("write_file", {"path": "typed.txt", "content": "ok"})],
    )

    stored = sub.list_goals()[0]
    assert stored["metadata"]["plan"] == [
        {"action": "write_file", "args": {"path": "typed.txt", "content": "ok"}}
    ]
    data = sub.tick(1, {})["events"][0]["data"]
    assert data["ok"] is True
    assert data["goal_id"] == goal["id"]
    assert (tmp_path / "workspace" / "typed.txt").read_text(encoding="utf-8") == "ok"


def test_run_now_and_status_summary(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)

    result = sub.run_now("запиши в direct.txt: hello")
    assert result["ok"] is True
    assert (tmp_path / "workspace" / "direct.txt").read_text(encoding="utf-8") == "hello"

    status = sub.status()
    assert status["runtime_ready"] is True
    assert status["last_result"]["task_id"] == result["task_id"]
    assert status["last_result"]["ok"] is True
    assert status["goals"] == {"pending": 0, "done": 0, "failed": 0}


def test_queue_goal_requires_executable_payload(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)

    with pytest.raises(ValueError):
        sub.queue_goal("empty goal")


def test_teardown_closes_runtime(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)
    sub.queue_goal("write", "запиши в a.txt: x")
    assert sub.runtime is not None

    sub.teardown()

    assert sub.runtime is None
    assert sub.status()["runtime_ready"] is False


def test_agent_runner_delamain_commands(tmp_path: Path) -> None:
    import asyncio

    from src.core.agent_runner import AgentRunner
    from src.core.event_bus import EventBus

    class FakeAgent:
        name = "FakeDelamainAgent"

        def __init__(self, delamain: DelamainSubsystem) -> None:
            self.energy = 100.0
            self.cycle_count = 0
            self.delamain = delamain

    sub = make_sub(tmp_path)
    runner = AgentRunner(
        FakeAgent(sub),
        EventBus(),
        watchdog=object(),
    )

    async def scenario() -> None:
        on = await runner.handle_command("/delamain on")
        assert "включён" in on
        status = await runner.handle_command("/delamain status")
        assert "Delamain-local" in status
        assert "Runtime: готов" in status

        result = await runner.handle_command("/delamain run запиши в cmd.txt: привет")
        assert "✅" in result
        assert (tmp_path / "workspace" / "cmd.txt").read_text(encoding="utf-8") == "привет"

        queued = await runner.handle_command("/delamain goal Note | запиши в goal.txt: ok")
        assert "поставлена в очередь" in queued
        goals = await runner.handle_command("/delamain goals")
        assert "Note" in goals

        off = await runner.handle_command("/delamain off")
        assert "выключен" in off

    asyncio.run(scenario())


def test_digital_being_registers_delamain_disabled(tmp_path: Path, monkeypatch) -> None:
    from src.core.agent import DigitalBeing
    from src.core.subsystem_base import PluginRegistry

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DELAMAIN_ENABLED", raising=False)
    monkeypatch.delenv("DELAMAIN_LOCAL_ENABLED", raising=False)
    PluginRegistry.reset_global()
    agent = None
    try:
        agent = DigitalBeing("DelamainIntegration")
        assert agent.delamain is not None
        assert agent.delamain.enabled is False
        assert agent.delamain.runtime is None
        assert agent.plugin_registry.get("delamain") is agent.delamain
    finally:
        if agent is not None:
            agent.plugin_registry.teardown_all()
        PluginRegistry.reset_global()
