import pytest

from src.delamain.planner import HeuristicPlanner, PlannerError


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
