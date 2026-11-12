"""Этап 5D: весь managed Delamain workspace принадлежит UUID и backup."""

import hashlib
from pathlib import Path
from uuid import uuid4

from src.delamain.subsystem import DelamainSubsystem
from src.memory.life_database import LifeDatabase
from src.memory.profile_backup import create_backup, restore_backup


def _managed(tmp_path, monkeypatch):
    data = tmp_path / "data"
    shared = tmp_path / "shared-workspace"
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(data))
    monkeypatch.setenv("DELAMAIN_WORKSPACE", str(shared))
    life_id = str(uuid4())
    subsystem = DelamainSubsystem(
        agent_name="ManagedWorkspace",
        workspace=shared,
        enabled=False,
        approval_mode="off",
        life_id=life_id,
    )
    assert subsystem.workspace == data / "lives" / life_id / "artifacts"
    assert subsystem.enable()["ok"] is True
    return subsystem, data, shared, life_id


def test_file_actions_stay_in_life_and_survive_verified_restore(
    tmp_path, monkeypatch
):
    subsystem, data, shared, life_id = _managed(tmp_path, monkeypatch)
    try:
        runtime = subsystem.runtime
        assert runtime.execute(
            "write_file", {"path": "notes/a.txt", "content": "первая"}
        ).ok
        assert runtime.execute(
            "append_file", {"path": "notes/a.txt", "content": "+вторая"}
        ).ok
        assert runtime.execute(
            "write_creative_draft", {"path": "draft.txt", "content": "черновик"}
        ).ok

        assert not shared.exists()
        root = data / "lives" / life_id / "artifacts"
        assert (root / "notes" / "a.txt").read_text(encoding="utf-8") == (
            "первая+вторая"
        )
        assert (root / "creative" / "draft.txt").read_text(encoding="utf-8") == (
            "черновик"
        )
        database = LifeDatabase(subsystem.db_path, life_id)
        rows = {row["relative_path"]: row for row in database.list_artifacts()}
        assert rows["artifacts/notes/a.txt"]["kind"] == "workspace"
        assert rows["artifacts/creative/draft.txt"]["kind"] == "creative"
        assert rows["artifacts/notes/a.txt"]["sha256"] == hashlib.sha256(
            (root / "notes" / "a.txt").read_bytes()
        ).hexdigest()
        assert database.verify_artifacts()["ok"] is True
    finally:
        subsystem.teardown()

    backup = tmp_path / "backup"
    restored = tmp_path / "restored"
    create_backup(data, backup)
    restore_backup(backup, restored)
    reopened = LifeDatabase(
        restored / "lives" / life_id / "life.sqlite3", life_id
    )
    assert reopened.verify_artifacts() == {
        "ok": True,
        "checked": 2,
        "problems": [],
    }


def test_run_python_registers_files_created_inside_workspace(tmp_path, monkeypatch):
    subsystem, data, shared, life_id = _managed(tmp_path, monkeypatch)
    try:
        runtime = subsystem.runtime
        script = (
            "from pathlib import Path\n"
            "Path('generated.txt').write_text('создано программой', encoding='utf-8')\n"
        )
        assert runtime.execute(
            "write_file", {"path": "make_artifact.py", "content": script}
        ).ok
        result = runtime.execute("run_python", {"path": "make_artifact.py"})
        assert result.ok, result.error

        generated = data / "lives" / life_id / "artifacts" / "generated.txt"
        assert generated.read_text(encoding="utf-8") == "создано программой"
        assert not shared.exists()
        database = LifeDatabase(subsystem.db_path, life_id)
        rows = {row["relative_path"]: row for row in database.list_artifacts()}
        assert rows["artifacts/make_artifact.py"]["kind"] == "workspace"
        assert rows["artifacts/generated.txt"]["metadata"] == {
            "source": "delamain.run_python"
        }
        assert database.verify_artifacts()["ok"] is True
    finally:
        subsystem.teardown()


def test_standalone_workspace_keeps_legacy_root(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(data))
    subsystem = DelamainSubsystem(
        agent_name="StandaloneWorkspace",
        enabled=False,
        approval_mode="off",
    )
    try:
        assert subsystem.workspace == data / "delamain" / "workspace"
        assert subsystem.enable()["ok"] is True
        result = subsystem.runtime.execute(
            "write_creative_draft", {"path": "draft.txt", "content": "legacy"}
        )
        assert result.ok
        assert (
            data / "delamain" / "workspace" / "creative" / "draft.txt"
        ).read_text(encoding="utf-8") == "legacy"
        assert not (data / "lives").exists()
    finally:
        subsystem.teardown()
