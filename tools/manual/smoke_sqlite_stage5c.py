"""Smoke этапа 5C на копии текущей жизни, без автономных тиков.

Реестр артефактов и SQL-предложения: учёт legacy creative-файлов и
предложений без удаления оригиналов, привязка нового творчества к UUID,
решение человека из SQL, backup/restore с проверкой реестра.
"""

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

CREATIVE_PARTS = ("delamain", "workspace", "creative")


def _hash(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _finish(agent):
    if agent is not None:
        registry = getattr(agent, "plugin_registry", None)
        if registry is not None:
            registry.teardown_all()


def _close_loggers():
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


def _copy_tree(source: Path, destination: Path):
    if not source.is_dir():
        return 0
    count = 0
    for path in source.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    return count


def main() -> int:
    profile = json.loads((DATA / "active_profile.json").read_text(encoding="utf-8"))
    life_id, name = profile["life_id"], profile["name"]
    source = DATA / "lives" / life_id / "life.sqlite3"
    legacy_creative = DATA / Path(*CREATIVE_PARTS)
    legacy_proposals = DATA / "architecture_proposals"
    watched = [source, DATA / "active_profile.json", DATA / "knowledge_base.json"]
    if legacy_creative.is_dir():
        watched.extend(sorted(legacy_creative.rglob("*")))
    if legacy_proposals.is_dir():
        watched.extend(sorted(legacy_proposals.glob("*.json")))
    watched = [path for path in watched if path.is_file()]
    before = {str(path): _hash(path) for path in watched}
    agent = restored = None
    restored_root = None

    with tempfile.TemporaryDirectory(prefix=".stage5c_", dir=ROOT) as temporary:
        root = Path(temporary)
        target = root / "lives" / life_id / "life.sqlite3"
        target.parent.mkdir(parents=True)
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(target)) as dst:
                src.backup(dst)
        copied_creative = _copy_tree(legacy_creative, root / Path(*CREATIVE_PARTS))
        copied_proposals = _copy_tree(legacy_proposals, root / "architecture_proposals")
        copied_legacy = {
            str(root / path.relative_to(DATA)): _hash(root / path.relative_to(DATA))
            for path in watched
            if path != source and (root / path.relative_to(DATA)).is_file()
        }

        os.environ["DIGITAL_BEING_DATA_DIR"] = str(root)
        os.environ["DIGITAL_BEING_TEST_MODE"] = "1"
        os.environ["VOICE_CONSOLE_QUIET"] = "1"
        try:
            from src.app.bootstrap import create_agent
            from src.app.paths import setup_environment
            from src.core.activity_workspace import workspace_for
            from src.core.subsystem_base import PluginRegistry
            from src.core.subsystems.architecture_proposal import ArchitectureProposal
            from src.core.subsystems.will_registry import WillRegistry
            from src.memory.life_database import LifeDatabase
            from src.memory.profile_backup import create_backup, restore_backup

            PluginRegistry.reset_global()
            env = setup_environment(chdir=False, console=False)
            agent, report = create_agent(env, name, expected_life_id=life_id)
            assert report["source"] == "checkpoint"
            proposals_api = agent.architecture_proposal
            assert proposals_api.database is not None
            assert proposals_api.database.life_id == life_id

            # 1. Учёт legacy creative и предложений: копии в каталоге жизни,
            #    оригиналы побайтно не изменены.
            workspace = workspace_for(agent)
            adopted = workspace.adopt_legacy_root()
            assert adopted["errors"] == [], adopted
            imported = ArchitectureProposal(
                registry=WillRegistry(agent_name="smoke"), life_id=life_id
            ).import_legacy()
            assert imported["errors"] == [], imported
            database = workspace.database
            creative_rows = database.list_artifacts("creative")
            proposal_rows = database.list_artifacts("architecture_proposal")
            assert adopted["adopted"] == copied_creative == len(creative_rows)
            assert imported["imported"] == copied_proposals == len(proposal_rows)
            for path, digest in copied_legacy.items():
                assert _hash(Path(path)) == digest, path
            assert database.verify_artifacts()["ok"] is True

            # 2. Новое предложение: SQL — источник, экспорт зарегистрирован.
            import config.will_config as will_config

            will_config.WILL_CONFIG.ALLOW_ARCHITECTURE_PROPOSAL = True
            created = proposals_api.propose(
                "config_change", "Smoke 5C: REST_FATIGUE_THRESHOLD",
                "Проверка SQL-источника предложений на копии.",
                code_snippet="--- a\n+++ b", cycle=0,
            )
            assert created["created"] is True
            proposal_id = created["proposal_id"]
            enriched = proposals_api.enrich(
                proposal_id, {"verification": {"passed": True, "cycles": 1}}
            )
            assert enriched["enriched"] is True
            decided = proposals_api.decide(proposal_id, approved=False, note="smoke")
            assert decided["decided"] is True and decided["status"] == "rejected"
            _finish(agent)
            agent = None

            # 3. Повторное открытие: pending и решения только из SQL.
            PluginRegistry.reset_global()
            restored, restored_report = create_agent(env, name, expected_life_id=life_id)
            assert restored_report["source"] == "checkpoint"
            reopened_api = restored.architecture_proposal
            pending_ids = [item["id"] for item in reopened_api.list_pending()]
            assert proposal_id not in pending_ids
            assert reopened_api.decide(proposal_id, approved=True) == {
                "decided": False, "reason": "уже решено: rejected",
            }
            exported = [
                item for item in database.list_artifacts("architecture_proposal")
                if item["metadata"].get("proposal_id") == proposal_id
            ]
            assert exported and exported[0]["metadata"]["status"] == "rejected"

            # 4. Новое творчество привязано к UUID и попадает в каталог жизни.
            #    Рисунок: у тестового агента 32 черновика (лимит 32), квота рисунков свободна.
            workspace = workspace_for(restored)
            assert workspace.database is not None
            from src.cognition import local_art

            state = local_art.art_step(
                None, palette="calm", theme="проверка хранилища", workspace=workspace,
            )
            new_file = workspace.root / f"{state['id']}.svg"
            assert new_file.is_file()
            row = [
                item for item in workspace.database.list_artifacts("creative")
                if item["relative_path"] == f"artifacts/creative/{state['id']}.svg"
            ]
            assert len(row) == 1
            assert row[0]["sha256"] == _hash(new_file)
            for path, digest in copied_legacy.items():
                if "creative" not in path:
                    continue
                assert _hash(Path(path)) == digest, path

            # 5. Backup/restore с проверкой реестра артефактов.
            backup = create_backup(
                root, root / "snapshots" / "smoke5c_backup"
            )
            restored_root = Path(str(root) + "_restore")
            restore_backup(backup, restored_root)
            reopened_db = LifeDatabase(
                restored_root / "lives" / life_id / "life.sqlite3", life_id
            )
            artifacts_report = reopened_db.verify_artifacts()
            assert artifacts_report["ok"] is True, artifacts_report
            verification = database.verify()
            assert verification["ok"] is True, verification
            result = {
                "ok": True,
                "life_id": life_id,
                "cycle_count": restored.cycle_count,
                "storage_schema_version": LifeDatabase.SCHEMA_VERSION,
                "creative_adopted": adopted["adopted"],
                "proposals_imported": imported["imported"],
                "proposal_roundtrip": True,
                "new_creative_registered": row[0]["relative_path"],                "backup_restore_ok": True,
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
            _close_loggers()
            if restored_root is not None:
                shutil.rmtree(restored_root, ignore_errors=True)

    after = {str(path): _hash(path) for path in watched}
    assert before == after, "Исходные файлы изменились"
    result["source_files_unchanged"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
