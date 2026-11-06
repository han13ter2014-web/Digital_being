"""К10: веб повторяет события Tk и не получает обходных путей в Core."""

import asyncio
from copy import deepcopy
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

pytest.importorskip("aiohttp", reason="aiohttp не установлен")
from aiohttp import ClientSession, ClientTimeout  # noqa: E402

from src.core.event_bus import EventBus, Events  # noqa: E402
from src.ui.web_dashboard import SharedState, WebDashboard  # noqa: E402


class RecordingBus:
    def __init__(self):
        self.published = []
        self.accept = True

    def publish_sync(self, name, data=None, source="system", priority=1):
        if self.accept:
            self.published.append((name, deepcopy(data or {}), source))
        return self.accept


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_url(url: str, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.05)
    return False


def _post(port: int, path: str, body: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps({} if body is None else body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _get(port: int, path: str) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


@pytest.fixture
def controlled_dashboard():
    port = _free_port()
    bus = RecordingBus()
    state = SharedState(max_thoughts=30)
    dash = WebDashboard(host="127.0.0.1", port=port, state=state, bus=bus)
    dash.start(in_thread=True)
    assert _wait_for_url(f"http://127.0.0.1:{port}/health")
    yield dash, port, state, bus
    dash.stop()


@pytest.mark.parametrize(
    ("path", "body", "event_name", "payload"),
    [
        ("/api/dialogue", {"text": "  Привет, Тэсс  "}, Events.USER_MESSAGE,
         {"text": "Привет, Тэсс"}),
        ("/api/control/pause", {}, Events.PAUSE_REQUESTED, {}),
        ("/api/control/resume", {}, Events.RESUME_REQUESTED, {}),
        ("/api/control/speed", {"mode": "fast"}, Events.SPEED_CHANGED, {"mode": "fast"}),
        ("/api/control/save", {}, Events.SAVE_REQUESTED, {}),
        ("/api/control/life/request", {"kind": "dream", "reason": "запрос из окна"},
         Events.LIFE_REQUEST, {"kind": "dream", "reason": "запрос из окна"}),
        ("/api/control/life/request", {"kind": "terminate", "reason": "запрос из окна"},
         Events.LIFE_REQUEST, {"kind": "terminate", "reason": "запрос из окна"}),
        ("/api/control/life/wake", {}, Events.LIFE_WAKE, {}),
        ("/api/access", {"key": "presence", "state": "off"}, Events.USER_COMMAND,
         {"command": "access presence off"}),
    ],
)
def test_web_publishes_exact_tk_event(controlled_dashboard, path, body, event_name, payload):
    _, port, _, bus = controlled_dashboard
    status, response = _post(port, path, body)
    assert status == 202 and response["status"] == "accepted"
    assert bus.published == [(event_name, payload, "web")]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/dialogue", {"text": "   "}),
        ("/api/control/speed", {"mode": "step"}),
        ("/api/control/life/request", {"kind": "explode"}),
        ("/api/access", {"key": "core", "state": "on"}),
        ("/api/access", {"key": "network", "state": "perhaps"}),
    ],
)
def test_invalid_commands_never_reach_bus(controlled_dashboard, path, body):
    _, port, _, bus = controlled_dashboard
    status, response = _post(port, path, body)
    assert status == 400 and response["status"] == "rejected"
    assert bus.published == []


def test_standalone_is_honest_and_never_accepts_mutations():
    port = _free_port()
    dash = WebDashboard(host="127.0.0.1", port=port)
    dash.start(in_thread=True)
    try:
        assert _wait_for_url(f"http://127.0.0.1:{port}/health")
        assert _get(port, "/health")["agent_responsive"] is False
        assert _get(port, "/api/control")["bus_connected"] is False
        for path, body in (
            ("/api/dialogue", {"text": "не доставится"}),
            ("/api/control/save", {}),
            ("/api/control/life/wake", {}),
            ("/api/access", {"key": "network", "state": "off"}),
        ):
            status, response = _post(port, path, body)
            assert status == 503 and response["status"] == "unavailable"
    finally:
        dash.stop()


def test_life_confirm_requires_prompt_and_preserves_guard_protocol(controlled_dashboard):
    _, port, state, bus = controlled_dashboard
    status, _ = _post(port, "/api/control/life/confirm", {
        "request_id": "missing", "phrase": "Тэсс",
    })
    assert status == 409 and bus.published == []

    prompt = {
        "request_id": "req-1", "kind": "dream", "phrase": "Тэсс",
        "cooldown_sec": 5.0, "description": "Проверка LifeGuard",
    }
    state.push_event("life_prompt", prompt)
    status, _ = _post(port, "/api/control/life/confirm", {
        "request_id": "req-1", "phrase": "неверная фраза",
    })
    assert status == 202
    assert bus.published[-1] == (Events.LIFE_CONFIRM, {
        "request_id": "req-1", "phrase": "неверная фраза",
    }, "web")

    state.push_event("life_result", {"ok": False, "message": "Слишком рано"})
    assert state.control_snapshot(bus_connected=True)["life_prompt"] == prompt
    state.push_event("life_result", {"ok": True, "message": "Запрос отменён"})
    control = state.control_snapshot(bus_connected=True)
    assert control["life_prompt"] is None
    assert control["life_result"]["ok"] is True
    state.push_event("life_prompt", {"request_id": "req-new", "kind": "terminate"})
    control = state.control_snapshot(bus_connected=True)
    assert control["life_prompt"]["request_id"] == "req-new"
    assert control["life_result"] is None


def test_life_cancel_uses_existing_request_id(controlled_dashboard):
    _, port, state, bus = controlled_dashboard
    state.push_event("life_prompt", {"request_id": "req-2", "kind": "dream", "phrase": "Тэсс"})
    status, _ = _post(port, "/api/control/life/cancel", {"request_id": "req-2"})
    assert status == 202
    assert bus.published == [(Events.LIFE_CANCEL, {"request_id": "req-2"}, "web")]


def test_control_snapshot_contains_only_observed_results(controlled_dashboard):
    _, port, state, _ = controlled_dashboard
    state.update_status({
        "paused": True, "speed_mode": "fast", "life_state": "alive",
        "last_save_ok": True, "last_save_at": 12345.0,
        "pending_life_request": {"request_id": "req-3"},
    })
    state.update_life({"access": {"network": {"enabled": False, "label": "Сеть"}}})
    control = _get(port, "/api/control")
    assert control["paused"] is True and control["speed_mode"] == "fast"
    assert control["last_save_ok"] is True and control["last_save_at"] == 12345.0
    assert control["access"]["network"]["enabled"] is False
    assert control["pending_life_request"] == {"request_id": "req-3"}


@pytest.mark.asyncio
async def test_http_message_reaches_real_runner_and_sse_once(tmp_path, monkeypatch):
    """HTTP → EventBus → настоящий AgentRunner → Runtime → SSE journal."""
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "sandbox"))
    from main import Runtime
    from src.core.agent import DigitalBeing
    from src.core.agent_runner import AgentRunner

    agent = DigitalBeing(name="WebRoute")
    bus = EventBus()
    runner = AgentRunner(agent, bus)
    agent.user_interaction.attach_bus(bus)
    port = _free_port()
    dashboard = WebDashboard(host="127.0.0.1", port=port, bus=bus)
    runtime = Runtime(agent, bus, runner, dashboard=dashboard)
    runtime._subscribe_dashboard()
    dashboard.start(in_thread=True)
    try:
        assert _wait_for_url(f"http://127.0.0.1:{port}/health")
        status, _ = _post(port, "/api/dialogue", {"text": "Привет! Я рядом."})
        assert status == 202
        await bus.start()
        bus.attach_loop(asyncio.get_running_loop())
        bus.drain_pre_start()
        # aiohttp публикует из своего потока: callback enqueue может выполниться
        # после HTTP-ответа. Ждём фактическую доставку, а не два случайных тика.
        for _ in range(50):
            await bus.dispatch_once()
            if agent.user_interaction.get_last_user_message_cycle() is not None:
                break
            await asyncio.sleep(0.02)
        await bus.dispatch_once()

        assert agent.user_interaction.get_last_user_message_cycle() == agent.cycle_count
        events = _get(port, "/api/dialogue?limit=20")["events"]
        sent = [event for event in events
                if event["kind"] == "user" and event["text"] == "Привет! Я рядом."]
        assert len(sent) == 1 and sent[0]["source"] == "web"
        replay = _get(port, f"/api/dialogue?after={sent[0]['sequence']}&limit=20")["events"]
        assert not [event for event in replay
                    if event["kind"] == "user" and event["text"] == "Привет! Я рядом."]
    finally:
        dashboard.stop()


@pytest.mark.asyncio
async def test_user_message_sse_reconnect_has_no_duplicate(controlled_dashboard):
    _, port, state, _ = controlled_dashboard
    state.push_event("user_message", {"text": "одно сообщение"}, source="web")

    async def read_one(after: int, publish_next: bool) -> list[dict]:
        received = []
        async with ClientSession(timeout=ClientTimeout(total=4)) as session:
            async with session.get(
                f"http://127.0.0.1:{port}/stream/dialogue",
                headers={"Last-Event-ID": str(after)},
            ) as response:
                if publish_next:
                    await asyncio.sleep(0.1)
                    state.push_event("agent_message", {"content": "новый ответ"})
                async for line in response.content:
                    text = line.decode("utf-8").strip()
                    if text.startswith("data:"):
                        received.append(json.loads(text[5:].strip()))
                        break
        return received

    first = await asyncio.wait_for(read_one(0, False), timeout=3)
    second = await asyncio.wait_for(read_one(1, True), timeout=3)
    assert len(first) == 1 and first[0]["kind"] == "user"
    assert [item["sequence"] for item in second] == [2]
    assert second[0]["text"] == "новый ответ"


def test_web_surface_has_no_core_or_direct_save_path():
    port = _free_port()
    dash = WebDashboard(host="127.0.0.1", port=port)
    assert not hasattr(dash, "agent") and not hasattr(dash.state, "agent")
    assert hasattr(dash, "bus")
    assert not hasattr(dash, "think") and not hasattr(dash, "save_state")
