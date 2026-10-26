import hashlib
import json
import sqlite3

import pytest

from src.memory.checkpoint_store import SQLiteCheckpointStore


@pytest.fixture
def store(tmp_path):
    return SQLiteCheckpointStore(tmp_path / "memory" / "checkpoints.sqlite3")


def rows(store, query, parameters=()):
    with sqlite3.connect(store.path) as connection:
        return connection.execute(query, parameters).fetchall()


def test_roundtrip_and_reopen(store):
    state = {
        "experiences": [
            {"id": 1, "text": "Привет 🌍", "reward": 0.25, "ok": True},
            {"nested": {"tags": [None, False, 42, -0.5, ""]}},
        ],
        "mental_models": {"concepts": {"one": {"name": "one", "score": 2}},
                          "claims": [{"claim": "a", "confidence": 0.8}]},
        "empty_list": [], "empty_dict": {}, "nothing": None,
        "boolean": False, "number": 3.0, "text": "hello",
    }
    assert store.latest("agent") is None
    snapshot = store.save(state, "agent", 7)
    assert isinstance(snapshot, int)
    assert store.load(snapshot) == state
    restored = SQLiteCheckpointStore(store.path)
    assert restored.latest("agent") == snapshot
    assert restored.load(snapshot) == state
    assert rows(store, "PRAGMA user_version") == [(1,)]
    assert rows(store, "PRAGMA journal_mode") == [("wal",)]
    metadata = rows(store, "SELECT agent_name, cycle, saved_at, manifest FROM snapshots")[0]
    assert metadata[:2] == ("agent", 7)
    assert "+00:00" in metadata[2]
    assert set(json.loads(metadata[3])) == {"root"}
    loaded = restored.load(snapshot)
    loaded["experiences"].clear()
    assert restored.load(snapshot) == state


def test_canonical_dedup_and_no_mutable_aliases(store):
    shared = {"a": 1, "b": "two"}
    first = store.save({"left": shared, "right": shared}, "a", 1)
    before = rows(store, "SELECT COUNT(*) FROM blobs")[0][0]
    second = store.save({"right": {"b": "two", "a": 1}, "left": shared}, "a", 2)
    assert rows(store, "SELECT COUNT(*) FROM blobs")[0][0] == before
    assert store.load(first) == store.load(second)
    loaded = store.load(first)
    loaded["left"]["a"] = 99
    assert loaded["right"]["a"] == 1


def test_twenty_growing_snapshots_share_records_and_full_chunks(store):
    experiences = [{"id": index, "text": "x" * 512} for index in range(512)]
    snapshots = []
    for cycle in range(20):
        if cycle:
            experiences.append({"id": 511 + cycle, "text": "x" * 512})
        snapshots.append(store.save({"experiences": experiences}, "agent", cycle))
    assert len(rows(store, "SELECT id FROM snapshots")) == 20
    blobs = rows(store, "SELECT payload FROM blobs")
    nodes = [json.loads(row[0]) for row in blobs]
    records = [node for node in nodes if node["kind"] == "leaf"]
    assert len(records) == 531
    assert sum(node["kind"] == "chunk" for node in nodes) == 4 + 19
    assert len(blobs) == 531 + 23 + 20 + 20
    assert sum(len(row[0]) for row in blobs) < 600_000
    for cycle, snapshot in enumerate(snapshots):
        assert len(store.load(snapshot)["experiences"]) == 512 + cycle


def test_atomic_rollback_after_blobs_inserted(store, monkeypatch):
    original = store.save({"experiences": [{"id": 1}]}, "agent", 1)
    before = rows(store, "SELECT * FROM blobs ORDER BY hash")
    put = store._put_node
    calls = 0

    def fail(connection, node):
        nonlocal calls
        result = put(connection, node)
        calls += 1
        if calls == 3:
            raise RuntimeError("injected write failure")
        return result

    monkeypatch.setattr(store, "_put_node", fail)
    with pytest.raises(RuntimeError, match="injected"):
        store.save({"experiences": [{"id": 2}, {"id": 3}]}, "agent", 2, 1)
    assert store.latest("agent") == original
    assert rows(store, "SELECT * FROM blobs ORDER BY hash") == before
    assert store.load(original) == {"experiences": [{"id": 1}]}


def test_prune_failure_rolls_back_snapshot_and_blobs(store):
    original = store.save({"value": "original"}, "agent", 0)
    before = rows(store, "SELECT * FROM blobs ORDER BY hash")
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_prune BEFORE DELETE ON snapshots "
            "BEGIN SELECT RAISE(ABORT, 'injected prune failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="injected prune failure"):
        store.save({"value": "new"}, "agent", 1, 1)
    assert store.latest("agent") == original
    assert rows(store, "SELECT * FROM blobs ORDER BY hash") == before


def test_pruning_is_per_agent_and_gc_preserves_all_agents(store):
    shared = {"experiences": [{"id": 1, "text": "shared"}]}
    other = store.save(shared, "other", 100)
    first = store.save(shared, "agent", 1, 2)
    second = store.save({"only": "orphan after pruning"}, "agent", 2, 2)
    third = store.save({"value": 3}, "agent", 3, 2)
    fourth = store.save({"value": 4}, "agent", 4, 2)
    assert store.latest("agent") == fourth
    assert store.latest("other") == other
    for snapshot in (first, second):
        with pytest.raises(KeyError):
            store.load(snapshot)
    assert store.gc() > 0
    assert store.gc() == 0
    assert store.load(other) == shared
    assert store.load(third) == {"value": 3}
    assert store.load(fourth) == {"value": 4}
    assert rows(store, "SELECT agent_name, COUNT(*) FROM snapshots GROUP BY agent_name") == [
        ("agent", 2), ("other", 1),
    ]
    fifth = store.save({}, "agent", 5, 1)
    assert fifth > fourth
    assert store.gc() > 0
    assert store.load(other) == shared
    assert store.load(fifth) == {}


def test_missing_snapshot(store):
    with pytest.raises(KeyError):
        store.load(123)


@pytest.mark.parametrize("damage", ["missing", "modified", "malformed", "shape"])
def test_corrupt_blob_raises_value_error(store, damage):
    snapshot = store.save({"value": "kept"}, "agent", 1)
    root = json.loads(rows(store, "SELECT manifest FROM snapshots")[0][0])["root"]
    with sqlite3.connect(store.path) as connection:
        if damage == "missing":
            connection.execute("DELETE FROM blobs WHERE hash = ?", (root,))
        elif damage == "modified":
            connection.execute("UPDATE blobs SET payload = '{}' WHERE hash = ?", (root,))
        else:
            payload = "not JSON" if damage == "malformed" else '{"kind":"dict","children":[]}'
            digest = hashlib.sha256(payload.encode()).hexdigest()
            connection.execute("INSERT INTO blobs VALUES (?, ?)", (digest, payload))
            connection.execute(
                "UPDATE snapshots SET manifest = ? WHERE id = ?",
                (json.dumps({"root": digest}), snapshot),
            )
    before = rows(store, "SELECT COUNT(*) FROM blobs")
    with pytest.raises(ValueError):
        store.load(snapshot)
    with pytest.raises(ValueError):
        store.gc()
    assert rows(store, "SELECT COUNT(*) FROM blobs") == before


@pytest.mark.parametrize("manifest", ['not JSON', '[]', '{}', '{"root":"invalid"}'])
def test_malformed_manifest(store, manifest):
    snapshot = store.save({}, "agent", 0)
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE snapshots SET manifest = ?", (manifest,))
    with pytest.raises(ValueError):
        store.load(snapshot)


def test_newer_schema_rejected_without_mutation(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=2")
    with pytest.raises(ValueError, match="schema version: 2"):
        SQLiteCheckpointStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
        assert connection.execute("SELECT name FROM sqlite_master").fetchall() == []


@pytest.mark.parametrize("state,error", [
    ([], TypeError), ({1: "not a JSON key"}, TypeError),
    ({"bad": object()}, TypeError), ({"bad": (1, 2)}, TypeError),
    ({"bad": float("nan")}, ValueError), ({"bad": float("inf")}, ValueError),
])
def test_invalid_state_is_not_committed(store, state, error):
    with pytest.raises(error):
        store.save(state, "agent", 1)
    assert store.latest("agent") is None
    assert rows(store, "SELECT COUNT(*) FROM blobs") == [(0,)]


def test_circular_state_is_not_committed(store):
    state = {"first": "would otherwise be inserted"}
    state["cycle"] = state
    with pytest.raises(ValueError, match="circular"):
        store.save(state, "agent", 0)
    assert rows(store, "SELECT COUNT(*) FROM blobs") == [(0,)]


@pytest.mark.parametrize("limit,error", [(0, ValueError), (-1, ValueError),
                                         (True, TypeError), (1.5, TypeError)])
def test_invalid_retention(store, limit, error):
    with pytest.raises(error):
        store.save({}, "agent", 0, limit)
    assert store.latest("agent") is None
