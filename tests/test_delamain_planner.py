from typing import Any, Dict

import pytest

from src.delamain.models import ActionRequest
from src.delamain.planner import FallbackPlanner, HeuristicPlanner, PlannerError


@pytest.fixture()
def planner() -> HeuristicPlanner:
    return HeuristicPlanner()


def test_list_files(planner: HeuristicPlanner) -> None:
    assert planner.plan("список файлов")[0].action == "list_files"
    plan = planner.plan("список файлов *.py")
    assert plan[0].action == "list_files"
    assert plan[0].args["pattern"] == "*.py"


def test_write_and_read(planner: HeuristicPlanner) -> None:
    plan = planner.plan("запиши в notes/a.txt: привет")
    assert plan[0].action == "write_file"
    assert plan[0].args == {"path": "notes/a.txt", "content": "привет"}

    plan = planner.plan("read notes/a.txt")
    assert plan[0].action == "read_file"
    assert plan[0].args["path"] == "notes/a.txt"


def test_verify(planner: HeuristicPlanner) -> None:
    plan = planner.plan("проверь notes/a.txt на привет")
    assert plan[0].action == "verify_file"
    assert plan[0].args == {"path": "notes/a.txt", "contains": "привет"}


def test_search(planner: HeuristicPlanner) -> None:
    plan = planner.plan("найди TODO в **/*.py")
    assert plan[0].action == "search_files"
    assert plan[0].args == {"query": "TODO", "pattern": "**/*.py"}

    plan = planner.plan("search TODO")
    assert plan[0].args == {"query": "TODO", "pattern": "**/*"}


def test_memory_commands(planner: HeuristicPlanner) -> None:
    plan = planner.plan("запомни язык = Python")
    assert plan[0].action == "remember_fact"
    assert plan[0].args["key"] == "язык"
    assert plan[0].args["value"] == "Python"

    plan = planner.plan("вспомни язык")
    assert plan[0].action == "recall_facts"
    assert plan[0].args["query"] == "язык"


def test_unknown_task_is_rejected(planner: HeuristicPlanner) -> None:
    with pytest.raises(PlannerError):
        planner.plan("сделай что-нибудь невероятное")
    with pytest.raises(PlannerError):
        planner.plan("")


def test_fallback_planner_uses_heuristic_and_combines_errors() -> None:
    class OfflinePlanner:
        def plan(self, task: str):
            raise PlannerError("primary planner is unavailable")

    planner = FallbackPlanner(OfflinePlanner(), HeuristicPlanner())
    plan = planner.plan("запиши в a.txt: ok")
    assert plan[0].action == "write_file"
    assert planner.status()["last_used"] == "fallback"
    assert "unavailable" in (planner.last_error or "")

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
