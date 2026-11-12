"""Этап 5C: creative-файлы привязаны к UUID; legacy-корень не изменяется."""

import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.core.activity_workspace import ActivityWorkspace, workspace_for
from src.core.paths import data_path
from src.cognition import creative_draft, local_art, local_music
from src.memory.life_database import LifeDatabase
from src.memory.profile_backup import create_backup, restore_backup


def _managed_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    life_id = str(uuid4())
    workspace = ActivityWorkspace.for_life(life_id)
    return workspace, life_id


def test_managed_draft_is_written_into_life_and_registered(
    tmp_path, monkeypatch
):
    workspace, life_id = _managed_workspace(tmp_path, monkeypatch)

    state = creative_draft.draft_step(workspace=workspace)

    stored = workspace.root / f"{state['id']}.txt"
    assert stored.is_file()
    content = stored.read_text(encoding="utf-8")
    assert state["sha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    artifacts = workspace.database.list_artifacts("creative")
    assert len(artifacts) == 1
    assert artifacts[0]["metadata"]["activity"] == "draft"
    assert artifacts[0]["relative_path"] == f"artifacts/creative/{state['id']}.txt"
    assert artifacts[0]["sha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert not Path(data_path("delamain", "workspace", "creative")).exists()


def test_managed_revision_continues_from_legacy_copy(tmp_path, monkeypatch):
    workspace, _life_id = _managed_workspace(tmp_path, monkeypatch)
    identifier = uuid4().hex
    legacy_root = Path(data_path("delamain", "workspace", "creative"))
    legacy_root.mkdir(parents=True)
    legacy_file = legacy_root / f"{identifier}.txt"
    text = "Черновик: тишина\n\nПервая строка."
    # Пишем байтами: файлы песочницы хранят перевод строк буквально.
    legacy_file.write_bytes(text.encode("utf-8"))
    original = legacy_file.read_bytes()
    state = {
        "id": identifier, "theme": "тишина", "revision": 1,
        "status": "active",
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }

    updated = creative_draft.draft_step(state, workspace=workspace)

    assert updated["revision"] == 2
    copied = workspace.root / f"{identifier}.txt"
    assert copied.is_file()
    assert copied.read_text(encoding="utf-8").startswith("Черновик: тишина")
    assert legacy_file.read_bytes() == original
    artifacts = workspace.database.list_artifacts("creative")
    assert artifacts[0]["metadata"]["activity"] == "draft"
    assert artifacts[0]["metadata"]["revision"] == 2


def test_standalone_mode_keeps_legacy_root_without_registration(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))

    state = creative_draft.draft_step()

    legacy_root = Path(data_path("delamain", "workspace", "creative"))
    assert (legacy_root / f"{state['id']}.txt").is_file()
    assert not (tmp_path / "lives").exists()


def test_art_and_music_register_into_life(tmp_path, monkeypatch):
    workspace, _life_id = _managed_workspace(tmp_path, monkeypatch)

    art = local_art.art_step(None, palette="joy", theme="свет", workspace=workspace)
    music = local_music.music_step(
        None, mood="calm", theme="след", workspace=workspace
    )

    svg = workspace.root / f"{art['id']}.svg"
    wav = workspace.root / f"{music['id']}.wav"
    assert svg.is_file() and wav.is_file()
    artifacts = {
        Path(row["relative_path"]).name: row
        for row in workspace.database.list_artifacts("creative")
    }
    assert artifacts[f"{art['id']}.svg"]["metadata"]["activity"] == "art"
    assert artifacts[f"{art['id']}.svg"]["sha256"] == hashlib.sha256(
        svg.read_bytes()
    ).hexdigest()
    assert artifacts[f"{music['id']}.wav"]["metadata"]["activity"] == "music"
    assert artifacts[f"{music['id']}.wav"]["sha256"] == hashlib.sha256(
        wav.read_bytes()
    ).hexdigest()
    assert workspace.database.verify_artifacts()["ok"] is True


def test_workspace_for_agent_selects_root_by_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    life_id = str(uuid4())
    managed = SimpleNamespace(_profile_managed=True, life_id=life_id)
    standalone = SimpleNamespace(_profile_managed=False, life_id=life_id)

    assert workspace_for(managed).root.as_posix().endswith(
        f"lives/{life_id}/artifacts/creative"
    )
    assert workspace_for(managed).database.life_id == life_id
    assert workspace_for(standalone).database is None
    assert workspace_for(standalone).root == Path(
        data_path("delamain", "workspace", "creative")
    ).resolve()
    assert workspace_for(object()).database is None


def test_adopt_legacy_root_copies_and_keeps_originals(tmp_path, monkeypatch):
    workspace, _life_id = _managed_workspace(tmp_path, monkeypatch)
    legacy_root = Path(data_path("delamain", "workspace", "creative"))
    (legacy_root / "notes").mkdir(parents=True)
    first = legacy_root / "a.txt"
    second = legacy_root / "notes" / "b.txt"
    first.write_text("первый", encoding="utf-8")
    second.write_text("второй", encoding="utf-8")
    before = {path: path.read_bytes() for path in (first, second)}

    report = workspace.adopt_legacy_root()

    assert report["adopted"] == 2 and report["kept"] == 0 and not report["errors"]
    assert (workspace.root / "a.txt").read_text(encoding="utf-8") == "первый"
    assert (workspace.root / "notes" / "b.txt").read_text(encoding="utf-8") == "второй"
    assert first.read_bytes() == before[first]
    assert second.read_bytes() == before[second]
    assert len(workspace.database.list_artifacts("creative")) == 2
    assert workspace.database.verify_artifacts()["ok"] is True

    again = workspace.adopt_legacy_root()
    assert again["adopted"] == 0 and again["kept"] == 2


def test_restore_backup_verifies_registered_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGITAL_BEING_DATA_DIR", str(tmp_path))
    life_id = str(uuid4())
    database = LifeDatabase(
        tmp_path / "lives" / life_id / "life.sqlite3", life_id
    )
    source = tmp_path / "outside" / "draft.txt"
    source.parent.mkdir(parents=True)
    source.write_text("текст работы", encoding="utf-8")
    database.register_artifact(source, kind="creative")

    profile = tmp_path
    backup = tmp_path / "snapshots" / "backup_5c"
    backup.parent.mkdir(parents=True)
    create_backup(profile, backup)
    restored = tmp_path / "restored_profile"
    restore_backup(backup, restored)

    restored_db = restored / "lives" / life_id / "life.sqlite3"
    reopened = LifeDatabase(restored_db, life_id)
    assert reopened.verify_artifacts() == {
        "ok": True, "checked": 1, "problems": [],
    }
    assert (
        restored / "lives" / life_id / "artifacts" / "creative" / "draft.txt"
    ).read_text(encoding="utf-8") == "текст работы"

    with database.write() as connection:
        connection.execute(
            "UPDATE artifacts SET sha256 = 'broken' WHERE relative_path = ?",
            ("artifacts/creative/draft.txt",),
        )
    tampered = tmp_path / "snapshots" / "backup_broken"
    create_backup(profile, tampered)

    with pytest.raises(ValueError, match="не совпали с реестром"):
        restore_backup(tampered, tmp_path / "restored_broken")
    assert not (tmp_path / "restored_broken").exists()
