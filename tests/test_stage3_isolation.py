"""Этап 3: тесты не пишут в data/ рабочей копии.

До этапа 3 запуск тестов мог изменить ``data/knowledge_base.json`` и
создать файлы в ``data/memory``, ``data/checkpoints`` и т.п. Теперь все
изменяемые данные идут через ``src.core.paths`` и уважают
``DIGITAL_BEING_DATA_DIR``, который ``tests/conftest.py`` указывает на
временную папку.
"""

import os
from pathlib import Path

import pytest

from src.core.paths import DATA_DIR_ENV, data_dir, data_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def test_session_data_dir_is_temporary_and_exists():
    root = Path(data_dir())
    assert root.is_absolute()
    assert root != (PROJECT_ROOT / "data").resolve()
    assert root.exists()


def test_data_path_honors_env(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    assert data_dir() == str(tmp_path)
    assert data_path("logs", "x.txt") == str(tmp_path / "logs" / "x.txt")


def test_settings_data_dir_follows_env():
    from config.settings import Settings

    assert Path(Settings.DATA_DIR).resolve() == Path(data_dir()).resolve()


def test_buffered_logger_default_is_isolated():
    from src.core.buffered_logger import BufferedLogger

    logger = BufferedLogger(buffer_size=10 ** 6)
    assert _is_inside(Path(logger.log_file), Path(data_dir()))


def test_knowledge_subsystem_defaults_to_isolated_file():
    from src.core.subsystems.knowledge_base import KnowledgeSubsystem

    kb = KnowledgeSubsystem(agent_name="isolation_probe")
    assert _is_inside(Path(kb.knowledge_file), Path(data_dir()))


def test_checkpoint_serializer_default_is_isolated():
    from src.core.checkpoint_serializer import CheckpointSerializer

    serializer = CheckpointSerializer()
    assert _is_inside(Path(serializer.checkpoint_dir), Path(data_dir()))


def test_knowledge_save_does_not_touch_repo_file():
    from src.core.subsystems.knowledge_base import KnowledgeSubsystem

    repo_kb = PROJECT_ROOT / "data" / "knowledge_base.json"
    before = (repo_kb.stat().st_size, repo_kb.stat().st_mtime_ns)

    kb = KnowledgeSubsystem(agent_name="isolation_probe")
    kb.add_definition(
        "что такое изоляция тестов?",
        "Изоляция тестов — это когда тесты пишут данные только во временную папку.",
    )
    kb.save()

    after = (repo_kb.stat().st_size, repo_kb.stat().st_mtime_ns)
    assert before == after, "Тест изменил data/knowledge_base.json рабочей копии"
    assert Path(kb.knowledge_file).exists()


def test_agent_uses_isolated_paths():
    from src.core.agent import DigitalBeing

    agent = DigitalBeing(name="IsolationProbe")
    root = Path(data_dir())

    assert _is_inside(Path(agent.knowledge_file), root)
    assert _is_inside(Path(agent.knowledge_subsystem.knowledge_file), root)
    assert _is_inside(Path(agent.checkpoint_subsystem.checkpoint_dir), root)
    assert _is_inside(Path(agent.long_term_memory.memory_file), root)


def test_repo_data_has_no_artifacts_from_old_tests():
    # Следы старого теста debounce, который писал в рабочую копию.
    assert not (PROJECT_ROOT / "data" / "test_kb_debounce.json").exists()
