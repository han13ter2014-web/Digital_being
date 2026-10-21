"""A small, dependency-free sandbox for workspace file operations.

The sandbox is the safety boundary of the local agent. Every path is treated
as relative to one workspace root. Absolute paths, drive-relative Windows
paths and parent-directory escapes are rejected before touching the file
system. Symlinks are resolved and must still stay inside the root.

This is intentionally *not* a full OS sandbox. It is a defensive path policy
for a local, single-user agent. Code execution is not part of this layer.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional


class SandboxError(Exception):
    """Raised when an operation would leave the workspace or is unsafe."""


def _is_within(path: Path, root: Path) -> bool:
    """Return True if *path* is inside *root*, case-insensitively on Windows."""

    try:
        path_norm = os.path.normcase(os.path.abspath(str(path)))
        root_norm = os.path.normcase(os.path.abspath(str(root)))
        return os.path.commonpath([path_norm, root_norm]) == root_norm
    except (OSError, ValueError):
        return False


def _best_effort_unlink(path: str) -> None:
    """Remove a temporary file without masking the original write error."""

    try:
        os.unlink(path)
    except OSError:
        return


class Sandbox:
    """Path-confined read/write/search operations for one workspace."""

    SKIP_DIRS = {
        ".git",
        ".hg",
        ".svn",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
    }

    def __init__(
        self,
        root: str | os.PathLike[str],
        max_file_bytes: int = 1_000_000,
        max_results: int = 200,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        if max_results <= 0:
            raise ValueError("max_results must be positive")
        self.max_file_bytes = int(max_file_bytes)
        self.max_results = int(max_results)

    # ------------------------------------------------------------------
    # Path policy
    # ------------------------------------------------------------------

    def resolve(self, path: str | os.PathLike[str]) -> Path:
        """Resolve a workspace-relative path, rejecting escapes.

        The returned path may not exist yet. The caller is responsible for
        checking whether the operation makes sense for a missing path.
        """

        raw = Path(path)
        if raw.is_absolute() or raw.drive:
            raise SandboxError(f"absolute paths are not allowed: {path!r}")
        if any(part == ".." for part in raw.parts):
            raise SandboxError(f"parent-directory escapes are not allowed: {path!r}")

        target = (self.root / raw).resolve(strict=False)
        if not _is_within(target, self.root):
            raise SandboxError(f"path escapes the workspace: {path!r}")
        return target

    def relative(self, path: Path) -> str:
        """Return a portable workspace-relative path."""

        return path.resolve(strict=False).relative_to(self.root).as_posix()

    def _safe_pattern(self, pattern: str) -> str:
        raw = Path(pattern)
        if raw.is_absolute() or raw.drive:
            raise SandboxError(f"absolute search patterns are not allowed: {pattern!r}")
        if any(part == ".." for part in raw.parts):
            raise SandboxError(f"search pattern escapes the workspace: {pattern!r}")
        return pattern

    def _is_skipped(self, path: Path) -> bool:
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            return True
        if any(part in self.SKIP_DIRS for part in rel.parts):
            return True
        return path.name.startswith(".delamain-")

    def _iter_files(self, pattern: str) -> Iterable[Path]:
        for path in self.root.glob(pattern):
            try:
                if not path.is_file():
                    continue
                resolved = path.resolve(strict=False)
                if not _is_within(resolved, self.root):
                    continue
            except OSError:
                continue
            if self._is_skipped(path):
                continue
            yield path

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def read_text(
        self,
        path: str | os.PathLike[str],
        max_bytes: Optional[int] = None,
    ) -> str:
        """Read a UTF-8 text file with size and binary checks."""

        target = self.resolve(path)
        if target == self.root:
            raise SandboxError("the workspace root is not a file")
        if not target.exists():
            raise FileNotFoundError(f"file not found: {path}")
        if not target.is_file():
            raise SandboxError(f"not a regular file: {path}")

        limit = self.max_file_bytes
        if max_bytes is not None:
            limit = min(limit, int(max_bytes))
        size = target.stat().st_size
        if size > limit:
            raise SandboxError(f"file is too large: {size} bytes > {limit}")

        raw = target.read_bytes()
        if len(raw) > limit:
            raise SandboxError(f"file grew beyond the limit: {len(raw)} bytes > {limit}")
        if b"\x00" in raw[:4096]:
            raise SandboxError(f"binary files are not supported: {path}")
        return raw.decode("utf-8", errors="replace")

    def write_text(
        self,
        path: str | os.PathLike[str],
        content: str,
        *,
        overwrite: bool = True,
    ) -> Dict[str, object]:
        """Atomically write a UTF-8 text file inside the workspace."""

        target = self.resolve(path)
        if target == self.root:
            raise SandboxError("the workspace root is not a file")
        if target.exists() and target.is_dir():
            raise SandboxError(f"target is a directory: {path}")
        if target.exists() and not overwrite:
            raise FileExistsError(f"file already exists: {path}")

        if not isinstance(content, str):
            content = str(content)
        data = content.encode("utf-8")
        if len(data) > self.max_file_bytes:
            raise SandboxError(
                f"content is too large: {len(data)} bytes > {self.max_file_bytes}"
            )

        created = not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)

        # Re-check after creating parents: an existing symlinked parent must
        # still resolve inside the workspace.
        if not _is_within(target.parent.resolve(strict=False), self.root):
            raise SandboxError(f"parent directory escapes the workspace: {path}")

        fd, tmp_name = tempfile.mkstemp(
            prefix=".delamain-", suffix=".tmp", dir=str(target.parent)
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                _best_effort_unlink(tmp_name)

        return {
            "path": self.relative(target),
            "bytes": len(data),
            "created": created,
        }

    def exists(self, path: str | os.PathLike[str]) -> bool:
        target = self.resolve(path)
        return target.exists() and target.is_file()

    def stat(self, path: str | os.PathLike[str]) -> Dict[str, object]:
        target = self.resolve(path)
        if not target.exists():
            raise FileNotFoundError(f"file not found: {path}")
        info = target.stat()
        return {
            "path": self.relative(target),
            "bytes": info.st_size,
            "is_file": target.is_file(),
            "modified_at": datetime.fromtimestamp(
                info.st_mtime, tz=timezone.utc
            ).isoformat(timespec="seconds"),
        }

    def list_files(
        self,
        pattern: str = "**/*",
        *,
        limit: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        """List files matching a workspace-relative glob."""

        pattern = self._safe_pattern(pattern or "**/*")
        cap = self.max_results if limit is None else min(int(limit), self.max_results)
        if cap <= 0:
            return []

        paths = sorted(self._iter_files(pattern), key=lambda p: self.relative(p).lower())
        result: List[Dict[str, object]] = []
        for path in paths[:cap]:
            try:
                info = path.stat()
            except OSError:
                continue
            result.append(
                {
                    "path": self.relative(path),
                    "bytes": info.st_size,
                    "modified_at": datetime.fromtimestamp(
                        info.st_mtime, tz=timezone.utc
                    ).isoformat(timespec="seconds"),
                }
            )
        return result

    def search_text(
        self,
        query: str,
        pattern: str = "**/*",
        *,
        limit: Optional[int] = None,
        context_lines: int = 1,
    ) -> List[Dict[str, object]]:
        """Case-insensitive text search across workspace files."""

        if not isinstance(query, str) or not query:
            raise SandboxError("search query must be a non-empty string")
        pattern = self._safe_pattern(pattern or "**/*")
        cap = self.max_results if limit is None else min(int(limit), self.max_results)
        if cap <= 0:
            return []

        needle = query.casefold()
        context_lines = max(0, int(context_lines))
        matches: List[Dict[str, object]] = []

        for path in sorted(self._iter_files(pattern), key=lambda p: self.relative(p).lower()):
            try:
                text = self.read_text(self.relative(path))
            except (OSError, SandboxError):
                continue
            lines = text.splitlines()
            for line_number, line in enumerate(lines, start=1):
                if needle not in line.casefold():
                    continue
                start = max(1, line_number - context_lines)
                end = min(len(lines), line_number + context_lines)
                matches.append(
                    {
                        "path": self.relative(path),
                        "line": line_number,
                        "text": line.strip(),
                        "context": "\n".join(lines[start - 1 : end]),
                    }
                )
                if len(matches) >= cap:
                    return matches
        return matches

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"Sandbox(root={str(self.root)!r})"
