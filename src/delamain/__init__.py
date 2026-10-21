"""Delamain-local: the closed action/memory loop for Digital Being.

This package is intentionally small and dependency-free. It contains the
first working vertical slice of the new architecture:

* a path-sandboxed file workspace;
* typed actions with observable results;
* SQLite episodic/semantic memory;
* a runtime that executes a plan and records every step.

The LLM layer is deliberately optional and not imported here. The core must
work without any model at all.
"""

from .actions import Action, ActionError, ActionRegistry
from .memory import MemoryStore
from .models import (
    ActionResult,
    ActionRequest,
    ActionSpec,
    TaskResult,
    utc_now_iso,
)
from .planner import HeuristicPlanner, PlannerError
from .runtime import DelamainRuntime
from .sandbox import Sandbox, SandboxError

__all__ = [
    "Action",
    "ActionError",
    "ActionRegistry",
    "ActionResult",
    "ActionRequest",
    "ActionSpec",
    "DelamainRuntime",
    "HeuristicPlanner",
    "MemoryStore",
    "PlannerError",
    "Sandbox",
    "SandboxError",
    "TaskResult",
    "utc_now_iso",
]
