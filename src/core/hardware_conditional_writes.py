"""Runtime-only per-life исходы условной записи web_search и explore."""

from __future__ import annotations

from copy import deepcopy
from functools import wraps
from typing import Dict, Optional

from src.core.hardware_storage_writes import storage_write_error_category


_ALLOWED_ACTIONS = frozenset({"web_search", "explore"})
_HISTORY_LIMIT = 50
_PROFILE_CLASSES = frozenset(
    {
        "web_search_standalone_immediate",
        "web_search_standalone_deferred",
        "web_search_no_result",
        "web_search_managed",
        "explore_standalone_external",
        "explore_standalone_internal",
        "explore_managed",
    }
)
_STANDALONE_CLASSES = {
    "web_search": (
        "web_search_standalone_immediate",
        "web_search_standalone_deferred",
        "web_search_no_result",
    ),
    "explore": (
        "explore_standalone_external",
        "explore_standalone_internal",
    ),
}


def _empty_latest() -> Dict:
    return {
        "action": None,
        "profile_class": None,
        "write_disposition": "none",
        "outcome": "unknown",
        "category": "no_observation",
        "cycle": None,
    }


class HardwareConditionalWrites:
    """Связывает только фактический handler и ограниченный исход записи."""

    def __init__(self):
        self.profiles: Dict[str, Dict] = {}
        self.history = []
        self.sample_count = 0
        self.latest = _empty_latest()
        self._active = None

    def begin(self, action: str, *, managed: bool, cycle: int) -> Optional[object]:
        if (
            self._active is not None
            or action not in _ALLOWED_ACTIONS
            or not isinstance(managed, bool)
            or isinstance(cycle, bool)
            or not isinstance(cycle, int)
            or cycle < 0
        ):
            return None
        token = object()
        self._active = {
            "token": token,
            "action": action,
            "managed": managed,
            "cycle": cycle,
            "recorded": False,
        }
        return token

    def record_save(self, disposition: str, error: Optional[BaseException] = None):
        """Принять факт из _save_knowledge_base; без активного действия нет записи."""
        context = self._active
        if context is None or context["recorded"]:
            return deepcopy(self.latest)
        action = context["action"]
        managed = context["managed"]
        if disposition == "managed_only" and managed and error is None:
            profile_class = f"{action}_managed"
            outcome = "not_written"
            category = "managed_snapshot"
        elif disposition == "deferred" and not managed and error is None:
            profile_class = (
                "web_search_standalone_deferred"
                if action == "web_search"
                else "explore_standalone_external"
            )
            outcome = "not_written"
            category = "debounced"
        elif disposition == "immediate" and not managed:
            profile_class = (
                "web_search_standalone_immediate"
                if action == "web_search"
                else "explore_standalone_external"
            )
            outcome = "failed" if error is not None else "succeeded"
            category = storage_write_error_category(error) if error else "written"
        else:
            return deepcopy(self.latest)

        context["recorded"] = True
        return self._record(
            action=action,
            profile_class=profile_class,
            write_disposition=disposition,
            outcome=outcome,
            category=category,
            cycle=context["cycle"],
        )

    def end(self, token: object):
        """Отсутствие вызова save — факт no-write, а не неизвестный успех."""
        context = self._active
        if context is None or context["token"] is not token:
            return deepcopy(self.latest)
        self._active = None
        if context["recorded"]:
            return deepcopy(self.latest)
        action = context["action"]
        if action == "web_search":
            profile_class = "web_search_no_result"
            category = "no_result"
        else:
            profile_class = (
                "explore_managed"
                if context["managed"]
                else "explore_standalone_internal"
            )
            category = "managed_snapshot" if context["managed"] else "internal_only"
        return self._record(
            action=action,
            profile_class=profile_class,
            write_disposition="no_write",
            outcome="not_written",
            category=category,
            cycle=context["cycle"],
        )

    def _record(
        self,
        *,
        action: str,
        profile_class: str,
        write_disposition: str,
        outcome: str,
        category: str,
        cycle: int,
    ) -> Dict:
        if action not in _ALLOWED_ACTIONS or profile_class not in _PROFILE_CLASSES:
            return deepcopy(self.latest)
        entry = {
            "action": action,
            "profile_class": profile_class,
            "write_disposition": write_disposition,
            "outcome": outcome,
            "category": category,
            "cycle": cycle,
        }
        profile = self.profiles.setdefault(
            profile_class,
            {
                "sample_count": 0,
                "write_count": 0,
                "failed_count": 0,
                "latest": _empty_latest(),
            },
        )
        profile["sample_count"] += 1
        profile["write_count"] += int(
            write_disposition == "immediate" and outcome == "succeeded"
        )
        profile["failed_count"] += int(outcome == "failed")
        profile["latest"] = deepcopy(entry)
        self.history.append(deepcopy(entry))
        del self.history[:-_HISTORY_LIMIT]
        self.sample_count += 1
        self.latest = deepcopy(entry)
        return deepcopy(entry)

    def evidence(self, action: str, *, managed: bool) -> Dict:
        """Агрегаты класса кандидата; прошлый success не обещает текущий write."""
        if action not in _ALLOWED_ACTIONS:
            return {
                "profile_class": None,
                "sample_count": 0,
                "write_count": 0,
                "failed_count": 0,
                "write_ratio": 0.0,
            }
        if managed:
            classes = (f"{action}_managed",)
            profile_class = f"{action}_managed"
        else:
            classes = _STANDALONE_CLASSES[action]
            profile_class = f"{action}_standalone_conditional"
        rows = [self.profiles.get(name, {}) for name in classes]
        sample_count = sum(int(row.get("sample_count", 0)) for row in rows)
        write_count = sum(int(row.get("write_count", 0)) for row in rows)
        failed_count = sum(int(row.get("failed_count", 0)) for row in rows)
        return {
            "profile_class": profile_class,
            "sample_count": sample_count,
            "write_count": write_count,
            "failed_count": failed_count,
            "write_ratio": write_count / sample_count if sample_count else 0.0,
        }

    def status(self) -> Dict:
        return {
            "latest": deepcopy(self.latest),
            "sample_count": self.sample_count,
            "profiles": deepcopy(self.profiles),
        }


def conditional_write_action(action: str):
    """Охватывает весь handler; диагностика не меняет его результат или исключение."""

    def decorate(function):
        @wraps(function)
        def wrapped(self, *args, **kwargs):
            observer = getattr(self, "hardware_interoception", None)
            begin = getattr(observer, "begin_conditional_write", None)
            end = getattr(observer, "end_conditional_write", None)
            token = None
            if callable(begin) and callable(end):
                try:
                    token = begin(
                        action,
                        managed=getattr(self, "_profile_managed", False),
                        cycle=getattr(self, "cycle_count", -1),
                    )
                except Exception:
                    token = None
            try:
                return function(self, *args, **kwargs)
            finally:
                if token is not None:
                    try:
                        end(token)
                    except Exception:
                        pass

        return wrapped

    return decorate


__all__ = ["HardwareConditionalWrites", "conditional_write_action"]
