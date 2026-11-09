"""Врезка TokenLedger в планнер (k16-36): телеметрия токенов.

Проверяет снаружи наблюдаемые инварианты: успешный ответ /api/chat с
валидным usage пишет ровно одну запись src="planner"; отсутствие или
невалидность usage — не потеря, а отсутствие данных (ноль записей, без
исключений); леджер резолвится лениво; FallbackPlanner делегирует
OllamaPlanner — одна врезка покрывает оба пути, двойной телеметрии нет.

Без сети: мок-транспорт через requester-injection (техника
test_delamain_llm_planner.py). Леджер — инъецированный фейк; синглтон
и файлы используются только в test_src_label_registered (tmp_path,
канон k16-33).
"""

import json
from typing import Any, Dict, List

import src.core.token_ledger as token_ledger_module
from src.core.token_ledger import TOKEN_SOURCES, TokenLedger
from src.delamain.llm_planner import OllamaPlanner
from src.delamain.models import ActionSpec
from src.delamain.planner import FallbackPlanner

ACTION_SPECS = [
    ActionSpec(
        name="read_file",
        description="Read a UTF-8 file inside the workspace.",
        parameters={"path": "workspace-relative path"},
    ),
]

PLAN_JSON = json.dumps({"plan": [{"action": "read_file", "args": {"path": "a.txt"}}]})


class FakeLedger:
    """Инъецированный фейк леджера: собирает вызовы record."""

    def __init__(self) -> None:
        self.records: List[Dict[str, Any]] = []

    def record(self, src, in_tokens, out_tokens, cycle=None) -> None:
        self.records.append(
            {
                "src": src,
                "in": in_tokens,
                "out": out_tokens,
                "cycle": cycle,
            }
        )


def _plan_response(**extra: Any) -> Dict[str, Any]:
    response: Dict[str, Any] = {"message": {"content": PLAN_JSON}}
    response.update(extra)
    return response


def _make_planner(response: Dict[str, Any], ledger: Any = None) -> OllamaPlanner:
    def requester(url: str, payload: Dict[str, Any], timeout: float) -> Dict:
        return response

    return OllamaPlanner(
        model="fake-model",
        requester=requester,
        action_specs=ACTION_SPECS,
        token_ledger=ledger,
    )


def test_plan_records_usage() -> None:
    """Ответ с валидным usage → ровно один record с точными числами."""
    ledger = FakeLedger()
    planner = _make_planner(
        _plan_response(prompt_eval_count=123, eval_count=45), ledger=ledger
    )
    plan = planner.plan("прочитай a.txt")

    assert len(plan) == 1
    assert ledger.records == [{"src": "planner", "in": 123, "out": 45, "cycle": None}]


def test_plan_without_usage_records_nothing() -> None:
    """Ответ без usage → ноль record, планнер вернул обычный результат."""
    ledger = FakeLedger()
    planner = _make_planner(_plan_response(), ledger=ledger)
    plan = planner.plan("прочитай a.txt")

    assert len(plan) == 1
    assert ledger.records == []


def test_invalid_usage_ignored() -> None:
    """Строки/bool/отрицательные в usage → None: ноль record, без
    исключений, план возвращается штатно."""
    invalid_usages: List[Dict[str, Any]] = [
        {"prompt_eval_count": "123", "eval_count": 45},
        {"prompt_eval_count": 123, "eval_count": True},
        {"prompt_eval_count": True, "eval_count": 45},
        {"prompt_eval_count": -5, "eval_count": 45},
        {"prompt_eval_count": 123, "eval_count": -1},
    ]
    for usage in invalid_usages:
        ledger = FakeLedger()
        planner = _make_planner(_plan_response(**usage), ledger=ledger)
        plan = planner.plan("прочитай a.txt")
        assert len(plan) == 1
        assert ledger.records == [], usage


def test_src_label_registered(tmp_path) -> None:
    """ "planner" — в закрытом наборе TOKEN_SOURCES; реальный TokenLedger
    пишет строку с src=planner (канон k16-33, tmp_path)."""
    assert "planner" in TOKEN_SOURCES

    log_file = tmp_path / "logs" / "token_journal.txt"
    ledger = TokenLedger(log_file=str(log_file), buffer_size=1)
    ledger.record("planner", 3, 5, cycle=None)
    ledger.journal.flush()

    text = log_file.read_text(encoding="utf-8")
    assert "src=planner" in text
    assert "in=3 out=5" in text


def test_ledger_lazy_resolution(monkeypatch) -> None:
    """Леджер не резолвится ни при конструировании, ни при вызове без
    usage — только в момент реального _plan с валидным usage."""
    resolutions: List[str] = []
    fake = FakeLedger()

    def spy_get_token_ledger() -> FakeLedger:
        resolutions.append("resolved")
        return fake

    monkeypatch.setattr(token_ledger_module, "get_token_ledger", spy_get_token_ledger)

    # Конструирование — без касаний синглтона.
    planner = _make_planner(
        _plan_response(prompt_eval_count=10, eval_count=4), ledger=None
    )
    assert resolutions == []

    # Вызов без usage — тоже без резолва: писать нечего.
    planner_no_usage = _make_planner(_plan_response(), ledger=None)
    planner_no_usage.plan("прочитай a.txt")
    assert resolutions == []

    # Первый реальный вызов с usage — ровно один резолв.
    planner.plan("прочитай a.txt")
    assert resolutions == ["resolved"]
    assert fake.records == [{"src": "planner", "in": 10, "out": 4, "cycle": None}]


def test_cli_delegation_single_record() -> None:
    """FallbackPlanner делегирует OllamaPlanner: одна врезка — один
    record, двойной телеметрии нет (путь CLI __main__.py:114–123)."""
    ledger = FakeLedger()
    primary = _make_planner(
        _plan_response(prompt_eval_count=100, eval_count=20), ledger=ledger
    )
    planner = FallbackPlanner(primary)
    plan = planner.plan("прочитай a.txt")

    assert len(plan) == 1
    assert planner.status()["last_used"] == "primary"
    assert len(ledger.records) == 1
    assert ledger.records[0] == {
        "src": "planner",
        "in": 100,
        "out": 20,
        "cycle": None,
    }


class _BrokenLedger:
    """Леджер, чей record бросает OSError (проба Дипсика, k16-36)."""

    def record(self, *args: Any, **kwargs: Any) -> None:
        raise OSError("disk on fire")


def test_ledger_record_failure_is_observable_and_passive(capsys) -> None:
    """record бросает OSError → план возвращён PRIMARY (исполнитель не
    сменился), отказ наблюдаем: last_ledger_error + одна строка stderr."""
    primary = _make_planner(
        _plan_response(prompt_eval_count=100, eval_count=20),
        ledger=_BrokenLedger(),
    )
    planner = FallbackPlanner(primary)
    plan = planner.plan("прочитай a.txt")

    assert len(plan) == 1
    assert planner.status()["last_used"] == "primary"
    assert primary.last_ledger_error is not None
    assert "OSError" in primary.last_ledger_error
    assert "disk on fire" in primary.last_ledger_error
    err_lines = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    assert len(err_lines) == 1
    assert err_lines[0].startswith("token_ledger: OSError")


def test_ledger_construction_failure_then_recovers(monkeypatch, capsys) -> None:
    """Конструирование леджера падает → план возвращён, ошибка наблюдаема;
    повторный plan() с рабочим леджером → запись появляется (упавшее
    конструирование не кэшируется, резолв повторяется)."""
    resolutions: List[str] = []
    working = FakeLedger()

    def flaky_get_token_ledger() -> Any:
        resolutions.append("called")
        if len(resolutions) == 1:
            raise OSError("makedirs denied")
        return working

    monkeypatch.setattr(token_ledger_module, "get_token_ledger", flaky_get_token_ledger)
    planner = _make_planner(
        _plan_response(prompt_eval_count=7, eval_count=3), ledger=None
    )

    # Первый вызов: конструирование падает — план всё равно возвращается.
    plan = planner.plan("прочитай a.txt")
    assert len(plan) == 1
    assert planner.last_ledger_error is not None
    assert "OSError" in planner.last_ledger_error
    assert working.records == []
    err_lines = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    assert len(err_lines) == 1
    assert err_lines[0].startswith("token_ledger: OSError")

    # Повторный вызов: резолв пошёл заново, запись появилась.
    plan = planner.plan("прочитай a.txt")
    assert len(plan) == 1
    assert resolutions == ["called", "called"]
    assert working.records == [{"src": "planner", "in": 7, "out": 3, "cycle": None}]


def test_happy_path_leaves_last_ledger_error_none(capsys) -> None:
    """Happy-path: last_ledger_error остаётся None — до первого вызова
    и после успешной записи; stderr пуст."""
    ledger = FakeLedger()
    planner = _make_planner(
        _plan_response(prompt_eval_count=10, eval_count=4), ledger=ledger
    )
    assert planner.last_ledger_error is None

    plan = planner.plan("прочитай a.txt")
    assert len(plan) == 1
    assert len(ledger.records) == 1
    assert planner.last_ledger_error is None
    assert capsys.readouterr().err == ""
