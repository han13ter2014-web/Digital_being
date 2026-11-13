"""Регрессии локальных граничных дефектов глобального багхантинга."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.access_control import set_access
from src.cognition.reflection_engine import ReflectionEngine
from src.core.event_bus import EventBus
from src.core.social_cell import SocialCell


def test_zero_event_history_limit_disables_storage():
    bus = EventBus(history_size=0)

    for index in range(3):
        assert bus.publish_sync("message", {"n": index})

    assert bus.get_history() == []
    assert bus.get_stats()["history_size"] == 0


def test_single_event_history_limit_retains_only_latest():
    bus = EventBus(history_size=1)

    assert bus.publish_sync("message", {"n": 1})
    assert bus.publish_sync("message", {"n": 2})

    assert [event.data["n"] for event in bus.get_history()] == [2]


def test_negative_event_history_limit_is_rejected():
    with pytest.raises(ValueError, match="history_size"):
        EventBus(history_size=-1)


class FakeSearcher:
    def __init__(self):
        self.is_enabled = True
        self.calls = []

    def toggle(self, enabled):
        self.calls.append(bool(enabled))
        self.is_enabled = bool(enabled)


def test_failed_access_write_cleans_partial_temporary_file(tmp_path, monkeypatch):
    path = tmp_path / "access_settings.json"
    previous = b'{"network": true}\n'
    path.write_bytes(previous)
    searcher = FakeSearcher()
    agent = SimpleNamespace(web_searcher=searcher)
    original_write_text = Path.write_text

    def fail_temporary_write(self, data, *args, **kwargs):
        if self.name == "access_settings.tmp":
            original_write_text(self, '{"partial"', *args, **kwargs)
            raise OSError("injected disk full")
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_temporary_write)
    result = set_access(agent, "network", False, root=tmp_path)

    assert result["ok"] is False
    assert "injected disk full" in result["error"]
    assert path.read_bytes() == previous
    assert not path.with_suffix(".tmp").exists()
    assert searcher.is_enabled is True
    assert searcher.calls == [False, True]


def test_empty_social_actions_are_consistent_before_and_after_registration():
    social = SocialCell(SimpleNamespace())

    assert social.choose_action_social("peer", []) == "wait"
    social.register_agent("peer")
    assert social.choose_action_social("peer", []) == "wait"


@pytest.mark.parametrize("window_size", [0, -2, 1.5, True])
def test_reflection_window_must_be_a_positive_integer(window_size):
    engine = ReflectionEngine()
    engine.record_cycle({"cycle_count": 1})

    with pytest.raises(ValueError, match="window_size"):
        engine.analyze_performance(window_size)


def test_reflection_window_larger_than_history_returns_none():
    engine = ReflectionEngine()
    engine.record_cycle({"cycle_count": 1})

    assert engine.analyze_performance(2) is None
    assert engine.analyze_performance(1) is not None
