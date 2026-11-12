"""Smoke этапа 5B на копии текущей жизни, без автономных тиков."""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"


def _hash(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _finish(agent):
    if agent is not None:
        registry = getattr(agent, "plugin_registry", None)
        if registry is not None:
            registry.teardown_all()


class Bus:
    def subscribe(self, name, callback):
        pass


def main() -> int:
    profile = json.loads((DATA / "active_profile.json").read_text(encoding="utf-8"))
    life_id, name = profile["life_id"], profile["name"]
    source = DATA / "lives" / life_id / "life.sqlite3"
    source_legacy = (
        DATA / "active_profile.json",
        DATA / "knowledge_base.json",
        DATA / "logs" / "dialogue_cycles.jsonl",
    )
    before = {str(path): _hash(path) for path in (source, *source_legacy)}
    agent = restored = None

    with tempfile.TemporaryDirectory(prefix=".stage5b_", dir=ROOT) as temporary:
        root = Path(temporary)
        target = root / "lives" / life_id / "life.sqlite3"
        target.parent.mkdir(parents=True)
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst)
        for path in source_legacy[1:]:
            if path.is_file():
                destination = root / path.relative_to(DATA)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
        copied_legacy = [root / path.relative_to(DATA) for path in source_legacy]
        copied_before = {str(path): _hash(path) for path in copied_legacy}

        os.environ["DIGITAL_BEING_DATA_DIR"] = str(root)
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        os.environ["VOICE_CONSOLE_QUIET"] = "1"
        try:
            from src.app.bootstrap import create_agent
            from src.app.paths import setup_environment
            from src.core.agent_runner import AgentRunner
            from src.core.subsystem_base import PluginRegistry
            from src.memory.life_database import LifeDatabase

            database = LifeDatabase(target, life_id)
            latest_before = database.get_meta("latest_snapshot_id")
            state = database.checkpoints.load(latest_before)
            with closing(database.connect(readonly=True)) as connection:
                dialogue_before = connection.execute(
                    "SELECT COUNT(*) FROM dialogue_cycles"
                ).fetchone()[0]

            PluginRegistry.reset_global()
            env = setup_environment(chdir=False, console=False)
            agent, report = create_agent(env, name, expected_life_id=life_id)
            assert report["source"] == "checkpoint"
            assert agent.knowledge_base == state["knowledge_base"]
            marker = "что такое проверка хранилища?"
            definition = "Проверка хранилища подтверждает восстановление знаний из SQLite-снимка."
            agent.knowledge_base[marker] = definition
            agent._save_knowledge_base()
            assert _hash(root / "knowledge_base.json") == copied_before[str(root / "knowledge_base.json")]
            agent.save_state(force=True)
            _finish(agent)
            agent = None

            PluginRegistry.reset_global()
            restored, restored_report = create_agent(env, name, expected_life_id=life_id)
            assert restored_report["source"] == "checkpoint"
            assert restored.knowledge_base[marker] == definition
            assert restored.cycle_count == state["cycle_count"]

            AgentRunner(restored, Bus())._save_dialogue_cycle_snapshot()
            AgentRunner(restored, Bus())._save_dialogue_cycle_snapshot()
            reopened = LifeDatabase(target, life_id)
            with closing(reopened.connect(readonly=True)) as connection:
                rows = connection.execute(
                    "SELECT payload_json FROM dialogue_cycles ORDER BY id"
                ).fetchall()
            assert len(rows) == dialogue_before + 2
            payloads = [json.loads(row[0]) for row in rows[-2:]]
            assert all(item["agent_name"] == name for item in payloads)
            assert all(item["cycle"] == state["cycle_count"] for item in payloads)
            assert all("dialogue" in item and "ledger" in item for item in payloads)
            assert _hash(root / "logs" / "dialogue_cycles.jsonl") == copied_before[
                str(root / "logs" / "dialogue_cycles.jsonl")
            ]
            verification = reopened.verify()
            assert verification["ok"] is True, verification
            assert {str(path): _hash(path) for path in copied_legacy} == copied_before
            result = {
                "ok": True,
                "life_id": life_id,
                "cycle_count": restored.cycle_count,
                "storage_schema_version": reopened.SCHEMA_VERSION,
                "knowledge_snapshot_roundtrip": True,
                "dialogue_rows_added": 2,
                "legacy_files_unchanged": True,
                "source_files_unchanged": None,
                "autonomous_ticks": 0,
            }
        finally:
            _finish(restored)
            _finish(agent)
            from src.core.buffered_logger import flush_logs
            flush_logs()
            # setup_environment открывает RotatingFileHandler. Закрываем его
            # до удаления временной копии на Windows.
            import logging
            loggers = [logging.getLogger()]
            loggers.extend(
                item for item in logging.getLogger().manager.loggerDict.values()
                if isinstance(item, logging.Logger)
            )
            for item in loggers:
                for handler in list(item.handlers):
                    handler.flush()
                    handler.close()
                    item.removeHandler(handler)

    after = {str(path): _hash(path) for path in (source, *source_legacy)}
    assert before == after, "Исходные файлы изменились"
    result["source_files_unchanged"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
