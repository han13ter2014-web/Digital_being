"""
test_metrics_endpoint.py — тесты для /metrics endpoint (Prometheus exposition).

Покрывает:
- Endpoint зарегистрирован в роутере (не 404).
- Возвращает 200 с Content-Type: text/plain.
- Содержит HELP/TYPE комментарии (стандарт Prometheus).
- Всегда присутствуют базовые gauge'ы: energy, intelligence, cycle_count, completed_goals,
  success_streak, concepts_total, subsystem_count, uptime_seconds.
- Значения обновляются после update_status.
- Работает без агента (standalone-режим).
- Опциональные метрики: goal_progress_percent (если передан), will_acts_total.
- Корректно обрабатывает snapshot без goals/will (не падает).
"""
import os
import re
import socket
import sys
import time

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

aiohttp = pytest.importorskip("aiohttp", reason="aiohttp не установлен")
from aiohttp import ClientSession  # noqa: E402

from src.ui.web_dashboard import (  # noqa: E402
    WebDashboard, SharedState, AIOHTTP_AVAILABLE,
)


def _free_port() -> int:
    """Возвращает свободный TCP-порт."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def dash():
    """Запускает WebDashboard в отдельном потоке на свободном порту."""
    if not AIOHTTP_AVAILABLE:
        pytest.skip("aiohttp не установлен")
    port = _free_port()
    d = WebDashboard(agent=None, host="127.0.0.1", port=port)
    d.start(in_thread=True)
    # Даём серверу время подняться
    time.sleep(0.5)
    yield d, port
    try:
        d.stop()
    except Exception:
        pass


async def _get_text(url, timeout=2.0):
    """GET-запрос с text-ответом."""
    async with ClientSession() as sess:
        async with sess.get(url, timeout=timeout) as resp:
            return resp.status, resp.headers, await resp.text()


# ============================================================
# Базовая доступность
# ============================================================
@pytest.mark.asyncio
async def test_metrics_route_registered(dash):
    """/metrics зарегистрирован в роутере (не 404)."""
    _, port = dash
    async with ClientSession() as sess:
        async with sess.get(f"http://127.0.0.1:{port}/metrics") as resp:
            assert resp.status != 404
            assert resp.status == 200


@pytest.mark.asyncio
async def test_metrics_returns_200(dash):
    """GET /metrics возвращает 200 OK."""
    _, port = dash
    status, _, _ = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert status == 200


@pytest.mark.asyncio
async def test_metrics_content_type_is_text_plain(dash):
    """Content-Type соответствует Prometheus (text/plain)."""
    _, port = dash
    _, headers, _ = await _get_text(f"http://127.0.0.1:{port}/metrics")
    ct = headers.get("Content-Type", "")
    assert "text/plain" in ct, f"ожидался text/plain, получен {ct!r}"


@pytest.mark.asyncio
async def test_metrics_no_cache_header(dash):
    """Заголовок Cache-Control: no-store (чтобы Prometheus не кэшировал)."""
    _, port = dash
    _, headers, _ = await _get_text(f"http://127.0.0.1:{port}/metrics")
    cc = headers.get("Cache-Control", "")
    assert "no-store" in cc, f"ожидался no-store, получен {cc!r}"


# ============================================================
# Формат Prometheus exposition
# ============================================================
@pytest.mark.asyncio
async def test_metrics_contains_help_comments(dash):
    """Каждая метрика имеет комментарий # HELP."""
    _, port = dash
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    help_lines = [l for l in body.splitlines() if l.startswith("# HELP")]
    assert len(help_lines) >= 5, f"слишком мало # HELP: {len(help_lines)}"


@pytest.mark.asyncio
async def test_metrics_contains_type_comments(dash):
    """Каждая метрика имеет комментарий # TYPE."""
    _, port = dash
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    type_lines = [l for l in body.splitlines() if l.startswith("# TYPE")]
    assert len(type_lines) >= 5, f"слишком мало # TYPE: {len(type_lines)}"


@pytest.mark.asyncio
async def test_metrics_format_is_valid_prometheus(dash):
    """Формат строк соответствует Prometheus exposition.

    Допустимые паттерны:
    - '# HELP <name> <description>'
    - '# TYPE <name> <gauge|counter|...>'
    - '<name>{<labels>}? <value>' (value — float)
    - пустые строки
    """
    _, port = dash
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    metric_re = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\{[^}]*\})?\s+(-?\d+(\.\d+)?|NaN|\+Inf|-Inf)$")
    for line in body.splitlines():
        if not line or line.startswith("#"):
            continue
        assert metric_re.match(line), f"некорректная строка метрики: {line!r}"


# ============================================================
# Обязательные метрики
# ============================================================
@pytest.mark.asyncio
async def test_metrics_contains_core_gauges(dash):
    """Все базовые gauge'ы присутствуют в ответе."""
    _, port = dash
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    required = [
        "digital_being_energy",
        "digital_being_intelligence",
        "digital_being_cycle_count",
        "digital_being_completed_goals",
        "digital_being_success_streak",
        "digital_being_concepts_total",
        "digital_being_subsystem_count",
        "digital_being_uptime_seconds",
    ]
    for metric in required:
        # Проверяем по строкам значений (не по HELP/TYPE, чтобы избежать ложных срабатываний)
        value_pattern = re.compile(rf"^{re.escape(metric)}(\{{[^}}]*\}})?\s+-?\d+(\.\d+)?$")
        assert any(value_pattern.match(l) for l in body.splitlines()), \
            f"метрика {metric!r} отсутствует в /metrics"


@pytest.mark.asyncio
async def test_metrics_energy_gauge_value(dash):
    """digital_being_energy отражает текущее значение из state."""
    d, port = dash
    d.state.update_status({
        "agent": {"name": "X", "energy": 145, "intelligence": 3, "cycle_count": 42},
        "system": {},
    })
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert re.search(r"^digital_being_energy\s+145(\.0+)?$", body, re.MULTILINE), \
        f"digital_being_energy должно быть 145, body={body!r}"


@pytest.mark.asyncio
async def test_metrics_intelligence_gauge_value(dash):
    """digital_being_intelligence отражает значение из state."""
    d, port = dash
    d.state.update_status({
        "agent": {"name": "X", "energy": 100, "intelligence": 7},
        "system": {},
    })
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert re.search(r"^digital_being_intelligence\s+7(\.0+)?$", body, re.MULTILINE), \
        f"digital_being_intelligence должно быть 7"


@pytest.mark.asyncio
async def test_metrics_cycle_count_value(dash):
    """digital_being_cycle_count — counter, отражает cycle_count из state."""
    d, port = dash
    d.state.update_status({
        "agent": {"name": "X", "cycle_count": 12345},
        "system": {},
    })
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert re.search(r"^digital_being_cycle_count\s+12345$", body, re.MULTILINE)


@pytest.mark.asyncio
async def test_metrics_concepts_total_value(dash):
    """digital_being_concepts_total отражает total_concepts из mental_models."""
    d, port = dash
    d.state.update_status({
        "agent": {"name": "X"},
        "mental_models": {"total_concepts": 87},
        "system": {},
    })
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert re.search(r"^digital_being_concepts_total\s+87(\.0+)?$", body, re.MULTILINE)


@pytest.mark.asyncio
async def test_metrics_subsystem_count_value(dash):
    """digital_being_subsystem_count отражает subsystem_count."""
    d, port = dash
    d.state.update_status({"agent": {"name": "X"}, "system": {}})
    d.state.update_subsystems({"subsystem_count": 12, "subsystems": []})
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert re.search(r"^digital_being_subsystem_count\s+12(\.0+)?$", body, re.MULTILINE)


# ============================================================
# Опциональные метрики
# ============================================================
@pytest.mark.asyncio
async def test_metrics_goal_progress_optional(dash):
    """digital_being_goal_progress_percent появляется только если goals.progress задан."""
    d, port = dash
    # Без goals — не должно быть goal_progress
    d.state.update_status({"agent": {"name": "X"}, "system": {}})
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert "digital_being_goal_progress_percent" not in body

    # С goals.progress — должно появиться
    d.state.update_status({
        "agent": {"name": "X"},
        "goals": {"progress": 65.5},
        "system": {},
    })
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert re.search(
        r"^digital_being_goal_progress_percent\s+65\.5$", body, re.MULTILINE
    ), f"goal_progress_percent=65.5 не найдено в {body!r}"


@pytest.mark.asyncio
async def test_metrics_will_acts_optional(dash):
    """digital_being_will_acts_total появляется только если will.total_acts > 0."""
    d, port = dash
    # Без will — не должно быть
    d.state.update_status({"agent": {"name": "X"}, "system": {}})
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert "digital_being_will_acts_total" not in body

    # С will.total_acts=15 — должно появиться
    d.state.update_status({
        "agent": {"name": "X"},
        "will": {"total_acts": 15},
        "system": {},
    })
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert re.search(r"^digital_being_will_acts_total\s+15$", body, re.MULTILINE)


# ============================================================
# Типы метрик
# ============================================================
@pytest.mark.asyncio
async def test_metrics_energy_is_gauge_type(dash):
    """digital_being_energy объявлен как gauge."""
    _, port = dash
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert re.search(r"^# TYPE digital_being_energy gauge$", body, re.MULTILINE)


@pytest.mark.asyncio
async def test_metrics_cycle_count_is_counter_type(dash):
    """digital_being_cycle_count объявлен как counter (только растёт)."""
    _, port = dash
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert re.search(r"^# TYPE digital_being_cycle_count counter$", body, re.MULTILINE)


@pytest.mark.asyncio
async def test_metrics_completed_goals_is_counter_type(dash):
    """digital_being_completed_goals — counter."""
    _, port = dash
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert re.search(r"^# TYPE digital_being_completed_goals counter$", body, re.MULTILINE)


# ============================================================
# Standalone-режим
# ============================================================
@pytest.mark.asyncio
async def test_metrics_works_without_agent(dash):
    """Endpoint работает без агента (agent=None), значения по умолчанию — нули."""
    _, port = dash  # agent=None
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    # Базовые метрики должны присутствовать
    assert "digital_being_energy 0" in body or "digital_being_energy 0.0" in body
    assert "digital_being_intelligence 1" in body or "digital_being_intelligence 1.0" in body
    assert "digital_being_cycle_count 0" in body


@pytest.mark.asyncio
async def test_metrics_handles_missing_keys_gracefully(dash):
    """При отсутствии вложенных ключей (mental_models, system) — не падает, отдаёт нули."""
    d, port = dash
    # state с пустым agent
    d.state.update_status({})
    _, _, body = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert "digital_being_energy 0" in body or "digital_being_energy 0.0" in body
    assert "digital_being_concepts_total 0" in body or "digital_being_concepts_total 0.0" in body


# ============================================================
# Динамическое обновление
# ============================================================
@pytest.mark.asyncio
async def test_metrics_reflects_state_updates(dash):
    """После update_status значения в /metrics меняются."""
    d, port = dash
    d.state.update_status({
        "agent": {"name": "X", "energy": 50, "intelligence": 2, "cycle_count": 10},
    })
    _, _, body1 = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert re.search(r"^digital_being_energy\s+50(\.0+)?$", body1, re.MULTILINE)

    d.state.update_status({
        "agent": {"name": "X", "energy": 200, "intelligence": 5, "cycle_count": 11},
    })
    _, _, body2 = await _get_text(f"http://127.0.0.1:{port}/metrics")
    assert re.search(r"^digital_being_energy\s+200(\.0+)?$", body2, re.MULTILINE)
    assert re.search(r"^digital_being_intelligence\s+5(\.0+)?$", body2, re.MULTILINE)