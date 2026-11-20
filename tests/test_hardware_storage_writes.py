"""Sanitized фактические исходы существующих storage write boundaries."""

from copy import deepcopy
import errno
import json
import sqlite3
from types import SimpleNamespace

import pytest

from src.core.agent_persistence import (
    _save_knowledge_base_impl,
    save_mental_models_impl,
    save_state_impl,
)
from src.core.hardware_interoception import HardwareInteroception
from src.core.hardware_storage_writes import storage_write_error_category


def _empty_write_status():
    return {
        "latest": {
            "operation": None,
            "outcome": "unknown",
            "category": "no_observation",
            "origin": "unknown",
            "cycle": None,
        },
        "sample_count": 0,
    }


def test_storage_write_status_is_sanitized_bounded_and_not_persisted():
    observer = HardwareInteroception()
    assert observer.status()["storage_writes"] == _empty_write_status()
    checkpoint = deepcopy(observer.to_checkpoint())

    for cycle in range(60):
        observer.record_storage_write(
            "knowledge_base", outcome="succeeded", category="written", cycle=cycle
        )

    status = observer.status()["storage_writes"]
    assert status["sample_count"] == 60
    assert status["latest"] == {
        "operation": "knowledge_base",
        "outcome": "succeeded",
        "category": "written",
        "origin": "unknown",
        "cycle": 59,
    }
    assert len(observer.storage_writes.history) == 50
    assert observer.to_checkpoint() == checkpoint

    status["latest"]["operation"] = "private/path"
    assert observer.status()["storage_writes"]["latest"]["operation"] == (
        "knowledge_base"
    )
    restored = HardwareInteroception.from_checkpoint(checkpoint)
    assert restored.status()["storage_writes"] == _empty_write_status()


def test_storage_write_rejects_unknown_context_and_false_success():
    observer = HardwareInteroception()

    observer.record_storage_write(
        "C:/private/knowledge.json",
        outcome="succeeded",
        category="written",
        cycle=1,
    )
    observer.record_storage_write(
        "knowledge_base", outcome="succeeded", category="no_space", cycle=1
    )
    observer.record_storage_write(
        "knowledge_base", outcome="failed", category="written", cycle=1
    )

    assert observer.status()["storage_writes"] == _empty_write_status()


def _sqlite_error(code=None):
    error = sqlite3.OperationalError("private sqlite detail")
    if code is not None:
        error.sqlite_errorcode = code
    return error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PermissionError("private path"), "permission_denied"),
        (ValueError("bad input"), "invalid_input"),
        (OSError(errno.ENOSPC, "private path"), "no_space"),
        (OSError(errno.EIO, "private path"), "io_error"),
        (_sqlite_error(sqlite3.SQLITE_FULL | (5 << 8)), "no_space"),
        (_sqlite_error(sqlite3.SQLITE_PERM), "permission_denied"),
        (_sqlite_error(sqlite3.SQLITE_AUTH), "permission_denied"),
        (_sqlite_error(sqlite3.SQLITE_IOERR), "io_error"),
        (_sqlite_error(), "unknown"),
        (RuntimeError("external detail"), "unknown"),
    ],
)
def test_storage_write_errors_have_distinct_bounded_categories(error, expected):
    assert storage_write_error_category(error) == expected

    observer = HardwareInteroception()
    checkpoint = deepcopy(observer.to_checkpoint())
    observer.record_storage_write(
        "checkpoint", outcome="failed", category=expected, cycle=7
    )

    latest = observer.status()["storage_writes"]["latest"]
    assert latest["outcome"] == "failed"
    assert latest["category"] == expected
    assert latest["origin"] == "unknown"
    assert str(error) not in str(latest)
    assert observer.to_checkpoint() == checkpoint


def test_external_service_refusal_is_not_no_space():
    observer = HardwareInteroception()
    observer.record_storage_write(
        "checkpoint",
        outcome="failed",
        category="external_service_refused",
        cycle=8,
    )

    latest = observer.status()["storage_writes"]["latest"]
    assert latest["category"] == "external_service_refused"
    assert latest["origin"] == "unknown"


class _KnowledgeAgent:
    _profile_managed = False
    _last_kb_save_ts = 0.0
    _last_kb_save_size = 0
    cycle_count = 11

    def __init__(self, filename):
        self.knowledge_file = str(filename)
        self.knowledge_base = {"тема": "знание"}
        self.hardware_interoception = HardwareInteroception()

    def _prune_knowledge_base(self):
        pass


def test_knowledge_save_records_only_actual_write_outcomes(tmp_path, monkeypatch):
    agent = _KnowledgeAgent(tmp_path / "knowledge.json")
    _save_knowledge_base_impl(agent)
    writes = agent.hardware_interoception.status()["storage_writes"]
    assert writes["sample_count"] == 1
    assert writes["latest"]["outcome"] == "succeeded"
    assert writes["latest"]["category"] == "written"

    agent._profile_managed = True
    _save_knowledge_base_impl(agent)
    agent._profile_managed = False
    _save_knowledge_base_impl(agent)  # debounce: фактической записи не было
    assert agent.hardware_interoception.status()["storage_writes"]["sample_count"] == 1

    agent._last_kb_save_ts = 0.0

    def deny(*args, **kwargs):
        raise PermissionError("private knowledge path")

    monkeypatch.setattr(json, "dump", deny)
    _save_knowledge_base_impl(agent)
    latest = agent.hardware_interoception.status()["storage_writes"]["latest"]
    assert latest["outcome"] == "failed"
    assert latest["category"] == "permission_denied"
    assert "private knowledge path" not in str(latest)


class _MentalModels:
    def to_storage_dict(self):
        return {"concepts": {}}


def test_mental_models_save_records_success_and_explicit_no_space(
    tmp_path, monkeypatch
):
    agent = SimpleNamespace(
        name="StorageProbe",
        mental_models=_MentalModels(),
        hardware_interoception=HardwareInteroception(),
        cycle_count=12,
    )
    path = tmp_path / "mind" / "mental_models.json"
    save_mental_models_impl(agent, str(path), data_path=lambda *parts: str(path))
    latest = agent.hardware_interoception.status()["storage_writes"]["latest"]
    assert latest["operation"] == "mental_models"
    assert latest["outcome"] == "succeeded"

    def no_space(*args, **kwargs):
        raise OSError(errno.ENOSPC, "private mental model path")

    monkeypatch.setattr(json, "dump", no_space)
    save_mental_models_impl(agent, str(path), data_path=lambda *parts: str(path))
    latest = agent.hardware_interoception.status()["storage_writes"]["latest"]
    assert latest["outcome"] == "failed"
    assert latest["category"] == "no_space"
    assert "private mental model path" not in str(latest)


def test_checkpoint_and_managed_memory_have_separate_outcomes(monkeypatch, tmp_path):
    import src.core.checkpoint_serializer as serializer_module

    monkeypatch.setattr(serializer_module, "build_state_from_agent", lambda agent: {})
    monkeypatch.setattr("src.core.paths.data_path", lambda *parts: str(tmp_path))
    save_error = None

    class Serializer:
        def __init__(self, **kwargs):
            pass

        def save(self, state, storage_key, cycle_count):
            if save_error is not None:
                raise save_error
            return "checkpoint-reference"

    class Memory:
        def __init__(self):
            self.error = None

        def save(self):
            if self.error is not None:
                raise self.error

    monkeypatch.setattr(serializer_module, "CheckpointSerializer", Serializer)
    memory = Memory()
    agent = SimpleNamespace(
        name="StorageCheckpointProbe",
        life_id="life-id",
        intelligence=0,
        _last_saved_intelligence=0,
        cycle_count=13,
        checkpoint_dir=str(tmp_path),
        _profile_managed=False,
        hardware_interoception=HardwareInteroception(),
        long_term_memory=memory,
    )

    assert save_state_impl(agent, force=True) == "checkpoint-reference"
    latest = agent.hardware_interoception.status()["storage_writes"]["latest"]
    assert latest["operation"] == "checkpoint"
    assert latest["outcome"] == "succeeded"

    save_error = _sqlite_error(sqlite3.SQLITE_FULL)
    with pytest.raises(sqlite3.Error):
        save_state_impl(agent, force=True)
    latest = agent.hardware_interoception.status()["storage_writes"]["latest"]
    assert latest["category"] == "no_space"

    save_error = None
    agent._profile_managed = True
    memory.error = _sqlite_error(sqlite3.SQLITE_PERM)
    with pytest.raises(sqlite3.Error):
        save_state_impl(agent, force=True)
    history = agent.hardware_interoception.storage_writes.history
    assert history[-2]["operation"] == "checkpoint"
    assert history[-2]["outcome"] == "succeeded"
    assert history[-1]["operation"] == "long_term_memory"
    assert history[-1]["category"] == "permission_denied"
    assert "private memory path" not in str(history[-1])
