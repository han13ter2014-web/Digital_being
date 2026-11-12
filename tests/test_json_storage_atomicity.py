"""Сохранность изменяемых JSON-хранилищ при ошибке записи."""

import json
from unittest.mock import Mock

from src.cognition.reflection_engine import ReflectionEngine
from src.core.subsystems.architecture_proposal import ArchitectureProposal
from src.core.subsystems.knowledge_base import KnowledgeSubsystem


def fail_during_dump(data, stream, **kwargs):
    stream.write('{"partial":')
    raise OSError("disk full")


def assert_previous_file_survived(path, previous):
    assert path.read_bytes() == previous
    assert not path.with_name(path.name + ".tmp").exists()


def test_knowledge_subsystem_save_failure_preserves_previous_file(
    tmp_path, monkeypatch
):
    path = tmp_path / "knowledge_base.json"
    subsystem = KnowledgeSubsystem("StorageProbe", knowledge_file=str(path))
    assert subsystem.save()
    previous = path.read_bytes()

    monkeypatch.setattr(json, "dump", fail_during_dump)
    assert not subsystem.save()

    assert_previous_file_survived(path, previous)


def test_reflection_report_save_failure_preserves_history(tmp_path, monkeypatch):
    path = tmp_path / "reflection_report.json"
    engine = ReflectionEngine()
    engine.save_reflection_report({"insight": "прежний отчёт"}, str(path))
    previous = path.read_bytes()

    monkeypatch.setattr(json, "dump", fail_during_dump)
    engine.save_reflection_report({"insight": "новый отчёт"}, str(path))

    assert_previous_file_survived(path, previous)


def make_file_proposal(tmp_path):
    api = ArchitectureProposal(registry=Mock(), proposals_dir=str(tmp_path))
    path = tmp_path / "prop_storage.json"
    path.write_text(
        json.dumps(
            {
                "id": "prop_storage",
                "title": "Проверка хранилища",
                "status": "pending",
                "cycle": 0,
            }
        ),
        encoding="utf-8",
    )
    return api, path


def test_proposal_enrich_failure_preserves_previous_file(tmp_path, monkeypatch):
    api, path = make_file_proposal(tmp_path)
    previous = path.read_bytes()

    monkeypatch.setattr(json, "dump", fail_during_dump)
    result = api.enrich("prop_storage", {"verification": {"passed": True}})

    assert result["enriched"] is False
    assert_previous_file_survived(path, previous)


def test_proposal_decision_failure_preserves_pending_record(tmp_path, monkeypatch):
    api, path = make_file_proposal(tmp_path)
    previous = path.read_bytes()

    monkeypatch.setattr(json, "dump", fail_during_dump)
    result = api.decide("prop_storage", approved=True, note="подтверждаю")

    assert result["decided"] is False
    assert_previous_file_survived(path, previous)
    api.registry.record.assert_not_called()


def test_proposal_creation_failure_leaves_no_pending_record(tmp_path, monkeypatch):
    api = ArchitectureProposal(registry=Mock(), proposals_dir=str(tmp_path))

    def fail_after_complete_dump(data, stream, **kwargs):
        stream.write(json.dumps(data, ensure_ascii=False))
        raise OSError("disk full")

    monkeypatch.setattr(json, "dump", fail_after_complete_dump)
    result = api.propose("method_add", "Не должно появиться", "проверка")

    assert result["created"] is False
    assert api.list_pending() == []
    assert list(tmp_path.glob("*.json")) == []
    assert list(tmp_path.glob("*.tmp")) == []
    api.registry.record.assert_not_called()
