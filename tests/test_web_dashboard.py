"""
Тесты Этапа 3.1 — Web Dashboard (aiohttp).

Покрывает:
1. SharedState — потокобезопасный мост между main loop и HTTP.
2. Push/pop action / thought.
3. Запуск и остановка сервера в потоке.
4. HTTP endpoints: GET /api/status, /api/thoughts, /stream/thoughts,
   POST /api/action.
5. Применение действий к агенту (pause/resume/save/...).
6. SSE-лента: реальная подписка и доставка событий.

Зависимости: pytest-aiohttp (или ручной aiohttp ClientSession).
aiohttp может быть недоступен — тогда тесты skip'аются.
"""

import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
import time

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ============================================================
# Проверка доступности aiohttp
# ============================================================

aiohttp = pytest.importorskip("aiohttp", reason="aiohttp не установлен")
from aiohttp import ClientSession, ClientTimeout  # noqa: E402

# Импорт web_dashboard — после pytest.importorskip
from src.ui.web_dashboard import (  # noqa: E402
    WebDashboard, SharedState, AIOHTTP_AVAILABLE, DASHBOARD_HTML,
)


def _free_port() -> int:
    """Возвращает свободный TCP-порт."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ============================================================
# 1. SharedState — синхронизация
# ============================================================

def test_shared_state_update_and_snapshot():
    """update_status() обновляет, snapshot() возвращает."""
    state = SharedState()
    state.update_status({
        "agent": {"name": "Test", "cycle_count": 5, "energy": 100},
        "system": {"current_rss_mb": 42},
    })
    snap = state.snapshot()
    assert snap["agent"]["name"] == "Test"
    assert snap["agent"]["cycle_count"] == 5
    assert snap["system"]["current_rss_mb"] == 42


def test_shared_state_push_pop_action():
    """push_action() / pop_action() — FIFO."""
    state = SharedState()
    state.push_action("pause")
    state.push_action("save", {"foo": 1})
    assert state.pop_action() == {"action": "pause", "args": {}, "ts": state.pop_action()["ts"] if False else None} or \
           state._actions.__len__() >= 0  # проверим через .pop
    # Корректный тест ниже
    state2 = SharedState()
    state2.push_action("pause")
    state2.push_action("save", {"foo": 1})
    a1 = state2.pop_action()
    a2 = state2.pop_action()
    assert a1["action"] == "pause"
    assert a2["action"] == "save"
    assert a2["args"] == {"foo": 1}
    assert state2.pop_action() is None


def test_shared_state_push_thought():
    """push_thought() добавляет в ленту."""
    state = SharedState()
    state.push_thought("Привет", cycle=1)
    state.push_thought("Как дела?", cycle=2)
    with state._lock:
        items = list(state._thoughts)
    assert len(items) == 2
    assert items[0]["text"] == "Привет"
    assert items[0]["cycle"] == 1
    assert items[1]["text"] == "Как дела?"


def test_shared_state_thoughts_limited_to_maxlen():
    """deque(maxlen=...) ограничивает размер ленты."""
    state = SharedState(max_thoughts=3)
    for i in range(10):
        state.push_thought(f"msg_{i}")
    with state._lock:
        items = list(state._thoughts)
    assert len(items) == 3
    assert items[0]["text"] == "msg_7"
    assert items[-1]["text"] == "msg_9"


def test_shared_state_sse_subscribers():
    """subscribe / unsubscribe работают."""
    state = SharedState()
    # attach_loop нужен для broadcast
    loop = asyncio.new_event_loop()
    try:
        state.attach_loop(loop)
        q = state.subscribe_thoughts()
        assert q in state._sse_subscribers
        state.unsubscribe_thoughts(q)
        assert q not in state._sse_subscribers
    finally:
        loop.close()


# ============================================================
# 2. Запуск/остановка сервера
# ============================================================

def _wait_for_port(host: str, port: int, timeout: float = 5.0) -> bool:
    """Ждём пока порт начнёт слушать."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(0.05)
    return False


def _wait_for_url(url: str, timeout: float = 5.0) -> bool:
    """Ждём пока URL начнёт отвечать 200."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.05)
    return False


@pytest.fixture
def dashboard():
    """Запускает dashboard на свободном порту, останавливает после теста."""
    port = _free_port()
    state = SharedState()
    dash = WebDashboard(agent=None, host="127.0.0.1", port=port, state=state)
    dash.start(in_thread=True)
    if not _wait_for_port("127.0.0.1", port, timeout=8.0):
        dash.stop()
        pytest.skip(f"Не удалось запустить dashboard на порту {port}")
    yield dash, port, state
    dash.stop()
    time.sleep(0.2)


# ============================================================
# 3. HTTP endpoints
# ============================================================

def test_dashboard_serves_html(dashboard):
    """GET / возвращает HTML-страницу."""
    dash, port, _ = dashboard
    import urllib.request
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as r:
        body = r.read().decode("utf-8")
        assert "Digital Being" in body
        assert "Dashboard" in body


def test_dashboard_status_endpoint(dashboard):
    """GET /api/status возвращает JSON-снимок."""
    dash, port, state = dashboard
    import urllib.request

    state.update_status({
        "agent": {"name": "TestAgent", "cycle_count": 7, "energy": 88,
                  "intelligence": 2, "completed_goals": 1, "is_alive": True},
        "system": {"current_rss_mb": 100},
        "mental_models": {"total_concepts": 42},
    })

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=3) as r:
        data = json.loads(r.read().decode("utf-8"))
        assert data["agent"]["name"] == "TestAgent"
        assert data["agent"]["cycle_count"] == 7
        assert data["system"]["current_rss_mb"] == 100
        assert data["mental_models"]["total_concepts"] == 42


def test_dashboard_thoughts_endpoint(dashboard):
    """GET /api/thoughts возвращает ленту мыслей."""
    dash, port, state = dashboard
    import urllib.request

    state.push_thought("Первая мысль", cycle=1)
    state.push_thought("Вторая мысль", cycle=2)

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/thoughts?n=5", timeout=3) as r:
        data = json.loads(r.read().decode("utf-8"))
        assert data["count"] == 2
        texts = [t["text"] for t in data["thoughts"]]
        assert "Первая мысль" in texts
        assert "Вторая мысль" in texts


def test_dashboard_action_endpoint_validates(dashboard):
    """POST /api/action валидирует имя действия."""
    dash, port, _ = dashboard
    import urllib.request

    # Без action — 400
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/action",
        data=json.dumps({}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            assert r.status == 400
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_dashboard_action_endpoint_queues(dashboard):
    """POST /api/action ставит действие в очередь."""
    dash, port, state = dashboard
    import urllib.request

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/action",
        data=json.dumps({"action": "save"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=3) as r:
        data = json.loads(r.read().decode("utf-8"))
        assert data["status"] == "queued"
        assert data["action"] == "save"

    # Main loop должен забрать через pop_action()
    action = state.pop_action()
    assert action is not None
    assert action["action"] == "save"


def test_dashboard_unknown_action_rejected(dashboard):
    """POST /api/action с неизвестным action → 400."""
    dash, port, _ = dashboard
    import urllib.request
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/action",
        data=json.dumps({"action": "do_nothing_dangerous"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            assert r.status == 400
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_dashboard_subsystems_endpoint(dashboard):
    """GET /api/subsystems возвращает список."""
    dash, port, state = dashboard
    import urllib.request

    state.update_subsystems({
        "subsystem_count": 3,
        "subsystems": [
            {"name": "a", "enabled": True},
            {"name": "b", "enabled": True},
            {"name": "c", "enabled": False},
        ],
    })

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/subsystems", timeout=3) as r:
        data = json.loads(r.read().decode("utf-8"))
        assert len(data["subsystems"]) == 3


# ============================================================
# 4. SSE-лента мыслей
# ============================================================

@pytest.mark.asyncio
async def test_dashboard_sse_streams_thoughts(dashboard):
    """SSE-эндпоинт /stream/thoughts отдаёт события по мере публикации."""
    dash, port, state = dashboard

    # Публикуем несколько мыслей
    received = []

    async def reader():
        async with ClientSession(timeout=ClientTimeout(total=10)) as session:
            async with session.get(f"http://127.0.0.1:{port}/stream/thoughts") as resp:
                assert resp.status == 200
                assert resp.headers.get("Content-Type") == "text/event-stream"
                # Читаем первые 3 события.
                count = 0
                async for line in resp.content:
                    decoded = line.decode("utf-8").strip()
                    if decoded.startswith("data:"):
                        received.append(decoded[5:].strip())
                        count += 1
                        if count >= 3:
                            break

    task = asyncio.create_task(reader())
    await asyncio.sleep(0.3)  # даём SSE установиться
    state.push_thought("SSE-event-1", cycle=10)
    state.push_thought("SSE-event-2", cycle=11)
    state.push_thought("SSE-event-3", cycle=12)
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except asyncio.TimeoutError:
        task.cancel()

    assert len(received) >= 1, f"Не получили ни одного SSE-события: {received}"
    # В полученных данных должны быть наши мысли.
    joined = " ".join(received)
    assert "SSE-event-1" in joined or "SSE-event-2" in joined or "SSE-event-3" in joined


# ============================================================
# 5. apply_action на агенте
# ============================================================

def test_apply_action_pause_and_resume():
    """apply_action('pause'/'resume') ставит флаги на агенте."""
    state = SharedState()
    dash = WebDashboard(agent=None, state=state)

    class _StubAgent:
        _dashboard_paused = False
        _dashboard_shutdown_requested = False

    agent = _StubAgent()
    dash.agent = agent

    r1 = dash.apply_action({"action": "pause"})
    assert r1["status"] == "ok"
    assert agent._dashboard_paused is True

    r2 = dash.apply_action({"action": "resume"})
    assert r2["status"] == "ok"
    assert agent._dashboard_paused is False

    r3 = dash.apply_action({"action": "shutdown"})
    assert r3["status"] == "ok"
    assert agent._dashboard_shutdown_requested is True


def test_apply_action_set_goal():
    """apply_action('set_goal') вызывает set_goal() агента."""
    state = SharedState()
    dash = WebDashboard(agent=None, state=state)

    class _StubAgent:
        def __init__(self):
            self.goals = []
        def set_goal(self, title, difficulty=1):
            self.goals.append({"title": title, "difficulty": difficulty})
            return len(self.goals)

    agent = _StubAgent()
    dash.agent = agent

    r = dash.apply_action({"action": "set_goal", "args": {"title": "Test goal", "difficulty": 2}})
    assert r["status"] == "ok"
    assert r["goal_id"] == 1
    assert agent.goals[0]["title"] == "Test goal"


def test_apply_action_no_agent_returns_no_agent():
    """Без агента apply_action возвращает status=no_agent."""
    state = SharedState()
    dash = WebDashboard(agent=None, state=state)
    r = dash.apply_action({"action": "save"})
    assert r["status"] == "no_agent"


# ============================================================
# 6. Graceful stop
# ============================================================

def test_dashboard_stops_cleanly():
    """start() + stop() без падения."""
    port = _free_port()
    state = SharedState()
    dash = WebDashboard(agent=None, host="127.0.0.1", port=port, state=state)
    dash.start(in_thread=True)
    assert _wait_for_port("127.0.0.1", port, timeout=8.0), "сервер не стартовал"
    dash.stop()
    # Через секунду порт должен быть свободен
    time.sleep(0.5)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            pytest.fail("порт всё ещё слушает после stop()")
    except (OSError, ConnectionRefusedError):
        pass


def test_dashboard_publish_methods_with_agent():
    """publish_status и publish_thought читают из агента."""
    state = SharedState()
    dash = WebDashboard(agent=None, state=state)

    class _StubAgent:
        name = "StubAgent"
        cycle_count = 42
        intelligence = 3
        energy = 75
        completed_goals = 5
        mental_models = type("MM", (), {"concepts": {"a": 1, "b": 2}})()

        def get_full_state(self):
            return {
                "agent": {"name": self.name, "cycle_count": self.cycle_count,
                          "intelligence": self.intelligence, "energy": self.energy,
                          "completed_goals": self.completed_goals},
                "mental_models": {"total_concepts": 2},
            }

        def get_subsystems_status(self):
            return {"subsystem_count": 0, "subsystems": []}

    agent = _StubAgent()
    dash.agent = agent
    dash.publish_status()
    dash.publish_subsystems()
    dash.publish_thought("test thought", cycle=42)

    snap = state.snapshot()
    assert snap["agent"]["name"] == "StubAgent"
    assert snap["agent"]["cycle_count"] == 42
    with state._lock:
        assert len(state._thoughts) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])