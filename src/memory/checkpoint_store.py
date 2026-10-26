"""Transactional, content-addressed JSON checkpoints stored in local SQLite.

Saves still scan the complete input state, but unchanged records and list chunks
are shared between snapshots. Pruning removes snapshot metadata; call ``gc`` to
reclaim unreachable blobs without adding a reachability scan to every save.
"""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


class SQLiteCheckpointStore:
    SCHEMA_VERSION = 1
    CHUNK_SIZE = 128

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, self.SCHEMA_VERSION):
                raise ValueError(f"Unsupported checkpoint schema version: {version}")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS blobs "
                "(hash TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS snapshots "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, agent_name TEXT NOT NULL, "
                "cycle INTEGER NOT NULL, saved_at TEXT NOT NULL, manifest TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS snapshots_agent_id "
                "ON snapshots(agent_name, id)"
            )
            connection.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @staticmethod
    def _canonical(value):
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )

    def _put_node(self, connection, node):
        payload = self._canonical(node)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        connection.execute(
            "INSERT OR IGNORE INTO blobs(hash, payload) VALUES (?, ?)",
            (digest, payload),
        )
        return digest

    def _encode(self, connection, value, active, root=False):
        if isinstance(value, (dict, list)):
            identity = id(value)
            if identity in active:
                raise ValueError("Checkpoint state contains a circular reference")
            active.add(identity)
            try:
                if isinstance(value, list):
                    chunks = []
                    for offset in range(0, len(value), self.CHUNK_SIZE):
                        children = [
                            self._encode(connection, item, active)
                            for item in value[offset:offset + self.CHUNK_SIZE]
                        ]
                        chunks.append(self._put_node(
                            connection, {"kind": "chunk", "children": children}
                        ))
                    return self._put_node(
                        connection, {"kind": "list", "children": chunks}
                    )
                if any(not isinstance(key, str) for key in value):
                    raise TypeError("Checkpoint object keys must be strings")
                if not root and not any(
                    isinstance(item, (dict, list)) for item in value.values()
                ):
                    for item in value.values():
                        self._validate_scalar(item)
                    return self._put_node(connection, {"kind": "leaf", "value": value})
                inline = {}
                children = {}
                for key, item in value.items():
                    if root or isinstance(item, (dict, list)):
                        children[key] = self._encode(connection, item, active)
                    else:
                        self._validate_scalar(item)
                        inline[key] = item
                return self._put_node(connection, {
                    "kind": "dict", "value": inline, "children": children,
                })
            finally:
                active.remove(identity)
        self._validate_scalar(value)
        return self._put_node(connection, {"kind": "leaf", "value": value})

    @staticmethod
    def _validate_scalar(value):
        if value is not None and not isinstance(value, (str, bool, int, float)):
            raise TypeError(f"Not a JSON value: {type(value).__name__}")
        if isinstance(value, float) and (value != value or abs(value) == float("inf")):
            raise ValueError("Checkpoint numbers must be finite")

    def save(self, state, agent_name, cycle_count, max_checkpoints=20) -> int:
        """Save atomically and retain the newest checkpoints for this agent only."""
        if not isinstance(state, dict):
            raise TypeError("Checkpoint state must be a dictionary")
        if not isinstance(agent_name, str):
            raise TypeError("agent_name must be a string")
        if isinstance(cycle_count, bool) or not isinstance(cycle_count, int):
            raise TypeError("cycle_count must be an integer")
        if isinstance(max_checkpoints, bool) or not isinstance(max_checkpoints, int):
            raise TypeError("max_checkpoints must be an integer")
        if max_checkpoints < 1:
            raise ValueError("max_checkpoints must be positive")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            root = self._encode(connection, state, set(), root=True)
            cursor = connection.execute(
                "INSERT INTO snapshots(agent_name, cycle, saved_at, manifest) "
                "VALUES (?, ?, ?, ?)",
                (agent_name, cycle_count, datetime.now(timezone.utc).isoformat(),
                 self._canonical({"root": root})),
            )
            snapshot_id = cursor.lastrowid
            connection.execute(
                "DELETE FROM snapshots WHERE agent_name = ? AND id NOT IN "
                "(SELECT id FROM snapshots WHERE agent_name = ? "
                "ORDER BY id DESC LIMIT ?)",
                (agent_name, agent_name, max_checkpoints),
            )
            return snapshot_id

    @staticmethod
    def _check_hash(digest):
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ValueError("Invalid checkpoint blob reference")

    def _manifest_root(self, manifest):
        try:
            value = json.loads(manifest)
            if not isinstance(value, dict) or set(value) != {"root"}:
                raise ValueError("Invalid checkpoint manifest")
            self._check_hash(value["root"])
            return value["root"]
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("Invalid checkpoint manifest") from error

    def _read_node(self, connection, digest):
        self._check_hash(digest)
        row = connection.execute(
            "SELECT payload FROM blobs WHERE hash = ?", (digest,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Missing checkpoint blob: {digest}")
        payload = row[0]
        if (not isinstance(payload, str)
                or hashlib.sha256(payload.encode("utf-8")).hexdigest() != digest):
            raise ValueError(f"Checkpoint blob hash mismatch: {digest}")
        try:
            node = json.loads(payload)
            if not isinstance(node, dict):
                raise ValueError("Invalid checkpoint node")
            kind = node.get("kind")
            if kind == "leaf" and set(node) == {"kind", "value"}:
                values = node["value"]
                if isinstance(values, dict):
                    values = values.values()
                else:
                    values = [values]
                for value in values:
                    self._validate_scalar(value)
            elif kind == "dict" and set(node) == {"kind", "value", "children"}:
                if not isinstance(node["value"], dict) or not isinstance(node["children"], dict):
                    raise ValueError("Invalid checkpoint dictionary")
                if node["value"].keys() & node["children"].keys():
                    raise ValueError("Duplicate checkpoint dictionary keys")
                for value in node["value"].values():
                    self._validate_scalar(value)
            elif kind in ("list", "chunk") and set(node) == {"kind", "children"}:
                if not isinstance(node["children"], list):
                    raise ValueError("Invalid checkpoint list")
                if kind == "chunk" and len(node["children"]) > self.CHUNK_SIZE:
                    raise ValueError("Oversized checkpoint chunk")
            else:
                raise ValueError("Invalid checkpoint node")
            for child in self._references(node):
                self._check_hash(child)
            return node
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"Malformed checkpoint blob: {digest}") from error

    @staticmethod
    def _references(node):
        if node["kind"] == "dict":
            return node["children"].values()
        return node.get("children", [])

    def _decode(self, connection, digest, active, expected=None):
        if digest in active:
            raise ValueError("Circular checkpoint blob references")
        active.add(digest)
        try:
            node = self._read_node(connection, digest)
            kind = node["kind"]
            if expected is not None and kind != expected:
                raise ValueError(f"Expected checkpoint {expected}, got {kind}")
            if kind == "leaf":
                return node["value"]
            if kind == "dict":
                result = dict(node["value"])
                for key, child in node["children"].items():
                    result[key] = self._decode(connection, child, active)
                return result
            if kind == "list":
                result = []
                for child in node["children"]:
                    result.extend(self._decode(connection, child, active, expected="chunk"))
                return result
            return [self._decode(connection, child, active) for child in node["children"]]
        finally:
            active.remove(digest)

    def load(self, snapshot_id) -> dict:
        """Load by global snapshot ID; missing/pruned IDs raise KeyError.

        IDs are not an authorization boundary. Callers enforce access control;
        agent names scope retention and latest-snapshot lookup only.
        """
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT manifest FROM snapshots WHERE id = ?", (snapshot_id,)
            ).fetchone()
            if row is None:
                raise KeyError(snapshot_id)
            return self._decode(
                connection, self._manifest_root(row[0]), set(), expected="dict"
            )

    def latest(self, agent_name) -> int | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT id FROM snapshots WHERE agent_name = ? ORDER BY id DESC LIMIT 1",
                (agent_name,),
            ).fetchone()
            return row[0] if row is not None else None

    def gc(self) -> int:
        """Remove unreachable blobs across all agents, atomically; return count.

        All retained nodes are hash-checked before deletion. Corruption aborts
        collection rather than risking removal of a live snapshot's data.
        """
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            pending = [self._manifest_root(row[0]) for row in connection.execute(
                "SELECT manifest FROM snapshots"
            )]
            reachable = set()
            while pending:
                digest = pending.pop()
                if digest in reachable:
                    continue
                node = self._read_node(connection, digest)
                reachable.add(digest)
                pending.extend(self._references(node))
            connection.execute("CREATE TEMP TABLE reachable(hash TEXT PRIMARY KEY)")
            connection.executemany(
                "INSERT INTO reachable(hash) VALUES (?)", ((key,) for key in reachable)
            )
            cursor = connection.execute(
                "DELETE FROM blobs WHERE hash NOT IN (SELECT hash FROM reachable)"
            )
            return cursor.rowcount
