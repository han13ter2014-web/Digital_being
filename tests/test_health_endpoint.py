"""
test_health_endpoint.py — тесты для /health endpoint в web_dashboard.

Покрывает:
- Liveness (по умолчанию) — всегда 200, если сервер жив.
- Readiness (?check=ready) — 503 если нет данных от агента 60+ секунд.
- Liveness возвращает 200 даже при пустом state.
- Поля JSON корректны (status, agent_responsive, last_update_age_sec).
- /health не требует наличия агента (работает в standalone-режиме).
- Endpoint зарегистрирован в роутере.
"""
import asyncio
import os
import socket
import sys
import threading
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


async def _get_json(url, timeout=2.0):
    """GET-запрос с JSON-ответом."""
    async with ClientSession() as sess:
        async with sess.get(url, timeout=timeout) as resp:
            return resp.status, await resp.json()


# ============================================================
# Liveness (по умолчанию)
# ============================================================
@pytest.mark.asyncio
async def test_health_liveness_default_ok(dash):
    """GET /health возвращает 200 со статусом 'ok' при живом сервере."""
    _, port = dash
    status, body = await _get_json(f"http://127.0.0.1:{port}/health")
    assert status == 200
    assert body["status"] == "ok"
    assert "agent_responsive" in body
    assert "last_update_age_sec" in body
    assert "subsystem_count" in body


@pytest.mark.asyncio
async def test_health_liveness_empty_state(dash):
    """Liveness возвращает 200 даже если state пустой (сервер жив — и ладно)."""
    _, port = dash
    # Не вызываем update_status — state пустой.
    status, body = await _get_json(f"http://127.0.0.1:{port}/health")
    assert status == 200
    assert body["status"] == "ok"
    # agent_responsive=False, т.к. last_update_ts == 0
    assert body["agent_responsive"] is False
    assert body["last_update_age_sec"] is None


@pytest.mark.asyncio
async def test_health_liveness_after_recent_update(dash):
    """Liveness показывает agent_responsive=True после свежего update_status."""
    d, port = dash
    d.state.update_status({"agent": {"name": "Test"}, "system": {}})
    status, body = await _get_json(f"http://127.0.0.1:{port}/health")
    assert status == 200
    assert body["status"] == "ok"
    assert body["agent_responsive"] is True
    # last_update_age_sec должен быть маленьким (< 5 сек).
    assert body["last_update_age_sec"] is not None
    assert body["last_update_age_sec"] < 5


# ============================================================
# Readiness (?check=ready)
# ============================================================
@pytest.mark.asyncio
async def test_health_readiness_empty_returns_503(dash):
    """readiness при пустом state — 503 (not_ready)."""
    _, port = dash
    status, body = await _get_json(
        f"http://127.0.0.1:{port}/health?check=ready"
    )
    assert status == 503
    assert body["status"] == "not_ready"
    assert body["agent_responsive"] is False
    assert "reason" in body


@pytest.mark.asyncio
async def test_health_readiness_after_update_returns_200(dash):
    """readiness с свежими данными — 200 (ready)."""
    d, port = dash
    d.state.update_status({"agent": {"name": "Test"}, "system": {}})
    status, body = await _get_json(
        f"http://127.0.0.1:{port}/health?check=ready"
    )
    assert status == 200
    assert body["status"] == "ready"
    assert body["agent_responsive"] is True


@pytest.mark.asyncio
async def test_health_readiness_stale_data_returns_503(dash):
    """readiness с устаревшими данными (>60 сек) — 503."""
    d, port = dash
    # Устанавливаем last_update_ts = now - 120 сек
    d.state._last_update_ts = time.time() - 120
    status, body = await _get_json(
        f"http://127.0.0.1:{port}/health?check=ready"
    )
    assert status == 503
    assert body["status"] == "not_ready"
    assert body["agent_responsive"] is False


# ============================================================
# Формат ответа
# ============================================================
@pytest.mark.asyncio
async def test_health_response_is_json(dash):
    """Ответ — валидный JSON (не HTML, не plain text)."""
    _, port = dash
    async with ClientSession() as sess:
        async with sess.get(f"http://127.0.0.1:{port}/health") as resp:
            ct = resp.headers.get("Content-Type", "")
            assert "application/json" in ct
            body = await resp.json()
            assert isinstance(body, dict)


@pytest.mark.asyncio
async def test_health_contains_expected_fields(dash):
    """Health-ответ содержит все ожидаемые поля."""
    d, port = dash
    d.state.update_status({
        "agent": {"name": "TestAgent", "energy": 100},
        "subsystem_count": 5,
        "system": {},
    })
    _, body = await _get_json(f"http://127.0.0.1:{port}/health")
    assert "status" in body
    assert "agent_responsive" in body
    assert "last_update_age_sec" in body
    assert "subsystem_count" in body
    # С новым update_status subsystem_count=5 (вне update_status,
    # но мы передали его в наш словарь, который перезапишется.
    # Проверим что поле присутствует — конкретное значение зависит от
    # порядка вызовов.
    assert isinstance(body["subsystem_count"], int)


# ============================================================
# Без агента (standalone-режим)
# ============================================================
@pytest.mark.asyncio
async def test_health_works_without_agent(dash):
    """Health работает даже без агента (только dashboard)."""
    _, port = dash  # agent=None
    # Не должно быть 5xx
    status, body = await _get_json(f"http://127.0.0.1:{port}/health")
    assert status == 200
    assert body["status"] == "ok"


# ============================================================
# Маршрут зарегистрирован
# ============================================================
@pytest.mark.asyncio
async def test_health_route_registered(dash):
    """/health доступен (не 404)."""
    _, port = dash
    async with ClientSession() as sess:
        async with sess.get(f"http://127.0.0.1:{port}/health") as resp:
            # Не должно быть 404 (route не зарегистрирован)
            assert resp.status != 404
            assert resp.status == 200