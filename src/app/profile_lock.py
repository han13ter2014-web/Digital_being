"""Эксклюзивная блокировка writer-процесса одного профиля жизни."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import BinaryIO, Optional


class ProfileWriterLockError(RuntimeError):
    """Профиль уже принадлежит другому запущенному writer-процессу."""


_HELD_PATHS: set[str] = set()
_HELD_PATHS_GUARD = threading.Lock()


class ProfileWriterLock:
    """Держит OS-level lock; read-only процессы этот файл не открывают."""

    def __init__(self, profile_dir: str | os.PathLike[str]) -> None:
        self.profile_dir = Path(profile_dir).expanduser().resolve()
        self.path = self.profile_dir / "writer.lock"
        self._handle: Optional[BinaryIO] = None
        self._key: Optional[str] = None

    @property
    def acquired(self) -> bool:
        return self._handle is not None

    def acquire(self) -> None:
        if self.acquired:
            return
        key = str(self.path)
        with _HELD_PATHS_GUARD:
            if key in _HELD_PATHS:
                raise ProfileWriterLockError(
                    f"Профиль уже используется другим writer-процессом: {self.profile_dir}"
                )

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            # msvcrt.locking работает с диапазоном от текущей позиции. Один
            # постоянный байт нужен, чтобы диапазон существовал у всех writers.
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise ProfileWriterLockError(
                f"Профиль уже используется другим writer-процессом: {self.profile_dir}"
            ) from exc

        with _HELD_PATHS_GUARD:
            if key in _HELD_PATHS:
                self._unlock_and_close(handle)
                raise ProfileWriterLockError(
                    f"Профиль уже используется другим writer-процессом: {self.profile_dir}"
                )
            _HELD_PATHS.add(key)
        self._handle = handle
        self._key = key

    @staticmethod
    def _unlock_and_close(handle: BinaryIO) -> None:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()

    def release(self) -> None:
        handle = self._handle
        key = self._key
        self._handle = None
        self._key = None
        if handle is not None:
            self._unlock_and_close(handle)
        if key is not None:
            with _HELD_PATHS_GUARD:
                _HELD_PATHS.discard(key)

    def __enter__(self) -> "ProfileWriterLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


__all__ = ["ProfileWriterLock", "ProfileWriterLockError"]
