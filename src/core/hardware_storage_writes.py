"""Ограниченные sanitized исходы явных операций записи сущности."""

from __future__ import annotations

from copy import deepcopy
import errno
import sqlite3
from typing import Dict, Optional


_ALLOWED_OPERATIONS = frozenset(
    {"checkpoint", "knowledge_base", "long_term_memory", "mental_models"}
)
_FAILURE_CATEGORIES = frozenset(
    {
        "external_service_refused",
        "invalid_input",
        "io_error",
        "no_space",
        "permission_denied",
        "unknown",
    }
)
_HISTORY_LIMIT = 50


def _empty_latest() -> Dict:
    return {
        "operation": None,
        "outcome": "unknown",
        "category": "no_observation",
        "origin": "unknown",
        "cycle": None,
    }


def storage_write_error_category(error: BaseException) -> str:
    """Классифицировать только известный тип; отказ не доказывает нехватку места."""
    if isinstance(error, sqlite3.Error):
        code = getattr(error, "sqlite_errorcode", None)
        primary = code & 0xFF if isinstance(code, int) else None
        if primary == sqlite3.SQLITE_FULL:
            return "no_space"
        if primary in {sqlite3.SQLITE_PERM, sqlite3.SQLITE_AUTH}:
            return "permission_denied"
        if primary == sqlite3.SQLITE_IOERR:
            return "io_error"
        return "unknown"
    if isinstance(error, PermissionError):
        return "permission_denied"
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        return "no_space"
    if isinstance(error, OSError):
        return "io_error"
    if isinstance(error, (TypeError, ValueError)):
        return "invalid_input"
    return "unknown"


class HardwareStorageWrites:
    """Runtime-only наблюдения; checkpoint и storage risk не изменяются."""

    def __init__(self):
        self.latest = _empty_latest()
        self.history = []
        self.sample_count = 0

    def record(
        self,
        operation: str,
        *,
        outcome: str,
        category: str,
        cycle: Optional[int],
    ) -> Dict:
        valid_cycle = cycle is None or (
            not isinstance(cycle, bool) and isinstance(cycle, int) and cycle >= 0
        )
        valid_outcome = (
            outcome == "succeeded"
            and category == "written"
            or outcome == "failed"
            and category in _FAILURE_CATEGORIES
        )
        if operation not in _ALLOWED_OPERATIONS or not valid_outcome or not valid_cycle:
            return deepcopy(self.latest)

        self.latest = {
            "operation": operation,
            "outcome": outcome,
            "category": category,
            "origin": "unknown",
            "cycle": cycle,
        }
        self.history.append(deepcopy(self.latest))
        del self.history[:-_HISTORY_LIMIT]
        self.sample_count += 1
        return deepcopy(self.latest)

    def status(self) -> Dict:
        return {
            "latest": deepcopy(self.latest),
            "sample_count": self.sample_count,
        }


__all__ = ["HardwareStorageWrites", "storage_write_error_category"]
