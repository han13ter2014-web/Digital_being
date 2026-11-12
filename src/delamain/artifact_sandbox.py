"""Delamain workspace bound to the artifact registry of one managed life."""

from __future__ import annotations

from pathlib import Path

from .sandbox import Sandbox


class ArtifactSandbox(Sandbox):
    """A path-confined workspace whose files are registered for one UUID.

    The database is intentionally supplied by the managed subsystem. Standalone
    Delamain keeps using plain :class:`Sandbox` and its legacy workspace.
    """

    def __init__(self, root, *args, database, kind="workspace", **kwargs):
        super().__init__(root, *args, **kwargs)
        self.database = database
        self.kind = str(kind)
        if not self.root.is_relative_to(database.life_dir.resolve()):
            raise ValueError("Managed Delamain workspace must stay inside its life directory")

    def child(self, path, **kwargs):
        """Keep artifact binding for the narrow ``creative/`` action sandbox."""
        kind = "creative" if Path(path).as_posix() == "creative" else self.kind
        return ArtifactSandbox(
            self.root / path,
            database=self.database,
            kind=kind,
            **kwargs,
        )

    def _register(self, path, *, source):
        target = self.resolve(path)
        relative = target.relative_to(self.database.life_dir.resolve()).as_posix()
        kind = "creative" if target.is_relative_to(self.root / "creative") else self.kind
        return self.database.register_artifact(
            target,
            kind=kind,
            relative_path=relative,
            metadata={"source": source},
            update=True,
        )

    def write_text(self, path, content, *, overwrite=True):
        result = super().write_text(path, content, overwrite=overwrite)
        self._register(path, source="delamain.write_file")
        return result

    def append_text(self, path, content):
        result = super().append_text(path, content)
        self._register(path, source="delamain.append_file")
        return result

    def sync_artifacts(self):
        """Register files produced by an approved workspace Python program.

        Missing files deliberately remain in the registry: ``verify_artifacts``
        will report their deletion instead of silently hiding it. Files outside
        this workspace are outside Delamain's path boundary and are not claimed.
        """
        registered = []
        for path in sorted(self.root.rglob("*")):
            if path.is_symlink() or not path.is_file() or self._is_skipped(path):
                continue
            relative = path.relative_to(self.root).as_posix()
            registered.append(self._register(relative, source="delamain.run_python"))
        return registered


__all__ = ["ArtifactSandbox"]
