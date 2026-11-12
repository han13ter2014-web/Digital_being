"""Read-only DTO-контракт, HTTP, SSE reconnect и отсутствие мутаций."""

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

from src.ui.web_dashboard import (  # noqa: E402
    DASHBOARD_HTML,
    READ_ONLY_MESSAGE,
    SharedState,
    WebDashboard,
)


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


def _life() -> dict:
    return {
        "name": "Parity",
        "life": {
            "cycle": 7,
            "energy": 123.0,
            "state": "alive",
            "state_label": "жив",
            "speed_mode": "step",
        },
        "now": {"activity": {"action": "play", "target": "партия"}},
        "motivation": {"most_pressing_need": "curiosity"},
        "intentions": {"recent": []},
        "emotions": {
            "levels": {"fear": 0.1, "joy": 0.4, "sadness": 0.2, "calm": 0.4},
            "dominant": {"emotion": "joy", "label": "мне радостно"},
            "episodes": 3,
        },
        "body": {
            "glucose": 80.0,
            "atp": 55.0,
            "atp_ratio": 0.55,
            "fatigue": 0.25,
            "fatigue_level": "normal",
            "needs_rest": False,
        },
        "activities": {"creative": {"count": 1, "drafts": [{"title": "Тишина"}]}},
        "access": {
            "network": {"enabled": True, "label": "Интернет-поиск"},
            "delamain": {"enabled": True, "label": "Планирование задач"},
            "effector": {"enabled": False, "label": "Действия в рабочей папке"},
            "presence": {"enabled": True, "label": "Присутствие"},
            "workspace": {"path": "sandbox", "label": "Творческая рабочая область"},
        },
        "effector": {"counts": {"queued": 1, "succeeded": 2}},
        "diary": {"episodes": [], "count": 0},
    }


@pytest.fixture
def dashboard():
    port = _free_port()
    state = SharedState(max_thoughts=20)
    dash = WebDashboard(host="127.0.0.1", port=port, state=state)
    dash.start(in_thread=True)
    assert _wait_for_url(f"http://127.0.0.1:{port}/health")
    yield dash, port, state
    dash.stop()


def _get_json(port: int, path: str) -> dict:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}{path}", timeout=3
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def test_shared_state_copies_dto_and_has_no_core():
    state = SharedState()
    life = _life()
    state.update_life(life)
    life["body"]["atp"] = 0
    assert state.life_snapshot()["body"]["atp"] == 55.0
    dash = WebDashboard(state=state)
    assert not hasattr(dash, "agent")
    assert not hasattr(dash, "apply_action")
    assert not hasattr(state, "push_action")


def test_status_uses_flat_runtime_dto():
    state = SharedState()
    state.update_status(
        {
            "name": "Parity",
            "cycle": 7,
            "energy": 123,
            "concepts": 9,
            "rss_mb": 42,
            "goals_completed": 2,
        }
    )
    state.update_life(_life())
    snap = state.snapshot()
    assert snap["agent"] == {
        "name": "Parity",
        "cycle_count": 7,
        "energy": 123,
        "intelligence": 1,
        "completed_goals": 2,
        "success_streak": 0,
        "is_alive": True,
    }
    assert snap["mental_models"]["total_concepts"] == 9
    assert snap["system"]["current_rss_mb"] == 42
    assert snap["panel"]["cycle"] == 7


def test_diary_pagination_contract():
    state = SharedState(max_diary=5)
    episodes = [{"id": i, "action": "play", "ts": i} for i in range(5)]
    state.update_diary({"episodes": episodes, "cache_limit": 5})
    first = state.diary_page(offset=0, limit=2)
    second = state.diary_page(offset=2, limit=2)
    third = state.diary_page(offset=4, limit=2)
    assert [row["id"] for row in first["episodes"]] == [0, 1]
    assert first["next_offset"] == 2 and first["has_more"] is True
    assert [row["id"] for row in second["episodes"]] == [2, 3]
    assert [row["id"] for row in third["episodes"]] == [4]
    assert third["next_offset"] is None and third["has_more"] is False
    assert third["stored"] == third["cache_limit"] == 5
    assert third["may_have_older_outside_cache"] is True


def test_dialogue_sequence_history_and_gap_are_explicit():
    state = SharedState(max_thoughts=3)
    for index in range(5):
        state.push_event(
            "agent_message", {"id": f"m{index}", "content": f"текст {index}"}
        )
    replay = state.dialogue_history(after=1, limit=10)
    assert [item["sequence"] for item in replay["events"]] == [3, 4, 5]
    assert replay["history_gap"] is True
    again = state.dialogue_history(after=5, limit=10)
    assert again["events"] == [] and again["latest_sequence"] == 5


def test_all_readonly_http_sections_match_published_dto(dashboard):
    _, port, state = dashboard
    life = _life()
    graph = {
        "nodes": [{"id": "c1", "kind": "concept", "label": "память"}],
        "edges": [],
        "omitted": 0,
    }
    state.update_life(life)
    state.update_graph(graph)
    assert _get_json(port, "/api/life") == life
    for section in ("activities", "access", "emotions", "body"):
        assert _get_json(port, f"/api/{section}")[section] == life[section]
    assert _get_json(port, "/api/graph") == graph


def test_diary_http_pagination(dashboard):
    _, port, state = dashboard
    state.update_diary({"episodes": [{"id": i} for i in range(7)], "cache_limit": 500})
    page = _get_json(port, "/api/diary?offset=5&limit=3")
    assert page["offset"] == 5 and page["limit"] == 3
    assert page["returned"] == 2 and page["has_more"] is False
    assert [row["id"] for row in page["episodes"]] == [5, 6]


def test_action_is_always_403_and_state_is_unchanged(dashboard):
    _, port, state = dashboard
    state.update_life(_life())
    before = deepcopy(state.life_snapshot())
    for body in (
        {},
        {"action": "save"},
        {"action": "shutdown"},
        {"action": "set_goal", "args": {"title": "мутация"}},
    ):
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/action",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=3)
        assert caught.value.code == 403
        payload = json.loads(caught.value.read().decode("utf-8"))
        assert payload["status"] == "forbidden"
        assert READ_ONLY_MESSAGE in payload["message"]
    assert state.life_snapshot() == before


def test_html_exposes_only_narrow_event_based_controls(dashboard):
    _, port, _ = dashboard
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
        body = response.read().decode("utf-8")
    assert body == DASHBOARD_HTML
    assert "ЭТАП 2 · СОБЫТИЯ ЯДРА" in body
    assert "fetch('/api/action'" not in body
    assert "sendCommand('/api/dialogue'" in body
    assert "sendCommand('/api/control/life/confirm'" in body
    assert "set_goal" not in body
    assert "think(" not in body and "save_state(" not in body


@pytest.mark.asyncio
async def test_sse_reconnect_replays_without_duplicates(dashboard):
    _, port, state = dashboard
    state.push_event("agent_message", {"content": "первое", "cycle": 1})
    state.push_event("agent_question", {"content": "второе", "cycle": 2})

    async def read_events(after: int, publish: bool) -> list:
        received = []
        async with ClientSession(timeout=ClientTimeout(total=5)) as session:
            async with session.get(
                f"http://127.0.0.1:{port}/stream/dialogue",
                headers={"Last-Event-ID": str(after)},
            ) as response:
                assert response.status == 200
                if publish:
                    await asyncio.sleep(0.1)
                    state.push_event("agent_message", {"content": "третье", "cycle": 3})
                async for line in response.content:
                    text = line.decode("utf-8").strip()
                    if text.startswith("data:"):
                        received.append(json.loads(text[5:].strip()))
                        if len(received) == (2 if after == 0 else 1):
                            break
        return received

    first = await asyncio.wait_for(read_events(0, False), timeout=4)
    second = await asyncio.wait_for(read_events(2, True), timeout=4)
    assert [item["sequence"] for item in first] == [1, 2]
    assert [item["sequence"] for item in second] == [3]
    assert second[0]["text"] == "третье"


def test_dashboard_stops_cleanly():
    port = _free_port()
    dash = WebDashboard(host="127.0.0.1", port=port)
    dash.start(in_thread=True)
    assert _wait_for_url(f"http://127.0.0.1:{port}/health")
    dash.stop()
    time.sleep(0.1)
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=0.3).close()


def test_bind_error_is_visible_to_runtime_wrapper():
    port = _free_port()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)
    dash = WebDashboard(host="127.0.0.1", port=port)
    try:
        with pytest.raises(OSError):
            dash.start(in_thread=True)
    finally:
        dash.stop()
        blocker.close()


def test_non_localhost_is_rejected():
    with pytest.raises(ValueError):
        WebDashboard(host="0.0.0.0", port=_free_port())
