"""Ограниченная рабочая область занятий; не общий доступ к компьютеру.

Managed-жизнь (этап 5C) получает свой корень внутри каталога жизни
(``lives/<life_id>/artifacts/creative``): каждый новый файл привязывается
к UUID записью в реестре ``artifacts`` (вид, путь, SHA-256, размер,
метаданные). Прежние файлы общего creative-корня не изменяются и не
удаляются: недостающая прежняя редакция копируется оттуда при
продолжении работы (``ensure_from_legacy``), а разовый полный учёт
выполняет ``tools/manual/adopt_life_artifacts.py``. Standalone-режим
сохраняет прежний общий корень без регистрации.
"""

import os
import shutil
import tempfile
from pathlib import Path

from src.core.paths import data_path
from src.delamain.sandbox import Sandbox


class ActivityWorkspace:
    """Только creative-артефакты внутри профиля Digital Being."""

    MAX_FILE_BYTES = 8192
    ROOT_PARTS = ("delamain", "workspace", "creative")
    LIFE_PARTS = ("artifacts", "creative")

    def __init__(self, root=None, *, database=None):
        self.root = Path(root or data_path(*self.ROOT_PARTS)).resolve()
        self.sandbox = Sandbox(
            self.root, max_file_bytes=self.MAX_FILE_BYTES, max_results=32
        )
        self.database = database

    @classmethod
    def for_life(cls, life_id):
        """Рабочая область конкретной жизни: свой каталог + реестр артефактов."""
        from src.core.life_identity import validate_life_id
        from src.memory.life_database import LifeDatabase

        life_id = validate_life_id(life_id)
        database = LifeDatabase(data_path("lives", life_id, "life.sqlite3"), life_id)
        return cls(
            Path(data_path("lives", life_id, *cls.LIFE_PARTS)),
            database=database,
        )

    def write(
        self, filename, content, *, overwrite=True, kind="creative", metadata=None
    ):
        """Пишет текстовый файл и (managed) регистрирует его за UUID жизни.

        Ошибка регистрации не откатывает сам файл: содержимое уже на
        месте, следующая редакция перерегистрирует его. Файл — артефакт,
        реестр — владение и целостность.
        """
        result = self.sandbox.write_text(filename, content, overwrite=overwrite)
        if self.database is not None:
            self._register(filename, kind=kind, metadata=metadata)
        return result

    def write_bytes(
        self, filename, content, *, overwrite=True, kind="creative", metadata=None
    ):
        """Атомарно пишет байты (например, WAV) и (managed) регистрирует файл.

        Байтовые артефакты не ограничены текстовым лимитом песочницы:
        размер мелодии ограничен самим синтезом (потолок длительности),
        а содержимое всегда порождено этим органом.
        """
        target = self.sandbox.resolve(filename)
        data = bytes(content)
        if target.exists() and target.is_dir():
            raise ValueError(f"Это каталог, не файл: {filename}")
        if target.exists() and not overwrite:
            raise FileExistsError(f"Файл уже существует: {filename}")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".creative-", suffix=".tmp", dir=str(target.parent)
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
        if self.database is not None:
            self._register(filename, kind=kind, metadata=metadata)
        return {"path": self.sandbox.relative(target), "bytes": len(data)}

    def ensure_from_legacy(self, filename) -> bool:
        """Возвращает прежнюю редакцию из общего creative-корня.

        Managed-жизнь продолжает работу только над файлами в своём
        каталоге. Если прежней редакции там ещё нет (файл остался в
        общем корне до перехода), он копируется целиком, регистрируется
        за UUID, и оригинал остаётся на месте. Standalone ничего не
        делает: его файлы уже в общем корне.
        """
        if self.database is None:
            return False
        target = self.sandbox.resolve(filename)
        if target.exists():
            return False
        source = Path(data_path(*self.ROOT_PARTS)) / filename
        if source.is_symlink() or not source.is_file():
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        self._register(
            filename, kind="creative", metadata={"source": "legacy_workspace"}
        )
        return True

    def adopt_legacy_root(self, legacy_root=None) -> dict:
        """Разовый учёт всех файлов общего creative-корня за UUID жизни.

        Файлы копируются в каталог жизни и регистрируются; оригиналы не
        изменяются. Уже лежащее в каталоге жизни содержимое не
        перезаписывается. Идемпотентно: повторный запуск ничего не
        копирует.
        """
        legacy = Path(legacy_root or data_path(*self.ROOT_PARTS))
        report = {"adopted": 0, "kept": 0, "errors": []}
        if not legacy.is_dir():
            report["errors"].append(f"корень creative отсутствует: {legacy}")
            return report
        for source in sorted(legacy.rglob("*")):
            if source.is_symlink() or not source.is_file():
                continue
            name = source.relative_to(legacy).as_posix()
            try:
                target = self.sandbox.resolve(name)
                if target.exists():
                    report["kept"] += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                self._register(
                    name, kind="creative", metadata={"source": "legacy_adoption"}
                )
                report["adopted"] += 1
            except Exception as exc:
                report["errors"].append(f"{name}: {exc}")
        return report

    def _register(self, filename, *, kind, metadata=None):
        target = self.sandbox.resolve(filename)
        life_dir = Path(self.database.path).parent.resolve()
        relative = target.resolve().relative_to(life_dir).as_posix()
        self.database.register_artifact(
            target,
            kind=kind,
            relative_path=relative,
            metadata=metadata,
            update=True,
        )

    def read(self, filename):
        return self.sandbox.read_text(filename)

    def exists(self, filename):
        return self.sandbox.exists(filename)

    def list(self, pattern="*.txt"):
        return self.sandbox.list_files(pattern, limit=32)


def workspace_for(agent) -> ActivityWorkspace:
    """Рабочая область агента: каталог его жизни или общий legacy-корень."""
    if bool(getattr(agent, "_profile_managed", False)):
        life_id = getattr(agent, "life_id", None)
        if life_id:
            return ActivityWorkspace.for_life(life_id)
    return ActivityWorkspace()
