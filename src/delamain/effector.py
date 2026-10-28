"""Delamain implementation of the core's effector contract.

This adapter is deliberately narrow.  It turns an explicit
:class:`src.core.effector_port.EffectorRequest` into one durable Delamain goal,
uses ``effector_request_id`` as the idempotency key and maps the stored goal
state back to the core contract.  It does not create goals from prose, does
not run the goal itself and does not own approvals.

Execution remains in ``DelamainSubsystem`` / ``DelamainRuntime``.  In
standalone mode the subsystem tick is still the driver.  When
``DELAMAIN_EFFECTOR_CORE_DRIVEN`` is enabled, the subsystem tick stops
executing goals and the core calls :meth:`step` at most once per cycle.  This
keeps one goal table, one runtime and one episode history; the core owns the
clock, while Delamain keeps the sandbox and approval gates.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import Any, Dict, List, Mapping, Optional

from src.core.effector_port import (
    EffectorConflict,
    EffectorDisabled,
    EffectorError,
    EffectorRequest,
    EffectorResult,
    EffectorStatus,
    EventSink,
)

try:  # The adapter is also usable without the project config.
    from config.simulation_config import LR_CONFIG
except Exception:  # pragma: no cover - only for standalone imports
    LR_CONFIG = None  # type: ignore[assignment]


def _cfg(name: str, default: Any) -> Any:
    if LR_CONFIG is None:
        return default
    return getattr(LR_CONFIG, name, default)


def _parse_bool(raw: Any) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def _short(value: Any, limit: int = 300) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "..."


class DelamainEffectorAdapter:
    """Expose Delamain as an idempotent effector behind an explicit flag."""

    name = "delamain_effector"
    version = "0.12.0"

    def __init__(
        self,
        subsystem: Any,
        *,
        enabled: Optional[bool] = None,
        event_sink: Optional[EventSink] = None,
    ) -> None:
        self.subsystem = subsystem
        self.enabled = self._resolve_enabled(enabled)
        self.event_sink = event_sink
        self._emitted: set[tuple[str, str, str]] = set()
        self._last_error: Optional[str] = None
        self._last_step_cycle: Optional[int] = None
        self._steps = 0

    @staticmethod
    def _resolve_enabled(enabled: Optional[bool]) -> bool:
        if enabled is not None:
            return bool(enabled)
        raw = os.environ.get("DELAMAIN_EFFECTOR_ENABLED")
        if raw is None:
            return bool(_cfg("DELAMAIN_EFFECTOR_ENABLED", False))
        return _parse_bool(raw)

    @property
    def core_driven(self) -> bool:
        """Whether the core, rather than the subsystem tick, drives this port."""

        return bool(getattr(self.subsystem, "core_driven", False))

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    def submit(self, request: EffectorRequest) -> EffectorResult:
        """Queue one explicit request, idempotently.

        A duplicate ``request_id`` with the same payload returns the current
        state and creates no second goal.  A duplicate id with a different
        payload raises :class:`EffectorConflict`; silently choosing one of two
        intentions would make the autobiography ambiguous.
        """

        if not isinstance(request, EffectorRequest):
            raise TypeError("request must be an EffectorRequest")
        self._require_ready()

        existing = self._find_goal(request.request_id, open_runtime=True)
        if existing is not None:
            if self._goal_fingerprint(existing) != self._request_fingerprint(request):
                raise EffectorConflict(
                    f"request_id {request.request_id!r} already exists with a "
                    "different payload"
                )
            result = self._result_from_goal(request.request_id, existing)
            self._emit_once("effector.duplicate", result)
            return result

        metadata = dict(request.metadata)
        metadata.update(
            {
                "effector_request_id": request.request_id,
                "effector_source": "core",
                "effector_fingerprint": self._request_fingerprint(request),
            }
        )
        try:
            queued = self.subsystem.queue_goal(
                request.goal,
                command=request.command,
                plan=list(request.plan) or None,
                priority=request.priority,
                success_predicate=request.success_predicate,
                metadata=metadata,
            )
        except (TypeError, ValueError) as exc:
            raise EffectorError(f"could not queue effector request: {exc}") from exc

        goal = self.subsystem.get_goal(int(queued["id"]))
        if goal is None:  # defensive: queue_goal just returned this id
            raise EffectorError("queued goal is no longer present")
        result = self._result_from_goal(request.request_id, goal)
        self._emit_once("effector.queued", result)
        return result

    def poll(self, request_id: str) -> EffectorResult:
        """Return the current state of a request without creating anything."""

        request_id = str(request_id).strip()
        if not self.enabled:
            return EffectorResult(
                request_id=request_id,
                status=EffectorStatus.DISABLED,
                error="Delamain effector is disabled",
                detail={"reason": "adapter_disabled"},
            )
        if not request_id:
            return EffectorResult(
                request_id=request_id,
                status=EffectorStatus.NOT_FOUND,
                error="request_id must not be empty",
            )

        goal = self._find_goal(request_id, open_runtime=True)
        if goal is None:
            return EffectorResult(
                request_id=request_id,
                status=EffectorStatus.NOT_FOUND,
                error="request was not found",
            )
        result = self._result_from_goal(request_id, goal)
        self._emit_once(f"effector.{result.status.value}", result)
        return result

    def step(self, cycle: int) -> Optional[EffectorResult]:
        """Advance at most one pending request for one core cycle.

        The method is observational when there is nothing ready.  A disabled
        subsystem, a pending approval, an empty queue or a non-step cycle all
        return ``None``.  The adapter never creates a second worker and never
        bypasses the subsystem's approval gate.

        ``cycle`` is part of the call because the core owns the clock.  A
        repeated call for the same cycle is a no-op, even if a dashboard asks
        the subsystem to tick again.  The configured ``tick_interval`` still
        gates how often a step executes.
        """

        cycle = int(cycle)
        if not self.enabled or not self.subsystem.enabled:
            return None
        if self._last_step_cycle == cycle:
            return None
        self._last_step_cycle = cycle

        try:
            summary = self.subsystem.run_effector_pending(
                trigger="core_effector",
                limit=1,
                cycle=cycle,
            )
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            raise
        if summary is None:
            return None

        goal_id = summary.get("goal_id")
        if goal_id is None:
            return None
        goal = self.subsystem.get_goal(int(goal_id))
        if goal is None:
            return None
        metadata = goal.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        request_id = str(metadata.get("effector_request_id") or "")
        if not request_id:
            return None

        result = self._result_from_goal(request_id, goal)
        budget = summary.get("budget")
        if isinstance(budget, Mapping):
            detail = dict(result.detail)
            detail["budget"] = dict(budget)
            result = replace(result, detail=detail)
        self._steps += 1
        self._emit_once(f"effector.{result.status.value}", result)
        return result

    def status(self) -> Dict[str, Any]:
        """Return a side-effect-free snapshot for diagnostics."""

        counts = {
            EffectorStatus.QUEUED.value: 0,
            EffectorStatus.WAITING_APPROVAL.value: 0,
            EffectorStatus.SUCCEEDED.value: 0,
            EffectorStatus.FAILED.value: 0,
            EffectorStatus.REJECTED.value: 0,
        }
        requests = 0
        if self.subsystem.runtime is not None:
            try:
                goals = self.subsystem.runtime.memory.list_goals()
            except Exception as exc:  # pragma: no cover - defensive
                self._last_error = f"{type(exc).__name__}: {exc}"
                goals = []
            for goal in goals:
                metadata = goal.get("metadata") or {}
                if not isinstance(metadata, Mapping):
                    continue
                if not metadata.get("effector_request_id"):
                    continue
                requests += 1
                result = self._result_from_goal(
                    str(metadata.get("effector_request_id")),
                    goal,
                )
                counts[result.status.value] = counts.get(result.status.value, 0) + 1

        return {
            "name": self.name,
            "version": self.version,
            "enabled": bool(self.enabled),
            "core_driven": self.core_driven,
            "subsystem_enabled": bool(self.subsystem.enabled),
            "runtime_ready": self.subsystem.runtime is not None,
            "requests": requests,
            "by_status": counts,
            "steps": self._steps,
            "last_step_cycle": self._last_step_cycle,
            "last_error": self._last_error,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_ready(self) -> None:
        if not self.enabled:
            raise EffectorDisabled("Delamain effector is disabled")
        if not self.subsystem.enabled:
            raise EffectorDisabled("Delamain subsystem is disabled")

    def _goals(self, *, open_runtime: bool) -> List[Dict[str, Any]]:
        if self.subsystem.runtime is None:
            if not open_runtime or not self.subsystem.enabled:
                return []
            # The public list_goals() creates the runtime when the subsystem
            # is enabled; status() deliberately does not use this path.
            return self.subsystem.list_goals()
        return self.subsystem.runtime.memory.list_goals()

    def _find_goal(
        self,
        request_id: str,
        *,
        open_runtime: bool,
    ) -> Optional[Dict[str, Any]]:
        for goal in self._goals(open_runtime=open_runtime):
            metadata = goal.get("metadata") or {}
            if not isinstance(metadata, Mapping):
                continue
            if str(metadata.get("effector_request_id") or "") == request_id:
                return goal
        return None

    @staticmethod
    def _payload_for_request(request: EffectorRequest) -> Dict[str, Any]:
        return {
            "goal": request.goal,
            "command": request.command,
            "plan": [dict(step) for step in request.plan],
            "success_predicate": request.success_predicate,
            "priority": request.priority,
        }

    @classmethod
    def _request_fingerprint(cls, request: EffectorRequest) -> str:
        return json.dumps(
            cls._payload_for_request(request),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    @staticmethod
    def _goal_fingerprint(goal: Mapping[str, Any]) -> str:
        metadata = goal.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        stored = metadata.get("effector_fingerprint")
        if stored:
            return str(stored)
        payload = {
            "goal": goal.get("title"),
            "command": metadata.get("command"),
            "plan": metadata.get("plan") or [],
            "success_predicate": goal.get("success_predicate") or "",
            "priority": goal.get("priority", 0.5),
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    def _result_from_goal(
        self,
        request_id: str,
        goal: Mapping[str, Any],
    ) -> EffectorResult:
        metadata = goal.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            metadata = {}

        goal_status = str(goal.get("status") or "pending")
        approval_status = metadata.get("approval_status")
        approval_id = metadata.get("approval_id") or metadata.get("last_approval_id")
        if approval_id and self.subsystem.runtime is not None:
            approval = self.subsystem.runtime.memory.get_approval(str(approval_id))
            if approval is not None:
                approval_status = approval.get("status") or approval_status

        if goal_status == "done":
            status = EffectorStatus.SUCCEEDED
            ok = True
        elif goal_status == "failed":
            if approval_status == "rejected":
                status = EffectorStatus.REJECTED
            else:
                status = EffectorStatus.FAILED
            ok = False
        elif approval_status == "pending":
            status = EffectorStatus.WAITING_APPROVAL
            ok = False
        elif approval_status == "rejected":
            status = EffectorStatus.REJECTED
            ok = False
        else:
            status = EffectorStatus.QUEUED
            ok = False

        error = metadata.get("last_error")
        if status is EffectorStatus.WAITING_APPROVAL and not error:
            error = "approval required"
        if status is EffectorStatus.SUCCEEDED:
            error = None

        return EffectorResult(
            request_id=request_id,
            status=status,
            goal_id=int(goal["id"]),
            approval_id=str(approval_id) if approval_id else None,
            ok=ok,
            error=_short(error),
            detail={
                "goal_status": goal_status,
                "approval_status": approval_status,
                "attempts": metadata.get("attempts", 0),
                "retry_scheduled": bool(metadata.get("retry_scheduled")),
                "last_error": _short(metadata.get("last_error")),
                "activity": metadata.get("activity"),
                "metadata": dict(metadata),
                "intention_id": metadata.get("intention_id"),
                "target": metadata.get("target"),
                "core_cycle": metadata.get("core_cycle"),
            },
        )

    def _emit_once(self, name: str, result: EffectorResult) -> None:
        if self.event_sink is None:
            return
        key = (name, result.request_id, result.status.value)
        if key in self._emitted:
            return
        self._emitted.add(key)
        try:
            self.event_sink(name, result.to_dict())
        except Exception as exc:  # a diagnostics sink must not break action
            self._last_error = f"{type(exc).__name__}: {exc}"


__all__ = ["DelamainEffectorAdapter"]
