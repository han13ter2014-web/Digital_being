"""Компенсирующая очистка частично собранного Runtime и агента."""

import logging

import pytest

import main
from src.app.bootstrap import create_agent
from src.app.paths import setup_environment
from src.app.profile_lock import ProfileWriterLock
from src.core.agent import DigitalBeing
from src.core.subsystem_base import PluginRegistry


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "data"))
    PluginRegistry.reset_global()
    env = setup_environment(chdir=False, console=False)
    yield env
    PluginRegistry.reset_global()
    logging.shutdown()


def test_build_runtime_preserves_setup_error_and_tears_down_when_release_fails(
    isolated_env, monkeypatch
):
    captured = {}
    teardown_calls = []
    original_create = create_agent
    original_teardown = PluginRegistry.teardown_all
    original_release = ProfileWriterLock.release

    def capturing_create(*args, **kwargs):
        agent, report = original_create(*args, **kwargs)
        captured["agent"] = agent
        return agent, report

    def tracked_teardown(self):
        teardown_calls.append(self)
        return original_teardown(self)

    def failing_release(self):
        original_release(self)
        raise OSError("injected close failure")

    def fail_controller(*args, **kwargs):
        raise RuntimeError("injected setup failure")

    monkeypatch.setattr("src.app.bootstrap.create_agent", capturing_create)
    monkeypatch.setattr("src.app.life_controller.LifeController", fail_controller)
    monkeypatch.setattr(PluginRegistry, "teardown_all", tracked_teardown)
    monkeypatch.setattr(ProfileWriterLock, "release", failing_release)
    monkeypatch.setattr(main.atexit, "register", lambda *args, **kwargs: None)
    args = main.parse_args(["--ui", "headless", "--name", "Cleanup", "--new"])

    try:
        with pytest.raises(RuntimeError, match="injected setup failure"):
            main.build_runtime(args, isolated_env)
        assert teardown_calls == [captured["agent"].plugin_registry]
    finally:
        agent = captured.get("agent")
        if agent is not None and not teardown_calls:
            original_teardown(agent.plugin_registry)


def test_create_agent_tears_down_constructed_agent_on_late_failure(
    isolated_env, monkeypatch
):
    captured = {}
    teardown_calls = []
    original_init = DigitalBeing.__init__
    original_teardown = PluginRegistry.teardown_all

    def capturing_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        captured["agent"] = self

    def tracked_teardown(self):
        teardown_calls.append(self)
        return original_teardown(self)

    def fail_apply_saved(*args, **kwargs):
        raise RuntimeError("injected late create_agent failure")

    monkeypatch.setattr(DigitalBeing, "__init__", capturing_init)
    monkeypatch.setattr(PluginRegistry, "teardown_all", tracked_teardown)
    monkeypatch.setattr("src.app.access_control.apply_saved", fail_apply_saved)

    try:
        with pytest.raises(RuntimeError, match="injected late create_agent failure"):
            create_agent(isolated_env, "CreateFail", new=True)
        assert teardown_calls == [captured["agent"].plugin_registry]
    finally:
        agent = captured.get("agent")
        if agent is not None and not teardown_calls:
            original_teardown(agent.plugin_registry)
