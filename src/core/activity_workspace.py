"""Ограниченная рабочая область занятий; не общий доступ к компьютеру."""

from pathlib import Path

from src.core.paths import data_path
from src.delamain.sandbox import Sandbox


class ActivityWorkspace:
    """Только creative-артефакты внутри профиля Digital Being."""

    MAX_FILE_BYTES = 8192
    ROOT_PARTS = ("delamain", "workspace", "creative")

    def __init__(self, root=None):
        self.root = Path(root or data_path(*self.ROOT_PARTS)).resolve()
        self.sandbox = Sandbox(self.root, max_file_bytes=self.MAX_FILE_BYTES, max_results=32)

    def read(self, filename):
        return self.sandbox.read_text(filename)

    def write(self, filename, content, *, overwrite=True):
        return self.sandbox.write_text(filename, content, overwrite=overwrite)

    def exists(self, filename):
        return self.sandbox.exists(filename)

    def list(self):
        return self.sandbox.list_files("*.txt", limit=32)
