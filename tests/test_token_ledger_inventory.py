"""Инвентаризация k16-31: контракты на текущее состояние учёта токенов
и журнала обращений к LLM.

Тесты пиннят СНАРУЖИ наблюдаемое состояние до implementation-части
(k16-32+). Где механики нет — пиннится её отсутствие: это преднамеренный
контракт, а не заглушка. Когда k16-32+ добавит механику, соответствующий
тест заменяется на проверку нового поведения явно, а не удаляется молча.
Где механика есть (ActionBudget, FallbackPlanner) — пиннятся ключевые
инварианты: идемпотентность, сходимость сумм, отказ без кэша.

Карта зон и список «не существует» — docs/token_ledger_inventory.md.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core.action_budget import ActionBudget
from src.delamain.llm_planner import OllamaPlanner
from src.delamain.models import ActionSpec
from src.delamain.planner import FallbackPlanner, HeuristicPlanner, PlannerError
from src.delamain.subsystem import DelamainSubsystem

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"

ACTION_SPECS = [
    ActionSpec(
        name="read_file",
        description="Read a UTF-8 file inside the workspace.",
        parameters={"path": "workspace-relative path"},
    ),
]


def _make_planner(requester: Any) -> OllamaPlanner:
    return OllamaPlanner(
        model="fake-model", requester=requester, action_specs=ACTION_SPECS
    )


# === 1. Пины отсутствия (контракт до k16-32+) ===


def test_no_token_ledger_module_yet() -> None:
    """Модуля-счётчика токенов / журнала обращений не существует.

    Ни файла с характерным именем в src/, ни импортируемого модуля.
    Когда k16-32+ введёт механику, этот тест заменяется на проверку
    нового контракта.
    """
    forbidden_stems = (
        "token_ledger",
        "llm_ledger",
        "usage_ledger",
        "call_journal",
        "token_budget",
    )
    hits = [
        path
        for path in SRC_ROOT.rglob("*.py")
        if any(stem in path.stem.lower() for stem in forbidden_stems)
    ]
    assert hits == []

    import importlib.util

    for name in (
        "src.core.token_ledger",
        "src.delamain.token_ledger",
        "src.delamain.call_journal",
    ):
        assert importlib.util.find_spec(name) is None, name


def test_ollama_planner_has_no_token_accounting() -> None:
    """Ответ Ollama несёт usage-поля, но планнер их не читает и не хранит."""
    requester_calls: List[Dict[str, Any]] = []

    def requester(url: str, payload: Dict[str, Any], timeout: float) -> Dict:
        requester_calls.append(payload)
        return {
            "message": {
                "content": json.dumps(
                    {"plan": [{"action": "read_file", "args": {"path": "a.txt"}}]}
                )
            },
            # Реальный ответ Ollama несёт статистику токенов — она
            # сейчас молча отбрасывается.
            "prompt_eval_count": 123,
            "eval_count": 45,
        }

    planner = _make_planner(requester)
    plan = planner.plan("прочитай a.txt")
    assert len(plan) == 1

    status = planner.status()
    accounting_keys = [
        key
        for key in status
        if any(part in key.lower() for part in ("token", "usage", "count", "calls"))
    ]
    assert accounting_keys == []
    assert not hasattr(planner, "token_usage")
    assert not hasattr(planner, "usage")


def test_ollama_planner_keeps_no_call_journal() -> None:
    """Несколько обращений не оставляют истории: виден только последний исход."""
    outcomes = [OSError("connection refused"), None]

    def requester(url: str, payload: Dict[str, Any], timeout: float) -> Dict:
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome
        return {
            "message": {
                "content": json.dumps(
                    {"plan": [{"action": "read_file", "args": {"path": "b.txt"}}]}
                )
            }
        }

    planner = _make_planner(requester)
    with pytest.raises(PlannerError):
        planner.plan("первый вызов")
    assert planner.last_error is not None
    planner.plan("второй вызов")
    # Журнала нет: после второго вызова первый безвозвратно забыт.
    assert planner.last_error is None
    for attr in ("history", "journal", "calls", "ledger", "records"):
        assert not hasattr(planner, attr), attr


def test_fallback_planner_reports_only_last_call_state() -> None:
    """FallbackPlanner: last_used/last_error — состояние последнего вызова,
    кумулятивного счётчика обращений нет."""

    class OfflinePlanner:
        def plan(self, task: str) -> List[Any]:
            raise PlannerError("ollama is offline")

    planner = FallbackPlanner(OfflinePlanner(), HeuristicPlanner())
    planner.plan("запиши в a.txt: ok")
    planner.plan("запиши в b.txt: ok")

    status = planner.status()
    assert set(status) == {
        "type",
        "primary",
        "fallback",
        "last_used",
        "last_context",
        "last_error",
    }
    assert status["last_used"] == "fallback"
    # Два обращения прошли, но ни один счётчик этого не зафиксировал.
    assert not hasattr(planner, "calls")
    assert not hasattr(planner, "call_count")


def test_llm_planner_built_only_when_enabled(tmp_path: Path) -> None:
    """Точка входа LLM-обращений одна: _build_planner, и только при флаге.

    При llm_enabled=False планнер-стек не создаётся (None → heuristic);
    при True — FallbackPlanner(OllamaPlanner, HeuristicPlanner).
    """
    subsystem = DelamainSubsystem(
        agent_name="inventory",
        workspace=tmp_path / "ws",
        db_path=tmp_path / "memory.sqlite3",
        enabled=False,
        llm_enabled=False,
    )
    assert subsystem._build_planner() is None
    assert subsystem._planner_mode == "heuristic"

    subsystem_llm = DelamainSubsystem(
        agent_name="inventory",
        workspace=tmp_path / "ws2",
        db_path=tmp_path / "memory2.sqlite3",
        enabled=False,
        llm_enabled=True,
    )
    stack = subsystem_llm._build_planner()
    assert isinstance(stack, FallbackPlanner)
    assert isinstance(stack.primary, OllamaPlanner)
    assert isinstance(stack.fallback, HeuristicPlanner)


# === 2. Пины существующих инвариантов (ActionBudget) ===


def _budget(energy: List[float], **kwargs: Any) -> ActionBudget:
    return ActionBudget(
        lambda: energy[0],
        lambda value: energy.__setitem__(0, value),
        enabled=True,
        **kwargs,
    )


def test_action_budget_charge_idempotent_by_action_id() -> None:
    """Повторный charge с тем же action_id не списывает энергию дважды."""
    energy = [100.0]
    budget = _budget(energy)

    first = budget.charge("web_search", 10.0, action_id="a1")
    second = budget.charge("web_search", 10.0, action_id="a1")

    assert first.allowed and not first.duplicate
    assert second.allowed and second.duplicate
    assert energy[0] == 90.0
    status = budget.status()
    assert status["allowed"] == 1
    assert status["spent"] == 10.0


def test_action_budget_spent_matches_energy_and_status_is_pure() -> None:
    """Сумма списаний сходится с энергией; refund её уменьшает; status()
    не имеет побочных эффектов."""
    energy = [100.0]
    budget = _budget(energy)

    budget.charge("web_search", 10.0, action_id="x")
    budget.charge("explore", 5.0, action_id="y")
    assert energy[0] == 85.0
    assert budget.status()["spent"] == 15.0

    budget.refund(6.0, source="test")
    assert energy[0] == 91.0
    assert budget.status()["spent"] == 9.0

    before = dict(budget.status())
    snapshot_energy = energy[0]
    budget.status()
    budget.status()
    assert budget.status() == before
    assert energy[0] == snapshot_energy


def test_action_budget_denial_is_not_cached() -> None:
    """Отказ не кэшируется: после восстановления энергии та же попытка
    получает новое решение, а не старый отказ."""
    energy = [6.0]
    budget = _budget(energy, min_reserve=5.0)

    denied = budget.charge("web_search", 4.0, action_id="z")
    assert not denied.allowed
    assert denied.reason == "insufficient_energy"

    energy[0] = 100.0
    retry = budget.charge("web_search", 4.0, action_id="z")
    assert retry.allowed and not retry.duplicate

    status = budget.status()
    assert status["denied"] == 1
    assert status["allowed"] == 1


def test_call_counters_exist_only_in_evaluation_harness() -> None:
    """Счётчики вызовов планнера существуют только в eval-харнессе.

    ScriptedPlanner (src/delamain/evaluation.py) считает plan_calls и
    replan_calls; продовые планнеры — нет. Это зафиксированная зона
    дублирования: прод-учёт обращений предстоит создать в k16-32+.
    """
    from src.delamain.evaluation import ScriptedPlanner

    scripted = ScriptedPlanner({})
    assert scripted.plan_calls == 0
    assert scripted.replan_calls == 0

    production_planners: List[Any] = [
        _make_planner(lambda url, payload, timeout: {}),
        FallbackPlanner(HeuristicPlanner(), HeuristicPlanner()),
        HeuristicPlanner(),
    ]
    for planner in production_planners:
        assert not hasattr(planner, "plan_calls"), type(planner).__name__
        assert not hasattr(planner, "replan_calls"), type(planner).__name__
