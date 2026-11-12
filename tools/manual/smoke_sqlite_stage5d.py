"""Проверка 5D на копии активной жизни без автономных тиков."""

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


def _hashes(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        result[path.relative_to(root).as_posix()] = digest.hexdigest()
    return result


def main():
    from src.delamain.subsystem import DelamainSubsystem
    from src.memory.life_database import LifeDatabase
    from src.memory.profile_backup import create_backup, restore_backup, verify_backup

    before = _hashes(DATA)
    profile = json.loads((DATA / "active_profile.json").read_text(encoding="utf-8"))
    life_id = profile["life_id"]
    previous_data = os.environ.get("DIGITAL_BEING_DATA_DIR")
    subsystem = None
    try:
        with tempfile.TemporaryDirectory(
            prefix="sqlite_stage5d_", dir=ROOT / "tmp"
        ) as isolated:
            work = Path(isolated)
            original_backup = work / "original-backup"
            create_backup(DATA, original_backup)
            manifest = verify_backup(original_backup)
            restored = work / "restored"
            restore_backup(original_backup, restored)

            database = LifeDatabase(
                restored / "lives" / life_id / "life.sqlite3", life_id
            )
            initial_count = len(database.list_artifacts())
            initial_verification = database.verify()
            initial_artifacts = database.verify_artifacts()
            assert initial_verification["ok"] is True
            assert initial_artifacts["ok"] is True

            os.environ["DIGITAL_BEING_DATA_DIR"] = str(restored)
            subsystem = DelamainSubsystem(
                agent_name=profile["name"],
                enabled=False,
                approval_mode="off",
                life_id=life_id,
            )
            assert subsystem.enable()["ok"] is True
            runtime = subsystem.runtime
            assert runtime.execute(
                "write_file",
                {"path": "notes/stage5d.txt", "content": "запись"},
            ).ok
            assert runtime.execute(
                "append_file",
                {"path": "notes/stage5d.txt", "content": "+дополнение"},
            ).ok
            assert runtime.execute(
                "write_creative_draft",
                {"path": "stage5d.txt", "content": "творческий файл"},
            ).ok
            script = (
                "from pathlib import Path\n"
                "Path('stage5d_generated.txt').write_text("
                "'создано на копии', encoding='utf-8')\n"
            )
            assert runtime.execute(
                "write_file", {"path": "stage5d_program.py", "content": script}
            ).ok
            executed = runtime.execute(
                "run_python", {"path": "stage5d_program.py"}
            )
            assert executed.ok, executed.error
            subsystem.teardown()
            subsystem = None

            database = LifeDatabase(
                restored / "lives" / life_id / "life.sqlite3", life_id
            )
            final_verification = database.verify()
            final_artifacts = database.verify_artifacts()
            assert final_verification["ok"] is True
            assert final_artifacts["ok"] is True
            assert final_artifacts["checked"] == initial_count + 4
            assert not (restored / "delamain" / "workspace" / "notes").exists()

            second_backup = work / "second-backup"
            second_restored = work / "second-restored"
            create_backup(restored, second_backup)
            restore_backup(second_backup, second_restored)
            reopened = LifeDatabase(
                second_restored / "lives" / life_id / "life.sqlite3", life_id
            )
            assert reopened.verify()["ok"] is True
            assert reopened.verify_artifacts() == final_artifacts

            result = {
                "life_id": life_id,
                "name": profile["name"],
                "autonomous_ticks": 0,
                "original_files_hashed": len(before),
                "backup_manifest_files": len(manifest["files"]),
                "initial_artifacts": initial_artifacts,
                "created_artifacts": [
                    "artifacts/notes/stage5d.txt",
                    "artifacts/creative/stage5d.txt",
                    "artifacts/stage5d_program.py",
                    "artifacts/stage5d_generated.txt",
                ],
                "final_artifacts": final_artifacts,
                "initial_sqlite": initial_verification,
                "final_sqlite": final_verification,
                "second_restore_verified": True,
                "shared_workspace_writes": 0,
            }
    finally:
        if subsystem is not None:
            subsystem.teardown()
        if previous_data is None:
            os.environ.pop("DIGITAL_BEING_DATA_DIR", None)
        else:
            os.environ["DIGITAL_BEING_DATA_DIR"] = previous_data

    after = _hashes(DATA)
    changed = [name for name in sorted(set(before) | set(after)) if before.get(name) != after.get(name)]
    assert not changed, f"Оригинальные файлы изменились: {changed}"
    result["original_files_unchanged"] = True
    result["temporary_copy_removed"] = not work.exists()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
