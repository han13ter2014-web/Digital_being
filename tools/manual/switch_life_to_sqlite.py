"""Финальный снимок, миграция и доказательство восстановления активной жизни.

Не меняет ``CHECKPOINT_BACKEND`` в коде: переключение конфигурации выполняется
только после успешного завершения этого сценария.
"""

from contextlib import redirect_stdout
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"


def _state_hash(state):
    payload = json.dumps(
        state, ensure_ascii=True, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _finish(agent):
    registry = getattr(agent, "plugin_registry", None) if agent is not None else None
    if registry is not None:
        registry.teardown_all()


def main():
    os.environ["DIGITAL_BEING_DATA_DIR"] = str(DATA)
    os.environ["VOICE_CONSOLE_QUIET"] = "1"
    for name in (
        "DIGITAL_BEING_TELEGRAM_TOKEN", "DIGITAL_BEING_TELEGRAM_CHAT_ID",
        "DIGITAL_BEING_DISCORD_WEBHOOK_URL",
    ):
        os.environ.pop(name, None)

    from config.simulation_config import SIM_CONFIG
    from src.app.bootstrap import create_agent
    from src.app.paths import setup_environment
    from src.core.checkpoint_serializer import CheckpointSerializer
    from src.core.subsystem_base import PluginRegistry
    from src.memory.life_database import LifeDatabase
    from src.memory.life_migration import migrate_life_to_sqlite
    from src.memory.profile_backup import create_backup, restore_backup
    from tools.manual.export_life_snapshot import export_snapshot

    profile = json.loads((DATA / "active_profile.json").read_text(encoding="utf-8"))
    life_id = profile["life_id"]
    name = profile["name"]
    target = DATA / "lives" / life_id / "life.sqlite3"
    if target.exists():
        raise FileExistsError(f"База уже существует; повторная миграция запрещена: {target}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pre_backup = create_backup(DATA, DATA / "snapshots" / f"json_before_sqlite_{stamp}")

    SIM_CONFIG.CHECKPOINT_BACKEND = "json"
    SIM_CONFIG.CHECKPOINT_SQLITE_MIRROR = False
    env = setup_environment(chdir=False, console=False)
    agent = None
    restored = None
    try:
        agent, load_report = create_agent(env, name, expected_life_id=life_id)
        if load_report["source"] != "checkpoint":
            raise RuntimeError("Финальный снимок не создан: жизнь не восстановлена из истории")
        searcher = getattr(agent, "web_searcher", None)
        if searcher is not None:
            searcher.toggle(False)
        final_json = agent.save_state(force=True)
        if not final_json.endswith(".json"):
            raise RuntimeError("Финальный снимок должен быть JSON")
        final_state = CheckpointSerializer().load(final_json)
        final_hash = _state_hash(final_state)

        migration = migrate_life_to_sqlite(DATA, life_id, DATA)
        database = LifeDatabase(target, life_id)
        latest_id = database.get_meta("latest_snapshot_id")
        sqlite_state = database.checkpoints.load(latest_id)
        if sqlite_state != final_state or _state_hash(sqlite_state) != final_hash:
            raise RuntimeError("Последний SQLite-снимок не совпал с финальным JSON")
        if not database.verify()["ok"]:
            raise RuntimeError("Итоговая база не прошла проверку целостности")

        export = export_snapshot(
            DATA, life_id,
            DATA / "lives" / life_id / "exports" / f"final_cycle_{agent.cycle_count}.json",
            latest_id,
        )
        final_backup = create_backup(
            DATA, DATA / "snapshots" / f"sqlite_verified_{stamp}"
        )

        temporary_parent = ROOT / "tmp"
        temporary_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="sqlite_restore_", dir=temporary_parent) as isolated:
            restored_root = Path(isolated) / "restored"
            restore_backup(final_backup, restored_root)
            _finish(agent)
            agent = None
            PluginRegistry.reset_global()
            os.environ["DIGITAL_BEING_DATA_DIR"] = str(restored_root)
            SIM_CONFIG.CHECKPOINT_BACKEND = "sqlite"
            restored_env = setup_environment(chdir=False, console=False)
            restored, restored_report = create_agent(
                restored_env, name, expected_life_id=life_id
            )
            if restored_report["source"] != "checkpoint":
                raise RuntimeError("Резервная копия не восстановила снимок")
            if restored.life_id != life_id or restored.name != name:
                raise RuntimeError("Резервная копия изменила идентичность жизни")
            if restored.cycle_count != final_state["cycle_count"]:
                raise RuntimeError("Резервная копия изменила cycle_count")
            if restored.goals != final_state.get("goals"):
                raise RuntimeError("Резервная копия изменила цели")
            if restored.knowledge_base != final_state.get("knowledge_base"):
                raise RuntimeError("Резервная копия изменила базу знаний")
            if restored.mental_models.to_storage_dict() != final_state.get("mental_models"):
                raise RuntimeError("Резервная копия изменила ментальные модели")
            restored_checkpoint = restored_report["checkpoint"]
            _finish(restored)
            restored = None
            from src.core.buffered_logger import flush_logs
            flush_logs()
            os.environ["DIGITAL_BEING_DATA_DIR"] = str(DATA)
            setup_environment(chdir=False, console=False)

        report = {
            "life_id": life_id,
            "name": name,
            "final_json": final_json,
            "final_cycle": final_state["cycle_count"],
            "final_state_sha256": final_hash,
            "pre_switch_backup": pre_backup,
            "migration": migration,
            "latest_sqlite_snapshot_id": latest_id,
            "json_sqlite_exact_match": True,
            "export": export,
            "verified_backup": final_backup,
            "backup_restored_in_new_directory": True,
            "restored_checkpoint": restored_checkpoint,
            "restored_identity_cycle_goals_memory_match": True,
            "config_backend_changed": False,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        _finish(agent)
        _finish(restored)
        from src.core.buffered_logger import flush_logs
        flush_logs()
        os.environ["DIGITAL_BEING_DATA_DIR"] = str(DATA)


if __name__ == "__main__":
    main()
