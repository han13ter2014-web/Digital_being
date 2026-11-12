"""Сохранность standalone JSON-файлов агента при ошибке записи."""

import json

from src.core.agent_persistence import (
    _save_knowledge_base_impl,
    save_mental_models_impl,
)


def fail_during_dump(data, stream, **kwargs):
    stream.write('{"partial":')
    raise OSError("disk full")


class _KnowledgeAgent:
    _profile_managed = False
    _last_kb_save_ts = 0.0
    _last_kb_save_size = 0

    def __init__(self, filename):
        self.knowledge_file = str(filename)
        self.knowledge_base = {"прежняя тема": "прежнее знание"}

    def _prune_knowledge_base(self):
        pass


def test_knowledge_save_failure_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "knowledge_base.json"
    agent = _KnowledgeAgent(path)
    _save_knowledge_base_impl(agent)
    previous = path.read_bytes()

    agent.knowledge_base = {"новая тема": "новое знание"}
    agent._last_kb_save_ts = 0.0
    monkeypatch.setattr(json, "dump", fail_during_dump)
    _save_knowledge_base_impl(agent)

    assert path.read_bytes() == previous
    assert not (tmp_path / "knowledge_base.json.tmp").exists()


class _MentalModels:
    def to_storage_dict(self):
        return {"concepts": {"прежнее": {"confidence": 0.5}}}


class _MentalModelsAgent:
    name = "PersistenceProbe"
    mental_models = _MentalModels()


def test_mental_models_save_failure_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "mind" / "mental_models.json"
    agent = _MentalModelsAgent()
    save_mental_models_impl(agent, str(path), data_path=lambda *parts: str(path))
    previous = path.read_bytes()

    monkeypatch.setattr(json, "dump", fail_during_dump)
    save_mental_models_impl(agent, str(path), data_path=lambda *parts: str(path))

    assert path.read_bytes() == previous
    assert not (tmp_path / "mind" / "mental_models.json.tmp").exists()
