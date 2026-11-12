"""Перенос всех действующих форматов в новую базу без изменения источников."""

from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest

from src.delamain.memory import MemoryStore
from src.memory.life_database import LifeDatabase
from src.memory.life_migration import migrate_life_to_sqlite


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def trace(content, associations=None):
    now = datetime(2026, 11, 10, 18, 0, 0).isoformat()
    return {
        "content": content,
        "importance": 0.6,
        "created_at": now,
        "last_accessed": now,
        "access_count": 2,
        "context": "test",
        "associations": list(associations or []),
    }


def make_source(root, life_id, other_life):
    checkpoint_dir = root / "checkpoints" / life_id
    checkpoint_dir.mkdir(parents=True)
    intention = {
        "id": "intention-1", "cycle": 1, "action": "explore", "source": "test",
        "target": "curiosity", "reason": "test", "continuation_of": None,
        "status": "performed", "outcome": None,
    }
    states = []
    for cycle in (1, 2):
        state = {
            "schema_version": 1,
            "life_id": life_id,
            "name": "TestLife",
            "cycle_count": cycle,
            "energy": 100,
            "goals": [],
            "intention_history": [intention] if cycle == 1 else [],
            "saved_at": f"2026-11-10T18:0{cycle}:00+00:00",
        }
        path = checkpoint_dir / f"{life_id}_cycle_{cycle}.json"
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        states.append(state)

    memory_dir = root / "memory"
    memory_dir.mkdir()
    first = trace("first", ["mem-2", "missing"])
    second = trace("second")
    orphan = trace("episodic only")
    (memory_dir / f"{life_id}_long_term.json").write_text(json.dumps({
        "short_term": {"mem-1": first},
        "long_term": {"mem-2": second},
        "episodic": [first, orphan],
        "metadata": {"consolidation_count": 3, "decay_events_count": 1},
    }), encoding="utf-8")

    delamain_dir = root / "delamain"
    delamain_dir.mkdir()
    store = MemoryStore(delamain_dir / "delamain.sqlite3")
    store.record_life_episode(
        life_id=life_id, intention_id="new-intention", action="explore"
    )
    store.record_episode(
        task_id="intention-1", task="digital_life", action="explore",
        metadata={"intention_id": "intention-1", "status": "performed"},
    )
    store.record_life_episode(
        life_id=other_life, intention_id="other", action="explore"
    )
    store.remember_fact("colour", "blue", metadata={"life_id": life_id})
    store.save_goal("Execute", metadata={"life_id": life_id})
    store.record_skill("unowned legacy skill", ["step"])
    store.create_approval(
        task_id="task", task="task", plan=[], metadata={"life_id": life_id}
    )
    store.begin_biography_run(life_id=life_id, run_id="run-1")
    store.close()

    (root / "life_state.json").write_text(json.dumps({
        "state": "alive", "agent_name": "TestLife", "reason": "",
        "changed_at": "2026-11-10T18:00:00", "seed_folder": None,
    }), encoding="utf-8")
    (root / "life_requests.json").write_text(json.dumps({
        "request-1": {
            "request_id": "request-1", "kind": "dream", "agent_name": "TestLife",
            "reason": "test", "created_at": 1.0, "expires_at": 100.0,
            "confirmed": False, "confirmed_at": None,
        }
    }), encoding="utf-8")
    (root / "life_events.log").write_text(
        json.dumps({"ts": "now", "event": "tested", "agent": "TestLife"}) + "\n"
        + json.dumps({"ts": "now", "event": "other", "agent": "Other"}) + "\n",
        encoding="utf-8",
    )
    metrics = root / "metrics"
    metrics.mkdir()
    (metrics / "TestLife_metrics.ndjson").write_text(
        '{"ts":1,"channel":"energy","value":100,"cycle":1}\n'
        '{"ts":2,"channel":"energy","value":99,"cycle":2}\n',
        encoding="utf-8",
    )
    return states


def test_full_migration_roundtrip_quarantine_and_source_preservation(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    life_id = str(uuid4())
    other_life = str(uuid4())
    states = make_source(source, life_id, other_life)
    tracked = [path for path in source.rglob("*") if path.is_file()]
    before = {str(path): digest(path) for path in tracked}

    report = migrate_life_to_sqlite(source, life_id, tmp_path / "destination")

    assert report["counts"]["snapshots"] == 2
    assert report["counts"]["memory_traces"] == 3
    assert report["counts"]["memory_links"] == 1
    assert report["counts"]["delamain_episodes"] == 2
    assert report["counts"]["delamain_facts"] == 1
    assert report["counts"]["delamain_execution_goals"] == 1
    assert report["counts"]["delamain_approvals"] == 1
    assert report["counts"]["delamain_skills"] == 0
    assert report["counts"]["skipped_other_life"] == 1
    assert report["counts"]["life_requests"] == 1
    assert report["counts"]["life_events"] == 1
    assert report["counts"]["metric_samples"] == 2
    assert report["source_files_unchanged"] is True
    assert report["verification"]["ok"] is True
    assert {item["store"] for item in report["quarantine"]} == {
        "memory_links", "delamain.skills", "life_events"
    }

    database = LifeDatabase(report["database"], life_id)
    restored = database.checkpoints.load(report["latest_snapshot_id"])
    assert restored == states[-1]
    assert database.get_meta("latest_snapshot_id") == report["latest_snapshot_id"]
    assert database.get_meta("long_term_memory.consolidation_count") == 3
    with closing(sqlite3.connect(report["database"])) as connection:
        assert connection.execute("SELECT status FROM migration_runs").fetchone()[0] == "verified"
        assert connection.execute("SELECT COUNT(*) FROM facts_fts").fetchone()[0] == 1
        assert connection.execute("SELECT state FROM life_status").fetchone()[0] == "alive"
    assert before == {str(path): digest(path) for path in tracked}

    with pytest.raises(FileExistsError):
        migrate_life_to_sqlite(source, life_id, tmp_path / "destination")


def test_invalid_source_does_not_create_target_database(tmp_path):
    source = tmp_path / "source"
    folder = source / "checkpoints" / (life_id := str(uuid4()))
    folder.mkdir(parents=True)
    (folder / f"{life_id}_cycle_1.json").write_text(json.dumps({
        "schema_version": 1, "life_id": life_id, "name": "Broken",
        "cycle_count": -1, "energy": 100,
    }), encoding="utf-8")
    target = tmp_path / "destination" / "lives" / life_id / "life.sqlite3"

    with pytest.raises(ValueError):
        migrate_life_to_sqlite(source, life_id, tmp_path / "destination")
    assert not target.exists()
