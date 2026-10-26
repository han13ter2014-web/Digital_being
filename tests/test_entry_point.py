"""Тесты единой точки входа: пути, сборка агента, семя, аргументы.

Проверяется то, из-за чего раньше было «две разные программы»:
разные пути к данным, разные способы восстановления состояния и
отсутствие проращивания семени в консольном режиме.
"""

import json
import os

import pytest

from src.app.bootstrap import (
    awaken_from_seed,
    create_agent,
    latest_checkpoint,
)
from src.app.paths import AppEnv, setup_environment
from main import INTERVAL_TO_MODE, parse_args, resolve_speed


# ============================================================
# Аргументы и темп
# ============================================================


@pytest.mark.parametrize(
    "value,expected",
    [
        ("5", "live"),
        ("5.0", "live"),
        ("0.5", "fast"),
        ("0", "max"),
        ("0.0", "max"),
        ("max", "max"),
        ("step", "step"),
        ("live", "live"),
        ("fast", "fast"),
    ],
)
def test_resolve_speed(value, expected):
    assert resolve_speed(value) == expected


def test_resolve_speed_rejects_garbage():
    with pytest.raises(SystemExit):
        resolve_speed("быстро-очень")


def test_default_ui_is_gui():
    args = parse_args([])
    assert args.ui == "gui"
    assert args.interval == "5"
    assert args.new is False
    assert args.seed is None


def test_legacy_headless_flag_maps():
    args = parse_args(["--headless", "--new"])
    assert args.headless is True
    assert args.new is True


def test_all_ui_modes_accepted():
    for mode in ("gui", "tray", "console", "headless"):
        assert parse_args(["--ui", mode]).ui == mode


def test_interval_table_is_consistent():
    for value, mode in INTERVAL_TO_MODE.items():
        assert resolve_speed(value) == mode


# ============================================================
# Окружение
# ============================================================


def test_setup_environment_creates_data_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "data"))
    env = setup_environment(chdir=False)

    assert isinstance(env, AppEnv)
    assert os.path.isdir(env.data_root)
    for sub in ("checkpoints", "logs", "nursery", "snapshots"):
        assert os.path.isdir(os.path.join(env.data_root, sub))
    assert os.path.isfile(env.log_file)


def test_setup_environment_respects_override(tmp_path, monkeypatch):
    target = tmp_path / "custom"
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(target))
    env = setup_environment(chdir=False)
    assert os.path.abspath(env.data_root) == os.path.abspath(str(target))


# ============================================================
# Чекпоинты
# ============================================================


def test_latest_checkpoint_none_when_empty(tmp_path):
    assert latest_checkpoint("Nobody", str(tmp_path / "nope")) is None


def test_latest_checkpoint_picks_newest(tmp_path):
    directory = tmp_path / "checkpoints"
    directory.mkdir()
    for step in (5, 120, 37):
        (directory / f"Alpha_cycle_{step}.json").write_text(
            "{}", encoding="utf-8"
        )

    found = latest_checkpoint("Alpha", str(directory))
    assert found is not None
    assert found.endswith("Alpha_cycle_120.json")


def test_latest_checkpoint_ignores_other_agents(tmp_path):
    directory = tmp_path / "checkpoints"
    directory.mkdir()
    (directory / "Other_cycle_900.json").write_text("{}", encoding="utf-8")
    (directory / "Alpha_cycle_3.json").write_text("{}", encoding="utf-8")

    found = latest_checkpoint("Alpha", str(directory))
    assert found is not None
    assert "Alpha_cycle_3" in found


# ============================================================
# Сборка агента
# ============================================================


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "data"))
    return setup_environment(chdir=False)


def test_create_agent_new_life(env):
    agent, report = create_agent(env, "EntryTest", new=True)

    assert agent.name == "EntryTest"
    assert report["source"] == "new"
    # База знаний лежит в пользовательской папке, не рядом с .exe.
    assert agent.knowledge_file.startswith(env.data_root)
    assert agent.checkpoint_dir.startswith(env.data_root)


def test_create_agent_restores_checkpoint(env):
    first, _ = create_agent(env, "EntryRestore", new=True)
    first.cycle_count = 42
    first.save_state()

    second, report = create_agent(env, "EntryRestore")
    assert report["source"] == "checkpoint"
    assert second.cycle_count == 42


def test_create_agent_new_ignores_checkpoint(env):
    first, _ = create_agent(env, "EntryFresh", new=True)
    first.cycle_count = 99
    first.save_state()

    second, report = create_agent(env, "EntryFresh", new=True)
    assert report["source"] == "new"
    assert second.cycle_count == 0


# ============================================================
# Проращивание семени
# ============================================================


def _write_seed(env, name="Parent_seed_2026", concepts=3):
    from src.core.paths import data_path

    seed_dir = os.path.join(data_path("nursery"), name)
    os.makedirs(seed_dir, exist_ok=True)
    with open(
        os.path.join(seed_dir, "metadata.json"), "w", encoding="utf-8"
    ) as handle:
        json.dump(
            {
                "parent_name": "Parent",
                "dream_time": "2026-06-23T23:15:00",
                "cycles_lived": 500,
            },
            handle,
        )
    with open(
        os.path.join(seed_dir, "mental_models.json"), "w", encoding="utf-8"
    ) as handle:
        json.dump(
            {
                "concepts": {
                    f"концепт_{i}": {
                        "definition_hypothesis": f"значение {i}",
                        "confidence": 0.7,
                        "connections": {},
                        "contexts": [],
                    }
                    for i in range(concepts)
                }
            },
            handle,
        )
    with open(
        os.path.join(seed_dir, "identity.json"), "w", encoding="utf-8"
    ) as handle:
        json.dump(
            {"values": ["Опыт", "Тишина"], "identity": {"statement": "Я есть"}},
            handle,
        )
    return seed_dir


def test_awaken_from_seed_inherits_and_saves(env):
    from src.core.paths import data_path

    _write_seed(env, "SeedA", concepts=3)
    agent, report = create_agent(env, "Child", seed="SeedA")

    assert report["source"] == "seed"
    assert report["seed"] == "SeedA"
    assert report["seed_report"]["concepts"] >= 3
    assert agent.parent_name == "Parent"
    assert agent.value_evolution.current_values == ["Опыт", "Тишина"]

    # Главное отличие от прежнего скрипта: ребёнок сохранён на диск.
    assert report["seed_report"]["saved"] is True
    checkpoint = latest_checkpoint("Child", data_path("checkpoints"))
    assert checkpoint, "ребёнок не сохранился — он жил бы только в памяти"
    from src.core.checkpoint_serializer import CheckpointSerializer

    assert CheckpointSerializer().load(checkpoint)["name"] == "Child"


def test_awaken_from_seed_missing_raises(env):
    with pytest.raises(FileNotFoundError):
        awaken_from_seed(
            _stub_agent(), "нет_такого_семени"
        )


class _StubMentalModels:
    concepts: dict = {}


class _StubAgent:
    """Минимальный агент для проверки отсутствия семени."""

    name = "Stub"
    cycle_count = 0
    mental_models = _StubMentalModels()

    def save_state(self):
        return None

    def save_mental_models(self):
        return None


def _stub_agent():
    return _StubAgent()


def test_awaken_reports_concepts_count(env):
    _write_seed(env, "SeedB", concepts=5)
    agent, report = create_agent(env, "ChildB", seed="SeedB")
    # Из семени пришло ровно 5; остальные — базовые знания новорождённого.
    assert report["seed_report"]["inherited_concepts"] == 5
    assert report["seed_report"]["concepts"] >= 5
    assert len(agent.mental_models.concepts) >= 5