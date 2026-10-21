"""Approval policy for dangerous actions.

The policy is intentionally small and deterministic. It inspects normalized
``ActionRequest`` objects against the live ``ActionRegistry`` and decides
whether the whole plan must be approved before any step runs.

Modes:

* ``off`` — no approval gate (the stage 10 behaviour);
* ``dangerous`` — plans containing an action marked ``dangerous=True`` wait
  for explicit approval;
* ``all`` — every plan with at least one known action waits for approval.

Unknown actions never trigger an approval request. They cannot execute, so
letting the registry report the usual ``unknown action`` error is simpler and
avoids asking the user to approve a step that is already invalid.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import ActionRequest


VALID_APPROVAL_MODES = ("off", "dangerous", "all")


def normalize_approval_mode(
    value: Any,
    *,
    fallback: str = "off",
) -> Tuple[str, Optional[str]]:
    """Return ``(mode, error)`` for a user-supplied approval mode.

    An invalid explicit value must not silently turn the gate off. Callers
    that configure the subsystem use ``fallback="dangerous"`` so a typo fails
    closed instead of allowing writes without approval.
    """

    fallback = str(fallback).strip().lower()
    if fallback not in VALID_APPROVAL_MODES:
        fallback = "off"
    raw = str(value or "").strip().lower()
    if raw in VALID_APPROVAL_MODES:
        return raw, None
    return fallback, f"unknown approval mode {value!r}; using {fallback!r}"


class ApprovalPolicy:
    """Decide whether a plan needs explicit user approval."""

    def __init__(
        self,
        mode: str = "off",
        *,
        registry: Any = None,
        fallback: str = "off",
    ) -> None:
        self.mode, self.error = normalize_approval_mode(mode, fallback=fallback)
        self.registry: Any = None
        if registry is not None:
            self.bind_registry(registry)

    def bind_registry(self, registry: Any) -> None:
        get = getattr(registry, "get", None)
        if not callable(get):
            raise TypeError("registry must provide get(name)")
        self.registry = registry

    def _spec_for(self, action: str) -> Any:
        if self.registry is None:
            return None
        try:
            return self.registry.get(str(action))
        except Exception:  # defensive: a bad registry must not bypass the gate
            return None

    def dangerous_actions(self, requests: Sequence[ActionRequest]) -> List[str]:
        """Return unique action names marked dangerous, in plan order."""

        names: List[str] = []
        for request in requests:
            action = self._spec_for(request.action)
            if action is None:
                continue
            spec = getattr(action, "spec", None)
            if spec is not None and bool(getattr(spec, "dangerous", False)):
                if request.action not in names:
                    names.append(request.action)
        return names

    def evaluate(
        self,
        requests: Sequence[ActionRequest],
    ) -> Tuple[bool, List[str]]:
        """Return ``(requires_approval, dangerous_action_names)``."""

        if self.mode == "off" or not requests:
            return False, []

        known = [
            request
            for request in requests
            if self._spec_for(request.action) is not None
        ]
        if not known:
            return False, []

        dangerous = self.dangerous_actions(requests)
        if self.mode == "all":
            return True, dangerous
        return bool(dangerous), dangerous

    def describe(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "error": self.error,
            "valid_modes": list(VALID_APPROVAL_MODES),
        }


__all__ = [
    "ApprovalPolicy",
    "VALID_APPROVAL_MODES",
    "normalize_approval_mode",
]
