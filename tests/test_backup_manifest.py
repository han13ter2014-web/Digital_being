"""Ошибочный manifest не превращается в успешное восстановление."""

import json

import pytest

from src.memory.profile_backup import create_backup, verify_backup, restore_backup


@pytest.mark.parametrize("entries", [[], None, [{"path": "../outside"}],
                                       [{"path": "unlisted.txt"}], [None]])
def test_invalid_file_list_rejected(tmp_path, entries):
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "manifest.json").write_text(json.dumps({"version": 1, "complete": True, "files": entries}))
    with pytest.raises(ValueError):
        restore_backup(backup, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_duplicate_paths_rejected(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "knowledge_base.json").write_text("{}")
    backup = tmp_path / "backup"
    create_backup(profile, backup)
    path = backup / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["files"].append(manifest["files"][0])
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_backup(backup)
