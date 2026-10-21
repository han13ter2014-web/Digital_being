"""Data structures shared by the Delamain-local core.

The types in this module are deliberately plain dataclasses. They are easy
to serialize, easy to test and do not depend on any model runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    """Return the current UTC time in a stable, readable ISO-8601 form."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ActionSpec:
    """Machine-readable description of an action.

    The planner (or a future LLM planner) can use this to decide which action
    to call. It is intentionally schema-light: the parameters map names to
    human-readable type descriptions.
    """

    name: str
    description: str
    parameters: Dict[str, str] = field(default_factory=dict)
    dangerous: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": dict(self.parameters),
            "dangerous": self.dangerous,
        }


@dataclass(frozen=True)
class ActionRequest:
    """A single step in a plan."""

    action: str
    args: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"action": self.action, "args": dict(self.args)}


@dataclass
class ActionResult:
    """Outcome of one action invocation."""

    action: str
    ok: bool
    output: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=utc_now_iso)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
            "metadata": dict(self.metadata),
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
        }


@dataclass
class TaskResult:
    """Outcome of a complete task, including every attempted step."""

    task_id: str
    task: str
    ok: bool
    steps: List[ActionResult] = field(default_factory=list)
    final_output: Any = None
    error: Optional[str] = None
    # Normalized requests that were actually attempted. This makes a
    # successful plan reusable as a skill without guessing arguments back
    # from ActionResult (which intentionally does not store them).
    planned_actions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task": self.task,
            "ok": self.ok,
            "steps": [step.to_dict() for step in self.steps],
            "final_output": self.final_output,
            "error": self.error,
            "planned_actions": [dict(step) for step in self.planned_actions],
        }
