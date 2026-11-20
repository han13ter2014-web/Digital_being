"""12A: владельческий allowlist relevant roots без наблюдения дисков."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Dict, Optional, Tuple

from config.simulation_config import SIM_CONFIG
from src.core.paths import data_dir


DATA_ROOT_ID = "data"
_MAX_ROOTS = 8
_ROOT_ID = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
_DATA_WRITE_SCOPES = (
    "architecture_proposals",
    "checkpoints",
    "creative_artifacts",
    "delamain_workspace",
    "knowledge",
    "logs",
    "managed_lives",
    "mental_models",
    "nursery",
)


def _normalized_path(value) -> str:
    try:
        raw = os.fspath(value)
    except TypeError as error:
        raise ValueError("root path must be a text path") from error
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError("root path must be a nonempty text path")
    return os.path.normpath(os.path.abspath(os.path.expanduser(raw)))


def _path_key(path: str) -> str:
    return os.path.normcase(path)


def _reject_overlap(paths: Dict[str, str], root_id: str, path: str) -> None:
    candidate = _path_key(path)
    for existing_id, existing_path in paths.items():
        existing = _path_key(existing_path)
        try:
            common = os.path.commonpath((candidate, existing))
        except ValueError:
            # Разные Windows drives не могут быть дубликатами или вложенными roots.
            continue
        if common in {candidate, existing}:
            raise ValueError(
                f"root {root_id!r} duplicates or nests with {existing_id!r}"
            )


class RelevantRootRegistry:
    """Текущий owner allowlist; пути доступны только внутренним consumers."""

    __slots__ = ("_paths",)

    def __init__(self, owner_allowlist=None, *, data_root=None) -> None:
        if owner_allowlist is None:
            owner_allowlist = {}
        if not isinstance(owner_allowlist, Mapping):
            raise ValueError("relevant roots must be a mapping of root ID to path")
        if len(owner_allowlist) > _MAX_ROOTS - 1:
            raise ValueError(f"relevant roots allow at most {_MAX_ROOTS} roots")

        paths = {
            DATA_ROOT_ID: _normalized_path(
                data_dir() if data_root is None else data_root
            )
        }
        entries = []
        for root_id, raw_path in owner_allowlist.items():
            if not isinstance(root_id, str) or _ROOT_ID.fullmatch(root_id) is None:
                raise ValueError("relevant root ID must be a bounded lowercase code")
            if root_id == DATA_ROOT_ID:
                raise ValueError("the existing data root ID is reserved")
            entries.append((root_id, raw_path))
        for root_id, raw_path in sorted(entries):
            path = _normalized_path(raw_path)
            _reject_overlap(paths, root_id, path)
            paths[root_id] = path
        self._paths = paths

    @classmethod
    def from_config(cls) -> "RelevantRootRegistry":
        """Прочитать только явный owner allowlist, не перечисляя разделы ОС."""
        return cls(getattr(SIM_CONFIG, "HARDWARE_RELEVANT_ROOTS", {}))

    @property
    def root_ids(self) -> Tuple[str, ...]:
        return tuple(self._paths)

    def path_for(self, root_id: str) -> Optional[str]:
        """Внутреннее разрешение пути; удалённый root не получает замену."""
        if not isinstance(root_id, str):
            return None
        return self._paths.get(root_id)

    def items(self) -> Tuple[Tuple[str, str], ...]:
        """Снимок для будущего read-only observer; не входит в публичный DTO."""
        return tuple(self._paths.items())

    def status(self) -> Dict:
        """Sanitized inventory без путей, устройств и порядка перечисления ОС."""
        roots = []
        for root_id in self.root_ids:
            is_data = root_id == DATA_ROOT_ID
            roots.append(
                {
                    "root_id": root_id,
                    "origin": "existing_data" if is_data else "owner_allowlist",
                    # Дополнительный root пока лишь разрешён, но не связан с записью.
                    "write_scopes": list(_DATA_WRITE_SCOPES) if is_data else [],
                }
            )
        return {
            "mode": "owner_allowlist",
            "root_count": len(roots),
            "roots": roots,
        }


__all__ = ["DATA_ROOT_ID", "RelevantRootRegistry"]
