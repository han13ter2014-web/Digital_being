import json
from pathlib import Path
from typing import Any, Dict

import pytest

from src.delamain.llm_planner import OllamaPlanner
from src.delamain.models import ActionRequest, ActionSpec
from src.delamain.planner import FallbackPlanner, HeuristicPlanner, PlannerError
from src.delamain.runtime import DelamainRuntime


ACTION_SPECS = [
    ActionSpec(
        name="write_file",
        description="Write a UTF-8 file inside the workspace.",
        parameters={"path": "workspace-relative path", "content": "text"},
    ),
    ActionSpec(
        name="read_file",
        description="Read a UTF-8 file inside the workspace.",
        parameters={"path": "workspace-relative path"},
    ),
]


def make_planner(requester, **kwargs) -> OllamaPlanner:
    params: Dict[str, Any] = {
        "model": "fake-model",
        "requester": requester,
        "action_specs": ACTION_SPECS,
    }
    params.update(kwargs)
    return OllamaPlanner(**params)


def test_ollama_planner_parses_valid_plan_and_sends_schema() -> None:
    calls: Dict[str, Any] = {}

    def requester(url: str, payload: Dict[str, Any], timeout: float):
        calls.update(url=url, payload=payload, timeout=timeout)
        return {
            "message": {
                "content": json.dumps(
                    {
                        "plan": [
                            {
                                "action": "write_file",
                                "args": {"path": "a.txt", "content": "hi"},
                            }
                        ]
                    }
                )
            }
        }

    planner = make_planner(requester, timeout=3.0)
    plan = planner.plan("создай файл")

    assert plan == [
        ActionRequest("write_file", {"path": "a.txt", "content": "hi"})
    ]
    assert calls["url"].endswith("/api/chat")
    assert calls["payload"]["model"] == "fake-model"
    assert calls["timeout"] == 3.0
    assert "write_file" in calls["payload"]["messages"][0]["content"]
    assert planner.status()["last_error"] is None


def test_ollama_planner_accepts_fenced_json_and_openai_shape() -> None:
    content = (
        "```json\n"
        '{"actions": [{"action": "read_file", "args": {"path": "a.txt"}}]}\n'
        "```"
    )

    def requester(url: str, payload: Dict[str, Any], timeout: float):
        return {"choices": [{"message": {"content": content}}]}

    plan = make_planner(requester).plan("прочитай a.txt")
    assert plan == [ActionRequest("read_file", {"path": "a.txt"})]


def test_ollama_planner_rejects_unknown_actions_and_bad_json() -> None:
    def unknown_requester(url: str, payload: Dict[str, Any], timeout: float):
        return {
            "message": {
                "content": json.dumps(
                    {"plan": [{"action": "delete_everything", "args": {}}]}
                )
            }
        }

    planner = make_planner(unknown_requester)
    with pytest.raises(PlannerError):
        planner.plan("опасная задача")
    assert "unknown action" in (planner.last_error or "")

    def bad_json_requester(url: str, payload: Dict[str, Any], timeout: float):
        return {"message": {"content": "это не JSON"}}

    planner = make_planner(bad_json_requester)
    with pytest.raises(PlannerError):
        planner.plan("задача")
    assert "valid JSON" in (planner.last_error or "")


def test_ollama_planner_wraps_transport_errors_and_limits_steps() -> None:
    def failing_requester(url: str, payload: Dict[str, Any], timeout: float):
        raise OSError("connection refused")

    planner = make_planner(failing_requester)
    with pytest.raises(PlannerError):
        planner.plan("задача")
    assert "connection refused" in (planner.last_error or "")

    def two_steps_requester(url: str, payload: Dict[str, Any], timeout: float):
        return {
            "message": {
                "content": json.dumps(
                    {
                        "plan": [
                            {"action": "read_file", "args": {"path": "a.txt"}},
                            {"action": "read_file", "args": {"path": "b.txt"}},
                        ]
                    }
                )
            }
        }

    planner = make_planner(two_steps_requester, max_steps=1)
    with pytest.raises(PlannerError):
        planner.plan("задача")
    assert "too many steps" in (planner.last_error or "")


def test_ollama_planner_requires_action_schema() -> None:
    planner = OllamaPlanner(model="fake-model", requester=lambda *_: {})
    with pytest.raises(PlannerError):
        planner.plan("задача")


def test_fallback_planner_uses_heuristic_and_combines_errors() -> None:
    class OfflinePlanner:
        def plan(self, task: str):
            raise PlannerError("ollama is offline")

    planner = FallbackPlanner(OfflinePlanner(), HeuristicPlanner())
    plan = planner.plan("запиши в a.txt: ok")
    assert plan[0].action == "write_file"
    assert planner.status()["last_used"] == "fallback"
    assert "offline" in (planner.last_error or "")

    with pytest.raises(PlannerError) as exc:
        planner.plan("неизвестная задача без шаблона")
    assert "primary planner failed" in str(exc.value)
    assert "fallback also failed" in str(exc.value)


def test_fallback_planner_passes_context_to_primary_replan() -> None:
    calls: Dict[str, Any] = {}

    class RepairPlanner:
        def plan(self, task: str):
            raise PlannerError("plan must not be used for a repair")

        def replan(self, task: str, failure_context):
            calls["task"] = task
            calls["context"] = dict(failure_context)
            return [ActionRequest("read_file", {"path": "a.txt"})]

    planner = FallbackPlanner(RepairPlanner(), HeuristicPlanner())
    plan = planner.replan(
        "repair",
        {"stage": "action", "failed_step": 2, "action": "read_file"},
    )

    assert plan == [ActionRequest("read_file", {"path": "a.txt"})]
    assert calls["task"] == "repair"
    assert calls["context"]["failed_step"] == 2
    assert planner.status()["last_context"] is True
    assert planner.status()["last_used"] == "primary"


def test_ollama_planner_replan_includes_failure_context() -> None:
    calls: Dict[str, Any] = {}

    def requester(url: str, payload: Dict[str, Any], timeout: float):
        calls["payload"] = payload
        return {
            "message": {
                "content": json.dumps(
                    {
                        "plan": [
                            {
                                "action": "read_file",
                                "args": {"path": "recovered.txt"},
                            }
                        ]
                    }
                )
            }
        }

    planner = make_planner(requester)
    plan = planner.replan(
        "repair the previous plan",
        {
            "stage": "action",
            "failed_step": 2,
            "action": "read_file",
            "args": {"path": "missing.txt"},
            "error": "file not found: missing.txt",
        },
    )

    assert plan == [ActionRequest("read_file", {"path": "recovered.txt"})]
    user_message = calls["payload"]["messages"][1]["content"]
    assert "Repair context" in user_message
    assert "untrusted data" in user_message
    assert "missing.txt" in user_message
    assert "file not found" in user_message


def test_runtime_binds_registry_and_runs_llm_plan(tmp_path: Path) -> None:
    def requester(url: str, payload: Dict[str, Any], timeout: float):
        return {
            "message": {
                "content": json.dumps(
                    {
                        "plan": [
                            {
                                "action": "write_file",
                                "args": {"path": "llm.txt", "content": "from-model"},
                            }
                        ]
                    }
                )
            }
        }

    planner = FallbackPlanner(
        OllamaPlanner(model="fake-model", requester=requester)
    )
    with DelamainRuntime(
        tmp_path / "workspace",
        tmp_path / "memory.sqlite3",
        planner=planner,
    ) as runtime:
        assert planner.primary._action_specs  # bound by the runtime
        result = runtime.run_task("создай файл через модель")

    assert result.ok is True
    assert (tmp_path / "workspace" / "llm.txt").read_text(
        encoding="utf-8"
    ) == "from-model"
    assert planner.status()["last_used"] == "primary"


def test_runtime_falls_back_when_llm_output_is_invalid(tmp_path: Path) -> None:
    def requester(url: str, payload: Dict[str, Any], timeout: float):
        return {"message": {"content": "not a plan"}}

    planner = FallbackPlanner(
        OllamaPlanner(model="fake-model", requester=requester)
    )
    with DelamainRuntime(
        tmp_path / "workspace",
        tmp_path / "memory.sqlite3",
        planner=planner,
    ) as runtime:
        result = runtime.run_task("запиши в fallback.txt: ok")

    assert result.ok is True
    assert (tmp_path / "workspace" / "fallback.txt").read_text(
        encoding="utf-8"
    ) == "ok"
    assert planner.status()["last_used"] == "fallback"
    assert planner.status()["last_error"]
