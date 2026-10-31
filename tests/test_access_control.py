"""Переключатели доступов: меняют Core, сохраняются и не врут при отказе."""

import json

from src.app.access_control import (
    apply_saved,
    current_state,
    load_saved,
    set_access,
)


class FakeSearcher:
    def __init__(self, enabled=True):
        self.is_enabled = enabled
        self.calls = []

    def toggle(self, enabled):
        self.calls.append(bool(enabled))
        self.is_enabled = bool(enabled)


class FakeDelamain:
    def __init__(self, enabled=False, fail=False):
        self.enabled = enabled
        self.fail = fail
        self.enable_calls = 0
        self.disable_calls = 0

    def enable(self):
        self.enable_calls += 1
        if self.fail:
            self.enabled = False
            return {"ok": False, "enabled": False, "error": "runtime не создан"}
        self.enabled = True
        return {"ok": True, "enabled": True, "error": None}

    def disable(self):
        self.disable_calls += 1
        self.enabled = False
        return {"ok": True, "enabled": False, "error": None}


class FakeEffector:
    def __init__(self, enabled=False):
        self.enabled = enabled


class FakeAgent:
    def __init__(self, **kwargs):
        self.web_searcher = kwargs.get("searcher", FakeSearcher())
        self.delamain = kwargs.get("delamain", FakeDelamain())
        self.delamain_effector = kwargs.get("effector", FakeEffector())


def test_set_access_applies_and_persists(tmp_path):
    agent = FakeAgent()
    result = set_access(agent, "network", False, root=tmp_path)
    assert result["ok"] is True
    assert agent.web_searcher.is_enabled is False
    assert load_saved(tmp_path) == {"network": False}


def test_saved_choice_is_applied_on_next_start(tmp_path):
    first = FakeAgent(searcher=FakeSearcher(True))
    set_access(first, "network", False, root=tmp_path)
    set_access(first, "delamain", True, root=tmp_path)

    second = FakeAgent(searcher=FakeSearcher(True), delamain=FakeDelamain(False))
    report = apply_saved(second, tmp_path)
    assert report["error"] is None
    assert set(report["applied"]) == {"network", "delamain"}
    assert second.web_searcher.is_enabled is False
    assert second.delamain.enabled is True


def test_failure_does_not_persist_a_false_promise(tmp_path):
    agent = FakeAgent(delamain=FakeDelamain(False, fail=True))
    result = set_access(agent, "delamain", True, root=tmp_path)
    assert result["ok"] is False
    assert "runtime" in result["error"]
    assert load_saved(tmp_path) == {}
    assert agent.delamain.enabled is False


def test_missing_subsystem_is_reported_not_swallowed(tmp_path):
    agent = FakeAgent()
    agent.web_searcher = None
    result = set_access(agent, "network", False, root=tmp_path)
    assert result["ok"] is False
    assert "не подключён" in result["error"]


def test_corrupt_settings_do_not_stop_life(tmp_path):
    (tmp_path / "access_settings.json").write_text("{битый", encoding="utf-8")
    report = apply_saved(FakeAgent(), tmp_path)
    assert report["applied"] == []
    assert report["error"]


def test_current_state_reads_real_flags(tmp_path):
    agent = FakeAgent(
        searcher=FakeSearcher(False),
        delamain=FakeDelamain(True),
        effector=FakeEffector(True),
    )
    assert current_state(agent) == {
        "network": False,
        "delamain": True,
        "effector": True,
    }


def test_runner_access_command_changes_and_answers_humanly(tmp_path, monkeypatch):
    from src.core.agent_runner import AgentRunner

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    runner = AgentRunner.__new__(AgentRunner)
    runner.agent = FakeAgent()

    text = runner._handle_access_command("access network off")
    assert "Интернет-поиск" in text
    assert "выключено" in text
    assert runner.agent.web_searcher.is_enabled is False

    bad = runner._handle_access_command("access network maybe")
    assert "Использование" in bad


def test_runner_command_rejects_unknown_access(tmp_path, monkeypatch):
    from src.core.agent_runner import AgentRunner

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    runner = AgentRunner.__new__(AgentRunner)
    runner.agent = FakeAgent()
    text = runner._handle_access_command("access dishes off")
    assert "Неизвестное разрешение" in text or "Использование" in text


def test_effector_requires_planning_layer(tmp_path):
    agent = FakeAgent(delamain=FakeDelamain(False), effector=FakeEffector(False))
    result = set_access(agent, "effector", True, root=tmp_path)
    assert result["ok"] is False
    assert "Планирование задач" in result["error"]
    assert agent.delamain_effector.enabled is False
    assert load_saved(tmp_path) == {}


def test_saved_file_is_plain_json(tmp_path):
    agent = FakeAgent(delamain=FakeDelamain(True))
    set_access(agent, "effector", True, root=tmp_path)
    payload = json.loads((tmp_path / "access_settings.json").read_text(encoding="utf-8"))
    assert payload == {"effector": True}
