"""Прогон этапа 3 на отдельной временной жизни без изменения живого data/."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None


def _state_hash(state):
    payload = json.dumps(
        state, ensure_ascii=True, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main():
    temporary_parent = ROOT / "tmp"
    temporary_parent.mkdir(exist_ok=True)
    live_profile = ROOT / "data" / "active_profile.json"
    live_profile_before = _file_hash(live_profile)

    with tempfile.TemporaryDirectory(prefix="sqlite_dual_write_", dir=temporary_parent) as isolated:
        data_root = Path(isolated) / "data"
        os.environ["DIGITAL_BEING_DATA_DIR"] = str(data_root)
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        os.environ["VOICE_CONSOLE_QUIET"] = "1"
        for name in (
            "DIGITAL_BEING_TELEGRAM_TOKEN", "DIGITAL_BEING_TELEGRAM_CHAT_ID",
            "DIGITAL_BEING_DISCORD_WEBHOOK_URL",
        ):
            os.environ.pop(name, None)

        from config.simulation_config import SIM_CONFIG
        from src.core.agent import DigitalBeing
        from src.core.checkpoint_serializer import CheckpointSerializer
        from src.memory.life_database import LifeDatabase

        SIM_CONFIG.CHECKPOINT_BACKEND = "json"
        SIM_CONFIG.CHECKPOINT_SQLITE_MIRROR = True
        agent = DigitalBeing("SQLiteDualWriteProbe", profile_managed=True)
        life_id = agent.life_id
        mirror_path = data_root / "lives" / life_id / "life.sqlite3"
        database = None
        records = []
        try:
            for cycle in range(1, 6):
                agent.cycle_count = cycle
                agent.knowledge_base[f"probe_{cycle}"] = f"значение {cycle}"
                primary_path = agent.save_state(force=True)
                assert primary_path.endswith(".json"), primary_path
                primary_state = CheckpointSerializer().load(primary_path)
                if database is None:
                    database = LifeDatabase(mirror_path, life_id)
                snapshot_id = database.get_meta("latest_snapshot_id")
                mirror_state = database.checkpoints.load(snapshot_id)
                assert primary_state == mirror_state
                assert _state_hash(primary_state) == _state_hash(mirror_state)
                records.append({
                    "cycle": cycle,
                    "snapshot_id": snapshot_id,
                    "sha256": _state_hash(primary_state),
                    "primary_file": Path(primary_path).name,
                })

            json_files = sorted(
                (data_root / "checkpoints" / life_id).glob("*_cycle_*.json")
            )
            connection = sqlite3.connect(mirror_path)
            try:
                snapshot_count = connection.execute(
                    "SELECT COUNT(*) FROM snapshots WHERE agent_name=?", (life_id,)
                ).fetchone()[0]
            finally:
                connection.close()
            verification = database.verify()
            assert len(json_files) == 5
            assert snapshot_count == 5
            assert verification["ok"] is True
            assert _file_hash(live_profile) == live_profile_before

            report = {
                "life_id": life_id,
                "agent_name": agent.name,
                "primary_backend": "json",
                "sqlite_mirror": str(mirror_path),
                "snapshots_written": len(records),
                "json_snapshots": len(json_files),
                "sqlite_snapshots": snapshot_count,
                "all_roundtrips_equal": True,
                "records": records,
                "verification": verification,
                "live_active_profile_unchanged": True,
                "temporary_life_removed_on_exit": True,
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            from src.core.buffered_logger import flush_logs
            flush_logs()


if __name__ == "__main__":
    main()
