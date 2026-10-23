"""Core-owned driver for pending effector requests.

The core owns the clock.  In integrated mode this small driver is the only
place that advances an effector request: ``DigitalBeing.tick_subsystems()``
calls :meth:`EffectorDriver.tick` once per cycle, and the driver calls the
effector's ``step()`` at most once for that cycle.

The driver deliberately does not know Delamain, approval or goals.  It only
guards the cycle boundary, contains failures and reports the result in a form
that the core can publish.  The concrete effector remains responsible for its
own durable state and its mandatory sandbox/approval checks.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from src.core.effector_port import EffectorResult


class EffectorDriver:
    """Drive at most one pending effector request per core cycle."""

    name = "core_effector_driver"
    version = "0.1.0"

    def __init__(self, effector: Any, *, enabled: bool = True) -> None:
        self.effector = effector
        self.enabled = bool(enabled)
        self._last_cycle: Optional[int] = None
        self._steps = 0
        self._last_error: Optional[str] = None
        self._last_result: Optional[EffectorResult] = None

    def tick(self, cycle: int) -> Dict[str, Any]:
        """Advance the effector at most once for ``cycle``.

        A duplicate call for the same cycle is a no-op.  This keeps the core
        loop safe when a dashboard or test calls ``tick_subsystems`` more than
        once while the core cycle has not advanced.
        """

        cycle = int(cycle)
        if not self.enabled:
            return self._report(cycle, skipped="disabled")
        if not getattr(self.effector, "enabled", True):
            return self._report(cycle, skipped="effector_disabled")
        if self._last_cycle == cycle:
            return self._report(cycle, skipped="duplicate_cycle")

        self._last_cycle = cycle
        step = getattr(self.effector, "step", None)
        if not callable(step):
            self._last_error = "effector has no callable step()"
            return self._report(cycle, skipped="unsupported")

        try:
            result = step(cycle)
        except Exception as exc:  # a broken action layer must not stop life
            self._last_error = f"{type(exc).__name__}: {exc}"
            return self._report(cycle, skipped="error")

        if result is None:
            return self._report(cycle, skipped="no_pending")

        self._steps += 1
        self._last_result = result
        return self._report(cycle, skipped=None, result=result)

    def status(self) -> Dict[str, Any]:
        """Return a side-effect-free diagnostic snapshot."""

        return {
            "name": self.name,
            "version": self.version,
            "enabled": bool(self.enabled),
            "effector_enabled": bool(getattr(self.effector, "enabled", False)),
            "steps": self._steps,
            "last_cycle": self._last_cycle,
            "last_error": self._last_error,
            "last_result": (
                self._last_result.to_dict()
                if self._last_result is not None
                else None
            ),
        }

    def _report(
        self,
        cycle: int,
        *,
        skipped: Optional[str],
        result: Optional[EffectorResult] = None,
    ) -> Dict[str, Any]:
        payload = None
        if result is not None:
            if isinstance(result, Mapping):
                payload = dict(result)
            elif hasattr(result, "to_dict"):
                payload = result.to_dict()
            else:  # defensive: a fake effector may return a plain object
                payload = {"value": str(result)}
        return {
            "cycle": cycle,
            "enabled": bool(self.enabled),
            "skipped": skipped,
            "result": payload,
        }


__all__ = ["EffectorDriver"]
