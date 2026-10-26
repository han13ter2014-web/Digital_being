"""Постоянный профиль выбирается до создания существа, а не после."""

import sys
from pathlib import Path

from src.app.paths import setup_environment, resolve_base_dir
from src.core.paths import data_dir, data_path, project_root
from config.settings import Settings


def test_frozen_profile_does_not_write_to_extraction_tree(tmp_path, monkeypatch):
    resources = tmp_path / "extracted"
    resources.mkdir()
    appdata = tmp_path / "roaming"
    monkeypatch.delenv("DIGITAL_BEING_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(resources), raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("XDG_DATA_HOME", str(appdata))
    env = setup_environment(chdir=False, console=False)
    assert env.frozen
    assert Path(data_dir()) == Path(env.data_root)
    assert Path(Settings.DATA_DIR) == Path(env.data_root)
    assert Path(data_path("nursery")) == Path(env.data_root) / "nursery"
    assert Path(Settings.CHECKPOINT_DIR) == Path(env.data_root) / "checkpoints"
    assert not list(resources.iterdir())
    assert str(resources) not in env.data_root


def test_source_resources_do_not_depend_on_launcher_path(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "argv", ["somewhere/launcher.py"])
    base, frozen = resolve_base_dir()
    assert base == project_root()
    assert not frozen


def test_relative_profile_is_resolved_once_before_later_cwd_change(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", "profile")
    env = setup_environment(chdir=False, console=False)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    assert Path(data_dir()) == tmp_path / "profile"
    assert Path(Settings.DATA_DIR) == Path(env.data_root)


def test_agent_constructor_and_nursery_use_selected_profile(tmp_path, monkeypatch):
    from src.app.bootstrap import create_agent
    from src.core.subsystem_base import PluginRegistry

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "profile"))
    env = setup_environment(chdir=False, console=False)
    PluginRegistry.reset_global()
    agent, _ = create_agent(env, "PathTest", new=True)
    assert Path(agent.knowledge_file).parent == Path(env.data_root)
    assert Path(agent.checkpoint_dir) == Path(env.data_root) / "checkpoints"
    watcher = agent.plugin_registry.get("nursery_watcher")
    assert Path(watcher.nursery_dir) == Path(env.data_root) / "nursery"
    assert Path(agent.life_guard.state_path).is_relative_to(Path(env.data_root))
    PluginRegistry.reset_global()
