"""Проверить SQLite активной жизни и восстановление её резервной копии."""

import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"


def _finish(agent):
    registry = getattr(agent, "plugin_registry", None) if agent is not None else None
    if registry is not None:
        registry.teardown_all()


def main():
    from config.simulation_config import SIM_CONFIG
    from src.app.bootstrap import create_agent
    from src.app.paths import setup_environment
    from src.core.checkpoint_serializer import CheckpointSerializer
    from src.core.subsystem_base import PluginRegistry
    from src.memory.life_database import LifeDatabase
    from src.memory.profile_backup import restore_backup, verify_backup

    profile = json.loads((DATA / "active_profile.json").read_text(encoding="utf-8"))
    life_id, name = profile["life_id"], profile["name"]
    database = LifeDatabase(DATA / "lives" / life_id / "life.sqlite3", life_id)
    latest_id = database.get_meta("latest_snapshot_id")
    state = database.checkpoints.load(latest_id)
    backups = sorted((DATA / "snapshots").glob("sqlite_verified_*/manifest.json"))
    if not backups:
        raise ValueError("Проверенная резервная копия не найдена")
    backup = backups[-1].parent
    verify_backup(backup)
    restored = None
    try:
        with tempfile.TemporaryDirectory(prefix="sqlite_verify_", dir=ROOT / "tmp") as isolated:
            restored_root = Path(isolated) / "restored"
            try:
                restore_backup(backup, restored_root)
                restored_database = LifeDatabase(
                    restored_root / "lives" / life_id / "life.sqlite3", life_id
                )
                backup_snapshot_id = restored_database.get_meta("latest_snapshot_id")
                backup_state = restored_database.checkpoints.load(backup_snapshot_id)
                PluginRegistry.reset_global()
                os.environ["DIGITAL_BEING_DATA_DIR"] = str(restored_root)
                SIM_CONFIG.CHECKPOINT_BACKEND = "sqlite"
                SIM_CONFIG.CHECKPOINT_SQLITE_MIRROR = False
                env = setup_environment(chdir=False, console=False)
                restored, report = create_agent(env, name, expected_life_id=life_id)
                assert report["source"] == "checkpoint"
                assert report["checkpoint"].startswith(f"{life_id}_cycle_") is False
                assert "#snapshot=" in report["checkpoint"]
                assert restored.life_id == life_id and restored.name == name
                assert restored.cycle_count == backup_state["cycle_count"]
                assert restored.goals == backup_state.get("goals")
                assert restored.knowledge_base == backup_state.get("knowledge_base")
                assert restored.mental_models.to_storage_dict() == backup_state.get("mental_models")
                restored_state = CheckpointSerializer().load(
                    str(restored_root / "lives" / life_id / "life.sqlite3")
                    + f"#snapshot={backup_snapshot_id}"
                )
                assert restored_state == backup_state
                result = {
                    "life_id": life_id,
                    "name": restored.name,
                    "live_cycle_count": state["cycle_count"],
                    "restored_cycle_count": restored.cycle_count,
                    "live_latest_snapshot_id": latest_id,
                    "backup_snapshot_id": backup_snapshot_id,
                    "backup": str(backup),
                    "backup_manifest_valid": True,
                    "restored_in_new_directory": True,
                    "restored_from_sqlite": True,
                    "identity_cycle_goals_memory_match": True,
                    "sqlite_state_exact_match": True,
                    "verification": database.verify(),
                }
                print(json.dumps(result, ensure_ascii=False, indent=2))
            finally:
                # Сначала закрываем SQLite, потом TemporaryDirectory удаляет копию.
                _finish(restored)
                restored = None
                from src.core.buffered_logger import flush_logs
                flush_logs()
                os.environ["DIGITAL_BEING_DATA_DIR"] = str(DATA)
                setup_environment(chdir=False, console=False)
    finally:
        _finish(restored)
        from src.core.buffered_logger import flush_logs
        flush_logs()
        os.environ["DIGITAL_BEING_DATA_DIR"] = str(DATA)


if __name__ == "__main__":
    main()
