"""Повреждение истории не является разрешением создать новую жизнь."""

import sqlite3
from pathlib import Path

import pytest

from src.app.bootstrap import create_agent, RecoveryRequiredError, checkpoint_candidates
from src.app.paths import setup_environment
from src.core.checkpoint_serializer import CheckpointSerializer, build_state_from_agent


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path / "life"))
    return setup_environment(chdir=False)


def test_corrupt_latest_json_recovers_previous_without_rewriting(env):
    agent, _ = create_agent(env, "Recovery", new=True)
    serializer = CheckpointSerializer(agent.checkpoint_dir)
    state = build_state_from_agent(agent)
    state["cycle_count"] = 10
    serializer.save(state, agent.name, 10)
    bad = Path(agent.checkpoint_dir) / "Recovery_cycle_20.json"
    bad.write_text("{broken", encoding="utf-8")
    before = {p.name: p.read_bytes() for p in Path(agent.checkpoint_dir).iterdir()}
    restored, report = create_agent(env, "Recovery")
    assert restored.cycle_count == 10
    assert report["recovered_from_older"]
    assert len(report["recovery_failures"]) == 1
    assert {p.name: p.read_bytes() for p in Path(agent.checkpoint_dir).iterdir()} == before


def test_all_corrupt_stops_instead_of_new_life(env):
    root = Path(env.data_root) / "checkpoints"
    root.mkdir(exist_ok=True)
    bad = root / "Recovery_cycle_20.json"
    bad.write_text("{broken", encoding="utf-8")
    with pytest.raises(RecoveryRequiredError):
        create_agent(env, "Recovery")
    assert bad.read_text(encoding="utf-8") == "{broken"
    fresh, report = create_agent(env, "Recovery", new=True)
    assert report["source"] == "new"


def test_corrupt_sqlite_snapshot_recovers_older(env):
    agent, _ = create_agent(env, "Recovery", new=True)
    ser = CheckpointSerializer(agent.checkpoint_dir, backend="sqlite")
    state = build_state_from_agent(agent)
    state["cycle_count"] = 10
    ser.save(state, agent.name, 10)
    state["cycle_count"] = 20
    newest = ser.save(state, agent.name, 20)
    database, ident = newest.rsplit("#snapshot=", 1)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE snapshots SET manifest = '{}' WHERE id = ?", (int(ident),))
    restored, report = create_agent(env, "Recovery")
    assert restored.cycle_count == 10
    assert report["recovered_from_older"]


def test_broken_database_requires_explicit_recovery(env):
    root = Path(env.data_root) / "checkpoints"
    root.mkdir(exist_ok=True)
    (root / "life.sqlite3").write_bytes(b"not sqlite")
    with pytest.raises(RecoveryRequiredError):
        create_agent(env, "Recovery")


def test_candidate_listing_ignores_temporary_files(env):
    root = Path(env.data_root) / "checkpoints"
    root.mkdir(exist_ok=True)
    (root / "Recovery_cycle_900.json.tmp").write_text("unfinished")
    assert checkpoint_candidates("Recovery", str(root)) == []
