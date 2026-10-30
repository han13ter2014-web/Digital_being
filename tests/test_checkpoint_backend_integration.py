"""Checkpoint backend compatibility at application and runner boundaries."""

import json
from pathlib import Path
from types import SimpleNamespace

from config.simulation_config import SIM_CONFIG
from src.app.bootstrap import latest_checkpoint
from src.core.agent_runner import AgentRunner
from src.core.checkpoint_migrations import SCHEMA_VERSION
from src.core.checkpoint_serializer import CheckpointSerializer


def state(name, cycle):
    return {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "cycle_count": cycle,
        "energy": 87.5,
        "experiences": [{"source": name, "context": "old", "outcome": cycle}],
    }


def test_latest_checkpoint_uses_isolated_sqlite_agent(tmp_path):
    directory = tmp_path / "checkpoints"
    serializer = CheckpointSerializer(checkpoint_dir=directory, backend="sqlite")
    first = serializer.save(state("alice", 1), "alice", 1)
    latest = serializer.save(state("alice", 2), "alice", 2)
    serializer.save(state("bob", 99), "bob", 99)

    assert latest_checkpoint("alice", str(directory)) == latest
    assert latest_checkpoint("bob", str(directory)).endswith("#snapshot=3")
    assert latest_checkpoint("missing", str(directory)) is None
    assert first != latest


def test_legacy_json_restore_then_sqlite_save_preserves_json(tmp_path, monkeypatch):
    directory = tmp_path / "checkpoints"
    directory.mkdir()
    legacy = state("legacy", 7)
    legacy_path = directory / "legacy_cycle_7.json"
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    before = legacy_path.read_bytes()

    from src.core.agent import DigitalBeing

    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", "sqlite")
    agent = DigitalBeing(name="legacy")
    agent.checkpoint_dir = str(directory)
    assert agent.load_state(str(legacy_path)) is True
    assert agent.cycle_count == 7
    assert agent.energy == 87.5
    agent.cycle_count = 8
    sqlite_path = agent.save_state(force=True)
    restored = CheckpointSerializer().load(sqlite_path)

    assert "#snapshot=" in sqlite_path
    assert restored["cycle_count"] == 8
    assert restored["energy"] == 87.5
    assert restored["mental_models"] == agent.mental_models.to_storage_dict()
    assert latest_checkpoint("legacy", str(directory)) == sqlite_path
    assert legacy_path.read_bytes() == before
    assert legacy_path.exists()


def test_json_explicit_backend_still_works(tmp_path):
    serializer = CheckpointSerializer(
        checkpoint_dir=tmp_path, backend="json", max_checkpoints=2
    )
    path = serializer.save(state("json-agent", 4), "json-agent", 4)

    assert Path(path).suffix == ".json"
    assert serializer.load(path) == state("json-agent", 4)
    assert not (tmp_path / "life.sqlite3").exists()


def test_sqlite_runner_does_not_export_mind(tmp_path, monkeypatch):
    """SQLite checkpoints contain mind state; runner must not write a side export."""
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    calls = []
    agent = SimpleNamespace(
        name="integration",
        save_state=lambda force=False: calls.append(("checkpoint", force)),
        save_mental_models=lambda: calls.append(("mind",)),
    )
    runner = AgentRunner.__new__(AgentRunner)
    runner.agent = agent
    runner.name = "integration"
    monkeypatch.setattr("src.core.agent_runner.flush_logs", lambda: None)
    monkeypatch.setattr(SIM_CONFIG, "CHECKPOINT_BACKEND", "sqlite")

    assert runner._save_state_safe() is True
    assert calls == [("checkpoint", True)]
    assert json.loads((tmp_path / "active_profile.json").read_text(encoding="utf-8")) == {
        "name": "integration"
    }
