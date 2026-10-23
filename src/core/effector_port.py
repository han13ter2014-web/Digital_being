"""Core-owned contract between the living core and an action effector.

The core owns identity, goals, time, energy and the autobiographical history.
An effector is allowed to execute only an explicit request; it must not invent
goals, spend resources invisibly or bypass the approval gate.

This module deliberately has no dependency on Delamain.  The concrete adapter
lives in ``src.delamain.effector`` and is injected at the composition root, so
the core can be tested with a fake effector and the optional action layer can
still be imported without the rest of the project.

The contract is intentionally small.  ``cancel`` is not part of it yet: a
cancellation primitive needs one authoritative goal queue, which is the next
integration step rather than a property of the first adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)


class EffectorStatus(str, Enum):
    """Lifecycle state of one effector request."""

    DISABLED = "disabled"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"

    @property
    def terminal(self) -> bool:
        return self in TERMINAL_STATUSES


TERMINAL_STATUSES = frozenset(
    {
        EffectorStatus.SUCCEEDED,
        EffectorStatus.FAILED,
        EffectorStatus.REJECTED,
    }
)

ACTIVE_STATUSES = frozenset(
    {
        EffectorStatus.QUEUED,
        EffectorStatus.RUNNING,
        EffectorStatus.WAITING_APPROVAL,
    }
)


@dataclass(frozen=True)
class EffectorRequest:
    """A durable request to execute an explicit goal.

    ``request_id`` is the idempotency key.  The same id may be submitted more
    than once (for example after a crash) and must resolve to the same durable
    task.  Reusing an id with a different payload is a conflict, not a retry.

    ``plan`` contains normalized action mappings, not Delamain ``ActionRequest``
    objects, so the core contract does not depend on the optional action layer.
    """

    request_id: str
    goal: str
    command: Optional[str] = None
    plan: Sequence[Mapping[str, Any]] = ()
    success_predicate: str = ""
    priority: float = 0.5
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        request_id = str(self.request_id).strip()
        goal = str(self.goal).strip()
        command = (
            str(self.command).strip() if self.command is not None else None
        )
        command = command or None

        if not request_id:
            raise ValueError("request_id must not be empty")
        if not goal:
            raise ValueError("goal must not be empty")
        if bool(command) == bool(self.plan):
            raise ValueError(
                "request needs exactly one of command or explicit plan"
            )

        normalized_plan = []
        for index, step in enumerate(self.plan or ()):
            if not isinstance(step, Mapping):
                raise TypeError(f"plan[{index}] must be a mapping")
            normalized_plan.append(dict(step))

        try:
            priority = float(self.priority)
        except (TypeError, ValueError):
            raise ValueError("priority must be a number") from None
        priority = max(0.0, min(1.0, priority))

        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "goal", goal)
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "plan", tuple(normalized_plan))
        object.__setattr__(self, "success_predicate", str(self.success_predicate))
        object.__setattr__(self, "priority", priority)
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "goal": self.goal,
            "command": self.command,
            "plan": [dict(step) for step in self.plan],
            "success_predicate": self.success_predicate,
            "priority": self.priority,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EffectorResult:
    """Observable state of one effector request.

    ``detail`` is intentionally non-normative.  Callers may use it for
    diagnostics, but the stable decision surface is ``status``, ``ok``,
    ``goal_id`` and ``approval_id``.
    """

    request_id: str
    status: EffectorStatus
    goal_id: Optional[int] = None
    approval_id: Optional[str] = None
    ok: bool = False
    error: Optional[str] = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.status.terminal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "status": self.status.value,
            "goal_id": self.goal_id,
            "approval_id": self.approval_id,
            "ok": bool(self.ok),
            "error": self.error,
            "detail": dict(self.detail),
        }


class EffectorError(RuntimeError):
    """Base class for effector contract violations."""


class EffectorDisabled(EffectorError):
    """The effector or its underlying action layer is disabled."""


class EffectorConflict(EffectorError):
    """A request id was reused with a different payload."""


# A synchronous sink keeps the contract usable from the core loop and from
# tests.  A composition root that owns an asyncio EventBus can schedule the
# publication itself; the adapter must not decide how the host dispatches.
EventSink = Callable[[str, Mapping[str, Any]], None]


@runtime_checkable
class EffectorPort(Protocol):
    """The only surface through which the core may request an action."""

    def submit(self, request: EffectorRequest) -> EffectorResult:
        ...

    def poll(self, request_id: str) -> EffectorResult:
        ...

    def status(self) -> Mapping[str, Any]:
        ...


__all__ = [
    "ACTIVE_STATUSES",
    "EffectorConflict",
    "EffectorDisabled",
    "EffectorError",
    "EffectorPort",
    "EffectorRequest",
    "EffectorResult",
    "EffectorStatus",
    "EventSink",
    "TERMINAL_STATUSES",
]
