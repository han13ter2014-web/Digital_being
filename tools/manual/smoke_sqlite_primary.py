"""Smoke-тест живого SQLite-primary без автономных циклов и сети."""

import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"


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

    assert SIM_CONFIG.CHECKPOINT_BACKEND == "sqlite"
    assert SIM_CONFIG.CHECKPOINT_SQLITE_MIRROR is False
    profile = json.loads((DATA / "active_profile.json").read_text(encoding="utf-8"))
    life_id, name = profile["life_id"], profile["name"]
    json_root = DATA / "checkpoints" / life_id
    json_before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in json_root.glob("*.json")
    }
    agent = None
    restarted = None
    try:
        env = setup_environment(chdir=False, console=False)
        agent, report = create_agent(env, name, expected_life_id=life_id)
        assert report["source"] == "checkpoint" and "#snapshot=" in report["checkpoint"]
        cycle = agent.cycle_count
        goals = agent.goals
        knowledge = agent.knowledge_base
        models = agent.mental_models.to_storage_dict()
        saved = agent.save_state(force=True)
        assert saved.startswith(str(DATA / "lives" / life_id / "life.sqlite3"))
        state = CheckpointSerializer().load(saved)
        assert state["cycle_count"] == cycle and state["life_id"] == life_id
        database = LifeDatabase(DATA / "lives" / life_id / "life.sqlite3", life_id)
        latest_id = database.get_meta("latest_snapshot_id")
        assert saved.endswith(f"#snapshot={latest_id}")
        assert database.verify()["ok"] is True
        json_after = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in json_root.glob("*.json")
        }
        assert json_after == json_before

        _finish(agent)
        agent = None
        PluginRegistry.reset_global()
        restarted, restart_report = create_agent(env, name, expected_life_id=life_id)
        assert restart_report["checkpoint"].endswith(f"#snapshot={latest_id}")
        assert restarted.life_id == life_id and restarted.name == name
        assert restarted.cycle_count == cycle
        assert restarted.goals == goals
        assert restarted.knowledge_base == knowledge
        assert restarted.mental_models.to_storage_dict() == models
        print(json.dumps({
            "backend": SIM_CONFIG.CHECKPOINT_BACKEND,
            "life_id": life_id,
            "name": name,
            "cycle_count": cycle,
            "snapshot_written": latest_id,
            "sqlite_save_and_restart_ok": True,
            "identity_cycle_goals_memory_match": True,
            "legacy_json_files_unchanged": True,
            "verification": database.verify(),
        }, ensure_ascii=False, indent=2))
    finally:
        _finish(agent)
        _finish(restarted)
        from src.core.buffered_logger import flush_logs
        flush_logs()


if __name__ == "__main__":
    main()
