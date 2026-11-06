"""К9: Runtime делит одни DTO между Tk и вебом и деградирует без вреда Tk."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from main import Runtime
from src.core.event_bus import EventBus, Events


class _Recorder:
    def __init__(self):
        self.status = []
        self.life = []
        self.graph = []
        self.diary = []
        self.events = []

    def push_status(self, value): self.status.append(value)
    def push_life_status(self, value): self.life.append(value)
    def push_graph(self, value): self.graph.append(value)
    def publish_status(self, value): self.status.append(value)
    def publish_life(self, value): self.life.append(value)
    def publish_graph(self, value): self.graph.append(value)
    def publish_diary(self, value): self.diary.append(value)
    def publish_event(self, *args, **kwargs): self.events.append((args, kwargs))


@pytest.mark.asyncio
async def test_tk_and_web_receive_same_dto_objects(monkeypatch):
    status = {"name": "Parity", "cycle": 9}
    life = {"name": "Parity", "life": {"cycle": 9}, "emotions": {}, "body": {}}
    graph = {"nodes": [], "edges": []}
    diary = {"episodes": [], "cache_limit": 500}
    monkeypatch.setattr("src.app.status.build_status_snapshot", lambda *a, **k: status)
    monkeypatch.setattr("src.ui.life_snapshot.build_life_snapshot", lambda *a: life)
    monkeypatch.setattr("src.ui.life_snapshot.build_diary_snapshot", lambda *a: diary)
    monkeypatch.setattr("src.ui.graph_view.build_life_graph", lambda *a: graph)
    window, dashboard = _Recorder(), _Recorder()
    runtime = Runtime(SimpleNamespace(), EventBus(), SimpleNamespace(), window, dashboard)

    task = asyncio.create_task(runtime._status_loop())
    await asyncio.sleep(0.05)
    runtime.shutdown.set()
    await asyncio.wait_for(task, timeout=1)

    assert window.status[0] is status and dashboard.status[0] is status
    assert window.life[0] is life and dashboard.life[0] is life
    assert window.graph[0] is graph and dashboard.graph[0] is graph
    assert dashboard.diary[0] is diary


@pytest.mark.asyncio
async def test_existing_bus_events_are_forwarded_readonly():
    bus = EventBus()
    dashboard = _Recorder()
    runtime = Runtime(SimpleNamespace(), bus, SimpleNamespace(), dashboard=dashboard)
    runtime._subscribe_dashboard()
    await bus.start()
    await bus.publish(Events.AGENT_MESSAGE, {"id": "m1", "content": "привет"}, source="agent")
    await bus.dispatch_once()
    assert len(dashboard.events) == 1
    args, _ = dashboard.events[0]
    assert args[0] == Events.AGENT_MESSAGE
    assert args[1]["content"] == "привет"


def test_bind_failure_does_not_escape_to_tk():
    dashboard = Mock()
    dashboard.start.side_effect = OSError("порт занят")
    runtime = Runtime(SimpleNamespace(), EventBus(), SimpleNamespace(), dashboard=dashboard)
    runtime._start_dashboard()
    assert "порт занят" in runtime.dashboard_error
    assert runtime.error is None


def test_dashboard_stop_is_idempotent_after_failed_start():
    dashboard = Mock()
    runtime = Runtime(SimpleNamespace(), EventBus(), SimpleNamespace(), dashboard=dashboard)
    runtime._stop_dashboard()
    runtime._stop_dashboard()
    assert dashboard.stop.call_count == 2
