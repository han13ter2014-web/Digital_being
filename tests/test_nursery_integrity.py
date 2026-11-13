"""Целостность и границы каталога «Яслей»."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.bootstrap import awaken_from_seed
from src.core.subsystems.mind_dream import MindDream
from src.core.subsystems.nursery_watcher import NurseryWatcher


class _Registry:
    def __init__(self):
        self.records = []

    def record(self, *args, **kwargs):
        self.records.append((args, kwargs))


def _agent():
    return SimpleNamespace(
        name="Parent",
        creation_time=datetime(2026, 1, 1),
        intelligence=1.25,
        cycle_count=7,
        completed_goals=2,
        energy=88,
        success_streak=3,
        mental_models=SimpleNamespace(
            to_storage_dict=lambda: {"concepts": {}, "claims": {}}
        ),
    )


def _dream(agent):
    return MindDream(agent_name=agent.name, registry=_Registry())


def test_seed_is_published_only_after_all_files_are_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    nursery = tmp_path / "nursery"
    watcher = NurseryWatcher(agent_name="Observer", nursery_dir=str(nursery))
    watcher.setup({})
    agent = _agent()
    dream = _dream(agent)
    original_save = dream._save_seed_files
    during_save = []

    def save_and_observe(seed_folder, *args):
        Path(seed_folder, "metadata.json").write_text("{}", encoding="utf-8")
        during_save.append(watcher.tick(cycle=1))
        return original_save(seed_folder, *args)

    monkeypatch.setattr(dream, "_save_seed_files", save_and_observe)
    result = dream._execute_dream(agent, user_approved=True)
    after_save = watcher.tick(cycle=2)

    assert during_save == [None]
    assert after_save is not None
    assert len(after_save["events"]) == 1
    assert after_save["events"][0]["data"]["is_complete"] is True
    assert after_save["events"][0]["data"]["name"] == Path(result["seed_folder"]).name


def test_failed_seed_save_leaves_no_visible_or_staging_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = _agent()
    dream = _dream(agent)

    def fail_save(seed_folder, *args):
        Path(seed_folder, "metadata.json").write_text("partial", encoding="utf-8")
        raise OSError("disk full")

    monkeypatch.setattr(dream, "_save_seed_files", fail_save)
    with pytest.raises(OSError, match="disk full"):
        dream._execute_dream(agent, user_approved=True)

    assert dream.seed_folder is None
    assert list((tmp_path / "nursery").iterdir()) == []


def test_same_second_dreams_never_overwrite_an_existing_seed(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 13, 12, 0, 0)

    monkeypatch.setattr("src.core.subsystems.mind_dream.datetime", FrozenDateTime)
    agent = _agent()
    first = _dream(agent)._execute_dream(agent, user_approved=True)
    first_path = Path(first["seed_folder"])
    original = (first_path / "metadata.json").read_bytes()

    agent.cycle_count = 8
    second = _dream(agent)._execute_dream(agent, user_approved=True)

    assert second["seed_folder"] != first["seed_folder"]
    assert (first_path / "metadata.json").read_bytes() == original


def test_seed_loading_rejects_parent_directory_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "metadata.json").write_text(
        '{"parent_name": "Outside"}', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="внутри каталога"):
        awaken_from_seed(_agent(), "../outside")


def test_seed_creation_rejects_parent_directory_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    agent = _agent()
    agent.name = "../outside"
    dream = _dream(agent)

    with pytest.raises(ValueError, match="внутри каталога"):
        dream._execute_dream(agent, user_approved=True)

    assert list(tmp_path.glob("outside_seed_*")) == []
