"""Compare JSON and SQLite checkpoint storage without touching live agent data.

Run from any directory: python tools/manual/checkpoint_storage_measure.py --report PATH
"""

import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from time import perf_counter


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def record(index):
    def text(field):
        seed = f"{field}:{index}:"
        return seed + hashlib.sha512(seed.encode()).hexdigest() + " observation"

    return {
        "id": index,
        "source": text("source"),
        "context": text("context"),
        "outcome": text("outcome"),
    }


def inventory(directory):
    files = {
        str(path.relative_to(directory)): path.stat().st_size
        for path in sorted(directory.rglob("*")) if path.is_file()
    }
    return {"total_bytes": sum(files.values()), "files_bytes": files,
            "wal_bytes": sum(size for name, size in files.items() if name.endswith("-wal")),
            "shm_bytes": sum(size for name, size in files.items() if name.endswith("-shm"))}


def measure(root, records, snapshots):
    from src.core.checkpoint_migrations import SCHEMA_VERSION
    from src.core.checkpoint_serializer import CheckpointSerializer

    serializers = {
        backend: CheckpointSerializer(
            checkpoint_dir=str(root / backend), backend=backend,
            max_checkpoints=snapshots, compress=False,
        ) for backend in ("json", "sqlite")
    }
    results = {backend: {"save_seconds": 0.0, "load_seconds": 0.0}
               for backend in serializers}
    paths = {backend: [] for backend in serializers}
    state = {"schema_version": SCHEMA_VERSION, "name": "StorageMeasure",
             "energy": 100.0, "cycle_count": 0,
             "experiences": [record(index) for index in range(records)]}
    oldest = None
    for cycle in range(snapshots):
        if cycle:
            state["experiences"].append(record(records + cycle - 1))
        state["cycle_count"] = cycle
        if cycle == 0:
            oldest = json.loads(json.dumps(state))
        for backend, serializer in serializers.items():
            started = perf_counter()
            path = serializer.save(state, state["name"], cycle)
            results[backend]["save_seconds"] += perf_counter() - started
            paths[backend].append(path)

    equality = {}
    loaded_edges = {backend: {} for backend in serializers}
    for backend, serializer in serializers.items():
        results[backend]["storage_after_saves"] = inventory(root / backend)
        for cycle, path in enumerate(paths[backend]):
            started = perf_counter()
            loaded = serializer.load(path)
            results[backend]["load_seconds"] += perf_counter() - started
            if cycle in (0, snapshots - 1):
                loaded_edges[backend][cycle] = loaded
        results[backend]["storage_after_loads"] = inventory(root / backend)
        results[backend]["oldest_equal_input"] = loaded_edges[backend][0] == oldest
        results[backend]["final_equal_input"] = loaded_edges[backend][snapshots - 1] == state

    for label, cycle in (("oldest", 0), ("final", snapshots - 1)):
        equality[f"{label}_backends_equal"] = (
            loaded_edges["json"][cycle] == loaded_edges["sqlite"][cycle]
        )
    database = root / "sqlite" / "life.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        kinds = Counter()
        record_rows = 0
        for (payload,) in connection.execute("SELECT payload FROM blobs"):
            node = json.loads(payload)
            kinds[node["kind"]] += 1
            value = node.get("value")
            if node["kind"] == "leaf" and isinstance(value, dict) and "source" in value:
                record_rows += 1
        snapshot_rows = connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    results["sqlite"]["counts"] = {
        "snapshots": snapshot_rows, "blobs": sum(kinds.values()),
        "experience_rows": record_rows, "blob_kinds": dict(kinds),
        "total_table_rows": snapshot_rows + sum(kinds.values()),
    }
    results["json"]["counts"] = {
        "snapshots": len(paths["json"]), "blobs": 0,
        "experience_records_across_files": sum(records + cycle for cycle in range(snapshots)),
        "final_experience_records": len(state["experiences"]),
    }
    json_bytes = results["json"]["storage_after_saves"]["total_bytes"]
    sqlite_bytes = results["sqlite"]["storage_after_saves"]["total_bytes"]
    return {
        "records": records, "snapshots": snapshots,
        "method": "Identical deterministic flat experience records; 100-200 characters per "
                  "unique source/context/outcome field. First snapshot has N records; "
                  "append one before each subsequent snapshot. Timings cover serializer "
                  "calls only; load_seconds sums all snapshot loads. File sizes include "
                  "all backend files, including any WAL/SHM present after closed connections. "
                  "No forced WAL checkpoint, GC, or VACUUM; JSON is uncompressed.",
        "backends": results, "equality": equality,
        "json_to_sqlite_bytes_ratio": json_bytes / sqlite_bytes,
        "all_equal": all(equality.values()) and all(
            result["oldest_equal_input"] and result["final_equal_input"]
            for result in results.values()
        ),
    }


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=positive_int, default=10000)
    parser.add_argument("--snapshots", type=positive_int, default=20)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(PROJECT_ROOT))
    approved_temp = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp" / "opencode"
    temp_parent = approved_temp if approved_temp.is_dir() else Path(tempfile.gettempdir())
    previous_data = os.environ.get("DIGITAL_BEING_DATA_DIR")
    with tempfile.TemporaryDirectory(prefix="checkpoint_measure_", dir=temp_parent) as temporary:
        os.environ["DIGITAL_BEING_DATA_DIR"] = str(Path(temporary) / "data")
        try:
            report = measure(Path(temporary), args.records, args.snapshots)
        finally:
            if previous_data is None:
                os.environ.pop("DIGITAL_BEING_DATA_DIR", None)
            else:
                os.environ["DIGITAL_BEING_DATA_DIR"] = previous_data
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {args.report.resolve()}")
    print(f"JSON / SQLite bytes: {report['json_to_sqlite_bytes_ratio']:.2f}x")
    print(f"All equality checks: {report['all_equal']}")
    return 0 if report["all_equal"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
