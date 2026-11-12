"""Однократный живой smoke SQLite-памяти без автономных тиков."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"


def _hash(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _finish(agent):
    registry = getattr(agent, "plugin_registry", None) if agent is not None else None
    if registry is not None:
        registry.teardown_all()


def main():
    from config.simulation_config import SIM_CONFIG
    from src.app.bootstrap import create_agent
    from src.app.paths import setup_environment
    from src.core.subsystem_base import PluginRegistry
    from src.delamain.memory import MemoryStore
    from src.memory.life_database import LifeDatabase
    from src.memory.life_migration import _read_delamain, _table_rows
    from src.memory.long_term_memory import LongTermMemory

    profile = json.loads((DATA / "active_profile.json").read_text(encoding="utf-8"))
    life_id, name = profile["life_id"], profile["name"]
    database_path = DATA / "lives" / life_id / "life.sqlite3"
    legacy_memory = DATA / "memory" / f"{life_id}_long_term.json"
    legacy_delamain = DATA / "delamain" / "delamain.sqlite3"
    watched = (DATA / "active_profile.json", legacy_memory, legacy_delamain)
    hashes_before = {str(path): _hash(path) for path in watched}

    os.environ["DIGITAL_BEING_DATA_DIR"] = str(DATA)
    os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
    os.environ["VOICE_CONSOLE_QUIET"] = "1"
    for variable in (
        "DIGITAL_BEING_TELEGRAM_TOKEN", "DIGITAL_BEING_TELEGRAM_CHAT_ID",
        "DIGITAL_BEING_DISCORD_WEBHOOK_URL",
    ):
        os.environ.pop(variable, None)
    SIM_CONFIG.CHECKPOINT_BACKEND = "sqlite"
    SIM_CONFIG.CHECKPOINT_SQLITE_MIRROR = False

    database = LifeDatabase(database_path, life_id)
    latest_before = database.get_meta("latest_snapshot_id")
    state = database.checkpoints.load(latest_before)
    intention_ids = {
        entry["id"] for entry in state.get("intention_history") or []
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    quarantine = []
    expected, _, skipped_other = _read_delamain(DATA, life_id, intention_ids, quarantine)
    with closing(database.connect(readonly=True)) as connection:
        for table, rows in expected.items():
            assert _table_rows(connection, table) == rows, f"Legacy mismatch: {table}"
        memory_before = connection.execute(
            "SELECT COUNT(*) FROM memory_traces"
        ).fetchone()[0]
    assert not quarantine, quarantine
    assert skipped_other == 0, skipped_other

    agent = None
    restored = None
    marker = f"sqlite runtime smoke: snapshot {latest_before}"
    episode_task_id = f"sqlite-runtime-smoke-{latest_before}"
    try:
        PluginRegistry.reset_global()
        env = setup_environment(chdir=False, console=False)
        agent, report = create_agent(env, name, expected_life_id=life_id)
        assert report["source"] == "checkpoint"
        assert agent.cycle_count == state["cycle_count"]
        assert agent.long_term_memory.life_id == life_id
        assert agent.delamain.life_id == life_id
        assert agent.delamain.db_path == database_path
        runtime = agent.delamain._ensure_runtime()
        assert runtime.memory.db_path == database_path
        assert runtime.memory.life_id == life_id

        agent.long_term_memory.store(
            marker, importance=0.4, context="sqlite_runtime_smoke",
            memory_type="semantic",
        )
        runtime.memory.record_episode(
            task_id=episode_task_id, task="sqlite_runtime_smoke",
            action="storage_roundtrip", ok=True, output={"snapshot": latest_before},
            metadata={"life_id": life_id},
        )
        agent.save_state(force=True)
        latest_after = database.get_meta("latest_snapshot_id")
        assert latest_after > latest_before
        _finish(agent)
        agent = None

        reopened_memory = LongTermMemory(name, life_id=life_id)
        assert any(
            trace.content == marker
            for trace in reopened_memory._short_term.values()
        ), "Новый след LongTermMemory не восстановлен"
        with MemoryStore(database_path, life_id=life_id) as store:
            episodes = store.recent_episodes(task_id=episode_task_id)
            assert len(episodes) == 1
            assert episodes[0]["action"] == "storage_roundtrip"
            assert episodes[0]["metadata"]["life_id"] == life_id

        PluginRegistry.reset_global()
        restored, restored_report = create_agent(env, name, expected_life_id=life_id)
        assert restored_report["source"] == "checkpoint"
        assert restored.life_id == life_id
        assert restored.cycle_count == state["cycle_count"]
        assert restored.delamain.db_path == database_path
        assert any(
            trace.content == marker
            for trace in restored.long_term_memory._short_term.values()
        )
        verification = LifeDatabase(database_path, life_id).verify()
        assert verification["ok"] is True, verification
        with closing(sqlite3.connect(database_path)) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM memory_traces"
            ).fetchone()[0] == memory_before + 1
            assert connection.execute(
                "SELECT COUNT(*) FROM episodes WHERE task_id = ?", (episode_task_id,)
            ).fetchone()[0] == 1

        hashes_after = {str(path): _hash(path) for path in watched}
        assert hashes_after == hashes_before, "Legacy-файлы изменились"
        result = {
            "life_id": life_id,
            "name": restored.name,
            "cycle_count": restored.cycle_count,
            "autonomous_ticks": 0,
            "legacy_delamain_rows_exact_match_before_write": True,
            "snapshot_before": latest_before,
            "snapshot_after": latest_after,
            "long_term_memory_roundtrip": True,
            "delamain_episode_roundtrip": True,
            "full_agent_reload": True,
            "legacy_files_unchanged": True,
            "verification": verification,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        _finish(restored)
        _finish(agent)
        from src.core.buffered_logger import flush_logs
        flush_logs()


if __name__ == "__main__":
    main()
