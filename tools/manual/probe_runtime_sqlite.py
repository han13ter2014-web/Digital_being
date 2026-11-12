"""Проверка Core + LongTermMemory + Delamain на копии живой базы.

Создаёт проверенный backup, но не запускает автономные циклы и не пишет в
живую базу. Все изменения выполняются во временном каталоге ``tmp/``.
"""

from contextlib import closing
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"
ITERATIONS = 20


def _hash(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _copy_sqlite(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(
        source.resolve().as_uri() + "?mode=ro", uri=True, timeout=30
    )) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)


def _counts(path):
    with closing(sqlite3.connect(path)) as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("snapshots", "memory_traces", "episodes", "facts")
        }


def main():
    from src.memory.profile_backup import create_backup, verify_backup

    profile = json.loads((DATA / "active_profile.json").read_text(encoding="utf-8"))
    life_id = profile["life_id"]
    live_db = DATA / "lives" / life_id / "life.sqlite3"
    legacy_memory = DATA / "memory" / f"{life_id}_long_term.json"
    legacy_delamain = DATA / "delamain" / "delamain.sqlite3"
    watched = (DATA / "active_profile.json", live_db, legacy_memory, legacy_delamain)
    hashes_before = {str(path): _hash(path) for path in watched}

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = Path(create_backup(DATA, DATA / "snapshots" / f"runtime_before_sqlite_{stamp}"))
    verify_backup(backup)

    temporary_parent = ROOT / "tmp"
    temporary_parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="runtime_sqlite_", dir=temporary_parent) as isolated:
        data_root = Path(isolated) / "data"
        copied_db = data_root / "lives" / life_id / "life.sqlite3"
        _copy_sqlite(live_db, copied_db)
        os.environ["DIGITAL_BEING_DATA_DIR"] = str(data_root)
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"

        from src.delamain.memory import MemoryStore
        from src.memory.life_database import LifeDatabase
        from src.memory.long_term_memory import LongTermMemory

        database = LifeDatabase(copied_db, life_id)
        latest_id = database.get_meta("latest_snapshot_id")
        state = database.checkpoints.load(latest_id)
        initial = _counts(copied_db)
        memory = LongTermMemory(profile["name"], life_id=life_id)
        writer_store = MemoryStore(copied_db, life_id=life_id)
        reader_store = MemoryStore(copied_db, life_id=life_id)
        barrier = threading.Barrier(4)
        errors = []

        def guarded(action):
            try:
                barrier.wait(timeout=30)
                action()
            except BaseException as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

        def write_checkpoints():
            local = LifeDatabase(copied_db, life_id)
            for _ in range(ITERATIONS):
                snapshot_id = local.save_checkpoint(
                    state, int(state["cycle_count"]), max_checkpoints=1000
                )
                assert local.checkpoints.load(snapshot_id) == state

        def write_long_term_memory():
            for index in range(ITERATIONS):
                memory.store(
                    f"concurrent runtime trace {index}", importance=0.4,
                    context="isolated_sqlite_probe", memory_type="semantic",
                )
                memory.save()

        def write_delamain():
            for index in range(ITERATIONS):
                writer_store.record_episode(
                    task_id=f"runtime-probe-{index}", task="sqlite_probe",
                    action="concurrent_write", ok=True, output={"index": index},
                    metadata={"life_id": life_id},
                )
                writer_store.remember_fact(
                    "runtime_probe", f"value_{index}", source="isolated", confidence=0.9,
                    metadata={"life_id": life_id},
                )

        def read_delamain_and_core():
            local = LifeDatabase(copied_db, life_id)
            for _ in range(ITERATIONS):
                reader_store.recent_episodes(limit=5)
                reader_store.recall_facts("runtime_probe", limit=5)
                current = local.get_meta("latest_snapshot_id")
                assert local.checkpoints.load(current)["life_id"] == life_id

        threads = [
            threading.Thread(target=guarded, args=(action,), name=name)
            for name, action in (
                ("core-writer", write_checkpoints),
                ("ltm-writer", write_long_term_memory),
                ("delamain-writer", write_delamain),
                ("reader", read_delamain_and_core),
            )
        ]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=180)
            assert all(not thread.is_alive() for thread in threads), "Проверочный поток завис"
            assert not errors, errors
        finally:
            writer_store.close()
            reader_store.close()

        final = _counts(copied_db)
        assert final["snapshots"] == initial["snapshots"] + ITERATIONS
        assert final["memory_traces"] == initial["memory_traces"] + ITERATIONS
        assert final["episodes"] == initial["episodes"] + ITERATIONS
        assert final["facts"] == initial["facts"] + ITERATIONS

        restored_memory = LongTermMemory(profile["name"], life_id=life_id)
        restored_contents = {
            trace.content for trace in restored_memory._short_term.values()
        } | {trace.content for trace in restored_memory._long_term.values()}
        assert all(
            f"concurrent runtime trace {index}" in restored_contents
            for index in range(ITERATIONS)
        )
        with MemoryStore(copied_db, life_id=life_id) as reopened:
            assert reopened.recall_facts("value_19", limit=10)[0]["value"] == "value_19"
        verification = LifeDatabase(copied_db, life_id).verify()
        assert verification["ok"] is True, verification

        hashes_after = {str(path): _hash(path) for path in watched}
        assert hashes_after == hashes_before, "Живые хранилища изменились во время probe"
        report = {
            "life_id": life_id,
            "backup": str(backup),
            "backup_manifest_valid": True,
            "iterations_per_writer": ITERATIONS,
            "concurrent_threads": 4,
            "initial_counts": initial,
            "final_counts": final,
            "all_new_rows_reopened": True,
            "verification": verification,
            "live_files_unchanged": True,
            "temporary_copy_removed_on_exit": True,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        os.environ["DIGITAL_BEING_DATA_DIR"] = str(DATA)


if __name__ == "__main__":
    main()
