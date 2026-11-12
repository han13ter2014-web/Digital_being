"""Явный экспорт выбранного SQLite-снимка жизни в диагностический JSON."""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.life_identity import validate_life_id
from src.memory.life_database import LifeDatabase


def _state_hash(state):
    payload = json.dumps(
        state, ensure_ascii=True, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def export_snapshot(data_root, life_id, output, snapshot_id=None):
    life_id = validate_life_id(life_id)
    database = LifeDatabase(Path(data_root) / "lives" / life_id / "life.sqlite3", life_id)
    snapshot_id = snapshot_id or database.get_meta("latest_snapshot_id")
    if snapshot_id is None:
        snapshot_id = database.checkpoints.latest(life_id)
    if snapshot_id is None:
        raise ValueError("В базе жизни нет снимков")
    state = database.checkpoints.load(snapshot_id)
    if state.get("life_id") != life_id:
        raise ValueError("Снимок принадлежит другой жизни")
    with closing(database.connect(readonly=True)) as connection:
        row = connection.execute(
            "SELECT manifest FROM snapshots WHERE id=?", (snapshot_id,)
        ).fetchone()
    root_hash = json.loads(row[0])["root"]
    exported = dict(state)
    exported["storage_schema_version"] = database.SCHEMA_VERSION
    exported["export_manifest"] = {
        "snapshot_id": snapshot_id,
        "state_sha256": _state_hash(state),
        "snapshot_root_sha256": root_hash,
    }
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(exported, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return {
        "output": str(destination.resolve()),
        "life_id": life_id,
        "snapshot_id": snapshot_id,
        "cycle_count": state.get("cycle_count"),
        "state_sha256": _state_hash(state),
        "snapshot_root_sha256": root_hash,
        "storage_schema_version": database.SCHEMA_VERSION,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--life-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--snapshot-id", type=int)
    args = parser.parse_args()
    report = export_snapshot(args.data_root, args.life_id, args.output, args.snapshot_id)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
