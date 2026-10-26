"""Проверяемый резервный комплект профиля; восстановление только в новую папку."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from contextlib import closing
from uuid import uuid4


DIRECTORIES = ("checkpoints", "mind", "memory", "nursery", "delamain")
FILES = ("knowledge_base.json", "life_state.json", "life_requests.json", "life_events.log")


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sqlite_copy(source, target):
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
            result = dst.execute("PRAGMA integrity_check").fetchall()
            if result != [("ok",)]:
                raise ValueError(f"SQLite integrity_check: {result}")


def verify_backup(directory):
    root = Path(directory).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or manifest.get("complete") is not True:
        raise ValueError("Незавершённый или неподдерживаемый резервный комплект")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("В manifest нет файлов")
    seen = set()
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("Недопустимая запись manifest")
        relative = Path(item["path"])
        key = relative.as_posix().casefold()
        if key in seen:
            raise ValueError("Повторный путь в manifest")
        seen.add(key)
        if (relative.is_absolute() or relative.drive or ".." in relative.parts
                or not relative.parts or relative.parts[0] not in (*DIRECTORIES, *FILES)):
            raise ValueError("Недопустимый путь в manifest")
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError(f"Нет безопасного файла {relative}")
        if path.stat().st_size != item.get("bytes") or _digest(path) != item.get("sha256"):
            raise ValueError(f"Контрольная сумма не совпала: {relative}")
    return manifest


def create_backup(profile, destination):
    source = Path(profile).resolve()
    target = Path(destination).absolute()
    if target.resolve().is_relative_to(source) and target.parent.resolve() != source / "snapshots":
        raise ValueError("Копия внутри профиля допускается только в snapshots")
    if not source.is_dir() or target.exists():
        raise ValueError("Нужен существующий профиль и новый путь копии")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / ("." + target.name + "." + uuid4().hex + ".tmp")
    staging.mkdir()
    try:
        entries = []
        paths = []
        for name in DIRECTORIES:
            folder = source / name
            if folder.is_symlink():
                raise ValueError(f"Ссылки не включаются в резервную копию: {folder}")
            if folder.is_dir():
                paths.extend(folder.rglob("*"))
        paths.extend(source / name for name in FILES if (source / name).exists())
        for path in sorted(paths):
            if path.is_symlink() or not path.resolve().is_relative_to(source):
                raise ValueError(f"Путь выходит из профиля: {path}")
            if not path.is_file():
                continue
            if path.name.endswith(("-wal", "-shm", "-journal")):
                continue
            relative = path.relative_to(source)
            output = staging / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            with path.open("rb") as handle:
                sqlite = handle.read(16) == b"SQLite format 3\x00"
            if sqlite:
                _sqlite_copy(path, output)
            else:
                shutil.copy2(path, output)
            entries.append({"path": relative.as_posix(), "bytes": output.stat().st_size,
                            "sha256": _digest(output), "sqlite": sqlite})
        if not entries:
            raise ValueError("В профиле нет данных для копии")
        manifest = {"version": 1, "complete": True, "files": entries,
                    "consistency": "per_database; stop writers for cross_store consistency"}
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        verify_backup(staging)
        if target.exists():
            raise FileExistsError(target)
        os.rename(staging, target)
        return str(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def restore_backup(backup, destination):
    manifest = verify_backup(backup)
    source = Path(backup).resolve()
    target = Path(destination).absolute()
    if target.exists():
        raise ValueError("Восстановление допускается только в новую папку")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / ("." + target.name + "." + uuid4().hex + ".tmp")
    staging.mkdir()
    try:
        for item in manifest["files"]:
            path = Path(item["path"])
            output = staging / path
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / path, output)
            if _digest(output) != item["sha256"]:
                raise ValueError(f"Ошибка копирования {path}")
        if target.exists():
            raise FileExistsError(target)
        os.rename(staging, target)
        return str(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
