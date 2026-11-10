"""Врезка TokenLedger в планнер (k16-36) + покрытие врезки (k16-37).

Проверяет снаружи наблюдаемые инварианты: успешный ответ /api/chat с
валидным usage пишет ровно одну запись src="planner"; отсутствие или
невалидность usage — не потеря, а отсутствие данных (ноль записей, без
исключений); леджер резолвится лениво; FallbackPlanner делегирует
OllamaPlanner — одна врезка покрывает оба пути, двойной телеметрии нет.

k16-37 добавляет пины закрытых пробелов: replan-канал (недвойная
телеметрия через repair-путь), запись ДО парсинга плана (токены
потрачены самим ответом), транспорт-отказ primary (ноль записей),
матрица невалидного usage по обоим полям, допустимость нулей и
недостижимость врезки при выключенном LLM (NO_LLM_LIFE).

Без сети: мок-транспорт через requester-injection (техника
test_delamain_llm_planner.py). Леджер — инъецированный фейк; синглтон
и файлы используются только в test_src_label_registered (tmp_path,
канон k16-33) и в пине неактивности (1f) — там data-каталог подменён
на tmp_path и файла журнала быть не должно.
"""

import json
from pathlib import Path
from typing import Any

import src.core.token_ledger as token_ledger_module
from src.core.paths import data_path
from src.core.token_ledger import TOKEN_SOURCES, TokenLedger
from src.delamain.llm_planner import OllamaPlanner
from src.delamain.models import ActionSpec
from src.delamain.planner import FallbackPlanner
from src.delamain.subsystem import DelamainSubsystem

ACTION_SPECS = [
    ActionSpec(
        name="read_file",
        description="Read a UTF-8 file inside the workspace.",
        parameters={"path": "workspace-relative path"},
    ),
]

PLAN_JSON = json.dumps({"plan": [{"action": "read_file", "args": {"path": "a.txt"}}]})

# Текст без единой скобки: _extract_json гарантированно не найдёт JSON,
# поэтому планнер уйдёт в fallback. Используется в 1b.
NOT_JSON = "это не план, а просто текст без скобок"

TASK = "прочитай a.txt"


class FakeLedger:
    """Инъецированный фейк леджера: собирает вызовы record."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, src, in_tokens, out_tokens, cycle=None) -> None:
        self.records.append(
            {
                "src": src,
                "in": in_tokens,
                "out": out_tokens,
                "cycle": cycle,
            }
        )


def _plan_response(**extra: Any) -> dict[str, Any]:
    response: dict[str, Any] = {"message": {"content": PLAN_JSON}}
    response.update(extra)
    return response


def _make_planner(response: dict[str, Any], ledger: Any = None) -> OllamaPlanner:
    def requester(url: str, payload: dict[str, Any], timeout: float) -> dict:
        return response

    return OllamaPlanner(
        model="fake-model",
        requester=requester,
        action_specs=ACTION_SPECS,
        token_ledger=ledger,
    )


def _make_raising_planner(exc: BaseException, ledger: Any = None) -> OllamaPlanner:
    """Планнер с транспортом, который падает до ответа (1c)."""

    def requester(url: str, payload: dict[str, Any], timeout: float) -> dict:
        raise exc

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
    invalid_usages: list[dict[str, Any]] = [
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
    resolutions: list[str] = []
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
    resolutions: list[str] = []
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


# === k16-37: покрытие врезки (1a–1f) ===


def test_replan_channel_single_record() -> None:
    """1a: непустой failure_context → FallbackPlanner зовёт primary.replan
    → РОВНО ОДИН record. Пин недвойной телеметрии через repair-путь:
    replan() и plan() ведут в один _plan, вторая врезка не появляется."""
    ledger = FakeLedger()
    primary = _make_planner(
        _plan_response(prompt_eval_count=100, eval_count=20), ledger=ledger
    )
    planner = FallbackPlanner(primary)

    plan = planner.replan(TASK, {"failed_step": "read_file", "error": "boom"})

    assert len(plan) == 1
    assert planner.status()["last_used"] == "primary"
    # Контекст действительно передавался: путь replan, а не plan.
    assert planner.status()["last_context"] is True
    assert ledger.records == [{"src": "planner", "in": 100, "out": 20, "cycle": None}]


def test_record_precedes_plan_parsing(capsys) -> None:
    """1b: валидный usage + непарсящийся план → ровно 1 запись, задача
    уходит в fallback. Токены потрачены самим ответом, поэтому запись
    не зависит от исхода парсинга; телеметрия при этом не отказала."""
    ledger = FakeLedger()
    response = {
        "message": {"content": NOT_JSON},
        "prompt_eval_count": 9,
        "eval_count": 2,
    }
    primary = _make_planner(response, ledger=ledger)
    planner = FallbackPlanner(primary)

    plan = planner.plan(TASK)

    # План дал fallback (LLM-ответ не распарсился), но токены учтены.
    assert len(plan) >= 1
    assert planner.status()["last_used"] == "fallback"
    assert primary.last_error is not None
    assert ledger.records == [{"src": "planner", "in": 9, "out": 2, "cycle": None}]
    assert primary.last_ledger_error is None
    # Канал учёта не отказал: строки отказа телеметрии в stderr нет
    # (warning FallbackPlanner сюда не относится — проверяем свой префикс).
    assert "token_ledger:" not in capsys.readouterr().err


def test_transport_failure_records_nothing() -> None:
    """1c: транспорт primary падает до ответа → 0 записей (писать нечего:
    usage не существует), задача уходит в fallback, отказ телеметрии не
    подмешивается (last_ledger_error пуст)."""
    ledger = FakeLedger()
    primary = _make_raising_planner(ConnectionRefusedError("ollama is down"), ledger)
    planner = FallbackPlanner(primary)

    plan = planner.plan(TASK)

    assert len(plan) >= 1
    assert planner.status()["last_used"] == "fallback"
    assert ledger.records == []
    assert primary.last_error is not None
    assert "ConnectionRefusedError" in primary.last_error
    # Отказ транспорта — не отказ телеметрии: канал учёта не участвовал.
    assert primary.last_ledger_error is None


def test_invalid_usage_matrix(capsys) -> None:
    """1d: матрица невалидного usage — для КАЖДОГО поля по отдельности
    False/None/"45"/0.0 → None, ноль record. bool отсекается первым
    (пин k16-36 сохраняется), второй поле всегда валидно (45), поэтому
    отказ даёт именно проверяемое поле."""
    invalid_values: list[Any] = [False, None, "45", 0.0]
    for field in ("prompt_eval_count", "eval_count"):
        for value in invalid_values:
            usage: dict[str, Any] = {
                "prompt_eval_count": 45,
                "eval_count": 45,
            }
            usage[field] = value
            ledger = FakeLedger()
            planner = _make_planner(_plan_response(**usage), ledger=ledger)

            plan = planner.plan(TASK)

            assert len(plan) == 1, (field, value)
            assert ledger.records == [], (field, value)
            assert planner.last_ledger_error is None, (field, value)
    assert "token_ledger:" not in capsys.readouterr().err


def test_zero_usage_is_valid() -> None:
    """1e: usage {0, 0} — валиден, ровно 1 record с in=0, out=0.

    Нули — это данные (модель ответила без расхода), а не отсутствие
    данных: ноль не должен схлопываться в None ни по одному полю.
    """
    ledger = FakeLedger()
    planner = _make_planner(
        _plan_response(prompt_eval_count=0, eval_count=0), ledger=ledger
    )

    plan = planner.plan(TASK)

    assert len(plan) == 1
    assert ledger.records == [{"src": "planner", "in": 0, "out": 0, "cycle": None}]


def test_llm_disabled_tap_unreachable(monkeypatch, tmp_path: Path) -> None:
    """1f: NO_LLM_LIFE — при llm_enabled=False _build_planner() → None,
    синглтон леджера не резолвится, файла журнала в data-каталоге нет.

    Каталог данных подменён на tmp_path: иначе пин зависел бы от порядка
    тестов (другие тесты создают сессионный журнал) и от data/ рабочей
    копии.

    Дополнение к формулировке 1f (не сужение): проверяется и llm_enabled=True —
    стек собирается, но врезка всё равно недостижима на этом шаге, потому
    что резолв ленив и происходит только в _plan с валидным usage. Пин
    «спай молчит» держится на обоих флагах, а не только на выключенном.
    """
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(data_dir))

    resolutions: list[str] = []

    def spy_get_token_ledger() -> Any:
        resolutions.append("resolved")
        raise AssertionError("леджер не должен резолвиться вне _plan")

    monkeypatch.setattr(token_ledger_module, "get_token_ledger", spy_get_token_ledger)

    journal = Path(data_path("logs", "token_journal.txt"))

    subsystem = DelamainSubsystem(
        agent_name="tap-coverage",
        workspace=tmp_path / "ws",
        db_path=tmp_path / "memory.sqlite3",
        enabled=False,
        llm_enabled=False,
    )
    assert subsystem._build_planner() is None
    assert subsystem._planner_mode == "heuristic"

    # Включённый флаг собирает стек, но телеметрию не касается:
    # решение о резолве отложено до реального _plan с валидным usage.
    subsystem_llm = DelamainSubsystem(
        agent_name="tap-coverage-llm",
        workspace=tmp_path / "ws2",
        db_path=tmp_path / "memory2.sqlite3",
        enabled=False,
        llm_enabled=True,
    )
    stack = subsystem_llm._build_planner()
    assert stack is not None

    assert resolutions == []
    assert not journal.exists(), f"журнал создан при выключенной врезке: {journal}"


# === k16-39: пин отсутствия двойной записи при replan-отказе после записи ===


def test_replan_failure_after_record_no_second_record() -> None:
    """k16-39: отказ primary в replan ПОСЛЕ успешной записи — без повторной
    записи. Порядок по коду (llm_planner._plan): usage пишется в леджер
    сразу после успешного ответа транспорта и ДО парсинга плана; если
    парсинг падает (битый JSON), PlannerError уходит в FallbackPlanner,
    который уходит на heuristic-replan через planner.py:_call (253–257) —
    fallback леджер не трогает, primary повторно не вызывается. Пин:
    ровно 1 запись, исполнитель fallback, last_ledger_error не испорчен
    отказом primary (запись была успешной, отказ — не телеметрии)."""
    ledger = FakeLedger()
    response = {
        "message": {"content": NOT_JSON},
        "prompt_eval_count": 9,
        "eval_count": 2,
    }
    primary = _make_planner(response, ledger=ledger)
    planner = FallbackPlanner(primary)

    plan = planner.replan(TASK, {"failed_step": "read_file", "error": "boom"})

    assert len(plan) >= 1
    assert planner.status()["last_used"] == "fallback"
    assert ledger.records == [{"src": "planner", "in": 9, "out": 2, "cycle": None}]
    assert primary.last_ledger_error is None
