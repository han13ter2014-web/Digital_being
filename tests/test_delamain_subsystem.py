from pathlib import Path

import pytest

from src.delamain.models import ActionRequest
from src.delamain.planner import PlannerError
from src.delamain.subsystem import DelamainSubsystem


class FailingPlanner:
    def plan(self, task: str):
        raise PlannerError(f"planner must not be called for {task!r}")


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
    assert data["attempts"] == 1
    assert data["retry_scheduled"] is False
    assert "file not found" in (data["error"] or "")

    goals = sub.list_goals()
    assert goals[0]["status"] == "failed"
    assert goals[0]["metadata"]["attempts"] == 1
    skill = sub.runtime.memory.get_skill("read missing")
    assert skill["success_count"] == 0
    assert skill["failure_count"] == 1


def test_goal_retries_until_success(tmp_path: Path) -> None:
    sub = make_sub(tmp_path, max_attempts=2)
    goal = sub.queue_goal("read later", "прочитай later.txt")

    first = sub.tick(1, {})["events"][0]["data"]
    assert first["ok"] is False
    assert first["attempts"] == 1
    assert first["retry_scheduled"] is True
    assert first["task_id"] == f"goal-{goal['id']}"
    assert sub.list_goals()[0]["status"] == "pending"

    (tmp_path / "workspace" / "later.txt").write_text("ready", encoding="utf-8")
    second = sub.tick(2, {})["events"][0]["data"]
    assert second["ok"] is True
    assert second["goal_id"] == goal["id"]
    assert second["attempts"] == 2
    assert second["retry_scheduled"] is False
    assert second["task_id"] == f"goal-{goal['id']}-attempt-2"

    stored = sub.list_goals()[0]
    assert stored["status"] == "done"
    assert stored["metadata"]["attempts"] == 2
    skill = sub.runtime.memory.get_skill("read later")
    assert skill["success_count"] == 1
    assert skill["failure_count"] == 1

    # A success after a retry is still reusable. If this plan were not
    # reused, the failing planner would make the next goal fail.
    sub.runtime.planner = FailingPlanner()
    sub.queue_goal("read later", "прочитай later.txt")
    third = sub.tick(3, {})["events"][0]["data"]
    assert third["ok"] is True
    assert third["reused_skill"] is True


def test_goal_stops_after_max_attempts(tmp_path: Path) -> None:
    sub = make_sub(tmp_path, max_attempts=2)
    sub.queue_goal("always missing", "прочитай missing.txt")

    first = sub.tick(1, {})["events"][0]["data"]
    assert first["ok"] is False
    assert first["retry_scheduled"] is True

    second = sub.tick(2, {})["events"][0]["data"]
    assert second["ok"] is False
    assert second["attempts"] == 2
    assert second["retry_scheduled"] is False

    stored = sub.list_goals()[0]
    assert stored["status"] == "failed"
    assert stored["metadata"]["attempts"] == 2
    skill = sub.runtime.memory.get_skill("always missing")
    assert skill["success_count"] == 0
    assert skill["failure_count"] == 2


def test_successful_skill_is_reused_only_for_same_command(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)
    command = "запиши в reused.txt: one"
    sub.queue_goal("repeat write", command)
    first = sub.tick(1, {})["events"][0]["data"]
    assert first["ok"] is True

    # If the skill is not reused, the failing planner makes the goal fail.
    sub.runtime.planner = FailingPlanner()
    (tmp_path / "workspace" / "reused.txt").unlink()

    sub.queue_goal("repeat write", command)
    second = sub.tick(2, {})["events"][0]["data"]
    assert second["ok"] is True
    assert second["reused_skill"] is True
    assert (tmp_path / "workspace" / "reused.txt").read_text(
        encoding="utf-8"
    ) == "one"
    skill = sub.runtime.memory.get_skill("repeat write")
    assert skill["success_count"] == 2

    sub.queue_goal("repeat write", "запиши в other.txt: two")
    third = sub.tick(3, {})["events"][0]["data"]
    assert third["ok"] is False
    assert third["reused_skill"] is False
    assert "planner must not be called" in (third["error"] or "")
    assert not (tmp_path / "workspace" / "other.txt").exists()


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


def test_planner_is_heuristic_by_default(tmp_path: Path) -> None:
    sub = make_sub(tmp_path)
    sub.enable()

    info = sub.status()["planner"]
    assert info["enabled"] is False
    assert info["mode"] == "heuristic"
    assert sub.runtime.planner.__class__.__name__ == "HeuristicPlanner"
    sub.teardown()


def test_llm_planner_status_does_not_require_network(tmp_path: Path) -> None:
    sub = make_sub(tmp_path, llm_enabled=True, llm_model="fake-model")
    sub.enable()

    info = sub.status()["planner"]
    assert info["enabled"] is True
    assert info["mode"] == "ollama:fake-model+fallback"
    assert info["model"] == "fake-model"
    assert info["base_url"] == "http://127.0.0.1:11434"
    assert info["last_used"] == "none"
    assert info["last_error"] is None
    assert sub.runtime.planner.__class__.__name__ == "FallbackPlanner"
    sub.teardown()


def test_invalid_llm_config_falls_back_to_heuristic(tmp_path: Path) -> None:
    sub = make_sub(tmp_path, llm_enabled=True, llm_model="   ")
    sub.enable()

    info = sub.status()["planner"]
    assert info["mode"] == "heuristic (LLM setup failed)"
    assert "model" in (info["error"] or "").lower()
    assert sub.runtime.planner.__class__.__name__ == "HeuristicPlanner"
    sub.teardown()


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
        assert "Планировщик: heuristic" in status

        result = await runner.handle_command("/delamain run запиши в cmd.txt: привет")
        assert "✅" in result
        assert (tmp_path / "workspace" / "cmd.txt").read_text(encoding="utf-8") == "привет"

        queued = await runner.handle_command("/delamain goal Note | запиши в goal.txt: ok")
        assert "поставлена в очередь" in queued
        assert sub.tick(1, {}) is not None
        goals = await runner.handle_command("/delamain goals")
        assert "Note" in goals
        assert "attempts=1" in goals

        skills = await runner.handle_command("/delamain skills")
        assert "Note" in skills
        assert "1✓/0✗" in skills

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
